# httpware deep audit — 2026-06-07

**Status:** in progress
**Spec:** [planning/specs/2026-06-07-deep-audit-design.md](../specs/2026-06-07-deep-audit-design.md)
**Plan:** [planning/plans/2026-06-07-deep-audit-plan.md](../plans/2026-06-07-deep-audit-plan.md)

## Summary

_Counts updated after final merge._

- Blockers: —
- High: —
- Medium: —
- Low: —
- Nits: —

<!-- chunk sections appended below in order: 1, 2, 3, 4 -->

## Chunk 1 — Correctness (from dry-run smoke test)

5 confirmed correctness findings reviewed, 5 survived verifier consensus, dominant area is the resilience retry middleware (4/5 land in `middleware/resilience/`, the fifth in `client.py`). The cluster points at a single subsystem — Finagle-style retry budgeting and the retry decision tree — where small arithmetic and ordering bugs compound into materially different behavior than documentation implies. No blockers; the bar between low and medium turns on whether default settings expose the defect to typical users, and in each case a non-default knob (floor=0, max_delay much smaller than server Retry-After, custom retry_methods) is required to observe the bug. Triaged into 3 low + 2 nit.

### Low

#### RetryBudget deposit fires per attempt instead of per original request

`src/httpware/middleware/resilience/retry.py:105`

`deposit()` lives inside the per-attempt `for` loop, so a request that retries twice contributes three deposits and two withdrawals. The Finagle budget contract is `withdrawals / deposits <= percent_can_retry` where the denominator counts original requests; inflating it lets through ~2x the configured retry rate when every request retries. The identical placement is present in the sync `Retry` class at line 236.

```python
        for attempt in range(self.max_attempts):
            is_last = attempt + 1 >= self.max_attempts
            self.budget.deposit()
            try:
                return await next(request)
            except StatusError as exc:
                retryable_status = exc.response.status_code in self.retry_status_codes
                if not method_eligible or not retryable_status:
                    if retryable_status and request.extensions.get(STREAMING_BODY_MARKER):
                        exc.add_note(_STREAMING_BODY_REFUSAL_NOTE)
                    raise
                last_exc = exc
                last_response = exc.response
```

Verifier consensus: 2/3 (code_reality + reproducer). Suggested direction: hoist `self.budget.deposit()` above the loop so it runs exactly once per call to the middleware; mirror the change in `Retry`.

#### Retry-After silently capped to max_delay

`src/httpware/middleware/resilience/retry.py:189`

When `respect_retry_after=True` and a server responds with `Retry-After: 120` while the client is configured with `max_delay=5.0`, the computed delay collapses to `min(120, 5.0) = 5.0` and the retry fires after 5 s — almost certainly receiving the same 429/503 again and burning an attempt. The option name implies the header is honored; in practice it is silently overridden by `max_delay`. Affects async and sync paths identically.

```python
            if retry_after is not None:
                delay = min(retry_after, self.max_delay)
            else:
                delay = full_jitter_delay(
                    attempt,
                    base_delay=self.base_delay,
                    max_delay=self.max_delay,
                )
```

Verifier consensus: 2/3 (code_reality confirmed twice). Suggested direction: when `retry_after > max_delay`, choose explicitly — either give up (and raise the underlying `StatusError` with a note explaining the Retry-After exceeded the cap) or document that `respect_retry_after` is bounded by `max_delay`. Whichever path is chosen, surface the decision in docs and the docstring.

#### RetryBudget ceiling truncates rather than rounds

`src/httpware/middleware/resilience/budget.py:67`

`ceiling = int(len(self._deposits) * self._percent_can_retry) + floor` truncates instead of rounding, so 4 deposits at `percent_can_retry=0.2` yield `int(0.8) = 0`. With the default `floor` (from `min_retries_per_sec=100`) this is invisible, but with `floor=0` and low traffic the budget refuses every retry until the deposit count crosses the next integer threshold. This is an off-by-one against the configured percentage for any deposit count not a clean multiple of `1 / percent_can_retry`.

```python
    def try_withdraw(self) -> bool:
        now = self._now()
        with self._lock:
            self._purge(now)
            floor = int(self._min_retries_per_sec * self._ttl)
            ceiling = int(len(self._deposits) * self._percent_can_retry) + floor
            if len(self._withdrawn) >= ceiling:
                return False
            self._withdrawn.append(now)
            return True
```

Verifier consensus: 2/3 (code_reality + reproducer). Suggested direction: replace `int(...)` with `math.ceil(...)` so the configured percentage is reached at the first deposit-count where it is mathematically expressible, and add a Hypothesis property that asserts `withdrawals / deposits` stays close to `percent_can_retry` within `±1/deposits`.

### Nit

#### Streaming-body refusal note attached when method ineligibility is the gating reason

`src/httpware/middleware/resilience/retry.py:111`

Inside the `if not method_eligible or not retryable_status:` early-out, the streaming-body note is added whenever `retryable_status and request.extensions.get(STREAMING_BODY_MARKER)` — even when the actual reason for not retrying is that the method is excluded from `retry_methods`. A `POST` with a streaming body that gets a 503 receives a note saying the stream cannot replay, when the real fix is to add `POST` to `retry_methods`. Same pattern in `Retry` at lines 242 and the `NetworkError`/`TimeoutError` arm at 249.

```python
            except StatusError as exc:
                retryable_status = exc.response.status_code in self.retry_status_codes
                if not method_eligible or not retryable_status:
                    if retryable_status and request.extensions.get(STREAMING_BODY_MARKER):
                        exc.add_note(_STREAMING_BODY_REFUSAL_NOTE)
                    raise
                last_exc = exc
                last_response = exc.response
            except (NetworkError, TimeoutError) as exc:
                if not method_eligible:
                    if request.extensions.get(STREAMING_BODY_MARKER):
                        exc.add_note(_STREAMING_BODY_REFUSAL_NOTE)
                    raise
```

Verifier consensus: 2/3 (code_reality + reproducer). Suggested direction: only attach the streaming-body note when the method *is* eligible and the status *is* retryable — i.e., move the note into the branch where streaming is the actual blocker. Otherwise emit a different note that names the real reason, or omit the note.

#### RuntimeError mapping to TransportError uses substring match on "closed"

`src/httpware/client.py:135`

`if "closed" in str(exc)` is a substring check against an external library's error string. Any `RuntimeError` whose message happens to contain "closed" — from any transport layer, plugin, or future httpx2 change — gets converted to `TransportError`; conversely, if httpx2 rewords the message ("shut down", "disposed", etc.) the typed mapping silently breaks and a raw `RuntimeError` escapes to the caller. Same pattern in sync `Client._terminal`.

```python
    async def _terminal(self, request: httpx2.Request) -> httpx2.Response:
        try:
            async with _httpx2_exception_mapper():
                response = await self._httpx2_client.send(request)
        except RuntimeError as exc:
            if "closed" in str(exc):
                raise TransportError(str(exc)) from exc
            raise
        _raise_on_status_error(response)
        return response
```

Verifier consensus: 2/3 (code_reality + reproducer). Suggested direction: gate the mapping on a more stable signal — check `self._httpx2_client.is_closed` (or whatever the public API exposes) before the call, or whitelist the message via a single module-level constant that lives next to a test asserting the current httpx2 wording.

<!-- chunk 1: concurrency + error_contract appended below by targeted run -->

## Chunk 1 — Concurrency & Error Contract

5 confirmed findings reviewed across the concurrency and error-contract dimensions; 5 survived verifier consensus. The dominant cluster is `AsyncBulkhead` cross-event-loop behavior (2/5 findings) and the surrounding test coverage that does not catch it (3/5). No `error_contract` defects surfaced in this chunk — all five lie in `middleware/resilience/bulkhead.py` and its tests, plus one weak post-condition in `tests/test_threading_with_shared_budget.py` that touches the RetryBudget threading harness. Triaged into 2 medium + 1 low + 2 nit. None reach blocker or high because the AsyncBulkhead defect requires the user to share a single instance across multiple event loops in different threads — a configuration the existing docs do not endorse but also do not warn against.

### Medium

#### AsyncBulkhead deadlocks when shared across event loops in different threads

`src/httpware/middleware/resilience/bulkhead.py:61`

`AsyncBulkhead` stores a single `asyncio.Semaphore` constructed at `__init__`, which binds to whichever loop is running at construction time (or the first acquirer). When loop A's `release()` calls `_wake_up_next()` and that waiter belongs to loop B in another thread, `fut.set_result()` reaches into loop B's machinery via `call_soon` — which is not thread-safe — and the wake-up is lost. With two threads each running `asyncio.run()` against one shared `AsyncBulkhead(max_concurrent=1)`, the second thread hangs indefinitely with `_sem._value == 0`.

```python
        self._sem = asyncio.Semaphore(max_concurrent)
```

Verifier consensus: 2/3 (code_reality + reproducer). Suggested direction: either document that `AsyncBulkhead` is single-event-loop and detect the violation eagerly (capture the loop on first acquire, raise on mismatch), or replace the bare `asyncio.Semaphore` with a thread-safe primitive (e.g., guard a counter with `threading.Lock` + per-loop futures). The cheap fix is detect-and-raise; the deep fix is a cross-loop-safe primitive.

#### AsyncBulkhead docstring advertises sharing without flagging the single-event-loop constraint

`src/httpware/middleware/resilience/bulkhead.py:10`

The module docstring tells users to share one `AsyncBulkhead` across multiple `AsyncClient(middleware=[shared])` calls "to enforce a joint cap" but says nothing about the loop boundary. The sibling sync `Bulkhead` class docstring at line 101 correctly warns that it is "per-world" and cannot be shared between `Client` and `AsyncClient`; no analogous caveat exists for `AsyncBulkhead` against sharing across multiple `asyncio.run()` calls or threads. A reader following the docs and reusing one instance across pytest async tests (each in its own loop) will hit the silent deadlock described above.

```python
AsyncBulkhead is the sharable unit — pass the same instance to multiple
AsyncClient(middleware=[shared]) calls to enforce a joint cap across clients.
```

Verifier consensus: 2/3 (code_reality + reproducer). Suggested direction: add a "Constraints" paragraph mirroring the sync class's "per-world" wording — explicitly state that all sharing must happen on a single event loop, and link to whatever runtime check is added for the finding above. Keep this fix and the runtime-detect fix in the same PR so the doc never drifts ahead of the code.

### Low

#### Sync `Bulkhead` has no Hypothesis property test for the concurrency-cap invariant

`tests/test_bulkhead_props.py:1`

The property suite verifies "observed in-flight count never exceeds `max_concurrent`" only for `AsyncBulkhead`, via `asyncio.gather`. The sync `Bulkhead` has a single deterministic check (`tests/test_bulkhead_sync.py::test_serializes_at_capacity` with `max_concurrent=1` and 3 threads) but no Hypothesis-driven search across the `(max_concurrent, n_requests)` space. Sync/async parity is a stated invariant for the resilience primitives, and the async side carries proportionally stronger evidence today.

```python
"""Hypothesis property tests for AsyncBulkhead.

Properties verified:
1. Observed in-flight count never exceeds max_concurrent under any interleaving.
```

Verifier consensus: 2/3 (code_reality twice). Suggested direction: add `tests/test_bulkhead_sync_props.py` that mirrors the async property suite using `threading.Thread` + a shared counter, parameterized by Hypothesis over `max_concurrent ∈ [1, 8]` and `n_requests ∈ [max_concurrent, max_concurrent * 4]`. Keep the async file unchanged; parity is the goal.

### Nit

#### `test_no_slot_leak_after_drain` asserts against `asyncio.Semaphore._value`

`tests/test_bulkhead_props.py:113`

The post-condition reads `bulkhead._sem._value`, a CPython implementation detail of `asyncio.Semaphore` (not part of the public asyncio surface). The comment acknowledges the trade-off ("implementation detail but reliable across CPython 3.11+"), but the assertion would silently change meaning on PyPy or on any CPython refactor that renames or removes the attribute. A behavioral check — submit one more request after drain and assert it completes within a small timeout — is portable and exercises the same release-correctness invariant.

```python
assert bulkhead._sem._value == max_concurrent  # noqa: SLF001
```

Verifier consensus: 2/3 (code_reality twice). Suggested direction: replace the `_value` peek with a behavioral assertion (submit `max_concurrent` more requests against the drained bulkhead under a tight `acquire_timeout` and confirm all succeed), which both removes the SLF001 suppression and survives any future asyncio internals change.

#### `test_threading_with_shared_budget` only asserts the deposit deque is non-empty

`tests/test_threading_with_shared_budget.py:77`

After 4 sync threads run 50 ops × 2 attempts and 20 async tasks run 2 attempts against a shared `RetryBudget(min_retries_per_sec=1000, percent_can_retry=0.5)`, the post-condition is `len(budget._deposits) > 0`. That assertion would pass even if the internal lock were removed and the deque corrupted as long as one survivor remained. The exact expected count — `(4 * 50 * 2) + (20 * 2) = 440` — is computable; the sibling test `tests/test_retry_budget_threadsafety.py::test_concurrent_only_deposit_count_matches` already establishes the pattern.

```python
assert len(budget._deposits) > 0  # noqa: SLF001
```

Verifier consensus: 2/3 (code_reality twice). Suggested direction: tighten the assertion to the exact expected total (or the exact total minus any TTL-purged deposits, computed from the test clock), matching the stricter post-condition used in the existing thread-safety suite. The current weak check effectively only guards against catastrophic failure.


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

## Chunk 2 — Public API & Optional Extras

8 confirmed findings reviewed across the public-api, correctness, and testing dimensions, all 8 survived verifier consensus. The dominant cluster is optional-extras isolation (3/8 findings — `pydantic.py`, `import_checker.py`, `observability.py`) where the lazy-import / fail-fast contract is brittle in ways the current tests don't exercise; the second cluster is public-API surface (3/8 — `chain.py` TYPE_CHECKING block, `compose`/`compose_async` not re-exported, README/index landing pages stale on sync `Client`). Two findings are testing gaps (one-directional `__all__` assertion, missing sync escape-hatch test). No blockers, no high; triaged into 1 medium + 5 low + 2 nit. The medium is the `compose` import path advertised in `docs/middleware.md` but absent from any `__init__.py` — every other finding lands at low because it requires either a partial-install edge or a non-default code path to observe.

### Medium

#### `compose` / `compose_async` documented as public imports but not re-exported

`docs/middleware.md:145`

The middleware guide instructs users to write `from httpware.middleware.chain import compose`, but neither `compose` nor `compose_async` appears in `httpware.middleware.__init__`, in the package-root `__all__`, or in any `__all__` anywhere — `chain.py` is a private implementation module. Either the symbols must be promoted (added to `httpware.middleware.__init__` and `__all__`) or the docs example must be removed and replaced with a note that chain composition is automatic via `AsyncClient`/`Client`. The current state breaks the project's "absolute imports through the public surface" convention from inside the docs.

```python
from httpware.middleware.chain import compose
```

Verifier consensus: 2/3 (code_reality + reproducer — `grep -rn 'compose' src/httpware/__init__.py src/httpware/middleware/__init__.py` returns zero matches). Suggested direction: decide whether manual chain composition is a supported user workflow. If yes, re-export both functions from `httpware.middleware` (and add them to the package-root `__all__` with a public-API test peer), update `tests/test_public_api.py::test_expected_exports`, and keep the doc snippet. If no, replace the snippet with a one-sentence note that chain composition is owned by `AsyncClient`/`Client` and not part of the public API.

### Low

#### `chain.py` uses `if typing.TYPE_CHECKING` — `get_type_hints()` raises NameError

`src/httpware/middleware/chain.py:9`

`compose_async` and `compose` use forward-reference string annotations referencing `AsyncMiddleware` / `Middleware`, which are imported only under a `if typing.TYPE_CHECKING:` block. Calling `typing.get_type_hints(compose_async)` at runtime raises `NameError: name 'AsyncMiddleware' is not defined` — and this also violates the project memory rule "Drop reflexive `if TYPE_CHECKING:` blocks". The unconditional import is safe here because `httpware.middleware.__init__` does not import `chain.py` back.

```python
if typing.TYPE_CHECKING:
    from httpware.middleware import AsyncMiddleware, Middleware
```

Verifier consensus: 2/3 (code_reality + reproducer — `python -c "import typing; from httpware.middleware.chain import compose_async; typing.get_type_hints(compose_async)"` raises NameError). Suggested direction: hoist `from httpware.middleware import AsyncMiddleware, Middleware` to module top-level; drop the TYPE_CHECKING guard entirely.

#### `docs/index.md` and `README.md` describe httpware as "async" — stale after 0.8.0 sync Client

`docs/index.md:3`

Both `docs/index.md` (line 3) and `README.md` (line 8) open by calling httpware an "async HTTP client framework" and the resilience teaser mentions only `AsyncRetry` + `AsyncBulkhead`. The 0.8.0 release added sync `Client`, `Retry`, and `Bulkhead` (all in `__all__` and fully tested), but a reader scanning either landing page sees no sync surface until they open `docs/resilience.md`. The README's "With resilience middleware" code block (line ~75) imports only the async primitives.

```text
A Python async HTTP client framework for building resilient service clients. `httpware` is a thin opinionated wrapper around `httpx2` — it re-exports `httpx2.Request`/`httpx2.Response` as the public request/response surface, adds a middleware chain (with a built-in resilience suite: `AsyncRetry` + `RetryBudget`, `AsyncBulkhead`), opt-in typed response decoding, and a status-keyed exception tree raised automatically on 4xx/5xx.
```

Verifier consensus: 2/3 (code_reality + spec_grounded). Suggested direction: replace the opening sentence with something neutral (e.g., "A Python HTTP client framework with sync and async clients...") and add the sync primitives (`Client`, `Retry`, `Bulkhead`) to the resilience teaser in both files. Mirror the change in the README's code block by showing one sync and one async example, or by linking to the resilience doc for both. Additional evidence (chunk 4): `README.md:10` ("resilience suite — `AsyncRetry` … plus an `AsyncBulkhead`") is the same async-only framing and should be revised in the same pass.

#### `pydantic.py` references `TypeAdapter` at runtime without binding it when the import was skipped

`src/httpware/decoders/pydantic.py:27`

`_get_adapter` and the `TypeError` fallback inside `decode()` both call `TypeAdapter(model)` as a bare name — it is bound only by the conditional `from pydantic import TypeAdapter` at line 16, which itself is gated on `is_pydantic_installed` evaluated at module-load time. If the module is imported when `is_pydantic_installed=False` (e.g., in a test that monkeypatches the flag and reloads the module), `TypeAdapter` is never defined and a later call raises `NameError`, not the clean `ImportError` the contract promises. The `try/except TypeError` on line 42 catches one path but leaves `NameError` unhandled.

```python
@functools.lru_cache(maxsize=1024)
def _get_adapter(model: type[T]) -> "TypeAdapter[T]":
    return TypeAdapter(model)

    def decode(self, content: bytes, model: type[T]) -> T:
        try:
            adapter = _get_adapter(model)
        except TypeError:
            adapter = TypeAdapter(model)
```

Verifier consensus: 2/3 (code_reality + reproducer — reload the module with `is_pydantic_installed=False`, then `_get_adapter(int)` raises `NameError`). Suggested direction: either import `TypeAdapter` unconditionally at module top (the module is already gated by the `_default_pydantic_decoder()` fail-fast in `client.py`), or wrap `_get_adapter` with an explicit guard that raises a clean `ImportError` referencing the `pydantic` extra. The current shape leaves a NameError window for anyone who reloads or imports the module outside the normal fail-fast path.

#### `import_checker.find_spec('opentelemetry')` is unreliable for a namespace package

`src/httpware/_internal/import_checker.py:8`

`is_otel_installed = find_spec('opentelemetry') is not None` detects the `opentelemetry` namespace, not `opentelemetry-api` specifically. `opentelemetry` is a PEP 420 native namespace: any `opentelemetry-instrumentation-*` package creates the directory even when `opentelemetry-api` is absent. In that case `find_spec` returns a non-None spec and `is_otel_installed` is True, so the lazy `from opentelemetry import trace` in `observability.py` raises an uncaught `ImportError` (see the paired finding below).

```python
is_otel_installed = find_spec("opentelemetry") is not None
```

Verifier consensus: 2/3 (code_reality + reproducer — install any `opentelemetry-instrumentation-*` package without `opentelemetry-api`; `is_otel_installed` becomes True but the lazy import fails). Suggested direction: probe a specific module that requires the api package — `find_spec("opentelemetry.trace")` is the cheapest correct check. Pair with the observability fix below so the same release closes both ends of the partial-install hole.

#### `observability._emit_event` does not wrap the lazy OTel import in try/except

`src/httpware/_internal/observability.py:40`

`_emit_event` gates the OTel path on `if import_checker.is_otel_installed` but does not wrap the lazy `from opentelemetry import trace` in `try/except ImportError`. If `is_otel_installed` is True but the import fails (the namespace-package false-positive above, or a broken otel install), the `ImportError` escapes `_emit_event` and propagates to the Retry/Bulkhead middleware that called it — crashing a live request cycle with an unrelated infrastructure error. The "lazy by design (optional-extras isolation)" comment acknowledges the intent but not the failure mode.

```python
    if import_checker.is_otel_installed:
        from opentelemetry import trace  # noqa: PLC0415 — lazy by design (optional-extras isolation)

        trace.get_current_span().add_event(event_name, attributes=attributes)
```

Verifier consensus: 2/3 (code_reality + reproducer). Suggested direction: wrap the lazy import (and the `add_event` call) in `try/except ImportError` and degrade to the structured-log-only path, mirroring the contract the docstring already implies. Combined with the `find_spec("opentelemetry.trace")` fix above, this turns the partial-install scenario from a crash into the documented soft fallback.

### Nit

#### `test_expected_exports` is one-directional — new `__all__` entries silently escape coverage

`tests/test_public_api.py:69`

`test_expected_exports` checks `expected - __all__` (symbols the test enumerates that are missing from `__all__`) but not the reverse — symbols added to `__all__` without a matching update to the expected set pass the test unchecked. `test_all_exports_resolve` only catches symbols that don't exist at all; a real but unintended export slips through.

```python
missing = expected - set(httpware.__all__)
assert not missing, f"expected exports missing from __all__: {missing}"
```

Verifier consensus: 2/3 (code_reality + reproducer — adding a bogus existing symbol to `__all__` does not trip the test). Suggested direction: use a symmetric-difference assertion (`assert expected == set(httpware.__all__)`) so both directions are guarded, and treat `__all__` and the expected set as a single declarative contract.

#### `tests/test_optional_extras_pydantic_missing.py` covers `AsyncClient` only — no sync `Client` peer

`tests/test_optional_extras_pydantic_missing.py:41`

`test_async_client_accepts_explicit_decoder_without_pydantic` verifies that an explicit `decoder=` bypasses the pydantic fail-fast. There is no equivalent test for the sync `Client`, even though both `AsyncClient.__init__` and `Client.__init__` share the same `_default_pydantic_decoder()` logic (`client.py:126` and `client.py:819`). The bypass exists for both classes but only the async path is asserted.

```python
def test_async_client_accepts_explicit_decoder_without_pydantic() -> None:
    """An explicit decoder= escapes the fail-fast even when pydantic is 'missing'."""
    ...
    with patch("httpware._internal.import_checker.is_pydantic_installed", False):
        client = AsyncClient(decoder=_FakeDecoder())
        assert client is not None
```

Verifier consensus: 2/3 (code_reality + reproducer). Suggested direction: add a `test_sync_client_accepts_explicit_decoder_without_pydantic` peer in the same file, or parameterize the existing test over `(AsyncClient, Client)` so the sync/async parity invariant for the fail-fast escape hatch is asserted symmetrically.

## Chunk 4 — Docs & Planning-Doc Staleness

14 confirmed findings reviewed across `docs/` and `planning/` plus a few cross-file echoes; 13 surfaced as net-new (one — README's async-only resilience framing — folded into the existing Chunk 2 finding for `docs/index.md:3` / `README.md:8`). The dominant cluster is post-0.8.0 staleness: 8 of the 13 net-new findings are the Async\* rename and the sync `Client`/`Retry`/`Bulkhead` additions not yet propagated through the doc surface (CLAUDE.md module layout, two of three Protocol Seams, the testing-pattern example, `engineering.md` §1 future tense, `engineering.md` §8 `attempt_timeout` and closing paragraph, `docs/resilience.md` "three primitives" intro, `docs/index.md` observability paragraph naming only async middlewares). The remaining 5 split into one factual reversal (`docs/resilience.md` "Single-thread assumption" section claiming the budget is *not* thread-safe when it is), one broken doc reproducer (`docs/testing.md` code block missing the `AsyncRetry` import), one cross-convention example (`LoggingMiddleware` taught with `print()`), and two stale internal cross-references (`decoders/__init__.py` "Seam 3" label, `engineering.md` §8 epic-closure paragraph). Triaged into 1 high + 1 medium + 6 low + 2 nit (5 stale-doc nits collapsed into one rolled-up entry per the spec). No blockers — the high item is wrong-direction documentation, not broken code; the medium is a non-runnable example, not an API defect.

### High

#### `docs/resilience.md` "Single-thread assumption" section is the exact opposite of what RetryBudget guarantees

`docs/resilience.md:103`

The "Single-thread assumption" header and its body tell users `RetryBudget` is asyncio-only and that cross-thread use is out of scope, but `RetryBudget` is implemented with a `threading.Lock` and the module docstring explicitly advertises "Thread-safe and asyncio-safe: all mutations go through a threading.Lock." The same `docs/resilience.md` file even contradicts itself at line 173, where it correctly describes `RetryBudget` as "safe to share across sync and async clients in the same process". A reader of the "Sharing across clients" guidance who hits the earlier "wrap calls in a lock yourself" instruction will either add a redundant lock or back away from a fully supported pattern.

```text
### Single-thread assumption

`RetryBudget` is asyncio-aware — deque mutations between await points are atomic on a single event loop. Cross-thread use is out of scope; if you need that, wrap calls in a lock yourself.
```

Verifier consensus: 2/3 (code_reality + spec_grounded — `src/httpware/middleware/resilience/budget.py` module docstring, the `self._lock = threading.Lock()` in `__init__`, and the existing `tests/test_retry_budget_threadsafety.py` / `tests/test_threading_with_shared_budget.py` all confirm the budget is thread-safe). Suggested direction: delete the "Single-thread assumption" section in `docs/resilience.md` outright and replace it with a one-paragraph "Thread safety" note that mirrors the budget module docstring (`threading.Lock` guards all mutations; safe to share across `Client` and `AsyncClient` in the same process). Cross-link this to the existing line-173 paragraph so the file no longer contradicts itself.

### Medium

#### `docs/testing.md` "Recording / stateful handlers" code block uses `AsyncRetry` without importing it

`docs/testing.md:77`

The example asynchronous test at lines 58–94 instantiates `AsyncRetry(base_delay=0.001, max_delay=0.002)` but the file's import section only pulls in `from httpware import AsyncClient` (line 12) and `from httpware import Client` (line 40). Copying the code block into a fresh file as the testing doc invites the reader to do raises `NameError: name 'AsyncRetry' is not defined`. The lower-status nature (medium not high) reflects that the fix is a one-line import addition, but it's a paste-and-it-fails example in the doc that exists specifically to teach a paste-and-run pattern.

```python
async def test_retry_succeeds_after_503() -> None:
    handler = _ResponseSequence([HTTPStatus.SERVICE_UNAVAILABLE, HTTPStatus.OK])
    transport = httpx2.MockTransport(handler)
    async with AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=transport),
        middleware=[AsyncRetry(base_delay=0.001, max_delay=0.002)],
    ) as client:
```

Verifier consensus: 2/3 (code_reality + reproducer). Suggested direction: add `from httpware import AsyncRetry` to the imports block of the snippet (next to the existing `from httpware import AsyncClient`). If the file already has other "Recording" examples that share imports, hoist a single combined imports block to the top of the section and reference it from each example.

### Low

#### `docs/resilience.md` intro lists "three resilience primitives" — five ship as of 0.8.0

`docs/resilience.md:3`

The opening paragraph names `AsyncRetry`, `RetryBudget`, and `AsyncBulkhead` as "three resilience primitives", omitting the sync `Retry` and `Bulkhead` added in 0.8.0. `src/httpware/middleware/resilience/__init__.py` exports all five (`__all__ = ['AsyncBulkhead', 'AsyncRetry', 'Bulkhead', 'Retry', 'RetryBudget']`), and the rest of the file does cover the sync variants further down — only the headline count is stale.

```text
`httpware` ships three resilience primitives under `httpware.middleware.resilience`, all composable through the standard [AsyncMiddleware](middleware.md) chain:

- **`AsyncRetry`** — automatic retry of transient failures with full-jitter exponential backoff
- **`RetryBudget`** — Finagle-style token bucket...
- **`AsyncBulkhead`** — concurrency limiter via `asyncio.Semaphore` with bounded acquire-wait
```

Verifier consensus: 2/3 (code_reality + spec_grounded). Suggested direction: update the count to "five" (or just say "the resilience primitives"), add `Retry` and `Bulkhead` as bullets, and consider grouping the bullets into sync/async pairs to mirror the layout already used for the client classes.

#### `docs/index.md` observability paragraph names only `AsyncRetry`/`AsyncBulkhead`; sync `Retry`/`Bulkhead` also emit events

`docs/index.md:109`

The observability paragraph reads "`AsyncRetry` and `AsyncBulkhead` emit operational events via two channels". The sync `Retry` class calls `_emit_event` at lines 261/279/295 of `src/httpware/middleware/resilience/retry.py` (events `retry.streaming_refused`, `retry.giving_up`, `retry.budget_refused`) and the sync `Bulkhead` calls `_emit_event` at line 128 of `bulkhead.py` (event `bulkhead.rejected`) — identical event names, identical logger names, identical OTel-span-event payloads. A reader who runs the sync clients in production sees the same telemetry but the docs imply otherwise. The exact same wording is duplicated in `README.md` at line 116.

```text
`AsyncRetry` and `AsyncBulkhead` emit operational events via two channels — stdlib `logging` records (always on) and OpenTelemetry span events (when `opentelemetry-api` is installed).
```

Verifier consensus: 2/3 (code_reality + spec_grounded). Suggested direction: change the subject to "`AsyncRetry`/`Retry` and `AsyncBulkhead`/`Bulkhead`" in both `docs/index.md:109` and `README.md:116`, and add a one-line note that event names and payloads are identical across the sync and async variants (i.e., dashboards built against one class apply unchanged to the other).

#### `CLAUDE.md` module layout annotates `client.py` as AsyncClient-only

`CLAUDE.md:71`

The Module layout diagram describes `client.py` as `# AsyncClient (thin wrapper over httpx2.AsyncClient)`, but the same file defines the sync `Client` at line 763 of `src/httpware/client.py` (its constructor accepts `httpx2_client: httpx2.Client`, the matching sync mirror). The diagram is the first thing an AI agent reads when locating the public surface; the omission silently steers extensions toward the async path only.

```text
├── client.py                      # AsyncClient (thin wrapper over httpx2.AsyncClient)
```

Verifier consensus: 2/3 (code_reality + spec_grounded). Suggested direction: amend the comment to `# AsyncClient + Client (thin wrappers over httpx2.AsyncClient / httpx2.Client)` so the layout reflects the 0.8.0 reality.

#### `CLAUDE.md` Protocol Seam 1 omits sync `Client`

`CLAUDE.md:83`

Seam 1 still reads "`AsyncClient ↔ Middleware`" and describes chain composition only at `AsyncClient.__init__`. After 0.8.0 the seam covers `Client ↔ Middleware` symmetrically (sync `compose` / `Next` mirror the async pair). `planning/engineering.md:33` already updated the canonical heading to "Seam A: `Client`/`AsyncClient` ↔ `Middleware`/`AsyncMiddleware`"; `CLAUDE.md` is the operative AI-agent reference and is now out of step with the engineering doc.

```text
1. **`AsyncClient ↔ Middleware`** — middleware chain composed at `AsyncClient.__init__`, frozen for the client's lifetime. Internal terminal calls `httpx2.AsyncClient.send`, maps exceptions, raises `StatusError` on 4xx/5xx.
```

Verifier consensus: 2/3 (spec_grounded twice). Suggested direction: replicate the engineering.md wording — heading "`Client`/`AsyncClient` ↔ `Middleware`/`AsyncMiddleware`", body describing composition at both `__init__`s and noting the parity guarantee. Update Seam labelling style at the same time if the broader Seam 1/2/3 → A/B/C rename below is adopted.

#### `planning/engineering.md` §1 uses future tense for 0.8.0 changes that already shipped

`planning/engineering.md:9`

§1 paragraphs 2 and 3 read "The next release renames the async middleware surface to use the `Async*`/`async_*` prefix" and "The same release also adds a sync `Client` with full feature parity". Both shipped on 2026-06-07 (PRs #30 + #31 to main; tracked in MEMORY.md as "Sync Client + Async\* rename merged"). Leaving the prose in future tense suggests to a reader that these are upcoming, planned changes still in design.

```text
The next release renames the async middleware surface to use the `Async*`/`async_*` prefix (aligning with httpx2's convention) and removes the seldom-used `attempt_timeout=` kwarg from `AsyncRetry` — see `planning/specs/2026-06-07-sync-client-design.md` for the rationale.

The same release also adds a sync `Client` with full feature parity
```

Verifier consensus: 2/3 (code_reality + spec_grounded). Suggested direction: rewrite both paragraphs in past tense ("As of 0.8.0 the async middleware surface uses the `Async*`/`async_*` prefix…"). Either fold them into the existing as-of narrative or move them to §8 (Shipped work) and leave §1 with the present-tense invariants only.

#### `planning/engineering.md` §8 credits `attempt_timeout=` as a shipped v0.4 feature; 0.8.0 removed it

`planning/engineering.md:136`

The v0.4 slice 1 line lists "`Retry` middleware + Finagle-style `RetryBudget` token bucket + `attempt_timeout=` parameter (folded-in 3-1)". 0.8.0 removed `attempt_timeout=` as a breaking change (confirmed by `grep -n attempt_timeout src/httpware/middleware/resilience/retry.py` returning zero matches; the parameter is gone from both the async and sync retry classes). The historical log is the canonical reference for "what currently ships" — a stale entry there directly misleads agents reasoning about the public API.

```text
**v0.4 slice 1:** `Retry` middleware + Finagle-style `RetryBudget` token bucket + `attempt_timeout=` parameter (folded-in 3-1).
```

Verifier consensus: 2/3 (code_reality + spec_grounded). Suggested direction: append a parenthetical to the v0.4 entry — `(attempt_timeout= removed in 0.8.0; see release notes)` — and add a v0.8.0 entry to the shipped-work log capturing the Async\* rename, sync `Client`, and `attempt_timeout=` removal in one place.

### Nit

#### `docs/middleware.md` LoggingMiddleware example calls `print()` — contradicts the no-print invariant

`docs/middleware.md:159`

The sync `LoggingMiddleware` class in the middleware guide uses `print()` for both the outgoing and incoming log lines. CLAUDE.md "Architecture invariants" lists "No `print()`: enforced by ruff" as non-negotiable. The doc example teaches a pattern that would fail CI in a user's own project if they follow the project's conventions, and contradicts the neighboring `RequestIdMiddleware` example in the same file which correctly uses `logging`.

```python
class LoggingMiddleware:
    def __call__(self, request: httpx2.Request, next: Next) -> httpx2.Response:  # noqa: A002
        print(f"-> {request.method} {request.url}")
        response = next(request)
        print(f"<- {response.status_code}")
        return response
```

Verifier consensus: 3/3 (code_reality + reproducer + spec_grounded). Suggested direction: rewrite the example with module-level `_LOGGER = logging.getLogger("myapp.logging_middleware")` and `_LOGGER.info(...)` calls. Match the style of the existing `RequestIdMiddleware` snippet so the two examples reinforce one convention.

#### Stale-doc nits (rolled up — 4 entries across CLAUDE.md, engineering.md, decoders/__init__.py)

Rolling four `stale_doc` nits into one entry per the spec's nits-collapse rule. All four are leftover 0.7.0-era phrasings that survived the 0.8.0 rename and sync-Client merge; none change runtime behavior, but together they form a small drift surface across the operative AI-agent reference (`CLAUDE.md`) and the canonical engineering doc (`planning/engineering.md`).

- **`CLAUDE.md:84`** — Protocol Seam 2 still reads "`AsyncClient ↔ ResponseDecoder`"; sync `Client.__init__` accepts the same `decoder=` argument and calls `self._decoder.decode()` identically. The same omission exists in `planning/engineering.md` Seam B. Suggested direction: rename both to "`Client`/`AsyncClient` ↔ `ResponseDecoder`" in the same pass that fixes Seam 1 above.
- **`CLAUDE.md:91`** — Testing section only shows the `AsyncClient(httpx2_client=httpx2.AsyncClient(transport=mock))` injection pattern; the sync mirror `Client(httpx2_client=httpx2.Client(transport=mock))` is exercised throughout `tests/test_client_sync.py` but never named. Suggested direction: add the sync line beside the async one so agents writing test scaffolding see both shapes.
- **`planning/engineering.md:146`** — §8 closing paragraph says "All planned epics are closed as of v0.7.0. The next semver bump is a judgment call…". 0.8.0 has since merged to main as a breaking release (sync `Client` + Async\* rename), so the paragraph is stale. Suggested direction: update the version to v0.8.0 and re-evaluate the "judgment call" sentence in light of the now-shipped 0.8 work.
- **`src/httpware/decoders/__init__.py:1`** — Module docstring references "Seam 3"; `planning/engineering.md` §3 now labels the seams A/B/C and the decoder seam is Seam B. Suggested direction: change "Seam 3" to "Seam B" (and audit `chain.py` / `client.py` for any peer references using the old numbering).

Verifier consensus: 2/3 each (code_reality + spec_grounded for the first three; code_reality + reproducer for the decoders docstring label). Combined suggested direction: knock out all four in a single doc-sweep PR after the Seam 1/Seam 2 wording is settled, so the rename style is consistent across `CLAUDE.md`, `engineering.md`, and the module docstrings.

## Chunk 3 — Test Quality (hand-review)

> _Method note: the workflow-driven tests dimension stalled across two attempts (single broad finder, then split into props / parity / mocks sub-finders). Both runs returned 0 findings after a combined ~1.5M Sonnet tokens. This section is a targeted hand-review covering the highest-signal angles only — it is not a substitute for an exhaustive test-suite audit and should be revisited as a separate pass when budget allows._

4 hand-picked findings, all in test files. Severity-bound between low and nit because none reflect production-code bugs — they're test-design issues that weaken the safety net around primitives the rest of the audit already flagged. Two are sync/async parity gaps the 0.8.0 rename left open; the other two are weakness patterns in the Hypothesis suites for the resilience primitives.

### Low

#### `test_try_withdraw_never_exceeds_theoretical_bound` reproduces the production formula it should audit

`tests/test_budget_props.py:52`

The property test computes its expected ceiling with `ceiling = int(deposits * percent) + floor` — the *exact same `int(...)` truncation* used by `RetryBudget.try_withdraw` at `src/httpware/middleware/resilience/budget.py:67`. The Chunk 1 finding "RetryBudget ceiling truncates rather than rounds" identifies this truncation as an off-by-one against the configured percentage; this test cannot find that bug because it asserts against the same buggy formula. A test that derives its expected bound from the same broken arithmetic as the code under test will pass under any consistent error.

```python
floor = int(min_rps * ttl)
ceiling = int(deposits * percent) + floor
permitted = 0
for _ in range(ceiling + 10):
    if budget.try_withdraw():
        permitted += 1
assert permitted <= ceiling
```

Suggested direction: pair this assertion with an independent check — e.g., compute the expected ceiling using `math.ceil(deposits * percent)` (the intended semantics) and assert `permitted` lies within `[ceiling_ceil - 1, ceiling_truncated]`. That makes the test discriminate between the two roundings and turns it into a regression guard for the Chunk 1 fix.

#### `test_on_error_lets_cancelled_propagate` is async-only — no sync peer for `KeyboardInterrupt` / `SystemExit`

`tests/test_middleware.py:162` vs `tests/test_middleware_sync.py`

The async middleware suite verifies that an `async_on_error` handler cannot suppress `asyncio.CancelledError` — the system-exit class of exception that must always escape user code. The sync middleware suite has no equivalent test for `KeyboardInterrupt` or `SystemExit`, which are the corresponding "must propagate" exceptions in synchronous code. The sync `on_error` decorator (`src/httpware/middleware/__init__.py`) accepts a handler signature that could in principle swallow `BaseException`, and there is no test pinning that behavior. Sync/async parity is a stated invariant for the resilience surface.

```python
async def test_on_error_lets_cancelled_propagate() -> None:
    @async_on_error
    async def swallow_all(request, exc) -> httpx2.Response | None:
        raise AssertionError("should not catch CancelledError")
    async def terminal(request):
        raise asyncio.CancelledError
    dispatch = compose_async((swallow_all,), terminal)
    with pytest.raises(asyncio.CancelledError):
        await dispatch(_make_request())
```

Suggested direction: add `test_on_error_lets_keyboardinterrupt_propagate` (and optionally `_systemexit_`) to `tests/test_middleware_sync.py`, mirroring the async shape with the sync `on_error` decorator and `compose` instead of `compose_async`. Keep the test names and structure aligned so the parity reads at a glance.

#### `tests/test_client_methods.py` has no construction / lifecycle tests for `AsyncClient`

`tests/test_client_methods.py:1`

`test_client_sync.py:297+` carries thorough construction and lifecycle coverage for the sync `Client`: no-args construction, forwarded kwargs, owned-vs-borrowed `httpx2` clients, `close()` idempotency, context-manager enter/exit. The async equivalent — `test_client_methods.py` — opens at line 29 with `test_get_returns_httpx2_response` and contains only per-method HTTP tests. `AsyncClient.__init__`, `aclose()`, `__aenter__`, and `__aexit__` would all regress silently against this file. The async-specific lifecycle file `test_client_lifecycle.py` (43 lines) covers a narrow slice — close idempotency — but not construction-arg validation or borrowed-client semantics.

```python
"""Tests for the per-method API surface of AsyncClient."""
from httpware import AsyncClient, NotFoundError
def _client_with_handler(handler, **kwargs) -> AsyncClient: ...
async def test_get_returns_httpx2_response() -> None: ...
```

Suggested direction: rename `tests/test_client_methods.py` to `tests/test_client_methods_async.py` for symmetry, add a dedicated `tests/test_client_construction_async.py` mirroring the sync construction section of `test_client_sync.py` (or expand `test_client_lifecycle.py` to cover construction). The fix tracks the same naming polish suggested for the `test_client_sync.py` consolidation.

### Nit

#### Retry property tests use a budget configuration that the budget cannot exhaust

`tests/test_retry_props.py:60` (per the file's `_make_async_retry` helper, exact line varies)

Every `AsyncRetry` instance the retry property suite constructs is given `RetryBudget(ttl=60.0, min_retries_per_sec=1000.0)`. The budget's `try_withdraw` floor is `int(min_retries_per_sec * ttl) = 60_000`, which means up to 60k retries are unconditionally permitted before the percent-based ceiling matters. With Hypothesis's `max_attempts ∈ [1, 5]` and `max_examples=50`, the budget is mathematically incapable of being exhausted by the property tests. The "total attempts never exceeds max_attempts" property is verified; the orthogonal property "when the budget is exhausted, the next attempt raises `RetryBudgetExhaustedError`" has no property-test coverage at all, only a handful of `test_retry.py` deterministic examples.

```python
AsyncRetry(
    _sleep=sleeper,
    max_attempts=max_attempts,
    base_delay=0.001,
    max_delay=0.002,
    budget=RetryBudget(ttl=60.0, min_retries_per_sec=1000.0),
)
```

Suggested direction: add a second property test (or parameterize the existing one) over a budget configured with `min_retries_per_sec=0.0` and `percent_can_retry ∈ [0.0, 0.5]`, then assert that `RetryBudgetExhaustedError` is raised within the first `ceil(attempts * percent) + 1` calls. Pair this with the Chunk 1 budget-rounding fix so the new property is well-defined.


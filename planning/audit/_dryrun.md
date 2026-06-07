# httpware deep audit — dryrun

**Status:** in progress
**Spec:** [planning/specs/2026-06-07-deep-audit-design.md](../specs/2026-06-07-deep-audit-design.md)

## Summary

_Counts updated after final merge._

- Blockers: —
- High: —
- Medium: —
- Low: —
- Nits: —

<!-- chunk sections appended below in order: 0, 1, 2, 3, ... -->

## Chunk 0 — Retry/Budget/Client correctness

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

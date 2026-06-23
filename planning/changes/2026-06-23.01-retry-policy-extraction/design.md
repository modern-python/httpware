---
status: draft
date: 2026-06-23
slug: retry-policy-extraction
summary: Extract a stateless _RetryPolicy decision module from the duplicated AsyncRetry/Retry __call__ loops.
supersedes: null
superseded_by: null
pr: null
outcome: null
---

# Design: Extract a deep `_RetryPolicy` decision module

## Summary

`AsyncRetry.__call__` and `Retry.__call__` hand-copy ~110 lines of retry
*decision* logic — status eligibility, streaming-body refusal, exhaustion,
Retry-After parsing, budget accounting, backoff — differing only in `await
next` vs `next` and `asyncio.sleep` vs `time.sleep`. This change pulls the
decision logic into a stateless private `_RetryPolicy` in the same module, so
both wrappers shrink to a thin loop and the decision lives once. It mirrors
the precedent already in the package: `CircuitBreaker`/`AsyncCircuitBreaker`
share the lock-free `_CircuitBreakerState`.

## Motivation

- `retry.py:100-210` (`AsyncRetry.__call__`) and `retry.py:213-349`
  (`Retry.__call__`) are ~110 lines each, byte-identical except the `await`.
  Parity is hand-maintained; drift is undetectable. Both carry
  `# noqa: C901, PLR0912, PLR0915` to silence the complexity budget.
- The package already proved the fix: `_CircuitBreakerState`
  (`circuit_breaker.py:131-310`) is a deep, synchronous, lock-free decision
  module that both breaker wrappers drive. Retry never got the same treatment.
- **Depth:** the retry interface (the `Middleware` protocol — one `__call__`)
  is small, but the implementation is duplicated rather than deep. Moving the
  decision behind `_RetryPolicy.decide` concentrates it: one place to fix a
  retry bug (locality), one interface to test directly without `MockTransport`
  (leverage).

## Non-goals

- No behaviour change. The retry policy, defaults, events, notes, and raised
  exceptions stay byte-identical.
- Not touching `RetryBudget`, `_backoff.full_jitter_delay`, or
  `_parse_retry_after` — they stay as-is.
- Not unifying the sync/async wrappers themselves — the `await`/blocking split
  is fundamental and stays in the two thin `__call__` shells.
- Not extending the same treatment to `Bulkhead` in this change.

## Design

### 1. `_RetryPolicy` — stateless decision module

A private class in `retry.py`, holding **immutable config + the shared
budget** and nothing per-call mutable. This is the faithful analog of
`_CircuitBreakerState`: there the *circuit* is the shared state; here the
shared state is the already-thread-safe `RetryBudget`, and `_RetryPolicy` is
the decision logic around it. Because it carries no per-call field, it is
trivially safe under the concurrent requests a single frozen middleware
instance serves.

It owns:

- config: `max_attempts`, `base_delay`, `max_delay`, `retry_status_codes`,
  `retry_methods`, `respect_retry_after`, `budget`;
- validation: `max_attempts < 1` → `ValueError` (raised when the wrapper
  builds the policy in `__init__`, so construction-time behaviour is
  unchanged);
- the `_LOGGER` event emissions and PEP-678 note additions (side effects move
  here with the decision).

### 2. The seam — one method

```python
def decide(self, *, attempt: int, request: httpx2.Request, exc: BaseException) -> float
```

- **Returns** the `float` delay to sleep for the retry case.
- **Raises** for every terminal case, having already added the note, emitted
  the event, and (for the budget case) constructed `RetryBudgetExhaustedError`
  with its `__cause__`. `decide` is called *inside* the wrapper's `except`
  block, so implicit `__context__` and explicit `raise ... from exc` chaining
  behave exactly as today — no manual `__cause__` fiddling.

Classification is folded in (no separate predicate): derive `last_response`
from `isinstance(exc, StatusError)`; apply method-eligibility and status-set
membership; re-raise non-retryable failures unchanged; otherwise walk
streaming-refusal → exhaustion → Retry-After-exceeds-`max_delay` → budget
`try_withdraw` → delay (Retry-After value or `full_jitter_delay`).

Rejected alternative: a `_Sleep | _Stop` sum type. It defers the raise to
*after* the `except` block, losing the active exception context and forcing
manual chain reconstruction — machinery that exists only to paper over that.
Returning-a-delay-or-raising matches `_CircuitBreakerState.admit()`, which
already raises `CircuitOpenError` rather than returning a rejected value.

### 3. The wrappers shrink to a thin driver

```python
_RETRYABLE_EXCEPTIONS = (StatusError, NetworkError, TimeoutError)

async def __call__(self, request: httpx2.Request, next: AsyncNext) -> httpx2.Response:
    self.budget.deposit()
    for attempt in range(self._policy.max_attempts):
        try:
            return await next(request)
        except _RETRYABLE_EXCEPTIONS as exc:
            delay = self._policy.decide(attempt=attempt, request=request, exc=exc)
        await self._sleep(delay)
    raise AssertionError("unreachable")  # pragma: no cover
```

The sync `Retry.__call__` is identical but for `next(request)` and
`self._sleep(delay)`. `_RETRYABLE_EXCEPTIONS` is one module constant
referenced by both — the narrow catch surface stays structural, so anything
not in the tuple (e.g. `httpx2.InvalidURL`, programming errors) propagates
untouched exactly as today. The `# noqa: C901, PLR0912, PLR0915` suppressions
come off `__call__`; `decide` may carry its own.

### 4. Preserved public contract

- `AsyncRetry.__init__` / `Retry.__init__` signatures unchanged (incl.
  `_sleep`, `budget`).
- The wrapper keeps `self.budget` (the *same object* the policy holds, so
  `r1.budget is r2.budget` identity tests pass) and `self._sleep`.
- The six config attributes (`max_attempts`, `base_delay`, `max_delay`,
  `retry_status_codes`, `retry_methods`, `respect_retry_after`) are **dropped**
  from the wrapper instances — they live solely on `_RetryPolicy`. They are
  read nowhere outside `retry.py` and `docs/resilience.md` documents them only
  as constructor parameters, not readable attributes.

## Operations

None — internal refactor, no infra or external changes.

## Out of scope

- `Bulkhead`/`AsyncBulkhead` deduplication.
- Injecting randomness into `full_jitter_delay` (see Testing — only needed if
  we want exact-value assertions on the jitter path).

## Testing

- **Parity net:** all existing `MockTransport` suites — `test_retry.py`,
  `test_retry_sync.py`, `test_retry_props.py`,
  `test_retry_budget_threadsafety.py`, `test_threading_with_shared_budget.py`
  — stay green unchanged. Byte-identical behaviour is the bar.
- **New seam tests:** `tests/test_retry_policy.py` drives `decide` directly
  (no client, no `MockTransport`) across the decision matrix: retryable →
  returns a delay; non-retryable status / non-eligible method → re-raises the
  original; streaming-body refusal; exhaustion note on the last attempt;
  Retry-After > `max_delay`; budget refusal → `RetryBudgetExhaustedError` with
  `__cause__`.
- The jitter path returns a random delay, so assert **bounds**
  (`0 ≤ delay ≤ max_delay`) for it; assert exact values only on the
  deterministic Retry-After path.
- `just lint` and `just test` both clean.

## Risk

- **Behavioural drift during extraction** (likely × high): a subtle
  reordering changes a note string, an event payload, or which exception wins.
  *Mitigation:* extract under the existing green suites; they assert notes,
  events (via the recording sleeper / caplog), and exception types. Do not
  edit the test suites in this change.
- **Exception-chaining regression** (low × medium): moving the raise into
  `decide` could drop a `__cause__`/`__context__`. *Mitigation:* `decide` is
  called inside the live `except`; an explicit test asserts `__cause__` on the
  budget-exhausted path.
- **Concurrency** (low × high): a stray per-call field on `_RetryPolicy` would
  make a shared instance unsafe. *Mitigation:* the policy holds only immutable
  config + the lock-guarded budget; per-attempt state stays as wrapper locals.
  The property/thread-safety suites cover interleaving.

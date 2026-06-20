---
status: shipped
date: 2026-06-05
slug: bulkhead
summary: Shipped 0.4.0 — Bulkhead
supersedes: null
superseded_by: null
pr: 23
outcome: 'Shipped 0.4.0 — Bulkhead'
---

# Spec: Bulkhead middleware (0.4.0, Epic 3 slice 2)

**Date:** 2026-06-05
**Topic slug:** `bulkhead`
**Status:** drafted, awaiting user review
**Target release:** 0.4.0 (bundled with slice 1 — Retry + RetryBudget).
**Epic 3 stories rolled in:** 3-5 (Bulkhead).

## Purpose

Ship `httpware`'s second resilience primitive: a `Bulkhead` middleware that caps in-flight requests through an `AsyncClient`. This is distinct from `httpx2.Limits`, which caps the *connection pool* — Bulkhead caps the *number of concurrent requests* the caller has waiting on the network at once. Use cases:

- Protect a downstream service from being overwhelmed by a busy client.
- Bound the client's own resource usage (memory, response handlers in flight).
- Fail fast under load instead of building up unbounded queues of waiting requests.

This is slice 2 of Epic 3; the only remaining Epic 3 work after this is `3-6` extension-slot docs (rides with the last code PR or in a docs-only follow-up).

## Non-goals

Items deliberately deferred so this slice ships clean:

- **No per-host / per-route partitioning.** One Bulkhead = one semaphore. If a future caller needs per-downstream caps, they install separate Bulkheads on separate clients (or wait for a future spec that adds keying). Adding partitioning later is purely additive.
- **No separate `BulkheadLimit` type.** Unlike `Retry`+`RetryBudget` (where the budget needs to be separable to share across multiple `Retry` middlewares), `Bulkhead` is *already* the sharable unit — reuse the instance across `AsyncClient(middleware=[shared])` calls.
- **No queue metrics surface.** No `bulkhead.in_flight` / `bulkhead.queued` properties. Observability lands in Epic 5 (`5-1` Layer 1 hooks); revisit then.
- **No fallback / shed-load callbacks.** Caller catches `BulkheadFullError` and decides what to do.
- **No connection-pool integration.** `Bulkhead` is a middleware; `httpx2.Limits` is a transport-level concern. They compose but stay independent.

## Architecture & module layout

```text
src/httpware/middleware/resilience/
├── __init__.py            # existing; add Bulkhead re-export
├── budget.py              # existing
├── retry.py               # existing
├── _backoff.py            # existing
└── bulkhead.py            # NEW
```

`Bulkhead` middleware in `bulkhead.py`. `BulkheadFullError(ClientError)` lands in `src/httpware/errors.py` alongside the existing exception tree. Both re-exported from `httpware/__init__.py`. No new optional extra — pure stdlib (`asyncio.Semaphore`, `asyncio.timeout`).

File-per-middleware mirrors slice-1's layout — each unit is independently testable.

## Public API

### `Bulkhead` middleware

```python
class Bulkhead:
    """Concurrency limiter middleware. See module docstring for behavior."""

    def __init__(
        self,
        *,
        max_concurrent: int,                  # required; no default
        acquire_timeout: float | None = 1.0,  # seconds; None = wait forever; 0 = fail fast
    ) -> None: ...

    async def __call__(
        self,
        request: httpx2.Request,
        next: Next,
    ) -> httpx2.Response: ...
```

Constructor validation:

- `max_concurrent < 1` → `ValueError("max_concurrent must be >= 1")`
- `acquire_timeout is not None and acquire_timeout < 0` → `ValueError("acquire_timeout must be >= 0")`
- `acquire_timeout == 0` is accepted (fail-fast: no wait).

Internal state: one `asyncio.Semaphore(max_concurrent)` instantiated in `__init__`. Created with the running event loop's binding rules — semaphores in asyncio are not loop-bound until first use in 3.10+, so the middleware is safe to construct outside an event loop.

`max_concurrent` is required because there is no universally-correct default — the right value depends on downstream capacity, request latency, and the caller's SLA. Forcing the choice avoids hiding a production-shaping default.

### `BulkheadFullError`

```python
class BulkheadFullError(ClientError):
    """Raised when acquire_timeout elapses before a Bulkhead slot becomes available."""

    max_concurrent: int
    acquire_timeout: float | None

    def __init__(self, *, max_concurrent: int, acquire_timeout: float | None) -> None:
        self.max_concurrent = max_concurrent
        self.acquire_timeout = acquire_timeout
        super().__init__(
            f"bulkhead full (max_concurrent={max_concurrent}, "
            f"acquire_timeout={acquire_timeout})"
        )

    def __reduce__(self) -> tuple[Any, ...]: ...  # picklable via module-level reconstructor
```

Picklable via the same `_reconstruct_*` pattern used for `StatusError` and `RetryBudgetExhaustedError` (see `src/httpware/errors.py:61-62, 149-156`). Tested explicitly.

`BulkheadFullError` inherits from `ClientError` so callers catching `ClientError` already handle it. We do NOT inherit from `httpware.TimeoutError` — semantically, a bulkhead-full event is a backpressure signal, not a network timeout. Conflating them would mislead callers writing observability/alerting around timeout vs overload.

## Behavior

### `Bulkhead.__call__` algorithm

```python
async def __call__(self, request, next):
    try:
        if self._acquire_timeout is None:
            await self._sem.acquire()
        else:
            async with asyncio.timeout(self._acquire_timeout):
                await self._sem.acquire()
    except TimeoutError as exc:  # builtins.TimeoutError, which `asyncio.timeout` raises in 3.11+
        raise BulkheadFullError(
            max_concurrent=self._max_concurrent,
            acquire_timeout=self._acquire_timeout,
        ) from exc

    try:
        return await next(request)
    finally:
        self._sem.release()
```

Why two-stage (`acquire` then `try/finally`) rather than `async with self._sem`:

- If we used `async with self._sem`, a CancelledError fired between the `__aenter__` return and the start of `next()` would still pass through `__aexit__`, which is fine — `asyncio.Semaphore.__aexit__` releases. But it is too easy to misread the structure as "the timeout wraps both acquire and execute," which is wrong.
- The explicit acquire makes the contract obvious: only the acquisition is bounded by `acquire_timeout`; `next()` runs as long as it needs to.
- The `try/finally` makes release deterministic across every exit path (success, exception from `next()`, cancellation during `next()`).

### Cancellation semantics

- **Cancellation before `acquire()` returns**: `CancelledError` propagates; no slot held; no release.
- **Cancellation during `next()`**: `try/finally` releases the slot; `CancelledError` propagates.
- **Cancellation between `acquire()` return and start of `next()`** (vanishingly small window): `try/finally` releases the slot; `CancelledError` propagates.

### Middleware chain position

Documented recommendation (not enforced):

```python
AsyncClient(middleware=[
    Bulkhead(max_concurrent=10),     # outermost: cap total concurrency
    Retry(...),                       # retries happen *inside* the Bulkhead slot
])
```

Rationale: with `Bulkhead` outside `Retry`, a single request occupies one slot across all its retry attempts. Concurrency stays bounded by `max_concurrent` even under retry storms. The opposite order — `Retry` outside `Bulkhead` — lets each retry attempt re-acquire a slot, which inflates effective concurrency under the exact load conditions retry is meant to absorb.

If a caller wants per-attempt rejection (each retry can be rejected independently), they put `Retry` outside; that is also valid and documented as a trade-off in the docstring.

### Sharing across clients

A `Bulkhead` instance is the sharable unit. Reuse:

```python
shared = Bulkhead(max_concurrent=20)
client_a = AsyncClient(base_url="https://upstream.example.com/v1", middleware=[shared])
client_b = AsyncClient(base_url="https://upstream.example.com/v2", middleware=[shared])
```

Both clients then contend for the same 20 slots. No special API surface — the semaphore is just a Python attribute on the shared object.

## Errors raised

- **`BulkheadFullError(ClientError)`** — raised when `acquire_timeout` elapses without acquiring a slot. Fields: `max_concurrent`, `acquire_timeout`. Picklable.
- **`asyncio.CancelledError`** — propagates unchanged. Never caught by `Bulkhead`.
- **All other exceptions from `next()`** — propagate unchanged. `Bulkhead` only intercepts the acquisition-timeout path.

## Testing

Per `planning/engineering.md §6`:

- **`tests/test_bulkhead.py`** — unit tests via `httpx2.MockTransport`:
  - succeeds when slots available (no wait, no `BulkheadFullError`)
  - serializes correctly when at capacity (second call waits for first to release)
  - `BulkheadFullError` raised after `acquire_timeout` elapses
  - `BulkheadFullError` carries the configured `max_concurrent` / `acquire_timeout`
  - `BulkheadFullError` is picklable (round-trip)
  - `acquire_timeout=0` fails fast (immediate raise when full)
  - `acquire_timeout=None` waits forever (use `asyncio.wait_for` to time out from outside the test)
  - slot released after success (next request acquires immediately)
  - slot released after exception from `next()` (semaphore not leaked)
  - slot released on `asyncio.CancelledError` propagation
  - `max_concurrent < 1` rejected at construction with `ValueError`
  - negative `acquire_timeout` rejected at construction with `ValueError`
  - shared `Bulkhead` instance across two `AsyncClient`s enforces the joint cap

- **`tests/test_bulkhead_props.py`** — Hypothesis property tests:
  - **Invariant 1**: For any interleaving of N coroutines through a single `Bulkhead(max_concurrent=K)`, the observed in-flight count never exceeds K.
  - **Invariant 2**: With `acquire_timeout=0`, the total successful acquisitions across the run equals K + (number of releases observed before each acquire attempt).
  - **Invariant 3**: `BulkheadFullError` is raised iff acquire takes longer than `acquire_timeout`.

- **No time injection.** Unlike `RetryBudget` (where deterministic time matters for TTL math), `Bulkhead`'s only time-sensitive operation is `asyncio.timeout` around the acquire. Tests use real `asyncio.sleep` with sub-100ms values; the suite stays under ~50ms even with the property tests.

- **Coverage target**: 100% line coverage.

## Open questions deferred to implementation

- **Construct-outside-loop, use-inside-loop test.** `asyncio.Semaphore` in Python 3.10+ binds lazily on first use (no construct-inside-loop requirement). The project floor is 3.11, so this is already fine — but a test that constructs `Bulkhead` at module scope and uses it inside an `async def` test pins the behavior and survives any future stdlib regression.
- **Property test seeding.** Hypothesis-driven concurrency tests can flap if the event loop scheduler is non-deterministic. Use `@settings(deadline=None)` and a sufficient `max_examples` to make flakes detectable, not deterministic. Same pattern as `test_budget_props.py`.

## References

- `planning/engineering.md` §6 (testing patterns, property tests for concurrency-sensitive code), §8 (roadmap — `3-5` Bulkhead)
- `planning/specs/2026-06-05-retry-and-retry-budget-design.md` (slice-1 patterns mirrored here: module-per-middleware, `__reduce__` for picklability, public re-export)
- Hystrix / Resilience4j bulkhead patterns (semaphore-based; conceptual reference, no API parity intended)

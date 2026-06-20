---
status: shipped
date: 2026-06-05
slug: retry-and-retry-budget
summary: Shipped 0.4.0 — Retry + RetryBudget
supersedes: null
superseded_by: null
pr: 22
outcome: 'Shipped 0.4.0 — Retry + RetryBudget'
---

# Spec: Retry middleware + RetryBudget (0.4.0, slice A of Epic 3)

**Date:** 2026-06-05
**Topic slug:** `retry-and-retry-budget`
**Status:** drafted, awaiting user review
**Target release:** 0.4.0
**Epic 3 stories rolled in:** 3-2 (Retry), 3-3 (RetryBudget), 3-4 (RetryBudget middleware integration); 3-1 (per-attempt timeout) is dissolved into the `attempt_timeout=` parameter rather than shipping as a separate middleware.

## Purpose

Ship `httpware`'s first resilience primitive: a `Retry` middleware that automatically retries transient failures, scoped by a Finagle-style `RetryBudget` that prevents retry storms when downstream services degrade. This is the first ship-unit of Epic 3; `Bulkhead` and extension-slot docs ship as later slices (next: `Bulkhead`; then: extension-slot docs ride with the last code PR).

## Non-goals

Items deliberately deferred so this slice ships clean:

- **No per-call retry override.** No `extensions["httpware_retry"]` key in v1. Callers with heterogeneous retry needs construct a second `AsyncClient` with different middleware. Purely additive to add later.
- **No `Backoff` protocol.** Backoff is hardcoded to exponential with full jitter (AWS-recommended). Add a protocol later if a real use case emerges (YAGNI).
- **No `retry_on_exception=` configuration.** The retryable-exception set is hardcoded to `(httpware.NetworkError, httpware.TimeoutError, asyncio.TimeoutError)`. Users wanting `ChunkedEncodingError`-style additions wait for v0.5.
- **No `Bulkhead`.** Slice C, separate spec.
- **No standalone per-attempt-timeout middleware.** Folded into `Retry.attempt_timeout=` (3-1 dissolved during brainstorming — `asyncio.timeout()` and httpx2's built-in per-op timeouts cover the standalone use case).
- **No status-code re-classification.** `RetryBudgetExhaustedError` and `httpware.TimeoutError` map cleanly to existing exception types — no new `_internal/` plumbing.

## Prerequisite refinement: `NetworkError`

The current `AsyncClient._terminal` maps every non-timeout `httpx2.HTTPError` (including non-transient `InvalidURL` and `CookieConflict`) to `httpware.TransportError`. Retrying on `TransportError` would noisily retry typos and bad cookies. This slice adds:

```python
# In src/httpware/errors.py:
class NetworkError(TransportError):
    """Transient network-layer failure (connect / read / write / close). Safe to retry."""
```

And refines the terminal mapping so that `httpx2`'s transient-network exception family (`httpx2.NetworkError` per httpx convention, or whichever symbols httpx2 exposes for the same hierarchy) raises `httpware.NetworkError` rather than the broader `TransportError`. `InvalidURL` and `CookieConflict` continue to raise `TransportError` directly so they are NOT retried. Existing tests catching `TransportError` keep working (`NetworkError` is a subclass).

This is the single load-bearing assumption Retry depends on — without it, Retry can't distinguish transient from permanent transport-layer failures.

## Architecture & module layout

```text
src/httpware/middleware/
├── __init__.py            # existing; re-export Retry, RetryBudget
├── chain.py               # existing
└── resilience/
    ├── __init__.py        # re-export Retry, RetryBudget
    ├── retry.py           # Retry middleware
    ├── budget.py          # RetryBudget token bucket
    └── _backoff.py        # full-jitter exponential helper (private)
```

A `resilience/` subpackage anticipates `Bulkhead` landing as `resilience/bulkhead.py` in slice C. Retry, RetryBudget, and backoff live in separate modules so each is independently testable: the token-bucket math is pure, the backoff helper is pure, retry orchestrates on top.

`Retry` and `RetryBudget` are re-exported from `httpware/__init__.py` so the public import is `from httpware import Retry, RetryBudget`. No new optional extra — retry is core, not behind `pip install httpware[resilience]`.

## Public API

### `RetryBudget` (Finagle-style token bucket)

```python
class RetryBudget:
    """Token-bucket budget bounding retry rate to prevent retry storms.

    Each request deposits a token; each retry attempts to withdraw one.
    Available retries are bounded by `percent_can_retry` of recent successful
    requests, with a `min_retries_per_sec` floor.
    """

    def __init__(
        self,
        *,
        ttl: float = 10.0,                  # seconds tokens remain valid
        min_retries_per_sec: float = 10.0,  # floor regardless of success rate
        percent_can_retry: float = 0.2,     # fraction of recent successes retriable
    ) -> None: ...

    def deposit(self) -> None:
        """Record a request (success or failure attempt). Adds one token."""

    def try_withdraw(self) -> bool:
        """Atomically attempt to spend one retry token.

        Returns True if a retry is permitted, False if the budget is exhausted.
        Never blocks.
        """
```

**Internal data structure**: a `collections.deque[tuple[float, int]]` of `(deposit_timestamp, count)` entries. `try_withdraw` first purges entries older than `ttl`, then computes:

```
available = floor(recent_deposits * percent_can_retry) + (min_retries_per_sec * ttl) - withdrawn_in_window
```

and decrements `withdrawn_in_window` on success. No lock is required: asyncio runs coroutines cooperatively on a single thread, so deque mutations between `await` points are atomic with respect to other coroutines on the same event loop. Cross-thread use is out of scope (consumers calling httpware from threads carry their own synchronization burden).

Defaults match Finagle's published defaults (ttl=10s, percent=20%, min=10/sec), which AWS SDK and Envoy converged on independently.

### `Retry` middleware

```python
class Retry:
    """Retry middleware. See module docstring for default policy."""

    def __init__(
        self,
        *,
        max_attempts: int = 3,                                  # total tries, including first
        base_delay: float = 0.1,                                # seconds; exponential base
        max_delay: float = 5.0,                                 # cap on backoff
        attempt_timeout: float | None = None,                   # wall-clock cap per attempt
        retry_status_codes: frozenset[int] = DEFAULT_RETRY_STATUS_CODES,
        retry_methods: frozenset[str] = DEFAULT_IDEMPOTENT_METHODS,
        respect_retry_after: bool = True,                       # honor Retry-After on 429/503
        budget: RetryBudget | None = None,                      # None -> fresh per-client default
    ) -> None: ...

    async def __call__(
        self,
        request: httpx2.Request,
        next: Next,
    ) -> httpx2.Response: ...
```

Module-level constants in `retry.py` (per the user's module-constants preference):

```python
DEFAULT_RETRY_STATUS_CODES: typing.Final = frozenset({
    HTTPStatus.REQUEST_TIMEOUT,         # 408
    HTTPStatus.TOO_MANY_REQUESTS,       # 429
    HTTPStatus.BAD_GATEWAY,             # 502
    HTTPStatus.SERVICE_UNAVAILABLE,     # 503
    HTTPStatus.GATEWAY_TIMEOUT,         # 504
})
DEFAULT_IDEMPOTENT_METHODS: typing.Final = frozenset({
    "GET", "HEAD", "OPTIONS", "PUT", "DELETE",
})
```

`http.HTTPStatus` is used rather than bare integers per the user preference.

## Behavior

### Retry trigger evaluation

For each completed attempt (exception OR response), `Retry` evaluates:

1. **Idempotency gate.** If `request.method.upper() not in retry_methods`, return the result as-is. POST/PATCH never retry by default.
2. **Failure-type gate.** Retry IF:
   - the attempt raised `httpware.NetworkError`, `httpware.TimeoutError`, or `asyncio.TimeoutError`; OR
   - the attempt raised an `httpware.StatusError` subclass whose `.response.status_code` is in `retry_status_codes` (since the `AsyncClient` terminal raises `StatusError` on 4xx/5xx, retryable status codes surface as exceptions, not response objects — see "Implementation note" below).
3. **Attempt-count gate.** If `attempt_index + 1 >= max_attempts`, stop.
4. **Budget gate.** Call `budget.try_withdraw()`. If `False`, raise `RetryBudgetExhaustedError` (see "Errors raised" below).
5. **Sleep, then retry.** Compute delay via backoff (Retry-After overrides if applicable), `await self._sleep(delay)`, increment attempt index.

### Backoff: exponential with full jitter

```python
sleep = random.uniform(0, min(max_delay, base_delay * (2 ** attempt_index)))
```

This is AWS's "full jitter" formulation. `attempt_index` is 0 for the first retry. With `base_delay=0.1, max_delay=5.0, max_attempts=3`, the two retry delays draw from `U(0, 0.2)` and `U(0, 0.4)` respectively — fast enough for transient blips, slow enough not to thunderbolt a recovering downstream.

### `Retry-After` interaction

When `respect_retry_after=True` and the response carries a `Retry-After` header (seconds or HTTP-date form), the parsed delay **overrides** the backoff schedule for that attempt. If the parsed delay exceeds `max_delay`, we cap to `max_delay` (a misbehaving server shouldn't extend our budget arbitrarily). Malformed `Retry-After` values are ignored and backoff is used.

Parsing: `int(value)` first, falling back to `email.utils.parsedate_to_datetime` for HTTP-date form.

### `attempt_timeout` semantics

When `attempt_timeout` is not `None`, each attempt runs inside `async with asyncio.timeout(attempt_timeout):`. A firing timeout is caught inside the retry loop, mapped to `httpware.TimeoutError`, and counts as a retryable failure (subject to the failure-type and attempt-count gates).

`attempt_timeout=None` is the documented default: each attempt is bounded only by httpx2's per-op timeouts.

### Middleware chain position

Documented recommendation (not enforced):

```python
AsyncClient(middleware=[
    Retry(...),         # outermost: each retry re-runs middleware below
    # observability middlewares (5-x) when they land
])
```

Rationale: putting `Retry` at the outermost position means each attempt re-runs every middleware below it — relevant when, e.g., an auth-refresh middleware sits below `Retry` and needs to refresh on retry. Users who prefer "log once across all attempts" can put observability above Retry; that trade-off is documented in the docstring, not enforced.

## Errors raised

- **`RetryBudgetExhaustedError(httpware.ClientError)`** — raised when `budget.try_withdraw()` returns `False` AND retries would otherwise have continued. Fields:
  - `last_response: httpx2.Response | None` — set if the latest attempt returned a response
  - `last_exception: BaseException | None` — set if the latest attempt raised
  - `attempts: int` — number of attempts completed before the budget refused
  - Inherits from `ClientError` so callers catching `httpware.ClientError` already handle it.
- **`max_attempts` exhausted**: the *last* error (exception or `StatusError`) is **re-raised unwrapped**. `exc.__notes__` is appended with `"httpware: gave up after N attempts"` (PEP 678) so the gave-up-after context is preserved without changing the exception type. This keeps consumer `except SomeStatusError:` blocks working unchanged.
- **`attempt_timeout` firing**: caught as `asyncio.TimeoutError` inside the retry loop, re-raised as `httpware.TimeoutError` (whether retried or surfaced as the final error). This matches the existing httpx2-error-mapping pattern in the `AsyncClient` terminal.

`RetryBudgetExhaustedError` and `NetworkError` both live in `src/httpware/errors.py` alongside the existing exception tree, exported from `httpware/__init__.py`.

### Implementation note: `StatusError` surfaces as exception, not response

The `AsyncClient` terminal (`client.py:106-126`) raises a `StatusError` subclass on 4xx/5xx — the middleware chain receives an exception, not a `Response` object with a non-2xx status. Retry's status-code check therefore lives in an `except StatusError as exc:` branch, inspecting `exc.response.status_code`. On exhaustion, the original `StatusError` subclass is re-raised unwrapped (preserving consumer `except NotFoundError:` patterns).

## Testing

Per `planning/engineering.md §6` (test patterns):

- **`tests/test_budget.py`** — unit tests for `RetryBudget` token-bucket math. Deterministic time via `monkeypatch` of `time.monotonic`. Cases: TTL expiry purges old deposits; `min_retries_per_sec` floor honored even with zero deposits; `percent_can_retry` ceiling honored under high deposit rate; `try_withdraw` returns `False` when exhausted; deposits accumulate correctly.
- **`tests/test_budget_props.py`** — Hypothesis property tests. Properties: for any interleaving of `deposit()` / `try_withdraw()` calls, `available <= floor(deposits * percent) + (min_retries_per_sec * ttl)`; for any monotonic clock advance, expired tokens are purged before the next computation; total `try_withdraw() == True` count never exceeds the theoretical bound over any window.
- **`tests/test_retry.py`** — middleware behavior via injected `httpx2.MockTransport`. Cases:
  - succeeds first try (no retry, no sleep)
  - succeeds on 2nd attempt after 503
  - gives up after `max_attempts`, re-raises last error unwrapped with PEP-678 note
  - respects `Retry-After` (integer-seconds form)
  - respects `Retry-After` (HTTP-date form)
  - `Retry-After` capped at `max_delay`
  - skips non-idempotent methods by default (POST returns 503 → not retried)
  - honors `attempt_timeout` (slow mock transport → `httpware.TimeoutError`)
  - retries on `httpware.NetworkError` / `httpware.TimeoutError`
  - does NOT retry on `httpware.NotFoundError` (404)
  - does NOT retry on bare `httpware.TransportError` (e.g., `InvalidURL`) — only on the `NetworkError` subclass
  - `RetryBudgetExhaustedError` raised when budget refuses
  - exhausted budget exposes `last_response` / `last_exception` / `attempts`
  - explicit `budget=` parameter shared across two `Retry` middlewares accumulates correctly
- **`tests/test_retry_props.py`** — Hypothesis property tests. For any sequence of `(status_code | exception)` mock responses and any `Retry(...)` config: total attempts never exceeds `max_attempts`; total sleep time never exceeds `max_attempts * max_delay`; never retries a non-retryable status or a non-idempotent method.

**Sleep injection**: `Retry.__init__` accepts a `_sleep: Callable[[float], Awaitable[None]] = asyncio.sleep` parameter (single leading underscore, omitted from the public docstring). Tests pass a recording mock so the suite runs instantly without `freezegun` or event-loop time-travel. The same pattern can apply to `time.monotonic` in `RetryBudget` via a `_now: Callable[[], float] = time.monotonic` parameter.

**Coverage target**: 100% line coverage (existing project standard).

## Open questions deferred to implementation

- **Budget default-instantiation policy.** When `Retry(budget=None)`, does each `AsyncClient` get a *fresh* `RetryBudget()`, or do all clients in a process share a module-level singleton? The spec says fresh-per-client (safer default; explicit shared budgets via `budget=`). Implementation should add a test pinning this.
- **`attempt_timeout` vs `httpx2.Timeout` interaction.** If both fire, which exception wins? The race is implementation-defined; the test should assert *some* `httpware.TimeoutError` is raised, not which path produced it.
- **Streaming request bodies are out of scope for v0.4.** `Retry` re-invokes `next(request)` with the same `httpx2.Request` object on each attempt. This is safe for bytes/JSON bodies (the body is in-memory and re-readable) but unsafe for streaming/async-iterable bodies (a consumed iterator can't replay). Streaming lands in Epic 4 (`4-3` `AsyncClient.stream`); when it ships, retry will need to refuse to retry streamed-body requests (or document that callers must supply a body factory). Add a follow-up entry to `planning/deferred-work.md` once retry merges so this isn't forgotten.

## References

- `planning/engineering.md` §3 (protocol seams), §6 (testing patterns), §8 (roadmap)
- `planning/deferred-work.md` (no items resolved by this slice)
- Finagle `RetryBudget`: https://twitter.github.io/finagle/guide/Clients.html#retry-budget
- AWS SDK adaptive retry mode (token bucket): https://docs.aws.amazon.com/sdkref/latest/guide/feature-retry-behavior.html
- RFC 9110 §9.2.2 (idempotent methods), §8.4 (Retry-After), §15.5.5/15.6.x (status semantics)

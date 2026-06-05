# Resilience reference

`httpware` ships three resilience primitives under `httpware.middleware.resilience`, all composable through the standard [Middleware](middleware.md) chain:

- **`Retry`** — automatic retry of transient failures with full-jitter exponential backoff
- **`RetryBudget`** — Finagle-style token bucket that bounds the global retry rate to prevent retry storms when downstreams degrade
- **`Bulkhead`** — concurrency limiter via `asyncio.Semaphore` with bounded acquire-wait

The canonical composition is `middleware=[Bulkhead(...), Retry()]` — `Bulkhead` outside `Retry` so one slot covers all retry attempts of a single call. Reach for the [Middleware guide](middleware.md) when you want to write your own resilience policy.

## `Retry`

```python
from httpware.middleware.resilience import Retry
```

| Parameter | Default | Effect |
|---|---|---|
| `max_attempts` | `3` | Total tries (including the first). `1` disables retries entirely; `<1` raises `ValueError`. |
| `base_delay` | `0.1` (s) | Floor for the full-jitter exponential backoff. |
| `max_delay` | `5.0` (s) | Ceiling for backoff. |
| `attempt_timeout` | `None` | If set, each individual attempt is wrapped in `asyncio.timeout(attempt_timeout)`. |
| `retry_status_codes` | `frozenset({408, 429, 502, 503, 504})` | Status codes considered retryable. |
| `retry_methods` | `frozenset({"GET", "HEAD", "OPTIONS", "PUT", "DELETE"})` | Idempotent methods only by default. POST excluded; pass an explicit frozenset including `"POST"` to retry it. |
| `respect_retry_after` | `True` | When the response carries a `Retry-After` header on a retryable status, sleep for the header value (clamped to `max_delay`) instead of the jittered backoff. |
| `budget` | `RetryBudget()` (default-configured) | The token bucket. Pass a shared `RetryBudget` instance to apply one budget across multiple clients. |

### Retry-After parsing

`Retry-After` is parsed as either:
- **Integer seconds** — `Retry-After: 30` → sleep 30s (clamped to `max_delay`)
- **HTTP-date** (RFC 5322) — `Retry-After: Wed, 21 Oct 2026 07:28:00 GMT` → sleep until that absolute time (clamped to `max_delay`, floored at 0)

Negative integer values are clamped to 0. Malformed values are ignored, falling back to the jittered backoff.

### Streaming-body refusal

If the request body was an async-iterable, `Retry` refuses to retry — the iterator is consumed after the first attempt and can't replay. The original exception is re-raised with a PEP 678 note:

```
httpware: not retrying — request body is a stream that cannot replay across attempts
```

The same refusal note is added at the non-idempotent early-exit sites (when streaming combines with a non-idempotent method). The observability event `httpware.retry` `retry.streaming_refused` fires only at the retryable-failure-path site — see [Observability](index.md#observability).

### Exhaustion behavior

On exhaustion, `Retry` re-raises the *last* exception observed (e.g., `ServiceUnavailableError`, `NetworkError`), preserving the original class so `except ServiceUnavailableError` still catches it. A PEP 678 note is added: `httpware: gave up after N attempts`.

If exhaustion is caused by the budget refusing a retry (not by `max_attempts`), the raised exception is `RetryBudgetExhaustedError` instead, with `last_response` / `last_exception` / `attempts` fields populated. See the [Errors reference](errors.md).

## `RetryBudget`

```python
from httpware.middleware.resilience import RetryBudget
```

A Finagle-style token bucket bounding retry rate. Each request deposits a token; each retry attempts to withdraw one. Available retries are bounded by `percent_can_retry` of recent deposits, plus a `min_retries_per_sec * ttl` floor.

| Parameter | Default | Effect |
|---|---|---|
| `ttl` | `10.0` (s) | Sliding window over which deposits and withdrawals count. |
| `min_retries_per_sec` | `10.0` | Absolute floor — at least this many retries/sec are permitted regardless of deposit rate. |
| `percent_can_retry` | `0.2` | Fraction of recent deposits that can convert to retries (above the floor). |

### The token-bucket formula

```
ceiling = int(len(deposits_in_window) * percent_can_retry) + int(min_retries_per_sec * ttl)
```

A withdrawal fails when `len(withdrawn_in_window) >= ceiling`.

### Why a floor matters

If the deposit rate is zero (no traffic yet), the percent term is zero — without the floor, the very first retry would be refused. The floor lets small-traffic clients still retry on isolated failures; high-traffic clients are dominated by the percent term and the floor becomes irrelevant.

### Sharing across clients

Pass the same `RetryBudget` instance to multiple `AsyncClient`s when they hit the same downstream — one joint budget covers them all:

```python
import asyncio

from httpware import AsyncClient
from httpware.middleware.resilience import Retry, RetryBudget


shared = RetryBudget()


async def main() -> None:
    async with (
        AsyncClient(base_url="https://api.example.com", middleware=[Retry(budget=shared)]) as users,
        AsyncClient(base_url="https://api.example.com", middleware=[Retry(budget=shared)]) as orders,
    ):
        await asyncio.gather(users.get("/users/1"), orders.get("/orders/1"))
```

### Single-thread assumption

`RetryBudget` is asyncio-aware — deque mutations between await points are atomic on a single event loop. Cross-thread use is out of scope; if you need that, wrap calls in a lock yourself.

## `Bulkhead`

```python
from httpware.middleware.resilience import Bulkhead
```

Concurrency limiter via `asyncio.Semaphore`. Acquires a slot before each request (bounded by `acquire_timeout`); releases on success, exception, AND cancellation.

| Parameter | Default | Effect |
|---|---|---|
| `max_concurrent` | **REQUIRED** | Maximum in-flight requests. `<1` raises `ValueError`. No default — the right cap depends on downstream capacity and SLA. |
| `acquire_timeout` | `1.0` (s) | How long to wait for a slot before raising `BulkheadFullError`. `None` waits forever; `0` fails fast. `<0` raises `ValueError`. |

### Slot release contract

The slot is released in a `try/finally` around `await next(request)`, so all three exit paths release deterministically:
- **Success** — slot released after the response returns
- **Exception** — slot released before the exception propagates
- **Cancellation** — slot released as the `CancelledError` propagates

The slot cannot leak.

### Sharing across clients

Same pattern as `RetryBudget`. One instance, many clients:

```python
shared_bulkhead = Bulkhead(max_concurrent=10)

async with (
    AsyncClient(base_url="https://api.example.com", middleware=[shared_bulkhead, Retry()]) as a,
    AsyncClient(base_url="https://api.example.com", middleware=[shared_bulkhead, Retry()]) as b,
):
    ...  # combined in-flight across a + b is capped at 10
```

### Rejection

When `acquire_timeout` elapses without a slot opening, `Bulkhead` raises `BulkheadFullError` (carries the configured `max_concurrent` and `acquire_timeout` for caller logging). See the [Errors reference](errors.md). The `httpware.bulkhead` `bulkhead.rejected` observability event fires at the same site — see [Observability](index.md#observability).

## Composition

The canonical ordering is `middleware=[Bulkhead, Retry]` — `Bulkhead` outermost so one slot covers all retry attempts of a single call:

```python
from httpware import AsyncClient
from httpware.middleware.resilience import Bulkhead, Retry


async def main() -> None:
    async with AsyncClient(
        base_url="https://api.example.com",
        middleware=[
            Bulkhead(max_concurrent=10),
            Retry(),
        ],
    ) as client:
        await client.get("/users/1")
```

Flipping the order (`[Retry, Bulkhead]`) means each retry attempt grabs a fresh slot — defeating the bulkhead under load. Don't do that.

Cross-cutting middleware that emit per-call state (e.g., the Request-ID middleware in the [Middleware guide](middleware.md)) should sit outside `Retry` for the same reason — so all attempts of one call share one ID rather than getting a fresh ID per attempt.

## See also

- **[Middleware guide](middleware.md)** — write your own resilience middleware against the same protocol `Retry` and `Bulkhead` use.
- **[Errors reference](errors.md)** — `RetryBudgetExhaustedError`, `BulkheadFullError`, and the broader exception tree.
- **[Observability](index.md#observability)** — the four operational events these middleware emit.
- **`planning/engineering.md` §3** — the formal Middleware/Seam-A contract.

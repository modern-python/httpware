# Resilience reference

`httpware` ships three resilience primitives under `httpware.middleware.resilience`, all composable through the standard [AsyncMiddleware](middleware.md) chain:

- **`AsyncRetry`** — automatic retry of transient failures with full-jitter exponential backoff
- **`RetryBudget`** — Finagle-style token bucket that bounds the global retry rate to prevent retry storms when downstreams degrade
- **`AsyncBulkhead`** — concurrency limiter via `asyncio.Semaphore` with bounded acquire-wait

The canonical composition is `middleware=[AsyncBulkhead(...), AsyncRetry()]` — `AsyncBulkhead` outside `AsyncRetry` so one slot covers all retry attempts of a single call. Reach for the [Middleware guide](middleware.md) when you want to write your own resilience policy.

## `AsyncRetry`

```python
from httpware.middleware.resilience import AsyncRetry
```

| Parameter | Default | Effect |
|---|---|---|
| `max_attempts` | `3` | Total tries (including the first). `1` disables retries entirely; `<1` raises `ValueError`. |
| `base_delay` | `0.1` (s) | Floor for the full-jitter exponential backoff. |
| `max_delay` | `5.0` (s) | Ceiling for backoff. |
| `retry_status_codes` | `frozenset({408, 429, 502, 503, 504})` | Status codes considered retryable. |
| `retry_methods` | `frozenset({"GET", "HEAD", "OPTIONS", "PUT", "DELETE"})` | Idempotent methods only by default. POST excluded; pass an explicit frozenset including `"POST"` to retry it. |
| `respect_retry_after` | `True` | When the response carries a `Retry-After` header on a retryable status, sleep for the header value (clamped to `max_delay`) instead of the jittered backoff. |
| `budget` | `RetryBudget()` (default-configured) | The token bucket. Pass a shared `RetryBudget` instance to apply one budget across multiple clients. |

For a whole-attempt wall-clock bound, use `httpx2.Timeout` on the client or
pass `timeout=` per request. `httpware` does not own a structured-cancellation
timeout knob.

### Retry-After parsing

`Retry-After` is parsed as either:
- **Integer seconds** — `Retry-After: 30` → sleep 30s (clamped to `max_delay`)
- **HTTP-date** (RFC 5322) — `Retry-After: Wed, 21 Oct 2026 07:28:00 GMT` → sleep until that absolute time (clamped to `max_delay`, floored at 0)

Negative integer values are clamped to 0. Malformed values are ignored, falling back to the jittered backoff.

### Streaming-body refusal

If the request body was an async-iterable, `AsyncRetry` refuses to retry — the iterator is consumed after the first attempt and can't replay. The original exception is re-raised with a PEP 678 note:

```
httpware: not retrying — request body is a stream that cannot replay across attempts
```

The same refusal note is added at the non-idempotent early-exit sites (when streaming combines with a non-idempotent method). The observability event `httpware.retry` `retry.streaming_refused` fires only at the retryable-failure-path site — see [Observability](index.md#observability).

### Exhaustion behavior

On exhaustion, `AsyncRetry` re-raises the *last* exception observed (e.g., `ServiceUnavailableError`, `NetworkError`), preserving the original class so `except ServiceUnavailableError` still catches it. A PEP 678 note is added: `httpware: gave up after N attempts`.

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
from httpware.middleware.resilience import AsyncRetry, RetryBudget


shared = RetryBudget()


async def main() -> None:
    async with (
        AsyncClient(base_url="https://api.example.com", middleware=[AsyncRetry(budget=shared)]) as users,
        AsyncClient(base_url="https://api.example.com", middleware=[AsyncRetry(budget=shared)]) as orders,
    ):
        await asyncio.gather(users.get("/users/1"), orders.get("/orders/1"))
```

### Single-thread assumption

`RetryBudget` is asyncio-aware — deque mutations between await points are atomic on a single event loop. Cross-thread use is out of scope; if you need that, wrap calls in a lock yourself.

## `AsyncBulkhead`

```python
from httpware.middleware.resilience import AsyncBulkhead
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
shared_bulkhead = AsyncBulkhead(max_concurrent=10)

async with (
    AsyncClient(base_url="https://api.example.com", middleware=[shared_bulkhead, AsyncRetry()]) as a,
    AsyncClient(base_url="https://api.example.com", middleware=[shared_bulkhead, AsyncRetry()]) as b,
):
    ...  # combined in-flight across a + b is capped at 10
```

### Rejection

When `acquire_timeout` elapses without a slot opening, `AsyncBulkhead` raises `BulkheadFullError` (carries the configured `max_concurrent` and `acquire_timeout` for caller logging). See the [Errors reference](errors.md). The `httpware.bulkhead` `bulkhead.rejected` observability event fires at the same site — see [Observability](index.md#observability).

## Composition

The canonical ordering is `middleware=[AsyncBulkhead, AsyncRetry]` — `AsyncBulkhead` outermost so one slot covers all retry attempts of a single call:

```python
from httpware import AsyncClient
from httpware.middleware.resilience import AsyncBulkhead, AsyncRetry


async def main() -> None:
    async with AsyncClient(
        base_url="https://api.example.com",
        middleware=[
            AsyncBulkhead(max_concurrent=10),
            AsyncRetry(),
        ],
    ) as client:
        await client.get("/users/1")
```

Flipping the order (`[AsyncRetry, AsyncBulkhead]`) means each retry attempt grabs a fresh slot — defeating the bulkhead under load. Don't do that.

Cross-cutting middleware that emit per-call state (e.g., the Request-ID middleware in the [Middleware guide](middleware.md)) should sit outside `AsyncRetry` for the same reason — so all attempts of one call share one ID rather than getting a fresh ID per attempt.

## Sync Retry and Bulkhead

The sync flavors mirror the async ones for use with `Client`. Same parameter set, same defaults, same `RetryBudget` (which is safe to share across sync and async clients in the same process).

### `Retry`

```python
from httpware.middleware.resilience import Retry
```

| Parameter | Default | Effect |
|---|---|---|
| `max_attempts` | `3` | Total tries (including the first). `1` disables retries entirely; `<1` raises `ValueError`. |
| `base_delay` | `0.1` (s) | Floor for the full-jitter exponential backoff. |
| `max_delay` | `5.0` (s) | Ceiling for backoff. |
| `retry_status_codes` | `frozenset({408, 429, 502, 503, 504})` | Status codes considered retryable. |
| `retry_methods` | `frozenset({"GET", "HEAD", "OPTIONS", "PUT", "DELETE"})` | Idempotent methods only by default. POST excluded; pass an explicit frozenset including `"POST"` to retry it. |
| `respect_retry_after` | `True` | When the response carries a `Retry-After` header on a retryable status, sleep for the header value (clamped to `max_delay`) instead of the jittered backoff. |
| `budget` | `RetryBudget()` (default-configured) | The token bucket. Pass a shared `RetryBudget` instance to apply one budget across multiple clients — sync, async, or both. |

`Retry` uses `time.sleep` between attempts. `Retry-After`, streaming-body refusal, exhaustion behavior, and `RetryBudgetExhaustedError` semantics are identical to `AsyncRetry`.

For a whole-attempt wall-clock bound, use `httpx2.Timeout` on the wrapped client or pass `timeout=` per request. `httpware` does not own a structured-cancellation timeout knob.

### `Bulkhead`

```python
from httpware.middleware.resilience import Bulkhead
```

| Parameter | Default | Effect |
|---|---|---|
| `max_concurrent` | **REQUIRED** | Maximum in-flight requests. `<1` raises `ValueError`. |
| `acquire_timeout` | `1.0` (s) | How long to wait for a slot before raising `BulkheadFullError`. `None` waits forever; `0` fails fast. `<0` raises `ValueError`. |

`Bulkhead` is backed by `threading.Semaphore`. Slot release follows the same `try/finally` contract as `AsyncBulkhead` — success, exception, and (in sync land) interrupt-style exceptions all release the slot.

> **Per-world Bulkhead.** A `Bulkhead` (sync) and an `AsyncBulkhead` are separate primitives backed by `threading.Semaphore` and `asyncio.Semaphore` respectively. A single Bulkhead instance cannot enforce a joint cap across sync + async clients in the same process. If you need that, create both with the same `max_concurrent`; the OS will not coordinate the two but the policy intent is documented.

### Composition with sync `Client`

```python
from httpware import Client
from httpware.middleware.resilience import Bulkhead, Retry


with Client(
    base_url="https://api.example.com",
    middleware=[
        Bulkhead(max_concurrent=10),
        Retry(),
    ],
) as client:
    client.get("/users/1")
```

## See also

- **[Middleware guide](middleware.md)** — write your own resilience middleware against the same protocol `AsyncRetry` and `AsyncBulkhead` use.
- **[Errors reference](errors.md)** — `RetryBudgetExhaustedError`, `BulkheadFullError`, and the broader exception tree.
- **[Observability](index.md#observability)** — the four operational events these middleware emit.
- **`planning/engineering.md` §3** — the formal Middleware/Seam-A contract.

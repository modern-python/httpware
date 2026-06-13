# Resilience reference

`httpware` ships these resilience primitives under `httpware.middleware.resilience`, all composable through the standard [Middleware](middleware.md) / [AsyncMiddleware](middleware.md) chain:

- **`Retry` / `AsyncRetry`** — automatic retry of transient failures with full-jitter exponential backoff
- **`RetryBudget`** — Finagle-style token bucket; safe to share across sync `Client` and `AsyncClient` in the same process. (Finagle-style bounds the global retry rate to prevent retry storms when downstreams degrade.)
- **`Bulkhead` / `AsyncBulkhead`** — concurrency limiter with bounded acquire-wait (`threading.Semaphore` and `asyncio.Semaphore` respectively)

A key ordering constraint: `AsyncBulkhead` must sit inside `AsyncRetry` so one slot covers all retry attempts of a single call. For the full recommended ordering across all four primitives, see [Composition](#composition). Reach for the [Middleware guide](middleware.md) when you want to write your own resilience policy.

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
| `respect_retry_after` | `True` | When the response carries a `Retry-After` header on a retryable status, sleep for the header value instead of the jittered backoff. If the header value exceeds `max_delay`, AsyncRetry gives up and re-raises the underlying `StatusError` with a PEP 678 note `httpware: Retry-After (Ns) exceeded max_delay (Ms); giving up`. Set `max_delay` higher (or `respect_retry_after=False`) to opt out. |
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

### Thread safety

`RetryBudget` is thread-safe and asyncio-safe — all mutations go through a `threading.Lock`. A single instance is safe to share across threads, across coroutines on one event loop, and across `Client` / `AsyncClient` pairs in the same process. See [Sync Retry and Bulkhead](#sync-retry-and-bulkhead) for the cross-world sharing pattern.

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

## `AsyncCircuitBreaker` / `CircuitBreaker`

```python
from httpware.middleware.resilience import AsyncCircuitBreaker  # async
from httpware.middleware.resilience import CircuitBreaker        # sync
```

Classic consecutive-failure circuit breaker. Counts failures and prevents requests from reaching a downstream that is known to be broken.

### States

- **CLOSED** — normal operation. Each counted failure increments the consecutive-failure counter. Once `failure_threshold` consecutive counted failures accumulate, the circuit opens.
- **OPEN** — fast-fail. All requests are rejected immediately with `CircuitOpenError` (carrying `retry_after` seconds until the next probe window). After `reset_timeout` seconds the circuit moves to HALF_OPEN.
- **HALF_OPEN** — exactly one probe is admitted. If `success_threshold` consecutive probe successes are observed, the circuit closes. A single probe failure re-opens the circuit.

### Constructor

| Parameter | Default | Effect |
|---|---|---|
| `failure_threshold` | `5` | Consecutive counted failures required to open. `<1` raises `ValueError`. |
| `reset_timeout` | `30.0` (s) | Seconds to stay OPEN before admitting a probe. `<0` raises `ValueError`. |
| `success_threshold` | `1` | Consecutive probe successes required to close. `<1` raises `ValueError`. |
| `failure_status_codes` | `None` | Which status codes count as failures. `None` → all 5xx (`500`–`599`). |

### Failure classification

A **counted failure** is a `NetworkError`, an httpware `TimeoutError`, or a `StatusError` whose status code is in `failure_status_codes`. All other exceptions propagate without affecting circuit state.

**4xx responses — including 429 — count as successes.** A 429 means the service is healthy but throttling; tripping the circuit on it would amplify an incident by adding circuit-open rejections on top of the throttle.

### `CircuitOpenError`

Raised when the circuit is OPEN (with a positive `retry_after: float`) or when HALF_OPEN with a probe already in flight (`retry_after=None`). Inherits `httpware.ClientError`. See the [Errors reference](errors.md).

### Observability

Emitted on logger `httpware.circuit_breaker`:

| Event | When |
|---|---|
| `circuit.opened` | Failure threshold reached; circuit transitions CLOSED → OPEN |
| `circuit.rejected` | Request fast-failed (OPEN or HALF_OPEN probe slot taken) |
| `circuit.half_open` | Reset timeout elapsed; circuit transitions OPEN → HALF_OPEN |
| `circuit.closed` | Success threshold reached; circuit transitions HALF_OPEN → CLOSED |

### Sharing

Pass the same instance to multiple clients to enforce one shared circuit across them. A `CircuitBreaker` (sync) cannot be shared with an `AsyncCircuitBreaker` — they use different concurrency primitives.

### Async example

```python
from httpware import AsyncClient
from httpware.middleware.resilience import AsyncCircuitBreaker


breaker = AsyncCircuitBreaker(failure_threshold=3, reset_timeout=60.0)

async with AsyncClient(
    base_url="https://api.example.com",
    middleware=[breaker],
) as client:
    response = await client.get("/users/1")
```

### Sync example

```python
from httpware import Client
from httpware.middleware.resilience import CircuitBreaker


breaker = CircuitBreaker(failure_threshold=3, reset_timeout=60.0)

with Client(
    base_url="https://api.example.com",
    middleware=[breaker],
) as client:
    client.get("/users/1")
```

## `AsyncTimeout`

```python
from httpware.middleware.resilience import AsyncTimeout
```

Bounds total wall-clock time across the entire inner pipeline. Place it outermost to enforce "this whole operation must finish within `timeout` seconds, even across retries and backoff sleeps." On expiry it raises `httpware.TimeoutError`.

| Parameter | Default | Effect |
|---|---|---|
| `timeout` | **REQUIRED** | Overall deadline in seconds. Must be `> 0`; `≤0` raises `ValueError`. |

**This is not a per-call timeout.** httpx2's connect/read/write/pool timeouts are the right tool for bounding a single outbound call; `AsyncTimeout` doesn't duplicate them. What httpx2 cannot bound is the total wall-clock across a whole retry sequence — `AsyncTimeout` fills that gap.

**No sync `Timeout` exists.** Sync Python has no cancellation primitive that can interrupt a blocking httpx2 call mid-flight. For sync per-call bounds, configure `httpx2.Timeout` on the wrapped client or pass `timeout=` per request.

Observability event: `timeout.exceeded` on logger `httpware.timeout`.

```python
from httpware import AsyncClient
from httpware.middleware.resilience import AsyncCircuitBreaker, AsyncRetry, AsyncTimeout


async with AsyncClient(
    base_url="https://api.example.com",
    middleware=[
        AsyncTimeout(timeout=10.0),   # overall deadline across the whole chain
        AsyncRetry(max_attempts=3),
    ],
) as client:
    response = await client.get("/users/1")
```

## Composition

The recommended ordering (not enforced, but each position has a reason):

```
AsyncTimeout → AsyncCircuitBreaker → AsyncRetry → AsyncBulkhead → terminal
```

- `AsyncTimeout` outermost so the overall deadline covers the entire sequence including retries and backoff.
- `AsyncCircuitBreaker` outside `AsyncRetry` so an open circuit short-circuits the whole retry loop without attempting any calls. This also means the breaker counts one outcome per fully-exhausted retry sequence rather than one per individual attempt.
- `AsyncBulkhead` inside `AsyncRetry` so one slot covers all retry attempts of a single call. Flip it (`[AsyncRetry, AsyncBulkhead]`) and each retry grabs a fresh slot — defeating the bulkhead under load.

```python
from httpware import AsyncClient
from httpware.middleware.resilience import (
    AsyncBulkhead,
    AsyncCircuitBreaker,
    AsyncRetry,
    AsyncTimeout,
)


async def main() -> None:
    async with AsyncClient(
        base_url="https://api.example.com",
        middleware=[
            AsyncTimeout(timeout=30.0),
            AsyncCircuitBreaker(),
            AsyncRetry(),
            AsyncBulkhead(max_concurrent=10),
        ],
    ) as client:
        await client.get("/users/1")
```

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
| `respect_retry_after` | `True` | When the response carries a `Retry-After` header on a retryable status, sleep for the header value instead of the jittered backoff. If the header value exceeds `max_delay`, Retry gives up and re-raises the underlying `StatusError` with a PEP 678 note `httpware: Retry-After (Ns) exceeded max_delay (Ms); giving up`. Set `max_delay` higher (or `respect_retry_after=False`) to opt out. |
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
- **[Errors reference](errors.md)** — `RetryBudgetExhaustedError`, `BulkheadFullError`, `CircuitOpenError`, and the broader exception tree.
- **[Observability](index.md#observability)** — the operational events these middleware emit.
- **`planning/engineering.md` §3** — the formal Middleware/Seam-A contract.

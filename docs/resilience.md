# Resilience reference

`httpware` ships these resilience primitives under `httpware.middleware.resilience`, all composable through the standard [Middleware](middleware.md) / [AsyncMiddleware](middleware.md) chain:

- **`Retry` / `AsyncRetry`** — automatic retry of transient failures with full-jitter exponential backoff
- **`RetryBudget`** — Finagle-style token bucket bounding the global retry rate to prevent retry storms; safe to share across sync `Client` and `AsyncClient` in the same process
- **`Bulkhead` / `AsyncBulkhead`** — concurrency limiter with bounded acquire-wait (`threading.Semaphore` and `asyncio.Semaphore` respectively)

A key ordering constraint: `AsyncBulkhead` must sit outside `AsyncRetry` (before it in `middleware=`) so one slot covers all retry attempts of a single call. For the full recommended ordering across all four primitives, see [Composition](#composition). Reach for the [Middleware guide](middleware.md) when you want to write your own resilience policy.

!!! tip "See it under load"
    New to these patterns? The [interactive demos](demos/index.md) show each one
    surviving an outage side by side with an unprotected client.

- [`AsyncRetry`](#asyncretry)
- [`RetryBudget`](#retrybudget)
- [`AsyncBulkhead`](#asyncbulkhead)
- [`AsyncCircuitBreaker` / `CircuitBreaker`](#asynccircuitbreaker-circuitbreaker)
- [`AsyncTimeout`](#asynctimeout)
- [Sync `Retry` and `Bulkhead`](#sync-retry-and-bulkhead)

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
| `respect_retry_after` | `True` | When a retryable response carries a `Retry-After` header, sleep for that value instead of the jittered backoff. If it exceeds `max_delay`, AsyncRetry gives up and re-raises the underlying `StatusError`, attaching an exception note (PEP 678): `httpware: Retry-After (Ns) exceeded max_delay (Ms); giving up`. Opt out with `respect_retry_after=False` or a higher `max_delay`. |
| `budget` | `RetryBudget()` (default-configured) | The token bucket. Pass a shared `RetryBudget` instance to apply one budget across multiple clients. |

For a whole-operation wall-clock bound across all retry attempts, compose `AsyncTimeout` outermost — see [AsyncTimeout](#asynctimeout) below. For a per-request bound, use `httpx2.Timeout` on the client or pass `timeout=` per request.

### Retry-After parsing

`Retry-After` is parsed as either:
- **Integer seconds** — `Retry-After: 30` → sleep 30s
- **HTTP-date** (RFC 5322) — `Retry-After: Wed, 21 Oct 2026 07:28:00 GMT` → sleep until that absolute time, computed delay floored at 0

Either form triggers the same give-up-and-re-raise rule above if it exceeds `max_delay`. Negative integer values floor at 0; malformed values are ignored, falling back to the jittered backoff.

### Streaming-body refusal

If the request body was an async-iterable, `AsyncRetry` refuses to retry — the iterator is consumed after the first attempt and can't replay. The original exception is re-raised with a PEP 678 note:

```
httpware: not retrying — request body is a stream that cannot replay across attempts
```

A non-idempotent request that also carries a streaming body is refused first by the method-eligibility check — that early exit re-raises the original exception without the streaming-refusal note. The note (and the `httpware.retry` `retry.streaming_refused` observability event) is added only on the retryable-failure path, i.e. once the method and status are both eligible — see [Observability](observability.md).

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
ceiling = ceil(len(deposits_in_window) * percent_can_retry) + int(min_retries_per_sec * ttl)
```

The percent term rounds **up** (`math.ceil`); the floor term truncates (`int`). A withdrawal fails when `len(withdrawn_in_window) >= ceiling`.

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

The slot is released in a `try/finally` around `await next(request)`, so success, an exception propagating, or a `CancelledError` propagating all release it deterministically — it cannot leak.

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

When `acquire_timeout` elapses without a slot opening, `AsyncBulkhead` raises `BulkheadFullError` (carries the configured `max_concurrent` and `acquire_timeout` for caller logging). See the [Errors reference](errors.md). The `httpware.bulkhead` `bulkhead.rejected` observability event fires at the same site — see [Observability](observability.md).

## `AsyncCircuitBreaker` / `CircuitBreaker`

```python
from httpware.middleware.resilience import AsyncCircuitBreaker  # async
from httpware.middleware.resilience import CircuitBreaker  # sync
```

Classic consecutive-failure circuit breaker. Counts failures and prevents requests from reaching a downstream that is known to be broken.

### States

- **CLOSED** — normal operation. Each counted failure increments the consecutive-failure counter. Once `failure_threshold` consecutive counted failures accumulate, the circuit opens.
- **OPEN** — fast-fail. While elapsed time is below `reset_timeout`, requests are rejected immediately with `CircuitOpenError` (carrying `retry_after` seconds until the next probe window). The first request after `reset_timeout` elapses transitions the circuit to HALF_OPEN and becomes the probe.
- **HALF_OPEN** — exactly one probe is admitted. If `success_threshold` consecutive probe successes are observed, the circuit closes. A single probe failure re-opens the circuit.

### Constructor

| Parameter | Default | Effect |
|---|---|---|
| `failure_threshold` | `5` | Consecutive counted failures required to open. `<1` raises `ValueError`. |
| `reset_timeout` | `30.0` (s) | Seconds to stay OPEN before admitting a probe. `<0` raises `ValueError`. |
| `success_threshold` | `1` | Consecutive probe successes required to close. `<1` raises `ValueError`. |
| `failure_status_codes` | `None` | Which status codes count as failures. `None` → all 5xx (`500`–`599`). |
| `failure_rate_threshold` | `None` | Opts into time-based rate mode when set (see [below](#time-based-failure-rate-mode)). Fraction of failures in the rolling window that opens the circuit; `None` keeps classic consecutive-failure mode. |
| `window_seconds` | `30.0` (s) | Rate mode only: width of the rolling window `failure_rate_threshold` is measured over. |
| `minimum_calls` | `20` | Rate mode only: outcomes required in the window before the rate is evaluated. |

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

### Time-based failure-rate mode

By default the circuit breaker trips on `failure_threshold` *consecutive* counted failures. This can miss partial degradation: a downstream returning errors on exactly half of all requests will never form a consecutive streak long enough to trip — the circuit stays closed while the error rate sits at 50%.

Passing `failure_rate_threshold` switches to rate mode (params in the [constructor table](#constructor) above):

```python
from httpware.middleware.resilience import AsyncCircuitBreaker


breaker = AsyncCircuitBreaker(
    failure_rate_threshold=0.5,  # open at ≥50% failures
    window_seconds=30.0,  # over a rolling 30s window
    minimum_calls=20,  # but only once 20+ calls are observed
)
```

Classic mode is the default; `failure_threshold` is ignored once rate mode is active. Half-open recovery works identically in both modes. The same `CircuitBreaker` constructor accepts the same parameters for sync clients.

### State introspection

Both `AsyncCircuitBreaker` and `CircuitBreaker` expose a read-only `state` property returning a public `CircuitState` enum:

```python
from httpware import CircuitState
from httpware.middleware.resilience import AsyncCircuitBreaker

breaker = AsyncCircuitBreaker(failure_threshold=5)
# ... later, in a health/readiness handler:
if breaker.state is CircuitState.OPEN:
    ...  # report the dependency as degraded
```

`state` reflects the stored state at the moment of the call and is read-only (writing raises `AttributeError`). The OPEN→HALF_OPEN transition is lazy — it fires only once a request is actually admitted after `reset_timeout` elapses, not on a clock tick — so `state` keeps reporting `OPEN` until that happens; reading it never triggers the transition. The same property exists on the sync `CircuitBreaker`.

### Sharing

Pass the same instance to multiple clients to enforce one shared circuit across them. A `CircuitBreaker` (sync) cannot be shared with an `AsyncCircuitBreaker` — they use different concurrency primitives.

### Example

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

Sync usage is identical: `Client` + `CircuitBreaker`, no `await`.

## `AsyncTimeout`

```python
from httpware.middleware.resilience import AsyncTimeout
```

Bounds total wall-clock time across the entire inner pipeline. Place it outermost to enforce "this whole operation must finish within `timeout` seconds, even across retries and backoff sleeps." On expiry it raises `httpware.TimeoutError`.

| Parameter | Default | Effect |
|---|---|---|
| `timeout` | **REQUIRED** | Overall deadline in seconds. Must be a finite number `> 0`; a non-finite (`inf`/`nan`) or `≤0` value raises `ValueError`. |

**This is not a per-call timeout.** httpx2's connect/read/write/pool timeouts are the right tool for bounding a single outbound call; `AsyncTimeout` doesn't duplicate them. What httpx2 cannot bound is the total wall-clock across a whole retry sequence — `AsyncTimeout` fills that gap.

**No sync `Timeout` exists.** Sync Python has no cancellation primitive that can interrupt a blocking httpx2 call mid-flight. For sync per-call bounds, configure `httpx2.Timeout` on the wrapped client or pass `timeout=` per request.

Observability event: `timeout.exceeded` on logger `httpware.timeout`. See [Composition](#composition) below for a worked example placing `AsyncTimeout` outermost alongside the other primitives.

## Composition

The recommended ordering (not enforced, but each position has a reason):

```
AsyncTimeout → AsyncCircuitBreaker → AsyncBulkhead → AsyncRetry → terminal
```

- `AsyncTimeout` outermost so the overall deadline covers the entire sequence including retries and backoff.
- `AsyncCircuitBreaker` outside `AsyncRetry` so an open circuit short-circuits the whole retry loop without attempting any calls. This also means the breaker counts one outcome per fully-exhausted retry sequence rather than one per individual attempt. Placing it outside `AsyncBulkhead` too means a request the open circuit rejects never consumes a concurrency slot.
- `AsyncBulkhead` outside `AsyncRetry` so one slot covers all retry attempts of a single call. Flip those two (`[AsyncRetry, AsyncBulkhead]`) and each retry grabs a fresh slot — defeating the bulkhead under load.

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
            AsyncBulkhead(max_concurrent=10),
            AsyncRetry(),
        ],
    ) as client:
        await client.get("/users/1")
```

Cross-cutting middleware that emit per-call state (e.g., the Request-ID middleware in the [Middleware guide](middleware.md)) should sit outside `AsyncRetry` for the same reason — so all attempts of one call share one ID rather than getting a fresh ID per attempt.

## Sync Retry and Bulkhead

The sync flavors mirror the async ones for use with `Client`.

### `Retry`

```python
from httpware.middleware.resilience import Retry
```

`Retry` takes the identical parameters as `AsyncRetry` (table [above](#asyncretry)); it sleeps with `time.sleep` between attempts. `Retry-After`, streaming-body refusal, exhaustion behavior, and `RetryBudgetExhaustedError` semantics are identical to `AsyncRetry`.

For a whole-attempt wall-clock bound, use `httpx2.Timeout` on the wrapped client or pass `timeout=` per request. No sync `Timeout` middleware exists — sync Python has no cancellation primitive that can interrupt a blocking call mid-flight.

### `Bulkhead`

```python
from httpware.middleware.resilience import Bulkhead
```

`Bulkhead` mirrors `AsyncBulkhead` (table [above](#asyncbulkhead)) on a `threading.Semaphore`. Slot release follows the same `try/finally` contract — success, exception, and (in sync land) interrupt-style exceptions all release the slot.

> **Per-world Bulkhead.** `Bulkhead` and `AsyncBulkhead` are separate primitives (`threading.Semaphore` vs `asyncio.Semaphore`); one instance cannot cap sync + async clients jointly. For a shared cap across both, create one of each with matching `max_concurrent` — the OS won't coordinate them, but the policy intent is documented.

### Composition with sync `Client`

The same ordering rationale from [Composition](#composition) applies — `Bulkhead` outside `Retry` — just without `AsyncTimeout` (no sync equivalent) and using `Client`, `Bulkhead`, and `Retry` in place of their async counterparts.

## See also

- **[Middleware guide](middleware.md)** — write your own resilience middleware against the same protocol `AsyncRetry` and `AsyncBulkhead` use.
- **[Errors reference](errors.md)** — `RetryBudgetExhaustedError`, `BulkheadFullError`, `CircuitOpenError`, and the broader exception tree.
- **[Observability](observability.md)** — the operational events these middleware emit.
- **[`architecture/middleware.md`](https://github.com/modern-python/httpware/blob/main/architecture/middleware.md)** — the formal Middleware/Seam-A contract.

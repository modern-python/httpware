# Resilience reference

httpware's resilience middleware live in `httpware.middleware.resilience` and plug into the same [middleware](middleware.md) chain as your own:

- [`AsyncRetry`](#asyncretry) and [`Retry`](#retry) retry transient failures with full-jitter exponential backoff.
- [`RetryBudget`](#retrybudget) is a token bucket that caps the share of traffic spent on retries, so retries can't pile onto an outage. One instance can be shared by sync and async clients.
- [`AsyncBulkhead`](#asyncbulkhead) and [`Bulkhead`](#bulkhead) cap concurrent requests and reject a request that can't get a slot in time.
- [`AsyncCircuitBreaker` and `CircuitBreaker`](#asynccircuitbreaker-circuitbreaker) stop sending requests to a downstream that keeps failing.
- [`AsyncKeyedCircuitBreaker` and `KeyedCircuitBreaker`](#asynckeyedcircuitbreaker-keyedcircuitbreaker) keep a separate circuit per upstream.
- [`AsyncTimeout`](#asynctimeout) bounds the total time of a call, retries included.

Order matters. [Composition](#composition) gives the recommended order and the reason for each position.

!!! tip "See it under load"
    The [interactive demos](demos/index.md) run each pattern through an outage
    next to a client without it.

## `AsyncRetry`

```python
from httpware.middleware.resilience import AsyncRetry
```

| Parameter | Default | Effect |
|---|---|---|
| `max_attempts` | `3` | Total tries, including the first. `1` disables retries; `<1` raises `ValueError`. |
| `base_delay` | `0.1` (s) | Floor for the full-jitter exponential backoff. |
| `max_delay` | `5.0` (s) | Ceiling for backoff. |
| `retry_status_codes` | `frozenset({408, 429, 502, 503, 504})` | Status codes considered retryable. |
| `retry_methods` | `frozenset({"GET", "HEAD", "OPTIONS", "PUT", "DELETE"})` | Idempotent methods only. To retry POST, pass a frozenset that includes `"POST"`. |
| `respect_retry_after` | `True` | When a retryable response has a `Retry-After` header, wait that long instead of the jittered backoff. If the value is over `max_delay`, `AsyncRetry` gives up and re-raises the `StatusError` with a PEP 678 note: `httpware: Retry-After (Ns) exceeded max_delay (Ms); giving up`. To avoid this, set `respect_retry_after=False` or raise `max_delay`. |
| `budget` | `RetryBudget()` | The token bucket. Pass one shared `RetryBudget` to several clients to give them a joint budget. |

To bound the total time across all attempts, put [`AsyncTimeout`](#asynctimeout) first in the chain. To bound a single request, set `httpx2.Timeout` on the client or pass `timeout=` per request.

### Retry-After parsing

`Retry-After` can be either:

- integer seconds: `Retry-After: 30` waits 30 seconds.
- an HTTP date (RFC 5322): `Retry-After: Wed, 21 Oct 2026 07:28:00 GMT` waits until that time, or not at all if it has passed.

Either form over `max_delay` makes `AsyncRetry` give up as described above. Negative integers count as 0. Malformed values are ignored and the jittered backoff is used instead.

### Streaming-body refusal

If the request body was an async iterable, `AsyncRetry` does not retry, because the first attempt consumed the iterator. It re-raises the original exception with a PEP 678 note:

```
httpware: not retrying because the request body is a stream that cannot replay across attempts
```

The note, and the `retry.streaming_refused` event on `httpware.retry`, appear only when the failure would otherwise have been retried. A POST with a streaming body, for example, is re-raised without the note because POST is not retried in the first place. See [Observability](observability.md).

### Exhaustion behavior

When attempts run out, `AsyncRetry` re-raises the last exception, such as `ServiceUnavailableError` or `NetworkError`, with its original class, so `except ServiceUnavailableError` still works. It adds the note `httpware: gave up after N attempts`.

If the budget refuses a retry before `max_attempts` is reached, `AsyncRetry` raises `RetryBudgetExhaustedError` instead, with `last_response`, `last_exception` and `attempts` set. See [Errors](errors.md).

## `RetryBudget`

```python
from httpware.middleware.resilience import RetryBudget
```

A token bucket in the style of Finagle's retry budget. Each request deposits a token and each retry tries to withdraw one. Retries are allowed up to `percent_can_retry` of recent deposits, plus a floor of `min_retries_per_sec * ttl`.

| Parameter | Default | Effect |
|---|---|---|
| `ttl` | `10.0` (s) | Sliding window over which deposits and withdrawals count. |
| `min_retries_per_sec` | `10.0` | Floor: at least this many retries per second are allowed, whatever the deposit rate. |
| `percent_can_retry` | `0.2` | Fraction of recent deposits that can convert to retries (above the floor). |

### The token-bucket formula

```
ceiling = ceil(len(deposits_in_window) * percent_can_retry) + int(min_retries_per_sec * ttl)
```

The percent term rounds up (`math.ceil`); the floor term truncates (`int`). A withdrawal fails when `len(withdrawn_in_window) >= ceiling`.

### Why a floor matters

With no traffic yet, the percent term is zero, and without the floor the first retry would be refused. The floor lets low-traffic clients retry occasional failures. For high-traffic clients the percent term is much larger and the floor stops mattering.

### Sharing across clients

Clients that call the same downstream can share one `RetryBudget`:

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

`RetryBudget` guards its state with a `threading.Lock`, so one instance can be shared across threads, across coroutines, and between a `Client` and an `AsyncClient` in the same process.

## `AsyncBulkhead`

```python
from httpware.middleware.resilience import AsyncBulkhead
```

Limits concurrent requests with an `asyncio.Semaphore`. Each request waits up to `acquire_timeout` for a slot and releases it when it finishes, fails or is cancelled.

| Parameter | Default | Effect |
|---|---|---|
| `max_concurrent` | required | Maximum requests in flight. `<1` raises `ValueError`. There is no default because the right cap depends on the downstream's capacity. |
| `acquire_timeout` | `1.0` (s) | How long to wait for a slot before raising `BulkheadFullError`. `None` waits forever; `0` fails fast. `<0` raises `ValueError`. |

### Slot release contract

The slot is released in a `try/finally` around `await next(request)`, so a success, an exception or a `CancelledError` all release it.

### Sharing across clients

Like `RetryBudget`, one bulkhead can be shared by several clients:

```python
shared_bulkhead = AsyncBulkhead(max_concurrent=10)

async with (
    AsyncClient(base_url="https://api.example.com", middleware=[shared_bulkhead, AsyncRetry()]) as a,
    AsyncClient(base_url="https://api.example.com", middleware=[shared_bulkhead, AsyncRetry()]) as b,
):
    ...  # combined in-flight across a + b is capped at 10
```

### Rejection

If no slot opens within `acquire_timeout`, `AsyncBulkhead` raises `BulkheadFullError` with the configured `max_concurrent` and `acquire_timeout` (see [Errors](errors.md)) and emits `bulkhead.rejected` on `httpware.bulkhead` (see [Observability](observability.md)).

## `AsyncCircuitBreaker` / `CircuitBreaker`

```python
from httpware.middleware.resilience import AsyncCircuitBreaker  # async
from httpware.middleware.resilience import CircuitBreaker  # sync
```

A circuit breaker counts consecutive failures and, past a threshold, stops sending requests to the downstream for a while.

### States

- CLOSED: normal operation. After `failure_threshold` counted failures in a row, the circuit opens.
- OPEN: until `reset_timeout` has passed, every request fails at once with `CircuitOpenError`, whose `retry_after` says how many seconds remain. The first request after that moves the circuit to HALF_OPEN and becomes the probe.
- HALF_OPEN: one probe at a time is let through. After `success_threshold` successful probes in a row the circuit closes; one failed probe opens it again.

### Constructor

| Parameter | Default | Effect |
|---|---|---|
| `failure_threshold` | `5` | Consecutive counted failures required to open. `<1` raises `ValueError`. |
| `reset_timeout` | `30.0` (s) | Seconds to stay OPEN before admitting a probe. `<0` raises `ValueError`. |
| `success_threshold` | `1` | Consecutive probe successes required to close. `<1` raises `ValueError`. |
| `failure_status_codes` | `None` | Status codes that count as failures. `None` means every 5xx. |
| `failure_rate_threshold` | `None` | Setting it switches to [rate mode](#time-based-failure-rate-mode): the share of failures in the rolling window that opens the circuit. `None` keeps the consecutive-failure mode. |
| `window_seconds` | `30.0` (s) | Rate mode only: the length of the rolling window. |
| `minimum_calls` | `20` | Rate mode only: how many outcomes the window needs before the rate is checked. |

### Failure classification

A counted failure is a `NetworkError`, an httpware `TimeoutError`, or a `StatusError` whose status is in `failure_status_codes`. Other exceptions pass through without changing the circuit.

4xx responses, 429 included, count as successes. A 429 means the service is up and throttling you; opening the circuit on it would add circuit-open rejections on top of the throttling.

### `CircuitOpenError`

Raised while the circuit is OPEN, with a positive `retry_after`, or while it is HALF_OPEN and a probe is already in flight, with `retry_after=None`. It subclasses `httpware.ClientError`; see [Errors](errors.md).

### Observability

Emitted on logger `httpware.circuit_breaker`:

| Event | When |
|---|---|
| `circuit.opened` | The failure threshold was reached and the circuit went from CLOSED to OPEN. |
| `circuit.rejected` | A request failed fast because the circuit was OPEN or a HALF_OPEN probe was already running. |
| `circuit.half_open` | The reset timeout passed and the circuit went from OPEN to HALF_OPEN. |
| `circuit.closed` | The success threshold was reached and the circuit went from HALF_OPEN to CLOSED. |

### Time-based failure-rate mode

By default the breaker opens after `failure_threshold` failures in a row. A downstream that fails every other request never produces a long enough streak, so the circuit stays closed at a 50% error rate.

Passing `failure_rate_threshold` switches to rate mode, which opens on the share of failures in a rolling window (parameters in the [constructor table](#constructor)):

```python
from httpware.middleware.resilience import AsyncCircuitBreaker


breaker = AsyncCircuitBreaker(
    failure_rate_threshold=0.5,  # open at ≥50% failures
    window_seconds=30.0,  # over a rolling 30s window
    minimum_calls=20,  # but only once 20+ calls are observed
)
```

In rate mode `failure_threshold` is ignored. Recovery through HALF_OPEN works the same in both modes, and the sync `CircuitBreaker` takes the same parameters.

### State introspection

`AsyncCircuitBreaker` and `CircuitBreaker` have a read-only `state` property that returns a `CircuitState`:

```python
from httpware import CircuitState
from httpware.middleware.resilience import AsyncCircuitBreaker

breaker = AsyncCircuitBreaker(failure_threshold=5)
# ... later, in a health/readiness handler:
if breaker.state is CircuitState.OPEN:
    ...  # report the dependency as degraded
```

Assigning to `state` raises `AttributeError`. The move from OPEN to HALF_OPEN happens when the first request arrives after `reset_timeout`, not when the timeout passes, so `state` reports `OPEN` until then. Reading `state` never changes it.

### Sharing

Pass the same instance to several clients to give them one circuit. A sync `CircuitBreaker` and an `AsyncCircuitBreaker` cannot share state, because they use different locking primitives.

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

For sync code, use `Client` and `CircuitBreaker` without `await`.

## `AsyncKeyedCircuitBreaker` / `KeyedCircuitBreaker`

```python
from httpware.middleware.resilience import AsyncKeyedCircuitBreaker  # async
from httpware.middleware.resilience import KeyedCircuitBreaker  # sync
```

Use a keyed breaker when one client sends requests to more than one upstream. A plain `AsyncCircuitBreaker` holds a single circuit, so one failing upstream fast-fails requests to all the healthy ones. The keyed breaker keeps a separate circuit for each circuit key and opens only the failing upstream's circuit.

Each circuit behaves exactly like an [`AsyncCircuitBreaker`](#asynccircuitbreaker-circuitbreaker) built with the same arguments: the same states, failure classification, rate mode, half-open probe and events. Each circuit has its own probe slot, so two upstreams that recover at the same time are probed independently.

### Constructor

Every `AsyncCircuitBreaker` parameter, with the same defaults, plus:

| Parameter | Default | Effect |
|---|---|---|
| `key` | the request's origin | Maps a request to its circuit key. Any hashable value works. The default is the origin as a string built from scheme, host and port, such as `https://a.example` or `http://a.example:8080`. Hosts are lowercased and default ports dropped, so `https://A.example/x` and `https://a.example:443/y` share a circuit, while `http://a.example` and `https://a.example:8443` each get their own. Userinfo is never part of it. |

### Circuit lifetime

A circuit is created on the first request for its key and kept for as long as the breaker lives. Nothing is evicted or pruned, so memory grows with the number of distinct keys. `key` must therefore map requests to a small, bounded set, such as your configured upstreams. Never derive it from user input. A key function that returns something unbounded, such as the full URL, grows the map forever.

### Observability

The keyed breakers emit the same events as `AsyncCircuitBreaker` on the same `httpware.circuit_breaker` logger. Each event has one extra attribute, `circuit_key`, which is the `str()` of the request's circuit key. httpware redacts `url` but not `circuit_key`, which reaches log records and span events exactly as the key function returned it. A custom `key` must not return credentials, tokens or other sensitive values. The default origin contains none.

### Example

```python
from httpware import AsyncClient
from httpware.middleware.resilience import AsyncKeyedCircuitBreaker, AsyncRetry


async with AsyncClient(
    middleware=[AsyncKeyedCircuitBreaker(failure_threshold=5, reset_timeout=60.0), AsyncRetry()],
) as client:
    await client.get("https://suggest-a.example/v1/suggest")
    await client.get("https://suggest-b.example/v1/suggest")  # unaffected if suggest-a is down
```

In the [composition order](#composition), the keyed breaker takes the circuit breaker's place, before `AsyncRetry`, so it counts one outcome per retry sequence. For sync code, use `Client` and `KeyedCircuitBreaker` without `await`.

## `AsyncTimeout`

```python
from httpware.middleware.resilience import AsyncTimeout
```

Bounds the total time of everything after it in the chain. Put it first so a call, with all its retries and backoff, finishes within `timeout` seconds. When time runs out it raises `httpware.TimeoutError`.

| Parameter | Default | Effect |
|---|---|---|
| `timeout` | required | Overall deadline in seconds. Must be finite and greater than 0, or `ValueError` is raised. |

`AsyncTimeout` does not replace per-request timeouts. httpx2's connect, read, write and pool timeouts bound each request; `AsyncTimeout` bounds the whole retry sequence, which httpx2 can't.

There is no sync `Timeout`, because sync Python cannot interrupt a blocking httpx2 call midway. In sync code, set `httpx2.Timeout` on the client or pass `timeout=` per request.

On expiry it emits `timeout.exceeded` on `httpware.timeout`. [Composition](#composition) has an example with `AsyncTimeout` first in the chain.

## Composition

httpware doesn't enforce an order, but this one is recommended:

```
AsyncTimeout → AsyncCircuitBreaker → AsyncBulkhead → AsyncRetry → terminal
```

- `AsyncTimeout` comes first, so the deadline covers every retry and backoff.
- `AsyncCircuitBreaker` comes before `AsyncRetry`, so an open circuit rejects the call without starting the retry loop, and the breaker counts one outcome per retry sequence instead of one per attempt. Putting it before `AsyncBulkhead` too means a rejected call never takes a slot.
- `AsyncBulkhead` comes before `AsyncRetry`, so one slot covers every attempt of a call. In the reverse order each retry takes a new slot, and under load the bulkhead admits more work than its cap intends.

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

Your own middleware that sets something per call, like the request-ID middleware in [Middleware](middleware.md), also belongs before `AsyncRetry`, so every attempt of a call shares one ID.

## Sync Retry and Bulkhead

Use these with the sync `Client`.

### `Retry`

```python
from httpware.middleware.resilience import Retry
```

`Retry` takes the same parameters as [`AsyncRetry`](#asyncretry) and sleeps with `time.sleep` between attempts. `Retry-After` handling, streaming bodies, giving up, and `RetryBudgetExhaustedError` all work the same way.

There is no sync `Timeout` (see [`AsyncTimeout`](#asynctimeout)); set `httpx2.Timeout` on the client or pass `timeout=` per request.

### `Bulkhead`

```python
from httpware.middleware.resilience import Bulkhead
```

`Bulkhead` is [`AsyncBulkhead`](#asyncbulkhead) on a `threading.Semaphore`. The slot is released in the same `try/finally`, including on `KeyboardInterrupt` and other interrupts.

One bulkhead cannot cap sync and async clients together, because `Bulkhead` and `AsyncBulkhead` use different semaphores. If you create one of each with the same `max_concurrent`, each is enforced separately, so together they admit up to twice that many requests.

### Composition with sync `Client`

The [composition order](#composition) applies with the sync classes, minus the timeout: `CircuitBreaker`, then `Bulkhead`, then `Retry`.

## See also

- [Middleware](middleware.md): write your own resilience middleware with the same protocol.
- [Errors](errors.md): `RetryBudgetExhaustedError`, `BulkheadFullError`, `CircuitOpenError` and the rest of the exception tree.
- [Observability](observability.md): the events these middleware emit.

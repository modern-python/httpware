# Phase decorator recipes

The `@async_before_request`, `@async_after_response`, and `@async_on_error` decorators from `httpware.middleware` turn a single async function into an `AsyncMiddleware`. Reach for them when the logic fits one function — no `self` state, no need to bracket `await next(...)` from both sides.

When the same logic would fit `httpx2.event_hooks` instead, prefer the hook: it's a layer below httpware's exception mapping and chain ordering, and is the right place for transforms that don't need either. Phase decorators participate in the middleware chain — they see `httpware` exceptions (mapped from `httpx2` ones), and they compose with `AsyncRetry`, `AsyncBulkhead`, and other middleware in a documented order.

This page collects four worked recipes — one minimal and one realistic for `@async_before_request`, a response-status counter for `@async_after_response`, and a `NetworkError` fallback for `@async_on_error`.

## `@async_before_request`: bearer token

The smallest useful case — add a static `Authorization` header to every outgoing request.

```python
import httpx2

from httpware import AsyncClient
from httpware.middleware import async_before_request


@async_before_request
async def add_bearer(request: httpx2.Request) -> httpx2.Request:
    request.headers["Authorization"] = "Bearer secret-token"
    return request


async def main() -> None:
    async with AsyncClient(
        base_url="https://api.example.com",
        middleware=[add_bearer],
    ) as client:
        await client.get("/me")
```

`add_bearer` is now an `AsyncMiddleware` instance; pass it directly into `middleware=[…]`. Order in the list is outer→inner — if you add `AsyncRetry()` after, the bearer header is set on every retry attempt (which is what you want — each attempt is a real HTTP call and needs auth).

## `@async_before_request`: correlation ID from `contextvars`

A more realistic case — propagate a correlation ID set by your application's surrounding context (FastAPI middleware, structlog binder, etc.). The decorator pulls the ID out of a `ContextVar` and stamps it on the outgoing request.

```python
import contextvars

import httpx2

from httpware import AsyncClient, AsyncRetry
from httpware.middleware import async_before_request


_CORRELATION_ID: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "correlation_id", default=None,
)


@async_before_request
async def propagate_correlation_id(request: httpx2.Request) -> httpx2.Request:
    correlation_id = _CORRELATION_ID.get()
    if correlation_id is not None:
        request.headers["X-Correlation-Id"] = correlation_id
    return request


async def main() -> None:
    _CORRELATION_ID.set("abc-123")
    async with AsyncClient(
        base_url="https://api.example.com",
        middleware=[propagate_correlation_id, AsyncRetry()],
    ) as client:
        await client.get("/me")  # request carries X-Correlation-Id: abc-123
```

Two notes worth calling out:

- **Placement matters.** `propagate_correlation_id` sits *before* `AsyncRetry` in the chain, so it re-runs for each retry attempt. The header is set on every attempt, but the ID itself stays the same across attempts because `ContextVar` state doesn't change between them.
- **vs `event_hooks`.** This is also expressible as `event_hooks={"request": [propagate_correlation_id]}` on the wrapped httpx2 client, with one functional difference: hooks run *below* the httpware chain, so they fire on every transport attempt including post-redirect hops. For correlation IDs the behaviour is usually equivalent; for anything that should fire once per *logical* call (e.g. a UUID generated inline), the phase decorator is correct.

## `@async_after_response`: counter by status class

Side-effect-only recipe — increment a counter keyed by status class (`2xx`, `4xx`, `5xx`) every time a response comes back. The decorator returns the response unchanged.

```python
from collections.abc import Callable

import httpx2

from httpware import AsyncClient
from httpware.middleware import AsyncMiddleware, async_after_response


MetricSink = Callable[[str, int], None]


def status_class_counter(metric_sink: MetricSink) -> AsyncMiddleware:
    @async_after_response
    async def observe(request: httpx2.Request, response: httpx2.Response) -> httpx2.Response:
        status_class = f"{response.status_code // 100}xx"
        metric_sink(f"http.{request.method.lower()}.responses.{status_class}", 1)
        return response

    return observe


def noop_sink(name: str, count: int) -> None:
    """Replace with your statsd / Prometheus / Datadog client."""


async def main() -> None:
    async with AsyncClient(
        base_url="https://api.example.com",
        middleware=[status_class_counter(noop_sink)],
    ) as client:
        await client.get("/me")
```

Notes:

- The factory function `status_class_counter(metric_sink)` is the canonical way to parameterize a phase decorator — the decorated function itself takes no extra args, but the enclosing factory can.
- **Why not request *latency* here?** Wall-clock timing requires bracketing the `await next(request)` call from both sides — `@async_after_response` only sees the response on the way back, so it can't measure the call duration. (`response.elapsed` from httpx2 is also unavailable at this chain point because the body isn't read yet.) Use a raw `AsyncMiddleware` class for timing — see [middleware.md](../middleware.md) for that pattern.
- Wiring real sinks: pass `statsd.incr` (statsd), a `prometheus_client.Counter` `.inc` method (Prometheus), or `datadog.statsd.increment` (Datadog). The signature `Callable[[str, int], None]` is loose on purpose.
- This middleware does NOT see exceptions. Failed requests (caught by `AsyncRetry`, raised as `StatusError`, or surfaced as `NetworkError`) never reach `@async_after_response`. If you want counts of *attempted* requests including failures, install a `httpware.retry` log handler or write a raw `AsyncMiddleware` that brackets the call.

## `@async_on_error`: fallback on `NetworkError`

When the upstream is unreachable, return a synthesized 503 with a sentinel header so callers can branch on degraded mode. The decorator returns a `Response` on `NetworkError`, and `None` for everything else (re-raise).

```python
import httpx2

from httpware import AsyncClient
from httpware.errors import NetworkError
from httpware.middleware import async_on_error


@async_on_error
async def fallback_on_network_error(
    request: httpx2.Request, exc: Exception,
) -> httpx2.Response | None:
    if isinstance(exc, NetworkError):
        return httpx2.Response(
            503,
            request=request,
            headers={"X-Httpware-Fallback": "network-error"},
            content=b'{"degraded": true}',
        )
    return None


async def main() -> None:
    async with AsyncClient(
        base_url="https://api.example.com",
        middleware=[fallback_on_network_error],
    ) as client:
        response = await client.get("/me")
        if response.headers.get("X-Httpware-Fallback") == "network-error":
            ...  # degraded path
```

Notes:

- **`return None` re-raises.** The decorator only synthesizes a response for cases it actually handles; everything else propagates unchanged. Be specific about which exception types you absorb.
- **Returning a 4xx/5xx response does NOT re-trigger status mapping.** The terminal raises `StatusError` on the upstream response; once your `@async_on_error` returns, the synthesized response flows up the chain unchanged. If you want callers to see a `ServiceUnavailableError`, raise it directly instead of synthesizing.
- **Catches `Exception`, not `BaseException`.** `asyncio.CancelledError` propagates — your fallback won't accidentally swallow cooperative cancellation.
- **Placement vs `AsyncRetry`.** Put `@async_on_error` *outside* `AsyncRetry` (`middleware=[fallback_on_network_error, AsyncRetry()]`) if you want the fallback to apply only after all retries have failed. Inside `AsyncRetry` (`middleware=[AsyncRetry(), fallback_on_network_error]`) the fallback fires on the first network error and `AsyncRetry` never sees it. The outer placement is almost always what you want.

## See also

- **[Middleware guide](../middleware.md)** — the protocol contract, the raw-`AsyncMiddleware` class form, and "when NOT to write a middleware".
- **[Resilience reference](../resilience.md)** — `AsyncRetry`, `RetryBudget`, `AsyncBulkhead` parameters and behaviour.
- **[Errors guide](../errors.md)** — `NetworkError`, `StatusError`, and the full exception tree.

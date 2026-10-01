# Phase decorator recipes

`@async_before_request`, `@async_after_response` and `@async_on_error` turn a single async function into an `AsyncMiddleware`. Use them when the logic fits in one function, with no state on `self` and no code on both sides of `await next(...)`.

Phase decorators run in the middleware chain: they see httpware exceptions and take their place in the chain order next to `AsyncRetry` and `AsyncBulkhead`. Logic that needs neither can also be an `httpx2` event hook; [Middleware](../middleware.md#choosing-where-behavior-lives) explains the difference.

## `@async_before_request`: bearer token

Add a fixed `Authorization` header to every request:

```python
import httpx2

from httpware import AsyncClient
from httpware import async_before_request


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

`add_bearer` is now an `AsyncMiddleware`, so it goes straight into `middleware=[...]`. If you add `AsyncRetry()` after it, every retry attempt carries the header too.

## `@async_before_request`: correlation ID from `contextvars`

Your application may already keep a correlation ID in a `ContextVar`, set by FastAPI middleware or a structlog binder. This middleware copies it onto each outgoing request:

```python
import contextvars

import httpx2

from httpware import AsyncClient, AsyncRetry
from httpware import async_before_request


_CORRELATION_ID: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "correlation_id",
    default=None,
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

`propagate_correlation_id` runs once per call, before `AsyncRetry`, and the request it changes is the one every attempt resends, so all attempts share the header.

The undecorated function would also work as a request hook, `event_hooks={"request": [...]}`, on an `httpx2` client you pass as `httpx2_client=`. Hooks run below the chain, on every transport attempt and every redirect hop. That makes no difference for a correlation ID read from a `ContextVar`, but a value generated in the function, like a fresh UUID, would change on each attempt.

## `@async_after_response`: counter by status class

Count responses by status class (`2xx`, `4xx`, `5xx`) and return each response unchanged:

```python
from collections.abc import Callable

import httpx2

from httpware import AsyncClient
from httpware import AsyncMiddleware, async_after_response


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

- The decorated function can't take extra arguments, so a factory such as `status_class_counter(metric_sink)` is how you pass it settings.
- It can't measure latency. Timing needs code before and after `await next(request)`, and `@async_after_response` only runs after. `response.elapsed` isn't set yet either, because the body hasn't been read at this point. Write an `AsyncMiddleware` class for timing; see [Middleware](../middleware.md).
- `metric_sink` can be `statsd.incr`, the `.inc` method of a `prometheus_client.Counter`, or `datadog.statsd.increment`; the `Callable[[str, int], None]` type is kept loose for that reason.
- It never sees failures. A request that ends in a `StatusError` or `NetworkError` never reaches `@async_after_response`. To count failed requests too, write an `AsyncMiddleware` class that wraps the call, or add a handler on the `httpware.retry` logger.

## `@async_on_error`: fallback on `NetworkError`

When the upstream is unreachable, return a made-up 503 with a marker header so callers can switch to a degraded mode. The function returns a `Response` for `NetworkError` and `None`, which re-raises, for anything else.

```python
import httpx2

from httpware import AsyncClient
from httpware import NetworkError
from httpware import async_on_error


@async_on_error
async def fallback_on_network_error(
    request: httpx2.Request,
    exc: Exception,
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

- Returning `None` re-raises the exception. Handle only the exception types you mean to absorb.
- A 4xx or 5xx response you return is not turned into a `StatusError`. Status mapping happens once, on the upstream response, and your response travels up the chain as is. If callers should get a `ServiceUnavailableError`, raise it.
- The decorator catches `Exception`, not `BaseException`, so `asyncio.CancelledError` still propagates.
- Put the fallback before `AsyncRetry`, as in `middleware=[fallback_on_network_error, AsyncRetry()]`, so it only runs once all retries have failed. After `AsyncRetry`, it handles the first network error and `AsyncRetry` never gets to retry.

## See also

- [Middleware](../middleware.md): the middleware protocol, writing a middleware class, and when to use something else.
- [Resilience](../resilience.md): the built-in resilience middleware and their parameters.
- [Errors](../errors.md): `NetworkError`, `StatusError` and the rest of the exception tree.

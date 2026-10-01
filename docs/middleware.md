# Middleware

Middleware is the main way to extend httpware. A middleware wraps every call a client makes, so it can add request IDs or auth headers, record traces, or apply your own resilience policy without subclassing `AsyncClient` or touching the transport.

The built-in retry, bulkhead, circuit breaker and timeout are ordinary middleware written against the same protocol. A rate limiter or an auth layer you write yourself plugs in the same way.

## Choosing where behavior lives

Middleware is for behavior that applies to every call through a client. Other cases have a better place:

- Behavior for a single call: pass it through `request.extensions=` (or the `extensions=` kwarg at the call site) instead of a middleware.
- Instance state or logic on both sides of the call (a counter, a circuit breaker's open/closed flag, timing that needs both the request and its response): write an `AsyncMiddleware` or `Middleware` class. Phase decorators only cover logic that fits in one function.
- Side effects that don't need httpware's exceptions or chain order, including on post-redirect hops: use `event_hooks` on an `httpx2` client you build yourself and pass as `httpx2_client=`. Middleware and phase decorators run in the httpware chain, see httpware exceptions, and compose with `AsyncRetry` and `AsyncBulkhead`. `event_hooks` run a layer below, on every transport attempt. That is also why `httpware` refuses `event_hooks=` as a client option: an `httpx2.HTTPStatusError` raised in a hook (say, by `raise_for_status()`) reaches the chain as a plain `TransportError` instead of a `StatusError`, so `AsyncRetry` never retries it and the circuit breaker never counts it.
- URL or header validation: `httpx2` already does it.
- Creating HTTP spans for tracing: install `opentelemetry-instrumentation-httpx`, which already traces every transport call. See [Observability](observability.md).
- Redaction: httpware redacts URLs before they reach logs, telemetry, and error messages. It strips `user:pass@` userinfo and masks the values of sensitive query and fragment parameters ([Errors](errors.md#excresponse-access-pattern) lists them). It does not touch headers or bodies, so if your middleware logs those, redact them yourself, for example with a `logging.Filter`.

## Writing your own

### The protocol

Two symbols, both exported from `httpware.middleware`:

```python
from collections.abc import Awaitable, Callable
from typing import Protocol, TypeAlias, runtime_checkable
import httpx2

AsyncNext: TypeAlias = Callable[[httpx2.Request], Awaitable[httpx2.Response]]


@runtime_checkable
class AsyncMiddleware(Protocol):
    async def __call__(self, request: httpx2.Request, next: AsyncNext) -> httpx2.Response: ...
```

The chain is composed once at `AsyncClient.__init__` and frozen for the client's lifetime. The first entry in `middleware=[...]` is the outermost layer: when you write `middleware=[AsyncBulkhead(...), AsyncRetry()]`, the bulkhead sees every request before the retry layer does, so one slot covers all retry attempts of the same call.

Calling `await next(request)` forwards to the next layer (or, eventually, to the terminal that hits `httpx2`). You can:

- forward it unchanged with `return await next(request)`
- change `request.headers`, or build a new request, before forwarding
- call `await next(...)` and inspect or replace the response
- return your own `httpx2.Response` without calling `next`
- wrap `await next(...)` in `try`/`except` to translate failures

Either return an `httpx2.Response` or raise. An exception travels up the chain: `AsyncRetry` catches the ones it retries, and the rest reach the caller.

### Phase decorators

When you need no state on `self` and don't need to wrap `await next(...)`, three decorators turn a single async function into an `AsyncMiddleware`:

```python
from httpware import async_before_request, async_after_response, async_on_error
```

| Decorator | Function signature | When to use |
|---|---|---|
| `@async_before_request` | `async (request) -> request` | Transform the outgoing request (add a header, rewrite a URL). |
| `@async_after_response` | `async (request, response) -> response` | Transform the incoming response (decode, log, attach metadata). |
| `@async_on_error` | `async (request, exc) -> response \| None` | Translate or absorb a failure. Return `None` to re-raise. Catches `Exception` (not `BaseException`), so `asyncio.CancelledError` propagates. |

The [phase decorator recipes](recipes/phase-decorator-patterns.md) have an example for each decorator: bearer-token injection, a correlation ID from `contextvars`, a status-class counter, and a `NetworkError` fallback.

### Worked example: request-ID propagation

This `RequestIdMiddleware` gives each call a UUID, sends it as a header, and logs it with the response status, so you can follow one request across services.

```python
import logging
import uuid

import httpx2

from httpware import AsyncClient, AsyncRetry
from httpware import AsyncNext


_LOGGER = logging.getLogger("myapp.request_id")


class RequestIdMiddleware:
    """Assign a per-call X-Request-Id and log it with the response status.

    Place it before AsyncRetry so every attempt of one call shares the ID.
    """

    def __init__(self, *, header: str = "X-Request-Id") -> None:
        self._header = header

    async def __call__(self, request: httpx2.Request, next: AsyncNext) -> httpx2.Response:  # noqa: A002
        request_id = str(uuid.uuid4())
        request.headers[self._header] = request_id
        response = await next(request)
        _LOGGER.info(
            "request complete",
            extra={"request_id": request_id, "status": response.status_code},
        )
        return response


async def main() -> None:
    async with AsyncClient(
        base_url="https://api.example.com",
        middleware=[RequestIdMiddleware(), AsyncRetry()],  # ID outside AsyncRetry
    ) as client:
        await client.get("/users/1")
```

The example logs under `myapp.request_id`. Keep your middleware's logs in your application's namespace: `httpware.*` is reserved for the library's own loggers, whose names are a stable contract (see [Observability](observability.md)).

A `retry.giving_up` record from `httpware.retry` carries the call's `url`, and this middleware logged an `X-Request-Id` for the same call. Joining the two in your log aggregator tells you which request gave up after its retries.

### Enriching the active span

httpware calls only get a span once you set up the OTel SDK and `opentelemetry-instrumentation-httpx`; [Wiring OpenTelemetry](observability.md#wiring-opentelemetry) shows how. With a span active, your middleware can add to it the same way the built-in resilience middleware do:

```python
import httpx2
from opentelemetry import trace

from httpware import AsyncNext


class SpanEnrichingMiddleware:
    async def __call__(self, request: httpx2.Request, next: AsyncNext) -> httpx2.Response:  # noqa: A002
        response = await next(request)
        trace.get_current_span().set_attribute("myapp.tenant_id", request.headers.get("X-Tenant-Id", ""))
        return response
```

When no span is active, `get_current_span()` returns a `NonRecordingSpan` whose `set_attribute` and `add_event` do nothing, so the call is always safe.

### Sync middleware

A sync `Client` takes sync middleware, which has the same shape without `async`:

```python
from httpware import Middleware, Next, before_request, after_response, on_error
```

`Middleware` is a structural protocol, so any callable with the right signature works:

```python
import logging

import httpx2

from httpware import Client
from httpware import Next


_LOGGER = logging.getLogger("myapp.logging_middleware")


class LoggingMiddleware:
    def __call__(self, request: httpx2.Request, next: Next) -> httpx2.Response:  # noqa: A002
        _LOGGER.info("-> %s %s", request.method, request.url)
        response = next(request)
        _LOGGER.info("<- %s", response.status_code)
        return response


with Client(base_url="https://api.example.com", middleware=[LoggingMiddleware()]) as client:
    client.get("/users/1")
```

`@before_request`, `@after_response` and `@on_error` behave like their `@async_*` versions but wrap sync functions:

```python
import uuid

import httpx2

from httpware import Client, before_request


@before_request
def add_request_id(request: httpx2.Request) -> httpx2.Request:
    return httpx2.Request(
        request.method,
        request.url,
        headers={**request.headers, "X-Request-ID": uuid.uuid4().hex},
        content=request.content,
    )


with Client(base_url="https://api.example.com", middleware=[add_request_id]) as client:
    client.get("/users/1")
```

Sync and async middleware don't mix: pass `Middleware` to `Client` and `AsyncMiddleware` to `AsyncClient`.

## See also

- [Resilience](resilience.md): the built-in middleware and the order to compose them in.
- [`src/httpware/middleware/resilience/`](https://github.com/modern-python/httpware/tree/main/src/httpware/middleware/resilience): the built-in middleware's source, written against this same protocol.

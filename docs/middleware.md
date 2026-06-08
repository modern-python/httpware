# Writing custom middleware

`httpware`'s primary extension point is the **AsyncMiddleware protocol**. Middleware lets you add cross-cutting behavior — request-ID propagation, auth header injection, structured tracing, custom resilience policies, anything that wraps "send a request, get a response" — without subclassing `AsyncClient` or touching the transport.

The built-in `AsyncRetry` and `AsyncBulkhead` middleware are themselves implementations of this protocol; nothing about them is privileged. If you want a circuit breaker, a rate limiter, or a header-injecting auth layer, write a middleware. If your need is per-call (not cross-cutting), pass it through `request.extensions=` instead.

## The protocol

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

- **Forward unchanged:** `return await next(request)`
- **Modify the request first:** mutate `request.headers` (or build a replacement) before forwarding
- **Inspect or replace the response:** call `await next(...)`, then act on what comes back
- **Short-circuit:** return a synthesized `httpx2.Response` without calling `next` at all
- **Wrap the call in error handling:** `try: return await next(...) except ...` to translate failures

Whatever you do, return an `httpx2.Response`. Raising an exception propagates up the chain (AsyncRetry catches retryable exceptions; everything else surfaces to the caller).

## Phase decorators

For the common cases where you don't need state-keeping on `self` and don't need to wrap the full `await next(...)` call, `httpware.middleware` exports three decorators that turn a single async function into an `AsyncMiddleware`:

```python
from httpware.middleware import async_before_request, async_after_response, async_on_error
```

| Decorator | Function signature | When to use |
|---|---|---|
| `@async_before_request` | `async (request) -> request` | Transform the outgoing request (add a header, rewrite a URL). |
| `@async_after_response` | `async (request, response) -> response` | Transform the incoming response (decode, log, attach metadata). |
| `@async_on_error` | `async (request, exc) -> response \| None` | Translate or absorb a failure. Return `None` to re-raise. Catches `Exception` (not `BaseException`), so `asyncio.CancelledError` propagates. |

See the **[Phase decorator recipes](recipes/phase-decorator-patterns.md)** for worked examples covering each decorator: bearer-token injection, correlation-ID propagation from `contextvars`, status-class counter, and `NetworkError` fallback.

**Reach for the raw `AsyncMiddleware` protocol when:** you need instance state (a counter, a CircuitBreaker's open/closed flag), you need to inspect both the request AND its response (e.g., timing), or you need to interleave behavior around the `await next(...)` call (e.g., emit one log line at the start and one at the end). The decorators are a convenience for the cases where a single function suffices.

**Reach for `httpx2.event_hooks` instead when:** the transform doesn't need `httpware`'s exception mapping or chain ordering — pure request/response side effects at the lowest level. Phase decorators participate in the `httpware` middleware chain (they see `httpware` exceptions and compose with `AsyncRetry`/`AsyncBulkhead`); `event_hooks` run a layer below, on every transport attempt including post-redirect hops. For static header injection or response logging that doesn't care about either property, a hook installed on the wrapped `httpx2_client` is the simpler tool.

## Worked example: request-ID propagation

A `RequestIdMiddleware` that assigns a per-call UUID, injects it as an outgoing header, and logs it alongside the response status. This is the canonical "trace every request through your distributed system" pattern.

```python
import logging
import uuid

import httpx2

from httpware import AsyncClient, AsyncRetry
from httpware.middleware import AsyncNext


_LOGGER = logging.getLogger("myapp.request_id")


class RequestIdMiddleware:
    """Assign a per-call X-Request-Id; log it on response.

    Place OUTSIDE AsyncRetry so all attempts of the same call share one ID
    (so a single call's retries all surface under the same correlation
    key in your logs, and match the URL attribute on httpware.retry's
    emitted events).
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

A note on logger names: the example logs under `myapp.request_id`, NOT under `httpware.*`. The `httpware.*` namespace is reserved for events emitted by the library itself (see [Observability](index.md#observability) — `httpware.retry` and `httpware.bulkhead` are stable contracts). Consumer middleware should use your application's own logger namespace.

The example pairs naturally with the 0.6.0 observability events: a `httpware.retry` `retry.giving_up` log record carries a `url` attribute, and your `RequestIdMiddleware` set an `X-Request-Id` for that same call. Correlate the two in your log aggregator and you have end-to-end visibility from "this user's request" to "we gave up after N retries."

## When NOT to write a middleware

- **Redaction:** Use a `logging.Filter` on the consumer side. `httpware` deliberately does no redaction in-library (per the 0.6.0 observability design).
- **URL or header validation:** `httpx2` owns it. Don't reimplement.
- **Per-call behavior that doesn't apply to other calls:** Pass through `request.extensions=` (or the `extensions=` kwarg at the call site) instead. Middleware exists for *cross-cutting* concerns.
- **HTTP-level span creation for tracing:** Install `opentelemetry-instrumentation-httpx` instead of writing an OTel middleware in httpware. We retired story `5-4` (standalone OTel middleware) for this reason — `opentelemetry-instrumentation-httpx` already covers transport-level tracing, and a separate httpware layer would duplicate it. See `planning/engineering.md` §8.

## Wiring OpenTelemetry

`httpware[otel]` only ships `opentelemetry-api`. To make the observability events emitted by `AsyncRetry` and `AsyncBulkhead` visible, you also need:

- An **SDK** (`opentelemetry-sdk`) to actually collect spans
- An **HTTP instrumentor** (`opentelemetry-instrumentation-httpx`) so each HTTP call creates a span — `httpware`'s events attach to that span via `trace.get_current_span().add_event(...)`

Minimal setup (console exporter for development):

```python
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

trace.set_tracer_provider(TracerProvider())
trace.get_tracer_provider().add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
HTTPXClientInstrumentor().instrument()
```

After this runs, every `httpware` HTTP call gets an `HTTP <method>` span from the instrumentor, and AsyncRetry/AsyncBulkhead observability events appear as span events on it (no extra configuration needed in `httpware` itself — the events fire whenever an active span is present).

For production, swap `ConsoleSpanExporter` for your OTLP/Jaeger/Zipkin exporter. See the [OpenTelemetry Python docs](https://opentelemetry.io/docs/languages/python/) for the full SDK setup.

## Sync middleware

The same protocol shape, sync flavor. Use these when wiring middleware into a sync `Client` instead of `AsyncClient`.

```python
from httpware import Middleware, Next, before_request, after_response, on_error
```

A sync `Middleware` is a structural protocol — any callable with the right signature satisfies it:

```python
import logging

import httpx2

from httpware import Client
from httpware.middleware import Next


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

Phase decorators (`@before_request`, `@after_response`, `@on_error`) have the same semantics as their `@async_*` siblings, but wrap sync functions:

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

Sync and async middleware classes do not interop: a `Middleware` cannot be passed to `AsyncClient(middleware=...)` and vice versa. Pick the flavor matching your client.

## See also

- **`planning/engineering.md` §3 (Seam A)** — the formal protocol contract and why the chain is frozen at construction.
- **`src/httpware/middleware/resilience/`** — `AsyncRetry`, `AsyncBulkhead`, `RetryBudget` as real-world consumers of this exact protocol.
- **[Quick-Start composition example](index.md#with-resilience-middleware)** — composing built-in middleware.

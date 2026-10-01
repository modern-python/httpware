<div class="mp-hero" markdown>

<h1 class="mp-lockup">
<img class="mp-logo mp-logo--light" src="assets/lockup-light.svg" alt="httpware">
<img class="mp-logo mp-logo--dark" src="assets/lockup-dark.svg" alt="" aria-hidden="true">
</h1>

</div>

httpware wraps `httpx2` to give you sync and async clients for calling other services. It adds a middleware chain with built-in retry, bulkhead, circuit breaker and timeout, optional typed response decoding, and an exception per HTTP status raised automatically on 4xx and 5xx. Requests and responses are plain `httpx2.Request` and `httpx2.Response` objects.

> **Status:** Pre-1.0. Public API is subject to change between minor releases until v1.0.

## Install

```bash
pip install httpware
```

Optional extras:

```bash
pip install httpware[pydantic]           # PydanticDecoder: BaseModel, dataclasses, primitives, generics
pip install httpware[msgspec]            # MsgspecDecoder: Struct, dataclasses, primitives, generics
pip install httpware[pydantic,msgspec]   # both; BaseModel goes to pydantic, Struct to msgspec
pip install httpware[otel]               # OpenTelemetry span events
pip install httpware[all]                # pydantic, msgspec, and otel
```

## First request

Async:

```python
import asyncio

from httpware import AsyncClient


async def main() -> None:
    async with AsyncClient(base_url="https://jsonplaceholder.typicode.com") as client:
        response = await client.get("/users/1")
        print(response.json())


asyncio.run(main())
```

Sync:

```python
from httpware import Client

with Client(base_url="https://jsonplaceholder.typicode.com") as client:
    response = client.get("/users/1")
    print(response.json())
```

### Typed responses

Pass `response_model=` to get a decoded body instead of the response. It works the same way on both clients:

```python
from httpware import AsyncClient
from pydantic import BaseModel


class User(BaseModel):
    id: int
    name: str


async def main() -> None:
    async with AsyncClient(base_url="https://api.example.com") as client:
        user = await client.get("/users/1", response_model=User)
        print(user.name)
```

The client tries its `decoders` in order and uses the first one whose `can_decode` returns `True`, so list order decides which decoder wins when more than one could handle a type. If none can, the call raises `MissingDecoderError` before the request is sent. See [Decoders](decoders.md) for the resolution rules and how pydantic and msgspec types are routed.

To get the raw response and the decoded body from the same call, for example to read pagination headers, use `send_with_response`. The [Link header pagination](recipes/link-header-pagination.md) recipe shows it in a loop.

### With resilience middleware

Pass resilience middleware when you build the client. Put `AsyncBulkhead` before `AsyncRetry` so one slot covers all retry attempts of a call.

```python
from httpware import AsyncClient, AsyncBulkhead, AsyncRetry


async def main() -> None:
    async with AsyncClient(
        base_url="https://api.example.com",
        middleware=[
            AsyncBulkhead(max_concurrent=10),  # cap total in-flight
            AsyncRetry(),  # default: 3 attempts, full-jitter backoff
        ],
    ) as client:
        user = await client.get("/users/1", response_model=User)
```

[Resilience](resilience.md) has the full recommended order, including the circuit breaker and timeout.

### Streaming responses

For large responses or server-sent events, stream the body in chunks. `stream()` is an async context manager:

```python
from httpware import AsyncClient


async def main() -> None:
    async with AsyncClient(base_url="https://api.example.com") as client:
        async with client.stream("GET", "/big-file") as response:
            async for chunk in response.aiter_bytes():
                process(chunk)
```

`stream()` raises `StatusError` subclasses on 4xx and 5xx like every other call. It reads the error body first, so `exc.response.content` is available on the caught exception.

`stream()` does not go through the middleware chain: `AsyncRetry`, `AsyncBulkhead`, and your own middleware are all skipped. Separately, `AsyncRetry` never retries a request whose body was an async iterable, streamed or not, because the iterable cannot be replayed.

## Client options

`base_url` must not contain a query string; a client built with one raises `ValueError`. Put query parameters shared by every request in `params=` instead.

The other keywords of `httpx2.AsyncClient` and `httpx2.Client` (`verify`, `proxy`, `http2`, `transport`, `follow_redirects`, ...) are passed through to the `httpx2` client that httpware builds and closes. Two are refused. `cert` is deprecated by `httpx2` in favour of an `ssl.SSLContext` passed as `verify`. `event_hooks` run below the middleware chain, so use [middleware](middleware.md) instead.

```python
import ssl

from httpware import AsyncClient

client = AsyncClient(
    base_url="https://internal.example",
    verify=ssl.create_default_context(cafile="/etc/ssl/internal-ca.pem"),
)
```

To share one connection pool between several clients, build the `httpx2` client yourself and pass it as `httpx2_client=`. You then close it yourself, and you cannot combine it with any of the options above.

### Capping response body size

Both clients accept `max_response_body_bytes: int | None = None`. When it is set, a response body larger than the cap raises `ResponseTooLargeError` instead of being returned. The default, `None`, sets no limit. [Errors](errors.md#responsetoolargeerror) lists exactly when the cap applies.

## Errors and observability

Every exception httpware raises subclasses `httpware.ClientError`. A 4xx or 5xx response raises a `StatusError` subclass, and a body that fails `response_model=` decoding raises `DecodeError`. [Errors](errors.md) has the full tree.

The resilience middleware log through stdlib `logging` and, when `opentelemetry-api` is installed, add span events. Logger and event names are stable; [Observability](observability.md) lists them.

## Where to go next

- [Resilience](resilience.md): every parameter of retry, retry budget, bulkhead, circuit breaker and timeout, plus the order to compose them in.
- [Middleware](middleware.md): the middleware protocol, phase decorators, and a request-ID example.
- [Errors](errors.md): the exception tree, catching strategies, and what each exception carries.
- [Decoders](decoders.md): how `response_model=` picks a decoder, and how to write your own.
- [Observability](observability.md): logger and event names, and OpenTelemetry wiring.
- [Testing](testing.md): testing code that uses httpware with `httpx2.MockTransport`.
- [Recipes](recipes/modern-di.md): `modern-di` wiring, phase decorator patterns, Link header pagination.
- [Decision records](https://github.com/modern-python/httpware/tree/main/docs/adr): alternatives that were considered and rejected, and why.
- [Contributing](dev/contributing.md): setup, conventions, workflow.
- [Release notes](https://github.com/modern-python/httpware/releases): changes in each version.

## Part of `modern-python`

httpware is part of the [`modern-python`](https://github.com/modern-python) org. The org profile has the categorized index of related templates and libraries.

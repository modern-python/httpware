# httpware

A Python HTTP client framework with sync and async clients for building resilient service clients. `httpware` is a thin opinionated wrapper around `httpx2` — it re-exports `httpx2.Request`/`httpx2.Response` as the public request/response surface, adds a middleware chain (with a built-in resilience suite: `AsyncRetry`/`Retry` + `RetryBudget`, `AsyncBulkhead`/`Bulkhead`), opt-in typed response decoding, and a status-keyed exception tree raised automatically on 4xx/5xx.

## Why httpware

Typed exceptions per HTTP status, typed response bodies, and composable
resilience (retry, bulkhead, circuit breaker, timeout) — a thin wrapper over
`httpx2`, not a new HTTP abstraction. See the
[project README](https://github.com/modern-python/httpware#why-httpware) for
the full pitch.

> **Status:** Pre-1.0. Public API is subject to change between minor releases until v1.0.

## Install

```bash
pip install httpware
```

Optional extras:

```bash
pip install httpware[pydantic]   # PydanticDecoder — handles BaseModel + dataclasses + primitives + generics
pip install httpware[msgspec]    # MsgspecDecoder — handles Struct + dataclasses + primitives + generics
pip install httpware[pydantic,msgspec]   # both extras — both decoders register; BaseModel routes to pydantic, Struct to msgspec
```

## First request

**Async usage:**

```python
import asyncio

from httpware import AsyncClient

async def main() -> None:
    async with AsyncClient(base_url="https://jsonplaceholder.typicode.com") as client:
        response = await client.get("/users/1")
        print(response.json())

asyncio.run(main())
```

**Sync usage:**

```python
from httpware import Client

with Client(base_url="https://jsonplaceholder.typicode.com") as client:
    response = client.get("/users/1")
    print(response.json())
```

Typed decoding via `response_model=` works the same way in both worlds:

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

Need the raw response **and** a decoded body from the same call (e.g., for header-based pagination)? See [Link header pagination](recipes/link-header-pagination.md) — it uses `send_with_response`.

### Decoder dispatch

When `response_model=` is set, the client walks `decoders` in order and picks
the first decoder whose `can_decode(model)` returns `True`. Both built-in
decoders claim broadly within their library; the ordering encodes your
preference for shared shapes (`dict`, `list[Foo]`, dataclasses, primitives):

```python
from httpware import AsyncClient
from httpware.decoders.msgspec import MsgspecDecoder
from httpware.decoders.pydantic import PydanticDecoder

# pydantic-first (the default when both extras are installed):
# - BaseModel  -> pydantic
# - Struct     -> msgspec
# - dict, list -> pydantic (first in list)
AsyncClient(decoders=[PydanticDecoder(), MsgspecDecoder()])

# msgspec-first — same native routing, but shared shapes go to msgspec:
# - BaseModel  -> pydantic
# - Struct     -> msgspec
# - dict, list -> msgspec
AsyncClient(decoders=[MsgspecDecoder(), PydanticDecoder()])
```

If no registered decoder claims your `response_model`, the call raises
`MissingDecoderError` *before* the HTTP request — see the
[Errors reference](errors.md#missingdecodererror).

### With resilience middleware

Compose resilience middleware at construction; `AsyncBulkhead` goes outside `AsyncRetry` so one slot covers all retry attempts.

```python
from httpware import AsyncClient, AsyncBulkhead, AsyncRetry


async def main() -> None:
    async with AsyncClient(
        base_url="https://api.example.com",
        middleware=[
            AsyncBulkhead(max_concurrent=10),  # cap total in-flight
            AsyncRetry(),                       # default: 3 attempts, full-jitter backoff
        ],
    ) as client:
        user = await client.get("/users/1", response_model=User)
```

### Streaming responses

For large responses or server-sent events, stream the body chunk-by-chunk. `stream()` is an async context manager:

```python
from httpware import AsyncClient


async def main() -> None:
    async with AsyncClient(base_url="https://api.example.com") as client:
        async with client.stream("GET", "/big-file") as response:
            async for chunk in response.aiter_bytes():
                process(chunk)
```

`stream()` auto-raises `StatusError` subclasses on 4xx/5xx with the response body pre-read, so `exc.response.content` is accessible from the caught exception.

It does NOT pass through the middleware chain: `AsyncRetry`, `AsyncBulkhead`, and any custom middleware are bypassed. (AsyncRetry separately refuses to retry any request — stream or non-stream — whose body was an async-iterable, since streams can't replay across attempts.)

## Errors

All errors inherit `httpware.ClientError`. The categories:

- **Status errors** (4xx/5xx responses) — raised automatically, no `raise_for_status()` needed: `NotFoundError`, `RateLimitedError`, `ServiceUnavailableError`, and the rest. All subclass `StatusError`.
- **Transport errors** — connection / network / protocol failures before a response arrived. `NetworkError` (transient) subclasses `TransportError`.
- **Resilience refusals** — `RetryBudgetExhaustedError`, `BulkheadFullError`, and `CircuitOpenError`, raised by the resilience middleware.
- **Decode errors** — `DecodeError`, raised when `response_model=` decoding fails (HTTP call itself succeeded). `MissingDecoderError`, raised when no registered decoder claims the `response_model=` type — fires *before* the HTTP call.

See the [Errors reference](errors.md) for the full tree and catching strategies.

## Observability

All resilience middleware emit operational events via two channels — stdlib `logging` records (always on) and OpenTelemetry span events (when `opentelemetry-api` is installed). Event names and payloads are identical across sync and async; dashboards built against one class apply unchanged to the other.

Logger names and event names are the stable public contract:

| Logger | Events |
|---|---|
| `httpware.retry` | `retry.giving_up`, `retry.budget_refused`, `retry.streaming_refused` |
| `httpware.bulkhead` | `bulkhead.rejected` |
| `httpware.circuit_breaker` | `circuit.opened` (WARNING), `circuit.rejected` (WARNING), `circuit.half_open` (INFO), `circuit.closed` (INFO) |
| `httpware.timeout` | `timeout.exceeded` (WARNING) |

Each log record carries an `event` field with the event-name string (e.g. `event="circuit.opened"`), usable for log-aggregator filtering. See [resilience.md](resilience.md) for the full event tables per middleware.

```python
import logging

# Enable visibility into resilience operational events
logging.getLogger("httpware.retry").setLevel(logging.WARNING)
logging.getLogger("httpware.bulkhead").setLevel(logging.WARNING)
logging.getLogger("httpware.circuit_breaker").setLevel(logging.INFO)  # INFO for recovery events
logging.getLogger("httpware.timeout").setLevel(logging.WARNING)
```

For OTel attribute enrichment on the active span — install the extra:

```bash
pip install httpware[otel]
```

When installed, `_emit_event` calls `trace.get_current_span().add_event(name, attributes=...)` automatically. We never create our own spans; for HTTP-level tracing install `opentelemetry-instrumentation-httpx` separately.

## Where to go next

- **[Resilience reference](resilience.md)** — every parameter on `AsyncRetry`, `RetryBudget`, and `AsyncBulkhead`; the retry-rule matrix; Retry-After parsing; budget sharing.
- **[Middleware guide](middleware.md)** — write your own middleware. Covers the AsyncMiddleware Protocol, the phase decorators, a worked Request-ID propagation example, and OpenTelemetry wiring.
- **[Errors reference](errors.md)** — the full exception tree, catching strategies, `exc.response.*` access pattern.
- **[Testing guide](testing.md)** — mock-transport injection pattern for testing code that uses `httpware`.
- **[Recipes](recipes/modern-di.md)** — wiring `AsyncClient` into a `modern-di` container.
- **[Architecture Notes](https://github.com/modern-python/httpware/blob/main/architecture/overview.md)** — per-capability design notes — invariants, the three protocol seams, exception contract, module layout, testing patterns — under `architecture/`. Lives in the repo under `architecture/`.
- **[Contributing](dev/contributing.md)** — setup, conventions, workflow.
- **[Release notes](https://github.com/modern-python/httpware/releases)** — per-version changelogs.

## Part of `modern-python`

`httpware` ships under the [`modern-python`](https://github.com/modern-python) org. See the org profile for the categorized index of related templates and libraries.

# httpware

[![Test](https://github.com/modern-python/httpware/actions/workflows/ci.yml/badge.svg)](https://github.com/modern-python/httpware/actions/workflows/ci.yml)
[![PyPI version](https://badge.fury.io/py/httpware.svg)](https://pypi.org/project/httpware/)
[![Python versions](https://img.shields.io/pypi/pyversions/httpware.svg)](https://pypi.org/project/httpware/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**A Python HTTP client framework with sync and async clients for building resilient service clients.**

`httpware` is a thin opinionated wrapper around `httpx2`. It re-exports `httpx2.Request`/`httpx2.Response`, adds a middleware chain composed at client construction, supports opt-in typed response decoding (pydantic and msgspec are both extras), and raises a status-keyed exception tree automatically on 4xx/5xx. It also ships a resilience suite under `httpware.middleware.resilience` — `AsyncRetry`/`Retry` with a Finagle-style `RetryBudget`, `AsyncBulkhead`/`Bulkhead` concurrency limiter, `AsyncCircuitBreaker`/`CircuitBreaker` consecutive-failure breaker, and `AsyncTimeout` for overall-operation wall-clock bounds.

> **Status:** Pre-1.0. Public API is subject to change between minor releases until v1.0.

## Install

```bash
pip install httpware                # core only — no decoder
pip install httpware[pydantic]      # + PydanticDecoder — handles BaseModel + dataclasses + primitives + generics
pip install httpware[msgspec]       # + MsgspecDecoder — handles Struct + dataclasses + primitives + generics
pip install httpware[pydantic,msgspec]   # both extras — both decoders register; BaseModel routes to pydantic, Struct to msgspec
pip install httpware[all]           # everything declared above (pydantic, msgspec, otel)
```

`AsyncClient()` resolves `decoders=None` against installed extras: pydantic if installed (first), msgspec if installed (second), or an empty tuple if neither. `AsyncClient()` never raises on missing extras — failure is deferred to the first `response_model=` call, where `MissingDecoderError` fires *before* the HTTP request if no registered decoder claims the model.

## Quickstart

**Async usage:**

```python
import asyncio

from httpware import AsyncClient

async def main() -> None:
    async with AsyncClient(base_url="https://example.test") as client:
        response = await client.get("/users/42")
        print(response.json())

asyncio.run(main())
```

**Sync usage:**

```python
from httpware import Client

with Client(base_url="https://example.test") as client:
    response = client.get("/users/42")
    print(response.json())
```

Typed decoding via `response_model=` works in both worlds — install either `pip install httpware[pydantic]` or `pip install httpware[msgspec]` (or both; pydantic is tried first when both are present). Decode failures (malformed body, schema mismatch) raise `httpware.DecodeError`, a `ClientError` subclass — so `except httpware.ClientError` covers them alongside transport and status errors.

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

### With resilience middleware

Compose resilience middleware at construction; `AsyncBulkhead` goes outside `AsyncRetry` so one slot covers all retry attempts.

The sync `Client` accepts identical `middleware=[...]`; swap `AsyncClient` → `Client` and `AsyncRetry` → `Retry` for the sync version.

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

Need a custom middleware (auth, tracing, request-ID propagation, etc.)? See the [Middleware guide](https://httpware.modern-python.org/middleware/).

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

All 4xx/5xx responses raise typed exceptions automatically: `NotFoundError`, `ServiceUnavailableError`, `RateLimitedError`, etc. — all subclasses of `httpware.StatusError`. Transport-layer transient failures raise `NetworkError`; the resilience middleware raise `RetryBudgetExhaustedError`, `BulkheadFullError`, and `CircuitOpenError`. Everything inherits `httpware.ClientError`.

## Observability

All resilience middleware emit operational events via two channels — stdlib `logging` records (always on) and OpenTelemetry span events (when `opentelemetry-api` is installed). Event names and payloads are identical across sync and async; dashboards built against one class apply unchanged to the other.

Logger names and event names are the stable public contract: `httpware.retry` (`retry.giving_up`, `retry.budget_refused`, `retry.streaming_refused`), `httpware.bulkhead` (`bulkhead.rejected`), `httpware.circuit_breaker` (`circuit.opened`, `circuit.rejected`, `circuit.half_open`, `circuit.closed`), and `httpware.timeout` (`timeout.exceeded`).

```python
import logging

# Enable visibility into resilience operational events
logging.getLogger("httpware.retry").setLevel(logging.WARNING)
logging.getLogger("httpware.bulkhead").setLevel(logging.WARNING)
logging.getLogger("httpware.circuit_breaker").setLevel(logging.INFO)   # INFO: includes recovery events (half_open, closed)
logging.getLogger("httpware.timeout").setLevel(logging.WARNING)
```

For OTel attribute enrichment on the active span — install the extra:

```bash
pip install httpware[otel]
```

When installed, `_emit_event` calls `trace.get_current_span().add_event(name, attributes=...)` automatically. We never create our own spans; for HTTP-level tracing install `opentelemetry-instrumentation-httpx` separately.

## 📚 [Documentation](https://httpware.modern-python.org)

## 🗒️ [Release notes](https://github.com/modern-python/httpware/releases)

## 📦 [PyPI](https://pypi.org/project/httpware)

## 📝 [License](https://github.com/modern-python/httpware/blob/main/LICENSE)

## Part of `modern-python`

Browse the full list of templates and libraries in [`modern-python`](https://github.com/modern-python) — see the org profile for the categorized index.

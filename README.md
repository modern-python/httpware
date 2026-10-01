<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)"  srcset="https://raw.githubusercontent.com/modern-python/.github/main/brand/projects/httpware/lockup-dark.svg">
    <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/modern-python/.github/main/brand/projects/httpware/lockup-light.svg">
    <img alt="httpware" src="https://raw.githubusercontent.com/modern-python/.github/main/brand/projects/httpware/lockup.png" width="420">
  </picture>
</p>

[![PyPI version](https://img.shields.io/pypi/v/httpware.svg)](https://pypi.org/project/httpware/)
[![Supported Python versions](https://img.shields.io/pypi/pyversions/httpware.svg)](https://pypi.org/project/httpware/)
[![Downloads](https://static.pepy.tech/badge/httpware/month)](https://pepy.tech/projects/httpware)
[![Coverage](https://img.shields.io/badge/coverage-100%25-brightgreen.svg)](https://github.com/modern-python/httpware/actions/workflows/ci.yml)
[![CI](https://github.com/modern-python/httpware/actions/workflows/ci.yml/badge.svg)](https://github.com/modern-python/httpware/actions/workflows/ci.yml)
[![License](https://img.shields.io/github/license/modern-python/httpware.svg)](https://github.com/modern-python/httpware/blob/main/LICENSE)
[![GitHub stars](https://img.shields.io/github/stars/modern-python/httpware)](https://github.com/modern-python/httpware/stargazers)
[![Context7](https://img.shields.io/badge/Context7-docs-blue)](https://context7.com/modern-python/httpware)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![ty](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ty/main/assets/badge/v0.json)](https://github.com/astral-sh/ty)

Typed, resilient HTTP clients for Python, sync and async.

## Why httpware

- A 4xx or 5xx response raises an exception named after its status, such as
  `NotFoundError` for 404 or `RateLimitedError` for 429. All of them subclass
  `httpware.StatusError`, so you never call `raise_for_status()`.
- `response_model=User` decodes the body into your pydantic or msgspec type.
  If no installed decoder handles the type, the call fails before the request
  is sent.
- Retry with a retry budget, bulkhead, circuit breaker, and timeout ship as
  middleware you compose per client.

httpware is a thin layer over `httpx2`: requests and responses are plain
`httpx2.Request` and `httpx2.Response` objects.

> **Status:** Pre-1.0. Public API is subject to change between minor releases until v1.0.

## Install

```bash
pip install httpware                     # core only, no decoder
pip install httpware[pydantic]           # PydanticDecoder: BaseModel, dataclasses, primitives, generics
pip install httpware[msgspec]            # MsgspecDecoder: Struct, dataclasses, primitives, generics
pip install httpware[pydantic,msgspec]   # both; BaseModel goes to pydantic, Struct to msgspec
pip install httpware[otel]               # OpenTelemetry span events
pip install httpware[all]                # pydantic, msgspec, and otel
```

## Quickstart

A typed GET against a live API (needs `pip install httpware[pydantic]`):

```python
import asyncio

from httpware import AsyncClient
from pydantic import BaseModel


class User(BaseModel):
    id: int
    name: str


async def main() -> None:
    async with AsyncClient(base_url="https://jsonplaceholder.typicode.com") as client:
        user = await client.get("/users/1", response_model=User)
        print(user.name)  # Leanne Graham


asyncio.run(main())
```

The sync `Client` works the same way: use `Client` instead of `AsyncClient`, and drop `await` and `async with`. A 4xx/5xx response raises a typed `StatusError`; a malformed body raises `DecodeError`. Both subclass `httpware.ClientError`.

## Documentation

Full guides live at [httpware.modern-python.org](https://httpware.modern-python.org):

- [Quickstart](https://httpware.modern-python.org/): first requests, client options, streaming.
- [Resilience](https://httpware.modern-python.org/resilience/): retry and retry budget, bulkhead, circuit breaker, timeout.
- [Errors](https://httpware.modern-python.org/errors/): the exception tree and how to catch it.
- [Decoders](https://httpware.modern-python.org/decoders/): typed response bodies and custom decoders.
- [Middleware](https://httpware.modern-python.org/middleware/): writing your own (auth, tracing, request IDs).
- [Observability](https://httpware.modern-python.org/observability/): logger and event names, OpenTelemetry wiring.
- [Testing](https://httpware.modern-python.org/testing/): injecting `httpx2.MockTransport`.
- [Recipes](https://httpware.modern-python.org/recipes/modern-di/): DI wiring, phase decorators, Link header pagination.

## 🗒️ [Release notes](https://github.com/modern-python/httpware/releases) · 📦 [PyPI](https://pypi.org/project/httpware) · 📝 [License](https://github.com/modern-python/httpware/blob/main/LICENSE)

## Part of `modern-python`

Browse the full list of templates and libraries in
[`modern-python`](https://github.com/modern-python); the org profile has the categorized index.

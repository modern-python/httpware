# httpware

[![PyPI version](https://img.shields.io/pypi/v/httpware.svg)](https://pypi.org/project/httpware/)
[![Supported Python versions](https://img.shields.io/pypi/pyversions/httpware.svg)](https://pypi.org/project/httpware/)
[![Downloads](https://img.shields.io/pypi/dm/httpware.svg)](https://pypistats.org/packages/httpware)
[![Coverage](https://img.shields.io/badge/coverage-100%25-brightgreen.svg)](https://github.com/modern-python/httpware/actions/workflows/ci.yml)
[![CI](https://github.com/modern-python/httpware/actions/workflows/ci.yml/badge.svg)](https://github.com/modern-python/httpware/actions/workflows/ci.yml)
[![License](https://img.shields.io/github/license/modern-python/httpware.svg)](https://github.com/modern-python/httpware/blob/main/LICENSE)
[![GitHub stars](https://img.shields.io/github/stars/modern-python/httpware)](https://github.com/modern-python/httpware/stargazers)
[![Context7](https://img.shields.io/badge/Context7-docs-blue)](https://context7.com/modern-python/httpware)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![ty](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ty/main/assets/badge/v0.json)](https://github.com/astral-sh/ty)

**A Python HTTP client framework with sync and async clients for building resilient service clients.**

## Why httpware

- **Typed errors, no `raise_for_status()`** — 4xx/5xx automatically raise a status-keyed exception tree (`NotFoundError`, `RateLimitedError`, …), all under `httpware.StatusError`.
- **Typed response bodies** — `response_model=YourType` decodes the body straight to your pydantic or msgspec model; a missing decoder fails fast, *before* the request goes out.
- **Production resilience as composable middleware** — retry + retry-budget, bulkhead, circuit breaker, and timeout, composed at construction — all over standard `httpx2`.

Built on `httpx2`: httpware re-exports `httpx2.Request`/`httpx2.Response` and stays a thin wrapper, not a new HTTP abstraction.

> **Status:** Pre-1.0. Public API is subject to change between minor releases until v1.0.

## Install

```bash
pip install httpware                # core only — no decoder
pip install httpware[pydantic]      # + PydanticDecoder — BaseModel, dataclasses, primitives, generics
pip install httpware[msgspec]       # + MsgspecDecoder — Struct, dataclasses, primitives, generics
pip install httpware[pydantic,msgspec]   # both — BaseModel routes to pydantic, Struct to msgspec
pip install httpware[all]           # everything (pydantic, msgspec, otel)
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

The sync `Client` is identical — swap `AsyncClient` → `Client` and drop the `await` / `async with`. A 4xx/5xx response raises a typed `StatusError`; a malformed body raises `DecodeError`. Both subclass `httpware.ClientError`.

## Documentation

Full guides live at **[httpware.modern-python.org](https://httpware.modern-python.org)**:

- **[Quickstart & observability](https://httpware.modern-python.org/)** — resilience middleware, streaming, and the stable logger/event contract.
- **[Middleware](https://httpware.modern-python.org/middleware/)** — write your own (auth, tracing, request-ID propagation).
- **[Resilience](https://httpware.modern-python.org/resilience/)** — retry + retry-budget, bulkhead, circuit breaker, timeout.
- **[Errors](https://httpware.modern-python.org/errors/)** — the exception tree and catching strategies.
- **[Testing](https://httpware.modern-python.org/testing/)** — `httpx2.MockTransport` injection.
- **[Recipes](https://httpware.modern-python.org/recipes/modern-di/)** — DI wiring, phase-decorator patterns, link-header pagination.

## 🗒️ [Release notes](https://github.com/modern-python/httpware/releases) · 📦 [PyPI](https://pypi.org/project/httpware) · 📝 [License](LICENSE)

## Part of `modern-python`

Browse the full list of templates and libraries in
[`modern-python`](https://github.com/modern-python) — see the org profile for the categorized index.

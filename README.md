# httpware

[![Test](https://github.com/modern-python/httpware/actions/workflows/ci.yml/badge.svg)](https://github.com/modern-python/httpware/actions/workflows/ci.yml)
[![PyPI version](https://badge.fury.io/py/httpware.svg)](https://pypi.org/project/httpware/)
[![Python versions](https://img.shields.io/pypi/pyversions/httpware.svg)](https://pypi.org/project/httpware/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Async HTTP client framework for Python.**

`httpware` is a typed, async HTTP client library built on `httpx2` with a protocol-based seam so the transport is swappable. Middleware composes via an onion model. Pydantic and msgspec response decoding ship out of the box. `RecordedTransport` replaces respx for transport-level tests.

> **Status:** Pre-1.0 (0.1.0 alpha). Public API is subject to change between minor releases until v1.0. Resilience middleware (retry / timeout / bulkhead), streaming, and observability are not yet shipped — track progress on GitHub.

## Install

```bash
pip install httpware
```

Optional extras:

```bash
pip install httpware[msgspec]    # MsgspecDecoder
```

(`otel`, `niquests`, and `all` extras are declared but their integrations have not shipped yet.)

## Quickstart

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

## What ships in 0.1.0

- **`AsyncClient`** — eight HTTP method shortcuts (`get`, `post`, `put`, `patch`, `delete`, `head`, `options`, `request`) with typed `response_model` overloads; per-call overrides for `headers`, `params`, `cookies`, `timeout`, `json`, `content`; httpx-style `base_url` join; `with_options(...)` returns a view sharing the same transport.
- **Transport-agnostic seam.** `httpx2` is confined to `httpware.transports.httpx2.Httpx2Transport`. Implement the `Transport` protocol to swap backends.
- **Middleware foundation.** `Middleware` protocol, `Next` type alias, and phase decorators (`@before_request`, `@after_response`, `@on_error`). The chain is composed at `AsyncClient` construction; consumers don't compose chains themselves.
- **Pluggable response decoding.** `PydanticDecoder` (default) with cached `TypeAdapter`; `MsgspecDecoder` via `httpware[msgspec]`.
- **`RecordedTransport`** — built-in test double with a route table, observed-request list, and `aclose_calls` counter.
- **Status-keyed exception hierarchy** — `StatusError`, 4xx / 5xx subclasses, plain typed fields (`status: int`, `body: bytes`, `headers`, `json`, `request_method`, `request_url`). Pickleable; userinfo redacted in `__repr__`.
- **No `httpx2` exception types** leak through `httpware`. The transport seam maps them to `httpware` exceptions.

## Part of `modern-python`

Browse the full list of templates and libraries in [`modern-python`](https://github.com/modern-python) — see the org profile for the categorized index.

## License

MIT — see [LICENSE](./LICENSE).

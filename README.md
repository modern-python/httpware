# httpware

[![Test](https://github.com/modern-python/httpware/actions/workflows/ci.yml/badge.svg)](https://github.com/modern-python/httpware/actions/workflows/ci.yml)
[![PyPI version](https://badge.fury.io/py/httpware.svg)](https://pypi.org/project/httpware/)
[![Python versions](https://img.shields.io/pypi/pyversions/httpware.svg)](https://pypi.org/project/httpware/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Async HTTP client framework for Python.**

`httpware` is a typed, async HTTP client library with a protocol-based seam so the transport is swappable (`httpx2` ships as the default). Middleware composes via an onion model. Pydantic and msgspec response decoding ship out of the box. `RecordedTransport` replaces `respx` for transport-level tests.

> **Status:** Pre-1.0 (0.1.0 alpha). Public API is subject to change between minor releases until v1.0. Resilience middleware (retry / timeout / bulkhead), streaming, and observability are not yet shipped.

## Install

```bash
pip install httpware
```

Optional extras:

```bash
pip install httpware[msgspec]    # MsgspecDecoder
```

(`otel`, `niquests`, and `all` extras are declared; integrations have not shipped yet.)

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

## 📚 [Documentation](https://httpware.readthedocs.io)

## 📦 [PyPI](https://pypi.org/project/httpware)

## 📝 [License](./LICENSE)

## Part of `modern-python`

Browse the full list of templates and libraries in [`modern-python`](https://github.com/modern-python) — see the org profile for the categorized index.

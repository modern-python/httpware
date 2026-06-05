# httpware

[![Test](https://github.com/modern-python/httpware/actions/workflows/ci.yml/badge.svg)](https://github.com/modern-python/httpware/actions/workflows/ci.yml)
[![PyPI version](https://badge.fury.io/py/httpware.svg)](https://pypi.org/project/httpware/)
[![Python versions](https://img.shields.io/pypi/pyversions/httpware.svg)](https://pypi.org/project/httpware/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Async HTTP client framework for Python.**

`httpware` is a thin opinionated wrapper around `httpx2`. It re-exports `httpx2.Request`/`httpx2.Response`, adds a middleware chain composed at client construction, supports opt-in typed response decoding (pydantic and msgspec are both extras), and raises a status-keyed exception tree automatically on 4xx/5xx.

> **Status:** Pre-1.0 (0.3.0). Public API is subject to change between minor releases until v1.0. Resilience middleware (retry / timeout / bulkhead), streaming, and observability are not yet shipped.

## Install

```bash
pip install httpware                # core only — no decoder
pip install httpware[pydantic]      # + PydanticDecoder (the default-decoder path)
pip install httpware[msgspec]       # + MsgspecDecoder
pip install httpware[all]           # everything declared above (pydantic, msgspec)
```

`AsyncClient()` with no `decoder=` argument defaults to constructing a `PydanticDecoder`; that path requires the `pydantic` extra and raises `ImportError` at `AsyncClient.__init__` if it is missing.

## Quickstart

> Requires: `pip install httpware[pydantic]`

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

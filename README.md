# httpware

[![Test](https://github.com/modern-python/httpware/actions/workflows/ci.yml/badge.svg)](https://github.com/modern-python/httpware/actions/workflows/ci.yml)
[![PyPI version](https://badge.fury.io/py/httpware.svg)](https://pypi.org/project/httpware/)
[![Python versions](https://img.shields.io/pypi/pyversions/httpware.svg)](https://pypi.org/project/httpware/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Resilience-first async HTTP client framework for Python.**

`httpware` is to Python what Polly is to .NET and resilience4j is to the JVM — a canonical resilience-first HTTP framework. The public API is transport-agnostic (the underlying client is `httpx2` by default, sitting behind a swappable `Transport` protocol). Retries, timeouts, bulkheads, and a Finagle-style **retry budget** ship as composable middleware. Tests use a `RecordedTransport` and never see the underlying client.

> **Status:** Pre-1.0. Public API is subject to change between minor releases until v1.0. See [CHANGELOG.md](./CHANGELOG.md).

## Install

```bash
pip install httpware
```

Optional extras:

```bash
pip install httpware[msgspec]    # msgspec ResponseDecoder
pip install httpware[otel]       # OpenTelemetry instrumentation
pip install httpware[all]        # all of the above
```

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

## Highlights

- **Transport-agnostic API.** No `httpx2` symbols leak through `httpware`. Swap to a different backend with one constructor argument.
- **Onion middleware** with phase shortcuts (`@before_request`, `@after_response`, `@on_error`). Built-in middleware: `Retry`, `RetryBudget`, `Bulkhead`, `Timeout`, `Observability`.
- **Retry budget by default** — token-bucket admission control (Finagle defaults). Caps retry storms before they happen.
- **Pluggable validation.** Default pydantic decoder with cached `TypeAdapter`; msgspec decoder via extras; bring your own.
- **`RecordedTransport` for tests.** A 3-line fixture replaces respx routes and transport-level mocking.
- **Status-keyed exceptions** with plain fields (`status: int`, `body: bytes`, `headers`, `json`). No transport exception types in user code.
- **First-class OpenTelemetry** instrumentation via `httpware[otel]`.

## Documentation

Full docs (in progress): https://httpware.readthedocs.io

## License

MIT — see [LICENSE](./LICENSE).

# httpware

A Python async HTTP client framework for building resilient service clients. `httpware` is a thin opinionated wrapper around `httpx2` — it re-exports `httpx2.Request`/`httpx2.Response` as the public request/response surface, adds a middleware chain (with a built-in resilience suite: `Retry` + `RetryBudget`, `Bulkhead`), opt-in typed response decoding, and a status-keyed exception tree raised automatically on 4xx/5xx.

> **Status:** Pre-1.0. Public API is subject to change between minor releases until v1.0. Streaming and observability are not yet shipped.

## Install

```bash
pip install httpware
```

Optional extras:

```bash
pip install httpware[pydantic]   # PydanticDecoder (the default decoder path)
pip install httpware[msgspec]    # MsgspecDecoder
```

## First request

```python
import asyncio

from httpware import AsyncClient
from pydantic import BaseModel


class User(BaseModel):
    id: int
    name: str


async def main() -> None:
    async with AsyncClient(base_url="https://api.example.com") as client:
        user = await client.get("/users/1", response_model=User)
        print(user.name)


asyncio.run(main())
```

### With resilience middleware

Compose resilience middleware at construction; `Bulkhead` goes outside `Retry` so one slot covers all retry attempts.

```python
from httpware import AsyncClient, Bulkhead, Retry


async def main() -> None:
    async with AsyncClient(
        base_url="https://api.example.com",
        middleware=[
            Bulkhead(max_concurrent=10),  # cap total in-flight
            Retry(),                       # default: 3 attempts, full-jitter backoff
        ],
    ) as client:
        user = await client.get("/users/1", response_model=User)
```

## Errors

All 4xx/5xx responses raise typed exceptions automatically: `NotFoundError`, `ServiceUnavailableError`, `RateLimitedError`, etc. — all subclasses of `httpware.StatusError`. Transport-layer transient failures raise `NetworkError`; the resilience middleware raise `RetryBudgetExhaustedError` and `BulkheadFullError`. Everything inherits `httpware.ClientError`.

## Where to go next

- **[Engineering Notes](https://github.com/modern-python/httpware/blob/main/planning/engineering.md)** — design invariants, the three protocol seams, exception contract, module layout, testing patterns, optional-extras pattern. Lives in the repo at `planning/engineering.md`.
- **[Contributing](dev/contributing.md)** — setup, conventions, workflow.
- **[Release notes](https://github.com/modern-python/httpware/releases)** — per-version changelogs.

## Part of `modern-python`

`httpware` ships under the [`modern-python`](https://github.com/modern-python) org. See the org profile for the categorized index of related templates and libraries.

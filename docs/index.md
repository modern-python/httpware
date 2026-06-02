# httpware

A Python async HTTP client framework for building resilient service clients. `httpware` owns the abstraction layer above the underlying HTTP client (`httpx2` by default); consumers never import the transport directly.

> **Status:** Pre-1.0 (0.1.0 alpha). Public API is subject to change between minor releases until v1.0.

## Install

```bash
pip install httpware
```

Optional extras:

```bash
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

## Where to go next

- **[Engineering Notes](dev/engineering.md)** — design invariants, the five protocol seams, exception contract, module layout, testing patterns, optional-extras pattern.
- **[Contributing](dev/contributing.md)** — setup, conventions, workflow.

## Part of `modern-python`

`httpware` ships under the [`modern-python`](https://github.com/modern-python) org. See the org profile for the categorized index of related templates and libraries.

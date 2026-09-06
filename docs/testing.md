# Testing guide

`httpware`'s test seam is `httpx2`. Pass any `httpx2.AsyncClient` (including one built on `httpx2.MockTransport`) to `AsyncClient(httpx2_client=...)` — the middleware chain still runs end-to-end, only the wire is mocked. No special test mode, no monkey-patching, no `respx`.

`httpx2_client=` is mutually exclusive with `base_url`, `headers`, `params`, `cookies`, `timeout`, `limits`, and `auth`: passing any of those alongside a pre-built `httpx2_client=` raises `TypeError`. Configure the `httpx2.AsyncClient`/`httpx2.Client` you pass instead.

## The basic pattern

```python
from http import HTTPStatus

import httpx2

from httpware import AsyncClient


def handler(request: httpx2.Request) -> httpx2.Response:
    return httpx2.Response(HTTPStatus.OK, json={"id": 1, "name": "Alice"})


async def test_get_user() -> None:
    transport = httpx2.MockTransport(handler)
    async with AsyncClient(httpx2_client=httpx2.AsyncClient(transport=transport)) as client:
        response = await client.get("https://api.example.test/users/1")
    assert response.status_code == HTTPStatus.OK
    assert response.json()["name"] == "Alice"
```

The handler can be sync or async; `httpx2.MockTransport` supports both. The test above uses a sync handler.

If you use `pytest-asyncio` in auto-mode (`asyncio_mode = "auto"` under `[tool.pytest.ini_options]`), async test functions don't need the `@pytest.mark.asyncio` decorator.

### Sync `Client`

The same pattern works for the sync `Client` — pass an `httpx2.Client` (not `httpx2.AsyncClient`) built on `httpx2.MockTransport`:

```python
from http import HTTPStatus

import httpx2

from httpware import Client


def test_get_returns_typed_response() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(HTTPStatus.OK, request=request, json={"ok": True})

    with Client(httpx2_client=httpx2.Client(transport=httpx2.MockTransport(handler))) as client:
        response = client.get("https://example.test/x")

    assert response.status_code == HTTPStatus.OK
    assert response.json() == {"ok": True}
```

## Recording / stateful handlers

For tests that need to vary the response by call count or assert on the requests that came in, use a handler with instance state:

```python
from httpware import AsyncRetry


class _ResponseSequence:
    """Returns each status in order; records every request received."""

    def __init__(self, statuses: list[int]) -> None:
        self._statuses = list(statuses)
        self.calls: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.calls.append(request)
        status = self._statuses.pop(0) if self._statuses else HTTPStatus.OK
        return httpx2.Response(status, request=request)


async def test_retry_succeeds_after_503() -> None:
    handler = _ResponseSequence([HTTPStatus.SERVICE_UNAVAILABLE, HTTPStatus.OK])
    transport = httpx2.MockTransport(handler)
    async with AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=transport),
        middleware=[AsyncRetry(base_delay=0.001, max_delay=0.002)],
    ) as client:
        response = await client.get("https://example.test/x")
    assert response.status_code == HTTPStatus.OK
    assert len(handler.calls) == 2  # initial + 1 retry
```

The `base_delay`/`max_delay` are set tiny so the test runs instantly — no need for `freezegun` or sleep injection in most cases.

## Testing your custom middleware

Compose your middleware with the mock transport to exercise the chain end-to-end:

```python
async def test_my_middleware_adds_header() -> None:
    handler = _ResponseSequence([HTTPStatus.OK])
    async with AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
        middleware=[MyHeaderMiddleware()],
    ) as client:
        await client.get("https://example.test/x")
    assert handler.calls[0].headers["X-My-Header"] == "expected-value"
```

For middleware with state-keeping (counters, circuit-breaker state), assert on instance attributes after running the call.

## Why not `respx`?

`httpware` deliberately uses `httpx2.MockTransport` instead of `respx` for its own tests. `MockTransport` is a first-party `httpx2` API — supported by the maintainers, stable across versions, part of the public API surface. `respx` targets the original `httpx` package (its README requires `httpx 0.25+`, with no stated `httpx2` support) and has a documented history of breaking across `httpx` major-version bumps, since it patches `httpx`/`httpcore` internals directly. Stick with `MockTransport` unless you have a specific reason not to.

## See also

- **[Middleware guide](middleware.md)** — write the middleware you're testing.
- **[Resilience reference](resilience.md)** — testing `AsyncRetry`/`AsyncBulkhead` configurations.
- **`AGENTS.md`** — the project's own testing conventions, and the admission check that decides where a new fact belongs.

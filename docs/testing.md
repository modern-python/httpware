# Testing guide

To test code that uses httpware, pass an `httpx2.MockTransport` as `AsyncClient(transport=...)`. Only the network is replaced: the middleware chain runs as usual, and the client still creates and closes its `httpx2` client.

You can pass a ready-made `httpx2.AsyncClient` or `httpx2.Client` as `httpx2_client=` instead. It can't be combined with any `httpx2` client option (`base_url`, `headers`, `transport`, `verify`, ...); passing one raises `TypeError`. Configure the client you pass, and close it yourself, since httpware won't.

## The basic pattern

```python
from http import HTTPStatus

import httpx2

from httpware import AsyncClient


def handler(request: httpx2.Request) -> httpx2.Response:
    return httpx2.Response(HTTPStatus.OK, json={"id": 1, "name": "Alice"})


async def test_get_user() -> None:
    async with AsyncClient(transport=httpx2.MockTransport(handler)) as client:
        response = await client.get("https://api.example.test/users/1")
    assert response.status_code == HTTPStatus.OK
    assert response.json()["name"] == "Alice"
```

The handler can be sync, as above, or async.

If you use `pytest-asyncio` in auto mode (`asyncio_mode = "auto"` under `[tool.pytest.ini_options]`), async test functions don't need the `@pytest.mark.asyncio` decorator.

### Sync `Client`

The same works for the sync `Client`:

```python
from http import HTTPStatus

import httpx2

from httpware import Client


def test_get_returns_typed_response() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(HTTPStatus.OK, request=request, json={"ok": True})

    with Client(transport=httpx2.MockTransport(handler)) as client:
        response = client.get("https://example.test/x")

    assert response.status_code == HTTPStatus.OK
    assert response.json() == {"ok": True}
```

## Recording / stateful handlers

To change the response from call to call, or to check the requests that were sent, give the handler some state:

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
    async with AsyncClient(
        transport=httpx2.MockTransport(handler),
        middleware=[AsyncRetry(base_delay=0.001, max_delay=0.002)],
    ) as client:
        response = await client.get("https://example.test/x")
    assert response.status_code == HTTPStatus.OK
    assert len(handler.calls) == 2  # initial + 1 retry
```

The tiny `base_delay` and `max_delay` keep the test fast, so you usually don't need `freezegun` or a fake sleep.

## Testing your custom middleware

Run your middleware against the mock transport to test it inside the real chain:

```python
async def test_my_middleware_adds_header() -> None:
    handler = _ResponseSequence([HTTPStatus.OK])
    async with AsyncClient(
        transport=httpx2.MockTransport(handler),
        middleware=[MyHeaderMiddleware()],
    ) as client:
        await client.get("https://example.test/x")
    assert handler.calls[0].headers["X-My-Header"] == "expected-value"
```

For middleware that keeps state, such as a counter, assert on its attributes after the call.

## Why not `respx`?

httpware's own tests use `httpx2.MockTransport`, which is part of `httpx2`'s public API. `respx` is built for the original `httpx` package: its README requires `httpx 0.25+` and says nothing about `httpx2`. It also patches `httpx` and `httpcore` internals, which has broken it across `httpx` major versions before.

## See also

- [Middleware](middleware.md): writing the middleware you're testing.
- [Resilience](resilience.md): the parameters of the middleware you're configuring.

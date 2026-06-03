"""Tests for the Middleware protocol, Next type, chain composition, and decorators."""

import asyncio

import httpx2
import pytest

from httpware.middleware import (
    Middleware,
    Next,
    after_response,
    before_request,
    on_error,
)
from httpware.middleware.chain import compose


def _make_request(url: str = "https://example.test/x") -> httpx2.Request:
    return httpx2.Request("GET", url)


_STATUS_OK = 200
_STATUS_UPGRADED = 299
_STATUS_SERVICE_UNAVAILABLE = 503


def _make_response(status: int = _STATUS_OK, *, request: httpx2.Request | None = None) -> httpx2.Response:
    if request is None:
        request = _make_request()
    return httpx2.Response(status, request=request)


async def test_middleware_protocol_is_runtime_checkable() -> None:
    class _OkMiddleware:
        async def __call__(self, request: httpx2.Request, next: Next) -> httpx2.Response:  # noqa: A002
            return await next(request)

    assert isinstance(_OkMiddleware(), Middleware)


async def test_empty_chain_calls_terminal_directly() -> None:
    seen: list[httpx2.Request] = []

    async def terminal(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return _make_response(200, request=request)

    dispatch = compose((), terminal)
    request = _make_request()
    response = await dispatch(request)
    assert response.status_code == _STATUS_OK
    assert seen == [request]


async def test_chain_runs_middleware_in_order() -> None:
    order: list[str] = []

    class _M:
        def __init__(self, label: str) -> None:
            self.label = label

        async def __call__(self, request: httpx2.Request, next: Next) -> httpx2.Response:  # noqa: A002
            order.append(f"{self.label}.before")
            response = await next(request)
            order.append(f"{self.label}.after")
            return response

    async def terminal(request: httpx2.Request) -> httpx2.Response:
        order.append("terminal")
        return _make_response(200, request=request)

    dispatch = compose((_M("a"), _M("b")), terminal)
    await dispatch(_make_request())
    assert order == ["a.before", "b.before", "terminal", "b.after", "a.after"]


async def test_before_request_decorator_transforms_request() -> None:
    @before_request
    async def add_header(request: httpx2.Request) -> httpx2.Request:
        return httpx2.Request(request.method, request.url, headers={**request.headers, "X-Custom": "1"})

    captured: list[httpx2.Request] = []

    async def terminal(request: httpx2.Request) -> httpx2.Response:
        captured.append(request)
        return _make_response(200, request=request)

    dispatch = compose((add_header,), terminal)
    await dispatch(_make_request())
    assert captured[0].headers["x-custom"] == "1"


async def test_after_response_decorator_transforms_response() -> None:
    @after_response
    async def upgrade_status(request: httpx2.Request, response: httpx2.Response) -> httpx2.Response:
        return httpx2.Response(299, request=request, headers=response.headers, content=response.content)

    async def terminal(request: httpx2.Request) -> httpx2.Response:
        return _make_response(200, request=request)

    dispatch = compose((upgrade_status,), terminal)
    response = await dispatch(_make_request())
    assert response.status_code == _STATUS_UPGRADED


async def test_on_error_decorator_can_translate_exception() -> None:
    @on_error
    async def swallow(request: httpx2.Request, exc: Exception) -> httpx2.Response | None:
        if isinstance(exc, RuntimeError) and str(exc) == "boom":
            return _make_response(503, request=request)
        return None

    async def terminal(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        msg = "boom"
        raise RuntimeError(msg)

    dispatch = compose((swallow,), terminal)
    response = await dispatch(_make_request())
    assert response.status_code == _STATUS_SERVICE_UNAVAILABLE


async def test_on_error_returns_none_reraises() -> None:
    @on_error
    async def passthrough(
        request: httpx2.Request,  # noqa: ARG001
        exc: Exception,  # noqa: ARG001
    ) -> httpx2.Response | None:
        return None

    async def terminal(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        msg = "boom"
        raise RuntimeError(msg)

    dispatch = compose((passthrough,), terminal)
    with pytest.raises(RuntimeError, match="boom"):
        await dispatch(_make_request())


async def test_on_error_lets_cancelled_propagate() -> None:
    @on_error
    async def swallow_all(
        request: httpx2.Request,  # noqa: ARG001
        exc: Exception,  # noqa: ARG001
    ) -> httpx2.Response | None:
        msg = "should not catch CancelledError"
        raise AssertionError(msg)

    async def terminal(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        raise asyncio.CancelledError

    dispatch = compose((swallow_all,), terminal)
    with pytest.raises(asyncio.CancelledError):
        await dispatch(_make_request())

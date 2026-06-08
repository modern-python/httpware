"""Tests for the AsyncMiddleware protocol, AsyncNext type, chain composition, and decorators."""

import asyncio
import typing
from http import HTTPStatus

import httpx2
import pytest

from httpware.middleware import (
    AsyncMiddleware,
    AsyncNext,
    async_after_response,
    async_before_request,
    async_on_error,
)
from httpware.middleware.chain import compose, compose_async


def _make_request(url: str = "https://example.test/x") -> httpx2.Request:
    return httpx2.Request("GET", url)


def _make_response(status: int = HTTPStatus.OK, *, request: httpx2.Request | None = None) -> httpx2.Response:
    if request is None:  # pragma: no cover
        request = _make_request()
    return httpx2.Response(status, request=request)


async def test_middleware_protocol_is_runtime_checkable() -> None:
    class _OkMiddleware:
        async def __call__(self, request: httpx2.Request, next: AsyncNext) -> httpx2.Response:  # noqa: A002  # pragma: no cover
            return await next(request)

    assert isinstance(_OkMiddleware(), AsyncMiddleware)


async def test_empty_chain_calls_terminal_directly() -> None:
    seen: list[httpx2.Request] = []

    async def terminal(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return _make_response(200, request=request)

    dispatch = compose_async((), terminal)
    request = _make_request()
    response = await dispatch(request)
    assert response.status_code == HTTPStatus.OK
    assert seen == [request]


async def test_chain_runs_middleware_in_order() -> None:
    order: list[str] = []

    class _M:
        def __init__(self, label: str) -> None:
            self.label = label

        async def __call__(self, request: httpx2.Request, next: AsyncNext) -> httpx2.Response:  # noqa: A002
            order.append(f"{self.label}.before")
            response = await next(request)
            order.append(f"{self.label}.after")
            return response

    async def terminal(request: httpx2.Request) -> httpx2.Response:
        order.append("terminal")
        return _make_response(200, request=request)

    dispatch = compose_async((_M("a"), _M("b")), terminal)
    await dispatch(_make_request())
    assert order == ["a.before", "b.before", "terminal", "b.after", "a.after"]


async def test_before_request_decorator_transforms_request() -> None:
    @async_before_request
    async def add_header(request: httpx2.Request) -> httpx2.Request:
        return httpx2.Request(request.method, request.url, headers={**request.headers, "X-Custom": "1"})

    captured: list[httpx2.Request] = []

    async def terminal(request: httpx2.Request) -> httpx2.Response:
        captured.append(request)
        return _make_response(200, request=request)

    dispatch = compose_async((add_header,), terminal)
    await dispatch(_make_request())
    assert captured[0].headers["x-custom"] == "1"


async def test_after_response_decorator_transforms_response() -> None:
    @async_after_response
    async def upgrade_status(request: httpx2.Request, response: httpx2.Response) -> httpx2.Response:
        return httpx2.Response(HTTPStatus.IM_USED, request=request, headers=response.headers, content=response.content)

    async def terminal(request: httpx2.Request) -> httpx2.Response:
        return _make_response(HTTPStatus.OK, request=request)

    dispatch = compose_async((upgrade_status,), terminal)
    response = await dispatch(_make_request())
    assert response.status_code == HTTPStatus.IM_USED


async def test_on_error_decorator_can_translate_exception() -> None:
    @async_on_error
    async def swallow(request: httpx2.Request, exc: Exception) -> httpx2.Response | None:
        if isinstance(exc, RuntimeError) and str(exc) == "boom":
            return _make_response(HTTPStatus.SERVICE_UNAVAILABLE, request=request)
        return None  # pragma: no cover

    async def terminal(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        msg = "boom"
        raise RuntimeError(msg)

    dispatch = compose_async((swallow,), terminal)
    response = await dispatch(_make_request())
    assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE


async def test_on_error_returns_none_reraises() -> None:
    @async_on_error
    async def passthrough(
        request: httpx2.Request,  # noqa: ARG001
        exc: Exception,  # noqa: ARG001
    ) -> httpx2.Response | None:
        return None

    async def terminal(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        msg = "boom"
        raise RuntimeError(msg)

    dispatch = compose_async((passthrough,), terminal)
    with pytest.raises(RuntimeError, match="boom"):
        await dispatch(_make_request())


def test_before_request_repr() -> None:
    @async_before_request
    async def my_transform(request: httpx2.Request) -> httpx2.Request:
        return request  # pragma: no cover

    assert "async_before_request" in repr(my_transform)
    assert "my_transform" in repr(my_transform)


def test_after_response_repr() -> None:
    @async_after_response
    async def my_transform(request: httpx2.Request, response: httpx2.Response) -> httpx2.Response:  # noqa: ARG001
        return response  # pragma: no cover

    assert "async_after_response" in repr(my_transform)
    assert "my_transform" in repr(my_transform)


def test_on_error_repr() -> None:
    @async_on_error
    async def my_handler(request: httpx2.Request, exc: Exception) -> httpx2.Response | None:  # noqa: ARG001
        return None  # pragma: no cover

    assert "async_on_error" in repr(my_handler)
    assert "my_handler" in repr(my_handler)


async def test_on_error_lets_cancelled_propagate() -> None:
    @async_on_error
    async def swallow_all(
        request: httpx2.Request,  # noqa: ARG001
        exc: Exception,  # noqa: ARG001
    ) -> httpx2.Response | None:  # pragma: no cover
        msg = "should not catch CancelledError"
        raise AssertionError(msg)

    async def terminal(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        raise asyncio.CancelledError

    dispatch = compose_async((swallow_all,), terminal)
    with pytest.raises(asyncio.CancelledError):
        await dispatch(_make_request())


def test_compose_async_get_type_hints_resolves_without_nameerror() -> None:
    """typing.get_type_hints(compose_async) must resolve to real classes, not raise NameError.

    Pre-0.8.5: AsyncMiddleware was imported only under `if typing.TYPE_CHECKING`,
    so get_type_hints raised NameError at runtime.
    """
    hints = typing.get_type_hints(compose_async)
    assert "middleware" in hints


def test_compose_get_type_hints_resolves_without_nameerror() -> None:
    """Sync mirror — sync `compose` get_type_hints must also resolve."""
    hints = typing.get_type_hints(compose)
    assert "middleware" in hints

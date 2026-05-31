"""Tests for the Middleware protocol and chain composition."""

from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from typing import get_type_hints

from httpware._internal.chain import compose
from httpware.middleware import Middleware, Next
from httpware.request import Request
from httpware.response import Response, StreamResponse


class _SignalMiddleware:
    """Minimal valid Middleware implementation used by tests."""

    async def __call__(self, request: Request, next: Next) -> Response:  # noqa: A002
        return await next(request)


def test_runtime_checkable_isinstance_works() -> None:
    """A class implementing `__call__` satisfies the Middleware Protocol at runtime."""
    # runtime_checkable checks for presence of __call__, not signature details
    assert isinstance(_SignalMiddleware(), Middleware)


def test_next_type_alias_resolves_to_callable() -> None:
    """`Next` resolves to `Callable[[Request], Awaitable[Response]]`."""
    expected = Callable[[Request], Awaitable[Response]]
    assert Next == expected


def test_next_annotation_on_signal_middleware() -> None:
    """`next` parameter on `_SignalMiddleware.__call__` is annotated with `Next`."""
    hints = get_type_hints(_SignalMiddleware.__call__)
    assert hints["next"] == Next


class _OkTransport:
    """Minimal Transport: returns a fixed Response, no streaming, no aclose work."""

    async def __call__(self, request: Request) -> Response:
        return Response(
            status=200,
            headers={"x-from": "transport"},
            content=b"transport",
            url=request.url,
            elapsed=0.0,
        )

    def stream(  # pragma: no cover - not exercised in 2-1
        self, request: Request
    ) -> AbstractAsyncContextManager[StreamResponse]:
        raise NotImplementedError

    async def aclose(self) -> None:  # pragma: no cover - not exercised in 2-1
        return None


def _make_request(method: str = "GET", url: str = "https://example.test/") -> Request:
    return Request(method=method, url=url)


async def test_empty_list_composes_to_transport_call() -> None:
    """compose([], transport) yields a callable that behaves like transport(req)."""
    transport = _OkTransport()
    dispatch = compose([], transport)

    request = _make_request()
    response = await dispatch(request)

    assert response.status == 200  # noqa: PLR2004
    assert response.content == b"transport"
    assert response.headers["x-from"] == "transport"


async def test_single_middleware_wraps_transport() -> None:
    """One middleware sees the request, calls next, returns the transport's response unchanged."""
    seen: list[Request] = []

    class Tap:
        async def __call__(self, request: Request, next: Next) -> Response:  # noqa: A002
            seen.append(request)
            return await next(request)

    transport = _OkTransport()
    request = _make_request()

    response = await compose([Tap()], transport)(request)

    assert seen == [request]
    assert response.content == b"transport"

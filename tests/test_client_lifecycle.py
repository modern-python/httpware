"""Unit tests for AsyncClient lifecycle (__aenter__, __aexit__)."""

from contextlib import AbstractAsyncContextManager

from httpware import AsyncClient
from httpware.request import Request
from httpware.response import Response, StreamResponse


class _TrackingTransport:
    """Counts aclose() invocations."""

    def __init__(self) -> None:
        self.aclose_calls = 0

    async def __call__(self, request: Request) -> Response:  # pragma: no cover - not used
        raise NotImplementedError

    def stream(  # pragma: no cover - not used
        self, request: Request
    ) -> AbstractAsyncContextManager[StreamResponse]:
        raise NotImplementedError

    async def aclose(self) -> None:
        self.aclose_calls += 1


async def test_aenter_returns_self() -> None:
    transport = _TrackingTransport()
    client = AsyncClient(transport=transport)
    async with client as entered:
        assert entered is client


async def test_async_with_calls_aclose_on_exit() -> None:
    transport = _TrackingTransport()
    client = AsyncClient(transport=transport)
    async with client:
        pass
    assert transport.aclose_calls == 1


async def test_double_close_is_safe() -> None:
    transport = _TrackingTransport()
    client = AsyncClient(transport=transport)
    async with client:
        pass
    async with client:
        pass
    assert transport.aclose_calls == 2  # noqa: PLR2004


async def test_view_async_with_does_not_close_transport() -> None:
    transport = _TrackingTransport()
    client = AsyncClient(transport=transport)
    view = client.with_options(timeout=10)
    async with view:
        pass
    assert transport.aclose_calls == 0

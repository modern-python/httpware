"""Unit tests for AsyncClient lifecycle (__aenter__, __aexit__)."""

from httpware import AsyncClient, RecordedTransport


async def test_aenter_returns_self() -> None:
    transport = RecordedTransport()
    client = AsyncClient(transport=transport)
    async with client as entered:
        assert entered is client


async def test_async_with_calls_aclose_on_exit() -> None:
    transport = RecordedTransport()
    client = AsyncClient(transport=transport)
    async with client:
        pass
    assert transport.aclose_calls == 1


async def test_double_close_is_safe() -> None:
    transport = RecordedTransport()
    client = AsyncClient(transport=transport)
    async with client:
        pass
    async with client:
        pass
    assert transport.aclose_calls == 2  # noqa: PLR2004


async def test_view_async_with_does_not_close_transport() -> None:
    transport = RecordedTransport()
    client = AsyncClient(transport=transport)
    view = client.with_options(timeout=10)
    async with view:
        pass
    assert transport.aclose_calls == 0

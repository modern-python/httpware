"""Tests for AsyncClient.__aenter__/__aexit__ lifecycle and ownership."""

from http import HTTPStatus

import httpx2

from httpware import AsyncClient


async def test_aexit_closes_owned_httpx2_client() -> None:
    client = AsyncClient()
    async with client:
        pass
    assert client._httpx2_client.is_closed  # noqa: SLF001


async def test_aexit_does_not_close_borrowed_httpx2_client() -> None:
    transport = httpx2.MockTransport(lambda req: httpx2.Response(HTTPStatus.OK, request=req))
    underlying = httpx2.AsyncClient(transport=transport)
    client = AsyncClient(httpx2_client=underlying)
    async with client:
        pass
    assert not underlying.is_closed
    await underlying.aclose()


async def test_aexit_is_idempotent_for_owned_client() -> None:
    client = AsyncClient()
    async with client:
        pass
    # Second use should not raise — the boolean prevents a double-close on httpx2 internals.
    await client.__aexit__(None, None, None)

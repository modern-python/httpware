"""Tests for AsyncClient.__aenter__/__aexit__ lifecycle and ownership."""

from http import HTTPStatus

import httpx2
import pytest

from httpware import AsyncClient
from httpware.errors import TransportError


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


async def test_aclose_closes_owned_httpx2_client() -> None:
    client = AsyncClient()
    await client.aclose()
    assert client._httpx2_client.is_closed  # noqa: SLF001


async def test_aclose_is_idempotent_for_owned_client() -> None:
    client = AsyncClient()
    await client.aclose()
    # Second call must not raise — the boolean prevents a double-close on httpx2 internals.
    await client.aclose()
    assert client._httpx2_client.is_closed  # noqa: SLF001


async def test_runtimeerror_unrelated_to_close_propagates_unchanged() -> None:
    """A RuntimeError NOT caused by client closure must propagate as-is, not get mapped to TransportError.

    The OLD substring check `"closed" in str(exc)` would mis-classify any
    RuntimeError whose message happened to contain "closed".
    """
    msg = "downstream proxy hiccup — closed connection reset by peer"  # contains "closed" but client is open

    def _handler(_request: httpx2.Request) -> httpx2.Response:
        raise RuntimeError(msg)

    transport = httpx2.MockTransport(_handler)
    async with AsyncClient(httpx2_client=httpx2.AsyncClient(transport=transport)) as client:
        with pytest.raises(RuntimeError) as exc_info:
            await client.get("https://example.test/x")
        assert not isinstance(exc_info.value, TransportError), (
            f"RuntimeError was incorrectly mapped to TransportError: {exc_info.value!r}"
        )


async def test_runtimeerror_after_aclose_maps_to_transporterror() -> None:
    """After aclose(), sending raises a RuntimeError that should map to TransportError via is_closed."""
    # Use an owned client (no httpx2_client= arg) so aclose() also closes the httpx2 layer.
    client = AsyncClient()
    await client.aclose()
    with pytest.raises(TransportError):
        await client.get("https://example.test/x")

"""Tests for the AsyncClient internal terminal's exception mapping."""

from http import HTTPStatus

import httpx2
import pytest

from httpware import (
    AsyncClient,
    BadRequestError,
    ClientStatusError,
    InternalServerError,
    NotFoundError,
    RateLimitedError,
    ServerStatusError,
    StatusError,
    TimeoutError,  # noqa: A004
    TransportError,
)
from httpware.errors import NetworkError


def _client_with_handler(handler) -> AsyncClient:  # noqa: ANN001
    transport = httpx2.MockTransport(handler)
    return AsyncClient(httpx2_client=httpx2.AsyncClient(transport=transport))


async def test_terminal_returns_response_on_2xx() -> None:
    client = _client_with_handler(lambda req: httpx2.Response(HTTPStatus.OK, json={"ok": True}, request=req))
    response = await client.send(httpx2.Request("GET", "https://example.test/x"))
    assert response.status_code == HTTPStatus.OK
    assert response.json() == {"ok": True}


@pytest.mark.parametrize(
    ("status", "exc_type"),
    [
        (HTTPStatus.BAD_REQUEST, BadRequestError),
        (HTTPStatus.NOT_FOUND, NotFoundError),
        (HTTPStatus.TOO_MANY_REQUESTS, RateLimitedError),
        (HTTPStatus.INTERNAL_SERVER_ERROR, InternalServerError),
    ],
)
async def test_known_status_codes_raise_typed_subclass(status: int, exc_type: type[StatusError]) -> None:
    client = _client_with_handler(lambda req: httpx2.Response(status, request=req))
    with pytest.raises(exc_type) as info:
        await client.send(httpx2.Request("GET", "https://example.test/x"))
    assert info.value.response.status_code == status


async def test_unknown_4xx_falls_back_to_client_status_error() -> None:
    client = _client_with_handler(lambda req: httpx2.Response(HTTPStatus.IM_A_TEAPOT, request=req))
    with pytest.raises(ClientStatusError) as info:
        await client.send(httpx2.Request("GET", "https://example.test/x"))
    assert info.value.response.status_code == HTTPStatus.IM_A_TEAPOT
    assert type(info.value) is ClientStatusError


async def test_unknown_5xx_falls_back_to_server_status_error() -> None:
    client = _client_with_handler(lambda req: httpx2.Response(599, request=req))
    with pytest.raises(ServerStatusError) as info:
        await client.send(httpx2.Request("GET", "https://example.test/x"))
    assert info.value.response.status_code == 599  # noqa: PLR2004
    assert type(info.value) is ServerStatusError


async def test_3xx_does_not_raise() -> None:
    client = _client_with_handler(
        lambda req: httpx2.Response(HTTPStatus.MOVED_PERMANENTLY, request=req, headers={"location": "/y"})
    )
    response = await client.send(httpx2.Request("GET", "https://example.test/x"))
    assert response.status_code == HTTPStatus.MOVED_PERMANENTLY


async def test_httpx2_timeout_maps_to_httpware_timeout() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        msg = "read timeout"
        raise httpx2.ReadTimeout(msg)

    client = _client_with_handler(handler)
    with pytest.raises(TimeoutError, match="read timeout"):
        await client.send(httpx2.Request("GET", "https://example.test/x"))


async def test_httpx2_connect_error_maps_to_network_error() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        msg = "connect refused"
        raise httpx2.ConnectError(msg)

    client = _client_with_handler(handler)
    with pytest.raises(NetworkError, match="connect refused"):
        await client.send(httpx2.Request("GET", "https://example.test/x"))


async def test_httpx2_invalid_url_maps_to_transport_error() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        msg = "synthetic invalid URL from transport"
        raise httpx2.InvalidURL(msg)

    client = _client_with_handler(handler)
    with pytest.raises(TransportError, match="synthetic invalid URL"):
        await client.send(httpx2.Request("GET", "https://example.test/x"))


async def test_send_on_closed_client_raises_transport_error() -> None:
    transport = httpx2.MockTransport(lambda req: httpx2.Response(HTTPStatus.OK, request=req))
    underlying = httpx2.AsyncClient(transport=transport)
    client = AsyncClient(httpx2_client=underlying)
    await underlying.aclose()
    with pytest.raises(TransportError):
        await client.send(httpx2.Request("GET", "https://example.test/x"))


async def test_httpx2_decoding_error_maps_to_transport_error() -> None:
    """Non-transient HTTPError (e.g. DecodingError) maps to bare TransportError, not NetworkError."""

    def handler(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        msg = "decoding failed"
        raise httpx2.DecodingError(msg)

    client = _client_with_handler(handler)
    with pytest.raises(TransportError) as info:
        await client.send(httpx2.Request("GET", "https://example.test/x"))
    assert not isinstance(info.value, NetworkError)


async def test_httpx2_invalid_url_does_not_map_to_network_error() -> None:
    """Regression: only transient errors map to NetworkError; InvalidURL stays bare TransportError."""

    def handler(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        msg = "bad url"
        raise httpx2.InvalidURL(msg)

    client = _client_with_handler(handler)
    with pytest.raises(TransportError) as info:
        await client.send(httpx2.Request("GET", "https://example.test/x"))
    assert not isinstance(info.value, NetworkError)

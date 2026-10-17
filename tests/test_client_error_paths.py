"""Error paths that must behave the same on every entry point of both clients."""

import typing
from collections.abc import AsyncIterator, Iterator
from http import HTTPStatus

import httpx2
import pytest

from httpware import (
    AsyncClient,
    AsyncNext,
    AsyncRetry,
    Client,
    NetworkError,
    Next,
    Retry,
    ServiceUnavailableError,
    TransportError,
)
from httpware._internal.status import STREAMING_BODY_MARKER


_INVALID_URL = "https://example.test/\x00"
_REFUSAL_NOTE = "httpware: not retrying because the request body is a stream that cannot replay across attempts"


def _ok(request: httpx2.Request) -> httpx2.Response:
    return httpx2.Response(HTTPStatus.OK, request=request)


def _remote_protocol_error(request: httpx2.Request) -> httpx2.Response:
    msg = "peer closed connection without sending complete message body"
    raise httpx2.RemoteProtocolError(msg, request=request)


async def _no_sleep(_: float) -> None:
    return None


def _no_sleep_sync(_: float) -> None:
    return None


def _sync_chunks() -> Iterator[bytes]:
    yield b"chunk"


async def _async_chunks() -> AsyncIterator[bytes]:
    yield b"chunk"


class _Counting503:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.calls += 1
        request.read()
        return httpx2.Response(HTTPStatus.SERVICE_UNAVAILABLE, request=request)


class _AsyncCounting503:
    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.calls += 1
        await request.aread()
        return httpx2.Response(HTTPStatus.SERVICE_UNAVAILABLE, request=request)


async def test_async_remote_protocol_error_maps_to_network_error() -> None:
    client = AsyncClient(transport=httpx2.MockTransport(_remote_protocol_error))
    with pytest.raises(NetworkError, match="peer closed"):
        await client.get("https://example.test/x")


def test_sync_remote_protocol_error_maps_to_network_error() -> None:
    client = Client(transport=httpx2.MockTransport(_remote_protocol_error))
    with pytest.raises(NetworkError, match="peer closed"):
        client.get("https://example.test/x")


async def test_async_retry_retries_remote_protocol_error() -> None:
    calls: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append(request)
        if len(calls) == 1:
            return _remote_protocol_error(request)
        return _ok(request)

    client = AsyncClient(transport=httpx2.MockTransport(handler), middleware=[AsyncRetry(_sleep=_no_sleep)])
    response = await client.get("https://example.test/x")
    assert response.status_code == HTTPStatus.OK
    assert len(calls) == 2  # noqa: PLR2004


def test_sync_retry_retries_remote_protocol_error() -> None:
    calls: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append(request)
        if len(calls) == 1:
            return _remote_protocol_error(request)
        return _ok(request)

    client = Client(transport=httpx2.MockTransport(handler), middleware=[Retry(_sleep=_no_sleep_sync)])
    response = client.get("https://example.test/x")
    assert response.status_code == HTTPStatus.OK
    assert len(calls) == 2  # noqa: PLR2004


@pytest.mark.parametrize("method", ["get", "post", "put", "patch", "delete", "head", "options"])
async def test_async_invalid_url_on_verb_maps_to_transport_error(method: str) -> None:
    client = AsyncClient(transport=httpx2.MockTransport(_ok))
    with pytest.raises(TransportError, match="non-printable") as info:
        await getattr(client, method)(_INVALID_URL)
    assert not isinstance(info.value, NetworkError)
    assert isinstance(info.value.__cause__, httpx2.InvalidURL)


@pytest.mark.parametrize("method", ["get", "post", "put", "patch", "delete", "head", "options"])
def test_sync_invalid_url_on_verb_maps_to_transport_error(method: str) -> None:
    client = Client(transport=httpx2.MockTransport(_ok))
    with pytest.raises(TransportError, match="non-printable") as info:
        getattr(client, method)(_INVALID_URL)
    assert not isinstance(info.value, NetworkError)
    assert isinstance(info.value.__cause__, httpx2.InvalidURL)


async def test_async_invalid_url_on_request_and_with_response_maps_to_transport_error() -> None:
    client = AsyncClient(transport=httpx2.MockTransport(_ok))
    with pytest.raises(TransportError, match="non-printable"):
        await client.request("GET", _INVALID_URL)
    with pytest.raises(TransportError, match="non-printable"):
        await client.get_with_response(_INVALID_URL, response_model=dict)


def test_sync_invalid_url_on_request_and_with_response_maps_to_transport_error() -> None:
    client = Client(transport=httpx2.MockTransport(_ok))
    with pytest.raises(TransportError, match="non-printable"):
        client.request("GET", _INVALID_URL)
    with pytest.raises(TransportError, match="non-printable"):
        client.get_with_response(_INVALID_URL, response_model=dict)


async def test_async_stream_on_closed_client_raises_transport_error() -> None:
    client = AsyncClient(transport=httpx2.MockTransport(_ok))
    await client.aclose()
    with pytest.raises(TransportError, match="closed"):
        async with client.stream("GET", "https://example.test/x"):
            pass


def test_sync_stream_on_closed_client_raises_transport_error() -> None:
    client = Client(transport=httpx2.MockTransport(_ok))
    client.close()
    with pytest.raises(TransportError, match="closed"), client.stream("GET", "https://example.test/x"):
        pass


async def test_async_stream_runtime_error_on_open_client_propagates() -> None:
    client = AsyncClient(transport=httpx2.MockTransport(_ok))
    msg = "user code failed"
    with pytest.raises(RuntimeError, match=msg) as info:
        async with client.stream("GET", "https://example.test/x"):
            raise RuntimeError(msg)
    assert not isinstance(info.value, TransportError)


def test_sync_stream_runtime_error_on_open_client_propagates() -> None:
    client = Client(transport=httpx2.MockTransport(_ok))
    msg = "user code failed"
    with pytest.raises(RuntimeError, match=msg) as info, client.stream("GET", "https://example.test/x"):
        raise RuntimeError(msg)
    assert not isinstance(info.value, TransportError)


def _async_retry_client(handler: typing.Any) -> AsyncClient:  # noqa: ANN401
    return AsyncClient(
        transport=httpx2.MockTransport(handler),
        middleware=[AsyncRetry(_sleep=_no_sleep, retry_methods=frozenset({"POST"}))],
    )


def _sync_retry_client(handler: typing.Any) -> Client:  # noqa: ANN401
    return Client(
        transport=httpx2.MockTransport(handler),
        middleware=[Retry(_sleep=_no_sleep_sync, retry_methods=frozenset({"POST"}))],
    )


class _AsyncPassThrough:
    async def __call__(self, request: httpx2.Request, next: AsyncNext) -> httpx2.Response:  # noqa: A002
        return await next(request)


async def _async_function_middleware(request: httpx2.Request, next: AsyncNext) -> httpx2.Response:  # noqa: A002
    return await next(request)


async def _async_identity(request: httpx2.Request) -> httpx2.Request:
    return request


async def _async_response_identity(request: httpx2.Request, response: httpx2.Response) -> httpx2.Response:  # noqa: ARG001
    return response


async def _async_swallow(request: httpx2.Request, exc: Exception) -> httpx2.Response | None:  # noqa: ARG001
    return None


def _sync_function_middleware(request: httpx2.Request, next: Next) -> httpx2.Response:  # noqa: A002
    return next(request)

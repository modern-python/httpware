"""max_response_body_bytes — non-streaming send() cap + construction validation.

Covers both clients: the terminal buffers under the cap and fails fast with
ResponseTooLargeError when a response body (any status) exceeds it. stream()
coverage lives in tests/test_client_stream*.py.
"""

import datetime as dt
import gzip
from collections.abc import AsyncIterator
from http import HTTPStatus

import httpx2
import pytest

from httpware import AsyncClient, Client
from httpware.errors import ResponseTooLargeError


def _sync(handler: object, cap: int | None) -> Client:
    return Client(
        httpx2_client=httpx2.Client(transport=httpx2.MockTransport(handler)),  # ty: ignore[invalid-argument-type]
        max_response_body_bytes=cap,
    )


def _async(handler: object, cap: int | None) -> AsyncClient:
    return AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),  # ty: ignore[invalid-argument-type]
        max_response_body_bytes=cap,
    )


# ---- construction validation ----


@pytest.mark.parametrize("bad", [0, -1])
def test_async_rejects_cap_below_one(bad: int) -> None:
    with pytest.raises(ValueError, match="max_response_body_bytes must be >= 1"):
        AsyncClient(max_response_body_bytes=bad)


@pytest.mark.parametrize("bad", [0, -1])
def test_sync_rejects_cap_below_one(bad: int) -> None:
    with pytest.raises(ValueError, match="max_response_body_bytes must be >= 1"):
        Client(max_response_body_bytes=bad)


# ---- sync send() ----


def test_sync_send_within_cap_returns_response() -> None:
    body = b"hello world"

    def handler(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        return httpx2.Response(200, content=body)

    client = _sync(handler, 1000)
    request = client.build_request("GET", "https://example.test/x")
    assert client.send(request).content == body
    client.close()


def test_sync_send_over_cap_declared_on_success() -> None:
    body = b"x" * 200

    def handler(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        return httpx2.Response(200, content=body)

    client = _sync(handler, 10)
    request = client.build_request("GET", "https://example.test/x")
    with pytest.raises(ResponseTooLargeError) as caught:
        client.send(request)
    assert caught.value.reason == "declared"
    assert caught.value.status_code == 200  # noqa: PLR2004 — status-agnostic: a 200 trips
    client.close()


def test_sync_send_over_cap_streamed_gzip_bomb() -> None:
    raw = gzip.compress(b"A" * 100_000)

    def handler(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        return httpx2.Response(200, headers={"content-encoding": "gzip"}, content=raw)

    client = _sync(handler, 1000)
    request = client.build_request("GET", "https://example.test/x")
    with pytest.raises(ResponseTooLargeError) as caught:
        client.send(request)
    assert caught.value.reason == "streamed"
    client.close()


def test_sync_send_within_cap_gzip_returns_decoded() -> None:
    raw = gzip.compress(b"A" * 500)

    def handler(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        return httpx2.Response(200, headers={"content-encoding": "gzip"}, content=raw)

    client = _sync(handler, 1_000_000)
    request = client.build_request("GET", "https://example.test/x")
    assert client.send(request).content == b"A" * 500  # not re-decompressed/crashed
    client.close()


def test_sync_head_large_declared_length_not_rejected() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        return httpx2.Response(200, headers={"content-length": "50000000"})

    client = _sync(handler, 1000)
    request = client.build_request("HEAD", "https://example.test/x")
    response = client.send(request)
    assert response.content == b""
    assert response.headers["content-length"] == "50000000"
    client.close()


def test_sync_send_none_cap_unbounded() -> None:
    body = b"x" * 10_000

    def handler(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        return httpx2.Response(200, content=body)

    client = _sync(handler, None)
    request = client.build_request("GET", "https://example.test/x")
    assert client.send(request).content == body
    client.close()


# ---- async send() ----


async def test_async_send_within_cap_returns_response() -> None:
    body = b"hello world"

    def handler(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        return httpx2.Response(200, content=body)

    client = _async(handler, 1000)
    request = client.build_request("GET", "https://example.test/x")
    assert (await client.send(request)).content == body
    await client.aclose()


async def test_async_send_over_cap_declared() -> None:
    body = b"x" * 200

    def handler(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        return httpx2.Response(200, content=body)

    client = _async(handler, 10)
    request = client.build_request("GET", "https://example.test/x")
    with pytest.raises(ResponseTooLargeError) as caught:
        await client.send(request)
    assert caught.value.reason == "declared"
    await client.aclose()


async def test_async_send_over_cap_streamed_chunked() -> None:
    async def body() -> AsyncIterator[bytes]:
        yield b"a" * 50
        yield b"b" * 50

    def handler(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        return httpx2.Response(200, content=body())

    client = _async(handler, 70)
    request = client.build_request("GET", "https://example.test/x")
    with pytest.raises(ResponseTooLargeError) as caught:
        await client.send(request)
    assert caught.value.reason == "streamed"
    assert caught.value.content_length is None
    await client.aclose()


async def test_async_send_within_cap_gzip_returns_decoded() -> None:
    raw = gzip.compress(b"A" * 500)

    def handler(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        return httpx2.Response(200, headers={"content-encoding": "gzip"}, content=raw)

    client = _async(handler, 1_000_000)
    request = client.build_request("GET", "https://example.test/x")
    assert (await client.send(request)).content == b"A" * 500
    await client.aclose()


async def test_async_head_large_declared_length_not_rejected() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        return httpx2.Response(200, headers={"content-length": "50000000"})

    client = _async(handler, 1000)
    request = client.build_request("HEAD", "https://example.test/x")
    response = await client.send(request)
    assert response.content == b""
    assert response.headers["content-length"] == "50000000"
    await client.aclose()


async def test_async_send_none_cap_unbounded() -> None:
    body = b"x" * 10_000

    def handler(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        return httpx2.Response(200, content=body)

    client = _async(handler, None)
    request = client.build_request("GET", "https://example.test/x")
    assert (await client.send(request)).content == body
    await client.aclose()


# ---- response attributes kept with or without a cap ----


def _latin1_body(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
    return httpx2.Response(HTTPStatus.OK, headers={"content-type": "text/plain"}, content="café".encode("latin-1"))


def _streamed_body(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
    return httpx2.Response(HTTPStatus.OK, content=iter([b"hello"]))


async def _hello() -> AsyncIterator[bytes]:
    yield b"hello"


def _streamed_body_async(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
    return httpx2.Response(HTTPStatus.OK, content=_hello())


def _redirect(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
    return httpx2.Response(HTTPStatus.FOUND, headers={"location": "/next"})


@pytest.mark.parametrize("cap", [None, 1024])
def test_sync_response_keeps_elapsed_with_or_without_a_cap(cap: int | None) -> None:
    with Client(transport=httpx2.MockTransport(_streamed_body), max_response_body_bytes=cap) as client:
        response = client.get("https://example.test/x")
    assert response.elapsed >= dt.timedelta(0)


@pytest.mark.parametrize("cap", [None, 1024])
def test_sync_response_keeps_next_request_with_or_without_a_cap(cap: int | None) -> None:
    with Client(transport=httpx2.MockTransport(_redirect), max_response_body_bytes=cap) as client:
        response = client.get("https://example.test/x")
    assert response.next_request is not None
    assert str(response.next_request.url) == "https://example.test/next"


@pytest.mark.parametrize("cap", [None, 1024])
def test_sync_response_keeps_default_encoding_with_or_without_a_cap(cap: int | None) -> None:
    with Client(
        transport=httpx2.MockTransport(_latin1_body), default_encoding="latin-1", max_response_body_bytes=cap
    ) as client:
        response = client.get("https://example.test/x")
    assert response.text == "café"


@pytest.mark.parametrize("cap", [None, 1024])
async def test_async_response_keeps_elapsed_with_or_without_a_cap(cap: int | None) -> None:
    async with AsyncClient(transport=httpx2.MockTransport(_streamed_body_async), max_response_body_bytes=cap) as client:
        response = await client.get("https://example.test/x")
    assert response.elapsed >= dt.timedelta(0)


@pytest.mark.parametrize("cap", [None, 1024])
async def test_async_response_keeps_next_request_with_or_without_a_cap(cap: int | None) -> None:
    async with AsyncClient(transport=httpx2.MockTransport(_redirect), max_response_body_bytes=cap) as client:
        response = await client.get("https://example.test/x")
    assert response.next_request is not None
    assert str(response.next_request.url) == "https://example.test/next"


@pytest.mark.parametrize("cap", [None, 1024])
async def test_async_response_keeps_default_encoding_with_or_without_a_cap(cap: int | None) -> None:
    async with AsyncClient(
        transport=httpx2.MockTransport(_latin1_body), default_encoding="latin-1", max_response_body_bytes=cap
    ) as client:
        response = await client.get("https://example.test/x")
    assert response.text == "café"


@pytest.mark.parametrize("cap", [None, 1024])
def test_sync_response_keeps_num_bytes_downloaded_with_or_without_a_cap(cap: int | None) -> None:
    with Client(transport=httpx2.MockTransport(_streamed_body), max_response_body_bytes=cap) as client:
        response = client.get("https://example.test/x")
    assert response.num_bytes_downloaded == len(b"hello")


@pytest.mark.parametrize("cap", [None, 1024])
async def test_async_response_keeps_num_bytes_downloaded_with_or_without_a_cap(cap: int | None) -> None:
    async with AsyncClient(transport=httpx2.MockTransport(_streamed_body_async), max_response_body_bytes=cap) as client:
        response = await client.get("https://example.test/x")
    assert response.num_bytes_downloaded == len(b"hello")

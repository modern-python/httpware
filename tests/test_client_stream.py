"""Tests for AsyncClient.stream() context manager."""

import asyncio
import typing
from http import HTTPStatus

import httpx2
import pytest

from httpware import (
    AsyncClient,
    ClientStatusError,
    InternalServerError,
    NetworkError,
    NotFoundError,
    ResponseTooLargeError,
    ServerStatusError,
    ServiceUnavailableError,
    TransportError,
)
from httpware import (
    TimeoutError as HttpwareTimeoutError,
)
from httpware.client import _parse_content_length
from httpware.middleware import AsyncMiddleware, AsyncNext


_UNKNOWN_4XX = 418  # I'm a teapot
_UNKNOWN_5XX = 599
_REDIRECT_3XX = 301
_NOT_FOUND = 404
_SERVICE_UNAVAILABLE = 503


def _client(handler: typing.Callable[[httpx2.Request], httpx2.Response]) -> AsyncClient:
    transport = httpx2.MockTransport(handler)
    return AsyncClient(httpx2_client=httpx2.AsyncClient(transport=transport))


async def test_streams_response_body_successfully() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(HTTPStatus.OK, request=request, content=b"chunk1chunk2chunk3")

    client = _client(handler)
    async with client.stream("GET", "https://example.test/x") as response:
        assert response.status_code == HTTPStatus.OK
        chunks = [chunk async for chunk in response.aiter_bytes()]
    assert b"".join(chunks) == b"chunk1chunk2chunk3"


async def test_auto_raises_on_4xx_with_body_preread() -> None:
    body = b'{"error": "not found"}'

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(_NOT_FOUND, request=request, content=body)

    client = _client(handler)
    with pytest.raises(NotFoundError) as info:
        async with client.stream("GET", "https://example.test/missing"):
            pytest.fail("should have raised before reaching block body")
    assert info.value.response.status_code == _NOT_FOUND
    assert info.value.response.content == body  # body was pre-read; accessible


async def test_auto_raises_on_5xx_with_body_preread() -> None:
    body = b"degraded"

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(_SERVICE_UNAVAILABLE, request=request, content=body)

    client = _client(handler)
    with pytest.raises(ServiceUnavailableError) as info:
        async with client.stream("GET", "https://example.test/x"):
            pytest.fail("unreachable")
    assert info.value.response.content == body


async def test_auto_raises_unknown_4xx_falls_back_to_client_status_error() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(_UNKNOWN_4XX, request=request)

    client = _client(handler)
    with pytest.raises(ClientStatusError) as info:
        async with client.stream("GET", "https://example.test/x"):
            pytest.fail("unreachable")
    assert type(info.value) is ClientStatusError
    assert info.value.response.status_code == _UNKNOWN_4XX


async def test_auto_raises_unknown_5xx_falls_back_to_server_status_error() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(_UNKNOWN_5XX, request=request)

    client = _client(handler)
    with pytest.raises(ServerStatusError) as info:
        async with client.stream("GET", "https://example.test/x"):
            pytest.fail("unreachable")
    assert type(info.value) is ServerStatusError
    assert info.value.response.status_code == _UNKNOWN_5XX


async def test_3xx_does_not_raise() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(_REDIRECT_3XX, request=request, headers={"location": "/y"})

    client = _client(handler)
    async with client.stream("GET", "https://example.test/x") as response:
        assert response.status_code == _REDIRECT_3XX


async def test_network_error_during_request_maps_to_network_error() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        msg = "connect refused"
        raise httpx2.ConnectError(msg)

    client = _client(handler)
    with pytest.raises(NetworkError, match="connect refused"):
        async with client.stream("GET", "https://example.test/x"):
            pytest.fail("unreachable")


async def test_network_error_during_body_consumption_maps_to_network_error() -> None:
    async def streaming_body() -> typing.AsyncIterator[bytes]:
        yield b"first chunk"
        msg = "read failed mid-stream"
        raise httpx2.ReadError(msg)

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(HTTPStatus.OK, request=request, content=streaming_body())

    client = _client(handler)

    async def consume() -> None:
        async with client.stream("GET", "https://example.test/x") as response:
            async for _ in response.aiter_bytes():
                pass

    with pytest.raises(NetworkError, match="read failed mid-stream"):
        await consume()


async def test_timeout_during_stream_maps_to_httpware_timeout() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        msg = "read timeout"
        raise httpx2.ReadTimeout(msg)

    client = _client(handler)
    with pytest.raises(HttpwareTimeoutError, match="read timeout"):
        async with client.stream("GET", "https://example.test/x"):
            pytest.fail("unreachable")


async def test_invalid_url_maps_to_bare_transport_error() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        msg = "bad url"
        raise httpx2.InvalidURL(msg)

    client = _client(handler)
    with pytest.raises(TransportError) as info:
        async with client.stream("GET", "https://example.test/x"):
            pytest.fail("unreachable")
    assert not isinstance(info.value, NetworkError)


async def test_cancellation_propagates_cleanly() -> None:
    async def slow_body() -> typing.AsyncIterator[bytes]:
        yield b"first"
        await asyncio.sleep(1.0)
        yield b"second"  # pragma: no cover

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(HTTPStatus.OK, request=request, content=slow_body())

    client = _client(handler)

    async def consume() -> None:
        async with client.stream("GET", "https://example.test/x") as response:
            async for _ in response.aiter_bytes():
                pass

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.01)  # let body consumption begin
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_user_exception_in_block_propagates_unchanged() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(HTTPStatus.OK, request=request, content=b"data")

    client = _client(handler)

    async def trigger() -> None:
        async with client.stream("GET", "https://example.test/x"):
            msg = "user explosion"
            raise ValueError(msg)

    with pytest.raises(ValueError, match="user explosion"):
        await trigger()


async def test_bypasses_middleware_chain() -> None:
    """stream() must not invoke any middleware in the chain."""
    invocations = {"n": 0}

    class _RecordingMiddleware:
        async def __call__(self, request: httpx2.Request, next: AsyncNext) -> httpx2.Response:  # noqa: A002  # pragma: no cover
            invocations["n"] += 1
            return await next(request)

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(HTTPStatus.OK, request=request, content=b"x")

    transport = httpx2.MockTransport(handler)
    middleware: AsyncMiddleware = _RecordingMiddleware()
    client = AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=transport),
        middleware=[middleware],
    )

    async with client.stream("GET", "https://example.test/x") as response:
        async for _ in response.aiter_bytes():
            pass

    assert invocations["n"] == 0


async def test_forwards_kwargs_to_httpx2() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(HTTPStatus.OK, request=request, content=b"")

    client = _client(handler)
    async with client.stream(
        "GET",
        "https://example.test/x",
        params={"q": "value"},
        headers={"X-Custom": "1"},
        cookies={"sid": "abc"},
    ) as response:
        _ = [chunk async for chunk in response.aiter_bytes()]

    request = seen[0]
    assert request.url.params["q"] == "value"
    assert request.headers["x-custom"] == "1"
    assert request.headers["cookie"] == "sid=abc"


async def test_stream_with_content_kwarg() -> None:
    seen: list[bytes] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request.content)
        return httpx2.Response(HTTPStatus.OK, request=request, content=b"")

    client = _client(handler)
    async with client.stream("POST", "https://example.test/upload", content=b"payload") as response:
        _ = [chunk async for chunk in response.aiter_bytes()]

    assert seen[0] == b"payload"


async def test_stream_with_async_iterable_content() -> None:
    """stream() bypass means async-iterable bodies work without the streaming-body marker mechanism."""
    seen_calls: list[int] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen_calls.append(1)
        return httpx2.Response(HTTPStatus.OK, request=request, content=b"")

    async def streamed_body() -> typing.AsyncIterator[bytes]:
        yield b"chunk1"
        yield b"chunk2"

    client = _client(handler)
    async with client.stream("POST", "https://example.test/upload", content=streamed_body()) as response:
        _ = [chunk async for chunk in response.aiter_bytes()]

    assert seen_calls == [1]


async def test_stream_with_timeout_kwarg() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(HTTPStatus.OK, request=request, content=b"ok")

    client = _client(handler)
    async with client.stream("GET", "https://example.test/x", timeout=5.0) as response:
        _ = [chunk async for chunk in response.aiter_bytes()]
    assert response.status_code == HTTPStatus.OK


async def test_stream_with_json_kwarg() -> None:
    seen: list[bytes] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request.content)
        return httpx2.Response(HTTPStatus.OK, request=request, content=b"ok")

    client = _client(handler)
    async with client.stream("POST", "https://example.test/x", json={"key": "value"}) as response:
        _ = [chunk async for chunk in response.aiter_bytes()]
    assert b"key" in seen[0]


async def test_stream_with_data_and_extensions_kwargs() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(HTTPStatus.OK, request=request, content=b"ok")

    client = _client(handler)
    async with client.stream(
        "POST",
        "https://example.test/x",
        data={"field": "val"},
        extensions={"timeout": {"connect": 5}},
    ) as response:
        _ = [chunk async for chunk in response.aiter_bytes()]
    assert seen[0].headers["content-type"].startswith("application/x-www-form-urlencoded")


async def test_stream_with_files_kwarg() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(HTTPStatus.OK, request=request, content=b"ok")

    client = _client(handler)
    async with client.stream(
        "POST",
        "https://example.test/x",
        files={"upload": ("hello.txt", b"hello", "text/plain")},
    ) as response:
        _ = [chunk async for chunk in response.aiter_bytes()]
    assert "multipart/form-data" in seen[0].headers["content-type"]


async def test_stream_raises_response_too_large_when_over_cap() -> None:
    body = b"x" * 200

    def handler(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        return httpx2.Response(500, content=body)

    client = AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)), max_response_body_bytes=10
    )
    with pytest.raises(ResponseTooLargeError) as caught:
        async with client.stream("GET", "https://example.test/x"):
            pytest.fail("unreachable")
    assert caught.value.limit == 10  # noqa: PLR2004 — mirrors max_response_body_bytes above
    assert caught.value.content_length == 200  # noqa: PLR2004 — len(body) above
    await client.aclose()


async def test_stream_reads_error_body_when_under_cap() -> None:
    body = b"nope"

    def handler(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        return httpx2.Response(404, content=body)

    client = AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)), max_response_body_bytes=1000
    )
    with pytest.raises(NotFoundError) as caught:
        async with client.stream("GET", "https://example.test/x"):
            pytest.fail("unreachable")
    assert caught.value.response.content == body
    await client.aclose()


async def test_stream_unbounded_by_default_reads_large_error_body() -> None:
    body = b"x" * 200

    def handler(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        return httpx2.Response(500, content=body)

    client = AsyncClient(httpx2_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)))
    with pytest.raises(InternalServerError) as caught:
        async with client.stream("GET", "https://example.test/x"):
            pytest.fail("unreachable")
    assert caught.value.response.content == body
    await client.aclose()


async def test_stream_error_pre_read_streamed_over_cap() -> None:
    async def body() -> typing.AsyncIterator[bytes]:
        yield b"a" * 50
        yield b"b" * 50

    def handler(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        return httpx2.Response(500, content=body())  # chunked: no Content-Length

    client = AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)), max_response_body_bytes=70
    )
    with pytest.raises(ResponseTooLargeError) as caught:
        async with client.stream("GET", "https://example.test/x"):
            pytest.fail("unreachable")
    assert caught.value.reason == "streamed"
    assert caught.value.content_length is None
    await client.aclose()


async def test_stream_error_pre_read_within_cap_gzip_decoded() -> None:
    import gzip  # noqa: PLC0415 — local to this regression test

    raw = gzip.compress(b"boom" * 50)

    def handler(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        return httpx2.Response(500, headers={"content-encoding": "gzip"}, content=raw)

    client = AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)), max_response_body_bytes=1_000_000
    )
    with pytest.raises(InternalServerError) as caught:
        async with client.stream("GET", "https://example.test/x"):
            pytest.fail("unreachable")
    assert caught.value.response.content == b"boom" * 50  # decoded, not re-decompressed
    await client.aclose()


async def test_stream_user_driven_success_body_not_capped() -> None:
    body = b"x" * 100_000

    def handler(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        return httpx2.Response(200, content=body)

    client = AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)), max_response_body_bytes=10
    )
    async with client.stream("GET", "https://example.test/x") as response:
        chunks = [chunk async for chunk in response.aiter_bytes()]
    assert b"".join(chunks) == body  # user-driven streaming is never capped
    await client.aclose()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(None, None), ("123", 123), ("abc", None), ("-5", None), ("0", 0)],
)
def test_parse_content_length(raw: str | None, expected: int | None) -> None:
    assert _parse_content_length(raw) == expected

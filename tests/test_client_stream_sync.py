"""Tests for Client.stream() — sync sibling of test_client_stream.py."""

import typing
from http import HTTPStatus

import httpx2
import pytest

from httpware import (
    Client,
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
from httpware.middleware import Middleware, Next


_UNKNOWN_4XX = 418  # I'm a teapot
_UNKNOWN_5XX = 599
_REDIRECT_3XX = 301
_NOT_FOUND = 404
_SERVICE_UNAVAILABLE = 503


def _client(handler: typing.Callable[[httpx2.Request], httpx2.Response]) -> Client:
    transport = httpx2.MockTransport(handler)
    return Client(httpx2_client=httpx2.Client(transport=transport))


def test_streams_response_body_successfully() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(HTTPStatus.OK, request=request, content=b"chunk1chunk2chunk3")

    client = _client(handler)
    with client.stream("GET", "https://example.test/x") as response:
        assert response.status_code == HTTPStatus.OK
        chunks = list(response.iter_bytes())
    assert b"".join(chunks) == b"chunk1chunk2chunk3"


def test_auto_raises_on_4xx_with_body_preread() -> None:
    body = b'{"error": "not found"}'

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(_NOT_FOUND, request=request, content=body)

    client = _client(handler)
    with pytest.raises(NotFoundError) as info, client.stream("GET", "https://example.test/missing"):
        pytest.fail("should have raised before reaching block body")
    assert info.value.response.status_code == _NOT_FOUND
    assert info.value.response.content == body  # body was pre-read; accessible


def test_auto_raises_on_5xx_with_body_preread() -> None:
    body = b"degraded"

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(_SERVICE_UNAVAILABLE, request=request, content=body)

    client = _client(handler)
    with pytest.raises(ServiceUnavailableError) as info, client.stream("GET", "https://example.test/x"):
        pytest.fail("unreachable")
    assert info.value.response.content == body


def test_auto_raises_unknown_4xx_falls_back_to_client_status_error() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(_UNKNOWN_4XX, request=request)

    client = _client(handler)
    with pytest.raises(ClientStatusError) as info, client.stream("GET", "https://example.test/x"):
        pytest.fail("unreachable")
    assert type(info.value) is ClientStatusError
    assert info.value.response.status_code == _UNKNOWN_4XX


def test_auto_raises_unknown_5xx_falls_back_to_server_status_error() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(_UNKNOWN_5XX, request=request)

    client = _client(handler)
    with pytest.raises(ServerStatusError) as info, client.stream("GET", "https://example.test/x"):
        pytest.fail("unreachable")
    assert type(info.value) is ServerStatusError
    assert info.value.response.status_code == _UNKNOWN_5XX


def test_3xx_does_not_raise() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(_REDIRECT_3XX, request=request, headers={"location": "/y"})

    client = _client(handler)
    with client.stream("GET", "https://example.test/x") as response:
        assert response.status_code == _REDIRECT_3XX


def test_network_error_during_request_maps_to_network_error() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        msg = "connect refused"
        raise httpx2.ConnectError(msg)

    client = _client(handler)
    with pytest.raises(NetworkError, match="connect refused"), client.stream("GET", "https://example.test/x"):
        pytest.fail("unreachable")


def test_network_error_during_body_consumption_maps_to_network_error() -> None:
    def streaming_body() -> typing.Iterator[bytes]:
        yield b"first chunk"
        msg = "read failed mid-stream"
        raise httpx2.ReadError(msg)

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(HTTPStatus.OK, request=request, content=streaming_body())

    client = _client(handler)

    def consume() -> None:
        with client.stream("GET", "https://example.test/x") as response:
            for _ in response.iter_bytes():
                pass

    with pytest.raises(NetworkError, match="read failed mid-stream"):
        consume()


def test_timeout_during_stream_maps_to_httpware_timeout() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        msg = "read timeout"
        raise httpx2.ReadTimeout(msg)

    client = _client(handler)
    with pytest.raises(HttpwareTimeoutError, match="read timeout"), client.stream("GET", "https://example.test/x"):
        pytest.fail("unreachable")


def test_invalid_url_maps_to_bare_transport_error() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        msg = "bad url"
        raise httpx2.InvalidURL(msg)

    client = _client(handler)
    with pytest.raises(TransportError) as info, client.stream("GET", "https://example.test/x"):
        pytest.fail("unreachable")
    assert not isinstance(info.value, NetworkError)


def test_user_exception_in_block_propagates_unchanged() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(HTTPStatus.OK, request=request, content=b"data")

    client = _client(handler)

    def trigger() -> None:
        with client.stream("GET", "https://example.test/x"):
            msg = "user explosion"
            raise ValueError(msg)

    with pytest.raises(ValueError, match="user explosion"):
        trigger()


def test_bypasses_middleware_chain() -> None:
    """stream() must not invoke any middleware in the chain."""
    invocations = {"n": 0}

    class _RecordingMiddleware:
        def __call__(self, request: httpx2.Request, next: Next) -> httpx2.Response:  # noqa: A002  # pragma: no cover
            invocations["n"] += 1
            return next(request)

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(HTTPStatus.OK, request=request, content=b"x")

    transport = httpx2.MockTransport(handler)
    middleware: Middleware = _RecordingMiddleware()
    client = Client(
        httpx2_client=httpx2.Client(transport=transport),
        middleware=[middleware],
    )

    with client.stream("GET", "https://example.test/x") as response:
        for _ in response.iter_bytes():
            pass

    assert invocations["n"] == 0


def test_forwards_kwargs_to_httpx2() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(HTTPStatus.OK, request=request, content=b"")

    client = _client(handler)
    with client.stream(
        "GET",
        "https://example.test/x",
        params={"q": "value"},
        headers={"X-Custom": "1"},
        cookies={"sid": "abc"},
    ) as response:
        _ = list(response.iter_bytes())

    request = seen[0]
    assert request.url.params["q"] == "value"
    assert request.headers["x-custom"] == "1"
    assert request.headers["cookie"] == "sid=abc"


def test_stream_with_content_kwarg() -> None:
    seen: list[bytes] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request.content)
        return httpx2.Response(HTTPStatus.OK, request=request, content=b"")

    client = _client(handler)
    with client.stream("POST", "https://example.test/upload", content=b"payload") as response:
        _ = list(response.iter_bytes())

    assert seen[0] == b"payload"


def test_stream_with_sync_iterable_content() -> None:
    """stream() bypass means sync-iterable bodies work without the streaming-body marker mechanism."""
    seen_calls: list[int] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen_calls.append(1)
        return httpx2.Response(HTTPStatus.OK, request=request, content=b"")

    def streamed_body() -> typing.Iterator[bytes]:
        yield b"chunk1"
        yield b"chunk2"

    client = _client(handler)
    with client.stream("POST", "https://example.test/upload", content=streamed_body()) as response:
        _ = list(response.iter_bytes())

    assert seen_calls == [1]


def test_stream_with_timeout_kwarg() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(HTTPStatus.OK, request=request, content=b"ok")

    client = _client(handler)
    with client.stream("GET", "https://example.test/x", timeout=5.0) as response:
        _ = list(response.iter_bytes())
    assert response.status_code == HTTPStatus.OK


def test_stream_with_json_kwarg() -> None:
    seen: list[bytes] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request.content)
        return httpx2.Response(HTTPStatus.OK, request=request, content=b"ok")

    client = _client(handler)
    with client.stream("POST", "https://example.test/x", json={"key": "value"}) as response:
        _ = list(response.iter_bytes())
    assert b"key" in seen[0]


def test_stream_with_data_and_extensions_kwargs() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(HTTPStatus.OK, request=request, content=b"ok")

    client = _client(handler)
    with client.stream(
        "POST",
        "https://example.test/x",
        data={"field": "val"},
        extensions={"timeout": {"connect": 5}},
    ) as response:
        _ = list(response.iter_bytes())
    assert seen[0].headers["content-type"].startswith("application/x-www-form-urlencoded")


def test_stream_with_files_kwarg() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(HTTPStatus.OK, request=request, content=b"ok")

    client = _client(handler)
    with client.stream(
        "POST",
        "https://example.test/x",
        files={"upload": ("hello.txt", b"hello", "text/plain")},
    ) as response:
        _ = list(response.iter_bytes())
    assert "multipart/form-data" in seen[0].headers["content-type"]


def test_stream_raises_response_too_large_when_over_cap_sync() -> None:
    body = b"x" * 200

    def handler(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        return httpx2.Response(500, content=body)

    client = Client(httpx2_client=httpx2.Client(transport=httpx2.MockTransport(handler)), max_response_body_bytes=10)
    with pytest.raises(ResponseTooLargeError) as caught, client.stream("GET", "https://example.test/x"):
        pytest.fail("unreachable")
    assert caught.value.limit == 10  # noqa: PLR2004 — mirrors max_response_body_bytes above
    assert caught.value.content_length == 200  # noqa: PLR2004 — len(body) above
    client.close()


def test_stream_reads_error_body_when_under_cap_sync() -> None:
    body = b"nope"

    def handler(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        return httpx2.Response(404, content=body)

    client = Client(httpx2_client=httpx2.Client(transport=httpx2.MockTransport(handler)), max_response_body_bytes=1000)
    with pytest.raises(NotFoundError) as caught, client.stream("GET", "https://example.test/x"):
        pytest.fail("unreachable")
    assert caught.value.response.content == body
    client.close()


def test_stream_unbounded_by_default_reads_large_error_body_sync() -> None:
    body = b"x" * 200

    def handler(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        return httpx2.Response(500, content=body)

    client = Client(httpx2_client=httpx2.Client(transport=httpx2.MockTransport(handler)))
    with pytest.raises(InternalServerError) as caught, client.stream("GET", "https://example.test/x"):
        pytest.fail("unreachable")
    assert caught.value.response.content == body
    client.close()

"""Unit tests for the shared _read_capped wrappers (sync + async).

Drive real streaming responses through MockTransport, then hand the streaming
Response to _read_capped / _read_capped_async directly — exercising the
Content-Length early reject, the decoded-byte accumulator, the rebuilt Response,
and extension sanitisation, independent of client wiring.
"""

import gzip
from collections.abc import AsyncIterator

import httpx2
import pytest

from httpware.client import _read_capped, _read_capped_async
from httpware.errors import ResponseTooLargeError


def _sync_stream(handler: object, method: str = "GET") -> tuple[httpx2.Client, httpx2.Response]:
    client = httpx2.Client(transport=httpx2.MockTransport(handler))  # ty: ignore[invalid-argument-type]
    request = client.build_request(method, "https://example.test/x")
    return client, client.send(request, stream=True)


async def _async_stream(handler: object, method: str = "GET") -> tuple[httpx2.AsyncClient, httpx2.Response]:
    client = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))  # ty: ignore[invalid-argument-type]
    request = client.build_request(method, "https://example.test/x")
    return client, await client.send(request, stream=True)


# ---- sync ----


def test_read_capped_returns_buffered_response_within_cap() -> None:
    body = b"hello world"

    def handler(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        return httpx2.Response(200, content=body)

    client, resp = _sync_stream(handler)
    try:
        out = _read_capped(resp, 1000, resp.request)
        assert out.content == body
        assert out.status_code == 200  # noqa: PLR2004 — mirrors handler
        assert "network_stream" not in out.extensions
    finally:
        resp.close()
        client.close()


def test_read_capped_declared_content_length_over_cap() -> None:
    body = b"x" * 200

    def handler(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        return httpx2.Response(500, content=body)

    client, resp = _sync_stream(handler)
    try:
        with pytest.raises(ResponseTooLargeError) as caught:
            _read_capped(resp, 10, resp.request)
        assert caught.value.reason == "declared"
        assert caught.value.content_length == 200  # noqa: PLR2004 — len(body)
        assert caught.value.limit == 10  # noqa: PLR2004 — cap above
    finally:
        resp.close()
        client.close()


def test_read_capped_streamed_over_cap_chunked_no_content_length() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        return httpx2.Response(200, content=(c for c in (b"a" * 50, b"b" * 50)))

    client, resp = _sync_stream(handler)
    try:
        with pytest.raises(ResponseTooLargeError) as caught:
            _read_capped(resp, 10, resp.request)
        assert caught.value.reason == "streamed"
        assert caught.value.content_length is None
    finally:
        resp.close()
        client.close()


def test_read_capped_within_cap_gzip_returns_decoded_content() -> None:
    # Regression: rebuilt Response must not re-decompress already-decoded content.
    raw = gzip.compress(b"A" * 500)

    def handler(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        return httpx2.Response(200, headers={"content-encoding": "gzip"}, content=raw)

    client, resp = _sync_stream(handler)
    try:
        out = _read_capped(resp, 1_000_000, resp.request)
        assert out.content == b"A" * 500  # decoded, not re-gzipped/crashed
        assert "content-encoding" not in out.headers  # stale wire header dropped
        assert out.headers["content-length"] == "500"  # recomputed from decoded content
    finally:
        resp.close()
        client.close()


def test_read_capped_head_with_large_declared_length_not_rejected() -> None:
    # Regression: a bodiless HEAD response buffers nothing and must not trip the cap.
    def handler(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        return httpx2.Response(200, headers={"content-length": "50000000"})

    client, resp = _sync_stream(handler, method="HEAD")
    try:
        out = _read_capped(resp, 1000, resp.request)
        assert out.content == b""
        assert out.headers["content-length"] == "50000000"  # entity length preserved for HEAD
    finally:
        resp.close()
        client.close()


def test_read_capped_gzip_bomb_trips_on_decoded_bytes() -> None:
    raw = gzip.compress(b"A" * 100_000)

    def handler(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        return httpx2.Response(200, headers={"content-encoding": "gzip"}, content=raw)

    client, resp = _sync_stream(handler)
    try:
        with pytest.raises(ResponseTooLargeError) as caught:
            _read_capped(resp, 1000, resp.request)
        assert caught.value.reason == "streamed"  # compressed CL (small) passed; decoded tripped
    finally:
        resp.close()
        client.close()


def test_read_capped_exact_cap_passes() -> None:
    body = b"x" * 10

    def handler(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        return httpx2.Response(200, content=body)

    client, resp = _sync_stream(handler)
    try:
        assert _read_capped(resp, 10, resp.request).content == body
    finally:
        resp.close()
        client.close()


def test_read_capped_empty_body_passes() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        return httpx2.Response(204)

    client, resp = _sync_stream(handler)
    try:
        assert _read_capped(resp, 1, resp.request).content == b""
    finally:
        resp.close()
        client.close()


# ---- async ----


async def test_read_capped_async_returns_buffered_response_within_cap() -> None:
    body = b"hello world"

    def handler(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        return httpx2.Response(200, content=body)

    client, resp = await _async_stream(handler)
    try:
        out = await _read_capped_async(resp, 1000, resp.request)
        assert out.content == body
        assert "network_stream" not in out.extensions
    finally:
        await resp.aclose()
        await client.aclose()


async def test_read_capped_async_within_cap_gzip_returns_decoded_content() -> None:
    raw = gzip.compress(b"A" * 500)

    def handler(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        return httpx2.Response(200, headers={"content-encoding": "gzip"}, content=raw)

    client, resp = await _async_stream(handler)
    try:
        out = await _read_capped_async(resp, 1_000_000, resp.request)
        assert out.content == b"A" * 500
        assert "content-encoding" not in out.headers
        assert out.headers["content-length"] == "500"
    finally:
        await resp.aclose()
        await client.aclose()


async def test_read_capped_async_head_with_large_declared_length_not_rejected() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        return httpx2.Response(200, headers={"content-length": "50000000"})

    client, resp = await _async_stream(handler, method="HEAD")
    try:
        out = await _read_capped_async(resp, 1000, resp.request)
        assert out.content == b""
        assert out.headers["content-length"] == "50000000"
    finally:
        await resp.aclose()
        await client.aclose()


async def test_read_capped_async_declared_over_cap() -> None:
    body = b"x" * 200

    def handler(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        return httpx2.Response(500, content=body)

    client, resp = await _async_stream(handler)
    try:
        with pytest.raises(ResponseTooLargeError) as caught:
            await _read_capped_async(resp, 10, resp.request)
        assert caught.value.reason == "declared"
        assert caught.value.content_length == 200  # noqa: PLR2004 — len(body)
    finally:
        await resp.aclose()
        await client.aclose()


async def test_read_capped_async_streamed_over_cap() -> None:
    async def body() -> AsyncIterator[bytes]:
        yield b"a" * 50
        yield b"b" * 50

    def handler(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        return httpx2.Response(200, content=body())

    client, resp = await _async_stream(handler)
    try:
        with pytest.raises(ResponseTooLargeError) as caught:
            await _read_capped_async(resp, 70, resp.request)  # trips on the second 50-byte chunk
        assert caught.value.reason == "streamed"
    finally:
        await resp.aclose()
        await client.aclose()

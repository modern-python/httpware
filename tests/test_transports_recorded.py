"""Unit tests for httpware.transports.recorded.RecordedTransport."""

import pytest

from httpware.request import Request
from httpware.response import Response
from httpware.transports.recorded import RecordedTransport


def _response(content: bytes = b"ok") -> Response:
    return Response(status=200, headers={}, content=content, url="/", elapsed=0.0)


def _request(method: str = "GET", url: str = "/foo") -> Request:
    return Request(method=method, url=url)


async def test_route_match_returns_response() -> None:
    canned = _response(b"matched")
    transport = RecordedTransport(routes={("GET", "/foo"): canned})

    result = await transport(_request())

    assert result is canned


async def test_route_match_raises_exception() -> None:
    class _BoomError(Exception):
        pass

    transport = RecordedTransport(routes={("GET", "/fail"): _BoomError("boom")})

    with pytest.raises(_BoomError, match="boom"):
        await transport(_request(url="/fail"))


async def test_no_match_with_no_default_raises_runtime_error() -> None:
    transport = RecordedTransport()

    with pytest.raises(RuntimeError, match=r"No route for GET /missing"):
        await transport(_request(url="/missing"))


async def test_no_match_with_response_default_returns_default() -> None:
    fallback = _response(b"fallback")
    transport = RecordedTransport(default=fallback)

    result = await transport(_request(url="/anything"))

    assert result is fallback


async def test_no_match_with_exception_default_raises_default() -> None:
    transport = RecordedTransport(default=RuntimeError("default boom"))

    with pytest.raises(RuntimeError, match="default boom"):
        await transport(_request(url="/anything"))

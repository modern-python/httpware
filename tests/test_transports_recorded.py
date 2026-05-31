"""Unit tests for httpware.transports.recorded.RecordedTransport."""

import pytest

from httpware.request import Request
from httpware.response import Response
from httpware.transports import Transport
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


async def test_method_normalized_to_uppercase_in_routes() -> None:
    canned = _response()
    transport = RecordedTransport(routes={("get", "/foo"): canned})

    result = await transport(_request(method="GET"))

    assert result is canned


async def test_method_normalized_to_uppercase_on_request() -> None:
    canned = _response()
    transport = RecordedTransport(routes={("GET", "/foo"): canned})

    result = await transport(_request(method="get"))

    assert result is canned


async def test_requests_list_records_every_call() -> None:
    transport = RecordedTransport(default=_response())

    req1 = _request(url="/a")
    req2 = _request(url="/b")
    req3 = _request(url="/c")
    await transport(req1)
    await transport(req2)
    await transport(req3)

    assert transport.requests == [req1, req2, req3]


async def test_last_request_returns_most_recent() -> None:
    transport = RecordedTransport(default=_response())

    assert transport.last_request is None

    req1 = _request(url="/a")
    await transport(req1)
    assert transport.last_request is req1

    req2 = _request(url="/b")
    await transport(req2)
    assert transport.last_request is req2


async def test_aclose_increments_counter() -> None:
    transport = RecordedTransport()

    assert transport.aclose_calls == 0

    await transport.aclose()
    await transport.aclose()
    await transport.aclose()

    assert transport.aclose_calls == 3  # noqa: PLR2004


async def test_aclose_is_idempotent_and_doesnt_block_calls() -> None:
    transport = RecordedTransport(default=_response())

    await transport.aclose()
    result = await transport(_request())

    assert result is not None
    assert transport.aclose_calls == 1


def test_stream_raises_not_implemented_error() -> None:
    transport = RecordedTransport()

    with pytest.raises(NotImplementedError, match="streaming lands in Epic 4"):
        transport.stream(_request())


def test_satisfies_transport_protocol() -> None:
    assert isinstance(RecordedTransport(), Transport)


async def test_add_route_appends_or_replaces_entry() -> None:
    transport = RecordedTransport()

    original = _response(b"first")
    transport.add_route("GET", "/foo", original)
    assert (await transport(_request())) is original

    replacement = _response(b"second")
    transport.add_route("GET", "/foo", replacement)
    assert (await transport(_request())) is replacement


async def test_routes_fire_indefinitely_on_repeat_calls() -> None:
    canned = _response(b"canned")
    transport = RecordedTransport(routes={("GET", "/foo"): canned})

    r1 = await transport(_request())
    r2 = await transport(_request())
    r3 = await transport(_request())

    assert r1 is canned
    assert r2 is canned
    assert r3 is canned

"""Unit tests for httpware.transports.httpx2."""

import asyncio
from collections.abc import Callable
from http import HTTPStatus

import httpx2
import pytest

from httpware import (
    BadRequestError,
    ClientStatusError,
    ConflictError,
    ForbiddenError,
    Httpx2Transport,
    InternalServerError,
    Limits,
    NotFoundError,
    RateLimitedError,
    Request,
    Response,
    ServerStatusError,
    ServiceUnavailableError,
    StatusError,
    Timeout,
    TimeoutError,  # noqa: A004
    Transport,
    TransportError,
    UnauthorizedError,
    UnprocessableEntityError,
)


_Handler = Callable[[httpx2.Request], httpx2.Response]


def _status_handler(code: int, content: bytes = b"", headers: dict[str, str] | None = None) -> _Handler:
    def handler(_req: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(code, content=content, headers=headers or {})

    return handler


def _raising_handler(exc: BaseException) -> _Handler:
    def handler(_req: httpx2.Request) -> httpx2.Response:
        raise exc

    return handler


def _make_transport(handler: _Handler) -> Httpx2Transport:
    return Httpx2Transport(client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)))


# ----- (a) protocol membership ----------------------------------------------


def test_httpx2_transport_satisfies_transport_protocol() -> None:
    assert isinstance(Httpx2Transport(), Transport)


# ----- (b) success path 200 --------------------------------------------------


async def test_success_path_returns_response() -> None:
    transport = _make_transport(_status_handler(200, content=b"hello", headers={"content-type": "text/plain"}))
    try:
        resp = await transport(Request(method="GET", url="http://example.com/x"))
    finally:
        await transport.aclose()

    assert isinstance(resp, Response)
    assert resp.status == HTTPStatus.OK
    assert resp.content == b"hello"
    assert resp.url == "http://example.com/x"
    # lowercase ASCII keys per AC11
    assert "content-type" in resp.headers
    assert resp.headers["content-type"] == "text/plain"
    assert resp.elapsed >= 0.0


# ----- (c) status-code mapping ----------------------------------------------


_STATUS_LEAVES: list[tuple[int, type[StatusError]]] = [
    (400, BadRequestError),
    (401, UnauthorizedError),
    (403, ForbiddenError),
    (404, NotFoundError),
    (409, ConflictError),
    (422, UnprocessableEntityError),
    (429, RateLimitedError),
    (500, InternalServerError),
    (503, ServiceUnavailableError),
]


async def test_success_status_200_returns_response_not_raises() -> None:
    transport = _make_transport(_status_handler(200))
    try:
        resp = await transport(Request(method="GET", url="http://example.com/"))
    finally:
        await transport.aclose()
    assert resp.status == HTTPStatus.OK


@pytest.mark.parametrize(("code", "exc_cls"), _STATUS_LEAVES)
async def test_status_mapping_raises_precise_leaf(code: int, exc_cls: type[StatusError]) -> None:
    transport = _make_transport(
        _status_handler(code, content=b'{"err":1}', headers={"content-type": "application/json"})
    )
    try:
        with pytest.raises(exc_cls) as info:
            await transport(Request(method="GET", url="http://example.com/p"))
    finally:
        await transport.aclose()

    assert type(info.value) is exc_cls
    assert info.value.status == code
    assert info.value.request_method == "GET"
    assert info.value.request_url == "http://example.com/p"
    assert info.value.json == {"err": 1}


# ----- (d) unknown-status fallback ------------------------------------------


async def test_unknown_4xx_falls_back_to_client_status_error() -> None:
    transport = _make_transport(_status_handler(418))
    try:
        with pytest.raises(ClientStatusError) as info:
            await transport(Request(method="GET", url="http://example.com/"))
    finally:
        await transport.aclose()
    assert type(info.value) is ClientStatusError
    assert info.value.status == HTTPStatus.IM_A_TEAPOT


async def test_unknown_5xx_falls_back_to_server_status_error() -> None:
    transport = _make_transport(_status_handler(504))
    try:
        with pytest.raises(ServerStatusError) as info:
            await transport(Request(method="GET", url="http://example.com/"))
    finally:
        await transport.aclose()
    assert type(info.value) is ServerStatusError
    assert info.value.status == HTTPStatus.GATEWAY_TIMEOUT


# ----- (e) _try_decode_json branches ----------------------------------------


async def test_json_body_decodes_into_exception_json_field() -> None:
    transport = _make_transport(
        _status_handler(400, content=b'{"k": "v"}', headers={"content-type": "application/json; charset=utf-8"})
    )
    try:
        with pytest.raises(BadRequestError) as info:
            await transport(Request(method="GET", url="http://example.com/"))
    finally:
        await transport.aclose()
    assert info.value.json == {"k": "v"}


async def test_non_json_body_yields_none_on_exception_json() -> None:
    transport = _make_transport(
        _status_handler(500, content=b"<html>oops</html>", headers={"content-type": "text/html"})
    )
    try:
        with pytest.raises(InternalServerError) as info:
            await transport(Request(method="GET", url="http://example.com/"))
    finally:
        await transport.aclose()
    assert info.value.json is None


async def test_malformed_json_body_yields_none_on_exception_json() -> None:
    transport = _make_transport(
        _status_handler(400, content=b"{not json", headers={"content-type": "application/json"})
    )
    try:
        with pytest.raises(BadRequestError) as info:
            await transport(Request(method="GET", url="http://example.com/"))
    finally:
        await transport.aclose()
    assert info.value.json is None


async def test_empty_body_with_json_content_type_yields_none() -> None:
    transport = _make_transport(_status_handler(400, content=b"", headers={"content-type": "application/json"}))
    try:
        with pytest.raises(BadRequestError) as info:
            await transport(Request(method="GET", url="http://example.com/"))
    finally:
        await transport.aclose()
    assert info.value.json is None


async def test_missing_content_type_header_yields_none_on_exception_json() -> None:
    transport = _make_transport(_status_handler(400, content=b'{"k": 1}', headers={}))
    try:
        with pytest.raises(BadRequestError) as info:
            await transport(Request(method="GET", url="http://example.com/"))
    finally:
        await transport.aclose()
    assert info.value.json is None


# ----- (f) httpx2.TimeoutException family -----------------------------------


_TIMEOUT_CLASSES = [httpx2.ConnectTimeout, httpx2.ReadTimeout, httpx2.WriteTimeout, httpx2.PoolTimeout]


@pytest.mark.parametrize("timeout_cls", _TIMEOUT_CLASSES)
async def test_timeout_classes_map_to_httpware_timeout_error(timeout_cls) -> None:  # noqa: ANN001
    transport = _make_transport(_raising_handler(timeout_cls("boom")))
    try:
        with pytest.raises(TimeoutError) as info:
            await transport(Request(method="GET", url="http://example.com/"))
    finally:
        await transport.aclose()
    assert type(info.value) is TimeoutError
    assert isinstance(info.value.__cause__, timeout_cls)


# ----- (g) httpx2.HTTPError family (representative) -------------------------


_HTTP_ERROR_CLASSES = [
    httpx2.ConnectError,
    httpx2.NetworkError,
    httpx2.ProxyError,
    httpx2.UnsupportedProtocol,
    httpx2.LocalProtocolError,
    httpx2.RemoteProtocolError,
    httpx2.DecodingError,
    httpx2.TooManyRedirects,
]


@pytest.mark.parametrize("http_err_cls", _HTTP_ERROR_CLASSES)
async def test_http_error_descendants_map_to_transport_error(http_err_cls) -> None:  # noqa: ANN001
    transport = _make_transport(_raising_handler(http_err_cls("boom")))
    try:
        with pytest.raises(TransportError) as info:
            await transport(Request(method="GET", url="http://example.com/"))
    finally:
        await transport.aclose()
    assert type(info.value) is TransportError
    assert isinstance(info.value.__cause__, http_err_cls)


# ----- (h) httpx2.InvalidURL (orphan branch) --------------------------------


async def test_invalid_url_maps_to_transport_error() -> None:
    transport = _make_transport(_raising_handler(httpx2.InvalidURL("nope")))
    try:
        with pytest.raises(TransportError) as info:
            await transport(Request(method="GET", url="http://example.com/"))
    finally:
        await transport.aclose()
    assert type(info.value) is TransportError
    assert isinstance(info.value.__cause__, httpx2.InvalidURL)


# ----- (i) no httpx2 exception escapes --------------------------------------


_ALL_HTTPX2_EXCEPTIONS = _TIMEOUT_CLASSES + _HTTP_ERROR_CLASSES + [httpx2.InvalidURL]


@pytest.mark.parametrize("exc_cls", _ALL_HTTPX2_EXCEPTIONS)
async def test_no_httpx2_exception_escapes(exc_cls) -> None:  # noqa: ANN001
    transport = _make_transport(_raising_handler(exc_cls("boom")))
    try:
        with pytest.raises((TimeoutError, TransportError)) as info:
            await transport(Request(method="GET", url="http://example.com/"))
    finally:
        await transport.aclose()
    assert not isinstance(info.value, httpx2.HTTPError)


# ----- (j) method casing normalization --------------------------------------


async def test_lowercase_method_uppercased_in_status_error() -> None:
    transport = _make_transport(_status_handler(404))
    try:
        with pytest.raises(NotFoundError) as info:
            await transport(Request(method="get", url="http://example.com/p"))
    finally:
        await transport.aclose()
    assert info.value.request_method == "GET"


# ----- (k) stream() raises synchronously ------------------------------------


def test_stream_raises_not_implemented_synchronously() -> None:
    transport = Httpx2Transport()
    with pytest.raises(NotImplementedError):
        transport.stream(Request(method="GET", url="http://example.com/"))


# ----- (l) aclose() idempotency ---------------------------------------------


async def test_aclose_is_idempotent() -> None:
    transport = _make_transport(_status_handler(200))
    await transport(Request(method="GET", url="http://example.com/"))
    await transport.aclose()
    await transport.aclose()
    assert transport._client is None  # noqa: SLF001


# ----- (m) aclose() on never-used transport ---------------------------------


async def test_aclose_no_op_on_never_used_transport() -> None:
    transport = Httpx2Transport()
    await transport.aclose()
    assert transport._client is None  # noqa: SLF001


# ----- (n) post-close call raises -------------------------------------------


async def test_post_close_call_raises_transport_error() -> None:
    transport = _make_transport(_status_handler(200))
    await transport(Request(method="GET", url="http://example.com/"))
    await transport.aclose()
    with pytest.raises(TransportError):
        await transport(Request(method="GET", url="http://example.com/"))


async def test_post_close_stream_raises_transport_error() -> None:
    transport = _make_transport(_status_handler(200))
    await transport.aclose()
    with pytest.raises(TransportError):
        transport.stream(Request(method="GET", url="http://example.com/"))


async def test_pre_close_stream_still_raises_not_implemented() -> None:
    transport = _make_transport(_status_handler(200))
    with pytest.raises(NotImplementedError):
        transport.stream(Request(method="GET", url="http://example.com/"))
    await transport.aclose()


async def test_invalid_url_at_request_construction_maps_to_transport_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = _make_transport(_status_handler(200))

    def _boom(*_args: object, **_kwargs: object) -> httpx2.Request:
        msg = "bad url"
        raise httpx2.InvalidURL(msg)

    monkeypatch.setattr(httpx2, "Request", _boom)
    with pytest.raises(TransportError):
        await transport(Request(method="GET", url="http://example.com/"))


async def test_cookie_conflict_at_request_construction_maps_to_transport_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = _make_transport(_status_handler(200))

    def _boom(*_args: object, **_kwargs: object) -> httpx2.Request:
        msg = "conflict"
        raise httpx2.CookieConflict(msg)

    monkeypatch.setattr(httpx2, "Request", _boom)
    with pytest.raises(TransportError):
        await transport(Request(method="GET", url="http://example.com/"))


async def test_send_on_externally_closed_user_client_maps_to_transport_error() -> None:
    user_client = httpx2.AsyncClient(transport=httpx2.MockTransport(_status_handler(200)))
    transport = Httpx2Transport(client=user_client)
    await user_client.aclose()
    with pytest.raises(TransportError):
        await transport(Request(method="GET", url="http://example.com/"))


async def test_unexpected_runtime_error_propagates_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = _make_transport(_status_handler(200))
    client = await transport._get_client()  # noqa: SLF001

    async def _boom(*_args: object, **_kwargs: object) -> httpx2.Response:
        msg = "something else entirely"
        raise RuntimeError(msg)

    monkeypatch.setattr(client, "send", _boom)
    with pytest.raises(RuntimeError, match="something else entirely"):
        await transport(Request(method="GET", url="http://example.com/"))


async def test_mapped_exceptions_preserve_original_message() -> None:
    transport = _make_transport(_raising_handler(httpx2.ReadTimeout("read timed out after 30s")))
    with pytest.raises(TimeoutError, match="read timed out after 30s") as info:
        await transport(Request(method="GET", url="http://example.com/"))
    assert isinstance(info.value.__cause__, httpx2.ReadTimeout)


# ----- (o) lazy event-loop binding ------------------------------------------


def test_default_transport_is_lazy_pre_call() -> None:
    transport = Httpx2Transport()
    assert transport._client is None  # noqa: SLF001


async def test_default_transport_constructs_client_on_first_call() -> None:
    transport = _make_transport(_status_handler(200))
    # _make_transport pre-supplies a client; assert post-call non-None invariant.
    await transport(Request(method="GET", url="http://example.com/"))
    assert transport._client is not None  # noqa: SLF001
    await transport.aclose()


async def test_lazy_default_constructs_real_client_on_first_call() -> None:
    transport = Httpx2Transport(limits=Limits(), timeout=Timeout())
    assert transport._client is None  # noqa: SLF001
    # Touch _get_client directly to avoid network; lazy construction is what we test.
    client = await transport._get_client()  # noqa: SLF001
    assert isinstance(client, httpx2.AsyncClient)
    assert transport._client is client  # noqa: SLF001
    await transport.aclose()


async def test_concurrent_first_calls_initialize_client_once() -> None:
    transport = Httpx2Transport(limits=Limits(), timeout=Timeout())
    clients = await asyncio.gather(
        transport._get_client(),  # noqa: SLF001
        transport._get_client(),  # noqa: SLF001
        transport._get_client(),  # noqa: SLF001
    )
    assert clients[0] is clients[1] is clients[2]
    assert transport._client is clients[0]  # noqa: SLF001
    await transport.aclose()


# ----- (p) constructor argument conflict ------------------------------------


def test_constructor_rejects_client_plus_limits() -> None:
    user_client = httpx2.AsyncClient()
    with pytest.raises(ValueError, match="limits/timeout"):
        Httpx2Transport(client=user_client, limits=Limits())


def test_constructor_rejects_client_plus_timeout() -> None:
    user_client = httpx2.AsyncClient()
    with pytest.raises(ValueError, match="limits/timeout"):
        Httpx2Transport(client=user_client, timeout=Timeout())

"""The URL's own query string survives per-request and client-level `params`, which are appended after it."""

from http import HTTPStatus

import httpx2
import pytest

from httpware import AsyncClient, Client


def _ok(request: httpx2.Request) -> httpx2.Response:
    return httpx2.Response(HTTPStatus.OK, request=request)


def _async_client(captured: list[httpx2.Request], params: dict[str, str] | None = None) -> AsyncClient:
    def handler(request: httpx2.Request) -> httpx2.Response:
        captured.append(request)
        return _ok(request)

    return AsyncClient(httpx2_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler), params=params))


def _sync_client(captured: list[httpx2.Request], params: dict[str, str] | None = None) -> Client:
    def handler(request: httpx2.Request) -> httpx2.Response:
        captured.append(request)
        return _ok(request)

    return Client(httpx2_client=httpx2.Client(transport=httpx2.MockTransport(handler), params=params))


_CASES = [
    pytest.param("https://example.test/x?a=1", {"b": "2"}, {}, "a=1&b=2", id="url-query-plus-params"),
    pytest.param("https://example.test/x?a=1&b=1", {"b": "2"}, {}, "a=1&b=1&b=2", id="same-key-appended"),
    pytest.param("https://example.test/x?a=1&a=2", {"b": "3"}, {}, "a=1&a=2&b=3", id="repeated-url-keys-kept"),
    pytest.param("https://example.test/x?a=1", {}, {}, "a=1", id="empty-params-keeps-url-query"),
    pytest.param("https://example.test/x?a=1", None, {"c": "3"}, "a=1&c=3", id="client-params-after-url-query"),
    pytest.param(
        "https://example.test/x?a=1&c=1", {"b": "2"}, {"c": "3"}, "a=1&c=1&c=3&b=2", id="url-and-client-same-key-kept"
    ),
    pytest.param("https://example.test/x", {"b": "2"}, {"c": "3"}, "c=3&b=2", id="no-url-query-unchanged"),
    pytest.param("https://example.test/x?q=a%20b&flag", {"p": "1"}, {}, "q=a%20b&flag&p=1", id="url-query-bytes-kept"),
]


@pytest.mark.parametrize(("url", "params", "client_params", "expected_query"), _CASES)
def test_async_build_request_merges_url_query(
    url: str, params: dict[str, str] | None, client_params: dict[str, str], expected_query: str
) -> None:
    client = _async_client([], params=client_params)
    assert client.build_request("GET", url, params=params).url.query == expected_query.encode()


@pytest.mark.parametrize(("url", "params", "client_params", "expected_query"), _CASES)
def test_sync_build_request_merges_url_query(
    url: str, params: dict[str, str] | None, client_params: dict[str, str], expected_query: str
) -> None:
    client = _sync_client([], params=client_params)
    assert client.build_request("GET", url, params=params).url.query == expected_query.encode()


@pytest.mark.parametrize(("url", "params", "client_params", "expected_query"), _CASES)
async def test_async_get_merges_url_query(
    url: str, params: dict[str, str] | None, client_params: dict[str, str], expected_query: str
) -> None:
    captured: list[httpx2.Request] = []
    await _async_client(captured, params=client_params).get(url, params=params)
    assert captured[0].url.query == expected_query.encode()


@pytest.mark.parametrize(("url", "params", "client_params", "expected_query"), _CASES)
def test_sync_get_merges_url_query(
    url: str, params: dict[str, str] | None, client_params: dict[str, str], expected_query: str
) -> None:
    captured: list[httpx2.Request] = []
    _sync_client(captured, params=client_params).get(url, params=params)
    assert captured[0].url.query == expected_query.encode()


@pytest.mark.parametrize(("url", "params", "client_params", "expected_query"), _CASES)
async def test_async_stream_merges_url_query(
    url: str, params: dict[str, str] | None, client_params: dict[str, str], expected_query: str
) -> None:
    captured: list[httpx2.Request] = []
    async with _async_client(captured, params=client_params).stream("GET", url, params=params):
        pass
    assert captured[0].url.query == expected_query.encode()


@pytest.mark.parametrize(("url", "params", "client_params", "expected_query"), _CASES)
def test_sync_stream_merges_url_query(
    url: str, params: dict[str, str] | None, client_params: dict[str, str], expected_query: str
) -> None:
    captured: list[httpx2.Request] = []
    with _sync_client(captured, params=client_params).stream("GET", url, params=params):
        pass
    assert captured[0].url.query == expected_query.encode()


def test_owned_client_relative_url_merges_with_base_url() -> None:
    client = Client(base_url="https://example.test/api", params={"c": "3"})
    request = client.build_request("GET", "items?a=1", params={"b": "2"})
    assert str(request.url) == "https://example.test/api/items?a=1&c=3&b=2"


def test_url_query_without_params_is_left_verbatim() -> None:
    client = _sync_client([])
    url = "https://example.test/x?cursor=a%2Fb+c"
    assert str(client.build_request("GET", url).url) == url

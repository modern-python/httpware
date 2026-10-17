"""URLs that skip the query merge, and boundary URLs that must not skip it, build the expected request."""

from http import HTTPStatus

import httpx2
import pytest

from httpware import AsyncClient, Client


def _ok(request: httpx2.Request) -> httpx2.Response:
    return httpx2.Response(HTTPStatus.OK, request=request)


_CASES = [
    pytest.param("https://example.test/x", None, {}, "https://example.test/x", id="no-query-no-params"),
    pytest.param("https://example.test/x", {"b": "2"}, {"c": "3"}, "https://example.test/x?c=3&b=2", id="no-query"),
    pytest.param("https://example.test/x?a=1", None, {}, "https://example.test/x?a=1", id="query-without-params"),
    pytest.param(
        "https://example.test/x?a=1", {}, {}, "https://example.test/x?a=1", id="query-with-empty-params-not-skipped"
    ),
    pytest.param(
        "https://example.test/x?a=1", None, {"c": "3"}, "https://example.test/x?a=1&c=3", id="client-params-not-skipped"
    ),
    pytest.param(
        "https://example.test/x#f?a=1",
        {"b": "2"},
        {},
        "https://example.test/x?b=2#f?a=1",
        id="question-mark-in-fragment",
    ),
    pytest.param(
        "https://example.test/x?a=1#f", {"b": "2"}, {}, "https://example.test/x?a=1&b=2#f", id="query-and-fragment"
    ),
    pytest.param("https://example.test/x?", {"b": "2"}, {}, "https://example.test/x?b=2", id="empty-query"),
    pytest.param(
        httpx2.URL("https://example.test/x?a=1"),
        {"b": "2"},
        {},
        "https://example.test/x?a=1&b=2",
        id="url-instance-with-query-not-skipped",
    ),
    pytest.param(
        httpx2.URL("https://example.test/x?a=1"), None, {}, "https://example.test/x?a=1", id="url-instance-no-params"
    ),
    pytest.param(
        httpx2.URL("https://example.test/x"), {"b": "2"}, {}, "https://example.test/x?b=2", id="url-instance-no-query"
    ),
]


@pytest.mark.parametrize(("url", "params", "client_params", "expected"), _CASES)
def test_async_build_request_url(
    url: str, params: dict[str, str] | None, client_params: dict[str, str], expected: str
) -> None:
    client = AsyncClient(httpx2_client=httpx2.AsyncClient(params=client_params))
    assert str(client.build_request("GET", url, params=params).url) == expected


@pytest.mark.parametrize(("url", "params", "client_params", "expected"), _CASES)
def test_sync_build_request_url(
    url: str, params: dict[str, str] | None, client_params: dict[str, str], expected: str
) -> None:
    client = Client(httpx2_client=httpx2.Client(params=client_params))
    assert str(client.build_request("GET", url, params=params).url) == expected


_BASE_URL_CASES = [
    pytest.param("items", None, {}, "https://example.test/api/items", id="relative-no-query"),
    pytest.param("items?a=1", None, {}, "https://example.test/api/items?a=1", id="relative-query-without-params"),
    pytest.param("/items?a=1", {"b": "2"}, {}, "https://example.test/api/items?a=1&b=2", id="relative-query-params"),
    pytest.param(
        "items?a=1", None, {"c": "3"}, "https://example.test/api/items?a=1&c=3", id="relative-query-client-params"
    ),
]


@pytest.mark.parametrize(("url", "params", "client_params", "expected"), _BASE_URL_CASES)
async def test_async_get_joins_base_url(
    url: str, params: dict[str, str] | None, client_params: dict[str, str], expected: str
) -> None:
    captured: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured.append(request)
        return _ok(request)

    client = AsyncClient(
        base_url="https://example.test/api", params=client_params, transport=httpx2.MockTransport(handler)
    )
    await client.get(url, params=params)
    assert str(captured[0].url) == expected


@pytest.mark.parametrize(("url", "params", "client_params", "expected"), _BASE_URL_CASES)
def test_sync_get_joins_base_url(
    url: str, params: dict[str, str] | None, client_params: dict[str, str], expected: str
) -> None:
    captured: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured.append(request)
        return _ok(request)

    client = Client(base_url="https://example.test/api", params=client_params, transport=httpx2.MockTransport(handler))
    client.get(url, params=params)
    assert str(captured[0].url) == expected

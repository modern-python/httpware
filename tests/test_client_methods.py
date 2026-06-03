"""Tests for the per-method API surface of AsyncClient."""

from http import HTTPStatus

import httpx2
import pytest

from httpware import AsyncClient, NotFoundError


def _echo_handler(request: httpx2.Request) -> httpx2.Response:
    return httpx2.Response(
        HTTPStatus.OK,
        request=request,
        json={
            "method": request.method,
            "url": str(request.url),
            "headers": dict(request.headers),
            "content": request.content.decode() if request.content else "",
        },
    )


def _client_with_handler(handler, **kwargs) -> AsyncClient:  # noqa: ANN001, ANN003
    transport = httpx2.MockTransport(handler)
    return AsyncClient(httpx2_client=httpx2.AsyncClient(transport=transport, **kwargs))


async def test_get_returns_httpx2_response() -> None:
    client = _client_with_handler(_echo_handler)
    response = await client.get("https://example.test/x")
    assert isinstance(response, httpx2.Response)
    assert response.json()["method"] == "GET"


@pytest.mark.parametrize(
    "method_name",
    ["get", "post", "put", "patch", "delete", "head", "options"],
)
async def test_each_per_method_helper_exists_and_uses_correct_verb(method_name: str) -> None:
    client = _client_with_handler(_echo_handler)
    method = getattr(client, method_name)
    response = await method("https://example.test/x")
    assert response.json()["method"] == method_name.upper()


async def test_post_json_body_serialized() -> None:
    client = _client_with_handler(_echo_handler)
    response = await client.post("https://example.test/x", json={"k": "v"})
    payload = response.json()
    assert "application/json" in payload["headers"]["content-type"]
    assert payload["content"] == '{"k":"v"}'


async def test_get_with_params_forwards_query() -> None:
    captured: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured.append(request)
        return httpx2.Response(HTTPStatus.OK, request=request)

    client = _client_with_handler(handler)
    await client.get("https://example.test/x", params={"a": "1"})
    assert "a=1" in str(captured[0].url)


async def test_get_with_headers_merges() -> None:
    captured: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured.append(request)
        return httpx2.Response(HTTPStatus.OK, request=request)

    client = _client_with_handler(handler)
    await client.get("https://example.test/x", headers={"x-trace": "abc"})
    assert captured[0].headers["x-trace"] == "abc"


async def test_get_raises_typed_status_error_on_404() -> None:
    client = _client_with_handler(lambda req: httpx2.Response(HTTPStatus.NOT_FOUND, request=req))
    with pytest.raises(NotFoundError):
        await client.get("https://example.test/missing")


async def test_request_method_takes_arbitrary_verb() -> None:
    client = _client_with_handler(_echo_handler)
    response = await client.request("PROPFIND", "https://example.test/x")
    assert response.json()["method"] == "PROPFIND"


async def test_base_url_is_applied() -> None:
    captured: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured.append(request)
        return httpx2.Response(HTTPStatus.OK, request=request)

    transport = httpx2.MockTransport(handler)
    underlying = httpx2.AsyncClient(transport=transport, base_url="https://example.test")
    client = AsyncClient(httpx2_client=underlying)
    await client.get("/relative")
    assert str(captured[0].url) == "https://example.test/relative"


async def test_get_with_cookies_forwarded() -> None:
    """Exercises the cookies branch in _request_with_body."""
    captured: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured.append(request)
        return httpx2.Response(HTTPStatus.OK, request=request)

    client = _client_with_handler(handler)
    await client.get("https://example.test/x", cookies={"token": "abc"})
    assert "token=abc" in captured[0].headers.get("cookie", "")


async def test_get_with_explicit_timeout() -> None:
    """Exercises the timeout branch in _request_with_body."""
    client = _client_with_handler(_echo_handler)
    response = await client.get("https://example.test/x", timeout=5.0)
    assert response.status_code == HTTPStatus.OK


async def test_get_with_extensions() -> None:
    """Exercises the extensions branch in _request_with_body."""
    client = _client_with_handler(_echo_handler)
    response = await client.get("https://example.test/x", extensions={"trace": True})
    assert response.status_code == HTTPStatus.OK


async def test_post_with_content_body() -> None:
    """Exercises the content branch in _request_with_body."""
    client = _client_with_handler(_echo_handler)
    response = await client.post("https://example.test/x", content=b"raw-bytes")
    assert response.json()["content"] == "raw-bytes"


async def test_post_with_data_body() -> None:
    """Exercises the data branch in _request_with_body."""
    client = _client_with_handler(_echo_handler)
    response = await client.post("https://example.test/x", data={"field": "value"})
    assert response.status_code == HTTPStatus.OK


async def test_post_with_files_body() -> None:
    """Exercises the files branch in _request_with_body."""
    client = _client_with_handler(_echo_handler)
    response = await client.post("https://example.test/x", files={"upload": b"file-content"})
    assert response.status_code == HTTPStatus.OK


async def test_runtime_error_without_closed_reraises() -> None:
    """Exercises the RuntimeError re-raise branch in _terminal (error not containing 'closed')."""

    def boom(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        msg = "unexpected internal failure"
        raise RuntimeError(msg)

    client = _client_with_handler(boom)
    with pytest.raises(RuntimeError, match="unexpected internal failure"):
        await client.get("https://example.test/x")

"""Tests for Client.send_with_response — atomic (response, decoded) pair (sync)."""

from http import HTTPStatus

import httpx2
import pydantic
import pytest

from httpware import Client, ClientError, DecodeError, NotFoundError
from httpware.middleware import before_request


class _User(pydantic.BaseModel):
    id: int
    name: str


def _client_with_payload(
    payload: bytes,
    *,
    status: int = HTTPStatus.OK,
    headers: dict[str, str] | None = None,
) -> Client:
    response_headers = {"content-type": "application/json"}
    if headers is not None:
        response_headers.update(headers)

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(status, content=payload, headers=response_headers, request=request)

    transport = httpx2.MockTransport(handler)
    return Client(httpx2_client=httpx2.Client(transport=transport))


def test_send_with_response_returns_response_and_decoded() -> None:
    client = _client_with_payload(b'{"id": 1, "name": "ada"}')
    request = client.build_request("GET", "https://example.test/u")
    response, user = client.send_with_response(request, response_model=_User)
    assert isinstance(response, httpx2.Response)
    assert isinstance(user, _User)
    assert user == _User(id=1, name="ada")
    assert response.content == b'{"id": 1, "name": "ada"}'


def test_send_with_response_preserves_response_headers() -> None:
    """Pagination callers read Link / X-Total-Count off the returned response."""
    client = _client_with_payload(
        b'{"id": 1, "name": "p"}',
        headers={"link": '<https://example.test/u?page=2>; rel="next"', "x-total-count": "100"},
    )
    request = client.build_request("GET", "https://example.test/u?page=1")
    response, _ = client.send_with_response(request, response_model=_User)
    assert response.headers.get("link") == '<https://example.test/u?page=2>; rel="next"'
    assert response.headers.get("x-total-count") == "100"


def test_send_with_response_response_request_url_populated() -> None:
    """Pagination loops do str(response.request.url) to compute the next page."""
    client = _client_with_payload(b'{"id": 1, "name": "p"}')
    request = client.build_request("GET", "https://example.test/u?page=1")
    response, _ = client.send_with_response(request, response_model=_User)
    assert str(response.request.url) == "https://example.test/u?page=1"


def test_send_with_response_decode_failure_raises_decode_error() -> None:
    client = _client_with_payload(b"null")
    request = client.build_request("GET", "https://example.test/u")
    with pytest.raises(DecodeError) as exc_info:
        client.send_with_response(request, response_model=_User)
    exc = exc_info.value
    assert exc.response.status_code == HTTPStatus.OK
    assert exc.model is _User
    assert isinstance(exc.original, pydantic.ValidationError)
    assert exc.__cause__ is exc.original


def test_send_with_response_malformed_json_raises_decode_error() -> None:
    client = _client_with_payload(b"{not json")
    request = client.build_request("GET", "https://example.test/u")
    with pytest.raises(DecodeError) as exc_info:
        client.send_with_response(request, response_model=_User)
    exc = exc_info.value
    assert exc.response.status_code == HTTPStatus.OK
    assert exc.model is _User
    assert isinstance(exc.original, pydantic.ValidationError)


def test_send_with_response_decode_error_caught_by_client_error() -> None:
    """The user-facing promise: `except ClientError` catches decode failures."""
    client = _client_with_payload(b"null")
    request = client.build_request("GET", "https://example.test/u")
    with pytest.raises(ClientError) as exc_info:
        client.send_with_response(request, response_model=_User)
    assert isinstance(exc_info.value, DecodeError)


def test_send_with_response_status_error_raised_before_decoder_runs() -> None:
    """4xx never produces a DecodeError — terminal raises StatusError first."""
    client = _client_with_payload(b'{"id": 1, "name": "x"}', status=HTTPStatus.NOT_FOUND)
    request = client.build_request("GET", "https://example.test/u")
    with pytest.raises(NotFoundError):
        client.send_with_response(request, response_model=_User)


def test_send_with_response_runs_middleware_chain() -> None:
    """User middleware mutates the request; mutation is visible on the wire."""
    recorded: list[httpx2.Request] = []

    def stamp(request: httpx2.Request) -> httpx2.Request:
        request.headers["x-test"] = "ok"
        return request

    def handler(request: httpx2.Request) -> httpx2.Response:
        recorded.append(request)
        return httpx2.Response(
            HTTPStatus.OK,
            content=b'{"id": 1, "name": "z"}',
            headers={"content-type": "application/json"},
            request=request,
        )

    transport = httpx2.MockTransport(handler)
    client = Client(
        httpx2_client=httpx2.Client(transport=transport),
        middleware=[before_request(stamp)],
    )
    request = client.build_request("GET", "https://example.test/u")
    response, _ = client.send_with_response(request, response_model=_User)
    assert recorded[0].headers.get("x-test") == "ok"
    assert response.request.headers.get("x-test") == "ok"

"""Tests for response_model decoding integration."""

from http import HTTPStatus

import httpx2
import pydantic
import pytest

from httpware import AsyncClient, Client, ClientError, DecodeError, NotFoundError


class _User(pydantic.BaseModel):
    id: int
    name: str


def _client_with_payload(payload: bytes, content_type: str = "application/json") -> AsyncClient:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            HTTPStatus.OK,
            content=payload,
            headers={"content-type": content_type},
            request=request,
        )

    transport = httpx2.MockTransport(handler)
    return AsyncClient(httpx2_client=httpx2.AsyncClient(transport=transport))


def _sync_client_with_payload(payload: bytes, content_type: str = "application/json") -> Client:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            HTTPStatus.OK,
            content=payload,
            headers={"content-type": content_type},
            request=request,
        )

    transport = httpx2.MockTransport(handler)
    return Client(httpx2_client=httpx2.Client(transport=transport))


async def test_get_with_response_model_returns_typed_object() -> None:
    client = _client_with_payload(b'{"id": 1, "name": "ada"}')
    user = await client.get("https://example.test/u", response_model=_User)
    assert isinstance(user, _User)
    assert user == _User(id=1, name="ada")


async def test_post_with_response_model_returns_typed_object() -> None:
    client = _client_with_payload(b'{"id": 2, "name": "bob"}')
    user = await client.post("https://example.test/u", json={"name": "bob"}, response_model=_User)
    assert isinstance(user, _User)


async def test_send_with_response_model_returns_typed_object() -> None:
    client = _client_with_payload(b'{"id": 3, "name": "cat"}')
    request = client.build_request("GET", "https://example.test/u")
    user = await client.send(request, response_model=_User)
    assert isinstance(user, _User)


async def test_status_error_raised_before_decoder_runs() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(HTTPStatus.NOT_FOUND, content=b'{"id": 1, "name": "x"}', request=request)

    transport = httpx2.MockTransport(handler)
    client = AsyncClient(httpx2_client=httpx2.AsyncClient(transport=transport))
    with pytest.raises(NotFoundError):
        await client.get("https://example.test/u", response_model=_User)


async def test_async_schema_mismatch_raises_decode_error() -> None:
    client = _client_with_payload(b"null")
    with pytest.raises(DecodeError) as exc_info:
        await client.get("https://example.test/u", response_model=_User)
    exc = exc_info.value
    assert exc.response.status_code == HTTPStatus.OK
    assert exc.model is _User
    assert isinstance(exc.original, pydantic.ValidationError)
    assert exc.__cause__ is exc.original


async def test_async_malformed_json_raises_decode_error() -> None:
    client = _client_with_payload(b"{not json")
    with pytest.raises(DecodeError) as exc_info:
        await client.get("https://example.test/u", response_model=_User)
    exc = exc_info.value
    assert exc.response.status_code == HTTPStatus.OK
    assert exc.model is _User
    assert isinstance(exc.original, pydantic.ValidationError)


async def test_async_decode_error_caught_by_client_error() -> None:
    """The user-facing promise: `except ClientError` catches decode failures."""
    client = _client_with_payload(b"null")
    with pytest.raises(ClientError) as exc_info:
        await client.get("https://example.test/u", response_model=_User)
    assert isinstance(exc_info.value, DecodeError)


def test_sync_schema_mismatch_raises_decode_error() -> None:
    client = _sync_client_with_payload(b"null")
    with pytest.raises(DecodeError) as exc_info:
        client.get("https://example.test/u", response_model=_User)
    exc = exc_info.value
    assert exc.response.status_code == HTTPStatus.OK
    assert exc.model is _User
    assert isinstance(exc.original, pydantic.ValidationError)


def test_sync_malformed_json_raises_decode_error() -> None:
    client = _sync_client_with_payload(b"{not json")
    with pytest.raises(DecodeError) as exc_info:
        client.get("https://example.test/u", response_model=_User)
    exc = exc_info.value
    assert exc.response.status_code == HTTPStatus.OK
    assert exc.model is _User
    assert isinstance(exc.original, pydantic.ValidationError)

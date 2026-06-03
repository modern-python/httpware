"""Tests for response_model decoding integration."""

from http import HTTPStatus

import httpx2
import pydantic
import pytest

from httpware import AsyncClient, NotFoundError


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


async def test_decoder_validation_error_propagates_unwrapped() -> None:
    client = _client_with_payload(b'{"id": "not-an-int", "name": "x"}')
    with pytest.raises(pydantic.ValidationError):
        await client.get("https://example.test/u", response_model=_User)


async def test_status_error_raised_before_decoder_runs() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(HTTPStatus.NOT_FOUND, content=b'{"id": 1, "name": "x"}', request=request)

    transport = httpx2.MockTransport(handler)
    client = AsyncClient(httpx2_client=httpx2.AsyncClient(transport=transport))
    with pytest.raises(NotFoundError):
        await client.get("https://example.test/u", response_model=_User)

"""Per-verb *_with_response siblings on AsyncClient — (response, decoded) pairs."""

from http import HTTPStatus

import httpx2
import pydantic
import pytest

from httpware import AsyncClient, DecodeError, MissingDecoderError


class _User(pydantic.BaseModel):
    id: int
    name: str


def _echo_client(
    payload: bytes = b'{"id": 1, "name": "ada"}',
    *,
    headers: dict[str, str] | None = None,
) -> tuple[AsyncClient, list[httpx2.Request]]:
    recorded: list[httpx2.Request] = []
    response_headers = {"content-type": "application/json"}
    if headers is not None:
        response_headers.update(headers)

    def handler(request: httpx2.Request) -> httpx2.Response:
        recorded.append(request)
        return httpx2.Response(HTTPStatus.OK, content=payload, headers=response_headers, request=request)

    client = AsyncClient(httpx2_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)))
    return client, recorded


@pytest.mark.parametrize(
    ("verb", "expected_method"),
    [("get", "GET"), ("post", "POST"), ("put", "PUT"), ("patch", "PATCH"), ("delete", "DELETE")],
)
async def test_verb_with_response_returns_pair_and_sends_right_method(verb: str, expected_method: str) -> None:
    client, recorded = _echo_client()
    method = getattr(client, f"{verb}_with_response")
    response, user = await method("https://example.test/u", response_model=_User)
    assert isinstance(response, httpx2.Response)
    assert user == _User(id=1, name="ada")
    assert recorded[0].method == expected_method


async def test_request_with_response_returns_pair() -> None:
    client, recorded = _echo_client()
    response, user = await client.request_with_response("GET", "https://example.test/u", response_model=_User)
    assert isinstance(response, httpx2.Response)
    assert user == _User(id=1, name="ada")
    assert recorded[0].method == "GET"


async def test_get_with_response_preserves_headers() -> None:
    client, _ = _echo_client(headers={"link": '<https://example.test/u?page=2>; rel="next"'})
    response, _user = await client.get_with_response("https://example.test/u", response_model=_User)
    assert response.headers.get("link") == '<https://example.test/u?page=2>; rel="next"'


async def test_post_with_response_forwards_json_body() -> None:
    client, recorded = _echo_client()
    await client.post_with_response("https://example.test/u", json={"name": "ada"}, response_model=_User)
    assert recorded[0].content == b'{"name":"ada"}'


async def test_with_response_decode_failure_raises_decode_error() -> None:
    client, _ = _echo_client(payload=b"null")
    with pytest.raises(DecodeError) as exc_info:
        await client.get_with_response("https://example.test/u", response_model=_User)
    assert exc_info.value.model is _User


async def test_with_response_missing_decoder_before_http_call() -> None:
    def handler(_: httpx2.Request) -> httpx2.Response:  # pragma: no cover
        pytest.fail("transport should not be invoked when MissingDecoderError fires")

    client = AsyncClient(httpx2_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)), decoders=[])

    class _Foo:
        pass

    with pytest.raises(MissingDecoderError):
        await client.get_with_response("https://example.test/x", response_model=_Foo)

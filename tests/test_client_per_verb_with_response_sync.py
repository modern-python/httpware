"""Per-verb *_with_response siblings on Client — (response, decoded) pairs."""

from http import HTTPStatus

import httpx2
import pydantic
import pytest

from httpware import Client, DecodeError, MissingDecoderError


class _User(pydantic.BaseModel):
    id: int
    name: str


def _echo_client(
    payload: bytes = b'{"id": 1, "name": "ada"}',
    *,
    headers: dict[str, str] | None = None,
) -> tuple[Client, list[httpx2.Request]]:
    recorded: list[httpx2.Request] = []
    response_headers = {"content-type": "application/json"}
    if headers is not None:
        response_headers.update(headers)

    def handler(request: httpx2.Request) -> httpx2.Response:
        recorded.append(request)
        return httpx2.Response(HTTPStatus.OK, content=payload, headers=response_headers, request=request)

    client = Client(httpx2_client=httpx2.Client(transport=httpx2.MockTransport(handler)))
    return client, recorded


@pytest.mark.parametrize(
    ("verb", "expected_method"),
    [("get", "GET"), ("post", "POST"), ("put", "PUT"), ("patch", "PATCH"), ("delete", "DELETE")],
)
def test_verb_with_response_returns_pair_and_sends_right_method(verb: str, expected_method: str) -> None:
    client, recorded = _echo_client()
    method = getattr(client, f"{verb}_with_response")
    response, user = method("https://example.test/u", response_model=_User)
    assert isinstance(response, httpx2.Response)
    assert user == _User(id=1, name="ada")
    assert recorded[0].method == expected_method


def test_request_with_response_returns_pair() -> None:
    client, recorded = _echo_client()
    response, user = client.request_with_response("GET", "https://example.test/u", response_model=_User)
    assert isinstance(response, httpx2.Response)
    assert user == _User(id=1, name="ada")
    assert recorded[0].method == "GET"


def test_get_with_response_preserves_headers() -> None:
    client, _ = _echo_client(headers={"link": '<https://example.test/u?page=2>; rel="next"'})
    response, _user = client.get_with_response("https://example.test/u", response_model=_User)
    assert response.headers.get("link") == '<https://example.test/u?page=2>; rel="next"'


def test_post_with_response_forwards_json_body() -> None:
    client, recorded = _echo_client()
    client.post_with_response("https://example.test/u", json={"name": "ada"}, response_model=_User)
    assert recorded[0].content == b'{"name":"ada"}'


def test_with_response_decode_failure_raises_decode_error() -> None:
    client, _ = _echo_client(payload=b"null")
    with pytest.raises(DecodeError) as exc_info:
        client.get_with_response("https://example.test/u", response_model=_User)
    assert exc_info.value.model is _User


def test_with_response_missing_decoder_before_http_call() -> None:
    def handler(_: httpx2.Request) -> httpx2.Response:  # pragma: no cover
        pytest.fail("transport should not be invoked when MissingDecoderError fires")

    client = Client(httpx2_client=httpx2.Client(transport=httpx2.MockTransport(handler)), decoders=[])

    class _Foo:
        pass

    with pytest.raises(MissingDecoderError):
        client.get_with_response("https://example.test/x", response_model=_Foo)

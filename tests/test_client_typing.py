"""Static-typing tests for AsyncClient and Client overloads.

Assertions come in two forms:
- Runtime ``isinstance`` checks that verify the overload selected at call
  time (send / send_with_response with and without response_model).
- Static ``typing.assert_type`` calls that let ty/mypy verify the inferred
  return type during ``just lint``.
"""

import typing
from http import HTTPStatus

import httpx2
import pydantic
import pytest

from httpware import AsyncClient, Client


class _User(pydantic.BaseModel):
    id: int
    name: str


async def test_get_without_response_model_returns_response() -> None:
    transport = httpx2.MockTransport(
        lambda req: httpx2.Response(HTTPStatus.OK, request=req, json={"id": 1, "name": "a"})
    )
    client = AsyncClient(httpx2_client=httpx2.AsyncClient(transport=transport))
    result = await client.get("https://example.test/x")
    assert isinstance(result, httpx2.Response)


async def test_get_with_response_model_returns_typed() -> None:
    transport = httpx2.MockTransport(
        lambda req: httpx2.Response(HTTPStatus.OK, request=req, json={"id": 1, "name": "a"})
    )
    client = AsyncClient(httpx2_client=httpx2.AsyncClient(transport=transport))
    result = await client.get("https://example.test/x", response_model=_User)
    assert isinstance(result, _User)


async def test_send_without_response_model_returns_response() -> None:
    transport = httpx2.MockTransport(
        lambda req: httpx2.Response(HTTPStatus.OK, request=req, json={"id": 1, "name": "a"})
    )
    client = AsyncClient(httpx2_client=httpx2.AsyncClient(transport=transport))
    result = await client.send(httpx2.Request("GET", "https://example.test/x"))
    assert isinstance(result, httpx2.Response)


async def test_send_with_response_model_returns_typed() -> None:
    transport = httpx2.MockTransport(
        lambda req: httpx2.Response(HTTPStatus.OK, request=req, json={"id": 1, "name": "a"})
    )
    client = AsyncClient(httpx2_client=httpx2.AsyncClient(transport=transport))
    result = await client.send(httpx2.Request("GET", "https://example.test/x"), response_model=_User)
    assert isinstance(result, _User)


# ---------------------------------------------------------------------------
# Sync Client overload tests — mirrors of each async case above
# ---------------------------------------------------------------------------


def test_sync_get_without_response_model_returns_response() -> None:
    transport = httpx2.MockTransport(
        lambda req: httpx2.Response(HTTPStatus.OK, request=req, json={"id": 1, "name": "a"})
    )
    client = Client(httpx2_client=httpx2.Client(transport=transport))
    result = client.get("https://example.test/x")
    assert isinstance(result, httpx2.Response)


def test_sync_get_with_response_model_returns_typed() -> None:
    transport = httpx2.MockTransport(
        lambda req: httpx2.Response(HTTPStatus.OK, request=req, json={"id": 1, "name": "a"})
    )
    client = Client(httpx2_client=httpx2.Client(transport=transport))
    result = client.get("https://example.test/x", response_model=_User)
    assert isinstance(result, _User)


def test_sync_send_without_response_model_returns_response() -> None:
    transport = httpx2.MockTransport(
        lambda req: httpx2.Response(HTTPStatus.OK, request=req, json={"id": 1, "name": "a"})
    )
    client = Client(httpx2_client=httpx2.Client(transport=transport))
    result = client.send(httpx2.Request("GET", "https://example.test/x"))
    assert isinstance(result, httpx2.Response)


def test_sync_send_with_response_model_returns_typed() -> None:
    transport = httpx2.MockTransport(
        lambda req: httpx2.Response(HTTPStatus.OK, request=req, json={"id": 1, "name": "a"})
    )
    client = Client(httpx2_client=httpx2.Client(transport=transport))
    result = client.send(httpx2.Request("GET", "https://example.test/x"), response_model=_User)
    assert isinstance(result, _User)


# ---------------------------------------------------------------------------
# *_with_response static-type assertions — validates tuple[Response, T] destructuring
# ---------------------------------------------------------------------------


async def test_get_with_response_return_type() -> None:
    transport = httpx2.MockTransport(
        lambda req: httpx2.Response(HTTPStatus.OK, request=req, json={"id": 1, "name": "a"})
    )
    client = AsyncClient(httpx2_client=httpx2.AsyncClient(transport=transport))
    response, user = await client.get_with_response("https://example.test/x", response_model=_User)
    typing.assert_type(response, httpx2.Response)
    typing.assert_type(user, _User)
    assert isinstance(response, httpx2.Response)
    assert isinstance(user, _User)


def test_sync_get_with_response_return_type() -> None:
    transport = httpx2.MockTransport(
        lambda req: httpx2.Response(HTTPStatus.OK, request=req, json={"id": 1, "name": "a"})
    )
    client = Client(httpx2_client=httpx2.Client(transport=transport))
    response, user = client.get_with_response("https://example.test/x", response_model=_User)
    typing.assert_type(response, httpx2.Response)
    typing.assert_type(user, _User)
    assert isinstance(response, httpx2.Response)
    assert isinstance(user, _User)


# ---------------------------------------------------------------------------
# Unknown keywords — rejected by the type checker and at runtime, in both worlds
# ---------------------------------------------------------------------------

_URL = "https://example.test/x"
_VERBS = ("get", "head", "options", "post", "put", "patch", "delete")
_WITH_RESPONSE_VERBS = ("get", "post", "put", "patch", "delete")
_METHOD_NAMES = (*_VERBS, *(f"{verb}_with_response" for verb in _WITH_RESPONSE_VERBS))


def _sync_client() -> Client:
    transport = httpx2.MockTransport(
        lambda req: httpx2.Response(HTTPStatus.OK, request=req, json={"id": 1, "name": "a"})
    )
    return Client(httpx2_client=httpx2.Client(transport=transport))


def _async_client() -> AsyncClient:
    transport = httpx2.MockTransport(
        lambda req: httpx2.Response(HTTPStatus.OK, request=req, json={"id": 1, "name": "a"})
    )
    return AsyncClient(httpx2_client=httpx2.AsyncClient(transport=transport))


def _unknown_keyword(owner: str, keyword: str = "foo") -> str:
    return rf"^{owner}\(\) got an unexpected keyword argument '{keyword}'$"


def test_sync_options_keep_the_overload_return_types() -> None:
    client = _sync_client()
    typing.assert_type(client.get(_URL, params={"q": "1"}, timeout=None), httpx2.Response)
    typing.assert_type(client.post(_URL, json={"a": 1}, response_model=_User), _User)
    typing.assert_type(
        client.request_with_response("PUT", _URL, content=b"x", response_model=_User), tuple[httpx2.Response, _User]
    )


async def test_options_keep_the_overload_return_types() -> None:
    client = _async_client()
    typing.assert_type(await client.get(_URL, params={"q": "1"}, timeout=None), httpx2.Response)
    typing.assert_type(await client.post(_URL, json={"a": 1}, response_model=_User), _User)
    typing.assert_type(
        await client.request_with_response("PUT", _URL, content=b"x", response_model=_User),
        tuple[httpx2.Response, _User],
    )


def test_sync_unknown_keyword_is_rejected_statically_and_at_runtime() -> None:
    client = _sync_client()
    with pytest.raises(TypeError, match=_unknown_keyword("Client.get")):
        client.get(_URL, foo=1)  # ty: ignore[no-matching-overload]
    with pytest.raises(TypeError, match=_unknown_keyword("Client.get", "json")):
        client.get(_URL, json={"a": 1})  # ty: ignore[no-matching-overload]
    with pytest.raises(TypeError, match=_unknown_keyword("Client.post_with_response")):
        client.post_with_response(_URL, response_model=_User, foo=1)  # ty: ignore[unknown-argument]
    with pytest.raises(TypeError, match=_unknown_keyword("Client.request")):
        client.request("GET", _URL, foo=1)  # ty: ignore[no-matching-overload]
    with pytest.raises(TypeError, match=_unknown_keyword("Client.request_with_response")):
        client.request_with_response("GET", _URL, response_model=_User, foo=1)  # ty: ignore[unknown-argument]
    with pytest.raises(TypeError, match=_unknown_keyword("Client.stream")):
        client.stream("GET", _URL, foo=1).__enter__()  # ty: ignore[unknown-argument]


async def test_unknown_keyword_is_rejected_statically_and_at_runtime() -> None:
    client = _async_client()
    with pytest.raises(TypeError, match=_unknown_keyword("AsyncClient.get")):
        await client.get(_URL, foo=1)  # ty: ignore[no-matching-overload]
    with pytest.raises(TypeError, match=_unknown_keyword("AsyncClient.get", "json")):
        await client.get(_URL, json={"a": 1})  # ty: ignore[no-matching-overload]
    with pytest.raises(TypeError, match=_unknown_keyword("AsyncClient.post_with_response")):
        await client.post_with_response(_URL, response_model=_User, foo=1)  # ty: ignore[unknown-argument]
    with pytest.raises(TypeError, match=_unknown_keyword("AsyncClient.request")):
        await client.request("GET", _URL, foo=1)  # ty: ignore[no-matching-overload]
    with pytest.raises(TypeError, match=_unknown_keyword("AsyncClient.request_with_response")):
        await client.request_with_response("GET", _URL, response_model=_User, foo=1)  # ty: ignore[unknown-argument]
    with pytest.raises(TypeError, match=_unknown_keyword("AsyncClient.stream")):
        await client.stream("GET", _URL, foo=1).__aenter__()  # ty: ignore[unknown-argument]


@pytest.mark.parametrize("name", _METHOD_NAMES)
def test_sync_every_verb_rejects_an_unknown_keyword_at_runtime(name: str) -> None:
    with pytest.raises(TypeError, match=_unknown_keyword(f"Client.{name}")):
        getattr(_sync_client(), name)(_URL, response_model=_User, foo=1)


@pytest.mark.parametrize("name", _METHOD_NAMES)
async def test_every_verb_rejects_an_unknown_keyword_at_runtime(name: str) -> None:
    with pytest.raises(TypeError, match=_unknown_keyword(f"AsyncClient.{name}")):
        await getattr(_async_client(), name)(_URL, response_model=_User, foo=1)

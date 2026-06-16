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

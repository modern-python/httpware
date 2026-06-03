"""Static-typing tests for AsyncClient overloads.

These assert overload selection at runtime via isinstance checks. ty/mypy
catches the static-typing variant during `just lint`.
"""

from http import HTTPStatus

import httpx2
import pydantic

from httpware import AsyncClient


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

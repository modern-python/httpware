"""Dispatch routing across multiple registered decoders.

Covers the routing examples in planning/specs/2026-06-09-multi-decoder-design.md
§ Architecture — native types route via their library regardless of order,
shared shapes route to the first decoder in the list.
"""

import dataclasses
from http import HTTPStatus

import httpx2
import msgspec
import pydantic
import pytest

from httpware import AsyncClient, Client, MissingDecoderError
from httpware.decoders.msgspec import MsgspecDecoder
from httpware.decoders.pydantic import PydanticDecoder


class _PydanticUser(pydantic.BaseModel):
    id: int
    name: str


class _MsgspecUser(msgspec.Struct):
    id: int
    name: str


@dataclasses.dataclass
class _DC:
    id: int
    name: str


def _async_client_with_body(payload: bytes, decoders: list) -> AsyncClient:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(HTTPStatus.OK, content=payload, request=request)

    transport = httpx2.MockTransport(handler)
    return AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=transport),
        decoders=decoders,
    )


def _sync_client_with_body(payload: bytes, decoders: list) -> Client:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(HTTPStatus.OK, content=payload, request=request)

    transport = httpx2.MockTransport(handler)
    return Client(
        httpx2_client=httpx2.Client(transport=transport),
        decoders=decoders,
    )


async def test_async_basemodel_routes_to_pydantic() -> None:
    client = _async_client_with_body(
        b'{"id": 1, "name": "Ada"}',
        decoders=[PydanticDecoder(), MsgspecDecoder()],
    )
    result = await client.get("https://example.test/x", response_model=_PydanticUser)
    assert type(result) is _PydanticUser
    assert result.id == 1


async def test_async_struct_routes_to_msgspec() -> None:
    client = _async_client_with_body(
        b'{"id": 1, "name": "Ada"}',
        decoders=[PydanticDecoder(), MsgspecDecoder()],
    )
    result = await client.get("https://example.test/x", response_model=_MsgspecUser)
    assert type(result) is _MsgspecUser
    assert result.id == 1


async def test_async_dict_routes_to_first_decoder() -> None:
    """Shared shape: first decoder in the list wins."""
    pyd = PydanticDecoder()
    msg = MsgspecDecoder()
    client = _async_client_with_body(b'{"a": 1}', decoders=[pyd, msg])
    result = await client.get("https://example.test/x", response_model=dict[str, int])
    assert type(result) is dict
    assert result == {"a": 1}


async def test_async_dict_routes_to_msgspec_when_first() -> None:
    """Reversed list flips routing for shared shapes."""
    client = _async_client_with_body(
        b'{"a": 1}',
        decoders=[MsgspecDecoder(), PydanticDecoder()],
    )
    result = await client.get("https://example.test/x", response_model=dict[str, int])
    assert result == {"a": 1}


async def test_async_dataclass_routes_to_first_decoder() -> None:
    client = _async_client_with_body(
        b'{"id": 1, "name": "Ada"}',
        decoders=[PydanticDecoder(), MsgspecDecoder()],
    )
    result = await client.get("https://example.test/x", response_model=_DC)
    assert type(result) is _DC
    assert result.id == 1


async def test_async_list_of_basemodel_routes_to_pydantic() -> None:
    client = _async_client_with_body(
        b'[{"id": 1, "name": "Ada"}, {"id": 2, "name": "Bo"}]',
        decoders=[PydanticDecoder(), MsgspecDecoder()],
    )
    result = await client.get("https://example.test/x", response_model=list[_PydanticUser])
    assert len(result) == 2  # noqa: PLR2004
    assert all(type(item) is _PydanticUser for item in result)


async def test_async_missing_decoder_with_empty_list() -> None:
    """Empty decoder list and response_model= raises before HTTP call."""

    def handler(_: httpx2.Request) -> httpx2.Response:  # pragma: no cover
        pytest.fail("transport should not be invoked")

    transport = httpx2.MockTransport(handler)
    client = AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=transport),
        decoders=[],
    )
    with pytest.raises(MissingDecoderError) as exc_info:
        await client.get("https://example.test/x", response_model=_PydanticUser)
    assert exc_info.value.registered_names == ()


async def test_async_missing_decoder_when_none_claim() -> None:
    """Registered decoders that all reject the model raise MissingDecoderError."""

    class _Stub:
        def can_decode(self, model: type) -> bool:  # noqa: ARG002
            return False

        def decode(self, content: bytes, model: type) -> object:  # noqa: ARG002  # pragma: no cover
            return None

    def handler(_: httpx2.Request) -> httpx2.Response:  # pragma: no cover
        pytest.fail("transport should not be invoked")

    transport = httpx2.MockTransport(handler)
    client = AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=transport),
        decoders=[_Stub()],
    )
    with pytest.raises(MissingDecoderError) as exc_info:
        await client.get("https://example.test/x", response_model=_PydanticUser)
    assert exc_info.value.registered_names == ("_Stub",)


def test_sync_basemodel_routes_to_pydantic() -> None:
    client = _sync_client_with_body(
        b'{"id": 1, "name": "Ada"}',
        decoders=[PydanticDecoder(), MsgspecDecoder()],
    )
    result = client.get("https://example.test/x", response_model=_PydanticUser)
    assert type(result) is _PydanticUser
    client.close()


def test_sync_struct_routes_to_msgspec() -> None:
    client = _sync_client_with_body(
        b'{"id": 1, "name": "Ada"}',
        decoders=[PydanticDecoder(), MsgspecDecoder()],
    )
    result = client.get("https://example.test/x", response_model=_MsgspecUser)
    assert type(result) is _MsgspecUser
    client.close()


def test_sync_dict_routes_to_first_decoder() -> None:
    client = _sync_client_with_body(
        b'{"a": 1}',
        decoders=[PydanticDecoder(), MsgspecDecoder()],
    )
    result = client.get("https://example.test/x", response_model=dict[str, int])
    assert result == {"a": 1}
    client.close()


def test_sync_dict_routes_to_msgspec_when_first() -> None:
    client = _sync_client_with_body(
        b'{"a": 1}',
        decoders=[MsgspecDecoder(), PydanticDecoder()],
    )
    result = client.get("https://example.test/x", response_model=dict[str, int])
    assert result == {"a": 1}
    client.close()


def test_sync_missing_decoder_with_empty_list() -> None:
    def handler(_: httpx2.Request) -> httpx2.Response:  # pragma: no cover
        pytest.fail("transport should not be invoked")

    transport = httpx2.MockTransport(handler)
    client = Client(
        httpx2_client=httpx2.Client(transport=transport),
        decoders=[],
    )
    with pytest.raises(MissingDecoderError):
        client.get("https://example.test/x", response_model=_PydanticUser)
    client.close()


async def test_async_msgspec_only_list_of_basemodel_preflight_raises() -> None:
    """MsgspecDecoder-only client raises MissingDecoderError for list[BaseModel] without sending a request."""

    def handler(_: httpx2.Request) -> httpx2.Response:  # pragma: no cover
        pytest.fail("transport should not be invoked: pre-flight must reject first")

    transport = httpx2.MockTransport(handler)
    client = AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=transport),
        decoders=[MsgspecDecoder()],
    )
    with pytest.raises(MissingDecoderError) as exc_info:
        await client.get("https://example.test/x", response_model=list[_PydanticUser])
    assert exc_info.value.registered_names == ("MsgspecDecoder",)


def test_sync_msgspec_only_list_of_basemodel_preflight_raises() -> None:
    """Sync MsgspecDecoder-only client raises MissingDecoderError for list[BaseModel] without sending a request."""

    def handler(_: httpx2.Request) -> httpx2.Response:  # pragma: no cover
        pytest.fail("transport should not be invoked: pre-flight must reject first")

    transport = httpx2.MockTransport(handler)
    client = Client(
        httpx2_client=httpx2.Client(transport=transport),
        decoders=[MsgspecDecoder()],
    )
    with pytest.raises(MissingDecoderError) as exc_info:
        client.get("https://example.test/x", response_model=list[_PydanticUser])
    assert exc_info.value.registered_names == ("MsgspecDecoder",)
    client.close()

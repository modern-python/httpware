"""Dispatch routing across multiple registered decoders.

Native types route via their library regardless of order; shared shapes
route to the first decoder in the list.
"""

import contextlib
import dataclasses
from collections.abc import Iterator
from http import HTTPStatus
from unittest.mock import MagicMock, patch

import httpx2
import msgspec
import pydantic
import pytest

from httpware import AsyncClient, Client, MissingDecoderError, ResponseDecoder
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


@contextlib.contextmanager
def _decode_spies(*decoders: ResponseDecoder) -> Iterator[list[MagicMock]]:
    """Wrap each decoder's `decode` so a test can assert WHICH one ran.

    Two real decoders that both claim a shared shape (e.g. `dict[str, int]` or a
    stdlib dataclass) produce identical output, so output equality can't prove
    the ordering invariant. Spying on `decode` shows which decoder the dispatcher
    actually selected. Spies are yielded in the same order as `decoders`.
    """
    with contextlib.ExitStack() as stack:
        yield [stack.enter_context(patch.object(d, "decode", wraps=d.decode)) for d in decoders]


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
    """Shared shape (dict): the FIRST decoder in the list actually decodes it."""
    pyd, msg = PydanticDecoder(), MsgspecDecoder()
    client = _async_client_with_body(b'{"a": 1}', decoders=[pyd, msg])
    with _decode_spies(pyd, msg) as (pyd_spy, msg_spy):
        result = await client.get("https://example.test/x", response_model=dict[str, int])
    assert result == {"a": 1}
    pyd_spy.assert_called_once()
    msg_spy.assert_not_called()


async def test_async_dict_routes_to_msgspec_when_first() -> None:
    """Reversed list: the shared shape now routes to msgspec, proven by the spy."""
    msg, pyd = MsgspecDecoder(), PydanticDecoder()
    client = _async_client_with_body(b'{"a": 1}', decoders=[msg, pyd])
    with _decode_spies(msg, pyd) as (msg_spy, pyd_spy):
        result = await client.get("https://example.test/x", response_model=dict[str, int])
    assert result == {"a": 1}
    msg_spy.assert_called_once()
    pyd_spy.assert_not_called()


async def test_async_dataclass_routes_to_first_decoder() -> None:
    """Stdlib dataclass is a shared shape; the first decoder (pydantic) decodes it."""
    pyd, msg = PydanticDecoder(), MsgspecDecoder()
    client = _async_client_with_body(b'{"id": 1, "name": "Ada"}', decoders=[pyd, msg])
    with _decode_spies(pyd, msg) as (pyd_spy, msg_spy):
        result = await client.get("https://example.test/x", response_model=_DC)
    assert type(result) is _DC
    assert result.id == 1
    pyd_spy.assert_called_once()
    msg_spy.assert_not_called()


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
    """Sync twin: shared shape (dict) routes to the first decoder (pydantic)."""
    pyd, msg = PydanticDecoder(), MsgspecDecoder()
    client = _sync_client_with_body(b'{"a": 1}', decoders=[pyd, msg])
    with _decode_spies(pyd, msg) as (pyd_spy, msg_spy):
        result = client.get("https://example.test/x", response_model=dict[str, int])
    assert result == {"a": 1}
    pyd_spy.assert_called_once()
    msg_spy.assert_not_called()
    client.close()


def test_sync_dict_routes_to_msgspec_when_first() -> None:
    """Sync twin: reversed list routes the shared shape to msgspec."""
    msg, pyd = MsgspecDecoder(), PydanticDecoder()
    client = _sync_client_with_body(b'{"a": 1}', decoders=[msg, pyd])
    with _decode_spies(msg, pyd) as (msg_spy, pyd_spy):
        result = client.get("https://example.test/x", response_model=dict[str, int])
    assert result == {"a": 1}
    msg_spy.assert_called_once()
    pyd_spy.assert_not_called()
    client.close()


def test_sync_dataclass_routes_to_first_decoder() -> None:
    """Sync twin: stdlib dataclass routes to the first decoder (pydantic)."""
    pyd, msg = PydanticDecoder(), MsgspecDecoder()
    client = _sync_client_with_body(b'{"id": 1, "name": "Ada"}', decoders=[pyd, msg])
    with _decode_spies(pyd, msg) as (pyd_spy, msg_spy):
        result = client.get("https://example.test/x", response_model=_DC)
    assert type(result) is _DC
    assert result.id == 1
    pyd_spy.assert_called_once()
    msg_spy.assert_not_called()
    client.close()


def test_sync_list_of_basemodel_routes_to_pydantic() -> None:
    """Sync twin: list[BaseModel] is claimed only by pydantic (msgspec rejects it)."""
    client = _sync_client_with_body(
        b'[{"id": 1, "name": "Ada"}, {"id": 2, "name": "Bo"}]',
        decoders=[PydanticDecoder(), MsgspecDecoder()],
    )
    result = client.get("https://example.test/x", response_model=list[_PydanticUser])
    assert len(result) == 2  # noqa: PLR2004
    assert all(type(item) is _PydanticUser for item in result)
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

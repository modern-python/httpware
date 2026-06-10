"""Unit tests for httpware.decoders.msgspec.MsgspecDecoder."""

import dataclasses
from http import HTTPStatus
from unittest.mock import patch

import httpx2
import msgspec
import pydantic
import pytest

from httpware import AsyncClient, DecodeError
from httpware._internal import import_checker
from httpware.decoders import ResponseDecoder
from httpware.decoders.msgspec import MsgspecDecoder, _get_msgspec_decoder


class _Item(msgspec.Struct):
    name: str
    qty: int


def test_decoder_satisfies_response_decoder_protocol() -> None:
    assert isinstance(MsgspecDecoder(), ResponseDecoder)


def test_decode_into_msgspec_struct() -> None:
    result = MsgspecDecoder().decode(b'{"name":"x","qty":1}', _Item)
    assert result == _Item(name="x", qty=1)


def test_decode_into_builtin_type() -> None:
    result = MsgspecDecoder().decode(b"42", int)
    assert result == 42  # noqa: PLR2004


def test_decode_into_list_of_struct() -> None:
    result = MsgspecDecoder().decode(b'[{"name":"a","qty":1}]', list[_Item])
    assert result == [_Item(name="a", qty=1)]


def test_decode_validation_error_propagates() -> None:
    with pytest.raises(msgspec.ValidationError):
        MsgspecDecoder().decode(b'{"name":"x","qty":"not-an-int"}', _Item)


def test_decode_json_parse_error_propagates() -> None:
    with pytest.raises(msgspec.DecodeError):
        MsgspecDecoder().decode(b"{", _Item)


def test_construction_raises_without_extra_via_monkeypatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(import_checker, "is_msgspec_installed", False)
    with pytest.raises(ImportError, match="MsgspecDecoder requires the 'msgspec' extra"):
        MsgspecDecoder()


async def test_msgspec_decoder_failures_wrap_as_decode_error_at_seam() -> None:
    """Proves wrapping is decoder-agnostic: switching to MsgspecDecoder still yields DecodeError."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(HTTPStatus.OK, content=b"{not json", request=request)

    transport = httpx2.MockTransport(handler)
    client = AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=transport),
        decoders=[MsgspecDecoder()],
    )
    with pytest.raises(DecodeError) as exc_info:
        await client.get("https://example.test/x", response_model=_Item)
    exc = exc_info.value
    assert exc.model is _Item
    assert isinstance(exc.original, (msgspec.DecodeError, msgspec.ValidationError))


class _PydanticUser(pydantic.BaseModel):
    id: int
    name: str


@dataclasses.dataclass
class _DC:
    id: int
    name: str


@pytest.fixture(autouse=True)
def _clear_msgspec_cache() -> None:
    _get_msgspec_decoder.cache_clear()


def test_msgspec_can_decode_struct() -> None:
    assert MsgspecDecoder().can_decode(_Item) is True


def test_msgspec_can_decode_dataclass() -> None:
    assert MsgspecDecoder().can_decode(_DC) is True


def test_msgspec_can_decode_dict() -> None:
    assert MsgspecDecoder().can_decode(dict) is True


def test_msgspec_can_decode_list_of_structs() -> None:
    assert MsgspecDecoder().can_decode(list[_Item]) is True


def test_msgspec_can_decode_primitive_int() -> None:
    assert MsgspecDecoder().can_decode(int) is True


def test_msgspec_rejects_pydantic_basemodel() -> None:
    assert MsgspecDecoder().can_decode(_PydanticUser) is False


def test_msgspec_can_decode_uses_cache() -> None:
    _get_msgspec_decoder.cache_clear()
    decoder = MsgspecDecoder()
    decoder.can_decode(_Item)
    decoder.can_decode(_Item)
    info = _get_msgspec_decoder.cache_info()
    assert info.hits >= 1
    assert info.misses == 1


def test_can_decode_returns_false_when_type_info_raises() -> None:
    """`type_info` failures (unrecognized type) are treated as a soft 'no'."""
    with patch(
        "httpware.decoders.msgspec.msgspec.inspect.type_info",
        side_effect=TypeError("unknown"),
    ):
        assert MsgspecDecoder().can_decode(_Item) is False


def test_can_decode_returns_false_when_decoder_build_raises() -> None:
    """A `_get_msgspec_decoder` failure after type_info-classification is a soft 'no'."""
    _get_msgspec_decoder.cache_clear()
    with patch(
        "httpware.decoders.msgspec._get_msgspec_decoder",
        side_effect=TypeError("cannot build decoder"),
    ):
        assert MsgspecDecoder().can_decode(_Item) is False


def test_unhashable_model_falls_back_to_uncached_decoder() -> None:
    """Unhashable `model` falls back to a direct uncached `msgspec.json.Decoder`.

    Mirrors `PydanticDecoder`'s unhashable-fallback test: when `_get_msgspec_decoder`
    raises `TypeError` (e.g., an unhashable parameterized type), `decode` bypasses
    the cache so the user-visible error is `msgspec`'s own decode error, not a
    `functools`-internal `TypeError`.
    """
    with patch(
        "httpware.decoders.msgspec._get_msgspec_decoder",
        side_effect=TypeError("unhashable type"),
    ):
        result = MsgspecDecoder().decode(b"42", int)
        assert result == 42  # noqa: PLR2004

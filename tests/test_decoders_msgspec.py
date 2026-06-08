"""Unit tests for httpware.decoders.msgspec.MsgspecDecoder."""

from http import HTTPStatus

import httpx2
import msgspec
import pytest

from httpware import AsyncClient, DecodeError
from httpware._internal import import_checker
from httpware.decoders import ResponseDecoder
from httpware.decoders.msgspec import MsgspecDecoder


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
        decoder=MsgspecDecoder(),
    )
    with pytest.raises(DecodeError) as exc_info:
        await client.get("https://example.test/x", response_model=_Item)
    exc = exc_info.value
    assert exc.model is _Item
    assert isinstance(exc.original, (msgspec.DecodeError, msgspec.ValidationError))

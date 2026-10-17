"""Unit tests for httpware.decoders.msgspec.MsgspecDecoder."""

import dataclasses
import typing
from http import HTTPStatus
from unittest.mock import MagicMock, patch

import httpx2
import msgspec
import pydantic
import pytest

from httpware import AsyncClient, Client, DecodeError, MissingDecoderError
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
    decoder = MsgspecDecoder()
    decoder.can_decode(_Item)
    decoder.can_decode(_Item)
    assert len(decoder._adapters) == 1  # noqa: SLF001
    assert _Item in decoder._adapters  # noqa: SLF001


def test_can_decode_returns_false_when_type_info_raises() -> None:
    """`type_info` failures (unrecognized type) are treated as a soft 'no'."""
    with patch(
        "httpware.decoders.msgspec.msgspec.inspect.type_info",
        side_effect=TypeError("unknown"),
    ):
        assert MsgspecDecoder().can_decode(_Item) is False


def test_can_decode_returns_false_when_decoder_build_raises() -> None:
    """A `msgspec.json.Decoder` failure after type_info-classification is a soft 'no'."""
    with patch(
        "httpware.decoders.msgspec.msgspec.json.Decoder",
        side_effect=TypeError("cannot build decoder"),
    ):
        assert MsgspecDecoder().can_decode(_Item) is False


def test_unhashable_model_falls_back_to_uncached_decoder() -> None:
    """Unhashable `model` falls back to a direct uncached `msgspec.json.Decoder`.

    Mirrors `PydanticDecoder`'s unhashable-fallback test: when the decoder
    cache lookup raises `TypeError` (e.g., an unhashable parameterized
    type), `decode` bypasses the cache so the user-visible error is
    `msgspec`'s own decode error, not a `TypeError` from the cache lookup.
    """
    decoder = MsgspecDecoder()
    decoder._adapters = MagicMock()  # noqa: SLF001
    decoder._adapters.get.side_effect = TypeError("unhashable type")  # noqa: SLF001

    result = decoder.decode(b"42", int)
    assert result == 42  # noqa: PLR2004


@pytest.mark.parametrize(
    "model",
    [
        list[_PydanticUser],
        dict[str, _PydanticUser],
        dict[_PydanticUser, str],
        _PydanticUser | None,
        tuple[_PydanticUser, int],
        list[list[_PydanticUser]],
        set[_PydanticUser],
    ],
)
def test_msgspec_rejects_containers_of_pydantic_models(model: type) -> None:
    """Nested CustomType (a pydantic model inside a container) must be rejected.

    Before the fix, can_decode inspected only the top-level type_info node, so a
    container parameterized by a BaseModel slipped past and built a decoder via
    the CustomType fallback — bypassing the MissingDecoderError pre-flight.
    """
    assert MsgspecDecoder().can_decode(model) is False


@pytest.mark.parametrize(
    "model",
    [
        _Item,
        list[_Item],
        dict[str, _Item],
        list[list[_Item]],
        dict[str, int],
        list[int],
        int,
    ],
)
def test_msgspec_still_accepts_native_containers(model: type) -> None:
    """Containers parameterized only by msgspec-native types stay accepted.

    Guards against the recursive walker over-rejecting: the walk must stop at
    Struct boundaries (StructType.fields are Field, not Type) and must not flag
    plain builtin element types.
    """
    assert MsgspecDecoder().can_decode(model) is True


def test_msgspec_can_decode_result_is_cached() -> None:
    """Repeat can_decode calls reuse a cached verdict, not the per-dispatch probe."""
    decoder = MsgspecDecoder()
    with patch(
        "httpware.decoders.msgspec.msgspec.inspect.type_info",
        wraps=msgspec.inspect.type_info,
    ) as spy:
        assert decoder.can_decode(_Item) is True
        assert decoder.can_decode(_Item) is True
    assert spy.call_count == 1
    assert decoder._adapters[_Item][1] is not None  # noqa: SLF001


def test_msgspec_can_decode_caches_negative_verdict() -> None:
    """A rejection is cached too, so repeat probes don't repeat the walk."""
    decoder = MsgspecDecoder()
    with patch(
        "httpware.decoders.msgspec.msgspec.inspect.type_info",
        wraps=msgspec.inspect.type_info,
    ) as spy:
        assert decoder.can_decode(_PydanticUser) is False
        assert decoder.can_decode(_PydanticUser) is False
    assert spy.call_count == 1
    assert decoder._adapters[_PydanticUser] == (_PydanticUser, None)  # noqa: SLF001


def test_msgspec_can_decode_unhashable_model_does_not_raise() -> None:
    """An unhashable model falls back to a fresh probe instead of raising from the cache."""
    decoder = MsgspecDecoder()
    decoder._adapters = MagicMock()  # noqa: SLF001
    decoder._adapters.get.side_effect = TypeError("unhashable type")  # noqa: SLF001
    assert decoder.can_decode(_Item) is True


def test_can_decode_agrees_with_decode_for_unhashable_buildable_model() -> None:
    """can_decode and decode must agree for a genuinely unhashable, schema-buildable model.

    `typing.Annotated[int, []]` is unhashable (its metadata is a list) but
    msgspec can still build a decoder for it. Before this refactor,
    can_decode incorrectly returned False for any unhashable model
    regardless of buildability; decode() already worked correctly for
    the same model via its own fallback. This test pins the fixed,
    consistent behavior.
    """
    model = typing.Annotated[int, []]
    decoder = MsgspecDecoder()
    assert decoder.can_decode(model) is True  # ty: ignore[invalid-argument-type]
    assert decoder.decode(b"42", model) == 42  # noqa: PLR2004  # ty: ignore[invalid-argument-type]


class _Opaque:
    pass


class _StructWithPydanticField(msgspec.Struct):
    user: _PydanticUser


class _StructWithOptionalPydanticList(msgspec.Struct):
    users: list[_PydanticUser] | None


class _Outer(msgspec.Struct):
    inner: _StructWithPydanticField


@dataclasses.dataclass
class _DCWithOpaqueField:
    thing: _Opaque


class _TDWithPydanticField(typing.TypedDict):
    user: _PydanticUser


class _NTWithPydanticField(typing.NamedTuple):
    user: _PydanticUser


class _Node(msgspec.Struct):
    value: int
    children: "list[_Node]"


class _BadNode(msgspec.Struct):
    children: "list[_BadNode]"
    user: _PydanticUser


@pytest.mark.parametrize(
    "model",
    [
        _StructWithPydanticField,
        _StructWithOptionalPydanticList,
        _Outer,
        list[_Outer],
        _DCWithOpaqueField,
        _TDWithPydanticField,
        _NTWithPydanticField,
        _BadNode,
        typing.Annotated[_StructWithPydanticField, msgspec.Meta(title="x")],
    ],
)
def test_msgspec_rejects_models_with_fields_it_cannot_decode(model: type) -> None:
    assert MsgspecDecoder().can_decode(model) is False


def test_msgspec_accepts_self_referential_struct() -> None:
    decoder = MsgspecDecoder()
    assert decoder.can_decode(_Node) is True
    assert decoder.decode(b'{"value":1,"children":[{"value":2,"children":[]}]}', _Node) == _Node(
        value=1, children=[_Node(value=2, children=[])]
    )


def test_unhashable_model_builds_decoder_once() -> None:
    with patch("httpware.decoders.msgspec.msgspec.json.Decoder", wraps=msgspec.json.Decoder) as spy:
        decoder = MsgspecDecoder()
        for _ in range(3):
            model = typing.Annotated[list[int], {"a": 1}]
            assert decoder.can_decode(model) is True  # ty: ignore[invalid-argument-type]
            assert decoder.decode(b"[1]", model) == [1]  # ty: ignore[invalid-argument-type]
    assert spy.call_count == 1


def _never_called(request: httpx2.Request) -> httpx2.Response:  # pragma: no cover — the request must not go out
    raise AssertionError(request.url)


def test_client_rejects_struct_with_unsupported_field_before_sending() -> None:
    client = Client(
        httpx2_client=httpx2.Client(transport=httpx2.MockTransport(_never_called)),
        decoders=[MsgspecDecoder()],
    )
    with pytest.raises(MissingDecoderError):
        client.get("https://example.test/x", response_model=_StructWithPydanticField)


async def test_async_client_rejects_struct_with_unsupported_field_before_sending() -> None:
    client = AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=httpx2.MockTransport(_never_called)),
        decoders=[MsgspecDecoder()],
    )
    with pytest.raises(MissingDecoderError):
        await client.get("https://example.test/x", response_model=_StructWithPydanticField)


class _BrokenRepr:
    __hash__ = None

    def __repr__(self) -> str:
        raise RuntimeError


def test_model_that_cannot_be_keyed_is_still_decoded() -> None:
    model = typing.Annotated[int, _BrokenRepr()]
    decoder = MsgspecDecoder()
    assert decoder.can_decode(model) is True  # ty: ignore[invalid-argument-type]
    assert decoder.decode(b"42", model) == 42  # noqa: PLR2004  # ty: ignore[invalid-argument-type]


def test_decode_into_rejected_model_raises_msgspec_error() -> None:
    with pytest.raises(msgspec.ValidationError):
        MsgspecDecoder().decode(b'{"id": 1, "name": "Ada"}', _PydanticUser)

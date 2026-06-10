"""Tests for `httpware.decoders.pydantic.PydanticDecoder` (Story 1.5)."""

import asyncio
import concurrent.futures
import dataclasses
from unittest.mock import patch

import msgspec
import pydantic
import pytest

from httpware import ResponseDecoder
from httpware.decoders.pydantic import PydanticDecoder


class User(pydantic.BaseModel):
    """Test pydantic model."""

    id: int
    name: str


@dataclasses.dataclass
class UserDC:
    """Test stdlib dataclass model."""

    id: int
    name: str


def test_pydantic_decoder_satisfies_response_decoder_protocol() -> None:
    assert isinstance(PydanticDecoder(), ResponseDecoder)


def test_pydantic_decoder_does_not_inherit_response_decoder() -> None:
    assert ResponseDecoder not in PydanticDecoder.__mro__


def test_decodes_basemodel_subclass() -> None:
    result = PydanticDecoder().decode(b'{"id": 1, "name": "Ada"}', User)
    assert type(result) is User
    assert result.id == 1
    assert result.name == "Ada"


def test_decodes_stdlib_dataclass() -> None:
    result = PydanticDecoder().decode(b'{"id": 1, "name": "Ada"}', UserDC)
    assert type(result) is UserDC
    assert result.id == 1
    assert result.name == "Ada"


def test_decodes_list_of_models() -> None:
    result = PydanticDecoder().decode(
        b'[{"id": 1, "name": "Ada"}, {"id": 2, "name": "Bo"}]',
        list[User],
    )
    assert type(result) is list
    assert len(result) == 2  # noqa: PLR2004
    assert all(type(item) is User for item in result)
    assert result[0].id == 1
    assert result[0].name == "Ada"
    assert result[1].id == 2  # noqa: PLR2004
    assert result[1].name == "Bo"


def test_decodes_dict_of_models() -> None:
    result = PydanticDecoder().decode(b'{"u1": {"id": 1, "name": "Ada"}}', dict[str, User])
    assert type(result) is dict
    assert list(result.keys()) == ["u1"]
    assert type(result["u1"]) is User
    assert result["u1"].id == 1
    assert result["u1"].name == "Ada"


def test_decodes_primitive_int() -> None:
    result = PydanticDecoder().decode(b"42", int)
    assert type(result) is int
    assert result == 42  # noqa: PLR2004


def test_validation_error_surfaces_unchanged() -> None:
    with pytest.raises(pydantic.ValidationError):
        PydanticDecoder().decode(b'{"id": "not-a-number", "name": "Ada"}', User)


def test_cache_invariance_single_model() -> None:
    with patch("httpware.decoders.pydantic.TypeAdapter", wraps=pydantic.TypeAdapter) as spy:
        decoder = PydanticDecoder()
        for _ in range(1000):
            decoder.decode(b'{"id": 1, "name": "Ada"}', User)
        assert spy.call_count == 1


def test_cache_invariance_two_distinct_models() -> None:
    with patch("httpware.decoders.pydantic.TypeAdapter", wraps=pydantic.TypeAdapter) as spy:
        decoder = PydanticDecoder()
        for _ in range(500):
            decoder.decode(b'{"id": 1, "name": "Ada"}', User)
            decoder.decode(b'{"id": 1, "name": "Ada"}', UserDC)
        assert spy.call_count == 2  # noqa: PLR2004 — two distinct model types


async def test_cache_invariance_concurrent_first_calls() -> None:
    with patch("httpware.decoders.pydantic.TypeAdapter", wraps=pydantic.TypeAdapter) as spy:
        decoder = PydanticDecoder()

        async def one_decode() -> User:
            return decoder.decode(b'{"id": 1, "name": "Ada"}', User)

        await asyncio.gather(*(one_decode() for _ in range(50)))
        assert spy.call_count == 1


def test_cache_invariance_concurrent_first_calls_threadpool() -> None:
    n_workers = 20
    with patch("httpware.decoders.pydantic.TypeAdapter", wraps=pydantic.TypeAdapter) as spy:
        decoder = PydanticDecoder()

        def one_decode(_: int) -> User:
            return decoder.decode(b'{"id": 1, "name": "Ada"}', User)

        with concurrent.futures.ThreadPoolExecutor(max_workers=n_workers) as pool:
            results = list(pool.map(one_decode, range(50)))

        assert all(type(r) is User and r.id == 1 for r in results)
        # `dict` reads/writes are atomic in CPython but the get→set sequence in
        # `_get_adapter` is not — concurrent first-callers may both build a
        # TypeAdapter before one wins (idempotent; loser is GC'd). Bounded by
        # worker count.
        assert 1 <= spy.call_count <= n_workers


def test_unhashable_model_falls_back_to_uncached_adapter() -> None:
    """Unhashable `model` falls back to a direct uncached `TypeAdapter`.

    When `_get_adapter` raises `TypeError` (e.g., `Annotated[int, unhashable_metadata]`),
    `decode` bypasses the cache so `pydantic.ValidationError` surfaces cleanly instead
    of leaking a `TypeError` to the caller.
    """
    with patch.object(
        PydanticDecoder,
        "_get_adapter",
        side_effect=TypeError("unhashable type"),
    ):
        result = PydanticDecoder().decode(b"42", int)
        assert result == 42  # noqa: PLR2004

        with pytest.raises(pydantic.ValidationError):
            PydanticDecoder().decode(b'"not-an-int"', int)


@pytest.mark.parametrize(
    ("payload", "model"),
    [
        (b"", int),
        (b"", User),
        (b"null", int),
        (b"null", User),
        (b"{}", User),
        (b"{not-json}", User),
        (b"\xff\xfe\x00\x00", User),
    ],
)
def test_malformed_payload_raises_validation_error(payload: bytes, model: type) -> None:
    """Pin current pydantic-core behavior for malformed payloads.

    A future pydantic upgrade that changes which error type surfaces will fail
    this test, surfacing the change for explicit acceptance or workaround.
    """
    with pytest.raises(pydantic.ValidationError):
        PydanticDecoder().decode(payload, model)


class _Struct(msgspec.Struct):
    id: int
    name: str


def test_pydantic_can_decode_basemodel() -> None:
    assert PydanticDecoder().can_decode(User) is True


def test_pydantic_can_decode_dataclass() -> None:
    assert PydanticDecoder().can_decode(UserDC) is True


def test_pydantic_can_decode_dict() -> None:
    assert PydanticDecoder().can_decode(dict) is True


def test_pydantic_can_decode_list_of_models() -> None:
    assert PydanticDecoder().can_decode(list[User]) is True


def test_pydantic_can_decode_primitive_int() -> None:
    assert PydanticDecoder().can_decode(int) is True


def test_pydantic_can_decode_optional_int() -> None:
    assert PydanticDecoder().can_decode(int | None) is True  # ty: ignore[invalid-argument-type]


def test_pydantic_rejects_msgspec_struct() -> None:
    assert PydanticDecoder().can_decode(_Struct) is False


def test_pydantic_can_decode_uses_cache() -> None:
    decoder = PydanticDecoder()
    decoder.can_decode(User)
    decoder.can_decode(User)
    assert len(decoder._adapters) == 1  # noqa: SLF001
    assert User in decoder._adapters  # noqa: SLF001

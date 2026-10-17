"""The decoder adapter caches stay bounded when models are created per request."""

import concurrent.futures
import gc
import typing
import weakref

import msgspec
import pydantic
import pytest

from httpware.decoders import _caching
from httpware.decoders.msgspec import MsgspecDecoder
from httpware.decoders.pydantic import PydanticDecoder


_CAP = 8


@pytest.fixture(autouse=True)
def _small_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_caching, "_MAX_ENTRIES", _CAP)


def _decode_through_fresh_models(decoder: PydanticDecoder | MsgspecDecoder, models: typing.Iterator[type]) -> list:
    refs = []
    for model in models:
        decoder.decode(b'{"x": 1}', model)
        refs.append(weakref.ref(model))
    gc.collect()
    return refs


def test_pydantic_cache_is_bounded_and_releases_old_models() -> None:
    decoder = PydanticDecoder()
    models = (pydantic.create_model(f"M{i}", x=(int, ...)) for i in range(_CAP + 1))
    refs = _decode_through_fresh_models(decoder, models)
    assert len(decoder._adapters) <= _CAP  # noqa: SLF001
    assert refs[0]() is None


def test_msgspec_cache_is_bounded_and_drops_old_models() -> None:
    """Checks our cache only: older msgspec inspects through `typing.Tuple[...]`, whose LRU keeps recent models."""
    decoder = MsgspecDecoder()
    models = [msgspec.defstruct(f"S{i}", [("x", int)]) for i in range(_CAP + 1)]
    for model in models:
        decoder.decode(b'{"x": 1}', model)
    assert len(decoder._adapters) <= _CAP  # noqa: SLF001
    assert all(cached is not models[0] for cached, _ in decoder._adapters.values())  # noqa: SLF001


def test_repr_keyed_cache_is_bounded() -> None:
    decoder = PydanticDecoder()
    for i in range(_CAP + 1):
        decoder.decode(b"1", typing.Annotated[int, [i]])  # ty: ignore[invalid-argument-type]
    assert len(decoder._adapters) <= _CAP  # noqa: SLF001


def test_model_decodes_after_the_cache_is_cleared() -> None:
    decoder = PydanticDecoder()
    for i in range(_CAP + 1):
        decoder.decode(b'{"x": 1}', pydantic.create_model(f"M{i}", x=(int, ...)))
    model = pydantic.create_model("Late", x=(int, ...))
    assert decoder.decode(b'{"x": 2}', model).model_dump() == {"x": 2}
    assert decoder.can_decode(model)


@pytest.mark.stress
def test_clear_racing_with_lookups_returns_the_right_adapter() -> None:
    models = [type(f"T{i}", (), {}) for i in range(_CAP * 4)]
    cache: _caching._Cache[type] = {}

    def look_up_all(_: int) -> bool:
        return all(_caching._lookup(cache, model, lambda m: m) is model for _ in range(50) for model in models)  # noqa: SLF001

    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
        assert all(pool.map(look_up_all, range(32)))

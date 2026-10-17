"""One cache per decoder, keyed so that union member order counts (Seam C).

Imports neither pydantic nor msgspec, so both decoder modules can use it
without crossing Seam C's per-extra import isolation.
"""

import typing
from collections.abc import Callable, Hashable


V = typing.TypeVar("V")

_MAX_ENTRIES = 4096

_Cache: typing.TypeAlias = dict[Hashable, tuple[object, V | None]]


def _key(model: object) -> Hashable:
    """Return a key that tells `int | str` from `str | int`, which compare equal.

    A class keys by identity; anything else by itself plus the keys of its
    `__args__`, in order.
    """
    if isinstance(model, type):
        return model
    return (model, *map(_key, getattr(model, "__args__", ())))


def _lookup(cache: "_Cache[V]", model: object, build: Callable[[typing.Any], V | None]) -> V | None:
    """Return the cached `build(model)`, building it on a miss; None means `model` cannot be decoded.

    `build` must not raise. Concurrent first calls may build twice; the last write wins.
    A full cache is emptied before the next insert, so a model seen again after that is rebuilt.
    """
    try:
        key = _key(model)
        entry = cache.get(key)
    except Exception:  # noqa: BLE001 — unhashable models fall back to a repr key
        return _lookup_by_repr(cache, model, build)
    if entry is None:
        entry = _store(cache, key, model, build)
    return entry[1]


def _lookup_by_repr(cache: "_Cache[V]", model: object, build: Callable[[typing.Any], V | None]) -> V | None:
    """Key an unhashable `model` by its repr; the equality check keeps two models with one repr apart."""
    try:
        key = repr(model)
        entry = cache.get(key)
        if entry is not None and entry[0] == model:
            return entry[1]
    except Exception:  # noqa: BLE001 — a model that cannot be keyed is built uncached
        return build(model)
    return _store(cache, key, model, build)[1]


def _store(
    cache: "_Cache[V]", key: Hashable, model: object, build: Callable[[typing.Any], V | None]
) -> tuple[object, V | None]:
    """Build and cache the entry for `model`, emptying `cache` first once it holds `_MAX_ENTRIES`."""
    entry = (model, build(model))
    if len(cache) >= _MAX_ENTRIES:
        cache.clear()
    cache[key] = entry
    return entry

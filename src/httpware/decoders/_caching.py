"""Shared memoizing get-or-build cache for the decoder adapters (Seam C).

Imports neither pydantic nor msgspec — safe for both decoder modules to
import without crossing Seam C's per-extra import isolation.
"""

import typing


V = typing.TypeVar("V")


def _get_or_build(cache: dict[type, V], model: type, build: typing.Callable[[], V]) -> V:
    """Return cache[model], building and memoizing it via build() on miss.

    Unhashable models bypass the cache entirely: dict.get(model) raises
    TypeError, in which case this returns a fresh, uncached build() every
    call rather than raising. A real cached value (bool verdict or a
    built adapter/decoder) is never None, so a None result unambiguously
    means "not cached yet" — callers must not store None as a value.
    """
    try:
        cached = cache.get(model)
    except TypeError:
        return build()
    if cached is not None:
        return cached
    result = build()
    cache[model] = result
    return result

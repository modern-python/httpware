"""PydanticDecoder — ResponseDecoder backed by per-instance TypeAdapter cache.

Requires the `pydantic` extra: `pip install httpware[pydantic]`. Constructing
`PydanticDecoder()` directly when pydantic is not installed raises ImportError.
The default-decoder path in `client.py:_build_default_decoders()` skips this
class entirely when `is_pydantic_installed` is False, so `AsyncClient()` does
not trip the ImportError when the user is not using `response_model=`.
"""

import typing
from typing import TypeVar

from httpware._internal import import_checker
from httpware.decoders._caching import _get_or_build


if import_checker.is_pydantic_installed:
    from pydantic import TypeAdapter


MISSING_DEPENDENCY_MESSAGE = (
    "PydanticDecoder requires the 'pydantic' extra. Install with: pip install httpware[pydantic]"
)

T = TypeVar("T")


class PydanticDecoder:
    """Decode raw response bytes into `model` via a per-instance cached `pydantic.TypeAdapter`.

    Requires the `pydantic` extra: `pip install httpware[pydantic]`. Importing
    this module without the extra works (the `pydantic` import is guarded by an
    `is_pydantic_installed` check), but instantiating the decoder raises
    `ImportError`.
    """

    _adapters: dict[type, "TypeAdapter[typing.Any]"]
    _can_decode_results: dict[type, bool]

    def __init__(self) -> None:
        if not import_checker.is_pydantic_installed:
            raise ImportError(MISSING_DEPENDENCY_MESSAGE)
        self._adapters = {}
        self._can_decode_results = {}

    def _get_adapter(self, model: type[T]) -> "TypeAdapter[T]":
        return _get_or_build(self._adapters, model, lambda: TypeAdapter(model))

    def can_decode(self, model: type) -> bool:
        """Return True iff pydantic can build a schema for `model`.

        The verdict is memoized per `model` so a rejection (which costs a
        `PydanticSchemaGenerationError` round-trip) is not re-probed on every
        dispatch. Unhashable models skip the cache and probe fresh.
        """
        return _get_or_build(self._can_decode_results, model, lambda: self._probe_can_decode(model))

    def _probe_can_decode(self, model: type) -> bool:
        """Decide whether pydantic can build a schema for `model` (uncached).

        Probes via `_get_adapter`; subsequent calls (including `decode`) reuse
        the cached `TypeAdapter`. Rejects `msgspec.Struct` subclasses —
        pydantic raises `PydanticSchemaGenerationError` (a `TypeError`) when
        building a schema for them.
        """
        try:
            self._get_adapter(model)
        except Exception:  # noqa: BLE001 — can_decode is a probe; any failure means no
            return False
        return True

    def decode(self, content: bytes, model: type[T]) -> T:
        """Validate `content` as JSON against `model` in a single parse pass."""
        adapter = self._get_adapter(model)
        return adapter.validate_json(content)

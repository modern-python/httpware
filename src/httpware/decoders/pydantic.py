"""PydanticDecoder — ResponseDecoder backed by per-instance TypeAdapter cache.

Requires the `pydantic` extra: `pip install httpware[pydantic]`. Constructing
`PydanticDecoder()` directly when pydantic is not installed raises ImportError.
The default-decoder path in `client.py:_build_default_decoders()` skips this
class entirely when `is_pydantic_installed` is False, so `AsyncClient()` does
not trip the ImportError when the user is not using `response_model=`.
"""

import typing
from typing import TypeVar

from pydantic import TypeAdapter

from httpware._internal import import_checker


MISSING_DEPENDENCY_MESSAGE = (
    "PydanticDecoder requires the 'pydantic' extra. Install with: pip install httpware[pydantic]"
)

T = TypeVar("T")


class PydanticDecoder:
    """Decode raw response bytes into `model` via a per-instance cached `pydantic.TypeAdapter`."""

    _adapters: dict[type, TypeAdapter[typing.Any]]

    def __init__(self) -> None:
        if not import_checker.is_pydantic_installed:
            raise ImportError(MISSING_DEPENDENCY_MESSAGE)
        self._adapters = {}

    def _get_adapter(self, model: type[T]) -> "TypeAdapter[T]":
        adapter = self._adapters.get(model)
        if adapter is None:
            adapter = TypeAdapter(model)
            self._adapters[model] = adapter
        return adapter

    def can_decode(self, model: type) -> bool:
        """Return True iff pydantic can build a schema for `model`.

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
        try:
            adapter = self._get_adapter(model)
        except TypeError:
            adapter = TypeAdapter(model)
        return adapter.validate_json(content)

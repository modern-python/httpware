"""PydanticDecoder — module-level cached TypeAdapter adapter for ResponseDecoder.

Requires the `pydantic` extra: `pip install httpware[pydantic]`. The optional-extras
gate is enforced upstream — `client.py:_default_pydantic_decoder()` raises
ImportError when pydantic is absent, so this module is never imported in that
path. Tests simulating "pydantic not installed" patch
`import_checker.is_pydantic_installed=False` at runtime, after this module is
already loaded; `PydanticDecoder.__init__` then raises ImportError with the
install hint.
"""

import functools
from typing import TypeVar

from pydantic import TypeAdapter

from httpware._internal import import_checker


MISSING_DEPENDENCY_MESSAGE = (
    "PydanticDecoder requires the 'pydantic' extra. Install with: pip install httpware[pydantic]"
)

T = TypeVar("T")


@functools.lru_cache(maxsize=1024)
def _get_adapter(model: type[T]) -> "TypeAdapter[T]":
    return TypeAdapter(model)


class PydanticDecoder:
    """Decode raw response bytes into `model` via a cached `pydantic.TypeAdapter`."""

    def __init__(self) -> None:
        if not import_checker.is_pydantic_installed:
            raise ImportError(MISSING_DEPENDENCY_MESSAGE)

    def can_decode(self, model: type) -> bool:
        """Return True iff pydantic can build a schema for `model`.

        Cached via `_get_adapter`; subsequent calls (including `decode`) reuse
        the same `TypeAdapter` instance. Rejects `msgspec.Struct` subclasses —
        pydantic raises `PydanticSchemaGenerationError` (a `TypeError`) when
        building a schema for them.
        """
        try:
            _get_adapter(model)
        except Exception:  # noqa: BLE001 — can_decode is a probe; any failure means no
            return False
        return True

    def decode(self, content: bytes, model: type[T]) -> T:
        """Validate `content` as JSON against `model` in a single parse pass."""
        try:
            adapter = _get_adapter(model)
        except TypeError:
            adapter = TypeAdapter(model)
        return adapter.validate_json(content)

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
from httpware.decoders._caching import _Cache, _lookup


if import_checker.is_pydantic_installed:
    from pydantic import TypeAdapter


MISSING_DEPENDENCY_MESSAGE = (
    "PydanticDecoder requires the 'pydantic' extra. Install with: pip install httpware[pydantic]"
)

T = TypeVar("T")


def _build_adapter(model: object) -> "TypeAdapter[typing.Any] | None":
    """Return a `TypeAdapter` for `model`, or None when pydantic cannot build a schema for it."""
    try:
        return TypeAdapter(model)
    except Exception:  # noqa: BLE001 — can_decode is a probe; any failure means no
        return None


class PydanticDecoder:
    """Decode raw response bytes into `model` via a per-instance cached `pydantic.TypeAdapter`.

    Requires the `pydantic` extra: `pip install httpware[pydantic]`. Importing
    this module without the extra works (the `pydantic` import is guarded by an
    `is_pydantic_installed` check), but instantiating the decoder raises
    `ImportError`.
    """

    _adapters: "_Cache[TypeAdapter[typing.Any]]"

    def __init__(self) -> None:
        if not import_checker.is_pydantic_installed:
            raise ImportError(MISSING_DEPENDENCY_MESSAGE)
        self._adapters = {}

    def can_decode(self, model: type) -> bool:
        """Return True iff pydantic can build a schema for `model`.

        The adapter, or the rejection, is cached per `model`, so `decode` reuses
        what this built. `msgspec.Struct` subclasses are rejected: pydantic
        cannot build a schema for them.
        """
        return _lookup(self._adapters, model, _build_adapter) is not None

    def decode(self, content: bytes, model: type[T]) -> T:
        """Validate `content` as JSON against `model` in a single parse pass."""
        adapter = _lookup(self._adapters, model, _build_adapter)
        if adapter is None:
            adapter = TypeAdapter(model)  # raises pydantic's own schema error
        return adapter.validate_json(content)

"""PydanticDecoder — module-level cached TypeAdapter adapter for ResponseDecoder.

Requires the `pydantic` extra: `pip install httpware[pydantic]`. Importing this
module without the extra works (the `pydantic` import is guarded by a
`find_spec` check), but instantiating the decoder raises `ImportError` with the
install hint.
"""

import functools
from typing import TypeVar

from httpware._internal import import_checker


if import_checker.is_pydantic_installed:
    from pydantic import TypeAdapter


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

    def decode(self, content: bytes, model: type[T]) -> T:
        """Validate `content` as JSON against `model` in a single parse pass."""
        try:
            adapter = _get_adapter(model)
        except TypeError:
            adapter = TypeAdapter(model)
        return adapter.validate_json(content)

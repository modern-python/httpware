"""PydanticDecoder — module-level cached TypeAdapter adapter for ResponseDecoder."""

import functools
from typing import TypeVar

from pydantic import TypeAdapter


T = TypeVar("T")


@functools.lru_cache(maxsize=1024)
def _get_adapter(model: type[T]) -> TypeAdapter[T]:
    return TypeAdapter(model)


class PydanticDecoder:
    """Decode raw response bytes into `model` via a cached `pydantic.TypeAdapter`."""

    def decode(self, content: bytes, model: type[T]) -> T:
        """Validate `content` as JSON against `model` in a single parse pass."""
        try:
            adapter = _get_adapter(model)
        except TypeError:
            adapter = TypeAdapter(model)
        return adapter.validate_json(content)


__all__ = ["PydanticDecoder"]

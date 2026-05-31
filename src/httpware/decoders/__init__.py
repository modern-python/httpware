"""ResponseDecoder protocol — the AsyncClient ↔ ResponseDecoder seam (Seam 3)."""

from typing import Protocol, TypeVar, runtime_checkable


T = TypeVar("T")


@runtime_checkable
class ResponseDecoder(Protocol):
    """Structural protocol every response-body decoder satisfies."""

    def decode(self, content: bytes, model: type[T]) -> T:
        """Decode `content` (raw response bytes) into an instance of `model`."""
        ...


__all__ = ["ResponseDecoder"]

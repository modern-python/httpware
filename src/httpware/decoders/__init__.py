"""ResponseDecoder protocol — the Client/AsyncClient ↔ ResponseDecoder seam (Seam B)."""

from typing import Protocol, TypeVar, runtime_checkable


T = TypeVar("T")


@runtime_checkable
class ResponseDecoder(Protocol):
    """Structural protocol every response-body decoder satisfies."""

    def decode(self, content: bytes, model: type[T]) -> T:
        """Decode `content` (raw response bytes) into an instance of `model`.

        Any exception raised by `decode` is wrapped by `Client.send` /
        `AsyncClient.send` into `httpware.DecodeError`; implementers do not
        need to raise `DecodeError` directly.
        """
        ...


__all__ = ["ResponseDecoder"]

"""ResponseDecoder protocol — the Client/AsyncClient ↔ ResponseDecoder seam (Seam B)."""

from typing import Protocol, TypeVar, runtime_checkable


T = TypeVar("T")


@runtime_checkable
class ResponseDecoder(Protocol):
    """Structural protocol every response-body decoder satisfies."""

    def can_decode(self, model: type) -> bool:
        """Return True iff this decoder claims responsibility for `model`.

        The client walks its `_decoders` tuple in order and picks the first
        decoder whose `can_decode` returns True. Implementations should claim
        every model type they can actually handle — broad is correct, because
        list ordering encodes the caller's preference for shared shapes.
        Native types of another library (e.g. `PydanticDecoder` vs
        `msgspec.Struct`) MUST be rejected.

        `can_decode` MUST NOT raise. It runs at dispatch time — before the HTTP
        call and outside the `DecodeError` wrap that protects `decode` — so an
        exception here escapes the `ClientError` contract rather than being
        translated. A decoder that cannot determine support for `model` must
        return False (decline), not raise; the built-in decoders treat any
        probe failure as False.
        """
        ...

    def decode(self, content: bytes, model: type[T]) -> T:
        """Decode `content` (raw response bytes) into an instance of `model`.

        Any exception raised by `decode` is wrapped by `Client.send` /
        `AsyncClient.send` into `httpware.DecodeError`; implementers do not
        need to raise `DecodeError` directly.
        """
        ...


__all__ = ["ResponseDecoder"]

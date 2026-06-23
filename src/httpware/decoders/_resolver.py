"""The Seam B orchestrator: resolve a response_model to a claiming decoder, then decode.

`_DecoderResolver` walks the client's frozen `_decoders` tuple and returns the
first decoder whose `can_decode` claims the model, bound to that model as a
`_BoundDecoder`. Resolution (and the pre-flight `MissingDecoderError`) is a
separate step from decoding because the HTTP call happens between them: the
client calls `resolve` before `_dispatch` — so a missing decoder fails before
the request goes out — and `_BoundDecoder.decode` after the response arrives.

Both clients hold one `_DecoderResolver`; it is fully synchronous, so there is
no sync/async split. See architecture/decoders.md for the full Seam B contract.
"""

from typing import Generic, TypeVar

import httpx2

from httpware.decoders import ResponseDecoder
from httpware.errors import DecodeError, MissingDecoderError


T = TypeVar("T")


class _BoundDecoder(Generic[T]):
    """A `ResponseDecoder` sealed to the `model` it will decode into.

    Binding the decoder and model together at resolve time makes a
    decoder/model mismatch unrepresentable: the caller supplies only the
    response. Decode failures are wrapped as `DecodeError` (the Seam B
    contract — implementers never raise it directly).
    """

    def __init__(self, decoder: ResponseDecoder, model: type[T]) -> None:
        self._decoder = decoder
        self._model = model

    def decode(self, response: httpx2.Response) -> T:
        """Decode `response.content` into `model`, wrapping any failure as `DecodeError`."""
        try:
            return self._decoder.decode(response.content, self._model)
        except Exception as exc:
            raise DecodeError(response=response, model=self._model, original=exc) from exc


class _DecoderResolver:
    """Resolves a `response_model` to the first claiming decoder in a frozen list."""

    def __init__(self, decoders: tuple[ResponseDecoder, ...]) -> None:
        self._decoders = decoders

    def resolve(self, model: type[T]) -> _BoundDecoder[T]:
        """Return the first decoder claiming `model`, bound to it.

        Raises `MissingDecoderError` when no registered decoder claims `model`.
        Called before the HTTP call, so the failure is pre-flight.
        """
        for decoder in self._decoders:
            if decoder.can_decode(model):
                return _BoundDecoder(decoder, model)
        raise MissingDecoderError(
            model=model,
            registered_names=tuple(type(d).__name__ for d in self._decoders),
        )

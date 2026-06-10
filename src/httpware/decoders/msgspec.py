"""MsgspecDecoder — opt-in ResponseDecoder backed by a per-instance msgspec.json.Decoder cache."""

import typing
from typing import TypeVar

from httpware._internal import import_checker


if import_checker.is_msgspec_installed:
    import msgspec


MISSING_DEPENDENCY_MESSAGE = "MsgspecDecoder requires the 'msgspec' extra. Install with: pip install httpware[msgspec]"

T = TypeVar("T")


class MsgspecDecoder:
    """Decode raw response bytes via a per-instance cached `msgspec.json.Decoder(model)`.

    Requires the `msgspec` extra: `pip install httpware[msgspec]`. Importing
    this module without the extra works (the `msgspec` import is guarded by a
    `find_spec` check), but instantiating the decoder raises `ImportError`.
    """

    _msgspec_decoders: dict[type, "msgspec.json.Decoder[typing.Any]"]

    def __init__(self) -> None:
        if not import_checker.is_msgspec_installed:
            raise ImportError(MISSING_DEPENDENCY_MESSAGE)
        self._msgspec_decoders = {}

    def _get_msgspec_decoder(self, model: type[T]) -> "msgspec.json.Decoder[T]":
        decoder = self._msgspec_decoders.get(model)
        if decoder is None:
            decoder = msgspec.json.Decoder(model)
            self._msgspec_decoders[model] = decoder
        return decoder

    def can_decode(self, model: type) -> bool:
        """Return True iff msgspec natively understands `model`.

        msgspec builds a Decoder for almost any class via a generic CustomType
        fallback; the Decoder constructor itself does NOT raise on unsupported
        types (e.g. pydantic.BaseModel). We use msgspec.inspect.type_info
        to detect the fallback and reject CustomType results explicitly.
        """
        try:
            info = msgspec.inspect.type_info(model)
        except Exception:  # noqa: BLE001 — can_decode is a probe; any failure means no
            return False
        if isinstance(info, msgspec.inspect.CustomType):
            return False
        try:
            self._get_msgspec_decoder(model)
        except Exception:  # noqa: BLE001 — can_decode is a probe; any failure means no
            return False
        return True

    def decode(self, content: bytes, model: type[T]) -> T:
        """Validate `content` as JSON against `model` in a single parse pass."""
        try:
            decoder = self._get_msgspec_decoder(model)
        except TypeError:
            decoder = msgspec.json.Decoder(model)
        return decoder.decode(content)

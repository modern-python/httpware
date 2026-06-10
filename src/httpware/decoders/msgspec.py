"""MsgspecDecoder — opt-in ResponseDecoder backed by a cached msgspec.json.Decoder."""

import functools
from typing import TypeVar

from httpware._internal import import_checker


if import_checker.is_msgspec_installed:
    import msgspec


MISSING_DEPENDENCY_MESSAGE = "MsgspecDecoder requires the 'msgspec' extra. Install with: pip install httpware[msgspec]"

T = TypeVar("T")


@functools.lru_cache(maxsize=1024)
def _get_msgspec_decoder(model: type[T]) -> "msgspec.json.Decoder[T]":
    return msgspec.json.Decoder(model)


class MsgspecDecoder:
    """Decode raw response bytes via a cached `msgspec.json.Decoder(model)`.

    Requires the `msgspec` extra: `pip install httpware[msgspec]`. Importing
    this module without the extra works (the `msgspec` import is guarded by a
    `find_spec` check), but instantiating the decoder raises `ImportError`.
    """

    def __init__(self) -> None:
        if not import_checker.is_msgspec_installed:
            raise ImportError(MISSING_DEPENDENCY_MESSAGE)

    def can_decode(self, model: type) -> bool:
        """Return True iff msgspec natively understands `model`.

        Cached via `_get_msgspec_decoder`; subsequent calls reuse the same
        Decoder instance. Rejects `pydantic.BaseModel` subclasses — msgspec
        will *build* a Decoder for them (falling back to a generic
        `CustomType`) but cannot actually decode them without a `dec_hook`,
        so we use `msgspec.inspect.type_info` to detect the fallback and
        refuse to claim the model.
        """
        try:
            info = msgspec.inspect.type_info(model)
        except Exception:  # noqa: BLE001 — can_decode is a probe; any failure means no
            return False
        if isinstance(info, msgspec.inspect.CustomType):
            return False
        try:
            _get_msgspec_decoder(model)
        except Exception:  # noqa: BLE001 — can_decode is a probe; any failure means no
            return False
        return True

    def decode(self, content: bytes, model: type[T]) -> T:
        """Validate `content` as JSON against `model` in a single parse pass."""
        try:
            decoder = _get_msgspec_decoder(model)
        except TypeError:
            decoder = msgspec.json.Decoder(model)
        return decoder.decode(content)

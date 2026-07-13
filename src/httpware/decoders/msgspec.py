"""MsgspecDecoder — opt-in ResponseDecoder backed by a per-instance msgspec.json.Decoder cache."""

import typing
from typing import TypeVar

from httpware._internal import import_checker
from httpware.decoders._caching import _get_or_build


if import_checker.is_msgspec_installed:
    import msgspec


MISSING_DEPENDENCY_MESSAGE = "MsgspecDecoder requires the 'msgspec' extra. Install with: pip install httpware[msgspec]"

T = TypeVar("T")


def _contains_custom_type(info: "msgspec.inspect.Type") -> bool:
    """Return True if `info` is a CustomType or nests one in its parameters.

    Walks generic-container parameterization (list/dict/set/tuple/union element
    types) by visiting any attribute that is itself a `msgspec.inspect.Type` or a
    tuple of them. It deliberately does NOT descend into `StructType`/dataclass
    fields: those expose `fields` as `Field` objects (not `Type`), so the walk
    stops at the boundary of a type msgspec natively owns. That boundary is what
    makes the walk both correct (a Struct is a valid target) and safe against
    infinite recursion on self-referential struct definitions.
    """
    if not import_checker.is_msgspec_installed:
        raise ImportError(MISSING_DEPENDENCY_MESSAGE)
    if isinstance(info, msgspec.inspect.CustomType):
        return True
    for name in dir(info):
        if name.startswith("_"):
            continue
        value = getattr(info, name, None)
        if isinstance(value, msgspec.inspect.Type):
            if _contains_custom_type(value):
                return True
        elif (
            isinstance(value, tuple)
            and value
            and all(isinstance(item, msgspec.inspect.Type) for item in value)
            and any(_contains_custom_type(item) for item in value)
        ):
            return True
    return False


class MsgspecDecoder:
    """Decode raw response bytes via a per-instance cached `msgspec.json.Decoder(model)`.

    Requires the `msgspec` extra: `pip install httpware[msgspec]`. Importing
    this module without the extra works (the `msgspec` import is guarded by a
    `find_spec` check), but instantiating the decoder raises `ImportError`.
    """

    _msgspec_decoders: dict[type, "msgspec.json.Decoder[typing.Any]"]
    _can_decode_results: dict[type, bool]

    def __init__(self) -> None:
        if not import_checker.is_msgspec_installed:
            raise ImportError(MISSING_DEPENDENCY_MESSAGE)
        self._msgspec_decoders = {}
        self._can_decode_results = {}

    def _get_msgspec_decoder(self, model: type[T]) -> "msgspec.json.Decoder[T]":
        return _get_or_build(self._msgspec_decoders, model, lambda: msgspec.json.Decoder(model))

    def can_decode(self, model: type) -> bool:
        """Return True iff msgspec natively understands `model` end-to-end.

        The verdict is memoized per `model`: the probe below (an uncached
        `type_info` call plus a recursive tree walk) runs once per type, not on
        every dispatch. Unhashable models skip the cache and probe fresh.
        """
        return _get_or_build(self._can_decode_results, model, lambda: self._probe_can_decode(model))

    def _probe_can_decode(self, model: type) -> bool:
        """Decide whether msgspec natively decodes `model` (the uncached path).

        msgspec builds a Decoder for almost any class via a generic CustomType
        fallback; the Decoder constructor does NOT raise on unsupported types
        (e.g. pydantic.BaseModel, or a container parameterized by one). We walk
        msgspec.inspect.type_info and reject if a CustomType appears anywhere in
        the type tree, so MissingDecoderError fires before a request is sent.
        """
        try:
            info = msgspec.inspect.type_info(model)
        except Exception:  # noqa: BLE001 — can_decode is a probe; any failure means no
            return False
        if _contains_custom_type(info):
            return False
        try:
            self._get_msgspec_decoder(model)
        except Exception:  # noqa: BLE001 — can_decode is a probe; any failure means no
            return False
        return True

    def decode(self, content: bytes, model: type[T]) -> T:
        """Validate `content` as JSON against `model` in a single parse pass."""
        decoder = self._get_msgspec_decoder(model)
        return decoder.decode(content)

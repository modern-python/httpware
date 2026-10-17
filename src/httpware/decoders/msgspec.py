"""MsgspecDecoder — opt-in ResponseDecoder backed by a per-instance msgspec.json.Decoder cache."""

import typing
from collections.abc import Iterator
from typing import TypeVar

from httpware._internal import import_checker
from httpware.decoders._caching import _Cache, _lookup


if import_checker.is_msgspec_installed:
    import msgspec


MISSING_DEPENDENCY_MESSAGE = "MsgspecDecoder requires the 'msgspec' extra. Install with: pip install httpware[msgspec]"

T = TypeVar("T")


def _child_types(info: "msgspec.inspect.Type") -> Iterator["msgspec.inspect.Type"]:
    """Yield the types nested in `info`: container parameters and the field types of a Struct-like model."""
    for name in info.__struct_fields__:
        value = getattr(info, name)
        if isinstance(value, msgspec.inspect.Type):
            yield value
        elif isinstance(value, tuple):
            for item in value:
                if isinstance(item, msgspec.inspect.Type):
                    yield item
                elif isinstance(item, msgspec.inspect.Field):
                    yield item.type


def _is_native(info: "msgspec.inspect.Type") -> bool:
    """Return True iff no `CustomType` appears anywhere in the type graph rooted at `info`.

    The graph is cyclic for self-referential models, so each node is visited once.
    """
    seen: set[int] = set()
    stack = [info]
    while stack:
        node = stack.pop()
        if isinstance(node, msgspec.inspect.CustomType):
            return False
        if id(node) in seen:
            continue
        seen.add(id(node))
        stack.extend(_child_types(node))
    return True


def _build_adapter(model: object) -> "msgspec.json.Decoder[typing.Any] | None":
    """Return a `msgspec.json.Decoder` for `model`, or None when msgspec cannot decode it natively.

    msgspec builds a Decoder for almost any class through its `CustomType`
    fallback, so the type graph is checked for one first, field types included.
    """
    try:
        if not _is_native(msgspec.inspect.type_info(model)):
            return None
        return msgspec.json.Decoder(model)
    except Exception:  # noqa: BLE001 — can_decode is a probe; any failure means no
        return None


class MsgspecDecoder:
    """Decode raw response bytes via a per-instance cached `msgspec.json.Decoder(model)`.

    Requires the `msgspec` extra: `pip install httpware[msgspec]`. Importing
    this module without the extra works (the `msgspec` import is guarded by a
    `find_spec` check), but instantiating the decoder raises `ImportError`.
    """

    _adapters: "_Cache[msgspec.json.Decoder[typing.Any]]"

    def __init__(self) -> None:
        if not import_checker.is_msgspec_installed:
            raise ImportError(MISSING_DEPENDENCY_MESSAGE)
        self._adapters = {}

    def can_decode(self, model: type) -> bool:
        """Return True iff msgspec natively understands `model` end-to-end.

        Rejects a model if any type in it, including the field types of a
        Struct, dataclass, TypedDict or NamedTuple, would need a `dec_hook`.
        The adapter, or the rejection, is cached per `model`.
        """
        return _lookup(self._adapters, model, _build_adapter) is not None

    def decode(self, content: bytes, model: type[T]) -> T:
        """Validate `content` as JSON against `model` in a single parse pass."""
        adapter = _lookup(self._adapters, model, _build_adapter)
        if adapter is None:
            adapter = msgspec.json.Decoder(model)  # decoding then raises msgspec's own error
        return adapter.decode(content)

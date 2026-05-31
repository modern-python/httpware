"""MsgspecDecoder — opt-in ResponseDecoder backed by msgspec.json.decode."""

from typing import TypeVar

from httpware._internal import import_checker


if import_checker.is_msgspec_installed:
    import msgspec


MISSING_DEPENDENCY_MESSAGE = (
    "MsgspecDecoder requires the 'msgspec' extra. "
    "Install with: pip install httpware[msgspec]"
)

T = TypeVar("T")


class MsgspecDecoder:
    """Decode raw response bytes via `msgspec.json.decode(content, type=model)`.

    Requires the `msgspec` extra: `pip install httpware[msgspec]`. Importing
    this module without the extra works (the `msgspec` import is guarded by a
    `find_spec` check), but instantiating the decoder raises `ImportError` with
    the install hint.
    """

    def __init__(self) -> None:
        if not import_checker.is_msgspec_installed:
            raise ImportError(MISSING_DEPENDENCY_MESSAGE)

    def decode(self, content: bytes, model: type[T]) -> T:
        """Validate `content` as JSON against `model` in a single parse pass.

        Falls back to `model.model_validate_json` for Pydantic BaseModel types,
        since msgspec cannot natively decode into Pydantic models.
        """
        if hasattr(model, "model_validate_json"):
            return model.model_validate_json(content)  # ty: ignore[call-non-callable]
        return msgspec.json.decode(content, type=model)  # guarded by import_checker above

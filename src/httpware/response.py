"""Immutable response value type."""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


_CHARSET_PREFIX = "charset="


def _get_content_type(headers: Mapping[str, str]) -> str:
    for key, value in headers.items():
        if key.lower() == "content-type":
            return value
    return ""


def _parse_charset(content_type: str) -> str | None:
    for raw in content_type.split(";"):
        part = raw.strip()
        if part.lower().startswith(_CHARSET_PREFIX):
            return part[len(_CHARSET_PREFIX) :].strip().strip('"').strip("'")
    return None


@dataclass(frozen=True, slots=True)
class Response:
    """Immutable HTTP response value type.

    `elapsed` is wall-clock seconds from request send to response receipt.
    """

    status: int
    headers: Mapping[str, str]
    content: bytes
    url: str
    elapsed: float

    @property
    def text(self) -> str:
        """Decode `content` using the response's declared charset (default UTF-8)."""
        charset = _parse_charset(_get_content_type(self.headers)) or "utf-8"
        try:
            return self.content.decode(charset)
        except LookupError:
            return self.content.decode("utf-8")

    def json(self) -> Any:  # noqa: ANN401
        """Parse `content` as JSON."""
        return json.loads(self.content)

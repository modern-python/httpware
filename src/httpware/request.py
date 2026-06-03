"""Immutable request value type."""

import dataclasses
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Self


def _validate_header_or_cookie(name: str, value: str, *, kind: str) -> None:
    if not isinstance(name, str) or not isinstance(value, str):
        msg = f"{kind} name and value must be str"
        raise TypeError(msg)
    if not name or not value:
        msg = f"{kind} name and value must be non-empty"
        raise ValueError(msg)
    if any(c in name or c in value for c in ("\r", "\n")):
        msg = f"{kind} name and value must not contain CR or LF"
        raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class Request:
    """Immutable HTTP request value type."""

    method: str
    url: str
    headers: Mapping[str, str] = field(default_factory=dict)
    params: Mapping[str, str] = field(default_factory=dict)
    cookies: Mapping[str, str] = field(default_factory=dict)
    body: bytes | None = None
    extensions: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.url, str):
            msg = "url must be str"
            raise TypeError(msg)
        if not self.url:
            msg = "url must be non-empty"
            raise ValueError(msg)
        for field_name in ("headers", "params", "cookies", "extensions"):
            field_value = getattr(self, field_name)
            if not isinstance(field_value, Mapping):
                msg = f"{field_name} must be a Mapping (got {type(field_value).__name__})"
                raise TypeError(msg)
        for name, value in self.headers.items():
            _validate_header_or_cookie(name, value, kind="header")
        for name, value in self.cookies.items():
            _validate_header_or_cookie(name, value, kind="cookie")

    def with_header(self, name: str, value: str) -> Self:
        """Return a copy with the given header added or replaced."""
        return dataclasses.replace(self, headers={**self.headers, name: value})

    def with_url(self, url: str) -> Self:
        """Return a copy with the given URL."""
        return dataclasses.replace(self, url=url)

    def with_body(self, body: bytes | None) -> Self:
        """Return a copy with the given body."""
        return dataclasses.replace(self, body=body)

    def with_query(self, params: Mapping[str, str]) -> Self:
        """Return a copy with the given query params replacing the existing ones."""
        return dataclasses.replace(self, params=params)

    def with_headers(self, headers: Mapping[str, str]) -> Self:
        """Return a copy with the given headers merged in (incoming keys override existing)."""
        return dataclasses.replace(self, headers={**self.headers, **headers})

    def with_cookie(self, name: str, value: str) -> Self:
        """Return a copy with the given cookie added or replaced."""
        return dataclasses.replace(self, cookies={**self.cookies, name: value})

    def with_cookies(self, cookies: Mapping[str, str]) -> Self:
        """Return a copy with the given cookies merged in (incoming keys override existing)."""
        return dataclasses.replace(self, cookies={**self.cookies, **cookies})

    def with_extension(self, name: str, value: Any) -> Self:  # noqa: ANN401
        """Return a copy with the given extension entry added or replaced."""
        return dataclasses.replace(self, extensions={**self.extensions, name: value})

    def with_extensions(self, extensions: Mapping[str, Any]) -> Self:
        """Return a copy with the given extensions merged in (incoming keys override existing)."""
        return dataclasses.replace(self, extensions={**self.extensions, **extensions})

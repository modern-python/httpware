"""Immutable request value type."""

import dataclasses
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Self


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

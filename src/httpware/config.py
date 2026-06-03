"""Immutable configuration value types: Limits, Timeout, ClientConfig."""

from collections.abc import Mapping
from dataclasses import dataclass, field

from httpware.decoders import ResponseDecoder
from httpware.decoders.pydantic import PydanticDecoder
from httpware.middleware import Middleware


@dataclass(frozen=True, slots=True)
class Timeout:
    """Per-phase request timeout configuration (seconds)."""

    connect: float = 5.0
    read: float = 30.0
    write: float = 30.0
    pool: float = 5.0

    def __post_init__(self) -> None:
        for attr in ("connect", "read", "write", "pool"):
            value = getattr(self, attr)
            if value < 0:
                msg = f"Timeout.{attr} must be non-negative (got {value})"
                raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class Limits:
    """Connection-pool limits."""

    max_connections: int = 100
    max_keepalive_connections: int = 20
    keepalive_expiry: float = 5.0

    def __post_init__(self) -> None:
        if self.max_connections < 0:
            msg = f"max_connections must be non-negative (got {self.max_connections})"
            raise ValueError(msg)
        if self.max_keepalive_connections < 0:
            msg = f"max_keepalive_connections must be non-negative (got {self.max_keepalive_connections})"
            raise ValueError(msg)
        if self.keepalive_expiry < 0:
            msg = f"keepalive_expiry must be non-negative (got {self.keepalive_expiry})"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class ClientConfig:
    """Immutable client configuration bag."""

    base_url: str | None = None
    default_headers: Mapping[str, str] = field(default_factory=dict)
    default_query: Mapping[str, str] = field(default_factory=dict)
    timeout: Timeout = field(default_factory=Timeout)
    limits: Limits = field(default_factory=Limits)
    decoder: ResponseDecoder = field(default_factory=PydanticDecoder)
    middleware: tuple[Middleware, ...] = ()

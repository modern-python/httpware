"""AsyncClient — the v0.1.0 public surface of httpware."""

from collections.abc import Mapping, Sequence
from typing import Any

from httpware._internal.chain import compose
from httpware.config import ClientConfig, Limits, Timeout
from httpware.decoders import ResponseDecoder
from httpware.decoders.pydantic import PydanticDecoder
from httpware.middleware import Middleware, Next
from httpware.transports import Transport
from httpware.transports.httpx2 import Httpx2Transport


_UNSET: Any = object()


def _normalize_timeout(value: Timeout | float | None) -> Timeout:
    if value is None:
        return Timeout()
    if isinstance(value, Timeout):
        return value
    return Timeout(connect=value, read=value, write=value, pool=value)


class AsyncClient:
    """Async HTTP client with typed response decoding and middleware composition."""

    _config: ClientConfig
    _transport: Transport
    _dispatch: Next
    _owns_transport: bool

    def __init__(  # noqa: PLR0913
        self,
        *,
        base_url: str | None = None,
        default_headers: Mapping[str, str] | None = None,
        default_query: Mapping[str, str] | None = None,
        timeout: Timeout | float | None = None,
        limits: Limits | None = None,
        transport: Transport | None = None,
        decoder: ResponseDecoder | None = None,
        middleware: Sequence[Middleware] | None = None,
    ) -> None:
        normalized_timeout = _normalize_timeout(timeout)
        resolved_limits = limits or Limits()
        resolved_transport: Transport = transport or Httpx2Transport(
            limits=resolved_limits, timeout=normalized_timeout
        )
        resolved_decoder = decoder or PydanticDecoder()
        resolved_middleware = tuple(middleware) if middleware is not None else ()

        self._config = ClientConfig(
            base_url=base_url,
            default_headers=dict(default_headers or {}),
            default_query=dict(default_query or {}),
            timeout=normalized_timeout,
            limits=resolved_limits,
            decoder=resolved_decoder,
            middleware=resolved_middleware,
        )
        self._transport = resolved_transport
        self._dispatch = compose(resolved_middleware, resolved_transport)
        self._owns_transport = True

    @classmethod
    def from_url(cls, base_url: str, **kwargs: Any) -> "AsyncClient":  # noqa: ANN401
        """Construct an AsyncClient with a base URL prefix."""
        return cls(base_url=base_url, **kwargs)

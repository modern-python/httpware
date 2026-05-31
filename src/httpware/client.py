"""AsyncClient — the v0.1.0 public surface of httpware."""

import dataclasses
import json as _json
import typing
from collections.abc import Mapping, Sequence

from httpware._internal.auth import AuthValue, _normalize_auth
from httpware._internal.chain import compose
from httpware.config import ClientConfig, Limits, Timeout
from httpware.decoders import ResponseDecoder
from httpware.decoders.pydantic import PydanticDecoder
from httpware.middleware import Middleware, Next
from httpware.request import Request
from httpware.response import Response
from httpware.transports import Transport
from httpware.transports.httpx2 import Httpx2Transport


_UNSET: typing.Any = object()

T = typing.TypeVar("T")

# Recursive type alias for any JSON-serializable Python value. Used for the `json=` body parameter
# on HTTP methods so we avoid `Any` while still accepting arbitrary nested structures.
JsonValue: typing.TypeAlias = Mapping[str, "JsonValue"] | Sequence["JsonValue"] | str | int | float | bool | None


def _normalize_timeout(value: Timeout | float | None) -> Timeout:
    if value is None:
        return Timeout()
    if isinstance(value, Timeout):
        return value
    return Timeout(connect=value, read=value, write=value, pool=value)


def _build_body(
    json_value: JsonValue,
    content: bytes | None,
) -> tuple[bytes | None, str | None]:
    if json_value is not None and content is not None:
        msg = "pass either `json` or `content`, not both"
        raise TypeError(msg)
    if json_value is not None:
        return _json.dumps(json_value).encode("utf-8"), "application/json"
    return content, None


class AsyncClient:
    """Async HTTP client with typed response decoding and middleware composition."""

    _config: ClientConfig
    _transport: Transport
    _dispatch: Next
    _owns_transport: bool
    _user_middleware: tuple[Middleware, ...]
    _auth: AuthValue

    def __init__(
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
        auth: AuthValue = None,
    ) -> None:
        normalized_timeout = _normalize_timeout(timeout)
        resolved_limits = limits or Limits()
        resolved_transport: Transport = transport or Httpx2Transport(
            limits=resolved_limits, timeout=normalized_timeout
        )
        resolved_decoder = decoder or PydanticDecoder()
        resolved_user_middleware: tuple[Middleware, ...] = (
            tuple(middleware) if middleware is not None else ()
        )
        resolved_auth_middleware = _normalize_auth(auth)
        composed_middleware: tuple[Middleware, ...] = (
            resolved_user_middleware
            if resolved_auth_middleware is None
            else (*resolved_user_middleware, resolved_auth_middleware)
        )

        self._config = ClientConfig(
            base_url=base_url,
            default_headers=dict(default_headers or {}),
            default_query=dict(default_query or {}),
            timeout=normalized_timeout,
            limits=resolved_limits,
            decoder=resolved_decoder,
            middleware=composed_middleware,
        )
        self._transport = resolved_transport
        self._dispatch = compose(composed_middleware, resolved_transport)
        self._owns_transport = True
        self._user_middleware = resolved_user_middleware
        self._auth = auth

    @classmethod
    def from_url(cls, base_url: str, **kwargs: object) -> "AsyncClient":
        """Construct an AsyncClient with a base URL prefix."""
        return cls(base_url=base_url, **kwargs)  # ty: ignore[invalid-argument-type]

    async def __aenter__(self) -> typing.Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object,
    ) -> None:
        if self._owns_transport:
            await self._transport.aclose()

    def _resolve_url(self, path: str) -> str:
        if path.startswith(("http://", "https://")):
            return path
        base = self._config.base_url
        if base is None:
            return path
        return f"{base.rstrip('/')}/{path.lstrip('/')}"

    def _build_request(
        self,
        method: str,
        path: str,
        *,
        headers: Mapping[str, str] | None,
        params: Mapping[str, str] | None,
        cookies: Mapping[str, str] | None,
        timeout: Timeout | float | None,
        body: bytes | None,
        content_type: str | None,
    ) -> Request:
        merged_headers: dict[str, str] = {**self._config.default_headers, **(headers or {})}
        if content_type is not None and "content-type" not in {k.lower() for k in merged_headers}:
            merged_headers["content-type"] = content_type
        merged_params: dict[str, str] = {**self._config.default_query, **(params or {})}
        extensions: dict[str, typing.Any] = {}
        if timeout is not None:
            extensions["timeout"] = _normalize_timeout(timeout)
        return Request(
            method=method,
            url=self._resolve_url(path),
            headers=merged_headers,
            params=merged_params,
            cookies=dict(cookies or {}),
            body=body,
            extensions=extensions,
        )

    async def _send(
        self,
        method: str,
        path: str,
        *,
        headers: Mapping[str, str] | None,
        params: Mapping[str, str] | None,
        cookies: Mapping[str, str] | None,
        timeout: Timeout | float | None,
        body: bytes | None,
        content_type: str | None,
        response_model: type[T] | None,
    ) -> Response | T:
        request = self._build_request(
            method,
            path,
            headers=headers,
            params=params,
            cookies=cookies,
            timeout=timeout,
            body=body,
            content_type=content_type,
        )
        response = await self._dispatch(request)
        if response_model is None:
            return response
        return self._config.decoder.decode(response.content, response_model)

    @typing.overload
    async def get(
        self,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, str] | None = None,
        cookies: Mapping[str, str] | None = None,
        timeout: Timeout | float | None = None,
        response_model: None = None,
    ) -> Response: ...

    @typing.overload
    async def get(
        self,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, str] | None = None,
        cookies: Mapping[str, str] | None = None,
        timeout: Timeout | float | None = None,
        response_model: type[T],
    ) -> T: ...

    async def get(
        self,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, str] | None = None,
        cookies: Mapping[str, str] | None = None,
        timeout: Timeout | float | None = None,
        response_model: type[T] | None = None,
    ) -> Response | T:
        """Send a GET request."""
        return await self._send(
            "GET",
            path,
            headers=headers,
            params=params,
            cookies=cookies,
            timeout=timeout,
            body=None,
            content_type=None,
            response_model=response_model,
        )

    @typing.overload
    async def post(
        self,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, str] | None = None,
        cookies: Mapping[str, str] | None = None,
        timeout: Timeout | float | None = None,
        json: JsonValue = None,
        content: bytes | None = None,
        response_model: None = None,
    ) -> Response: ...

    @typing.overload
    async def post(
        self,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, str] | None = None,
        cookies: Mapping[str, str] | None = None,
        timeout: Timeout | float | None = None,
        json: JsonValue = None,
        content: bytes | None = None,
        response_model: type[T],
    ) -> T: ...

    async def post(
        self,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, str] | None = None,
        cookies: Mapping[str, str] | None = None,
        timeout: Timeout | float | None = None,
        json: JsonValue = None,
        content: bytes | None = None,
        response_model: type[T] | None = None,
    ) -> Response | T:
        """Send a POST request."""
        body, content_type = _build_body(json, content)
        return await self._send(
            "POST",
            path,
            headers=headers,
            params=params,
            cookies=cookies,
            timeout=timeout,
            body=body,
            content_type=content_type,
            response_model=response_model,
        )

    @typing.overload
    async def put(
        self,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, str] | None = None,
        cookies: Mapping[str, str] | None = None,
        timeout: Timeout | float | None = None,
        json: JsonValue = None,
        content: bytes | None = None,
        response_model: None = None,
    ) -> Response: ...

    @typing.overload
    async def put(
        self,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, str] | None = None,
        cookies: Mapping[str, str] | None = None,
        timeout: Timeout | float | None = None,
        json: JsonValue = None,
        content: bytes | None = None,
        response_model: type[T],
    ) -> T: ...

    async def put(
        self,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, str] | None = None,
        cookies: Mapping[str, str] | None = None,
        timeout: Timeout | float | None = None,
        json: JsonValue = None,
        content: bytes | None = None,
        response_model: type[T] | None = None,
    ) -> Response | T:
        """Send a PUT request."""
        body, content_type = _build_body(json, content)
        return await self._send(
            "PUT",
            path,
            headers=headers,
            params=params,
            cookies=cookies,
            timeout=timeout,
            body=body,
            content_type=content_type,
            response_model=response_model,
        )

    @typing.overload
    async def patch(
        self,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, str] | None = None,
        cookies: Mapping[str, str] | None = None,
        timeout: Timeout | float | None = None,
        json: JsonValue = None,
        content: bytes | None = None,
        response_model: None = None,
    ) -> Response: ...

    @typing.overload
    async def patch(
        self,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, str] | None = None,
        cookies: Mapping[str, str] | None = None,
        timeout: Timeout | float | None = None,
        json: JsonValue = None,
        content: bytes | None = None,
        response_model: type[T],
    ) -> T: ...

    async def patch(
        self,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, str] | None = None,
        cookies: Mapping[str, str] | None = None,
        timeout: Timeout | float | None = None,
        json: JsonValue = None,
        content: bytes | None = None,
        response_model: type[T] | None = None,
    ) -> Response | T:
        """Send a PATCH request."""
        body, content_type = _build_body(json, content)
        return await self._send(
            "PATCH",
            path,
            headers=headers,
            params=params,
            cookies=cookies,
            timeout=timeout,
            body=body,
            content_type=content_type,
            response_model=response_model,
        )

    @typing.overload
    async def delete(
        self,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, str] | None = None,
        cookies: Mapping[str, str] | None = None,
        timeout: Timeout | float | None = None,
        response_model: None = None,
    ) -> Response: ...

    @typing.overload
    async def delete(
        self,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, str] | None = None,
        cookies: Mapping[str, str] | None = None,
        timeout: Timeout | float | None = None,
        response_model: type[T],
    ) -> T: ...

    async def delete(
        self,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, str] | None = None,
        cookies: Mapping[str, str] | None = None,
        timeout: Timeout | float | None = None,
        response_model: type[T] | None = None,
    ) -> Response | T:
        """Send a DELETE request."""
        return await self._send(
            "DELETE",
            path,
            headers=headers,
            params=params,
            cookies=cookies,
            timeout=timeout,
            body=None,
            content_type=None,
            response_model=response_model,
        )

    @typing.overload
    async def head(
        self,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, str] | None = None,
        cookies: Mapping[str, str] | None = None,
        timeout: Timeout | float | None = None,
        response_model: None = None,
    ) -> Response: ...

    @typing.overload
    async def head(
        self,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, str] | None = None,
        cookies: Mapping[str, str] | None = None,
        timeout: Timeout | float | None = None,
        response_model: type[T],
    ) -> T: ...

    async def head(
        self,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, str] | None = None,
        cookies: Mapping[str, str] | None = None,
        timeout: Timeout | float | None = None,
        response_model: type[T] | None = None,
    ) -> Response | T:
        """Send a HEAD request."""
        return await self._send(
            "HEAD",
            path,
            headers=headers,
            params=params,
            cookies=cookies,
            timeout=timeout,
            body=None,
            content_type=None,
            response_model=response_model,
        )

    @typing.overload
    async def options(
        self,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, str] | None = None,
        cookies: Mapping[str, str] | None = None,
        timeout: Timeout | float | None = None,
        response_model: None = None,
    ) -> Response: ...

    @typing.overload
    async def options(
        self,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, str] | None = None,
        cookies: Mapping[str, str] | None = None,
        timeout: Timeout | float | None = None,
        response_model: type[T],
    ) -> T: ...

    async def options(
        self,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, str] | None = None,
        cookies: Mapping[str, str] | None = None,
        timeout: Timeout | float | None = None,
        response_model: type[T] | None = None,
    ) -> Response | T:
        """Send an OPTIONS request."""
        return await self._send(
            "OPTIONS",
            path,
            headers=headers,
            params=params,
            cookies=cookies,
            timeout=timeout,
            body=None,
            content_type=None,
            response_model=response_model,
        )

    @typing.overload
    async def request(
        self,
        method: str,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, str] | None = None,
        cookies: Mapping[str, str] | None = None,
        timeout: Timeout | float | None = None,
        json: JsonValue = None,
        content: bytes | None = None,
        response_model: None = None,
    ) -> Response: ...

    @typing.overload
    async def request(
        self,
        method: str,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, str] | None = None,
        cookies: Mapping[str, str] | None = None,
        timeout: Timeout | float | None = None,
        json: JsonValue = None,
        content: bytes | None = None,
        response_model: type[T],
    ) -> T: ...

    async def request(
        self,
        method: str,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, str] | None = None,
        cookies: Mapping[str, str] | None = None,
        timeout: Timeout | float | None = None,
        json: JsonValue = None,
        content: bytes | None = None,
        response_model: type[T] | None = None,
    ) -> Response | T:
        """Send a request with an arbitrary HTTP method."""
        body, content_type = _build_body(json, content)
        return await self._send(
            method,
            path,
            headers=headers,
            params=params,
            cookies=cookies,
            timeout=timeout,
            body=body,
            content_type=content_type,
            response_model=response_model,
        )

    def with_options(
        self,
        *,
        base_url: str | None = _UNSET,
        default_headers: Mapping[str, str] | None = _UNSET,
        default_query: Mapping[str, str] | None = _UNSET,
        timeout: Timeout | float | None = _UNSET,
        decoder: ResponseDecoder | None = _UNSET,
        middleware: Sequence[Middleware] | None = _UNSET,
    ) -> "AsyncClient":
        """Return a new AsyncClient sharing the same transport with overridden config.

        The returned client is a "view": it does NOT own the transport lifecycle.
        Closing it via `async with` is a no-op. The original client should be the
        one inside the outermost `async with` block.

        `limits` and `transport` are NOT overridable here — both bind to the
        transport, which is shared. Construct a fresh AsyncClient for those.
        """
        changes: dict[str, typing.Any] = {}
        if base_url is not _UNSET:
            changes["base_url"] = base_url
        if default_headers is not _UNSET:
            changes["default_headers"] = dict(default_headers or {})
        if default_query is not _UNSET:
            changes["default_query"] = dict(default_query or {})
        if timeout is not _UNSET:
            changes["timeout"] = _normalize_timeout(timeout)
        if decoder is not _UNSET:
            changes["decoder"] = decoder or PydanticDecoder()
        if middleware is not _UNSET:
            changes["middleware"] = tuple(middleware) if middleware is not None else ()

        new_config = dataclasses.replace(self._config, **changes)
        return AsyncClient._from_view(new_config, self._transport)

    @classmethod
    def _from_view(cls, config: ClientConfig, transport: Transport) -> "AsyncClient":
        """Construct a view sharing an existing transport. Bypasses __init__."""
        client = cls.__new__(cls)
        client._config = config  # noqa: SLF001
        client._transport = transport  # noqa: SLF001
        client._dispatch = compose(config.middleware, transport)  # noqa: SLF001
        client._owns_transport = False  # noqa: SLF001
        return client

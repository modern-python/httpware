"""Client + AsyncClient — thin httpx2 wrappers with typed decoding and middleware."""

import contextlib
import typing
from collections.abc import AsyncIterator, Iterator, Sequence
from http import HTTPStatus

import httpx2

from httpware._internal import import_checker
from httpware._internal.body_cap import _read_capped, _read_capped_async, _validate_max_response_body_bytes
from httpware._internal.exception_mapping import (
    _httpx2_exception_mapper,
    _httpx2_exception_mapper_sync,
)
from httpware._internal.status import (
    STREAMING_BODY_MARKER,
    _is_streaming_body_async,
    _is_streaming_body_sync,
    _raise_on_status_error,
)
from httpware.decoders import ResponseDecoder
from httpware.decoders._resolver import _DecoderResolver
from httpware.errors import TransportError
from httpware.middleware import AsyncMiddleware, AsyncNext, Middleware, Next
from httpware.middleware.chain import compose, compose_async


T = typing.TypeVar("T")


_FORWARDED_KWARG_NAMES = ("base_url", "headers", "params", "cookies", "timeout", "limits", "auth")
_HTTPX2_CLIENT_CONFLICT_MESSAGE = (
    "httpx2_client=... cannot be combined with any of "
    f"{_FORWARDED_KWARG_NAMES}; configure the httpx2 client you pass instead."
)


def _build_default_decoders() -> tuple[ResponseDecoder, ...]:
    """Construct the default decoder tuple based on installed extras.

    Pydantic-first when both extras are present; either-only when only one is
    installed; empty tuple when neither is installed. Imports the concrete
    decoder modules lazily so missing extras never trip `find_spec`-guarded
    import paths. Called by `AsyncClient.__init__` and `Client.__init__` when
    `decoders=None` (the default).
    """
    decoders: list[ResponseDecoder] = []
    if import_checker.is_pydantic_installed:
        from httpware.decoders.pydantic import PydanticDecoder  # noqa: PLC0415 — lazy by design (Seam C)

        decoders.append(PydanticDecoder())
    if import_checker.is_msgspec_installed:
        from httpware.decoders.msgspec import MsgspecDecoder  # noqa: PLC0415 — lazy by design (Seam C)

        decoders.append(MsgspecDecoder())
    return tuple(decoders)


def _validate_httpx2_client_conflict(  # noqa: PLR0913 — 7 forwarded kwargs from caller's constructor
    *,
    base_url: str,
    headers: dict[str, str] | None,
    params: dict[str, str] | None,
    cookies: dict[str, str] | None,
    timeout: httpx2.Timeout | float | None,
    limits: httpx2.Limits | None,
    auth: httpx2.Auth | None,
) -> None:
    """Raise TypeError if httpx2_client=... is combined with a forwarded kwarg."""
    forwarded = {
        "base_url": base_url,
        "headers": headers,
        "params": params,
        "cookies": cookies,
        "timeout": timeout,
        "limits": limits,
        "auth": auth,
    }
    if any(value not in (None, "") for value in forwarded.values()):
        raise TypeError(_HTTPX2_CLIENT_CONFLICT_MESSAGE)


def _assemble_httpx2_client_kwargs(  # noqa: PLR0913 — 7 forwarded kwargs from caller's constructor
    *,
    base_url: str,
    headers: dict[str, str] | None,
    params: dict[str, str] | None,
    cookies: dict[str, str] | None,
    timeout: httpx2.Timeout | float | None,
    limits: httpx2.Limits | None,
    auth: httpx2.Auth | None,
) -> dict[str, typing.Any]:
    """Build the kwargs dict for constructing the owned httpx2 client."""
    kwargs: dict[str, typing.Any] = {}
    if base_url:
        kwargs["base_url"] = base_url
    if headers is not None:
        kwargs["headers"] = headers
    if params is not None:
        kwargs["params"] = params
    if cookies is not None:
        kwargs["cookies"] = cookies
    if timeout is not None:
        kwargs["timeout"] = timeout
    if limits is not None:
        kwargs["limits"] = limits
    if auth is not None:
        kwargs["auth"] = auth
    return kwargs


def _assemble_request_kwargs(  # noqa: PLR0913 — 9 per-request kwargs from httpx2 call signatures
    *,
    params: typing.Any | None,
    headers: typing.Any | None,
    cookies: typing.Any | None,
    timeout: typing.Any,
    extensions: typing.Any | None,
    json: typing.Any | None,
    content: typing.Any | None,
    data: typing.Any | None,
    files: typing.Any | None,
) -> dict[str, typing.Any]:
    """Build the kwargs dict for a per-request httpx2 call (build_request/stream)."""
    kwargs: dict[str, typing.Any] = {}
    if params is not None:
        kwargs["params"] = params
    if headers is not None:
        kwargs["headers"] = headers
    if cookies is not None:
        kwargs["cookies"] = cookies
    if timeout is not httpx2.USE_CLIENT_DEFAULT:
        kwargs["timeout"] = timeout
    if extensions is not None:
        kwargs["extensions"] = extensions
    if json is not None:
        kwargs["json"] = json
    if content is not None:
        kwargs["content"] = content
    if data is not None:
        kwargs["data"] = data
    if files is not None:
        kwargs["files"] = files
    return kwargs


class AsyncClient:
    """Async HTTP client: thin wrapper around httpx2 with typed decoding and middleware."""

    _httpx2_client: httpx2.AsyncClient
    _owns_client: bool
    _decoders: tuple[ResponseDecoder, ...]
    _user_middleware: tuple[AsyncMiddleware, ...]
    _dispatch: AsyncNext
    _max_response_body_bytes: int | None

    def __init__(  # noqa: PLR0913 — wide constructor is the cost of a single-call API
        self,
        *,
        base_url: str = "",
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
        cookies: dict[str, str] | None = None,
        timeout: httpx2.Timeout | float | None = None,
        limits: httpx2.Limits | None = None,
        auth: httpx2.Auth | None = None,
        httpx2_client: httpx2.AsyncClient | None = None,
        decoders: Sequence[ResponseDecoder] | None = None,
        middleware: Sequence[AsyncMiddleware] = (),
        max_response_body_bytes: int | None = None,
    ) -> None:
        _validate_max_response_body_bytes(max_response_body_bytes)
        if httpx2_client is not None:
            _validate_httpx2_client_conflict(
                base_url=base_url,
                headers=headers,
                params=params,
                cookies=cookies,
                timeout=timeout,
                limits=limits,
                auth=auth,
            )
            self._httpx2_client = httpx2_client
            self._owns_client = False
        else:
            kwargs = _assemble_httpx2_client_kwargs(
                base_url=base_url,
                headers=headers,
                params=params,
                cookies=cookies,
                timeout=timeout,
                limits=limits,
                auth=auth,
            )
            self._httpx2_client = httpx2.AsyncClient(**kwargs)
            self._owns_client = True

        self._decoders = tuple(decoders) if decoders is not None else _build_default_decoders()
        self._decoder_resolver = _DecoderResolver(self._decoders)
        self._user_middleware = tuple(middleware)
        self._dispatch = compose_async(self._user_middleware, self._terminal)
        self._max_response_body_bytes = max_response_body_bytes

    async def _terminal(self, request: httpx2.Request) -> httpx2.Response:
        cap = self._max_response_body_bytes
        try:
            async with _httpx2_exception_mapper():
                if cap is None:
                    response = await self._httpx2_client.send(request)
                else:
                    streaming = await self._httpx2_client.send(request, stream=True)
                    try:
                        response = await _read_capped_async(streaming, cap, request)
                    finally:
                        await streaming.aclose()
        except RuntimeError as exc:
            if self._httpx2_client.is_closed:
                raise TransportError(str(exc)) from exc
            raise
        _raise_on_status_error(response)
        return response

    @typing.overload
    async def send(self, request: httpx2.Request, *, response_model: None = None) -> httpx2.Response: ...

    @typing.overload
    async def send(self, request: httpx2.Request, *, response_model: type[T]) -> T: ...

    async def send(
        self,
        request: httpx2.Request,
        *,
        response_model: type[T] | None = None,
    ) -> httpx2.Response | T:
        """Send `request` through the middleware chain. Decode if `response_model` is set."""
        if response_model is None:
            return await self._dispatch(request)

        bound = self._decoder_resolver.resolve(response_model)
        response = await self._dispatch(request)
        return bound.decode(response)

    async def send_with_response(
        self,
        request: httpx2.Request,
        *,
        response_model: type[T],
    ) -> tuple[httpx2.Response, T]:
        """Send `request` through the middleware chain; return (response, decoded).

        Use this when you need response metadata (headers, status, request URL)
        AND a typed body — most commonly for Link-header pagination. For the
        body-only case, prefer ``send(request, response_model=...)``.

        Not for streaming responses — decodes ``response.content``, which
        requires the body to be fully read. Use ``stream()`` for streaming.
        """
        bound = self._decoder_resolver.resolve(response_model)
        response = await self._dispatch(request)
        return response, bound.decode(response)

    def build_request(self, method: str, url: str, **kwargs: typing.Any) -> httpx2.Request:
        """Delegate request construction to the wrapped httpx2.AsyncClient."""
        return self._httpx2_client.build_request(method, url, **kwargs)

    def _prepare_request(  # noqa: PLR0913 — mirrors httpx2 per-method signatures; kwargs-forwarding complexity is structural
        self,
        method: str,
        url: str,
        *,
        params: typing.Any | None = None,
        headers: typing.Any | None = None,
        cookies: typing.Any | None = None,
        timeout: typing.Any = httpx2.USE_CLIENT_DEFAULT,
        extensions: typing.Any | None = None,
        json: typing.Any | None = None,
        content: typing.Any | None = None,
        data: typing.Any | None = None,
        files: typing.Any | None = None,
    ) -> httpx2.Request:
        kwargs = _assemble_request_kwargs(
            params=params,
            headers=headers,
            cookies=cookies,
            timeout=timeout,
            extensions=extensions,
            json=json,
            content=content,
            data=data,
            files=files,
        )
        request = self._httpx2_client.build_request(method, url, **kwargs)
        if _is_streaming_body_async(content) or _is_streaming_body_async(data) or _is_streaming_body_async(files):
            request.extensions[STREAMING_BODY_MARKER] = True
        return request

    async def _request_with_body(  # noqa: PLR0913 — mirrors httpx2 per-method signatures
        self,
        method: str,
        url: str,
        *,
        params: typing.Any | None = None,
        headers: typing.Any | None = None,
        cookies: typing.Any | None = None,
        timeout: typing.Any = httpx2.USE_CLIENT_DEFAULT,
        extensions: typing.Any | None = None,
        json: typing.Any | None = None,
        content: typing.Any | None = None,
        data: typing.Any | None = None,
        files: typing.Any | None = None,
        response_model: type[T] | None = None,
    ) -> httpx2.Response | T:
        request = self._prepare_request(
            method,
            url,
            params=params,
            headers=headers,
            cookies=cookies,
            timeout=timeout,
            extensions=extensions,
            json=json,
            content=content,
            data=data,
            files=files,
        )
        return await self.send(request, response_model=response_model)

    async def _request_with_body_with_response(  # noqa: PLR0913 — mirrors httpx2 per-method signatures
        self,
        method: str,
        url: str,
        *,
        params: typing.Any | None = None,
        headers: typing.Any | None = None,
        cookies: typing.Any | None = None,
        timeout: typing.Any = httpx2.USE_CLIENT_DEFAULT,
        extensions: typing.Any | None = None,
        json: typing.Any | None = None,
        content: typing.Any | None = None,
        data: typing.Any | None = None,
        files: typing.Any | None = None,
        response_model: type[T],
    ) -> tuple[httpx2.Response, T]:
        request = self._prepare_request(
            method,
            url,
            params=params,
            headers=headers,
            cookies=cookies,
            timeout=timeout,
            extensions=extensions,
            json=json,
            content=content,
            data=data,
            files=files,
        )
        return await self.send_with_response(request, response_model=response_model)

    @typing.overload
    async def get(
        self,
        url: str,
        *,
        params: typing.Any | None = None,
        headers: typing.Any | None = None,
        cookies: typing.Any | None = None,
        timeout: typing.Any = httpx2.USE_CLIENT_DEFAULT,
        extensions: typing.Any | None = None,
        response_model: None = None,
    ) -> httpx2.Response: ...

    @typing.overload
    async def get(
        self,
        url: str,
        *,
        params: typing.Any | None = None,
        headers: typing.Any | None = None,
        cookies: typing.Any | None = None,
        timeout: typing.Any = httpx2.USE_CLIENT_DEFAULT,
        extensions: typing.Any | None = None,
        response_model: type[T],
    ) -> T: ...

    async def get(  # noqa: PLR0913 — mirrors httpx2 per-method signatures
        self,
        url: str,
        *,
        params: typing.Any | None = None,
        headers: typing.Any | None = None,
        cookies: typing.Any | None = None,
        timeout: typing.Any = httpx2.USE_CLIENT_DEFAULT,
        extensions: typing.Any | None = None,
        response_model: type[T] | None = None,
    ) -> httpx2.Response | T:
        """Send a GET request."""
        return await self._request_with_body(
            "GET",
            url,
            params=params,
            headers=headers,
            cookies=cookies,
            timeout=timeout,
            extensions=extensions,
            response_model=response_model,
        )

    async def get_with_response(  # noqa: PLR0913 — mirrors httpx2 per-method signatures
        self,
        url: str,
        *,
        params: typing.Any | None = None,
        headers: typing.Any | None = None,
        cookies: typing.Any | None = None,
        timeout: typing.Any = httpx2.USE_CLIENT_DEFAULT,
        extensions: typing.Any | None = None,
        response_model: type[T],
    ) -> tuple[httpx2.Response, T]:
        """Send a GET request; return (response, decoded body)."""
        return await self._request_with_body_with_response(
            "GET",
            url,
            params=params,
            headers=headers,
            cookies=cookies,
            timeout=timeout,
            extensions=extensions,
            response_model=response_model,
        )

    @typing.overload
    async def post(
        self,
        url: str,
        *,
        params: typing.Any | None = None,
        headers: typing.Any | None = None,
        cookies: typing.Any | None = None,
        timeout: typing.Any = httpx2.USE_CLIENT_DEFAULT,
        extensions: typing.Any | None = None,
        json: typing.Any | None = None,
        content: typing.Any | None = None,
        data: typing.Any | None = None,
        files: typing.Any | None = None,
        response_model: None = None,
    ) -> httpx2.Response: ...

    @typing.overload
    async def post(
        self,
        url: str,
        *,
        params: typing.Any | None = None,
        headers: typing.Any | None = None,
        cookies: typing.Any | None = None,
        timeout: typing.Any = httpx2.USE_CLIENT_DEFAULT,
        extensions: typing.Any | None = None,
        json: typing.Any | None = None,
        content: typing.Any | None = None,
        data: typing.Any | None = None,
        files: typing.Any | None = None,
        response_model: type[T],
    ) -> T: ...

    async def post(  # noqa: PLR0913 — mirrors httpx2 per-method signatures
        self,
        url: str,
        *,
        params: typing.Any | None = None,
        headers: typing.Any | None = None,
        cookies: typing.Any | None = None,
        timeout: typing.Any = httpx2.USE_CLIENT_DEFAULT,
        extensions: typing.Any | None = None,
        json: typing.Any | None = None,
        content: typing.Any | None = None,
        data: typing.Any | None = None,
        files: typing.Any | None = None,
        response_model: type[T] | None = None,
    ) -> httpx2.Response | T:
        """Send a POST request."""
        return await self._request_with_body(
            "POST",
            url,
            params=params,
            headers=headers,
            cookies=cookies,
            timeout=timeout,
            extensions=extensions,
            json=json,
            content=content,
            data=data,
            files=files,
            response_model=response_model,
        )

    async def post_with_response(  # noqa: PLR0913 — mirrors httpx2 per-method signatures
        self,
        url: str,
        *,
        params: typing.Any | None = None,
        headers: typing.Any | None = None,
        cookies: typing.Any | None = None,
        timeout: typing.Any = httpx2.USE_CLIENT_DEFAULT,
        extensions: typing.Any | None = None,
        json: typing.Any | None = None,
        content: typing.Any | None = None,
        data: typing.Any | None = None,
        files: typing.Any | None = None,
        response_model: type[T],
    ) -> tuple[httpx2.Response, T]:
        """Send a POST request; return (response, decoded body)."""
        return await self._request_with_body_with_response(
            "POST",
            url,
            params=params,
            headers=headers,
            cookies=cookies,
            timeout=timeout,
            extensions=extensions,
            json=json,
            content=content,
            data=data,
            files=files,
            response_model=response_model,
        )

    @typing.overload
    async def put(
        self,
        url: str,
        *,
        params: typing.Any | None = None,
        headers: typing.Any | None = None,
        cookies: typing.Any | None = None,
        timeout: typing.Any = httpx2.USE_CLIENT_DEFAULT,
        extensions: typing.Any | None = None,
        json: typing.Any | None = None,
        content: typing.Any | None = None,
        data: typing.Any | None = None,
        files: typing.Any | None = None,
        response_model: None = None,
    ) -> httpx2.Response: ...

    @typing.overload
    async def put(
        self,
        url: str,
        *,
        params: typing.Any | None = None,
        headers: typing.Any | None = None,
        cookies: typing.Any | None = None,
        timeout: typing.Any = httpx2.USE_CLIENT_DEFAULT,
        extensions: typing.Any | None = None,
        json: typing.Any | None = None,
        content: typing.Any | None = None,
        data: typing.Any | None = None,
        files: typing.Any | None = None,
        response_model: type[T],
    ) -> T: ...

    async def put(  # noqa: PLR0913 — mirrors httpx2 per-method signatures
        self,
        url: str,
        *,
        params: typing.Any | None = None,
        headers: typing.Any | None = None,
        cookies: typing.Any | None = None,
        timeout: typing.Any = httpx2.USE_CLIENT_DEFAULT,
        extensions: typing.Any | None = None,
        json: typing.Any | None = None,
        content: typing.Any | None = None,
        data: typing.Any | None = None,
        files: typing.Any | None = None,
        response_model: type[T] | None = None,
    ) -> httpx2.Response | T:
        """Send a PUT request."""
        return await self._request_with_body(
            "PUT",
            url,
            params=params,
            headers=headers,
            cookies=cookies,
            timeout=timeout,
            extensions=extensions,
            json=json,
            content=content,
            data=data,
            files=files,
            response_model=response_model,
        )

    async def put_with_response(  # noqa: PLR0913 — mirrors httpx2 per-method signatures
        self,
        url: str,
        *,
        params: typing.Any | None = None,
        headers: typing.Any | None = None,
        cookies: typing.Any | None = None,
        timeout: typing.Any = httpx2.USE_CLIENT_DEFAULT,
        extensions: typing.Any | None = None,
        json: typing.Any | None = None,
        content: typing.Any | None = None,
        data: typing.Any | None = None,
        files: typing.Any | None = None,
        response_model: type[T],
    ) -> tuple[httpx2.Response, T]:
        """Send a PUT request; return (response, decoded body)."""
        return await self._request_with_body_with_response(
            "PUT",
            url,
            params=params,
            headers=headers,
            cookies=cookies,
            timeout=timeout,
            extensions=extensions,
            json=json,
            content=content,
            data=data,
            files=files,
            response_model=response_model,
        )

    @typing.overload
    async def patch(
        self,
        url: str,
        *,
        params: typing.Any | None = None,
        headers: typing.Any | None = None,
        cookies: typing.Any | None = None,
        timeout: typing.Any = httpx2.USE_CLIENT_DEFAULT,
        extensions: typing.Any | None = None,
        json: typing.Any | None = None,
        content: typing.Any | None = None,
        data: typing.Any | None = None,
        files: typing.Any | None = None,
        response_model: None = None,
    ) -> httpx2.Response: ...

    @typing.overload
    async def patch(
        self,
        url: str,
        *,
        params: typing.Any | None = None,
        headers: typing.Any | None = None,
        cookies: typing.Any | None = None,
        timeout: typing.Any = httpx2.USE_CLIENT_DEFAULT,
        extensions: typing.Any | None = None,
        json: typing.Any | None = None,
        content: typing.Any | None = None,
        data: typing.Any | None = None,
        files: typing.Any | None = None,
        response_model: type[T],
    ) -> T: ...

    async def patch(  # noqa: PLR0913 — mirrors httpx2 per-method signatures
        self,
        url: str,
        *,
        params: typing.Any | None = None,
        headers: typing.Any | None = None,
        cookies: typing.Any | None = None,
        timeout: typing.Any = httpx2.USE_CLIENT_DEFAULT,
        extensions: typing.Any | None = None,
        json: typing.Any | None = None,
        content: typing.Any | None = None,
        data: typing.Any | None = None,
        files: typing.Any | None = None,
        response_model: type[T] | None = None,
    ) -> httpx2.Response | T:
        """Send a PATCH request."""
        return await self._request_with_body(
            "PATCH",
            url,
            params=params,
            headers=headers,
            cookies=cookies,
            timeout=timeout,
            extensions=extensions,
            json=json,
            content=content,
            data=data,
            files=files,
            response_model=response_model,
        )

    async def patch_with_response(  # noqa: PLR0913 — mirrors httpx2 per-method signatures
        self,
        url: str,
        *,
        params: typing.Any | None = None,
        headers: typing.Any | None = None,
        cookies: typing.Any | None = None,
        timeout: typing.Any = httpx2.USE_CLIENT_DEFAULT,
        extensions: typing.Any | None = None,
        json: typing.Any | None = None,
        content: typing.Any | None = None,
        data: typing.Any | None = None,
        files: typing.Any | None = None,
        response_model: type[T],
    ) -> tuple[httpx2.Response, T]:
        """Send a PATCH request; return (response, decoded body)."""
        return await self._request_with_body_with_response(
            "PATCH",
            url,
            params=params,
            headers=headers,
            cookies=cookies,
            timeout=timeout,
            extensions=extensions,
            json=json,
            content=content,
            data=data,
            files=files,
            response_model=response_model,
        )

    @typing.overload
    async def delete(
        self,
        url: str,
        *,
        params: typing.Any | None = None,
        headers: typing.Any | None = None,
        cookies: typing.Any | None = None,
        timeout: typing.Any = httpx2.USE_CLIENT_DEFAULT,
        extensions: typing.Any | None = None,
        json: typing.Any | None = None,
        content: typing.Any | None = None,
        data: typing.Any | None = None,
        files: typing.Any | None = None,
        response_model: None = None,
    ) -> httpx2.Response: ...

    @typing.overload
    async def delete(
        self,
        url: str,
        *,
        params: typing.Any | None = None,
        headers: typing.Any | None = None,
        cookies: typing.Any | None = None,
        timeout: typing.Any = httpx2.USE_CLIENT_DEFAULT,
        extensions: typing.Any | None = None,
        json: typing.Any | None = None,
        content: typing.Any | None = None,
        data: typing.Any | None = None,
        files: typing.Any | None = None,
        response_model: type[T],
    ) -> T: ...

    async def delete(  # noqa: PLR0913 — mirrors httpx2 per-method signatures
        self,
        url: str,
        *,
        params: typing.Any | None = None,
        headers: typing.Any | None = None,
        cookies: typing.Any | None = None,
        timeout: typing.Any = httpx2.USE_CLIENT_DEFAULT,
        extensions: typing.Any | None = None,
        json: typing.Any | None = None,
        content: typing.Any | None = None,
        data: typing.Any | None = None,
        files: typing.Any | None = None,
        response_model: type[T] | None = None,
    ) -> httpx2.Response | T:
        """Send a DELETE request."""
        return await self._request_with_body(
            "DELETE",
            url,
            params=params,
            headers=headers,
            cookies=cookies,
            timeout=timeout,
            extensions=extensions,
            json=json,
            content=content,
            data=data,
            files=files,
            response_model=response_model,
        )

    async def delete_with_response(  # noqa: PLR0913 — mirrors httpx2 per-method signatures
        self,
        url: str,
        *,
        params: typing.Any | None = None,
        headers: typing.Any | None = None,
        cookies: typing.Any | None = None,
        timeout: typing.Any = httpx2.USE_CLIENT_DEFAULT,
        extensions: typing.Any | None = None,
        json: typing.Any | None = None,
        content: typing.Any | None = None,
        data: typing.Any | None = None,
        files: typing.Any | None = None,
        response_model: type[T],
    ) -> tuple[httpx2.Response, T]:
        """Send a DELETE request; return (response, decoded body)."""
        return await self._request_with_body_with_response(
            "DELETE",
            url,
            params=params,
            headers=headers,
            cookies=cookies,
            timeout=timeout,
            extensions=extensions,
            json=json,
            content=content,
            data=data,
            files=files,
            response_model=response_model,
        )

    @typing.overload
    async def head(
        self,
        url: str,
        *,
        params: typing.Any | None = None,
        headers: typing.Any | None = None,
        cookies: typing.Any | None = None,
        timeout: typing.Any = httpx2.USE_CLIENT_DEFAULT,
        extensions: typing.Any | None = None,
        response_model: None = None,
    ) -> httpx2.Response: ...

    @typing.overload
    async def head(
        self,
        url: str,
        *,
        params: typing.Any | None = None,
        headers: typing.Any | None = None,
        cookies: typing.Any | None = None,
        timeout: typing.Any = httpx2.USE_CLIENT_DEFAULT,
        extensions: typing.Any | None = None,
        response_model: type[T],
    ) -> T: ...

    async def head(  # noqa: PLR0913 — mirrors httpx2 per-method signatures
        self,
        url: str,
        *,
        params: typing.Any | None = None,
        headers: typing.Any | None = None,
        cookies: typing.Any | None = None,
        timeout: typing.Any = httpx2.USE_CLIENT_DEFAULT,
        extensions: typing.Any | None = None,
        response_model: type[T] | None = None,
    ) -> httpx2.Response | T:
        """Send a HEAD request."""
        return await self._request_with_body(
            "HEAD",
            url,
            params=params,
            headers=headers,
            cookies=cookies,
            timeout=timeout,
            extensions=extensions,
            response_model=response_model,
        )

    @typing.overload
    async def options(
        self,
        url: str,
        *,
        params: typing.Any | None = None,
        headers: typing.Any | None = None,
        cookies: typing.Any | None = None,
        timeout: typing.Any = httpx2.USE_CLIENT_DEFAULT,
        extensions: typing.Any | None = None,
        response_model: None = None,
    ) -> httpx2.Response: ...

    @typing.overload
    async def options(
        self,
        url: str,
        *,
        params: typing.Any | None = None,
        headers: typing.Any | None = None,
        cookies: typing.Any | None = None,
        timeout: typing.Any = httpx2.USE_CLIENT_DEFAULT,
        extensions: typing.Any | None = None,
        response_model: type[T],
    ) -> T: ...

    async def options(  # noqa: PLR0913 — mirrors httpx2 per-method signatures
        self,
        url: str,
        *,
        params: typing.Any | None = None,
        headers: typing.Any | None = None,
        cookies: typing.Any | None = None,
        timeout: typing.Any = httpx2.USE_CLIENT_DEFAULT,
        extensions: typing.Any | None = None,
        response_model: type[T] | None = None,
    ) -> httpx2.Response | T:
        """Send an OPTIONS request."""
        return await self._request_with_body(
            "OPTIONS",
            url,
            params=params,
            headers=headers,
            cookies=cookies,
            timeout=timeout,
            extensions=extensions,
            response_model=response_model,
        )

    @typing.overload
    async def request(
        self,
        method: str,
        url: str,
        *,
        params: typing.Any | None = None,
        headers: typing.Any | None = None,
        cookies: typing.Any | None = None,
        timeout: typing.Any = httpx2.USE_CLIENT_DEFAULT,
        extensions: typing.Any | None = None,
        json: typing.Any | None = None,
        content: typing.Any | None = None,
        data: typing.Any | None = None,
        files: typing.Any | None = None,
        response_model: None = None,
    ) -> httpx2.Response: ...

    @typing.overload
    async def request(
        self,
        method: str,
        url: str,
        *,
        params: typing.Any | None = None,
        headers: typing.Any | None = None,
        cookies: typing.Any | None = None,
        timeout: typing.Any = httpx2.USE_CLIENT_DEFAULT,
        extensions: typing.Any | None = None,
        json: typing.Any | None = None,
        content: typing.Any | None = None,
        data: typing.Any | None = None,
        files: typing.Any | None = None,
        response_model: type[T],
    ) -> T: ...

    async def request(  # noqa: PLR0913 — mirrors httpx2 per-method signatures
        self,
        method: str,
        url: str,
        *,
        params: typing.Any | None = None,
        headers: typing.Any | None = None,
        cookies: typing.Any | None = None,
        timeout: typing.Any = httpx2.USE_CLIENT_DEFAULT,
        extensions: typing.Any | None = None,
        json: typing.Any | None = None,
        content: typing.Any | None = None,
        data: typing.Any | None = None,
        files: typing.Any | None = None,
        response_model: type[T] | None = None,
    ) -> httpx2.Response | T:
        """Send a request with an arbitrary HTTP method."""
        return await self._request_with_body(
            method,
            url,
            params=params,
            headers=headers,
            cookies=cookies,
            timeout=timeout,
            extensions=extensions,
            json=json,
            content=content,
            data=data,
            files=files,
            response_model=response_model,
        )

    async def request_with_response(  # noqa: PLR0913 — mirrors httpx2 per-method signatures
        self,
        method: str,
        url: str,
        *,
        params: typing.Any | None = None,
        headers: typing.Any | None = None,
        cookies: typing.Any | None = None,
        timeout: typing.Any = httpx2.USE_CLIENT_DEFAULT,
        extensions: typing.Any | None = None,
        json: typing.Any | None = None,
        content: typing.Any | None = None,
        data: typing.Any | None = None,
        files: typing.Any | None = None,
        response_model: type[T],
    ) -> tuple[httpx2.Response, T]:
        """Send a request with an explicit method; return (response, decoded body)."""
        return await self._request_with_body_with_response(
            method,
            url,
            params=params,
            headers=headers,
            cookies=cookies,
            timeout=timeout,
            extensions=extensions,
            json=json,
            content=content,
            data=data,
            files=files,
            response_model=response_model,
        )

    @contextlib.asynccontextmanager
    async def stream(  # noqa: PLR0913 — mirrors httpx2 per-method signatures; kwargs-forwarding complexity is structural
        self,
        method: str,
        url: str,
        *,
        params: typing.Any | None = None,
        headers: typing.Any | None = None,
        cookies: typing.Any | None = None,
        timeout: typing.Any = httpx2.USE_CLIENT_DEFAULT,
        extensions: typing.Any | None = None,
        json: typing.Any | None = None,
        content: typing.Any | None = None,
        data: typing.Any | None = None,
        files: typing.Any | None = None,
    ) -> AsyncIterator[httpx2.Response]:
        """Stream an HTTP response. Bypasses the middleware chain.

        Yields an httpx2.Response; consume the body via response.aiter_bytes(),
        response.aiter_text(), response.aiter_lines(), or response.aiter_raw().
        The body is NOT pre-read for 2xx/3xx (streaming preserved); the response
        is closed when the context exits.

        Bypasses the middleware chain (no AsyncRetry, no AsyncBulkhead, no user-installed
        middleware) for v1 — see architecture/client.md for the contract.

        Auto-raises StatusError subclasses on 4xx/5xx (NotFoundError,
        ServiceUnavailableError, etc.) — consistent with client.get()/post()/etc.
        On error the response body is pre-read so exc.response.content is
        accessible. You lose the streaming property on errors; rare in practice.

        Maps httpx2 exceptions raised during the request OR body consumption to
        httpware exceptions via _httpx2_exception_mapper.
        """
        kwargs = _assemble_request_kwargs(
            params=params,
            headers=headers,
            cookies=cookies,
            timeout=timeout,
            extensions=extensions,
            json=json,
            content=content,
            data=data,
            files=files,
        )

        async with _httpx2_exception_mapper(), self._httpx2_client.stream(method, url, **kwargs) as response:
            if HTTPStatus.BAD_REQUEST <= response.status_code < 600:  # noqa: PLR2004 — 600 is the synthetic upper bound for 5xx
                cap = self._max_response_body_bytes
                if cap is None:
                    await response.aread()  # pre-read body so exc.response.content works
                    _raise_on_status_error(response)
                else:
                    # Bound the error pre-read; raises ResponseTooLargeError when over cap.
                    _raise_on_status_error(await _read_capped_async(response, cap, response.request))
            yield response

    async def __aenter__(self) -> typing.Self:
        """Enter the async context manager; return self."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object,
    ) -> None:
        """Exit the async context manager; close the underlying client only if owned."""
        if self._owns_client and not self._httpx2_client.is_closed:
            await self._httpx2_client.aclose()

    async def aclose(self) -> None:
        """Close the underlying httpx2 client if we own it.

        Idempotent — safe to call after ``__aexit__`` or another ``aclose()`` call.
        Use this when the client is not managed by ``async with`` (e.g., wired
        into a DI container's lifecycle).
        """
        if self._owns_client and not self._httpx2_client.is_closed:
            await self._httpx2_client.aclose()


class Client:
    """Sync HTTP client: thin wrapper around httpx2 with typed decoding and middleware."""

    _httpx2_client: httpx2.Client
    _owns_client: bool
    _decoders: tuple[ResponseDecoder, ...]
    _user_middleware: tuple[Middleware, ...]
    _dispatch: Next
    _max_response_body_bytes: int | None

    def __init__(  # noqa: PLR0913 — wide constructor is the cost of a single-call API
        self,
        *,
        base_url: str = "",
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
        cookies: dict[str, str] | None = None,
        timeout: httpx2.Timeout | float | None = None,
        limits: httpx2.Limits | None = None,
        auth: httpx2.Auth | None = None,
        httpx2_client: httpx2.Client | None = None,
        decoders: Sequence[ResponseDecoder] | None = None,
        middleware: Sequence[Middleware] = (),
        max_response_body_bytes: int | None = None,
    ) -> None:
        _validate_max_response_body_bytes(max_response_body_bytes)
        if httpx2_client is not None:
            _validate_httpx2_client_conflict(
                base_url=base_url,
                headers=headers,
                params=params,
                cookies=cookies,
                timeout=timeout,
                limits=limits,
                auth=auth,
            )
            self._httpx2_client = httpx2_client
            self._owns_client = False
        else:
            kwargs = _assemble_httpx2_client_kwargs(
                base_url=base_url,
                headers=headers,
                params=params,
                cookies=cookies,
                timeout=timeout,
                limits=limits,
                auth=auth,
            )
            self._httpx2_client = httpx2.Client(**kwargs)
            self._owns_client = True

        self._decoders = tuple(decoders) if decoders is not None else _build_default_decoders()
        self._decoder_resolver = _DecoderResolver(self._decoders)
        self._user_middleware = tuple(middleware)
        self._dispatch = compose(self._user_middleware, self._terminal)
        self._max_response_body_bytes = max_response_body_bytes

    def _terminal(self, request: httpx2.Request) -> httpx2.Response:
        cap = self._max_response_body_bytes
        try:
            with _httpx2_exception_mapper_sync():
                if cap is None:
                    response = self._httpx2_client.send(request)
                else:
                    streaming = self._httpx2_client.send(request, stream=True)
                    try:
                        response = _read_capped(streaming, cap, request)
                    finally:
                        streaming.close()
        except RuntimeError as exc:
            if self._httpx2_client.is_closed:
                raise TransportError(str(exc)) from exc
            raise
        _raise_on_status_error(response)
        return response

    def __enter__(self) -> typing.Self:
        """Enter the sync context manager; return self."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object,
    ) -> None:
        """Exit the sync context manager; close the underlying client only if owned."""
        if self._owns_client and not self._httpx2_client.is_closed:
            self._httpx2_client.close()

    def close(self) -> None:
        """Close the underlying httpx2 client if we own it.

        Idempotent — safe to call after ``__exit__`` or another ``close()`` call.
        Use this when the client is not managed by ``with`` (e.g., wired into a
        DI container's lifecycle). Mirrors AsyncClient.aclose().
        """
        if self._owns_client and not self._httpx2_client.is_closed:
            self._httpx2_client.close()

    @typing.overload
    def send(self, request: httpx2.Request, *, response_model: None = None) -> httpx2.Response: ...

    @typing.overload
    def send(self, request: httpx2.Request, *, response_model: type[T]) -> T: ...

    def send(
        self,
        request: httpx2.Request,
        *,
        response_model: type[T] | None = None,
    ) -> httpx2.Response | T:
        """Send `request` through the middleware chain. Decode if `response_model` is set."""
        if response_model is None:
            return self._dispatch(request)

        bound = self._decoder_resolver.resolve(response_model)
        response = self._dispatch(request)
        return bound.decode(response)

    def send_with_response(
        self,
        request: httpx2.Request,
        *,
        response_model: type[T],
    ) -> tuple[httpx2.Response, T]:
        """Send `request` through the middleware chain; return (response, decoded).

        Use this when you need response metadata (headers, status, request URL)
        AND a typed body — most commonly for Link-header pagination. For the
        body-only case, prefer ``send(request, response_model=...)``.

        Not for streaming responses — decodes ``response.content``, which
        requires the body to be fully read. Use ``stream()`` for streaming.
        """
        bound = self._decoder_resolver.resolve(response_model)
        response = self._dispatch(request)
        return response, bound.decode(response)

    def build_request(self, method: str, url: str, **kwargs: typing.Any) -> httpx2.Request:
        """Delegate request construction to the wrapped httpx2.Client."""
        return self._httpx2_client.build_request(method, url, **kwargs)

    def _prepare_request(  # noqa: PLR0913 — mirrors httpx2 per-method signatures; kwargs-forwarding complexity is structural
        self,
        method: str,
        url: str,
        *,
        params: typing.Any | None = None,
        headers: typing.Any | None = None,
        cookies: typing.Any | None = None,
        timeout: typing.Any = httpx2.USE_CLIENT_DEFAULT,
        extensions: typing.Any | None = None,
        json: typing.Any | None = None,
        content: typing.Any | None = None,
        data: typing.Any | None = None,
        files: typing.Any | None = None,
    ) -> httpx2.Request:
        kwargs = _assemble_request_kwargs(
            params=params,
            headers=headers,
            cookies=cookies,
            timeout=timeout,
            extensions=extensions,
            json=json,
            content=content,
            data=data,
            files=files,
        )
        request = self._httpx2_client.build_request(method, url, **kwargs)
        if _is_streaming_body_sync(content) or _is_streaming_body_sync(data) or _is_streaming_body_sync(files):
            request.extensions[STREAMING_BODY_MARKER] = True
        return request

    def _request_with_body(  # noqa: PLR0913 — mirrors httpx2 per-method signatures
        self,
        method: str,
        url: str,
        *,
        params: typing.Any | None = None,
        headers: typing.Any | None = None,
        cookies: typing.Any | None = None,
        timeout: typing.Any = httpx2.USE_CLIENT_DEFAULT,
        extensions: typing.Any | None = None,
        json: typing.Any | None = None,
        content: typing.Any | None = None,
        data: typing.Any | None = None,
        files: typing.Any | None = None,
        response_model: type[T] | None = None,
    ) -> httpx2.Response | T:
        request = self._prepare_request(
            method,
            url,
            params=params,
            headers=headers,
            cookies=cookies,
            timeout=timeout,
            extensions=extensions,
            json=json,
            content=content,
            data=data,
            files=files,
        )
        return self.send(request, response_model=response_model)

    def _request_with_body_with_response(  # noqa: PLR0913 — mirrors httpx2 per-method signatures
        self,
        method: str,
        url: str,
        *,
        params: typing.Any | None = None,
        headers: typing.Any | None = None,
        cookies: typing.Any | None = None,
        timeout: typing.Any = httpx2.USE_CLIENT_DEFAULT,
        extensions: typing.Any | None = None,
        json: typing.Any | None = None,
        content: typing.Any | None = None,
        data: typing.Any | None = None,
        files: typing.Any | None = None,
        response_model: type[T],
    ) -> tuple[httpx2.Response, T]:
        request = self._prepare_request(
            method,
            url,
            params=params,
            headers=headers,
            cookies=cookies,
            timeout=timeout,
            extensions=extensions,
            json=json,
            content=content,
            data=data,
            files=files,
        )
        return self.send_with_response(request, response_model=response_model)

    @typing.overload
    def get(
        self,
        url: str,
        *,
        params: typing.Any | None = None,
        headers: typing.Any | None = None,
        cookies: typing.Any | None = None,
        timeout: typing.Any = httpx2.USE_CLIENT_DEFAULT,
        extensions: typing.Any | None = None,
        response_model: None = None,
    ) -> httpx2.Response: ...

    @typing.overload
    def get(
        self,
        url: str,
        *,
        params: typing.Any | None = None,
        headers: typing.Any | None = None,
        cookies: typing.Any | None = None,
        timeout: typing.Any = httpx2.USE_CLIENT_DEFAULT,
        extensions: typing.Any | None = None,
        response_model: type[T],
    ) -> T: ...

    def get(  # noqa: PLR0913 — mirrors httpx2 per-method signatures
        self,
        url: str,
        *,
        params: typing.Any | None = None,
        headers: typing.Any | None = None,
        cookies: typing.Any | None = None,
        timeout: typing.Any = httpx2.USE_CLIENT_DEFAULT,
        extensions: typing.Any | None = None,
        response_model: type[T] | None = None,
    ) -> httpx2.Response | T:
        """Send a GET request."""
        return self._request_with_body(
            "GET",
            url,
            params=params,
            headers=headers,
            cookies=cookies,
            timeout=timeout,
            extensions=extensions,
            response_model=response_model,
        )

    def get_with_response(  # noqa: PLR0913 — mirrors httpx2 per-method signatures
        self,
        url: str,
        *,
        params: typing.Any | None = None,
        headers: typing.Any | None = None,
        cookies: typing.Any | None = None,
        timeout: typing.Any = httpx2.USE_CLIENT_DEFAULT,
        extensions: typing.Any | None = None,
        response_model: type[T],
    ) -> tuple[httpx2.Response, T]:
        """Send a GET request; return (response, decoded body)."""
        return self._request_with_body_with_response(
            "GET",
            url,
            params=params,
            headers=headers,
            cookies=cookies,
            timeout=timeout,
            extensions=extensions,
            response_model=response_model,
        )

    @typing.overload
    def post(
        self,
        url: str,
        *,
        params: typing.Any | None = None,
        headers: typing.Any | None = None,
        cookies: typing.Any | None = None,
        timeout: typing.Any = httpx2.USE_CLIENT_DEFAULT,
        extensions: typing.Any | None = None,
        json: typing.Any | None = None,
        content: typing.Any | None = None,
        data: typing.Any | None = None,
        files: typing.Any | None = None,
        response_model: None = None,
    ) -> httpx2.Response: ...

    @typing.overload
    def post(
        self,
        url: str,
        *,
        params: typing.Any | None = None,
        headers: typing.Any | None = None,
        cookies: typing.Any | None = None,
        timeout: typing.Any = httpx2.USE_CLIENT_DEFAULT,
        extensions: typing.Any | None = None,
        json: typing.Any | None = None,
        content: typing.Any | None = None,
        data: typing.Any | None = None,
        files: typing.Any | None = None,
        response_model: type[T],
    ) -> T: ...

    def post(  # noqa: PLR0913 — mirrors httpx2 per-method signatures
        self,
        url: str,
        *,
        params: typing.Any | None = None,
        headers: typing.Any | None = None,
        cookies: typing.Any | None = None,
        timeout: typing.Any = httpx2.USE_CLIENT_DEFAULT,
        extensions: typing.Any | None = None,
        json: typing.Any | None = None,
        content: typing.Any | None = None,
        data: typing.Any | None = None,
        files: typing.Any | None = None,
        response_model: type[T] | None = None,
    ) -> httpx2.Response | T:
        """Send a POST request."""
        return self._request_with_body(
            "POST",
            url,
            params=params,
            headers=headers,
            cookies=cookies,
            timeout=timeout,
            extensions=extensions,
            json=json,
            content=content,
            data=data,
            files=files,
            response_model=response_model,
        )

    def post_with_response(  # noqa: PLR0913 — mirrors httpx2 per-method signatures
        self,
        url: str,
        *,
        params: typing.Any | None = None,
        headers: typing.Any | None = None,
        cookies: typing.Any | None = None,
        timeout: typing.Any = httpx2.USE_CLIENT_DEFAULT,
        extensions: typing.Any | None = None,
        json: typing.Any | None = None,
        content: typing.Any | None = None,
        data: typing.Any | None = None,
        files: typing.Any | None = None,
        response_model: type[T],
    ) -> tuple[httpx2.Response, T]:
        """Send a POST request; return (response, decoded body)."""
        return self._request_with_body_with_response(
            "POST",
            url,
            params=params,
            headers=headers,
            cookies=cookies,
            timeout=timeout,
            extensions=extensions,
            json=json,
            content=content,
            data=data,
            files=files,
            response_model=response_model,
        )

    @typing.overload
    def put(
        self,
        url: str,
        *,
        params: typing.Any | None = None,
        headers: typing.Any | None = None,
        cookies: typing.Any | None = None,
        timeout: typing.Any = httpx2.USE_CLIENT_DEFAULT,
        extensions: typing.Any | None = None,
        json: typing.Any | None = None,
        content: typing.Any | None = None,
        data: typing.Any | None = None,
        files: typing.Any | None = None,
        response_model: None = None,
    ) -> httpx2.Response: ...

    @typing.overload
    def put(
        self,
        url: str,
        *,
        params: typing.Any | None = None,
        headers: typing.Any | None = None,
        cookies: typing.Any | None = None,
        timeout: typing.Any = httpx2.USE_CLIENT_DEFAULT,
        extensions: typing.Any | None = None,
        json: typing.Any | None = None,
        content: typing.Any | None = None,
        data: typing.Any | None = None,
        files: typing.Any | None = None,
        response_model: type[T],
    ) -> T: ...

    def put(  # noqa: PLR0913 — mirrors httpx2 per-method signatures
        self,
        url: str,
        *,
        params: typing.Any | None = None,
        headers: typing.Any | None = None,
        cookies: typing.Any | None = None,
        timeout: typing.Any = httpx2.USE_CLIENT_DEFAULT,
        extensions: typing.Any | None = None,
        json: typing.Any | None = None,
        content: typing.Any | None = None,
        data: typing.Any | None = None,
        files: typing.Any | None = None,
        response_model: type[T] | None = None,
    ) -> httpx2.Response | T:
        """Send a PUT request."""
        return self._request_with_body(
            "PUT",
            url,
            params=params,
            headers=headers,
            cookies=cookies,
            timeout=timeout,
            extensions=extensions,
            json=json,
            content=content,
            data=data,
            files=files,
            response_model=response_model,
        )

    def put_with_response(  # noqa: PLR0913 — mirrors httpx2 per-method signatures
        self,
        url: str,
        *,
        params: typing.Any | None = None,
        headers: typing.Any | None = None,
        cookies: typing.Any | None = None,
        timeout: typing.Any = httpx2.USE_CLIENT_DEFAULT,
        extensions: typing.Any | None = None,
        json: typing.Any | None = None,
        content: typing.Any | None = None,
        data: typing.Any | None = None,
        files: typing.Any | None = None,
        response_model: type[T],
    ) -> tuple[httpx2.Response, T]:
        """Send a PUT request; return (response, decoded body)."""
        return self._request_with_body_with_response(
            "PUT",
            url,
            params=params,
            headers=headers,
            cookies=cookies,
            timeout=timeout,
            extensions=extensions,
            json=json,
            content=content,
            data=data,
            files=files,
            response_model=response_model,
        )

    @typing.overload
    def patch(
        self,
        url: str,
        *,
        params: typing.Any | None = None,
        headers: typing.Any | None = None,
        cookies: typing.Any | None = None,
        timeout: typing.Any = httpx2.USE_CLIENT_DEFAULT,
        extensions: typing.Any | None = None,
        json: typing.Any | None = None,
        content: typing.Any | None = None,
        data: typing.Any | None = None,
        files: typing.Any | None = None,
        response_model: None = None,
    ) -> httpx2.Response: ...

    @typing.overload
    def patch(
        self,
        url: str,
        *,
        params: typing.Any | None = None,
        headers: typing.Any | None = None,
        cookies: typing.Any | None = None,
        timeout: typing.Any = httpx2.USE_CLIENT_DEFAULT,
        extensions: typing.Any | None = None,
        json: typing.Any | None = None,
        content: typing.Any | None = None,
        data: typing.Any | None = None,
        files: typing.Any | None = None,
        response_model: type[T],
    ) -> T: ...

    def patch(  # noqa: PLR0913 — mirrors httpx2 per-method signatures
        self,
        url: str,
        *,
        params: typing.Any | None = None,
        headers: typing.Any | None = None,
        cookies: typing.Any | None = None,
        timeout: typing.Any = httpx2.USE_CLIENT_DEFAULT,
        extensions: typing.Any | None = None,
        json: typing.Any | None = None,
        content: typing.Any | None = None,
        data: typing.Any | None = None,
        files: typing.Any | None = None,
        response_model: type[T] | None = None,
    ) -> httpx2.Response | T:
        """Send a PATCH request."""
        return self._request_with_body(
            "PATCH",
            url,
            params=params,
            headers=headers,
            cookies=cookies,
            timeout=timeout,
            extensions=extensions,
            json=json,
            content=content,
            data=data,
            files=files,
            response_model=response_model,
        )

    def patch_with_response(  # noqa: PLR0913 — mirrors httpx2 per-method signatures
        self,
        url: str,
        *,
        params: typing.Any | None = None,
        headers: typing.Any | None = None,
        cookies: typing.Any | None = None,
        timeout: typing.Any = httpx2.USE_CLIENT_DEFAULT,
        extensions: typing.Any | None = None,
        json: typing.Any | None = None,
        content: typing.Any | None = None,
        data: typing.Any | None = None,
        files: typing.Any | None = None,
        response_model: type[T],
    ) -> tuple[httpx2.Response, T]:
        """Send a PATCH request; return (response, decoded body)."""
        return self._request_with_body_with_response(
            "PATCH",
            url,
            params=params,
            headers=headers,
            cookies=cookies,
            timeout=timeout,
            extensions=extensions,
            json=json,
            content=content,
            data=data,
            files=files,
            response_model=response_model,
        )

    @typing.overload
    def delete(
        self,
        url: str,
        *,
        params: typing.Any | None = None,
        headers: typing.Any | None = None,
        cookies: typing.Any | None = None,
        timeout: typing.Any = httpx2.USE_CLIENT_DEFAULT,
        extensions: typing.Any | None = None,
        json: typing.Any | None = None,
        content: typing.Any | None = None,
        data: typing.Any | None = None,
        files: typing.Any | None = None,
        response_model: None = None,
    ) -> httpx2.Response: ...

    @typing.overload
    def delete(
        self,
        url: str,
        *,
        params: typing.Any | None = None,
        headers: typing.Any | None = None,
        cookies: typing.Any | None = None,
        timeout: typing.Any = httpx2.USE_CLIENT_DEFAULT,
        extensions: typing.Any | None = None,
        json: typing.Any | None = None,
        content: typing.Any | None = None,
        data: typing.Any | None = None,
        files: typing.Any | None = None,
        response_model: type[T],
    ) -> T: ...

    def delete(  # noqa: PLR0913 — mirrors httpx2 per-method signatures
        self,
        url: str,
        *,
        params: typing.Any | None = None,
        headers: typing.Any | None = None,
        cookies: typing.Any | None = None,
        timeout: typing.Any = httpx2.USE_CLIENT_DEFAULT,
        extensions: typing.Any | None = None,
        json: typing.Any | None = None,
        content: typing.Any | None = None,
        data: typing.Any | None = None,
        files: typing.Any | None = None,
        response_model: type[T] | None = None,
    ) -> httpx2.Response | T:
        """Send a DELETE request."""
        return self._request_with_body(
            "DELETE",
            url,
            params=params,
            headers=headers,
            cookies=cookies,
            timeout=timeout,
            extensions=extensions,
            json=json,
            content=content,
            data=data,
            files=files,
            response_model=response_model,
        )

    def delete_with_response(  # noqa: PLR0913 — mirrors httpx2 per-method signatures
        self,
        url: str,
        *,
        params: typing.Any | None = None,
        headers: typing.Any | None = None,
        cookies: typing.Any | None = None,
        timeout: typing.Any = httpx2.USE_CLIENT_DEFAULT,
        extensions: typing.Any | None = None,
        json: typing.Any | None = None,
        content: typing.Any | None = None,
        data: typing.Any | None = None,
        files: typing.Any | None = None,
        response_model: type[T],
    ) -> tuple[httpx2.Response, T]:
        """Send a DELETE request; return (response, decoded body)."""
        return self._request_with_body_with_response(
            "DELETE",
            url,
            params=params,
            headers=headers,
            cookies=cookies,
            timeout=timeout,
            extensions=extensions,
            json=json,
            content=content,
            data=data,
            files=files,
            response_model=response_model,
        )

    @typing.overload
    def head(
        self,
        url: str,
        *,
        params: typing.Any | None = None,
        headers: typing.Any | None = None,
        cookies: typing.Any | None = None,
        timeout: typing.Any = httpx2.USE_CLIENT_DEFAULT,
        extensions: typing.Any | None = None,
        response_model: None = None,
    ) -> httpx2.Response: ...

    @typing.overload
    def head(
        self,
        url: str,
        *,
        params: typing.Any | None = None,
        headers: typing.Any | None = None,
        cookies: typing.Any | None = None,
        timeout: typing.Any = httpx2.USE_CLIENT_DEFAULT,
        extensions: typing.Any | None = None,
        response_model: type[T],
    ) -> T: ...

    def head(  # noqa: PLR0913 — mirrors httpx2 per-method signatures
        self,
        url: str,
        *,
        params: typing.Any | None = None,
        headers: typing.Any | None = None,
        cookies: typing.Any | None = None,
        timeout: typing.Any = httpx2.USE_CLIENT_DEFAULT,
        extensions: typing.Any | None = None,
        response_model: type[T] | None = None,
    ) -> httpx2.Response | T:
        """Send a HEAD request."""
        return self._request_with_body(
            "HEAD",
            url,
            params=params,
            headers=headers,
            cookies=cookies,
            timeout=timeout,
            extensions=extensions,
            response_model=response_model,
        )

    @typing.overload
    def options(
        self,
        url: str,
        *,
        params: typing.Any | None = None,
        headers: typing.Any | None = None,
        cookies: typing.Any | None = None,
        timeout: typing.Any = httpx2.USE_CLIENT_DEFAULT,
        extensions: typing.Any | None = None,
        response_model: None = None,
    ) -> httpx2.Response: ...

    @typing.overload
    def options(
        self,
        url: str,
        *,
        params: typing.Any | None = None,
        headers: typing.Any | None = None,
        cookies: typing.Any | None = None,
        timeout: typing.Any = httpx2.USE_CLIENT_DEFAULT,
        extensions: typing.Any | None = None,
        response_model: type[T],
    ) -> T: ...

    def options(  # noqa: PLR0913 — mirrors httpx2 per-method signatures
        self,
        url: str,
        *,
        params: typing.Any | None = None,
        headers: typing.Any | None = None,
        cookies: typing.Any | None = None,
        timeout: typing.Any = httpx2.USE_CLIENT_DEFAULT,
        extensions: typing.Any | None = None,
        response_model: type[T] | None = None,
    ) -> httpx2.Response | T:
        """Send an OPTIONS request."""
        return self._request_with_body(
            "OPTIONS",
            url,
            params=params,
            headers=headers,
            cookies=cookies,
            timeout=timeout,
            extensions=extensions,
            response_model=response_model,
        )

    @typing.overload
    def request(
        self,
        method: str,
        url: str,
        *,
        params: typing.Any | None = None,
        headers: typing.Any | None = None,
        cookies: typing.Any | None = None,
        timeout: typing.Any = httpx2.USE_CLIENT_DEFAULT,
        extensions: typing.Any | None = None,
        json: typing.Any | None = None,
        content: typing.Any | None = None,
        data: typing.Any | None = None,
        files: typing.Any | None = None,
        response_model: None = None,
    ) -> httpx2.Response: ...

    @typing.overload
    def request(
        self,
        method: str,
        url: str,
        *,
        params: typing.Any | None = None,
        headers: typing.Any | None = None,
        cookies: typing.Any | None = None,
        timeout: typing.Any = httpx2.USE_CLIENT_DEFAULT,
        extensions: typing.Any | None = None,
        json: typing.Any | None = None,
        content: typing.Any | None = None,
        data: typing.Any | None = None,
        files: typing.Any | None = None,
        response_model: type[T],
    ) -> T: ...

    def request(  # noqa: PLR0913 — mirrors httpx2 per-method signatures
        self,
        method: str,
        url: str,
        *,
        params: typing.Any | None = None,
        headers: typing.Any | None = None,
        cookies: typing.Any | None = None,
        timeout: typing.Any = httpx2.USE_CLIENT_DEFAULT,
        extensions: typing.Any | None = None,
        json: typing.Any | None = None,
        content: typing.Any | None = None,
        data: typing.Any | None = None,
        files: typing.Any | None = None,
        response_model: type[T] | None = None,
    ) -> httpx2.Response | T:
        """Send a request with an arbitrary HTTP method."""
        return self._request_with_body(
            method,
            url,
            params=params,
            headers=headers,
            cookies=cookies,
            timeout=timeout,
            extensions=extensions,
            json=json,
            content=content,
            data=data,
            files=files,
            response_model=response_model,
        )

    def request_with_response(  # noqa: PLR0913 — mirrors httpx2 per-method signatures
        self,
        method: str,
        url: str,
        *,
        params: typing.Any | None = None,
        headers: typing.Any | None = None,
        cookies: typing.Any | None = None,
        timeout: typing.Any = httpx2.USE_CLIENT_DEFAULT,
        extensions: typing.Any | None = None,
        json: typing.Any | None = None,
        content: typing.Any | None = None,
        data: typing.Any | None = None,
        files: typing.Any | None = None,
        response_model: type[T],
    ) -> tuple[httpx2.Response, T]:
        """Send a request with an explicit method; return (response, decoded body)."""
        return self._request_with_body_with_response(
            method,
            url,
            params=params,
            headers=headers,
            cookies=cookies,
            timeout=timeout,
            extensions=extensions,
            json=json,
            content=content,
            data=data,
            files=files,
            response_model=response_model,
        )

    @contextlib.contextmanager
    def stream(  # noqa: PLR0913 — mirrors httpx2 per-method signatures; kwargs-forwarding complexity is structural
        self,
        method: str,
        url: str,
        *,
        params: typing.Any | None = None,
        headers: typing.Any | None = None,
        cookies: typing.Any | None = None,
        timeout: typing.Any = httpx2.USE_CLIENT_DEFAULT,
        extensions: typing.Any | None = None,
        json: typing.Any | None = None,
        content: typing.Any | None = None,
        data: typing.Any | None = None,
        files: typing.Any | None = None,
    ) -> Iterator[httpx2.Response]:
        """Stream an HTTP response. Bypasses the middleware chain.

        Yields an httpx2.Response; consume the body via response.iter_bytes(),
        response.iter_text(), response.iter_lines(), or response.iter_raw().
        The body is NOT pre-read for 2xx/3xx (streaming preserved); the response
        is closed when the context exits.

        Bypasses the middleware chain (no Retry, no Bulkhead, no user-installed
        middleware) — matches AsyncClient.stream() behavior.

        Auto-raises StatusError subclasses on 4xx/5xx. On error the response
        body is pre-read so exc.response.content is accessible.

        Maps httpx2 exceptions raised during the request OR body consumption to
        httpware exceptions via _httpx2_exception_mapper_sync.
        """
        kwargs = _assemble_request_kwargs(
            params=params,
            headers=headers,
            cookies=cookies,
            timeout=timeout,
            extensions=extensions,
            json=json,
            content=content,
            data=data,
            files=files,
        )

        with _httpx2_exception_mapper_sync(), self._httpx2_client.stream(method, url, **kwargs) as response:
            if HTTPStatus.BAD_REQUEST <= response.status_code < 600:  # noqa: PLR2004 — 600 is the synthetic upper bound for 5xx
                cap = self._max_response_body_bytes
                if cap is None:
                    response.read()  # pre-read body so exc.response.content works
                    _raise_on_status_error(response)
                else:
                    # Bound the error pre-read; raises ResponseTooLargeError when over cap.
                    _raise_on_status_error(_read_capped(response, cap, response.request))
            yield response

"""AsyncClient — the thin httpx2 wrapper."""

import contextlib
import typing
from collections.abc import AsyncIterator, Sequence
from http import HTTPStatus

import httpx2

from httpware._internal import import_checker
from httpware.decoders import ResponseDecoder
from httpware.errors import (
    STATUS_TO_EXCEPTION,
    ClientStatusError,
    NetworkError,
    ServerStatusError,
    TimeoutError,  # noqa: A004
    TransportError,
)
from httpware.middleware import Middleware, Next
from httpware.middleware.chain import compose


T = typing.TypeVar("T")


_FORWARDED_KWARG_NAMES = ("base_url", "headers", "params", "cookies", "timeout", "limits", "auth")
_HTTPX2_CLIENT_CONFLICT_MESSAGE = (
    "AsyncClient(httpx2_client=...) cannot be combined with any of "
    f"{_FORWARDED_KWARG_NAMES}; configure the httpx2.AsyncClient you pass instead."
)

_DEFAULT_DECODER_MISSING_MESSAGE = (
    "AsyncClient(decoder=None) defaults to PydanticDecoder, which requires the "
    "'pydantic' extra. Either install it (`pip install httpware[pydantic]`) or "
    "pass an explicit decoder=..."
)


def _default_pydantic_decoder() -> ResponseDecoder:
    if not import_checker.is_pydantic_installed:
        raise ImportError(_DEFAULT_DECODER_MISSING_MESSAGE)
    from httpware.decoders.pydantic import PydanticDecoder  # noqa: PLC0415 — lazy by design

    return PydanticDecoder()


@contextlib.asynccontextmanager
async def _httpx2_exception_mapper() -> AsyncIterator[None]:
    """Map httpx2 exceptions to httpware exceptions. Shared by AsyncClient._terminal and stream()."""
    try:
        yield
    except httpx2.TimeoutException as exc:
        raise TimeoutError(str(exc)) from exc
    except (httpx2.InvalidURL, httpx2.CookieConflict) as exc:
        raise TransportError(str(exc)) from exc
    except httpx2.NetworkError as exc:
        raise NetworkError(str(exc)) from exc
    except httpx2.HTTPError as exc:
        raise TransportError(str(exc)) from exc


def _raise_on_status_error(response: httpx2.Response) -> None:
    """Raise the appropriate StatusError subclass for a 4xx/5xx response. No-op for 2xx/3xx."""
    status = response.status_code
    if HTTPStatus.BAD_REQUEST <= status < 600:  # noqa: PLR2004 — 600 is the synthetic upper bound for 5xx
        exc_class = STATUS_TO_EXCEPTION.get(
            status,
            ClientStatusError if status < HTTPStatus.INTERNAL_SERVER_ERROR else ServerStatusError,
        )
        raise exc_class(response)


STREAMING_BODY_MARKER = "httpware.streaming_body"
"""Key set on ``httpx2.Request.extensions`` by ``_request_with_body`` when content/data/files is an async-iterable.

``Retry.__call__`` reads this marker to refuse retrying a streamed-body request
(the consumed iterator cannot replay across attempts)."""


def _is_streaming_body(value: typing.Any) -> bool:
    """Return True if value is an async-iterable that cannot be safely replayed for retry."""
    if value is None:
        return False
    if isinstance(value, (bytes, bytearray, memoryview, str, dict)):
        return False
    return hasattr(value, "__aiter__")


class AsyncClient:
    """Async HTTP client: thin wrapper around httpx2 with typed decoding and middleware."""

    _httpx2_client: httpx2.AsyncClient
    _owns_client: bool
    _decoder: ResponseDecoder
    _user_middleware: tuple[Middleware, ...]
    _dispatch: Next

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
        decoder: ResponseDecoder | None = None,
        middleware: Sequence[Middleware] = (),
    ) -> None:
        if httpx2_client is not None:
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
            self._httpx2_client = httpx2_client
            self._owns_client = False
        else:
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
            self._httpx2_client = httpx2.AsyncClient(**kwargs)
            self._owns_client = True

        self._decoder = decoder if decoder is not None else _default_pydantic_decoder()
        self._user_middleware = tuple(middleware)
        self._dispatch = compose(self._user_middleware, self._terminal)

    async def _terminal(self, request: httpx2.Request) -> httpx2.Response:
        try:
            async with _httpx2_exception_mapper():
                response = await self._httpx2_client.send(request)
        except RuntimeError as exc:
            if "closed" in str(exc):
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
        response = await self._dispatch(request)
        if response_model is None:
            return response
        return self._decoder.decode(response.content, response_model)

    def build_request(self, method: str, url: str, **kwargs: typing.Any) -> httpx2.Request:
        """Delegate request construction to the wrapped httpx2.AsyncClient."""
        return self._httpx2_client.build_request(method, url, **kwargs)

    async def _request_with_body(  # noqa: PLR0913, C901 — mirrors httpx2 per-method signatures; kwargs-forwarding complexity is structural
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
        request = self._httpx2_client.build_request(method, url, **kwargs)
        if _is_streaming_body(content) or _is_streaming_body(data) or _is_streaming_body(files):
            request.extensions[STREAMING_BODY_MARKER] = True
        return await self.send(request, response_model=response_model)

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

    @contextlib.asynccontextmanager
    async def stream(  # noqa: PLR0913, C901 — mirrors httpx2 per-method signatures; kwargs-forwarding complexity is structural
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

        Bypasses the middleware chain (no Retry, no Bulkhead, no user-installed
        middleware) for v1 — see planning/specs/2026-06-05-streaming-design.md.

        Auto-raises StatusError subclasses on 4xx/5xx (NotFoundError,
        ServiceUnavailableError, etc.) — consistent with client.get()/post()/etc.
        On error the response body is pre-read so exc.response.content is
        accessible. You lose the streaming property on errors; rare in practice.

        Maps httpx2 exceptions raised during the request OR body consumption to
        httpware exceptions via _httpx2_exception_mapper.
        """
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

        async with _httpx2_exception_mapper(), self._httpx2_client.stream(method, url, **kwargs) as response:
            if HTTPStatus.BAD_REQUEST <= response.status_code < 600:  # noqa: PLR2004 — 600 is the synthetic upper bound for 5xx
                await response.aread()  # pre-read body so exc.response.content works
                _raise_on_status_error(response)
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

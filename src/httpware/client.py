"""Client + AsyncClient — thin httpx2 wrappers with typed decoding and middleware."""

import contextlib
import ssl
import typing
from collections.abc import AsyncIterator, Callable, Iterator, Mapping, Sequence
from http import HTTPStatus

import httpx2
import typing_extensions

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


_HTTPX2_CLIENT_CONFLICT_MESSAGE = (
    "httpx2_client=... cannot be combined with httpx2 client options {names}; "
    "configure the httpx2 client you pass instead."
)
_UNSUPPORTED_OPTION_HINTS = {
    "cert": "cert=... is deprecated by httpx2; pass verify=<ssl.SSLContext> configured with .load_cert_chain().",
    "event_hooks": "event_hooks=... is not supported; use middleware=... instead.",
}
_TOO_MANY_REDIRECTS_MESSAGE = "Exceeded maximum allowed redirects."
_NO_AUTH = httpx2.Auth()
_BASE_URL_QUERY_MESSAGE = (
    "base_url must not contain a query string: httpx2 appends request paths after it, "
    "producing malformed URLs. Pass the query as params=... instead."
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


def _reject_base_url_query(base_url: httpx2.URL | str) -> None:
    """Raise ValueError if base_url carries a query string."""
    if httpx2.URL(base_url).query:
        raise ValueError(_BASE_URL_QUERY_MESSAGE)


class _ClientOptionsBase(typing_extensions.TypedDict, total=False):
    base_url: str
    headers: dict[str, str] | None
    params: dict[str, str] | None
    cookies: dict[str, str] | None
    timeout: httpx2.Timeout | float | None
    limits: httpx2.Limits | None
    auth: httpx2.Auth | None
    verify: ssl.SSLContext | bool
    trust_env: bool
    http1: bool
    http2: bool
    proxy: httpx2.URL | str | httpx2.Proxy | None
    follow_redirects: bool
    max_redirects: int
    default_encoding: str | Callable[[bytes], str | None]


class _AsyncClientOptions(_ClientOptionsBase, total=False, closed=True):
    """Keyword arguments `AsyncClient` forwards to the `httpx2.AsyncClient` it owns."""

    transport: httpx2.AsyncBaseTransport | None
    mounts: Mapping[str, httpx2.AsyncBaseTransport | None] | None


class _ClientOptions(_ClientOptionsBase, total=False, closed=True):
    """Keyword arguments `Client` forwards to the `httpx2.Client` it owns."""

    transport: httpx2.BaseTransport | None
    mounts: Mapping[str, httpx2.BaseTransport | None] | None


def _is_unset(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value)


def _select_httpx2_options(
    owner: str,
    options: Mapping[str, typing.Any],
    supported: frozenset[str],
    *,
    httpx2_client: httpx2.Client | httpx2.AsyncClient | None,
) -> dict[str, typing.Any]:
    """Return the options to forward to the owned httpx2 client, dropping unset ones.

    Raise TypeError for unsupported options or options combined with `httpx2_client`.
    """
    unsupported = sorted(options.keys() - supported)
    if unsupported:
        hints = "".join(
            f" {_UNSUPPORTED_OPTION_HINTS[name]}" for name in unsupported if name in _UNSUPPORTED_OPTION_HINTS
        )
        msg = f"{owner}() got unexpected keyword arguments {unsupported}.{hints}"
        raise TypeError(msg)
    forwarded = {name: value for name, value in options.items() if not _is_unset(value)}
    if httpx2_client is not None and forwarded:
        raise TypeError(_HTTPX2_CLIENT_CONFLICT_MESSAGE.format(names=sorted(forwarded)))
    return forwarded


def _request_auth(client: httpx2.Client | httpx2.AsyncClient, request: httpx2.Request) -> httpx2.Auth:
    """Return the auth httpx2 applies to `request`: the client's, else Basic from URL credentials, else none."""
    if client.auth is not None:
        return client.auth
    if request.url.username or request.url.password:
        return httpx2.BasicAuth(request.url.username, request.url.password)
    return _NO_AUTH


async def _send_redirect_hops_async(
    client: httpx2.AsyncClient,
    request: httpx2.Request,
    history: list[httpx2.Response],
) -> httpx2.Response:
    """Send `request` streaming, following redirects hop by hop without reading intermediate bodies.

    The final response's history is `history` plus this call's redirect hops, as in httpx2.
    """
    hops = list(history)
    response = await client.send(request, stream=True, follow_redirects=False, auth=_NO_AUTH)
    while client.follow_redirects and response.next_request is not None:
        await response.aclose()
        hops.append(response)
        if len(hops) > client.max_redirects:
            raise httpx2.TooManyRedirects(_TOO_MANY_REDIRECTS_MESSAGE, request=response.next_request)
        response = await client.send(response.next_request, stream=True, follow_redirects=False, auth=_NO_AUTH)
    response.history = hops
    return response


async def _send_capped_async(client: httpx2.AsyncClient, request: httpx2.Request, cap: int) -> httpx2.Response:
    """Send `request` streaming, driving the client's auth flow and redirects without reading intermediate bodies.

    An auth that sets `requires_response_body` gets each response buffered under `cap` instead.
    """
    auth = _request_auth(client, request)
    flow = auth.async_auth_flow(request)
    history: list[httpx2.Response] = []
    try:
        request = await anext(flow)
        while True:
            response = await _send_redirect_hops_async(client, request, history)
            if auth.requires_response_body:
                streaming = response
                try:
                    response = await _read_capped_async(streaming, cap, streaming.request)
                finally:
                    await streaming.aclose()
            try:
                next_request = await flow.asend(response)
            except StopAsyncIteration:
                return response
            except BaseException:
                await response.aclose()
                raise
            await response.aclose()
            history.append(response)
            request = next_request
    finally:
        await flow.aclose()


@contextlib.asynccontextmanager
async def _stream_capped_async(
    client: httpx2.AsyncClient,
    method: str,
    url: httpx2.URL | str,
    kwargs: dict[str, typing.Any],
    cap: int,
) -> AsyncIterator[httpx2.Response]:
    """Async mirror of `httpx2.AsyncClient.stream` that sends via `_send_capped_async`."""
    response = await _send_capped_async(client, client.build_request(method, url, **kwargs), cap)
    try:
        yield response
    finally:
        await response.aclose()


def _send_redirect_hops(
    client: httpx2.Client,
    request: httpx2.Request,
    history: list[httpx2.Response],
) -> httpx2.Response:
    """Sync mirror of `_send_redirect_hops_async`."""
    hops = list(history)
    response = client.send(request, stream=True, follow_redirects=False, auth=_NO_AUTH)
    while client.follow_redirects and response.next_request is not None:
        response.close()
        hops.append(response)
        if len(hops) > client.max_redirects:
            raise httpx2.TooManyRedirects(_TOO_MANY_REDIRECTS_MESSAGE, request=response.next_request)
        response = client.send(response.next_request, stream=True, follow_redirects=False, auth=_NO_AUTH)
    response.history = hops
    return response


def _send_capped(client: httpx2.Client, request: httpx2.Request, cap: int) -> httpx2.Response:
    """Sync mirror of `_send_capped_async`."""
    auth = _request_auth(client, request)
    flow = auth.sync_auth_flow(request)
    history: list[httpx2.Response] = []
    try:
        request = next(flow)
        while True:
            response = _send_redirect_hops(client, request, history)
            if auth.requires_response_body:
                streaming = response
                try:
                    response = _read_capped(streaming, cap, streaming.request)
                finally:
                    streaming.close()
            try:
                next_request = flow.send(response)
            except StopIteration:
                return response
            except BaseException:
                response.close()
                raise
            response.close()
            history.append(response)
            request = next_request
    finally:
        flow.close()


@contextlib.contextmanager
def _stream_capped(
    client: httpx2.Client,
    method: str,
    url: httpx2.URL | str,
    kwargs: dict[str, typing.Any],
    cap: int,
) -> Iterator[httpx2.Response]:
    """Sync mirror of `_stream_capped_async`."""
    response = _send_capped(client, client.build_request(method, url, **kwargs), cap)
    try:
        yield response
    finally:
        response.close()


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


def _merge_url_query(
    url: httpx2.URL | str, params: typing.Any | None, client_params: httpx2.QueryParams
) -> tuple[httpx2.URL | str, typing.Any | None]:
    """Fold the URL's own query into `params`; httpx2 would otherwise replace it."""
    parsed = httpx2.URL(url)
    if not parsed.query or (params is None and not client_params):
        return url, params
    return parsed.copy_with(query=None), parsed.params.merge(params)


class AsyncClient:
    """Async HTTP client: thin wrapper around httpx2 with typed decoding and middleware."""

    _httpx2_client: httpx2.AsyncClient
    _owns_client: bool
    _decoders: tuple[ResponseDecoder, ...]
    _user_middleware: tuple[AsyncMiddleware, ...]
    _dispatch: AsyncNext
    _max_response_body_bytes: int | None

    def __init__(
        self,
        *,
        httpx2_client: httpx2.AsyncClient | None = None,
        decoders: Sequence[ResponseDecoder] | None = None,
        middleware: Sequence[AsyncMiddleware] = (),
        max_response_body_bytes: int | None = None,
        **httpx2_options: typing.Unpack[_AsyncClientOptions],
    ) -> None:
        _validate_max_response_body_bytes(max_response_body_bytes)
        forwarded = _select_httpx2_options(
            type(self).__name__,
            httpx2_options,
            _AsyncClientOptions.__optional_keys__,
            httpx2_client=httpx2_client,
        )
        if httpx2_client is not None:
            _reject_base_url_query(httpx2_client.base_url)
            self._httpx2_client = httpx2_client
            self._owns_client = False
        else:
            _reject_base_url_query(forwarded.get("base_url", ""))
            self._httpx2_client = httpx2.AsyncClient(**forwarded)
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
                    streaming = await _send_capped_async(self._httpx2_client, request, cap)
                    try:
                        response = await _read_capped_async(streaming, cap, streaming.request)
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
        """Delegate request construction to the wrapped httpx2.AsyncClient, keeping the URL's own query."""
        merged_url, params = _merge_url_query(url, kwargs.pop("params", None), self._httpx2_client.params)
        return self._httpx2_client.build_request(method, merged_url, params=params, **kwargs)

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
        merged_url, params = _merge_url_query(url, params, self._httpx2_client.params)
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
        request = self._httpx2_client.build_request(method, merged_url, **kwargs)
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
        middleware): the protocol is typed on a fully-buffered response, and reading it
        would consume the stream.

        Auto-raises StatusError subclasses on 4xx/5xx (NotFoundError,
        ServiceUnavailableError, etc.) — consistent with client.get()/post()/etc.
        On error the response body is pre-read so exc.response.content is
        accessible. You lose the streaming property on errors; rare in practice.

        Maps httpx2 exceptions raised during the request OR body consumption to
        httpware exceptions via _httpx2_exception_mapper.
        """
        merged_url, params = _merge_url_query(url, params, self._httpx2_client.params)
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

        cap = self._max_response_body_bytes
        opened = (
            self._httpx2_client.stream(method, merged_url, **kwargs)
            if cap is None
            else _stream_capped_async(self._httpx2_client, method, merged_url, kwargs, cap)
        )
        async with _httpx2_exception_mapper(), opened as response:
            if HTTPStatus.BAD_REQUEST <= response.status_code < 600:  # noqa: PLR2004 — 600 is the synthetic upper bound for 5xx
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

    def __init__(
        self,
        *,
        httpx2_client: httpx2.Client | None = None,
        decoders: Sequence[ResponseDecoder] | None = None,
        middleware: Sequence[Middleware] = (),
        max_response_body_bytes: int | None = None,
        **httpx2_options: typing.Unpack[_ClientOptions],
    ) -> None:
        _validate_max_response_body_bytes(max_response_body_bytes)
        forwarded = _select_httpx2_options(
            type(self).__name__,
            httpx2_options,
            _ClientOptions.__optional_keys__,
            httpx2_client=httpx2_client,
        )
        if httpx2_client is not None:
            _reject_base_url_query(httpx2_client.base_url)
            self._httpx2_client = httpx2_client
            self._owns_client = False
        else:
            _reject_base_url_query(forwarded.get("base_url", ""))
            self._httpx2_client = httpx2.Client(**forwarded)
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
                    streaming = _send_capped(self._httpx2_client, request, cap)
                    try:
                        response = _read_capped(streaming, cap, streaming.request)
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
        """Delegate request construction to the wrapped httpx2.Client, keeping the URL's own query."""
        merged_url, params = _merge_url_query(url, kwargs.pop("params", None), self._httpx2_client.params)
        return self._httpx2_client.build_request(method, merged_url, params=params, **kwargs)

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
        merged_url, params = _merge_url_query(url, params, self._httpx2_client.params)
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
        request = self._httpx2_client.build_request(method, merged_url, **kwargs)
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
        merged_url, params = _merge_url_query(url, params, self._httpx2_client.params)
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

        cap = self._max_response_body_bytes
        opened = (
            self._httpx2_client.stream(method, merged_url, **kwargs)
            if cap is None
            else _stream_capped(self._httpx2_client, method, merged_url, kwargs, cap)
        )
        with _httpx2_exception_mapper_sync(), opened as response:
            if HTTPStatus.BAD_REQUEST <= response.status_code < 600:  # noqa: PLR2004 — 600 is the synthetic upper bound for 5xx
                if cap is None:
                    response.read()  # pre-read body so exc.response.content works
                    _raise_on_status_error(response)
                else:
                    # Bound the error pre-read; raises ResponseTooLargeError when over cap.
                    _raise_on_status_error(_read_capped(response, cap, response.request))
            yield response

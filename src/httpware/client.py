"""AsyncClient — the thin httpx2 wrapper."""

import typing
from collections.abc import Sequence
from http import HTTPStatus

import httpx2

from httpware.decoders import ResponseDecoder
from httpware.decoders.pydantic import PydanticDecoder
from httpware.errors import (
    STATUS_TO_EXCEPTION,
    ClientStatusError,
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

        self._decoder = decoder if decoder is not None else PydanticDecoder()
        self._user_middleware = tuple(middleware)
        self._dispatch = compose(self._user_middleware, self._terminal)

    async def _terminal(self, request: httpx2.Request) -> httpx2.Response:
        try:
            response = await self._httpx2_client.send(request)
        except httpx2.TimeoutException as exc:
            raise TimeoutError(str(exc)) from exc
        except (httpx2.InvalidURL, httpx2.CookieConflict) as exc:
            raise TransportError(str(exc)) from exc
        except httpx2.HTTPError as exc:
            raise TransportError(str(exc)) from exc
        except RuntimeError as exc:
            if "closed" in str(exc):
                raise TransportError(str(exc)) from exc
            raise
        status = response.status_code
        if HTTPStatus.BAD_REQUEST <= status < 600:  # noqa: PLR2004 — 600 is the synthetic upper bound for 5xx
            exc_class = STATUS_TO_EXCEPTION.get(
                status,
                ClientStatusError if status < HTTPStatus.INTERNAL_SERVER_ERROR else ServerStatusError,
            )
            raise exc_class(response)
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

    def build_request(self, method: str, url: str, **kwargs: typing.Any) -> httpx2.Request:  # noqa: ANN401 — mirrors httpx2.AsyncClient.build_request kwargs
        """Delegate request construction to the wrapped httpx2.AsyncClient."""
        return self._httpx2_client.build_request(method, url, **kwargs)

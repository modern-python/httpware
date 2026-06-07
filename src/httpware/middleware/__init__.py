"""Middleware + AsyncMiddleware protocols, Next + AsyncNext types, and phase-shortcut decorators.

Middleware operates directly on httpx2.Request / httpx2.Response — there is
no httpware-owned request type. The chain is composed at AsyncClient.__init__
or Client.__init__ (see client.py) and frozen for the client's lifetime.
"""

from collections.abc import Awaitable, Callable
from typing import Protocol, TypeAlias, runtime_checkable

import httpx2


AsyncNext: TypeAlias = Callable[[httpx2.Request], Awaitable[httpx2.Response]]


@runtime_checkable
class AsyncMiddleware(Protocol):
    """Structural protocol every async middleware satisfies."""

    async def __call__(self, request: httpx2.Request, next: AsyncNext) -> httpx2.Response:  # noqa: A002
        """Process `request`; call `next(request)` to forward, or synthesize a Response."""
        ...


def async_before_request(f: Callable[[httpx2.Request], Awaitable[httpx2.Request]]) -> AsyncMiddleware:
    """Wrap an async request transform into an AsyncMiddleware."""

    class _BeforeRequestMiddleware:
        async def __call__(self, request: httpx2.Request, next: AsyncNext) -> httpx2.Response:  # noqa: A002
            return await next(await f(request))

        def __repr__(self) -> str:
            return f"<async_before_request({f.__qualname__})>"  # ty: ignore[unresolved-attribute]

    return _BeforeRequestMiddleware()


def async_after_response(
    f: Callable[[httpx2.Request, httpx2.Response], Awaitable[httpx2.Response]],
) -> AsyncMiddleware:
    """Wrap an async response transform into an AsyncMiddleware."""

    class _AfterResponseMiddleware:
        async def __call__(self, request: httpx2.Request, next: AsyncNext) -> httpx2.Response:  # noqa: A002
            response = await next(request)
            return await f(request, response)

        def __repr__(self) -> str:
            return f"<async_after_response({f.__qualname__})>"  # ty: ignore[unresolved-attribute]

    return _AfterResponseMiddleware()


def async_on_error(
    f: Callable[[httpx2.Request, Exception], Awaitable[httpx2.Response | None]],
) -> AsyncMiddleware:
    """Wrap an async error handler into an AsyncMiddleware.

    Catches Exception (not BaseException), so asyncio.CancelledError propagates.
    Handler returning None re-raises; returning a Response replaces the failure.
    """

    class _OnErrorMiddleware:
        async def __call__(self, request: httpx2.Request, next: AsyncNext) -> httpx2.Response:  # noqa: A002
            try:
                return await next(request)
            except Exception as exc:
                result = await f(request, exc)
                if result is None:
                    raise
                return result

        def __repr__(self) -> str:
            return f"<async_on_error({f.__qualname__})>"  # ty: ignore[unresolved-attribute]

    return _OnErrorMiddleware()


Next: TypeAlias = Callable[[httpx2.Request], httpx2.Response]


@runtime_checkable
class Middleware(Protocol):
    """Structural protocol every sync middleware satisfies."""

    def __call__(self, request: httpx2.Request, next: Next) -> httpx2.Response:  # noqa: A002
        """Process `request`; call `next(request)` to forward, or synthesize a Response."""
        ...


def before_request(f: Callable[[httpx2.Request], httpx2.Request]) -> Middleware:
    """Wrap a sync request transform into a Middleware."""

    class _BeforeRequestMiddleware:
        def __call__(self, request: httpx2.Request, next: Next) -> httpx2.Response:  # noqa: A002
            return next(f(request))

        def __repr__(self) -> str:
            return f"<before_request({f.__qualname__})>"  # ty: ignore[unresolved-attribute]

    return _BeforeRequestMiddleware()


def after_response(
    f: Callable[[httpx2.Request, httpx2.Response], httpx2.Response],
) -> Middleware:
    """Wrap a sync response transform into a Middleware."""

    class _AfterResponseMiddleware:
        def __call__(self, request: httpx2.Request, next: Next) -> httpx2.Response:  # noqa: A002
            response = next(request)
            return f(request, response)

        def __repr__(self) -> str:
            return f"<after_response({f.__qualname__})>"  # ty: ignore[unresolved-attribute]

    return _AfterResponseMiddleware()


def on_error(
    f: Callable[[httpx2.Request, Exception], httpx2.Response | None],
) -> Middleware:
    """Wrap a sync error handler into a Middleware.

    Catches Exception (not BaseException), so KeyboardInterrupt / SystemExit propagate.
    Handler returning None re-raises; returning a Response replaces the failure.
    """

    class _OnErrorMiddleware:
        def __call__(self, request: httpx2.Request, next: Next) -> httpx2.Response:  # noqa: A002
            try:
                return next(request)
            except Exception as exc:
                result = f(request, exc)
                if result is None:
                    raise
                return result

        def __repr__(self) -> str:
            return f"<on_error({f.__qualname__})>"  # ty: ignore[unresolved-attribute]

    return _OnErrorMiddleware()

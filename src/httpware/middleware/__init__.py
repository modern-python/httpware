"""AsyncMiddleware protocol, AsyncNext type, and phase-shortcut decorators.

AsyncMiddleware operates directly on httpx2.Request / httpx2.Response — there is
no httpware-owned request type. The chain is composed at AsyncClient.__init__
(see client.py) and frozen for the client's lifetime.
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

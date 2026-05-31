"""Middleware protocol — the AsyncClient ↔ Middleware seam (Seam 2)."""

from collections.abc import Awaitable, Callable
from typing import Protocol, TypeAlias, runtime_checkable

from httpware.request import Request
from httpware.response import Response


Next: TypeAlias = Callable[[Request], Awaitable[Response]]


@runtime_checkable
class Middleware(Protocol):
    """Structural protocol every middleware satisfies.

    A middleware receives the incoming `Request` and a `Next` callable. It may
    inspect/transform the request, await `next(request)` to forward to the rest
    of the chain (eventually the transport), inspect/transform the returned
    `Response`, short-circuit by returning a `Response` without calling `next`,
    or raise.
    """

    async def __call__(self, request: Request, next: Next) -> Response:  # noqa: A002
        """Process `request`; call `next(request)` to forward, or synthesize a Response."""
        ...


def before_request(f: Callable[[Request], Awaitable[Request]]) -> Middleware:
    """Wrap an async request transform into a Middleware.

    The decorated function receives the incoming Request and returns a
    (possibly modified) Request, which is then forwarded down the chain.
    """

    class _BeforeRequestMiddleware:
        async def __call__(self, request: Request, next: Next) -> Response:  # noqa: A002
            return await next(await f(request))

        def __repr__(self) -> str:
            return f"<before_request({f.__qualname__})>"  # ty: ignore[unresolved-attribute]

    return _BeforeRequestMiddleware()


__all__ = ["Middleware", "Next", "before_request"]

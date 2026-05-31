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


__all__ = ["Middleware", "Next"]

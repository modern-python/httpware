"""Middleware chain composition — wires a middleware list against a Transport.

Private helper. AsyncClient calls `compose` at construction time and stores the
returned `Next` callable; per-request dispatch awaits that callable.
"""

from collections.abc import Sequence

from httpware.middleware import Middleware, Next
from httpware.request import Request
from httpware.response import Response
from httpware.transports import Transport


def compose(middlewares: Sequence[Middleware], transport: Transport) -> Next:
    """Fold `middlewares` into a single `Next` callable terminating at `transport`.

    The outermost middleware in the input sequence is the first to receive the
    request; its `next` argument forwards to the next middleware, and so on,
    until the innermost middleware's `next` calls `transport.__call__`. An
    empty sequence returns `transport.__call__` directly.

    The returned callable is reusable across many requests; it captures
    references to `middlewares` and `transport` by closure.
    """
    chain: Next = transport.__call__
    for middleware in reversed(middlewares):
        chain = _wrap(middleware, chain)
    return chain


def _wrap(middleware: Middleware, next_call: Next) -> Next:
    async def _call(request: Request) -> Response:
        return await middleware(request, next_call)

    return _call


__all__ = ["compose"]

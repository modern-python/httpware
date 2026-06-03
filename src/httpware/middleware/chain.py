"""Chain composition for the middleware stack."""

import typing
from collections.abc import Awaitable, Callable, Sequence

import httpx2


if typing.TYPE_CHECKING:
    from httpware.middleware import Middleware


_Next: typing.TypeAlias = Callable[[httpx2.Request], Awaitable[httpx2.Response]]


def compose(middleware: "Sequence[Middleware]", terminal: _Next) -> _Next:
    """Fold `middleware` into a single callable around `terminal`.

    The first middleware in the sequence is the outermost wrapper.
    """
    dispatch: _Next = terminal
    for layer in reversed(middleware):
        dispatch = _wrap(layer, dispatch)
    return dispatch


def _wrap(layer: "Middleware", inner: _Next) -> _Next:
    async def call(request: httpx2.Request) -> httpx2.Response:
        return await layer(request, inner)

    return call

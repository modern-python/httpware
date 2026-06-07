"""Chain composition for the middleware stack."""

import typing
from collections.abc import Awaitable, Callable, Sequence

import httpx2


if typing.TYPE_CHECKING:
    from httpware.middleware import AsyncMiddleware


_AsyncNext: typing.TypeAlias = Callable[[httpx2.Request], Awaitable[httpx2.Response]]


def compose_async(middleware: "Sequence[AsyncMiddleware]", terminal: _AsyncNext) -> _AsyncNext:
    """Fold `middleware` into a single callable around `terminal`.

    The first middleware in the sequence is the outermost wrapper.
    """
    dispatch: _AsyncNext = terminal
    for layer in reversed(middleware):
        dispatch = _wrap(layer, dispatch)
    return dispatch


def _wrap(layer: "AsyncMiddleware", inner: _AsyncNext) -> _AsyncNext:
    async def call(request: httpx2.Request) -> httpx2.Response:
        return await layer(request, inner)

    return call

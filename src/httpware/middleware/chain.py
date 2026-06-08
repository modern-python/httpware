"""Chain composition for the middleware stack."""

import typing
from collections.abc import Awaitable, Callable, Sequence

import httpx2

from httpware.middleware import AsyncMiddleware, Middleware


_AsyncNext: typing.TypeAlias = Callable[[httpx2.Request], Awaitable[httpx2.Response]]
_Next: typing.TypeAlias = Callable[[httpx2.Request], httpx2.Response]


def compose_async(middleware: Sequence[AsyncMiddleware], terminal: _AsyncNext) -> _AsyncNext:
    """Fold `middleware` into a single callable around `terminal`.

    The first middleware in the sequence is the outermost wrapper.
    """
    dispatch: _AsyncNext = terminal
    for layer in reversed(middleware):
        dispatch = _wrap(layer, dispatch)
    return dispatch


def _wrap(layer: AsyncMiddleware, inner: _AsyncNext) -> _AsyncNext:
    async def call(request: httpx2.Request) -> httpx2.Response:
        return await layer(request, inner)

    return call


def compose(middleware: Sequence[Middleware], terminal: _Next) -> _Next:
    """Fold sync `middleware` into a single callable around sync `terminal`.

    The first middleware in the sequence is the outermost wrapper.
    """
    dispatch: _Next = terminal
    for layer in reversed(middleware):
        dispatch = _wrap_sync(layer, dispatch)
    return dispatch


def _wrap_sync(layer: Middleware, inner: _Next) -> _Next:
    def call(request: httpx2.Request) -> httpx2.Response:
        return layer(request, inner)

    return call

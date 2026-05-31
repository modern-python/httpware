"""Tests for the Middleware protocol and chain composition."""

from collections.abc import Awaitable, Callable
from typing import get_type_hints

from httpware.middleware import Middleware, Next
from httpware.request import Request
from httpware.response import Response


class _SignalMiddleware:
    """Minimal valid Middleware implementation used by tests."""

    async def __call__(self, request: Request, next: Next) -> Response:  # noqa: A002
        return await next(request)


def test_runtime_checkable_isinstance_works() -> None:
    """A class implementing `__call__` satisfies the Middleware Protocol at runtime."""
    # runtime_checkable checks for presence of __call__, not signature details
    assert isinstance(_SignalMiddleware(), Middleware)


def test_next_type_alias_resolves_to_callable() -> None:
    """`Next` resolves to `Callable[[Request], Awaitable[Response]]`."""
    expected = Callable[[Request], Awaitable[Response]]
    assert Next == expected


def test_next_annotation_on_signal_middleware() -> None:
    """`next` parameter on `_SignalMiddleware.__call__` is annotated with `Next`."""
    hints = get_type_hints(_SignalMiddleware.__call__)
    assert hints["next"] == Next

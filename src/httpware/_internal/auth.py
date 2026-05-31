"""Normalize the `auth=` value of AsyncClient into a Middleware (or None)."""

import inspect
from collections.abc import Awaitable, Callable
from typing import TypeAlias

from httpware.middleware import Middleware, before_request
from httpware.request import Request


_MIDDLEWARE_ARITY = 2

AuthValue: TypeAlias = str | Callable[[], str | Awaitable[str]] | Middleware | None


def _normalize_auth(value: AuthValue) -> Middleware | None:
    """Coerce an `auth=` value into a Middleware.

    - `None` → returns `None` (no auth middleware injected).
    - `str` → returns a middleware that sets `Authorization: Bearer <str>`
      on every request (skipping if Authorization is already present).
    - `Callable[[], str | Awaitable[str]]` (zero-arg) → returns a middleware
      that calls the provider per request (awaiting if it returns an
      awaitable) and sets `Authorization: Bearer <result>` (skip-if-present).
    - `Middleware` (two-arg `__call__(request, next)`) → returned unchanged.
    - Any other callable shape → raises `TypeError` naming `auth=`.
    """
    if value is None:
        return None
    if isinstance(value, str):
        return _bearer(value)
    if not callable(value):
        msg = f"`auth=` must be a string, zero-arg callable, Middleware, or None; got {type(value).__name__}"
        raise TypeError(msg)
    n_params = len(inspect.signature(value).parameters)
    if n_params == 0:
        return _bearer_from_provider(value)  # ty: ignore[invalid-argument-type]
    if n_params == _MIDDLEWARE_ARITY:
        return value  # ty: ignore[invalid-return-type]
    msg = f"`auth=` callable must take 0 args (token provider) or 2 args (Middleware); got {n_params}"
    raise TypeError(msg)


def _bearer(token: str) -> Middleware:
    """Middleware that sets `Authorization: Bearer <token>` (skip-if-present)."""

    @before_request
    async def _add_static_bearer(request: Request) -> Request:
        if _has_authorization(request):
            return request
        return request.with_header("Authorization", f"Bearer {token}")

    return _add_static_bearer


def _bearer_from_provider(
    provider: Callable[[], str | Awaitable[str]],
) -> Middleware:
    """Middleware that calls `provider()` per request and sets the header."""

    @before_request
    async def _add_dynamic_bearer(request: Request) -> Request:
        if _has_authorization(request):
            return request
        token = provider()
        if inspect.isawaitable(token):
            token = await token
        return request.with_header("Authorization", f"Bearer {token}")

    return _add_dynamic_bearer


def _has_authorization(request: Request) -> bool:
    """Case-insensitive check for an existing Authorization header."""
    return any(k.lower() == "authorization" for k in request.headers)

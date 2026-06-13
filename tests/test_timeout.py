"""Tests for the AsyncTimeout middleware.

Calls the middleware directly with an injected `next` callable. Expiry tests use a
tiny timeout against a long sleep (large margin -> not wall-clock flaky); the
inner-timeout test raises immediately so no real time passes.
"""

import asyncio
import builtins
import logging

import httpx2
import pytest

from httpware.errors import TimeoutError as HttpwareTimeoutError
from httpware.middleware.resilience.timeout import AsyncTimeout


def _request() -> httpx2.Request:
    return httpx2.Request("GET", "https://example.test/x")


async def test_passes_through_response_when_under_budget() -> None:
    async def _next(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, request=request)

    middleware = AsyncTimeout(timeout=10.0)
    response = await middleware(_request(), _next)
    assert response.status_code == 200  # noqa: PLR2004


async def test_expiry_raises_httpware_timeout_chained_from_builtin(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def _next(request: httpx2.Request) -> httpx2.Response:
        await asyncio.sleep(5.0)
        return httpx2.Response(200, request=request)  # pragma: no cover — deadline fires first

    middleware = AsyncTimeout(timeout=0.01)
    with (
        caplog.at_level(logging.WARNING, logger="httpware.timeout"),
        pytest.raises(HttpwareTimeoutError) as info,
    ):
        await middleware(_request(), _next)

    assert "overall timeout of 0.01s exceeded" in str(info.value)
    assert isinstance(info.value.__cause__, builtins.TimeoutError)

    records = [r for r in caplog.records if r.name == "httpware.timeout"]
    assert len(records) == 1
    assert records[0].levelno == logging.WARNING
    assert records[0].event == "timeout.exceeded"  # ty: ignore[unresolved-attribute]
    assert records[0].timeout == 0.01  # noqa: PLR2004  # ty: ignore[unresolved-attribute]
    assert records[0].method == "GET"  # ty: ignore[unresolved-attribute]
    assert "example.test/x" in records[0].url  # ty: ignore[unresolved-attribute]


async def test_inner_timeout_propagates_unchanged() -> None:
    """A TimeoutError from next (not our deadline) is re-raised untouched."""

    async def _next(_request: httpx2.Request) -> httpx2.Response:
        msg = "inner read timeout"
        raise HttpwareTimeoutError(msg)

    middleware = AsyncTimeout(timeout=10.0)
    with pytest.raises(HttpwareTimeoutError) as info:
        await middleware(_request(), _next)

    assert "inner read timeout" in str(info.value)
    assert "overall timeout" not in str(info.value)


async def test_raw_builtin_timeout_from_next_propagates_by_identity() -> None:
    """A raw builtins.TimeoutError from next (e.g. a nested asyncio.timeout) is re-raised as-is."""
    inner = builtins.TimeoutError("nested asyncio timeout")

    async def _next(_request: httpx2.Request) -> httpx2.Response:
        raise inner

    middleware = AsyncTimeout(timeout=10.0)
    with pytest.raises(builtins.TimeoutError) as info:
        await middleware(_request(), _next)

    assert info.value is inner  # propagated by identity, not re-wrapped
    assert "overall timeout" not in str(info.value)


def test_zero_timeout_rejected() -> None:
    with pytest.raises(ValueError, match="timeout must be a finite number > 0"):
        AsyncTimeout(timeout=0)


def test_negative_timeout_rejected() -> None:
    with pytest.raises(ValueError, match="timeout must be a finite number > 0"):
        AsyncTimeout(timeout=-1.0)


def test_nan_timeout_rejected() -> None:
    with pytest.raises(ValueError, match="timeout must be a finite number > 0"):
        AsyncTimeout(timeout=float("nan"))


def test_inf_timeout_rejected() -> None:
    with pytest.raises(ValueError, match="timeout must be a finite number > 0"):
        AsyncTimeout(timeout=float("inf"))

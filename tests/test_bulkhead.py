"""Tests for the Bulkhead middleware.

Mocks the transport via httpx2.MockTransport. Concurrency tests use real
asyncio coroutines with sub-100ms timeouts so the suite stays fast.
"""

import asyncio
import contextlib
from collections.abc import Callable, Coroutine
from http import HTTPStatus
from typing import Any

import httpx2
import pytest

from httpware import AsyncClient
from httpware.errors import BulkheadFullError
from httpware.middleware.resilience.bulkhead import Bulkhead


_MAX_CONCURRENT_1 = 1
_MAX_CONCURRENT_2 = 2
_ACQUIRE_TIMEOUT_FAST = 0.01


class _SlowHandler:
    """Mock handler that blocks for `delay` seconds before returning 200 OK."""

    def __init__(self, delay: float) -> None:
        self.delay = delay
        self.in_flight = 0
        self.max_in_flight = 0
        self.calls = 0

    async def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.calls += 1
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            await asyncio.sleep(self.delay)
            return httpx2.Response(HTTPStatus.OK, request=request)
        finally:
            self.in_flight -= 1


def _client(
    handler: Callable[[httpx2.Request], httpx2.Response]
    | Callable[[httpx2.Request], Coroutine[Any, Any, httpx2.Response]],
    *,
    bulkhead: Bulkhead,
) -> AsyncClient:
    transport = httpx2.MockTransport(handler)
    return AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=transport),
        middleware=[bulkhead],
    )


def test_max_concurrent_zero_rejected() -> None:
    with pytest.raises(ValueError, match="max_concurrent must be >= 1"):
        Bulkhead(max_concurrent=0)


def test_max_concurrent_negative_rejected() -> None:
    with pytest.raises(ValueError, match="max_concurrent must be >= 1"):
        Bulkhead(max_concurrent=-1)


def test_negative_acquire_timeout_rejected() -> None:
    with pytest.raises(ValueError, match="acquire_timeout must be >= 0"):
        Bulkhead(max_concurrent=_MAX_CONCURRENT_1, acquire_timeout=-0.1)


def test_acquire_timeout_zero_accepted() -> None:
    bulkhead = Bulkhead(max_concurrent=_MAX_CONCURRENT_1, acquire_timeout=0)
    assert bulkhead._acquire_timeout == 0  # noqa: SLF001


def test_acquire_timeout_none_accepted() -> None:
    bulkhead = Bulkhead(max_concurrent=_MAX_CONCURRENT_1, acquire_timeout=None)
    assert bulkhead._acquire_timeout is None  # noqa: SLF001


async def test_succeeds_when_slot_available() -> None:
    handler = _SlowHandler(delay=0.0)
    client = _client(handler, bulkhead=Bulkhead(max_concurrent=_MAX_CONCURRENT_2))
    response = await client.get("https://example.test/x")
    assert response.status_code == HTTPStatus.OK
    assert handler.calls == 1


async def test_serializes_at_capacity() -> None:
    """With max_concurrent=1 and 3 concurrent calls, in-flight count never exceeds 1."""
    handler = _SlowHandler(delay=0.02)
    client = _client(
        handler,
        bulkhead=Bulkhead(max_concurrent=_MAX_CONCURRENT_1, acquire_timeout=None),
    )
    await asyncio.gather(
        client.get("https://example.test/a"),
        client.get("https://example.test/b"),
        client.get("https://example.test/c"),
    )
    assert handler.calls == 3  # noqa: PLR2004 — three concurrent gets above
    assert handler.max_in_flight == 1  # cap honored


async def test_max_concurrent_2_observes_at_most_2_in_flight() -> None:
    handler = _SlowHandler(delay=0.02)
    client = _client(handler, bulkhead=Bulkhead(max_concurrent=_MAX_CONCURRENT_2, acquire_timeout=None))
    await asyncio.gather(
        client.get("https://example.test/a"),
        client.get("https://example.test/b"),
        client.get("https://example.test/c"),
        client.get("https://example.test/d"),
    )
    assert handler.calls == 4  # noqa: PLR2004 — four concurrent gets above
    assert handler.max_in_flight <= _MAX_CONCURRENT_2


async def test_raises_bulkhead_full_error_when_acquire_timeout_exceeded() -> None:
    """Slot is held by a slow request; a second request with a tiny timeout raises BulkheadFullError."""
    handler = _SlowHandler(delay=1.0)
    bulkhead = Bulkhead(max_concurrent=_MAX_CONCURRENT_1, acquire_timeout=_ACQUIRE_TIMEOUT_FAST)
    client = _client(handler, bulkhead=bulkhead)

    async def _hold_slot() -> None:
        await client.get("https://example.test/slow")

    task = asyncio.create_task(_hold_slot())
    # Yield to let the slow request acquire the semaphore.
    await asyncio.sleep(0)

    with pytest.raises(BulkheadFullError) as exc_info:
        await client.get("https://example.test/fast")

    assert exc_info.value.max_concurrent == _MAX_CONCURRENT_1
    assert exc_info.value.acquire_timeout == _ACQUIRE_TIMEOUT_FAST

    # Cancel the lingering slow task to avoid polluting the event loop.
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task

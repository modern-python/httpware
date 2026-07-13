"""Tests for the AsyncBulkhead middleware.

Mocks the transport via httpx2.MockTransport. Concurrency tests use real
asyncio coroutines with sub-100ms timeouts so the suite stays fast.
"""

import asyncio
import contextlib
import logging
from collections.abc import Callable, Coroutine
from http import HTTPStatus
from typing import Any
from unittest.mock import AsyncMock

import httpx2
import pytest

from httpware import AsyncClient
from httpware.errors import BulkheadFullError
from httpware.middleware.resilience.bulkhead import AsyncBulkhead
from httpware.middleware.resilience.retry import AsyncRetry


_MAX_CONCURRENT_1 = 1
_MAX_CONCURRENT_2 = 2
_ACQUIRE_TIMEOUT_FAST = 0.01
_ACQUIRE_TIMEOUT_SHORT = 0.02
_ACQUIRE_TIMEOUT_LONG = 0.1


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
    bulkhead: AsyncBulkhead,
) -> AsyncClient:
    transport = httpx2.MockTransport(handler)
    return AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=transport),
        middleware=[bulkhead],
    )


def test_max_concurrent_zero_rejected() -> None:
    with pytest.raises(ValueError, match="max_concurrent must be >= 1"):
        AsyncBulkhead(max_concurrent=0)


def test_max_concurrent_negative_rejected() -> None:
    with pytest.raises(ValueError, match="max_concurrent must be >= 1"):
        AsyncBulkhead(max_concurrent=-1)


def test_negative_acquire_timeout_rejected() -> None:
    with pytest.raises(ValueError, match="acquire_timeout must be >= 0"):
        AsyncBulkhead(max_concurrent=_MAX_CONCURRENT_1, acquire_timeout=-0.1)


def test_acquire_timeout_zero_accepted() -> None:
    bulkhead = AsyncBulkhead(max_concurrent=_MAX_CONCURRENT_1, acquire_timeout=0)
    assert bulkhead._acquire_timeout == 0  # noqa: SLF001


def test_acquire_timeout_none_accepted() -> None:
    bulkhead = AsyncBulkhead(max_concurrent=_MAX_CONCURRENT_1, acquire_timeout=None)
    assert bulkhead._acquire_timeout is None  # noqa: SLF001


async def test_succeeds_when_slot_available() -> None:
    handler = _SlowHandler(delay=0.0)
    client = _client(handler, bulkhead=AsyncBulkhead(max_concurrent=_MAX_CONCURRENT_2))
    response = await client.get("https://example.test/x")
    assert response.status_code == HTTPStatus.OK
    assert handler.calls == 1


async def test_serializes_at_capacity() -> None:
    """With max_concurrent=1 and 3 concurrent calls, in-flight count never exceeds 1."""
    handler = _SlowHandler(delay=0.02)
    client = _client(
        handler,
        bulkhead=AsyncBulkhead(max_concurrent=_MAX_CONCURRENT_1, acquire_timeout=None),
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
    client = _client(handler, bulkhead=AsyncBulkhead(max_concurrent=_MAX_CONCURRENT_2, acquire_timeout=None))
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
    bulkhead = AsyncBulkhead(max_concurrent=_MAX_CONCURRENT_1, acquire_timeout=_ACQUIRE_TIMEOUT_FAST)
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


async def test_bulkhead_full_error_chains_from_timeout() -> None:
    """BulkheadFullError raised on the async timeout path chains from the TimeoutError."""
    handler = _SlowHandler(delay=1.0)
    bulkhead = AsyncBulkhead(max_concurrent=_MAX_CONCURRENT_1, acquire_timeout=_ACQUIRE_TIMEOUT_FAST)
    client = _client(handler, bulkhead=bulkhead)

    async def _hold_slot() -> None:
        await client.get("https://example.test/slow")

    task = asyncio.create_task(_hold_slot())
    # Yield to let the slow request acquire the semaphore.
    await asyncio.sleep(0)

    with pytest.raises(BulkheadFullError) as exc_info:
        await client.get("https://example.test/fast")

    assert isinstance(exc_info.value.__cause__, TimeoutError)

    # Cancel the lingering slow task to avoid polluting the event loop.
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


async def test_bounded_wait_raises_bulkhead_full_error() -> None:
    """With max_concurrent=1 and acquire_timeout=0.02, the second call raises after ~20ms.

    Complements test_raises_bulkhead_full_error_when_acquire_timeout_exceeded
    (from Task 3, coverage smoke); this test additionally asserts the
    BulkheadFullError fields (max_concurrent / acquire_timeout) carry the
    configured values.
    """
    handler = _SlowHandler(delay=_ACQUIRE_TIMEOUT_LONG)  # holds slot for 100ms
    client = _client(
        handler,
        bulkhead=AsyncBulkhead(max_concurrent=_MAX_CONCURRENT_1, acquire_timeout=_ACQUIRE_TIMEOUT_SHORT),
    )

    first = asyncio.create_task(client.get("https://example.test/a"))
    await asyncio.sleep(0.005)  # let first acquire the slot
    with pytest.raises(BulkheadFullError) as info:
        await client.get("https://example.test/b")
    assert info.value.max_concurrent == _MAX_CONCURRENT_1
    assert info.value.acquire_timeout == _ACQUIRE_TIMEOUT_SHORT
    await first  # cleanup


async def test_acquire_timeout_zero_fails_fast() -> None:
    """With acquire_timeout=0, the second call raises immediately without waiting."""
    handler = _SlowHandler(delay=_ACQUIRE_TIMEOUT_LONG)
    client = _client(
        handler,
        bulkhead=AsyncBulkhead(max_concurrent=_MAX_CONCURRENT_1, acquire_timeout=0),
    )

    first = asyncio.create_task(client.get("https://example.test/a"))
    await asyncio.sleep(0.005)
    with pytest.raises(BulkheadFullError) as info:
        await client.get("https://example.test/b")
    assert info.value.acquire_timeout == 0
    await first


async def test_acquire_timeout_none_waits_forever() -> None:
    """With acquire_timeout=None, the second call waits until the first releases."""
    handler = _SlowHandler(delay=_ACQUIRE_TIMEOUT_SHORT)
    client = _client(
        handler,
        bulkhead=AsyncBulkhead(max_concurrent=_MAX_CONCURRENT_1, acquire_timeout=None),
    )

    first = asyncio.create_task(client.get("https://example.test/a"))
    second = asyncio.create_task(client.get("https://example.test/b"))
    responses = await asyncio.wait_for(asyncio.gather(first, second), timeout=1.0)
    assert all(r.status_code == HTTPStatus.OK for r in responses)
    assert handler.calls == 2  # noqa: PLR2004 — both eventually succeeded


async def test_slot_released_after_exception_in_next() -> None:
    """If next() raises, the slot is released — subsequent calls succeed immediately."""
    call_count = {"n": 0}

    def handler(request: httpx2.Request) -> httpx2.Response:
        call_count["n"] += 1
        if call_count["n"] == 1:
            msg = "boom"
            raise RuntimeError(msg)
        return httpx2.Response(HTTPStatus.OK, request=request)

    client = _client(handler, bulkhead=AsyncBulkhead(max_concurrent=_MAX_CONCURRENT_1, acquire_timeout=0))

    # First call raises; slot must release.
    with pytest.raises(RuntimeError, match="boom"):
        await client.get("https://example.test/a")

    # Second call must succeed immediately — fail-fast=0 proves the slot is free.
    response = await client.get("https://example.test/b")
    assert response.status_code == HTTPStatus.OK
    assert call_count["n"] == 2  # noqa: PLR2004 — second call reached handler


async def test_slot_released_on_cancellation() -> None:
    """If the calling task is cancelled while next() runs, the slot is released."""
    handler = _SlowHandler(delay=0.5)  # would block indefinitely
    bulkhead = AsyncBulkhead(max_concurrent=_MAX_CONCURRENT_1, acquire_timeout=0)
    client = _client(handler, bulkhead=bulkhead)

    first = asyncio.create_task(client.get("https://example.test/a"))
    await asyncio.sleep(0.01)  # let first acquire and start sleeping in handler
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first

    # Slot must now be released — fail-fast=0 next call proves it.
    handler.delay = 0.0  # speed up the next request
    response = await client.get("https://example.test/b")
    assert response.status_code == HTTPStatus.OK


async def test_cancellation_before_acquire_does_not_hold_slot() -> None:
    """Cancellation while waiting for a slot must not leak the slot to the cancelled task.

    Stronger check than just "first completes": after the cancelled task is buried,
    a fresh request issued WHILE first still holds the slot must wait for first to
    release (it must NOT take the slot the cancelled task was waiting for). And once
    first releases, the fresh request must complete normally.
    """
    handler = _SlowHandler(delay=0.05)
    bulkhead = AsyncBulkhead(max_concurrent=_MAX_CONCURRENT_1, acquire_timeout=None)
    client = _client(handler, bulkhead=bulkhead)

    first = asyncio.create_task(client.get("https://example.test/a"))
    await asyncio.sleep(0.005)  # first acquires
    second = asyncio.create_task(client.get("https://example.test/b"))  # waits for slot
    await asyncio.sleep(0.005)  # ensure second is parked on acquire
    second.cancel()
    with pytest.raises(asyncio.CancelledError):
        await second

    # Third request issued while first still holds the slot — must not see a phantom
    # free slot left by the cancelled second.
    third = asyncio.create_task(client.get("https://example.test/c"))
    first_response, third_response = await asyncio.gather(first, third)
    assert first_response.status_code == HTTPStatus.OK
    assert third_response.status_code == HTTPStatus.OK
    assert handler.calls == 2  # noqa: PLR2004 — first and third reached handler; second never did


# Constructed at module scope on purpose — pins the construct-outside-loop behavior.
_MODULE_SCOPE_BULKHEAD = AsyncBulkhead(max_concurrent=_MAX_CONCURRENT_1, acquire_timeout=None)


async def test_construct_outside_event_loop_then_use_inside() -> None:
    """AsyncBulkhead constructed at module scope must work when used inside an event loop."""
    handler = _SlowHandler(delay=0.0)
    client = _client(handler, bulkhead=_MODULE_SCOPE_BULKHEAD)
    response = await client.get("https://example.test/x")
    assert response.status_code == HTTPStatus.OK


async def test_shared_bulkhead_enforces_joint_cap() -> None:
    """One AsyncBulkhead shared across two AsyncClients enforces the joint cap."""
    # Both clients use ONE handler that tracks combined in-flight across all calls.
    # asyncio is single-threaded so a plain dict counter is safe between awaits.
    state = {"in_flight": 0, "max_in_flight": 0}

    async def shared_handler(request: httpx2.Request) -> httpx2.Response:
        state["in_flight"] += 1
        state["max_in_flight"] = max(state["max_in_flight"], state["in_flight"])
        try:
            await asyncio.sleep(0.02)
            return httpx2.Response(HTTPStatus.OK, request=request)
        finally:
            state["in_flight"] -= 1

    shared = AsyncBulkhead(max_concurrent=_MAX_CONCURRENT_1, acquire_timeout=None)
    client_a = AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=httpx2.MockTransport(shared_handler)),
        middleware=[shared],
    )
    client_b = AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=httpx2.MockTransport(shared_handler)),
        middleware=[shared],
    )

    await asyncio.gather(
        client_a.get("https://upstream-a.example.test/x"),
        client_a.get("https://upstream-a.example.test/y"),
        client_b.get("https://upstream-b.example.test/x"),
        client_b.get("https://upstream-b.example.test/y"),
    )

    # The shared bulkhead enforces max=1 across BOTH clients combined.
    assert state["max_in_flight"] <= _MAX_CONCURRENT_1


# ----------------------------------------------------------------------------
# AsyncBulkhead + AsyncRetry composition tests
#
# The recommended ordering is [AsyncBulkhead, AsyncRetry] in middleware= — AsyncBulkhead OUTSIDE
# AsyncRetry so a retrying request holds one slot across all attempts (rather than
# re-acquiring per retry). These tests pin the documented composition.
# ----------------------------------------------------------------------------


async def test_bulkhead_outside_retry_holds_one_slot_across_attempts() -> None:
    """[AsyncBulkhead, AsyncRetry]: one slot covers the whole retry sequence, not per-attempt."""
    state = {"in_flight": 0, "max_in_flight": 0}
    call_count = {"n": 0}

    async def handler(request: httpx2.Request) -> httpx2.Response:
        call_count["n"] += 1
        state["in_flight"] += 1
        state["max_in_flight"] = max(state["max_in_flight"], state["in_flight"])
        try:
            # First call returns 503 (retryable); second call returns OK.
            if call_count["n"] == 1:
                return httpx2.Response(HTTPStatus.SERVICE_UNAVAILABLE, request=request)
            return httpx2.Response(HTTPStatus.OK, request=request)
        finally:
            state["in_flight"] -= 1

    transport = httpx2.MockTransport(handler)

    async def _sleep(_: float) -> None:  # don't actually wait between retries
        return

    client = AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=transport),
        middleware=[
            AsyncBulkhead(max_concurrent=_MAX_CONCURRENT_1, acquire_timeout=None),
            AsyncRetry(_sleep=_sleep, base_delay=0.001, max_delay=0.002),
        ],
    )
    response = await client.get("https://example.test/x")
    assert response.status_code == HTTPStatus.OK
    assert call_count["n"] == 2  # noqa: PLR2004 — first 503 + retry success
    # max_in_flight stays at 1: the same AsyncBulkhead slot covers both attempts.
    assert state["max_in_flight"] == 1


async def test_bulkhead_full_error_is_not_retried_by_retry() -> None:
    """AsyncRetry does NOT retry BulkheadFullError — it's neither a StatusError nor a NetworkError/TimeoutError."""
    handler = _SlowHandler(delay=0.5)  # holds the slot indefinitely
    bulkhead = AsyncBulkhead(max_concurrent=_MAX_CONCURRENT_1, acquire_timeout=0)
    transport = httpx2.MockTransport(handler)

    # AsyncMock so the never-called assertion is structural — no user-defined
    # body that would need # pragma: no cover.
    mock_sleep = AsyncMock()

    client = AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=transport),
        middleware=[
            bulkhead,
            AsyncRetry(_sleep=mock_sleep, max_attempts=3, base_delay=0.001, max_delay=0.002),
        ],
    )

    # Fill the slot with a long-lived task.
    first = asyncio.create_task(client.get("https://example.test/holder"))
    await asyncio.sleep(0.01)

    # Second call hits a full AsyncBulkhead. AsyncRetry must NOT swallow + retry it.
    with pytest.raises(BulkheadFullError):
        await client.get("https://example.test/rejected")
    mock_sleep.assert_not_called()  # AsyncRetry never slept — it didn't try to retry

    # Cleanup.
    first.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await first


async def test_bulkhead_rejected_emits_observability_event(caplog: pytest.LogCaptureFixture) -> None:
    """When the bulkhead rejects a request via acquire_timeout, emit one WARNING on httpware.bulkhead."""
    bulkhead = AsyncBulkhead(max_concurrent=1, acquire_timeout=0.0)

    async def slow_handler(request: httpx2.Request) -> httpx2.Response:
        await asyncio.sleep(0.05)
        return httpx2.Response(HTTPStatus.OK, request=request)

    transport = httpx2.MockTransport(slow_handler)
    client = AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=transport),
        middleware=[bulkhead],
    )

    async with client:
        # First request occupies the only slot. Second should be rejected immediately.
        first_task = asyncio.create_task(client.get("https://example.test/x"))
        await asyncio.sleep(0)  # let first_task start and acquire the slot

        with caplog.at_level(logging.WARNING, logger="httpware.bulkhead"), pytest.raises(BulkheadFullError):
            await client.get("https://example.test/y")

        await first_task

    bulkhead_records = [r for r in caplog.records if r.name == "httpware.bulkhead"]
    rejected_records = [r for r in bulkhead_records if "rejected" in r.message]
    assert len(rejected_records) == 1
    record = rejected_records[0]
    assert record.levelno == logging.WARNING
    assert record.max_concurrent == 1  # ty: ignore[unresolved-attribute]
    assert record.acquire_timeout == 0.0  # ty: ignore[unresolved-attribute]
    assert record.method == "GET"  # ty: ignore[unresolved-attribute]
    assert "example.test/y" in record.url  # ty: ignore[unresolved-attribute]


# ───── Single-event-loop guard ──────────────────────────────────────────────


async def test_first_acquire_captures_running_loop() -> None:
    """AsyncBulkhead binds to whichever loop first acquires a slot."""
    bulkhead = AsyncBulkhead(max_concurrent=_MAX_CONCURRENT_1)
    assert bulkhead._loop is None  # noqa: SLF001
    handler = _SlowHandler(delay=0.0)
    async with _client(handler, bulkhead=bulkhead) as client:
        await client.get("https://example.test/x")
    assert bulkhead._loop is asyncio.get_running_loop()  # noqa: SLF001


async def test_same_loop_succeeds_across_multiple_acquires() -> None:
    """Repeated acquires on the same loop never trigger the cross-loop guard."""
    bulkhead = AsyncBulkhead(max_concurrent=_MAX_CONCURRENT_2)
    handler = _SlowHandler(delay=0.0)
    async with _client(handler, bulkhead=bulkhead) as client:
        for _ in range(5):
            response = await client.get("https://example.test/x")
            assert response.status_code == HTTPStatus.OK


def test_cross_loop_acquire_raises_runtimeerror() -> None:
    """A bulkhead first used on one loop, then reused on another, raises RuntimeError.

    Each asyncio.run() call creates a fresh event loop and tears it down on
    exit. Sharing one AsyncBulkhead instance across two asyncio.run() calls
    is the cross-loop case the guard prevents.
    """
    bulkhead = AsyncBulkhead(max_concurrent=_MAX_CONCURRENT_1)
    handler = _SlowHandler(delay=0.0)

    async def _run_once() -> None:
        async with _client(handler, bulkhead=bulkhead) as client:
            await client.get("https://example.test/x")

    asyncio.run(_run_once())  # captures loop L1, then L1 closes
    with pytest.raises(RuntimeError, match="AsyncBulkhead is bound to a single event loop"):
        asyncio.run(_run_once())

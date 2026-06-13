"""Tests for the AsyncCircuitBreaker middleware.

Time is driven by an injected _now (a _Clock); the transport is mocked via
httpx2.MockTransport. 5xx responses surface as StatusError at the client terminal;
httpx2.ConnectError surfaces as NetworkError.
"""

import asyncio
import logging
from collections.abc import Callable
from http import HTTPStatus

import httpx2
import pytest

from httpware import (
    AsyncClient,
    CircuitOpenError,
    InternalServerError,
    NetworkError,
    NotFoundError,
    RateLimitedError,
)
from httpware.middleware.resilience.circuit_breaker import AsyncCircuitBreaker


class _Clock:
    """Manually-advanced monotonic clock for deterministic reset_timeout tests."""

    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


class _StatusSequence:
    """Mock-transport handler returning a fixed sequence of status codes (default 200)."""

    def __init__(self, statuses: list[int]) -> None:
        self._statuses = list(statuses)
        self.calls = 0

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.calls += 1
        status = self._statuses.pop(0) if self._statuses else HTTPStatus.OK
        return httpx2.Response(status, request=request)


def _client(
    handler: Callable[[httpx2.Request], httpx2.Response],
    *,
    breaker: AsyncCircuitBreaker,
) -> AsyncClient:
    return AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
        middleware=[breaker],
    )


# ── construction validation ──


def test_failure_threshold_below_one_rejected() -> None:
    with pytest.raises(ValueError, match="failure_threshold must be >= 1"):
        AsyncCircuitBreaker(failure_threshold=0)


def test_negative_reset_timeout_rejected() -> None:
    with pytest.raises(ValueError, match="reset_timeout must be >= 0"):
        AsyncCircuitBreaker(reset_timeout=-1.0)


def test_success_threshold_below_one_rejected() -> None:
    with pytest.raises(ValueError, match="success_threshold must be >= 1"):
        AsyncCircuitBreaker(success_threshold=0)


# ── closed-state behavior ──


async def test_closed_passes_through() -> None:
    handler = _StatusSequence([HTTPStatus.OK])
    breaker = AsyncCircuitBreaker(failure_threshold=3, _now=_Clock())
    async with _client(handler, breaker=breaker) as client:
        response = await client.get("https://example.test/x")
    assert response.status_code == HTTPStatus.OK
    assert handler.calls == 1


async def test_consecutive_failures_open_the_circuit() -> None:
    handler = _StatusSequence([500, 500, 500])
    breaker = AsyncCircuitBreaker(failure_threshold=3, _now=_Clock())
    async with _client(handler, breaker=breaker) as client:
        for _ in range(3):
            with pytest.raises(InternalServerError):
                await client.get("https://example.test/x")
        with pytest.raises(CircuitOpenError) as info:
            await client.get("https://example.test/x")
    assert handler.calls == 3  # noqa: PLR2004 — 4th was short-circuited
    assert info.value.retry_after is not None
    # (circuit.opened event asserted in test_open_emits_opened_event_and_rejects)


async def test_open_emits_opened_event_and_rejects(caplog: pytest.LogCaptureFixture) -> None:
    handler = _StatusSequence([500, 500])
    breaker = AsyncCircuitBreaker(failure_threshold=2, _now=_Clock())
    async with _client(handler, breaker=breaker) as client:
        with caplog.at_level(logging.WARNING, logger="httpware.circuit_breaker"):
            for _ in range(2):
                with pytest.raises(InternalServerError):
                    await client.get("https://example.test/x")
            with pytest.raises(CircuitOpenError):
                await client.get("https://example.test/y")
    records = [r for r in caplog.records if r.name == "httpware.circuit_breaker"]
    opened = [r for r in records if "opened" in r.message]
    rejected = [r for r in records if "rejecting" in r.message]
    assert len(opened) == 1
    assert opened[0].failure_threshold == 2  # noqa: PLR2004  # ty: ignore[unresolved-attribute]
    assert opened[0].failures == 2  # noqa: PLR2004  # ty: ignore[unresolved-attribute]
    assert len(rejected) == 1
    assert rejected[0].retry_after is not None  # ty: ignore[unresolved-attribute]
    assert rejected[0].method == "GET"  # ty: ignore[unresolved-attribute]


async def test_success_resets_failure_streak() -> None:
    handler = _StatusSequence([500, 500, 200, 500, 500])
    breaker = AsyncCircuitBreaker(failure_threshold=3, _now=_Clock())
    async with _client(handler, breaker=breaker) as client:
        for _ in range(2):
            with pytest.raises(InternalServerError):
                await client.get("https://example.test/x")
        await client.get("https://example.test/x")  # 200 resets the streak
        for _ in range(2):
            with pytest.raises(InternalServerError):
                await client.get("https://example.test/x")
        response = await client.get("https://example.test/x")  # 6th -> default 200
    assert response.status_code == HTTPStatus.OK
    assert handler.calls == 6  # noqa: PLR2004 — 2 failures + 1 success + 2 failures + 1 success


async def test_404_and_429_do_not_count_as_failures() -> None:
    handler = _StatusSequence([404, 429, 404, 429, 404])
    breaker = AsyncCircuitBreaker(failure_threshold=2, _now=_Clock())
    async with _client(handler, breaker=breaker) as client:
        for _ in range(5):
            with pytest.raises((NotFoundError, RateLimitedError)):
                await client.get("https://example.test/x")
    assert handler.calls == 5  # noqa: PLR2004 — never opened, all five reached the transport


async def test_network_error_counts_as_failure() -> None:
    def _raise(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        msg = "connect failed"
        raise httpx2.ConnectError(msg)

    breaker = AsyncCircuitBreaker(failure_threshold=2, _now=_Clock())
    async with _client(_raise, breaker=breaker) as client:
        for _ in range(2):
            with pytest.raises(NetworkError):
                await client.get("https://example.test/x")
        with pytest.raises(CircuitOpenError):
            await client.get("https://example.test/x")


async def test_non_counted_exception_propagates_without_state_change() -> None:
    """A ValueError from inner middleware is neither success nor failure; state unchanged."""

    class _Boom:
        async def __call__(self, request: httpx2.Request, next: object) -> httpx2.Response:  # noqa: A002,ARG002
            msg = "boom"
            raise ValueError(msg)

    handler = _StatusSequence([200])
    breaker = AsyncCircuitBreaker(failure_threshold=1, _now=_Clock())
    client = AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
        middleware=[breaker, _Boom()],
    )
    async with client:
        # failure_threshold=1, but ValueError is never counted -> circuit stays CLOSED.
        # Each call raises ValueError (NOT CircuitOpenError), proving no state change.
        for _ in range(3):
            with pytest.raises(ValueError, match="boom"):
                await client.get("https://example.test/x")


async def test_non_counted_exception_in_probe_releases_slot() -> None:
    """A non-counted exception during the probe releases the probe slot.

    The circuit stays OPEN (probe didn't succeed/fail), and the next request
    after reset_timeout can take the probe slot again.
    """
    clock = _Clock()

    class _Boom:
        async def __call__(self, request: httpx2.Request, next: object) -> httpx2.Response:  # noqa: A002,ARG002
            msg = "boom"
            raise ValueError(msg)

    open_handler = _StatusSequence([500])
    breaker = AsyncCircuitBreaker(failure_threshold=1, reset_timeout=5.0, _now=clock)
    async with _client(open_handler, breaker=breaker) as opener:
        with pytest.raises(InternalServerError):
            await opener.get("https://example.test/x")
    # Circuit is OPEN. Advance time to allow a probe.
    clock.advance(5.0)

    boom_client = AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=httpx2.MockTransport(open_handler)),
        middleware=[breaker, _Boom()],
    )
    async with boom_client:
        # First call after timeout: probe slot taken, but _Boom raises ValueError.
        # release_probe is called, clearing probe_in_flight.
        with pytest.raises(ValueError, match="boom"):
            await boom_client.get("https://example.test/probe")
        # Circuit is still OPEN (probe neither succeeded nor failed).
        # Advance again and try a second probe — this time without the boom middleware.
    # Use a fresh good client to verify the probe slot was released.
    good_handler = _StatusSequence([200])
    good_client = AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=httpx2.MockTransport(good_handler)),
        middleware=[breaker],
    )
    async with good_client:
        # clock hasn't advanced further, but reset_timeout was met earlier.
        # After probe slot was released, admit should allow a new probe.
        response = await good_client.get("https://example.test/x")
    assert response.status_code == HTTPStatus.OK


# ── half-open / reset_timeout ──


async def test_reset_timeout_admits_probe_then_closes(caplog: pytest.LogCaptureFixture) -> None:
    clock = _Clock()
    handler = _StatusSequence([500, 500, 200])  # 2 fails -> open; probe (3rd) -> 200 -> close
    breaker = AsyncCircuitBreaker(failure_threshold=2, reset_timeout=30.0, success_threshold=1, _now=clock)
    async with _client(handler, breaker=breaker) as client:
        for _ in range(2):
            with pytest.raises(InternalServerError):
                await client.get("https://example.test/x")
        with pytest.raises(CircuitOpenError):  # OPEN, before reset_timeout -> rejected
            await client.get("https://example.test/x")
        assert handler.calls == 2  # noqa: PLR2004 — 2 failures, 3rd rejected
        clock.advance(30.0)
        with caplog.at_level(logging.INFO, logger="httpware.circuit_breaker"):
            response = await client.get("https://example.test/x")  # probe -> 200 -> CLOSED
    assert response.status_code == HTTPStatus.OK
    assert handler.calls == 3  # noqa: PLR2004 — 2 failures + 1 probe
    messages = [r.message for r in caplog.records if r.name == "httpware.circuit_breaker"]
    assert any("half-open" in m for m in messages)
    assert any("closed" in m for m in messages)


async def test_probe_failure_reopens_circuit() -> None:
    clock = _Clock()
    handler = _StatusSequence([500, 500, 500])  # open after 2; probe (3rd) fails -> reopen
    breaker = AsyncCircuitBreaker(failure_threshold=2, reset_timeout=10.0, _now=clock)
    async with _client(handler, breaker=breaker) as client:
        for _ in range(2):
            with pytest.raises(InternalServerError):
                await client.get("https://example.test/x")
        clock.advance(10.0)
        with pytest.raises(InternalServerError):  # probe runs, fails
            await client.get("https://example.test/x")
        with pytest.raises(CircuitOpenError):  # reopened; immediate retry rejected
            await client.get("https://example.test/x")
    assert handler.calls == 3  # noqa: PLR2004 — 2 failures + 1 probe-failure


async def test_success_threshold_requires_multiple_probes() -> None:
    clock = _Clock()
    handler = _StatusSequence([500, 500, 200, 200])  # open; then 2 successful probes to close
    breaker = AsyncCircuitBreaker(failure_threshold=2, reset_timeout=5.0, success_threshold=2, _now=clock)
    async with _client(handler, breaker=breaker) as client:
        for _ in range(2):
            with pytest.raises(InternalServerError):
                await client.get("https://example.test/x")
        clock.advance(5.0)
        await client.get("https://example.test/x")  # probe 1 -> 200 (still HALF_OPEN, 1/2)
        await client.get("https://example.test/x")  # probe 2 -> 200 -> CLOSED
        response = await client.get("https://example.test/x")  # default 200, CLOSED
    assert response.status_code == HTTPStatus.OK
    assert handler.calls == 5  # noqa: PLR2004 — 2 failures + 2 probes + 1 closed call


async def test_half_open_second_concurrent_request_rejected_with_none_retry_after() -> None:
    """While the single probe is in flight, a concurrent request fast-fails (retry_after=None)."""
    clock = _Clock()
    probe_started = asyncio.Event()
    release_probe = asyncio.Event()

    async def _handler_async(request: httpx2.Request) -> httpx2.Response:
        probe_started.set()
        await release_probe.wait()
        return httpx2.Response(HTTPStatus.OK, request=request)

    breaker = AsyncCircuitBreaker(failure_threshold=1, reset_timeout=1.0, _now=clock)
    open_handler = _StatusSequence([500])
    async with _client(open_handler, breaker=breaker) as opener:
        with pytest.raises(InternalServerError):
            await opener.get("https://example.test/x")
    clock.advance(1.0)

    client = AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=httpx2.MockTransport(_handler_async)),
        middleware=[breaker],
    )
    async with client:
        probe_task = asyncio.create_task(client.get("https://example.test/probe"))
        await probe_started.wait()  # probe in flight, HALF_OPEN
        with pytest.raises(CircuitOpenError) as info:
            await client.get("https://example.test/concurrent")
        assert info.value.retry_after is None
        release_probe.set()
        await probe_task


# ── single-event-loop guard ──


def test_cross_loop_use_raises_runtimeerror() -> None:
    breaker = AsyncCircuitBreaker(_now=_Clock())
    handler = _StatusSequence([200])

    async def _run_once() -> None:
        async with _client(handler, breaker=breaker) as client:
            await client.get("https://example.test/x")

    asyncio.run(_run_once())  # binds to loop L1
    with pytest.raises(RuntimeError, match="bound to a single event loop"):
        asyncio.run(_run_once())

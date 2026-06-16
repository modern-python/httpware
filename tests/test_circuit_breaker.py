"""Tests for the AsyncCircuitBreaker middleware.

Time is driven by an injected _now (a _Clock); the transport is mocked via
httpx2.MockTransport. 5xx responses surface as StatusError at the client terminal;
httpx2.ConnectError surfaces as NetworkError.
"""

import asyncio
import contextlib
import logging
import re
from collections.abc import Callable
from http import HTTPStatus

import httpx2
import pytest

from httpware import (
    AsyncClient,
    CircuitOpenError,
    CircuitState,
    InternalServerError,
    NetworkError,
    NotFoundError,
    RateLimitedError,
    ServiceUnavailableError,
    TimeoutError,  # noqa: A004 — intentional: httpware.TimeoutError shadows the builtin
)
from httpware.middleware.resilience.circuit_breaker import (
    _FAILURE_RATE_THRESHOLD_INVALID,
    _MINIMUM_CALLS_INVALID,
    _WINDOW_SECONDS_INVALID,
    AsyncCircuitBreaker,
)


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
    assert opened[0].event == "circuit.opened"  # ty: ignore[unresolved-attribute]
    assert opened[0].failure_threshold == 2  # noqa: PLR2004  # ty: ignore[unresolved-attribute]
    assert opened[0].failures == 2  # noqa: PLR2004  # ty: ignore[unresolved-attribute]
    assert len(rejected) == 1
    assert rejected[0].event == "circuit.rejected"  # ty: ignore[unresolved-attribute]
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


async def test_timeout_error_counts_as_failure() -> None:
    def _raise(request: httpx2.Request) -> httpx2.Response:
        msg = "read timed out"
        raise httpx2.ReadTimeout(msg, request=request)

    breaker = AsyncCircuitBreaker(failure_threshold=2, _now=_Clock())
    async with _client(_raise, breaker=breaker) as client:
        for _ in range(2):
            with pytest.raises(TimeoutError):
                await client.get("https://example.test/x")
        with pytest.raises(CircuitOpenError):
            await client.get("https://example.test/x")


async def test_custom_failure_status_codes_trips_on_member() -> None:
    """A status code in a custom failure set trips the breaker (plain set accepted)."""
    handler = _StatusSequence([503, 503])
    breaker = AsyncCircuitBreaker(
        failure_threshold=2,
        failure_status_codes={503},  # a plain set — any Collection[int] is accepted
        _now=_Clock(),
    )
    async with _client(handler, breaker=breaker) as client:
        for _ in range(2):
            with pytest.raises(ServiceUnavailableError):
                await client.get("https://example.test/x")
        with pytest.raises(CircuitOpenError):
            await client.get("https://example.test/x")
    assert handler.calls == 2  # noqa: PLR2004


async def test_custom_failure_status_codes_excludes_other_5xx() -> None:
    """With a custom set of {503}, a 500 response is NOT a failure — it counts as success."""
    handler = _StatusSequence([500, 500, 500, 500])
    breaker = AsyncCircuitBreaker(
        failure_threshold=2,
        failure_status_codes=[503],  # a list, too — frozen internally
        _now=_Clock(),
    )
    async with _client(handler, breaker=breaker) as client:
        for _ in range(4):
            with pytest.raises(InternalServerError):
                await client.get("https://example.test/x")
    assert handler.calls == 4  # noqa: PLR2004  # 500 not in custom set -> never opened


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
    records = [r for r in caplog.records if r.name == "httpware.circuit_breaker"]
    assert any(r.event == "circuit.half_open" for r in records)  # ty: ignore[unresolved-attribute]
    assert any(r.event == "circuit.closed" for r in records)  # ty: ignore[unresolved-attribute]
    messages = [r.message for r in records]
    assert any("half-open" in m for m in messages)
    assert any("closed" in m for m in messages)


async def test_probe_failure_reopens_circuit(caplog: pytest.LogCaptureFixture) -> None:
    clock = _Clock()
    handler = _StatusSequence([500, 500, 500])  # open after 2; probe (3rd) fails -> reopen
    breaker = AsyncCircuitBreaker(failure_threshold=2, reset_timeout=10.0, _now=clock)
    async with _client(handler, breaker=breaker) as client:
        with caplog.at_level(logging.WARNING, logger="httpware.circuit_breaker"):
            for _ in range(2):
                with pytest.raises(InternalServerError):
                    await client.get("https://example.test/x")
            clock.advance(10.0)
            with pytest.raises(InternalServerError):  # probe runs, fails
                await client.get("https://example.test/x")
            with pytest.raises(CircuitOpenError):  # reopened; immediate retry rejected
                await client.get("https://example.test/x")
    assert handler.calls == 3  # noqa: PLR2004 — 2 failures + 1 probe-failure
    # Probe failure emits circuit.opened with failures=1 (the single probe that reopened it).
    reopen_records = [
        r
        for r in caplog.records
        if r.name == "httpware.circuit_breaker"
        and r.event == "circuit.opened"  # ty: ignore[unresolved-attribute]
        and r.failures == 1  # ty: ignore[unresolved-attribute]
    ]
    assert len(reopen_records) == 1


async def test_open_reject_retry_after_value() -> None:
    """retry_after is exactly reset_timeout - elapsed (not just non-None)."""
    clock = _Clock()
    handler = _StatusSequence([500, 500])
    breaker = AsyncCircuitBreaker(failure_threshold=2, reset_timeout=30.0, _now=clock)
    async with _client(handler, breaker=breaker) as client:
        for _ in range(2):
            with pytest.raises(InternalServerError):
                await client.get("https://example.test/x")
        clock.advance(10.0)  # 10s into a 30s open window
        with pytest.raises(CircuitOpenError) as info:
            await client.get("https://example.test/x")
    assert info.value.retry_after == 20.0  # noqa: PLR2004  # 30 - 10, exact
    # The max(0.0, …) floor is only reachable if elapsed > reset_timeout while still
    # OPEN, but the lazy OPEN→HALF_OPEN transition in admit() fires as soon as
    # elapsed >= reset_timeout — so the circuit is never both OPEN and elapsed >
    # reset_timeout.  The floor is defensive dead code; no separate floor test needed.


async def test_429_resets_failure_streak() -> None:
    """A 429 response is treated as success, resetting the failure streak."""
    handler = _StatusSequence([500, 429, 500, 500])
    breaker = AsyncCircuitBreaker(failure_threshold=2, _now=_Clock())
    async with _client(handler, breaker=breaker) as client:
        with pytest.raises(InternalServerError):
            await client.get("https://example.test/x")  # streak=1
        with pytest.raises(RateLimitedError):
            await client.get("https://example.test/x")  # 429 -> success, resets streak to 0
        with pytest.raises(InternalServerError):
            await client.get("https://example.test/x")  # streak=1 again
        with pytest.raises(InternalServerError):
            await client.get("https://example.test/x")  # streak=2 -> opens
    assert handler.calls == 4  # noqa: PLR2004  # all four reached the transport; never short-circuited


async def test_success_threshold_probe_failure_mid_streak_reopens() -> None:
    """A probe failure mid-streak resets consecutive_successes — the next close needs two FRESH successes.

    Discriminating: if the success counter were NOT reset on reopen, the circuit would
    close after a single post-reopen success and the final request would reach the
    transport instead of being rejected.
    """
    clock = _Clock()
    # 2x500 open; probe-1=200 (s=1); probe-2=500 (reopen, s->0); probe-3=200 (s=1, NOT 2);
    # probe-4=500 -> half-open probe failure -> reopen -> next request rejected.
    handler = _StatusSequence([500, 500, 200, 500, 200, 500])
    breaker = AsyncCircuitBreaker(failure_threshold=2, success_threshold=2, reset_timeout=5.0, _now=clock)
    async with _client(handler, breaker=breaker) as client:
        for _ in range(2):
            with pytest.raises(InternalServerError):
                await client.get("https://example.test/x")
        clock.advance(5.0)
        await client.get("https://example.test/x")  # probe-1: 200 -> HALF_OPEN s=1
        with pytest.raises(InternalServerError):  # probe-2: 500 -> reopen, s reset to 0
            await client.get("https://example.test/x")
        clock.advance(5.0)
        await client.get("https://example.test/x")  # probe-3: 200 -> s=1 (would be 2->CLOSED if not reset)
        with pytest.raises(InternalServerError):  # probe-4: 500 -> half-open probe failure -> reopen
            await client.get("https://example.test/x")
        # OPEN now (no clock advance): a missing-reset bug would have CLOSED the circuit
        # after probe-3, so this request would reach the transport instead of being rejected.
        with pytest.raises(CircuitOpenError):
            await client.get("https://example.test/x")
    assert handler.calls == 6  # noqa: PLR2004  # the final request was short-circuited (not the 7th transport hit)


async def test_reset_timeout_zero_admits_probe_immediately() -> None:
    """With reset_timeout=0, the circuit admits a probe immediately (elapsed >= 0 always)."""
    handler = _StatusSequence([500, 200])
    breaker = AsyncCircuitBreaker(failure_threshold=1, reset_timeout=0.0, _now=_Clock())
    async with _client(handler, breaker=breaker) as client:
        with pytest.raises(InternalServerError):
            await client.get("https://example.test/x")  # opens
        # No clock advance needed — reset_timeout=0, so elapsed >= 0 is immediately true.
        response = await client.get("https://example.test/x")  # admitted as probe
    assert response.status_code == HTTPStatus.OK
    assert handler.calls == 2  # noqa: PLR2004  # both reached the transport


async def test_empty_failure_status_codes_ignores_5xx_trips_on_network_error() -> None:
    """With failure_status_codes=[], no status ever counts; only NetworkError trips the breaker."""
    handler = _StatusSequence([500, 500, 500])
    breaker = AsyncCircuitBreaker(failure_threshold=2, failure_status_codes=[], _now=_Clock())
    async with _client(handler, breaker=breaker) as client:
        for _ in range(3):
            with pytest.raises(InternalServerError):
                await client.get("https://example.test/x")
    assert handler.calls == 3  # noqa: PLR2004  # never opened — 500 not in empty set

    def _raise(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        msg = "connect failed"
        raise httpx2.ConnectError(msg)

    breaker2 = AsyncCircuitBreaker(failure_threshold=2, failure_status_codes=[], _now=_Clock())
    async with AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=httpx2.MockTransport(_raise)),
        middleware=[breaker2],
    ) as client2:
        for _ in range(2):
            with pytest.raises(NetworkError):
                await client2.get("https://example.test/x")
        with pytest.raises(CircuitOpenError):
            await client2.get("https://example.test/x")


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


# ── rate-mode config validation ──


@pytest.mark.parametrize("bad", [0.0, -0.1, 1.5])
def test_rate_threshold_out_of_range_raises(bad: float) -> None:
    with pytest.raises(ValueError, match=re.escape(_FAILURE_RATE_THRESHOLD_INVALID)):
        AsyncCircuitBreaker(failure_rate_threshold=bad)


def test_non_positive_window_seconds_raises() -> None:
    with pytest.raises(ValueError, match=re.escape(_WINDOW_SECONDS_INVALID)):
        AsyncCircuitBreaker(failure_rate_threshold=0.5, window_seconds=0.0)


def test_minimum_calls_below_one_raises() -> None:
    with pytest.raises(ValueError, match=re.escape(_MINIMUM_CALLS_INVALID)):
        AsyncCircuitBreaker(failure_rate_threshold=0.5, minimum_calls=0)


def test_classic_mode_is_default_when_rate_threshold_none() -> None:
    breaker = AsyncCircuitBreaker()  # no failure_rate_threshold
    assert breaker._state._rate_mode is False  # noqa: SLF001 — white-box assertion for internal mode flag


# ── rate-mode trip behavior ──


async def test_rate_mode_trips_on_partial_failure() -> None:
    """Alternating 50% failures trip rate mode (classic never would)."""
    clock = _Clock()
    breaker = AsyncCircuitBreaker(failure_rate_threshold=0.5, window_seconds=100.0, minimum_calls=10, _now=clock)
    handler = _StatusSequence([500, 200, 500, 200, 500, 200, 500, 200, 500, 200])
    client = _client(handler, breaker=breaker)
    for _ in range(10):
        with contextlib.suppress(InternalServerError):
            await client.get("https://example.test/x")
    with pytest.raises(CircuitOpenError):
        await client.get("https://example.test/x")


async def test_rate_mode_does_not_trip_below_minimum_calls() -> None:
    clock = _Clock()
    breaker = AsyncCircuitBreaker(failure_rate_threshold=0.5, window_seconds=100.0, minimum_calls=10, _now=clock)
    handler = _StatusSequence([500, 500, 500])  # 3 failures, below floor of 10
    client = _client(handler, breaker=breaker)
    for _ in range(3):
        with pytest.raises(InternalServerError):
            await client.get("https://example.test/x")
    handler_ok = _StatusSequence([200])
    client_ok = _client(handler_ok, breaker=breaker)
    assert (await client_ok.get("https://example.test/x")).status_code == HTTPStatus.OK


async def test_rate_mode_evicts_old_failures() -> None:
    clock = _Clock()
    breaker = AsyncCircuitBreaker(failure_rate_threshold=0.5, window_seconds=10.0, minimum_calls=4, _now=clock)
    fail = _client(_StatusSequence([500, 500, 500, 500, 500, 500, 500, 500]), breaker=breaker)
    for _ in range(3):
        with pytest.raises(InternalServerError):
            await fail.get("https://example.test/x")
    clock.advance(20.0)  # push them fully out of the 10s window
    with pytest.raises(InternalServerError):
        await fail.get("https://example.test/x")
    ok = _client(_StatusSequence([200]), breaker=breaker)
    assert (await ok.get("https://example.test/x")).status_code == HTTPStatus.OK


async def test_rate_mode_clears_window_on_close() -> None:
    """Closing from HALF_OPEN in rate mode clears the window — recovery starts fresh.

    Discriminating: without the clear, the pre-open failures would still be inside the
    window after recovery and a single post-close failure would re-cross the rate
    threshold immediately. With the clear, the post-close failure is below minimum_calls
    again, so the circuit stays CLOSED.
    """
    clock = _Clock()
    breaker = AsyncCircuitBreaker(
        failure_rate_threshold=0.5,
        window_seconds=100.0,
        minimum_calls=2,
        reset_timeout=5.0,
        success_threshold=1,
        _now=clock,
    )
    open_client = _client(_StatusSequence([500, 500]), breaker=breaker)
    for _ in range(2):
        with pytest.raises(InternalServerError):
            await open_client.get("https://example.test/x")
    with pytest.raises(CircuitOpenError):  # 2/2 failures >= 0.5 -> OPEN
        await open_client.get("https://example.test/x")
    clock.advance(5.0)
    probe_client = _client(_StatusSequence([200]), breaker=breaker)
    await probe_client.get("https://example.test/x")  # probe 200 -> CLOSED, window cleared
    # One fresh failure: total=1 < minimum_calls=2, so the circuit stays CLOSED.
    fail_client = _client(_StatusSequence([500]), breaker=breaker)
    with pytest.raises(InternalServerError):
        await fail_client.get("https://example.test/x")
    ok_client = _client(_StatusSequence([200]), breaker=breaker)
    assert (await ok_client.get("https://example.test/x")).status_code == HTTPStatus.OK


async def test_rate_mode_open_event_carries_rate_attributes(caplog: pytest.LogCaptureFixture) -> None:
    """circuit.opened in rate mode carries rate attributes, not the classic ones."""
    clock = _Clock()
    breaker = AsyncCircuitBreaker(failure_rate_threshold=0.5, window_seconds=100.0, minimum_calls=4, _now=clock)
    # 2 failures then 2 successes → total 4 (meets minimum_calls), rate 2/4 = 0.5 → opens
    client = _client(_StatusSequence([500, 500, 200, 200]), breaker=breaker)
    with caplog.at_level(logging.WARNING, logger="httpware.circuit_breaker"):
        for _ in range(2):
            with pytest.raises(InternalServerError):
                await client.get("https://example.test/x")
        for _ in range(2):
            await client.get("https://example.test/x")
    opened = [r for r in caplog.records if r.event == "circuit.opened"]  # ty: ignore[unresolved-attribute]
    assert opened, "expected a circuit.opened record"
    rec = opened[-1]
    assert rec.failure_rate_threshold == 0.5  # noqa: PLR2004  # ty: ignore[unresolved-attribute]
    assert rec.observed_calls >= 4  # noqa: PLR2004  # ty: ignore[unresolved-attribute]
    assert hasattr(rec, "failure_rate")
    assert not hasattr(rec, "failure_threshold")  # classic attribute absent in rate mode


# ── state property ──


async def test_state_closed_open_and_raw_read_caveat() -> None:
    clock = _Clock()
    breaker = AsyncCircuitBreaker(failure_threshold=2, reset_timeout=10.0, success_threshold=1, _now=clock)
    assert breaker.state is CircuitState.CLOSED
    client = _client(_StatusSequence([500, 500]), breaker=breaker)
    for _ in range(2):
        with pytest.raises(InternalServerError):
            await client.get("https://example.test/x")
    assert breaker.state is CircuitState.OPEN
    # raw-read caveat: reset_timeout elapses but NO request is made → still OPEN
    clock.advance(10.0)
    assert breaker.state is CircuitState.OPEN
    # the next request is admitted as the probe and (success_threshold=1) closes the circuit
    ok = _client(_StatusSequence([200]), breaker=breaker)
    assert (await ok.get("https://example.test/x")).status_code == HTTPStatus.OK
    assert breaker.state is CircuitState.CLOSED


async def test_state_half_open_while_probing() -> None:
    clock = _Clock()
    breaker = AsyncCircuitBreaker(failure_threshold=1, reset_timeout=5.0, success_threshold=2, _now=clock)
    fail = _client(_StatusSequence([500]), breaker=breaker)
    with pytest.raises(InternalServerError):
        await fail.get("https://example.test/x")
    assert breaker.state is CircuitState.OPEN
    clock.advance(5.0)
    ok = _client(_StatusSequence([200, 200]), breaker=breaker)
    await ok.get("https://example.test/x")  # admitted as probe; 1 success, needs 2 → HALF_OPEN
    assert breaker.state is CircuitState.HALF_OPEN
    await ok.get("https://example.test/x")  # 2nd consecutive success → CLOSED
    assert breaker.state is CircuitState.CLOSED

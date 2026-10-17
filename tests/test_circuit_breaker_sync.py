"""Tests for the sync CircuitBreaker middleware (mirror of AsyncCircuitBreaker)."""

import contextlib
import logging
import threading
from collections.abc import Callable
from http import HTTPStatus

import httpx2
import pytest

from httpware import (
    CircuitOpenError,
    CircuitState,
    Client,
    ClientError,
    InternalServerError,
    NetworkError,
    NotFoundError,
    RateLimitedError,
    Retry,
    RetryBudget,
    RetryBudgetExhaustedError,
    ServiceUnavailableError,
    TimeoutError,  # noqa: A004 — intentional: httpware.TimeoutError shadows the builtin
)
from httpware.middleware.resilience.circuit_breaker import CircuitBreaker


class _Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


class _StatusSequence:
    def __init__(self, statuses: list[int]) -> None:
        self._statuses = list(statuses)
        self.calls = 0

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.calls += 1
        status = self._statuses.pop(0) if self._statuses else HTTPStatus.OK
        return httpx2.Response(status, request=request)


def _client(handler: Callable[[httpx2.Request], httpx2.Response], *, breaker: CircuitBreaker) -> Client:
    return Client(
        httpx2_client=httpx2.Client(transport=httpx2.MockTransport(handler)),
        middleware=[breaker],
    )


def test_failure_threshold_below_one_rejected() -> None:
    with pytest.raises(ValueError, match="failure_threshold must be >= 1"):
        CircuitBreaker(failure_threshold=0)


def test_negative_reset_timeout_rejected() -> None:
    with pytest.raises(ValueError, match="reset_timeout must be >= 0"):
        CircuitBreaker(reset_timeout=-1.0)


def test_success_threshold_below_one_rejected() -> None:
    with pytest.raises(ValueError, match="success_threshold must be >= 1"):
        CircuitBreaker(success_threshold=0)


def test_closed_passes_through() -> None:
    handler = _StatusSequence([HTTPStatus.OK])
    breaker = CircuitBreaker(failure_threshold=3, _now=_Clock())
    with _client(handler, breaker=breaker) as client:
        response = client.get("https://example.test/x")
    assert response.status_code == HTTPStatus.OK
    assert handler.calls == 1


def test_open_emits_opened_event_and_rejects(caplog: pytest.LogCaptureFixture) -> None:
    handler = _StatusSequence([500, 500])
    breaker = CircuitBreaker(failure_threshold=2, _now=_Clock())
    with (
        _client(handler, breaker=breaker) as client,
        caplog.at_level(logging.WARNING, logger="httpware.circuit_breaker"),
    ):
        for _ in range(2):
            with pytest.raises(InternalServerError):
                client.get("https://example.test/x")
        with pytest.raises(CircuitOpenError) as info:
            client.get("https://example.test/y")
    assert info.value.retry_after is not None
    assert handler.calls == 2  # noqa: PLR2004
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


def test_success_resets_failure_streak() -> None:
    handler = _StatusSequence([500, 500, 200, 500, 500])
    breaker = CircuitBreaker(failure_threshold=3, _now=_Clock())
    with _client(handler, breaker=breaker) as client:
        for _ in range(2):
            with pytest.raises(InternalServerError):
                client.get("https://example.test/x")
        client.get("https://example.test/x")
        for _ in range(2):
            with pytest.raises(InternalServerError):
                client.get("https://example.test/x")
        response = client.get("https://example.test/x")
    assert response.status_code == HTTPStatus.OK
    assert handler.calls == 6  # noqa: PLR2004 — 2 failures + 1 success + 2 failures + 1 success


def test_404_and_429_do_not_count_as_failures() -> None:
    handler = _StatusSequence([404, 429, 404, 429, 404])
    breaker = CircuitBreaker(failure_threshold=2, _now=_Clock())
    with _client(handler, breaker=breaker) as client:
        for _ in range(5):
            with pytest.raises((NotFoundError, RateLimitedError)):
                client.get("https://example.test/x")
    assert handler.calls == 5  # noqa: PLR2004 — never opened, all five reached the transport


def test_network_error_counts_as_failure() -> None:
    def _raise(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        msg = "connect failed"
        raise httpx2.ConnectError(msg)

    breaker = CircuitBreaker(failure_threshold=2, _now=_Clock())
    with _client(_raise, breaker=breaker) as client:
        for _ in range(2):
            with pytest.raises(NetworkError):
                client.get("https://example.test/x")
        with pytest.raises(CircuitOpenError):
            client.get("https://example.test/x")


def test_timeout_error_counts_as_failure() -> None:
    def _raise(request: httpx2.Request) -> httpx2.Response:
        msg = "read timed out"
        raise httpx2.ReadTimeout(msg, request=request)

    breaker = CircuitBreaker(failure_threshold=2, _now=_Clock())
    with _client(_raise, breaker=breaker) as client:
        for _ in range(2):
            with pytest.raises(TimeoutError):
                client.get("https://example.test/x")
        with pytest.raises(CircuitOpenError):
            client.get("https://example.test/x")


def test_custom_failure_status_codes_trips_on_member() -> None:
    handler = _StatusSequence([503, 503])
    breaker = CircuitBreaker(failure_threshold=2, failure_status_codes={503}, _now=_Clock())  # plain set accepted
    with _client(handler, breaker=breaker) as client:
        for _ in range(2):
            with pytest.raises(ServiceUnavailableError):
                client.get("https://example.test/x")
        with pytest.raises(CircuitOpenError):
            client.get("https://example.test/x")
    assert handler.calls == 2  # noqa: PLR2004


def test_custom_failure_status_codes_excludes_other_5xx() -> None:
    handler = _StatusSequence([500, 500, 500, 500])
    breaker = CircuitBreaker(failure_threshold=2, failure_status_codes=[503], _now=_Clock())  # list accepted too
    with _client(handler, breaker=breaker) as client:
        for _ in range(4):
            with pytest.raises(InternalServerError):
                client.get("https://example.test/x")
    assert handler.calls == 4  # noqa: PLR2004  # 500 not in custom set -> never opened


def test_non_counted_exception_propagates_without_state_change() -> None:
    class _Boom:
        def __call__(self, request: httpx2.Request, next: object) -> httpx2.Response:  # noqa: A002,ARG002
            msg = "boom"
            raise ValueError(msg)

    handler = _StatusSequence([200])
    breaker = CircuitBreaker(failure_threshold=1, _now=_Clock())
    client = Client(
        httpx2_client=httpx2.Client(transport=httpx2.MockTransport(handler)),
        middleware=[breaker, _Boom()],
    )
    with client:
        for _ in range(3):
            with pytest.raises(ValueError, match="boom"):
                client.get("https://example.test/x")


def test_reset_timeout_admits_probe_then_closes(caplog: pytest.LogCaptureFixture) -> None:
    clock = _Clock()
    handler = _StatusSequence([500, 500, 200])
    breaker = CircuitBreaker(failure_threshold=2, reset_timeout=30.0, success_threshold=1, _now=clock)
    with _client(handler, breaker=breaker) as client:
        for _ in range(2):
            with pytest.raises(InternalServerError):
                client.get("https://example.test/x")
        with pytest.raises(CircuitOpenError):
            client.get("https://example.test/x")
        assert handler.calls == 2  # noqa: PLR2004
        clock.advance(30.0)
        with caplog.at_level(logging.INFO, logger="httpware.circuit_breaker"):
            response = client.get("https://example.test/x")
    assert response.status_code == HTTPStatus.OK
    assert handler.calls == 3  # noqa: PLR2004
    records = [r for r in caplog.records if r.name == "httpware.circuit_breaker"]
    assert any(r.event == "circuit.half_open" for r in records)
    assert any(r.event == "circuit.closed" for r in records)
    messages = [r.message for r in records]
    assert any("half-open" in m for m in messages)
    assert any("closed" in m for m in messages)


def test_probe_failure_reopens_circuit(caplog: pytest.LogCaptureFixture) -> None:
    clock = _Clock()
    handler = _StatusSequence([500, 500, 500])
    breaker = CircuitBreaker(failure_threshold=2, reset_timeout=10.0, _now=clock)
    with (
        _client(handler, breaker=breaker) as client,
        caplog.at_level(logging.WARNING, logger="httpware.circuit_breaker"),
    ):
        for _ in range(2):
            with pytest.raises(InternalServerError):
                client.get("https://example.test/x")
        clock.advance(10.0)
        with pytest.raises(InternalServerError):
            client.get("https://example.test/x")
        with pytest.raises(CircuitOpenError):
            client.get("https://example.test/x")
    assert handler.calls == 3  # noqa: PLR2004
    # Probe failure emits circuit.opened with failures=1 (the single probe that reopened it).
    reopen_records = [
        r
        for r in caplog.records
        if r.name == "httpware.circuit_breaker"
        and r.event == "circuit.opened"  # ty: ignore[unresolved-attribute]
        and r.failures == 1  # ty: ignore[unresolved-attribute]
    ]
    assert len(reopen_records) == 1


def test_open_reject_retry_after_value() -> None:
    """retry_after is exactly reset_timeout - elapsed (not just non-None)."""
    clock = _Clock()
    handler = _StatusSequence([500, 500])
    breaker = CircuitBreaker(failure_threshold=2, reset_timeout=30.0, _now=clock)
    with _client(handler, breaker=breaker) as client:
        for _ in range(2):
            with pytest.raises(InternalServerError):
                client.get("https://example.test/x")
        clock.advance(10.0)  # 10s into a 30s open window
        with pytest.raises(CircuitOpenError) as info:
            client.get("https://example.test/x")
    assert info.value.retry_after == 20.0  # noqa: PLR2004  # 30 - 10, exact
    # The max(0.0, …) floor is only reachable if elapsed > reset_timeout while still
    # OPEN, but the lazy OPEN→HALF_OPEN transition fires as soon as elapsed >= reset_timeout.
    # The floor is defensive dead code; no separate floor test needed.


def test_429_resets_failure_streak() -> None:
    """A 429 response is treated as success, resetting the failure streak."""
    handler = _StatusSequence([500, 429, 500, 500])
    breaker = CircuitBreaker(failure_threshold=2, _now=_Clock())
    with _client(handler, breaker=breaker) as client:
        with pytest.raises(InternalServerError):
            client.get("https://example.test/x")  # streak=1
        with pytest.raises(RateLimitedError):
            client.get("https://example.test/x")  # 429 -> success, resets streak to 0
        with pytest.raises(InternalServerError):
            client.get("https://example.test/x")  # streak=1 again
        with pytest.raises(InternalServerError):
            client.get("https://example.test/x")  # streak=2 -> opens
    assert handler.calls == 4  # noqa: PLR2004  # all four reached the transport; never short-circuited


def test_non_counted_exception_in_probe_releases_slot() -> None:
    """A non-counted exception during the probe releases the probe slot (sync mirror).

    The circuit stays OPEN (probe neither succeeded nor failed), and the next request
    after reset_timeout can take the probe slot again.
    """
    clock = _Clock()

    class _Boom:
        def __call__(self, request: httpx2.Request, next: object) -> httpx2.Response:  # noqa: A002,ARG002
            msg = "boom"
            raise ValueError(msg)

    open_handler = _StatusSequence([500])
    breaker = CircuitBreaker(failure_threshold=1, reset_timeout=5.0, _now=clock)
    with _client(open_handler, breaker=breaker) as opener, pytest.raises(InternalServerError):
        opener.get("https://example.test/x")
    # Circuit is OPEN. Advance time to allow a probe.
    clock.advance(5.0)

    boom_client = Client(
        httpx2_client=httpx2.Client(transport=httpx2.MockTransport(open_handler)),
        middleware=[breaker, _Boom()],
    )
    with boom_client, pytest.raises(ValueError, match="boom"):
        # Probe slot taken, but _Boom raises ValueError — probe slot must be released.
        boom_client.get("https://example.test/probe")

    # After the ValueError, probe_in_flight is False again. The next request should
    # be admitted as a new probe (not rejected with retry_after=None).
    good_handler = _StatusSequence([200])
    good_client = Client(
        httpx2_client=httpx2.Client(transport=httpx2.MockTransport(good_handler)),
        middleware=[breaker],
    )
    with good_client:
        response = good_client.get("https://example.test/x")
    assert response.status_code == HTTPStatus.OK


def test_success_threshold_probe_failure_mid_streak_reopens() -> None:
    """A probe failure mid-streak resets consecutive_successes — the next close needs two FRESH successes.

    Discriminating: if the success counter were NOT reset on reopen, the circuit would
    close after a single post-reopen success and the final request would reach the
    transport instead of being rejected.
    """
    clock = _Clock()
    # 2x500 open; probe-1=200 (s=1); probe-2=500 (reopen, s->0); probe-3=200 (s=1, NOT 2);
    # probe-4=500 -> half-open probe failure -> reopen -> next request rejected.
    handler = _StatusSequence([500, 500, 200, 500, 200, 500])
    breaker = CircuitBreaker(failure_threshold=2, success_threshold=2, reset_timeout=5.0, _now=clock)
    with _client(handler, breaker=breaker) as client:
        for _ in range(2):
            with pytest.raises(InternalServerError):
                client.get("https://example.test/x")
        clock.advance(5.0)
        client.get("https://example.test/x")  # probe-1: 200 -> HALF_OPEN s=1
        with pytest.raises(InternalServerError):  # probe-2: 500 -> reopen, s reset to 0
            client.get("https://example.test/x")
        clock.advance(5.0)
        client.get("https://example.test/x")  # probe-3: 200 -> s=1 (would be 2->CLOSED if not reset)
        with pytest.raises(InternalServerError):  # probe-4: 500 -> half-open probe failure -> reopen
            client.get("https://example.test/x")
        # OPEN now (no clock advance): a missing-reset bug would have CLOSED the circuit
        # after probe-3, so this request would reach the transport instead of being rejected.
        with pytest.raises(CircuitOpenError):
            client.get("https://example.test/x")
    assert handler.calls == 6  # noqa: PLR2004  # the final request was short-circuited (not the 7th transport hit)


def test_reset_timeout_zero_admits_probe_immediately() -> None:
    """With reset_timeout=0, the circuit admits a probe immediately (elapsed >= 0 always)."""
    handler = _StatusSequence([500, 200])
    breaker = CircuitBreaker(failure_threshold=1, reset_timeout=0.0, _now=_Clock())
    with _client(handler, breaker=breaker) as client:
        with pytest.raises(InternalServerError):
            client.get("https://example.test/x")  # opens
        # No clock advance needed — reset_timeout=0, so elapsed >= 0 is immediately true.
        response = client.get("https://example.test/x")  # admitted as probe
    assert response.status_code == HTTPStatus.OK
    assert handler.calls == 2  # noqa: PLR2004  # both reached the transport


def test_empty_failure_status_codes_ignores_5xx_trips_on_network_error() -> None:
    """With failure_status_codes=[], no status ever counts; only NetworkError trips the breaker."""
    handler = _StatusSequence([500, 500, 500])
    breaker = CircuitBreaker(failure_threshold=2, failure_status_codes=[], _now=_Clock())
    with _client(handler, breaker=breaker) as client:
        for _ in range(3):
            with pytest.raises(InternalServerError):
                client.get("https://example.test/x")
    assert handler.calls == 3  # noqa: PLR2004  # never opened — 500 not in empty set

    def _raise(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        msg = "connect failed"
        raise httpx2.ConnectError(msg)

    breaker2 = CircuitBreaker(failure_threshold=2, failure_status_codes=[], _now=_Clock())
    with Client(
        httpx2_client=httpx2.Client(transport=httpx2.MockTransport(_raise)),
        middleware=[breaker2],
    ) as client2:
        for _ in range(2):
            with pytest.raises(NetworkError):
                client2.get("https://example.test/x")
        with pytest.raises(CircuitOpenError):
            client2.get("https://example.test/x")


def test_success_threshold_requires_multiple_probes() -> None:
    clock = _Clock()
    handler = _StatusSequence([500, 500, 200, 200])
    breaker = CircuitBreaker(failure_threshold=2, reset_timeout=5.0, success_threshold=2, _now=clock)
    with _client(handler, breaker=breaker) as client:
        for _ in range(2):
            with pytest.raises(InternalServerError):
                client.get("https://example.test/x")
        clock.advance(5.0)
        client.get("https://example.test/x")  # probe 1 -> 200 (HALF_OPEN 1/2)
        client.get("https://example.test/x")  # probe 2 -> 200 -> CLOSED
        response = client.get("https://example.test/x")  # default 200, CLOSED
    assert response.status_code == HTTPStatus.OK
    assert handler.calls == 5  # noqa: PLR2004 — 2 failures + 2 probes + 1 CLOSED


def test_half_open_second_concurrent_request_rejected_with_none_retry_after() -> None:
    """Two threads hit a half-open breaker; exactly one is the probe, the other is rejected."""
    clock = _Clock()
    probe_started = threading.Event()
    release_probe = threading.Event()

    def _handler(request: httpx2.Request) -> httpx2.Response:
        probe_started.set()
        release_probe.wait(timeout=5.0)
        return httpx2.Response(HTTPStatus.OK, request=request)

    breaker = CircuitBreaker(failure_threshold=1, reset_timeout=1.0, _now=clock)
    open_handler = _StatusSequence([500])
    with _client(open_handler, breaker=breaker) as opener, pytest.raises(InternalServerError):
        opener.get("https://example.test/x")
    clock.advance(1.0)

    client = Client(
        httpx2_client=httpx2.Client(transport=httpx2.MockTransport(_handler)),
        middleware=[breaker],
    )
    rejected: list[CircuitOpenError] = []

    def _probe() -> None:
        client.get("https://example.test/probe")

    with client:
        thread = threading.Thread(target=_probe)
        thread.start()
        assert probe_started.wait(timeout=5.0)
        with pytest.raises(CircuitOpenError) as info:
            client.get("https://example.test/concurrent")
        rejected.append(info.value)
        release_probe.set()
        thread.join(timeout=5.0)
        assert not thread.is_alive()

    assert rejected[0].retry_after is None


# ── rate-mode trip behavior (sync mirror) ──


def test_rate_mode_trips_on_partial_failure() -> None:
    """Alternating 50% failures trip rate mode (classic never would)."""
    clock = _Clock()
    breaker = CircuitBreaker(failure_rate_threshold=0.5, window_seconds=100.0, minimum_calls=10, _now=clock)
    handler = _StatusSequence([500, 200, 500, 200, 500, 200, 500, 200, 500, 200])
    client = _client(handler, breaker=breaker)
    for _ in range(10):
        with contextlib.suppress(InternalServerError):
            client.get("https://example.test/x")
    with pytest.raises(CircuitOpenError):
        client.get("https://example.test/x")


def test_rate_mode_does_not_trip_below_minimum_calls() -> None:
    clock = _Clock()
    breaker = CircuitBreaker(failure_rate_threshold=0.5, window_seconds=100.0, minimum_calls=10, _now=clock)
    handler = _StatusSequence([500, 500, 500])  # 3 failures, below floor of 10
    client = _client(handler, breaker=breaker)
    for _ in range(3):
        with pytest.raises(InternalServerError):
            client.get("https://example.test/x")
    handler_ok = _StatusSequence([200])
    client_ok = _client(handler_ok, breaker=breaker)
    assert client_ok.get("https://example.test/x").status_code == HTTPStatus.OK


def test_rate_mode_evicts_old_failures() -> None:
    clock = _Clock()
    breaker = CircuitBreaker(failure_rate_threshold=0.5, window_seconds=10.0, minimum_calls=4, _now=clock)
    fail = _client(_StatusSequence([500, 500, 500, 500, 500, 500, 500, 500]), breaker=breaker)
    for _ in range(3):
        with pytest.raises(InternalServerError):
            fail.get("https://example.test/x")
    clock.advance(20.0)  # push them fully out of the 10s window
    with pytest.raises(InternalServerError):
        fail.get("https://example.test/x")
    ok = _client(_StatusSequence([200]), breaker=breaker)
    assert ok.get("https://example.test/x").status_code == HTTPStatus.OK


def test_rate_mode_clears_window_on_close() -> None:
    """Closing from HALF_OPEN in rate mode clears the window — recovery starts fresh.

    Discriminating: without the clear, the pre-open failures would still be inside the
    window after recovery and a single post-close failure would re-cross the rate
    threshold immediately. With the clear, the post-close failure is below minimum_calls
    again, so the circuit stays CLOSED.
    """
    clock = _Clock()
    breaker = CircuitBreaker(
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
            open_client.get("https://example.test/x")
    with pytest.raises(CircuitOpenError):  # 2/2 failures >= 0.5 -> OPEN
        open_client.get("https://example.test/x")
    clock.advance(5.0)
    probe_client = _client(_StatusSequence([200]), breaker=breaker)
    probe_client.get("https://example.test/x")  # probe 200 -> CLOSED, window cleared
    # One fresh failure: total=1 < minimum_calls=2, so the circuit stays CLOSED.
    fail_client = _client(_StatusSequence([500]), breaker=breaker)
    with pytest.raises(InternalServerError):
        fail_client.get("https://example.test/x")
    ok_client = _client(_StatusSequence([200]), breaker=breaker)
    assert ok_client.get("https://example.test/x").status_code == HTTPStatus.OK


# ── state property (sync mirror) ──


def test_state_closed_open_and_raw_read_caveat() -> None:
    clock = _Clock()
    breaker = CircuitBreaker(failure_threshold=2, reset_timeout=10.0, success_threshold=1, _now=clock)
    assert breaker.state is CircuitState.CLOSED
    client = _client(_StatusSequence([500, 500]), breaker=breaker)
    for _ in range(2):
        with pytest.raises(InternalServerError):
            client.get("https://example.test/x")
    assert breaker.state is CircuitState.OPEN
    # raw-read caveat: reset_timeout elapses but NO request is made → still OPEN
    clock.advance(10.0)
    assert breaker.state is CircuitState.OPEN
    # the next request is admitted as the probe and (success_threshold=1) closes the circuit
    ok = _client(_StatusSequence([200]), breaker=breaker)
    assert ok.get("https://example.test/x").status_code == HTTPStatus.OK
    assert breaker.state is CircuitState.CLOSED


def test_state_half_open_while_probing() -> None:
    clock = _Clock()
    breaker = CircuitBreaker(failure_threshold=1, reset_timeout=5.0, success_threshold=2, _now=clock)
    fail = _client(_StatusSequence([500]), breaker=breaker)
    with pytest.raises(InternalServerError):
        fail.get("https://example.test/x")
    assert breaker.state is CircuitState.OPEN
    clock.advance(5.0)
    ok = _client(_StatusSequence([200, 200]), breaker=breaker)
    ok.get("https://example.test/x")  # admitted as probe; 1 success, needs 2 → HALF_OPEN
    assert breaker.state is CircuitState.HALF_OPEN
    ok.get("https://example.test/x")  # 2nd consecutive success → CLOSED
    assert breaker.state is CircuitState.CLOSED


def test_rate_mode_probe_failure_reopens_with_classic_attributes(caplog: pytest.LogCaptureFixture) -> None:
    """Sync mirror: a failed HALF_OPEN probe re-opens a rate-mode circuit via the shared classic path.

    Documented as intended (2026-06-16 delta audit, Low #1): the re-open's circuit.opened carries
    the classic failure_threshold/failures shape (failures=1) in both modes.
    """
    clock = _Clock()
    breaker = CircuitBreaker(
        failure_rate_threshold=0.5, window_seconds=100.0, minimum_calls=2, reset_timeout=5.0, _now=clock
    )
    fail = _client(_StatusSequence([500, 500]), breaker=breaker)  # total=2, rate=1.0 → trip via rate
    for _ in range(2):
        with pytest.raises(InternalServerError):
            fail.get("https://example.test/x")
    assert breaker.state is CircuitState.OPEN
    clock.advance(5.0)  # past reset_timeout → next request is admitted as the probe
    with caplog.at_level(logging.WARNING, logger="httpware.circuit_breaker"):
        probe = _client(_StatusSequence([500]), breaker=breaker)
        with pytest.raises(InternalServerError):
            probe.get("https://example.test/x")
    assert breaker.state is CircuitState.OPEN  # the failed probe re-opened it
    opened = [r for r in caplog.records if r.event == "circuit.opened"]  # ty: ignore[unresolved-attribute]
    assert opened
    rec = opened[-1]
    assert rec.failures == 1  # ty: ignore[unresolved-attribute]  # classic probe-failure shape
    assert hasattr(rec, "failure_threshold")
    assert not hasattr(rec, "failure_rate")  # NOT the rate shape


# ── stragglers: outcomes apply to the state the request was admitted under ──


class _HeldCall:
    """One breaker call on its own thread whose `next` blocks until `finish` gives it a status."""

    def __init__(self, calls: "_HeldCalls") -> None:
        self._calls = calls
        self._settled = threading.Event()
        self._release = threading.Event()
        self._status = HTTPStatus.OK
        self._thread = threading.Thread(target=self._run)
        self._thread.start()
        assert self._settled.wait(timeout=5.0)

    def _next(self, request: httpx2.Request) -> httpx2.Response:
        probe = self._calls.enter()
        self._settled.set()
        try:
            self._release.wait(timeout=5.0)
        finally:
            self._calls.leave(probe)
        if self._status >= HTTPStatus.INTERNAL_SERVER_ERROR:
            raise InternalServerError(httpx2.Response(self._status, request=request))
        return httpx2.Response(self._status, request=request)

    def _run(self) -> None:
        with contextlib.suppress(InternalServerError, CircuitOpenError):
            self._calls.breaker(httpx2.Request("GET", "https://example.test/x"), self._next)
        self._settled.set()

    def finish(self, status: int) -> None:
        self._status = status
        self._release.set()
        self._thread.join(timeout=5.0)
        assert not self._thread.is_alive()


class _HeldCalls:
    """Counts how many calls that entered `next` while the circuit was HALF_OPEN are in flight."""

    def __init__(self, breaker: CircuitBreaker) -> None:
        self.breaker = breaker
        self._lock = threading.Lock()
        self._started: list[_HeldCall] = []
        self.probes_in_flight = 0
        self.max_probes_in_flight = 0

    def enter(self) -> bool:
        probe = self.breaker.state is CircuitState.HALF_OPEN
        if probe:
            with self._lock:
                self.probes_in_flight += 1
                self.max_probes_in_flight = max(self.max_probes_in_flight, self.probes_in_flight)
        return probe

    def leave(self, probe: bool) -> None:
        if probe:
            with self._lock:
                self.probes_in_flight -= 1

    def start(self) -> _HeldCall:
        call = _HeldCall(self)
        self._started.append(call)
        return call

    def drain(self) -> None:
        for call in self._started:
            call.finish(HTTPStatus.OK)


def _open_now(breaker: CircuitBreaker) -> None:
    def _five_hundred(request: httpx2.Request) -> httpx2.Response:
        raise InternalServerError(httpx2.Response(HTTPStatus.INTERNAL_SERVER_ERROR, request=request))

    with pytest.raises(InternalServerError):
        breaker(httpx2.Request("GET", "https://example.test/x"), _five_hundred)


def test_stale_closed_era_failure_does_not_reopen_half_open_circuit() -> None:
    clock = _Clock()
    breaker = CircuitBreaker(failure_threshold=1, reset_timeout=1.0, _now=clock)
    calls = _HeldCalls(breaker)
    straggler = calls.start()
    _open_now(breaker)
    clock.advance(1.0)
    probe = calls.start()
    straggler.finish(HTTPStatus.INTERNAL_SERVER_ERROR)
    assert breaker.state is CircuitState.HALF_OPEN
    probe.finish(HTTPStatus.OK)
    assert breaker.state is CircuitState.CLOSED


def test_stale_closed_era_successes_do_not_close_half_open_circuit() -> None:
    clock = _Clock()
    breaker = CircuitBreaker(failure_threshold=1, reset_timeout=1.0, success_threshold=3, _now=clock)
    calls = _HeldCalls(breaker)
    stragglers = [calls.start(), calls.start()]
    _open_now(breaker)
    clock.advance(1.0)
    probe = calls.start()
    for straggler in stragglers:
        straggler.finish(HTTPStatus.OK)
    probe.finish(HTTPStatus.OK)
    assert breaker.state is CircuitState.HALF_OPEN


def test_stragglers_never_let_a_second_probe_in() -> None:
    clock = _Clock()
    breaker = CircuitBreaker(failure_threshold=1, reset_timeout=1.0, success_threshold=2, _now=clock)
    calls = _HeldCalls(breaker)
    straggler = calls.start()
    _open_now(breaker)
    clock.advance(1.0)
    calls.start()
    straggler.finish(HTTPStatus.INTERNAL_SERVER_ERROR)
    clock.advance(1.0)
    calls.start()
    calls.drain()
    assert calls.max_probes_in_flight == 1


# ── a RetryBudgetExhaustedError is classified by its last_exception ──


def _behind_starved_retry(handler: Callable[[httpx2.Request], httpx2.Response], breaker: CircuitBreaker) -> Client:
    return Client(
        httpx2_client=httpx2.Client(transport=httpx2.MockTransport(handler)),
        middleware=[
            breaker,
            Retry(
                budget=RetryBudget(min_retries_per_sec=0.0, percent_can_retry=0.0),
                base_delay=0.0,
                retry_status_codes=frozenset({429, 503}),
            ),
        ],
    )


def test_budget_exhausted_on_5xx_is_a_counted_failure() -> None:
    breaker = CircuitBreaker(failure_threshold=1, _now=_Clock())
    with _behind_starved_retry(_StatusSequence([503]), breaker) as client:
        with pytest.raises(RetryBudgetExhaustedError):
            client.get("https://example.test/x")
        with pytest.raises(CircuitOpenError):
            client.get("https://example.test/x")


def test_budget_exhausted_on_network_error_is_a_counted_failure() -> None:
    def _refuse(request: httpx2.Request) -> httpx2.Response:
        msg = "refused"
        raise httpx2.ConnectError(msg, request=request)

    breaker = CircuitBreaker(failure_threshold=1, _now=_Clock())
    with _behind_starved_retry(_refuse, breaker) as client:
        with pytest.raises(RetryBudgetExhaustedError) as info:
            client.get("https://example.test/x")
        assert isinstance(info.value.last_exception, NetworkError)
        with pytest.raises(CircuitOpenError):
            client.get("https://example.test/x")


def test_budget_exhausted_on_4xx_is_a_success() -> None:
    breaker = CircuitBreaker(failure_threshold=2, _now=_Clock())
    with _behind_starved_retry(_StatusSequence([500, 429, 500, 200]), breaker) as client:
        with pytest.raises(InternalServerError):
            client.get("https://example.test/x")
        with pytest.raises(RetryBudgetExhaustedError):
            client.get("https://example.test/x")
        with pytest.raises(InternalServerError):
            client.get("https://example.test/x")
        response = client.get("https://example.test/x")
    assert response.status_code == HTTPStatus.OK


def test_budget_exhausted_with_a_foreign_last_exception_leaves_the_circuit_alone() -> None:
    def _exhausted(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        raise RetryBudgetExhaustedError(last_response=None, last_exception=ValueError("boom"), attempts=1)

    breaker = CircuitBreaker(failure_threshold=1, _now=_Clock())
    for _ in range(3):
        with pytest.raises(RetryBudgetExhaustedError):
            breaker(httpx2.Request("GET", "https://example.test/x"), _exhausted)
    assert breaker.state is CircuitState.CLOSED


# ── circuit.rejected is rate limited per circuit and emitted outside the lock ──


def _unreachable(request: httpx2.Request) -> httpx2.Response:  # pragma: no cover — OPEN never forwards
    return httpx2.Response(HTTPStatus.OK, request=request)


def test_rejected_event_is_emitted_at_most_once_per_second(caplog: pytest.LogCaptureFixture) -> None:
    clock = _Clock()
    breaker = CircuitBreaker(failure_threshold=1, reset_timeout=30.0, _now=clock)
    _open_now(breaker)
    with caplog.at_level(logging.WARNING, logger="httpware.circuit_breaker"):
        for step in (0.0, 0.0, 0.0, 0.5, 0.49, 0.01, 0.2):
            clock.advance(step)
            with pytest.raises(CircuitOpenError):
                breaker(httpx2.Request("GET", "https://example.test/x"), _unreachable)
    rejected = [r for r in caplog.records if r.event == "circuit.rejected"]  # ty: ignore[unresolved-attribute]
    assert [r.suppressed for r in rejected] == [0, 4]  # ty: ignore[unresolved-attribute]


class _LockProbe(logging.Handler):
    """Records whether `lock` was held when each breaker event in `events` (None: all) arrived."""

    def __init__(self, lock: threading.Lock, events: frozenset[str] | None = frozenset({"circuit.rejected"})) -> None:
        super().__init__()
        self._lock = lock
        self._events = events
        self.held_during: list[bool] = []

    def emit(self, record: logging.LogRecord) -> None:
        event = getattr(record, "event", None)
        if event is not None and (self._events is None or event in self._events):
            self.held_during.append(self._lock.locked())


def test_rejected_event_is_emitted_outside_the_lock() -> None:
    breaker = CircuitBreaker(failure_threshold=1, reset_timeout=30.0, _now=_Clock())
    _open_now(breaker)
    probe = _LockProbe(breaker._lock)  # noqa: SLF001 — the lock is the thing under test
    logger = logging.getLogger("httpware.circuit_breaker")
    logger.addHandler(probe)
    try:
        with pytest.raises(CircuitOpenError):
            breaker(httpx2.Request("GET", "https://example.test/x"), _unreachable)
    finally:
        logger.removeHandler(probe)
    assert probe.held_during == [False]


class _CallOnEvent(logging.Handler):
    """Sends one request through `call` from inside every breaker event, like a log shipper."""

    def __init__(self, call: Callable[[], object]) -> None:
        super().__init__()
        self._call = call
        self._active = threading.local()
        self.events: list[str] = []

    def handle(self, record: logging.LogRecord) -> bool:
        """Emit without taking the handler lock, so a deadlocked call cannot hang logging.shutdown."""
        self.emit(record)
        return True

    def emit(self, record: logging.LogRecord) -> None:
        self.events.append(getattr(record, "event", ""))
        if getattr(self._active, "on", False):
            return
        self._active.on = True
        try:
            with contextlib.suppress(ClientError):
                self._call()
        finally:
            self._active.on = False


def _in_thread_with_handler(handler: logging.Handler, target: Callable[[], object]) -> bool:
    """Run `target` on a daemon thread with `handler` attached; return whether it finished in time."""
    logger = logging.getLogger("httpware.circuit_breaker")
    logger.addHandler(handler)
    previous = logger.level
    logger.setLevel(logging.INFO)

    def _run() -> None:
        with contextlib.suppress(ClientError):
            target()

    thread = threading.Thread(target=_run, daemon=True)
    try:
        thread.start()
        thread.join(timeout=5.0)
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous)
    return not thread.is_alive()


def test_event_handler_may_send_through_the_same_breaker() -> None:
    clock = _Clock()
    handler = _StatusSequence([500])
    breaker = CircuitBreaker(failure_threshold=1, reset_timeout=1.0, _now=clock)
    client = _client(handler, breaker=breaker)
    shipper = _CallOnEvent(lambda: client.get("https://logs.example.test/ingest"))

    def _outage_and_recovery() -> None:
        with contextlib.suppress(InternalServerError):
            client.get("https://example.test/x")
        clock.advance(1.0)
        client.get("https://example.test/x")

    with client:
        assert _in_thread_with_handler(shipper, _outage_and_recovery)
    assert shipper.events == [
        "circuit.opened",
        "circuit.rejected",
        "circuit.half_open",
        "circuit.rejected",
        "circuit.closed",
    ]


def test_every_event_is_emitted_outside_the_lock() -> None:
    clock = _Clock()
    breaker = CircuitBreaker(failure_threshold=1, reset_timeout=1.0, _now=clock)
    probe = _LockProbe(breaker._lock, events=None)  # noqa: SLF001 — the lock is the thing under test
    logger = logging.getLogger("httpware.circuit_breaker")
    logger.addHandler(probe)
    previous = logger.level
    logger.setLevel(logging.INFO)
    try:
        _open_now(breaker)
        _reject(breaker)
        clock.advance(1.0)
        breaker(httpx2.Request("GET", "https://example.test/x"), _ok)
    finally:
        logger.removeHandler(probe)
        logger.setLevel(previous)
    assert probe.held_during == [False, False, False, False]


# ── rejection accounting runs per outage episode ──


def _ok(request: httpx2.Request) -> httpx2.Response:
    return httpx2.Response(HTTPStatus.OK, request=request)


def _reject(breaker: CircuitBreaker) -> None:
    with pytest.raises(CircuitOpenError):
        breaker(httpx2.Request("GET", "https://example.test/x"), _unreachable)


def _events(caplog: pytest.LogCaptureFixture, name: str) -> list[logging.LogRecord]:
    return [r for r in caplog.records if getattr(r, "event", None) == name]


def test_first_rejection_of_a_new_outage_is_emitted(caplog: pytest.LogCaptureFixture) -> None:
    clock = _Clock()
    breaker = CircuitBreaker(failure_threshold=1, reset_timeout=0.1, _now=clock)
    with caplog.at_level(logging.INFO, logger="httpware.circuit_breaker"):
        _open_now(breaker)
        _reject(breaker)
        clock.advance(0.1)
        breaker(httpx2.Request("GET", "https://example.test/x"), _ok)
        _open_now(breaker)
        _reject(breaker)
    assert [r.suppressed for r in _events(caplog, "circuit.rejected")] == [0, 0]  # ty: ignore[unresolved-attribute]


def test_closed_event_reports_every_rejection_of_the_outage(caplog: pytest.LogCaptureFixture) -> None:
    clock = _Clock()
    breaker = CircuitBreaker(failure_threshold=1, reset_timeout=5.0, _now=clock)
    with caplog.at_level(logging.INFO, logger="httpware.circuit_breaker"):
        _open_now(breaker)
        _reject(breaker)
        _reject(breaker)
        clock.advance(5.0)
        _open_now(breaker)
        _reject(breaker)
        _reject(breaker)
        clock.advance(5.0)
        breaker(httpx2.Request("GET", "https://example.test/x"), _ok)
    assert [r.suppressed for r in _events(caplog, "circuit.rejected")] == [0, 1]  # ty: ignore[unresolved-attribute]
    assert [r.rejected for r in _events(caplog, "circuit.closed")] == [4]  # ty: ignore[unresolved-attribute]


def test_suppressed_never_counts_a_previous_outage(caplog: pytest.LogCaptureFixture) -> None:
    clock = _Clock()
    breaker = CircuitBreaker(failure_threshold=1, reset_timeout=5.0, _now=clock)
    with caplog.at_level(logging.INFO, logger="httpware.circuit_breaker"):
        _open_now(breaker)
        for _ in range(3):
            _reject(breaker)
        clock.advance(5.0)
        breaker(httpx2.Request("GET", "https://example.test/x"), _ok)
        _open_now(breaker)
        _reject(breaker)
    assert [r.suppressed for r in _events(caplog, "circuit.rejected")] == [0, 0]  # ty: ignore[unresolved-attribute]

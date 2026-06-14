"""Tests for the sync CircuitBreaker middleware (mirror of AsyncCircuitBreaker)."""

import logging
import threading
from collections.abc import Callable
from http import HTTPStatus

import httpx2
import pytest

from httpware import (
    CircuitOpenError,
    Client,
    InternalServerError,
    NetworkError,
    NotFoundError,
    RateLimitedError,
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
    assert any(r.event == "circuit.half_open" for r in records)  # ty: ignore[unresolved-attribute]
    assert any(r.event == "circuit.closed" for r in records)  # ty: ignore[unresolved-attribute]
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

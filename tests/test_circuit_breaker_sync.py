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
    assert any("opened" in r.message for r in records)
    assert any("rejecting" in r.message for r in records)


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


def test_custom_failure_status_codes_trips_on_member() -> None:
    handler = _StatusSequence([503, 503])
    breaker = CircuitBreaker(failure_threshold=2, failure_status_codes=frozenset({503}), _now=_Clock())
    with _client(handler, breaker=breaker) as client:
        for _ in range(2):
            with pytest.raises(ServiceUnavailableError):
                client.get("https://example.test/x")
        with pytest.raises(CircuitOpenError):
            client.get("https://example.test/x")
    assert handler.calls == 2  # noqa: PLR2004


def test_custom_failure_status_codes_excludes_other_5xx() -> None:
    handler = _StatusSequence([500, 500, 500, 500])
    breaker = CircuitBreaker(failure_threshold=2, failure_status_codes=frozenset({503}), _now=_Clock())
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
    messages = [r.message for r in caplog.records if r.name == "httpware.circuit_breaker"]
    assert any("half-open" in m for m in messages)
    assert any("closed" in m for m in messages)


def test_probe_failure_reopens_circuit() -> None:
    clock = _Clock()
    handler = _StatusSequence([500, 500, 500])
    breaker = CircuitBreaker(failure_threshold=2, reset_timeout=10.0, _now=clock)
    with _client(handler, breaker=breaker) as client:
        for _ in range(2):
            with pytest.raises(InternalServerError):
                client.get("https://example.test/x")
        clock.advance(10.0)
        with pytest.raises(InternalServerError):
            client.get("https://example.test/x")
        with pytest.raises(CircuitOpenError):
            client.get("https://example.test/x")
    assert handler.calls == 3  # noqa: PLR2004


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

    assert rejected[0].retry_after is None

"""Free-threaded stress: CircuitBreaker transitions stay consistent under parallel failures.

Many threads drive concurrent 5xx requests. Every call must raise an expected error type — a
StatusError while the request is forwarded, or CircuitOpenError once the breaker fast-fails —
and the breaker must end OPEN with no torn state. Verify-first: expected to PASS.

Collect *every* exception (not just unexpected ones) so the single `except` branch always runs
and stays covered under the 100% gate; then assert all collected errors are of the expected
types. A catch-all that only fires on the unexpected path would be dead code on a passing run
and would drop coverage below 100%.
"""

import threading
import typing
from http import HTTPStatus

import httpx2
import pytest

from httpware import CircuitBreaker, CircuitState, Client, InternalServerError
from httpware.errors import CircuitOpenError, StatusError
from httpware.middleware import Next
from httpware.middleware.resilience.circuit_breaker import _FAILURE, _SUCCESS, _HalfOpened


_N_THREADS = 16
_N_OPS = 50


def _fail(request: httpx2.Request) -> httpx2.Response:
    return httpx2.Response(HTTPStatus.INTERNAL_SERVER_ERROR, request=request)


@pytest.mark.stress
def test_circuit_breaker_opens_consistently_under_parallel_failures() -> None:
    breaker = CircuitBreaker(failure_threshold=5, reset_timeout=60.0)
    client = Client(
        httpx2_client=httpx2.Client(transport=httpx2.MockTransport(_fail)),
        middleware=[breaker],
    )
    errors: list[Exception] = []
    guard = threading.Lock()

    def worker() -> None:
        for _ in range(_N_OPS):
            try:
                client.get("https://example.test/x")
            except Exception as exc:  # noqa: BLE001
                with guard:
                    errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(_N_THREADS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    client.close()

    # Every request fails: a 5xx StatusError while forwarding, or CircuitOpenError once open.
    # No torn state means no other type leaks and the count is exact.
    assert len(errors) == _N_THREADS * _N_OPS
    assert all(isinstance(exc, (StatusError, CircuitOpenError)) for exc in errors)
    assert breaker.state is CircuitState.OPEN


_FAILURE_THRESHOLD = 3
_SUCCESS_THRESHOLD = 2
_FAILURES_PER_TEN = 3
_N_STRESS_OPS = 2000


class _Recorder:
    """Wraps a breaker's state to check its invariants from inside the breaker's lock.

    The sync breaker calls `admit` (when the circuit is not closed) and `record` under its lock,
    so the snapshots taken there are consistent.
    """

    def __init__(self, breaker: CircuitBreaker, monkeypatch: pytest.MonkeyPatch) -> None:
        self.state = breaker._state  # noqa: SLF001
        self.admit = self.state.admit
        self.record = self.state.record
        self.probes_in_flight = 0
        self.max_probes_in_flight = 0
        self.records: list[tuple[bool, tuple[typing.Any, ...], tuple[typing.Any, ...], bool, bool]] = []
        self.probe_outcomes: list[tuple[int, int]] = []
        monkeypatch.setattr(self.state, "admit", self._admit)
        monkeypatch.setattr(self.state, "record", self._record)

    def _snapshot(self) -> tuple[typing.Any, ...]:
        state = self.state
        return (
            state.state,
            state._epoch,  # noqa: SLF001
            state.closed_ticket,
            state._consecutive_failures,  # noqa: SLF001
            state._consecutive_successes,  # noqa: SLF001
            state._probe_in_flight,  # noqa: SLF001
        )

    def _admitted(self, ticket: int) -> None:
        if ticket % 2:
            self.probes_in_flight += 1
            self.max_probes_in_flight = max(self.max_probes_in_flight, self.probes_in_flight)

    def _admit(self, request: httpx2.Request) -> int:
        try:
            ticket = self.admit(request)
        except _HalfOpened as half_opened:
            self._admitted(half_opened.ticket)
            raise
        self._admitted(ticket)
        return ticket

    def _record(self, ticket: int, outcome: int, request: httpx2.Request) -> list[typing.Any] | None:
        if ticket % 2:
            self.probes_in_flight -= 1
            self.probe_outcomes.append((ticket, outcome))
        before = self._snapshot()
        stale = ticket not in (before[1], before[1] + 1)
        events = self.record(ticket, outcome, request)
        after = self._snapshot()
        circuit, epoch, closed_ticket, failures, successes, probe_in_flight = after
        consistent = (
            closed_ticket == (epoch if circuit is CircuitState.CLOSED else None)
            and failures < _FAILURE_THRESHOLD
            and successes < _SUCCESS_THRESHOLD
            and probe_in_flight == (self.probes_in_flight == 1)
        )
        self.records.append((stale, before, after, events is None, consistent))
        return events


def _next(fail: bool) -> Next:
    def _send(request: httpx2.Request) -> httpx2.Response:
        if fail:
            raise InternalServerError(httpx2.Response(HTTPStatus.INTERNAL_SERVER_ERROR, request=request))
        return httpx2.Response(HTTPStatus.OK, request=request)

    return _send


def _probe_eras(probe_outcomes: list[tuple[int, int]]) -> list[list[int]]:
    eras: dict[int, list[int]] = {}
    for ticket, outcome in probe_outcomes:
        eras.setdefault(ticket, []).append(outcome)
    return list(eras.values())


@pytest.mark.stress
def test_lock_free_admission_keeps_the_circuit_invariants(monkeypatch: pytest.MonkeyPatch) -> None:
    """Probes never overlap, success_threshold probes close the circuit, stale outcomes change nothing."""
    breaker = CircuitBreaker(
        failure_threshold=_FAILURE_THRESHOLD,
        reset_timeout=0.0,
        success_threshold=_SUCCESS_THRESHOLD,
    )
    recorder = _Recorder(breaker, monkeypatch)
    succeeded: list[int] = []
    errors: list[Exception] = []
    guard = threading.Lock()

    def worker(seed: int) -> None:
        request = httpx2.Request("GET", "https://example.test/x")
        for op in range(_N_STRESS_OPS):
            try:
                breaker(request, _next((seed + op * op) % 10 < _FAILURES_PER_TEN))
                with guard:
                    succeeded.append(op)
            except Exception as exc:  # noqa: BLE001
                with guard:
                    errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(_N_THREADS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(succeeded) + len(errors) == _N_THREADS * _N_STRESS_OPS
    assert all(isinstance(exc, (CircuitOpenError, InternalServerError)) for exc in errors)
    assert recorder.max_probes_in_flight == 1
    assert recorder.probes_in_flight == 0
    assert all(consistent for *_, consistent in recorder.records)
    assert all(after == before and no_events for stale, before, after, no_events, _ in recorder.records if stale)
    eras = _probe_eras(recorder.probe_outcomes)
    assert eras
    for era in eras:
        successes = era.count(_SUCCESS)
        assert successes <= _SUCCESS_THRESHOLD
        assert era in ([_SUCCESS] * successes, [*[_SUCCESS] * successes, _FAILURE])
    assert all(_FAILURE in era or len(era) == _SUCCESS_THRESHOLD for era in eras[:-1])

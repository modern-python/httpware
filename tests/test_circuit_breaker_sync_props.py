"""Property tests for the sync CircuitBreaker state machine.

Mirrors the interleaving test in tests/test_circuit_breaker_props.py. Each call runs on its own
thread and blocks inside `next` until the test finishes it, so calls overlap in any order the
strategy picks while the steps themselves stay sequential and deterministic.
"""

import dataclasses
import threading
import typing
from http import HTTPStatus

import httpx2
from hypothesis import given, settings
from hypothesis import strategies as st

from httpware import CircuitOpenError, InternalServerError
from httpware.middleware.resilience.circuit_breaker import CircuitBreaker, CircuitState


_FOREIGN = 0


def _request() -> httpx2.Request:
    return httpx2.Request("GET", "https://example.test/x")


@dataclasses.dataclass
class _Call:
    generation: int
    settled: threading.Event = dataclasses.field(default_factory=threading.Event)
    release: threading.Event = dataclasses.field(default_factory=threading.Event)
    status: int = HTTPStatus.OK
    probe: bool = False
    error: Exception | None = None
    thread: threading.Thread = dataclasses.field(init=False)


class _Harness:
    """Starts and finishes sync breaker calls, checking the circuit's invariants after every step.

    The generation counts observed state changes; each step causes at most one.
    """

    def __init__(self, breaker: CircuitBreaker, *, failure_threshold: int, success_threshold: int) -> None:
        self.breaker = breaker
        self.failure_threshold = failure_threshold
        self.success_threshold = success_threshold
        self.generation = 0
        self.observed = breaker.state
        self.in_flight: list[_Call] = []
        self.probes_in_flight = 0
        self.probe_successes = 0

    def _observe(self) -> None:
        state = self.breaker.state
        if state is not self.observed:
            if self.observed is CircuitState.HALF_OPEN and state is CircuitState.CLOSED:
                assert self.probe_successes == self.success_threshold
            if state is CircuitState.HALF_OPEN:
                self.probe_successes = 0
            self.generation += 1
            self.observed = state
        self._assert_consistent()

    def _assert_consistent(self) -> None:
        state = self.breaker._state  # noqa: SLF001
        closed = state.state is CircuitState.CLOSED
        assert state.closed_ticket == (state._epoch if closed else None)  # noqa: SLF001
        assert state._probe_in_flight == (self.probes_in_flight == 1)  # noqa: SLF001
        assert state._consecutive_failures < self.failure_threshold  # noqa: SLF001
        assert state._consecutive_successes < self.success_threshold  # noqa: SLF001

    def _next_for(self, call: _Call) -> typing.Callable[[httpx2.Request], httpx2.Response]:
        def _next(request: httpx2.Request) -> httpx2.Response:
            call.probe = self.breaker.state is CircuitState.HALF_OPEN
            self.probes_in_flight += call.probe
            call.settled.set()
            call.release.wait()
            self.probes_in_flight -= call.probe
            if call.status == _FOREIGN:
                msg = "foreign"
                raise ValueError(msg)
            if call.status >= HTTPStatus.INTERNAL_SERVER_ERROR:
                raise InternalServerError(httpx2.Response(call.status, request=request))
            return httpx2.Response(call.status, request=request)

        return _next

    def _run(self, call: _Call) -> None:
        try:
            self.breaker(_request(), self._next_for(call))
        except Exception as exc:  # noqa: BLE001
            call.error = exc
        finally:
            call.settled.set()

    def start(self) -> None:
        call = _Call(self.generation)
        call.thread = threading.Thread(target=self._run, args=(call,), daemon=True)
        call.thread.start()
        call.settled.wait()
        assert self.probes_in_flight <= 1
        self._observe()
        call.generation = self.generation
        if isinstance(call.error, CircuitOpenError):
            call.thread.join()
        else:
            self.in_flight.append(call)

    def finish(self, index: int, status: int) -> None:
        call = self.in_flight.pop(index % len(self.in_flight))
        before = self.breaker.state
        call.status = status
        call.release.set()
        call.thread.join()
        assert call.error is None or isinstance(call.error, (InternalServerError, ValueError))
        if call.probe and status != _FOREIGN and status < HTTPStatus.INTERNAL_SERVER_ERROR:
            self.probe_successes += 1
        if call.generation != self.generation:
            assert self.breaker.state is before
        self._observe()

    def drain(self) -> None:
        while self.in_flight:
            self.finish(0, HTTPStatus.OK)


_operations = st.lists(
    st.one_of(
        st.just(("start",)),
        st.tuples(
            st.just("finish"), st.integers(min_value=0, max_value=31), st.sampled_from([200, 404, 500, _FOREIGN])
        ),
    ),
    min_size=8,
    max_size=40,
)


@given(
    failure_threshold=st.integers(min_value=1, max_value=2),
    success_threshold=st.integers(min_value=1, max_value=3),
    operations=_operations,
)
@settings(max_examples=100, deadline=None)
def test_outcomes_only_move_the_state_they_were_admitted_under(
    failure_threshold: int,
    success_threshold: int,
    operations: list[tuple[typing.Any, ...]],
) -> None:
    """Stale outcomes leave the circuit alone, probes never overlap, and success_threshold probes close it."""
    breaker = CircuitBreaker(
        failure_threshold=failure_threshold,
        reset_timeout=0.0,
        success_threshold=success_threshold,
        _now=lambda: 0.0,
    )
    harness = _Harness(breaker, failure_threshold=failure_threshold, success_threshold=success_threshold)
    for operation in operations:
        if operation[0] == "start":
            harness.start()
        elif harness.in_flight:
            harness.finish(operation[1], operation[2])
    harness.drain()

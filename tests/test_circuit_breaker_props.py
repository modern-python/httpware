"""Property tests for the AsyncCircuitBreaker state machine.

Drives the breaker directly with stub `next` callables; time is injected via a clock.
"""

import asyncio
import contextlib
import dataclasses
import typing
from http import HTTPStatus

import httpx2
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from httpware import CircuitOpenError, InternalServerError
from httpware.middleware.resilience.circuit_breaker import AsyncCircuitBreaker, CircuitState


class _Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def _request() -> httpx2.Request:
    return httpx2.Request("GET", "https://example.test/x")


@given(
    failure_threshold=st.integers(min_value=1, max_value=5),
    reset_timeout=st.floats(min_value=1.0, max_value=100.0),
    fractions=st.lists(st.floats(min_value=0.0, max_value=0.99), min_size=1, max_size=20),
)
@settings(max_examples=50, deadline=None)
async def test_open_circuit_never_forwards_before_reset_timeout(
    failure_threshold: int,
    reset_timeout: float,
    fractions: list[float],
) -> None:
    clock = _Clock()
    breaker = AsyncCircuitBreaker(
        failure_threshold=failure_threshold,
        reset_timeout=reset_timeout,
        _now=clock,
    )
    forwarded = 0

    async def _ok(request: httpx2.Request) -> httpx2.Response:
        nonlocal forwarded
        forwarded += 1  # pragma: no cover — invariant: OPEN never forwards, so this never runs
        return httpx2.Response(200, request=request)  # pragma: no cover — invariant: OPEN never forwards

    async def _five_hundred(request: httpx2.Request) -> httpx2.Response:
        raise InternalServerError(httpx2.Response(500, request=request))

    # Open the circuit while the clock reads 0.0, so opened_at == 0.0.
    for _ in range(failure_threshold):
        with pytest.raises(InternalServerError):
            await breaker(_request(), _five_hundred)

    # Now OPEN. Probe at clock times strictly below reset_timeout (fraction <= 0.99), so
    # elapsed = clock.t - 0.0 < reset_timeout and every request is rejected without ever
    # forwarding to _ok. No conditional branch here — coverage is deterministic across examples.
    for fraction in fractions:
        clock.t = fraction * reset_timeout
        with pytest.raises(CircuitOpenError):
            await breaker(_request(), _ok)

    assert forwarded == 0  # `next` (_ok) was never called while OPEN pre-timeout


_FOREIGN = 0


@dataclasses.dataclass
class _InFlight:
    future: asyncio.Future[int]
    task: asyncio.Task[httpx2.Response]
    generation: int


class _Harness:
    """Starts and finishes breaker calls, tracking the circuit's generation and probes in flight.

    The generation counts observed state changes; each operation causes at most one.
    """

    def __init__(self, breaker: AsyncCircuitBreaker) -> None:
        self.breaker = breaker
        self.generation = 0
        self.observed = breaker.state
        self.in_flight: list[_InFlight] = []
        self.probes_in_flight = 0

    def _observe(self) -> None:
        if self.breaker.state is not self.observed:
            self.generation += 1
            self.observed = self.breaker.state

    async def _next(self, request: httpx2.Request) -> httpx2.Response:
        call = self.in_flight[-1]
        probe = self.breaker.state is CircuitState.HALF_OPEN
        self.probes_in_flight += probe
        assert self.probes_in_flight <= 1
        try:
            status = await call.future
        finally:
            self.probes_in_flight -= probe
        if status == _FOREIGN:
            msg = "foreign"
            raise ValueError(msg)
        if status >= HTTPStatus.INTERNAL_SERVER_ERROR:
            raise InternalServerError(httpx2.Response(status, request=request))
        return httpx2.Response(status, request=request)

    async def start(self) -> None:
        future: asyncio.Future[int] = asyncio.get_running_loop().create_future()
        call = _InFlight(future, asyncio.create_task(self.breaker(_request(), self._next)), self.generation)
        self.in_flight.append(call)
        await asyncio.sleep(0)
        self._observe()
        call.generation = self.generation
        if call.task.done():
            self.in_flight.remove(call)
            assert isinstance(call.task.exception(), CircuitOpenError)

    async def finish(self, index: int, status: int) -> None:
        call = self.in_flight.pop(index % len(self.in_flight))
        before = self.breaker.state
        call.future.set_result(status)
        with contextlib.suppress(InternalServerError, ValueError):
            await call.task
        if call.generation != self.generation:
            assert self.breaker.state is before
        self._observe()

    async def drain(self) -> None:
        for call in self.in_flight:
            call.future.set_result(HTTPStatus.OK)
        await asyncio.gather(*(call.task for call in self.in_flight))


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
@settings(max_examples=200, deadline=None)
async def test_outcomes_only_move_the_state_they_were_admitted_under(
    failure_threshold: int,
    success_threshold: int,
    operations: list[tuple[typing.Any, ...]],
) -> None:
    """A call finishing after the circuit has changed state leaves it alone, and probes never overlap."""
    breaker = AsyncCircuitBreaker(
        failure_threshold=failure_threshold,
        reset_timeout=0.0,
        success_threshold=success_threshold,
        _now=_Clock(),
    )
    harness = _Harness(breaker)
    for operation in operations:
        if operation[0] == "start":
            await harness.start()
        elif harness.in_flight:
            await harness.finish(operation[1], operation[2])
    await harness.drain()

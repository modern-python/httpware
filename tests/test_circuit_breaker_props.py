"""Property test: while OPEN and before reset_timeout, the breaker never forwards.

Drives the AsyncCircuitBreaker directly with a stub `next` that records calls.
Hypothesis generates random advance/outcome sequences. Time is injected via a clock.
"""

import httpx2
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from httpware import CircuitOpenError, InternalServerError
from httpware.middleware.resilience.circuit_breaker import AsyncCircuitBreaker


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
    advances=st.lists(st.floats(min_value=0.0, max_value=0.5), min_size=1, max_size=20),
)
@settings(max_examples=50, deadline=None)
async def test_open_circuit_never_forwards_before_reset_timeout(
    failure_threshold: int,
    reset_timeout: float,
    advances: list[float],
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
        return httpx2.Response(200, request=request)  # pragma: no cover

    async def _five_hundred(request: httpx2.Request) -> httpx2.Response:
        raise InternalServerError(httpx2.Response(500, request=request))

    # Open the circuit: failure_threshold consecutive 500s.
    for _ in range(failure_threshold):
        with pytest.raises(InternalServerError):
            await breaker(_request(), _five_hundred)

    # Now OPEN. Advance the clock in small steps that stay strictly below reset_timeout.
    calls_before = forwarded
    total = 0.0
    for step in advances:
        if total + step >= reset_timeout:
            break
        total += step
        clock.t = total
        with pytest.raises(CircuitOpenError):
            await breaker(_request(), _ok)

    assert forwarded == calls_before  # `next` (_ok) was never called while OPEN pre-timeout

"""Hypothesis property tests for AsyncBulkhead.

Properties verified:
1. Observed in-flight count never exceeds max_concurrent under any interleaving.
2. With acquire_timeout=0 and a full bulkhead, the call raises BulkheadFullError.
3. Successful acquisitions are released — back-to-back calls eventually drain
   without leaking slots.
"""

import asyncio
from http import HTTPStatus

import httpx2
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from httpware import AsyncClient
from httpware.errors import BulkheadFullError
from httpware.middleware.resilience.bulkhead import AsyncBulkhead


class _InFlightHandler:
    """Tracks max simultaneous in-flight count across all calls."""

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


@given(
    max_concurrent=st.integers(min_value=1, max_value=8),
    n_requests=st.integers(min_value=1, max_value=32),
    delay=st.floats(min_value=0.001, max_value=0.005),
)
@settings(max_examples=30, deadline=None)
async def test_in_flight_never_exceeds_max_concurrent(
    max_concurrent: int,
    n_requests: int,
    delay: float,
) -> None:
    handler = _InFlightHandler(delay=delay)
    transport = httpx2.MockTransport(handler)
    client = AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=transport),
        middleware=[AsyncBulkhead(max_concurrent=max_concurrent, acquire_timeout=None)],
    )
    await asyncio.gather(*(client.get(f"https://example.test/{i}") for i in range(n_requests)))
    assert handler.calls == n_requests
    assert handler.max_in_flight <= max_concurrent


@given(
    max_concurrent=st.integers(min_value=1, max_value=4),
    extra_requests=st.integers(min_value=1, max_value=8),
)
@settings(max_examples=20, deadline=None)
async def test_fail_fast_rejects_when_at_capacity(
    max_concurrent: int,
    extra_requests: int,
) -> None:
    handler = _InFlightHandler(delay=0.05)  # hold slots long enough for fail-fast to fire
    transport = httpx2.MockTransport(handler)
    client = AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=transport),
        middleware=[AsyncBulkhead(max_concurrent=max_concurrent, acquire_timeout=0)],
    )

    # Fill the bulkhead with max_concurrent long-running tasks.
    holders = [asyncio.create_task(client.get(f"https://example.test/hold-{i}")) for i in range(max_concurrent)]
    await asyncio.sleep(0.005)  # let the holders acquire their slots

    # Any extra requests should fail fast with BulkheadFullError.
    for i in range(extra_requests):
        with pytest.raises(BulkheadFullError):
            await client.get(f"https://example.test/extra-{i}")

    # Cleanup the holders.
    await asyncio.gather(*holders)


@given(
    max_concurrent=st.integers(min_value=1, max_value=4),
    n_requests=st.integers(min_value=4, max_value=16),
)
@settings(max_examples=20, deadline=None)
async def test_no_slot_leak_after_drain(max_concurrent: int, n_requests: int) -> None:
    """After all calls complete, the bulkhead has its full capacity available."""
    handler = _InFlightHandler(delay=0.001)
    bulkhead = AsyncBulkhead(max_concurrent=max_concurrent, acquire_timeout=None)
    transport = httpx2.MockTransport(handler)
    client = AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=transport),
        middleware=[bulkhead],
    )

    await asyncio.gather(*(client.get(f"https://example.test/{i}") for i in range(n_requests)))

    # AsyncBulkhead should be drained — _value equals max_concurrent again.
    # asyncio.Semaphore._value is implementation detail but reliable across CPython 3.11+.
    assert bulkhead._sem._value == max_concurrent  # noqa: SLF001

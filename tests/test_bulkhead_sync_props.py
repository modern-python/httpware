"""Hypothesis property tests for sync Bulkhead.

Mirrors tests/test_bulkhead_props.py for sync/async parity. Uses
threading.Thread + a shared lock-guarded counter instead of asyncio.gather.

Properties verified:
1. Observed in-flight count never exceeds max_concurrent under any interleaving.
2. With acquire_timeout=0 and a full bulkhead, the call raises BulkheadFullError.
3. Successful acquisitions are released — after drain, max_concurrent fresh
   acquires succeed (behavioral, no internal-state peek).
"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http import HTTPStatus

import httpx2
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from httpware import Client
from httpware.errors import BulkheadFullError
from httpware.middleware.resilience.bulkhead import Bulkhead


class _InFlightHandler:
    """Tracks max simultaneous in-flight count under a threading.Lock."""

    def __init__(self, delay: float) -> None:
        self.delay = delay
        self._lock = threading.Lock()
        self.in_flight = 0
        self.max_in_flight = 0
        self.calls = 0

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        with self._lock:
            self.calls += 1
            self.in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            time.sleep(self.delay)
            return httpx2.Response(HTTPStatus.OK, request=request)
        finally:
            with self._lock:
                self.in_flight -= 1


@given(
    max_concurrent=st.integers(min_value=1, max_value=8),
    n_requests=st.integers(min_value=1, max_value=32),
    delay=st.floats(min_value=0.001, max_value=0.005),
)
@settings(max_examples=20, deadline=None)
def test_in_flight_never_exceeds_max_concurrent(
    max_concurrent: int,
    n_requests: int,
    delay: float,
) -> None:
    handler = _InFlightHandler(delay=delay)
    transport = httpx2.MockTransport(handler)
    client = Client(
        httpx2_client=httpx2.Client(transport=transport),
        middleware=[Bulkhead(max_concurrent=max_concurrent, acquire_timeout=None)],
    )
    with ThreadPoolExecutor(max_workers=n_requests) as pool:
        futures = [pool.submit(client.get, f"https://example.test/{i}") for i in range(n_requests)]
        for f in futures:
            f.result()
    assert handler.calls == n_requests
    assert handler.max_in_flight <= max_concurrent


class _BarrierHandler:
    """Handler that signals slot acquisition via a threading.Barrier before holding the slot."""

    def __init__(self, barrier: threading.Barrier) -> None:
        self._barrier = barrier

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        # Signal that this holder has acquired a bulkhead slot and is now in-flight.
        self._barrier.wait(timeout=5.0)
        # Hold the slot long enough for the over-limit requests to be rejected.
        time.sleep(0.05)
        return httpx2.Response(HTTPStatus.OK, request=request)


@given(
    max_concurrent=st.integers(min_value=1, max_value=4),
    extra_requests=st.integers(min_value=1, max_value=8),
)
@settings(max_examples=15, deadline=None)
def test_fail_fast_rejects_when_at_capacity(
    max_concurrent: int,
    extra_requests: int,
) -> None:
    # Barrier: max_concurrent holders + 1 main thread — all parties meet once every
    # holder has acquired its bulkhead slot (i.e. is inside the handler).
    # timeout=5.0 sets the default for all barrier.wait() calls.
    acquired_barrier = threading.Barrier(max_concurrent + 1, timeout=5.0)
    handler = _BarrierHandler(acquired_barrier)
    transport = httpx2.MockTransport(handler)
    client = Client(
        httpx2_client=httpx2.Client(transport=transport),
        middleware=[Bulkhead(max_concurrent=max_concurrent, acquire_timeout=0)],
    )

    # Fill the bulkhead with max_concurrent long-running threads.
    pool = ThreadPoolExecutor(max_workers=max_concurrent + extra_requests)
    holders = [pool.submit(client.get, f"https://example.test/hold-{i}") for i in range(max_concurrent)]
    # Wait deterministically — barrier releases only once ALL holders are inside the handler.
    acquired_barrier.wait(timeout=5.0)

    # Any extra requests should fail fast with BulkheadFullError.
    for i in range(extra_requests):
        with pytest.raises(BulkheadFullError):
            client.get(f"https://example.test/extra-{i}")

    # Cleanup the holders.
    for f in holders:
        f.result()
    pool.shutdown()


@given(
    max_concurrent=st.integers(min_value=1, max_value=4),
    n_requests=st.integers(min_value=4, max_value=16),
)
@settings(max_examples=15, deadline=None)
def test_no_slot_leak_after_drain(max_concurrent: int, n_requests: int) -> None:
    """After all threads complete, the bulkhead has its full capacity available."""
    handler = _InFlightHandler(delay=0.001)
    bulkhead = Bulkhead(max_concurrent=max_concurrent, acquire_timeout=None)
    transport = httpx2.MockTransport(handler)
    client = Client(
        httpx2_client=httpx2.Client(transport=transport),
        middleware=[bulkhead],
    )

    with ThreadPoolExecutor(max_workers=n_requests) as pool:
        futures = [pool.submit(client.get, f"https://example.test/{i}") for i in range(n_requests)]
        for f in futures:
            f.result()

    # Behavioral drain check: after the threads finish, max_concurrent fresh
    # acquires must succeed simultaneously under a tight acquire_timeout. If
    # any slot leaked, the post-drain acquires would block past the timeout.
    bulkhead._acquire_timeout = 0.05  # noqa: SLF001 — test-local override
    with ThreadPoolExecutor(max_workers=max_concurrent) as pool:
        post = [pool.submit(client.get, f"https://example.test/post-drain-{i}") for i in range(max_concurrent)]
        for f in post:
            f.result()

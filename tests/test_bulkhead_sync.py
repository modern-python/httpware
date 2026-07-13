"""Tests for the sync Bulkhead middleware.

Mirror of test_bulkhead.py for sync semantics. Uses threading for the
concurrency-cap proofs.
"""

import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from http import HTTPStatus

import httpx2
import pytest

from httpware import Client
from httpware.errors import BulkheadFullError
from httpware.middleware.resilience.bulkhead import Bulkhead


_MAX_CONCURRENT_1 = 1
_MAX_CONCURRENT_2 = 2
_ACQUIRE_TIMEOUT_FAST = 0.01
_ACQUIRE_TIMEOUT_SHORT = 0.05
_ACQUIRE_TIMEOUT_LONG = 0.5


class _SlowHandler:
    """Mock handler that blocks for ``delay`` seconds before returning 200 OK."""

    def __init__(self, delay: float) -> None:
        self.delay = delay
        self.lock = threading.Lock()
        self.in_flight = 0
        self.max_in_flight = 0
        self.calls = 0

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        with self.lock:
            self.calls += 1
            self.in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            time.sleep(self.delay)
            return httpx2.Response(HTTPStatus.OK, request=request)
        finally:
            with self.lock:
                self.in_flight -= 1


def _client(
    handler: Callable[[httpx2.Request], httpx2.Response],
    *,
    bulkhead: Bulkhead,
) -> Client:
    transport = httpx2.MockTransport(handler)
    return Client(
        httpx2_client=httpx2.Client(transport=transport),
        middleware=[bulkhead],
    )


def test_max_concurrent_zero_rejected() -> None:
    with pytest.raises(ValueError, match="max_concurrent must be >= 1"):
        Bulkhead(max_concurrent=0)


def test_max_concurrent_negative_rejected() -> None:
    with pytest.raises(ValueError, match="max_concurrent must be >= 1"):
        Bulkhead(max_concurrent=-1)


def test_negative_acquire_timeout_rejected() -> None:
    with pytest.raises(ValueError, match="acquire_timeout must be >= 0"):
        Bulkhead(max_concurrent=_MAX_CONCURRENT_1, acquire_timeout=-0.1)


def test_acquire_timeout_zero_accepted() -> None:
    bulkhead = Bulkhead(max_concurrent=_MAX_CONCURRENT_1, acquire_timeout=0)
    assert bulkhead._acquire_timeout == 0  # noqa: SLF001


def test_acquire_timeout_none_accepted() -> None:
    bulkhead = Bulkhead(max_concurrent=_MAX_CONCURRENT_1, acquire_timeout=None)
    assert bulkhead._acquire_timeout is None  # noqa: SLF001


def test_succeeds_when_slot_available() -> None:
    handler = _SlowHandler(delay=0.0)
    client = _client(handler, bulkhead=Bulkhead(max_concurrent=_MAX_CONCURRENT_2))
    response = client.get("https://example.test/x")
    assert response.status_code == HTTPStatus.OK
    assert handler.calls == 1


def test_serializes_at_capacity() -> None:
    """With max_concurrent=1 and 3 concurrent threads, in-flight count never exceeds 1."""
    handler = _SlowHandler(delay=0.02)
    client = _client(
        handler,
        bulkhead=Bulkhead(max_concurrent=_MAX_CONCURRENT_1, acquire_timeout=None),
    )
    with ThreadPoolExecutor(max_workers=3) as ex:
        futures = [ex.submit(client.get, f"https://example.test/{i}") for i in "abc"]
        for f in futures:
            f.result()
    assert handler.calls == 3  # noqa: PLR2004
    assert handler.max_in_flight == 1


def test_acquire_timeout_rejects_when_no_slot_available() -> None:
    handler = _SlowHandler(delay=0.1)
    client = _client(
        handler,
        bulkhead=Bulkhead(max_concurrent=_MAX_CONCURRENT_1, acquire_timeout=_ACQUIRE_TIMEOUT_FAST),
    )

    holder = threading.Thread(target=client.get, args=("https://example.test/hold",))
    holder.start()
    # Give the holder time to acquire the only slot
    time.sleep(0.01)
    try:
        with pytest.raises(BulkheadFullError) as info:
            client.get("https://example.test/blocked")
        assert info.value.max_concurrent == _MAX_CONCURRENT_1
        assert info.value.acquire_timeout == _ACQUIRE_TIMEOUT_FAST
    finally:
        holder.join()


def test_bulkhead_full_error_no_chaining() -> None:
    """BulkheadFullError raised on the sync timeout path has no __cause__ (no active exception)."""
    handler = _SlowHandler(delay=0.1)
    client = _client(
        handler,
        bulkhead=Bulkhead(max_concurrent=_MAX_CONCURRENT_1, acquire_timeout=_ACQUIRE_TIMEOUT_FAST),
    )

    holder = threading.Thread(target=client.get, args=("https://example.test/hold",))
    holder.start()
    # Give the holder time to acquire the only slot
    time.sleep(0.01)
    try:
        with pytest.raises(BulkheadFullError) as exc_info:
            client.get("https://example.test/blocked")
        assert exc_info.value.__cause__ is None
    finally:
        holder.join()


def test_releases_slot_on_exception() -> None:
    """A handler that raises must still cause the slot to be released."""
    calls = []

    def boom(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        calls.append(1)
        msg = "kaboom"
        raise RuntimeError(msg)

    transport = httpx2.MockTransport(boom)
    bulkhead = Bulkhead(max_concurrent=_MAX_CONCURRENT_1, acquire_timeout=_ACQUIRE_TIMEOUT_SHORT)
    client = Client(httpx2_client=httpx2.Client(transport=transport), middleware=[bulkhead])

    with pytest.raises(RuntimeError, match="kaboom"):
        client.get("https://example.test/x")
    # Second call must succeed (slot was released) — handler still raises, but bulkhead doesn't reject
    with pytest.raises(RuntimeError, match="kaboom"):
        client.get("https://example.test/y")
    assert len(calls) == 2  # noqa: PLR2004 — both attempts reached the handler


def test_emits_rejected_event(caplog: pytest.LogCaptureFixture) -> None:
    handler = _SlowHandler(delay=0.1)
    client = _client(
        handler,
        bulkhead=Bulkhead(max_concurrent=_MAX_CONCURRENT_1, acquire_timeout=_ACQUIRE_TIMEOUT_FAST),
    )
    holder = threading.Thread(target=client.get, args=("https://example.test/hold",))
    holder.start()
    time.sleep(0.01)
    try:
        with caplog.at_level(logging.WARNING, logger="httpware.bulkhead"), pytest.raises(BulkheadFullError):
            client.get("https://example.test/blocked")
        assert any("bulkhead rejected" in r.getMessage() for r in caplog.records)
    finally:
        holder.join()


def test_acquire_timeout_none_blocks_until_slot_available() -> None:
    """With acquire_timeout=None, the call should block until a slot frees up."""
    handler = _SlowHandler(delay=0.05)
    client = _client(
        handler,
        bulkhead=Bulkhead(max_concurrent=_MAX_CONCURRENT_1, acquire_timeout=None),
    )
    holder = threading.Thread(target=client.get, args=("https://example.test/hold",))
    holder.start()
    time.sleep(0.005)  # ensure holder has the slot
    # This should not raise; it should wait for the slot.
    response = client.get("https://example.test/wait")
    holder.join()
    assert response.status_code == HTTPStatus.OK
    assert handler.calls == 2  # noqa: PLR2004

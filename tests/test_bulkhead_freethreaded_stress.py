"""Free-threaded stress: Bulkhead's semaphore caps real parallel in-flight requests.

The handler tracks live concurrency; peak must never exceed max_concurrent even when many
threads run Python in parallel (3.14t). Verify-first: expected to PASS.
"""

import threading
import time
from http import HTTPStatus

import httpx2
import pytest

from httpware import Bulkhead, Client

_MAX = 4
_N_THREADS = 24


@pytest.mark.stress
def test_bulkhead_never_exceeds_max_concurrent_under_parallelism() -> None:
    active = 0
    peak = 0
    guard = threading.Lock()

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal active, peak
        with guard:
            active += 1
            peak = max(peak, active)
        time.sleep(0.002)  # hold the slot so contention is real
        with guard:
            active -= 1
        return httpx2.Response(HTTPStatus.OK, request=request)

    client = Client(
        httpx2_client=httpx2.Client(transport=httpx2.MockTransport(handler)),
        # generous acquire_timeout so contention blocks rather than raising BulkheadFullError
        middleware=[Bulkhead(max_concurrent=_MAX, acquire_timeout=30.0)],
    )

    def worker() -> None:
        client.get("https://example.test/x")

    threads = [threading.Thread(target=worker) for _ in range(_N_THREADS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    client.close()

    assert peak <= _MAX  # the invariant: semaphore holds the cap under true parallelism
    assert peak > 1  # sanity: the test actually exercised concurrency

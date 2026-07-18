"""Free-threaded stress: a shared RetryBudget stays consistent under real thread parallelism.

Meaningful under free-threaded CPython (3.14t), where threads run Python in parallel; also a
valid concurrency check under the GIL. Verify-first: this is expected to PASS (RetryBudget is
already lock-guarded). A failure means a real race.
"""

import contextlib
import threading
from http import HTTPStatus

import httpx2
import pytest

from httpware import Client, Retry
from httpware.middleware.resilience.budget import RetryBudget

_N_THREADS = 16
_N_OPS = 100


def _fail(request: httpx2.Request) -> httpx2.Response:
    return httpx2.Response(HTTPStatus.SERVICE_UNAVAILABLE, request=request)


def _fixed_clock() -> float:
    return 0.0


@pytest.mark.stress
def test_shared_retry_budget_survives_thread_parallelism() -> None:
    # Pinned clock: all deposits share timestamp 0.0, so _purge (strict `< cutoff`) evicts
    # nothing and the deposit count is exact — any lost/torn append would change it.
    budget = RetryBudget(ttl=60.0, min_retries_per_sec=1000.0, percent_can_retry=0.5, _now=_fixed_clock)
    client = Client(
        httpx2_client=httpx2.Client(transport=httpx2.MockTransport(_fail)),
        middleware=[Retry(budget=budget, max_attempts=2, base_delay=0.0001, max_delay=0.001)],
    )

    def worker() -> None:
        for _ in range(_N_OPS):
            with contextlib.suppress(Exception):
                client.get("https://example.test/x")

    threads = [threading.Thread(target=worker) for _ in range(_N_THREADS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    client.close()

    # One deposit per request (deposit-hoist counts requests, not attempts).
    assert len(budget._deposits) == _N_THREADS * _N_OPS  # noqa: SLF001

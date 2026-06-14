"""Demonstrates that a single RetryBudget can be shared across a sync Client and an AsyncClient.

The lock added in Task B2 makes ``RetryBudget`` thread-safe so sync threads and an asyncio
event loop can deposit/withdraw concurrently without corrupting the internal deques.
"""

import asyncio
import contextlib
import threading
from http import HTTPStatus

import httpx2

from httpware import AsyncClient, AsyncRetry, Client, Retry
from httpware.middleware.resilience.budget import RetryBudget


_N_SYNC_THREADS = 4
_N_OPS_PER_THREAD = 50
_N_ASYNC_TASKS = 20


def _failing_handler(request: httpx2.Request) -> httpx2.Response:
    return httpx2.Response(HTTPStatus.SERVICE_UNAVAILABLE, request=request)


def _sync_worker(sync_client: Client) -> None:
    for _ in range(_N_OPS_PER_THREAD):
        with contextlib.suppress(Exception):
            sync_client.get("https://example.test/x")


async def _safe_get(async_client: AsyncClient) -> None:
    with contextlib.suppress(Exception):
        await async_client.get("https://example.test/x")


async def _drive_async_side(budget: RetryBudget) -> None:
    transport = httpx2.MockTransport(_failing_handler)
    async_client = AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=transport),
        middleware=[
            AsyncRetry(
                budget=budget,
                max_attempts=2,
                base_delay=0.0001,
                max_delay=0.001,
                _sleep=asyncio.sleep,
            ),
        ],
    )
    async with async_client:
        await asyncio.gather(*[_safe_get(async_client) for _ in range(_N_ASYNC_TASKS)])


def _fixed_clock() -> float:
    """Return a constant timestamp so RetryBudget._purge never evicts deposits during this test."""
    return 0.0


def test_shared_budget_across_sync_threads_and_async_loop() -> None:
    # _now is pinned to a fixed timestamp: all deposits share the same timestamp,
    # so the TTL window cutoff is also 0.0 and _purge evicts nothing. This makes
    # the deposit-count assertion exact and independent of wall-clock elapsed time.
    budget = RetryBudget(ttl=60.0, min_retries_per_sec=1000.0, percent_can_retry=0.5, _now=_fixed_clock)

    sync_transport = httpx2.MockTransport(_failing_handler)
    sync_client = Client(
        httpx2_client=httpx2.Client(transport=sync_transport),
        middleware=[Retry(budget=budget, max_attempts=2, base_delay=0.0001, max_delay=0.001)],
    )

    threads = [threading.Thread(target=_sync_worker, args=(sync_client,)) for _ in range(_N_SYNC_THREADS)]
    for t in threads:
        t.start()

    asyncio.run(_drive_async_side(budget))

    for t in threads:
        t.join()

    # The lock kept the budget's internal deques consistent — no IndexError, no corruption.
    # 0.8.3 deposit-hoist: deposits count requests, not attempts (one per __call__,
    # regardless of max_attempts). The pinned clock ensures _purge never evicts any
    # deposit (all timestamps are 0.0, cutoff is 0.0 - 60.0 = -60.0 < 0.0, so the
    # strict `< cutoff` predicate is always False), making the deposit count exact.
    expected_deposits = (_N_SYNC_THREADS * _N_OPS_PER_THREAD) + _N_ASYNC_TASKS
    assert len(budget._deposits) == expected_deposits, (  # noqa: SLF001
        f"expected {expected_deposits} deposits, got {len(budget._deposits)}"  # noqa: SLF001
    )

    sync_client.close()

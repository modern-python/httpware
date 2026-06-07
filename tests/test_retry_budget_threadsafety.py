"""Thread-safety test for RetryBudget.

Sync Client may share a RetryBudget across a ThreadPoolExecutor. Concurrent
deposit() / try_withdraw() calls must not corrupt the internal deques. We
spawn many threads doing many ops and assert no exception, sane counters.
"""

import threading

from httpware.middleware.resilience.budget import RetryBudget


_N_THREADS = 16
_N_OPS_PER_THREAD = 1000


def test_concurrent_deposit_withdraw_does_not_corrupt() -> None:
    budget = RetryBudget(ttl=60.0, min_retries_per_sec=1000.0, percent_can_retry=0.5)
    errors: list[BaseException] = []
    barrier = threading.Barrier(_N_THREADS)

    def worker() -> None:
        try:
            barrier.wait()
            for _ in range(_N_OPS_PER_THREAD):
                budget.deposit()
                budget.try_withdraw()
        except BaseException as exc:  # noqa: BLE001 — collect any failure for the assert  # pragma: no cover — defensive harness; passes mean this branch is not taken
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(_N_THREADS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    # Each thread did _N_OPS_PER_THREAD deposits; budget must have accepted them all
    # (and possibly some withdrawals — we don't assert withdrawn count; the ceiling
    # formula doesn't guarantee how many succeed).
    assert len(budget._deposits) <= _N_THREADS * _N_OPS_PER_THREAD  # noqa: SLF001 — internal state check
    assert len(budget._deposits) > 0  # noqa: SLF001


def test_concurrent_only_deposit_count_matches() -> None:
    budget = RetryBudget(ttl=60.0)
    barrier = threading.Barrier(_N_THREADS)

    def worker() -> None:
        barrier.wait()
        for _ in range(_N_OPS_PER_THREAD):
            budget.deposit()

    threads = [threading.Thread(target=worker) for _ in range(_N_THREADS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # With no withdraws and no TTL expiry (60s window, sub-second test), every
    # deposit lands in the deque. Exact equality proves no deposits were lost
    # to a race.
    assert len(budget._deposits) == _N_THREADS * _N_OPS_PER_THREAD  # noqa: SLF001

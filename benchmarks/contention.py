"""Contention benchmark: shared Lock-based resilience components, GIL vs free-threaded.

Answers whether removing the GIL helps httpware's shared components or whether lock contention
eats the gain. Run under both interpreters and compare:

    uv run --python 3.11 benchmarks/contention.py
    uv run --python 3.14t benchmarks/contention.py

Not a test and not a CI gate (shared-runner perf is too noisy); a characterization tool. Free-
threading support here is a correctness certification, not a performance claim: this benchmark
measured 3.14t as roughly 1.9x *slower* than GIL 3.11 on a single-shared-lock hot loop.
"""

import sys
import threading
import time

from httpware.middleware.resilience.budget import RetryBudget


_N_THREADS = 8
_N_OPS = 200_000


def _run() -> float:
    budget = RetryBudget(ttl=60.0, min_retries_per_sec=1_000_000.0, percent_can_retry=1.0)

    def worker() -> None:
        for _ in range(_N_OPS):
            budget.deposit()
            budget.try_withdraw()

    threads = [threading.Thread(target=worker) for _ in range(_N_THREADS)]
    start = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return time.perf_counter() - start


def main() -> None:
    gil = getattr(sys, "_is_gil_enabled", lambda: True)()
    elapsed = _run()
    ops = _N_THREADS * _N_OPS * 2
    message = (
        f"python={sys.version.split()[0]} gil_enabled={gil} threads={_N_THREADS} "
        f"ops={ops} elapsed={elapsed:.3f}s throughput={ops / elapsed:,.0f} ops/s"
    )
    # T201 is fine here: benchmarks/ is not library code and is coverage-omitted.
    print(message)  # noqa: T201


if __name__ == "__main__":
    main()

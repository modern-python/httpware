# httpware free-threading (nogil) audit — 2026-07-18

**Status:** complete
**Scope:** empirical findings backing `planning/changes/2026-07-18.01-nogil-free-threading-support.md`
— the extras wheel matrix, the httpx2 shared-pool boundary result, the
free-threaded stress-test suite, and the contention benchmark baseline
(`benchmarks/contention.py`).

## Extras wheel matrix (free-threaded interpreters)

| Extra | 3.13t | 3.14t |
|---|---|---|
| pydantic | ✓ | ✓ |
| msgspec | ✗ (no cp313t wheel, versions 0.18–0.21.1) | ✓ |
| otel (opentelemetry) | ✓ (pure-Python, no wheel gap) | ✓ |

3.14t is the only free-threaded interpreter with complete extras coverage
from prebuilt wheels; all three extras keep the GIL disabled after import
(verified — none silently re-enables it). This is why free-threaded CI
(`.github/workflows/_checks.yml`, `pytest-freethreaded` job) targets `3.14t`
only; 3.13t is deferred in `planning/deferred.md` until msgspec ships a
cp313t wheel.

## httpx2 shared-pool boundary

`tests/test_httpx2_freethreaded_boundary.py::test_httpx2_shared_pool_no_crosstalk_under_parallelism`
(marked `stress`) drives 16 threads sharing one `httpx2` client + connection
pool, 100 requests per thread (1,600 total), in a single run on 3.14t with the
GIL disabled. Every response is verified against its own request. Result:
**zero cross-talk, zero crashes.** (The initial exploratory validation during
design was heavier — 32 threads, 3 × 12,800 requests — and also clean; the
committed test is the trimmed, CI-fast regression guard.) httpx2 is a
dependency httpware can't self-certify beyond this boundary test — this is the
recorded regression evidence that it holds under true thread parallelism.

## Free-threaded stress-test suite

Real thread-parallelism tests exercise httpware's Lock/Semaphore-based
components; five carry `pytest.mark.stress` and a sixth deterministically
covers the cross-loop guard. All pass on 3.14t with `sys._is_gil_enabled() is
False` (verified directly, and via the `pytest-freethreaded` CI job which
asserts the GIL is disabled before running the suite):

- `tests/test_retry_budget_threadsafety.py::test_concurrent_deposit_withdraw_does_not_corrupt` (`stress`)
- `tests/test_retry_budget_threadsafety.py::test_concurrent_only_deposit_count_matches` (`stress`)
- `tests/test_circuit_breaker_freethreaded_stress.py::test_circuit_breaker_opens_consistently_under_parallel_failures` (`stress`)
- `tests/test_bulkhead_freethreaded_stress.py::test_bulkhead_never_exceeds_max_concurrent_under_parallelism` (`stress`)
- `tests/test_httpx2_freethreaded_boundary.py::test_httpx2_shared_pool_no_crosstalk_under_parallelism` (`stress`)
- `tests/test_bulkhead.py::test_cross_loop_acquire_raises_runtimeerror` (deterministic;
  covers the guard's outer cross-loop raise. The inner double-checked-lock arm
  stays `# pragma: no cover` — free-threading makes it reachable but only
  nondeterministically, so it is not asserted)

Each stress test uses invariant assertions (final counts, exhaustion bounds,
state consistency) rather than interleaving-dependent timing, per
`architecture/testing.md`'s stress-test convention.

## Contention benchmark: GIL vs free-threaded

`benchmarks/contention.py` (committed, not a CI gate — shared-runner perf is
too noisy to gate on) drives 8 threads × 200,000 iterations of
`RetryBudget.deposit()` + `RetryBudget.try_withdraw()` against one shared
`RetryBudget` (3,200,000 total lock-guarded ops), measuring wall-clock
throughput. Run twice per interpreter for stability:

```
uv run --no-sync python benchmarks/contention.py
python=3.11.9 gil_enabled=True threads=8 ops=3200000 elapsed=0.869s throughput=3,684,320 ops/s
python=3.11.9 gil_enabled=True threads=8 ops=3200000 elapsed=0.869s throughput=3,683,289 ops/s

<ft-run venv>/bin/python benchmarks/contention.py
python=3.14.6 gil_enabled=False threads=8 ops=3200000 elapsed=1.626s throughput=1,967,685 ops/s
python=3.14.6 gil_enabled=False threads=8 ops=3200000 elapsed=1.634s throughput=1,958,734 ops/s
```

**Interpretation:** for this workload — a tiny critical section
(`deque` purge + append/compare under `threading.Lock`) hammered by 8 threads
with no non-lock work between acquisitions — free-threaded 3.14t is
**~1.9x slower** than GIL 3.11 (≈1.96M ops/s vs ≈3.68M ops/s), so **lock
contention dominates and nogil does not help here**: free threads spend more
wall-clock time contending for the same `threading.Lock` than the GIL's
cooperative bytecode-level serialization costs, and `RetryBudget`'s
correctness (proven by the stress test above) does not translate into a
throughput win under this access pattern. This is expected for a
single-shared-lock hot loop and is not a regression to fix — a real client
workload interleaves this critical section with I/O and non-lock CPU work
where free-threading's benefit (true parallel non-lock work) would show up
where this microbenchmark cannot show it. `RetryBudget`'s thread-safety
contract (`architecture/resilience.md`) is unaffected either way; this
benchmark characterizes throughput, not correctness.

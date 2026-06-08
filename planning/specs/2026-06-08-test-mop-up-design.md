# Spec: Test mop-up (0.8.6)

**Date:** 2026-06-08
**Topic slug:** `test-mop-up`
**Branch:** `fix/test-mop-up`
**Target release:** `0.8.6` — patch (test-only, no production code change)
**Status:** drafted, awaiting user review

## Purpose

Close 5 remaining test-quality audit findings in one PR. All test-only — no production code change, no API change, no behavioral change. After this lands, the audit's open list is empty for findings the author can act on without spec-level redesign decisions.

| # | Severity | File | Headline |
|---|---|---|---|
| 1 | Low | `tests/test_bulkhead_sync_props.py` (new) | Sync `Bulkhead` has no Hypothesis property test for the concurrency-cap invariant — async sibling exists, sync side is asymmetric |
| 2 | Low | `tests/test_middleware_sync.py` (new test) | `on_error` `BaseException` propagation has no sync peer for the async `CancelledError` test |
| 3 | Nit | `tests/test_bulkhead_props.py:113` | `assert bulkhead._sem._value == max_concurrent` peeks at a CPython implementation detail; replace with behavioral assertion |
| 4 | Nit | `tests/test_threading_with_shared_budget.py:77` | `assert len(budget._deposits) > 0` is weak — tighten to the exact expected total |
| 5 | Nit | `tests/test_optional_extras_pydantic_missing.py:41` | `test_async_client_accepts_explicit_decoder_without_pydantic` has no sync `Client` peer |

## Audit-finding scope note

The audit's chunk-3 hand-review listed `tests/test_client_methods.py has no construction/lifecycle tests for AsyncClient` as a Low finding. That finding is INVALID — the async construction and lifecycle tests live in `tests/test_client_construction.py` (8 tests) and `tests/test_client_lifecycle.py` (7 tests). The audit was looking in the wrong file. Excluded from this PR.

## Non-goals

- No production code changes.
- No fixes to the existing tests beyond the specific assertions named above.
- No refactoring of the test directory layout (e.g., no merge of `test_client_methods.py` + `test_client_construction.py` into one file).
- No additional Hypothesis strategies beyond what the audit specified.
- No new mock infrastructure — reuse the existing patterns (`MockTransport`, `_InFlightHandler`-style trackers, etc.).
- No change to the `_TEST_LOGGER` / `_TEST_*` constants conventions.

## Architecture

### Six commits, one PR

Order: 3 small Nit commits first (cheap, low-risk), then 2 Low test additions (more careful), then release notes:

1. `test(bulkhead-props): replace _value peek with behavioral assertion` — finding #3 (Nit)
2. `test(threading-budget): tighten weak post-condition to exact total` — finding #4 (Nit)
3. `test(optional-extras-pydantic): add sync Client peer for explicit-decoder escape hatch` — finding #5 (Nit)
4. `test(bulkhead-sync-props): Hypothesis property tests for sync Bulkhead` — finding #1 (Low)
5. `test(middleware-sync): on_error must let BaseException (KeyboardInterrupt, SystemExit) propagate` — finding #2 (Low)
6. `docs(release): draft 0.8.6 notes`

## Per-finding change list

### Finding #3 — `test_bulkhead_props.py` behavioral assertion

Current state (`tests/test_bulkhead_props.py:113`):

```python
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
```

**Fix:** replace the `._value` peek with a behavioral check — after drain, submit `max_concurrent` more requests under a tight `acquire_timeout` and confirm they all succeed (slots are available). This survives any future `asyncio.Semaphore` internals refactor.

```python
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

    # Behavioral drain check: after gather completes, max_concurrent fresh acquires
    # must succeed simultaneously. If any slot leaked, this gather would block forever
    # on the tight acquire_timeout and pytest's deadline=None settings would never
    # surface it — so use an acquire_timeout >0 to force a deterministic failure.
    bulkhead._acquire_timeout = 0.05  # noqa: SLF001 — test-local override of the internal config
    await asyncio.gather(*(client.get(f"https://example.test/post-drain-{i}") for i in range(max_concurrent)))
```

The `_acquire_timeout` override is still a private-attribute touch, but it's per-instance test config (not a CPython implementation detail). The `# noqa: SLF001` annotation matches the existing style for this kind of test-config override elsewhere in the file.

### Finding #4 — `test_threading_with_shared_budget.py` tight assertion

Current state (`tests/test_threading_with_shared_budget.py:77`):

```python
    # The lock kept the budget's internal deques consistent — no IndexError, no corruption.
    # No specific count assertion: the test passes if it completes without an exception
    # from the budget itself. Add a smoke check that the budget recorded SOME activity:
    assert len(budget._deposits) > 0  # noqa: SLF001
```

The 0.8.3 deposit-hoist changed semantics: deposits now count REQUESTS, not attempts. The new expected total per the audit is `(N_SYNC_THREADS * N_OPS_PER_THREAD) + N_ASYNC_TASKS` = `(4 * 50) + 20` = `220` deposits across all callers (since `max_attempts=2` no longer matters — deposits happen once per `__call__`, regardless of how many retries).

**Fix:** assert the exact expected total. The budget's TTL is `60.0` so no purge fires during the test's sub-second runtime.

```python
    # 0.8.3 hoist: deposits count requests, not attempts (one per __call__, regardless of max_attempts).
    expected_deposits = (_N_SYNC_THREADS * _N_OPS_PER_THREAD) + _N_ASYNC_TASKS
    assert len(budget._deposits) == expected_deposits, (  # noqa: SLF001
        f"expected {expected_deposits} deposits, got {len(budget._deposits)}"
    )
```

If the implementer finds the actual count differs (e.g., the async side's `_safe_get` catches an exception path that skips the deposit, or some test-time interleaving causes a divergence), STOP and report DONE_WITH_CONCERNS — the assertion is supposed to be exact, not approximate.

### Finding #5 — `test_optional_extras_pydantic_missing.py` sync peer

Current state (`tests/test_optional_extras_pydantic_missing.py:41-50`):

```python
def test_async_client_accepts_explicit_decoder_without_pydantic() -> None:
    """An explicit decoder= escapes the fail-fast even when pydantic is 'missing'."""

    class _FakeDecoder:
        def decode(self, content: bytes, model: type) -> object:  # noqa: ARG002 — name pinned by ResponseDecoder protocol
            return model()  # pragma: no cover

    with patch("httpware._internal.import_checker.is_pydantic_installed", False):
        client = AsyncClient(decoder=_FakeDecoder())
        assert client is not None
```

**Fix:** add a sync mirror. The `_FakeDecoder` class can be lifted to module top (it's already used in only this one test, so a module-level class is reasonable). Add:

```python
class _FakeDecoder:
    """Test stand-in for ResponseDecoder; never used at runtime."""

    def decode(self, content: bytes, model: type) -> object:  # noqa: ARG002 — name pinned by ResponseDecoder protocol
        return model()  # pragma: no cover


def test_async_client_accepts_explicit_decoder_without_pydantic() -> None:
    """An explicit decoder= escapes the fail-fast even when pydantic is 'missing'."""
    with patch("httpware._internal.import_checker.is_pydantic_installed", False):
        client = AsyncClient(decoder=_FakeDecoder())
        assert client is not None


def test_sync_client_accepts_explicit_decoder_without_pydantic() -> None:
    """Sync mirror: explicit decoder= escapes the fail-fast for sync Client too."""
    with patch("httpware._internal.import_checker.is_pydantic_installed", False):
        client = Client(decoder=_FakeDecoder())
        assert client is not None
```

The inner-class `_FakeDecoder` definition is replaced by a module-level one to keep the two tests DRY.

### Finding #1 — sync `Bulkhead` Hypothesis property tests (NEW FILE)

Create `tests/test_bulkhead_sync_props.py` mirroring `tests/test_bulkhead_props.py`. Uses `threading.Thread` + a shared counter instead of `asyncio.gather`. The properties to verify:

1. **`in_flight_never_exceeds_max_concurrent`** — under any thread interleaving, the observed max-in-flight count never exceeds `max_concurrent`.
2. **`fail_fast_rejects_when_at_capacity`** — with `acquire_timeout=0` and a full bulkhead, the call raises `BulkheadFullError`.
3. **`no_slot_leak_after_drain`** — after all threads complete, `max_concurrent` fresh acquires succeed (behavioral check, no `._value` peek).

Hypothesis strategies match the async file: `max_concurrent ∈ [1, 8]`, `n_requests ∈ [1, 32]`, `delay ∈ [0.001, 0.005]`.

The shared in-flight counter must be guarded by a `threading.Lock` since multiple threads update it; this is the test's plumbing, not the bulkhead's contract.

Full file content (~95 lines mirroring the async file's shape):

```python
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


@given(
    max_concurrent=st.integers(min_value=1, max_value=4),
    extra_requests=st.integers(min_value=1, max_value=8),
)
@settings(max_examples=15, deadline=None)
def test_fail_fast_rejects_when_at_capacity(
    max_concurrent: int,
    extra_requests: int,
) -> None:
    handler = _InFlightHandler(delay=0.05)  # hold slots long enough for fail-fast to fire
    transport = httpx2.MockTransport(handler)
    client = Client(
        httpx2_client=httpx2.Client(transport=transport),
        middleware=[Bulkhead(max_concurrent=max_concurrent, acquire_timeout=0)],
    )

    # Fill the bulkhead with max_concurrent long-running threads.
    holders = []
    pool = ThreadPoolExecutor(max_workers=max_concurrent + extra_requests)
    for i in range(max_concurrent):
        holders.append(pool.submit(client.get, f"https://example.test/hold-{i}"))
    # Wait for the holders to acquire — sleep long enough for thread startup.
    time.sleep(0.005)

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
```

Implementer note: if `ThreadPoolExecutor`-based scheduling produces flaky `max_in_flight ≤ max_concurrent` (e.g., due to time.sleep granularity at small delays), DROP `max_examples` to 10 and re-run. If still flaky, escalate as DONE_WITH_CONCERNS.

### Finding #2 — `on_error` sync `BaseException` propagation test (NEW TEST)

Append to `tests/test_middleware_sync.py`:

```python
def test_on_error_lets_keyboardinterrupt_propagate() -> None:
    """on_error catches Exception, NOT BaseException — KeyboardInterrupt / SystemExit must escape.

    Sync mirror of test_middleware.py::test_on_error_lets_cancelled_propagate. The async test
    pins CancelledError (an asyncio-specific BaseException). The sync world's equivalents are
    KeyboardInterrupt and SystemExit; they too must propagate through the on_error decorator.
    """

    @on_error
    def swallow_all(
        request: httpx2.Request,  # noqa: ARG001
        exc: Exception,  # noqa: ARG001
    ) -> httpx2.Response | None:  # pragma: no cover
        msg = "should not catch BaseException"
        raise AssertionError(msg)

    def terminal_ki(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        raise KeyboardInterrupt

    dispatch = compose((swallow_all,), terminal_ki)
    with pytest.raises(KeyboardInterrupt):
        dispatch(_make_request())


def test_on_error_lets_systemexit_propagate() -> None:
    """SystemExit (sibling of KeyboardInterrupt) must also escape on_error."""

    @on_error
    def swallow_all(
        request: httpx2.Request,  # noqa: ARG001
        exc: Exception,  # noqa: ARG001
    ) -> httpx2.Response | None:  # pragma: no cover
        msg = "should not catch BaseException"
        raise AssertionError(msg)

    def terminal_se(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        raise SystemExit

    dispatch = compose((swallow_all,), terminal_se)
    with pytest.raises(SystemExit):
        dispatch(_make_request())
```

Confirm that `compose`, `on_error`, `_make_request`, and `httpx2.Request`/`Response` are already imported at the top of the file; add any missing imports.

## Verification

After each commit:

```bash
just lint-ci
uv run pytest -x --no-cov -q
```

Full suite + lint green after every commit.

## Release notes

`planning/releases/0.8.6.md` — short patch, test-only, no behavior change. Note that the audit's open-findings list is now empty (modulo the one INVALID finding excluded).

## Acceptance criteria

1. Five test-fix commits + one release-notes commit on branch `fix/test-mop-up`.
2. `just lint-ci` and `uv run pytest` green after every commit.
3. PR opened against `main` with title `test(mop-up): close 5 audit findings (0.8.6)`.
4. After merge, tag `0.8.6` from the merge SHA; GitHub Release published from `planning/releases/0.8.6.md`.
5. Memory `release_0_8_6_shipped` added; the audit memory ([[deep-audit-2026-06-08-shipped]]) updated with the closure summary.

## Open questions

None. All five fixes are precisely specified. The finding excluded as INVALID is documented in scope-note above.

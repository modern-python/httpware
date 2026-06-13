---
status: shipped
date: 2026-06-08
slug: test-mop-up
spec: test-mop-up
pr: 37
---

# Test Mop-Up Implementation Plan (0.8.6)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land 6 commits on branch `fix/test-mop-up` that close 5 test-only audit findings, draft 0.8.6 release notes, and open the PR. After this lands, the audit's open list is empty.

**Architecture:** Three small Nit commits first (cheap, low-risk: behavioral drain assertion, tight deposit count, sync-decoder peer test), then two Low test additions (sync `Bulkhead` Hypothesis suite, sync `on_error` BaseException tests), then release notes. No production code change.

**Tech Stack:** Python 3.11+, pytest, Hypothesis, `threading.Thread` / `ThreadPoolExecutor` for sync concurrency tests. No new dependencies.

---

## Spec reference

`planning/specs/2026-06-08-test-mop-up-design.md`. Decisions locked there: 5 findings in scope (one chunk-3 finding excluded as INVALID per spec §Audit-finding scope note); test-only changes; commit order is 3 Nits → 2 Lows → release notes.

## File structure

```
tests/test_bulkhead_props.py                       # Task 1 — replace _value peek with behavioral check
tests/test_threading_with_shared_budget.py         # Task 2 — tighten count to exact total
tests/test_optional_extras_pydantic_missing.py     # Task 3 — add sync Client peer test
tests/test_bulkhead_sync_props.py                  # Task 4 — NEW FILE, sync Bulkhead Hypothesis suite
tests/test_middleware_sync.py                      # Task 5 — append two on_error BaseException tests
planning/releases/0.8.6.md                         # Task 6 — release notes
```

No new source files. No file deletions. Branch is already created (`fix/test-mop-up`); spec already committed.

---

## Task 1: `test_no_slot_leak_after_drain` — behavioral drain assertion

**Files:**
- Modify: `tests/test_bulkhead_props.py` (the `test_no_slot_leak_after_drain` function around line 99-113)

Closes audit Nit finding #3 (`tests/test_bulkhead_props.py:113`).

- [ ] **Step 1: Confirm current state**

```bash
sed -n '94,114p' tests/test_bulkhead_props.py
```

Expected: the test ends with `assert bulkhead._sem._value == max_concurrent  # noqa: SLF001`.

- [ ] **Step 2: Replace the test body with the behavioral version**

Use Edit tool.

old_string:
```python
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
```

new_string:
```python
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

    # Behavioral drain check: after gather completes, max_concurrent fresh acquires
    # must succeed simultaneously under a tight acquire_timeout. If any slot leaked,
    # the post-drain acquires would block past the timeout and BulkheadFullError
    # would surface — a deterministic failure rather than an internals-peek.
    bulkhead._acquire_timeout = 0.05  # noqa: SLF001 — test-local override of internal config
    await asyncio.gather(*(client.get(f"https://example.test/post-drain-{i}") for i in range(max_concurrent)))
```

- [ ] **Step 3: Run the test**

```bash
uv run pytest tests/test_bulkhead_props.py::test_no_slot_leak_after_drain --no-cov -q
```

Expected: PASS (the bulkhead drain correctness is unchanged; the test now exercises it behaviorally instead of via internals peek).

- [ ] **Step 4: Run the full bulkhead suites**

```bash
uv run pytest tests/test_bulkhead_props.py tests/test_bulkhead.py tests/test_bulkhead_sync.py -x --no-cov -q
```

Expected: all pass.

- [ ] **Step 5: Lint**

```bash
just lint-ci
```

Expected: green.

- [ ] **Step 6: Commit**

```bash
git add tests/test_bulkhead_props.py
git commit -m "$(cat <<'EOF'
test(bulkhead-props): replace _value peek with behavioral drain check

`test_no_slot_leak_after_drain` asserted `bulkhead._sem._value ==
max_concurrent` after a gather of n_requests. That assertion read a
CPython implementation detail of asyncio.Semaphore — non-portable across
interpreters and brittle against any future asyncio refactor.

Replace with a behavioral check: after gather completes, submit
max_concurrent fresh acquires under a tight acquire_timeout (0.05s). If
any slot leaked, the post-drain gather would block past the timeout and
BulkheadFullError would surface as a deterministic failure.

The `_acquire_timeout` override is still a private-attribute touch
(per-instance test-local config, not a CPython internal), so the
`# noqa: SLF001` annotation stays.

Closes audit Nit finding (test_bulkhead_props.py:113) from
planning/audit/2026-06-07-deep-audit.md.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `test_threading_with_shared_budget` — exact deposit count

**Files:**
- Modify: `tests/test_threading_with_shared_budget.py:74-77`

Closes audit Nit finding #4.

- [ ] **Step 1: Confirm current state**

```bash
sed -n '70,80p' tests/test_threading_with_shared_budget.py
```

Expected: the assertion `assert len(budget._deposits) > 0  # noqa: SLF001` at line 77.

- [ ] **Step 2: Tighten to exact expected total**

Note: the 0.8.3 deposit-hoist made `deposit()` fire once per `__call__`, not per attempt. The new expected count is `(N_SYNC_THREADS * N_OPS_PER_THREAD) + N_ASYNC_TASKS` = `(4 * 50) + 20` = `220`.

Use Edit tool.

old_string:
```python
    # The lock kept the budget's internal deques consistent — no IndexError, no corruption.
    # No specific count assertion: the test passes if it completes without an exception
    # from the budget itself. Add a smoke check that the budget recorded SOME activity:
    assert len(budget._deposits) > 0  # noqa: SLF001
```

new_string:
```python
    # The lock kept the budget's internal deques consistent — no IndexError, no corruption.
    # 0.8.3 deposit-hoist: deposits count requests, not attempts (one per __call__,
    # regardless of max_attempts). Budget TTL is 60.0 so no purge fires during the
    # sub-second runtime; the count is exact.
    expected_deposits = (_N_SYNC_THREADS * _N_OPS_PER_THREAD) + _N_ASYNC_TASKS
    assert len(budget._deposits) == expected_deposits, (  # noqa: SLF001
        f"expected {expected_deposits} deposits, got {len(budget._deposits)}"
    )
```

- [ ] **Step 3: Run the test**

```bash
uv run pytest tests/test_threading_with_shared_budget.py -x --no-cov -q
```

Expected: PASS. If FAIL with the exact-count assertion's message, STOP and report DONE_WITH_CONCERNS — the actual count differs from the formula (likely because the async side's `_safe_get` exception-suppression path skips the deposit somehow, which would be a real finding).

- [ ] **Step 4: Run related tests**

```bash
uv run pytest tests/test_threading_with_shared_budget.py tests/test_retry_budget_threadsafety.py tests/test_budget.py tests/test_budget_props.py -x --no-cov -q
```

Expected: all pass.

- [ ] **Step 5: Lint**

```bash
just lint-ci
```

Expected: green.

- [ ] **Step 6: Commit**

```bash
git add tests/test_threading_with_shared_budget.py
git commit -m "$(cat <<'EOF'
test(threading-budget): tighten weak deposit assertion to exact expected total

`assert len(budget._deposits) > 0` would have passed even with the
internal lock removed and the deque corrupted, as long as ONE survivor
remained. The audit's recommended tighten is to assert the exact
expected total — computable from the test constants.

After the 0.8.3 deposit-hoist, deposits count requests (not attempts),
so `(N_SYNC_THREADS * N_OPS_PER_THREAD) + N_ASYNC_TASKS` = (4*50)+20 = 220
is the exact expected. Budget TTL is 60.0s so no purge fires within the
sub-second test runtime.

If the actual count diverges, the test now surfaces it.

Closes audit Nit finding (test_threading_with_shared_budget.py:77) from
planning/audit/2026-06-07-deep-audit.md.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `test_optional_extras_pydantic_missing` — sync `Client` peer

**Files:**
- Modify: `tests/test_optional_extras_pydantic_missing.py`

Closes audit Nit finding #5.

- [ ] **Step 1: Confirm current state**

```bash
sed -n '41,55p' tests/test_optional_extras_pydantic_missing.py
```

Expected: a single `test_async_client_accepts_explicit_decoder_without_pydantic` function with an inner `class _FakeDecoder`. No sync mirror.

- [ ] **Step 2: Refactor the existing test (hoist `_FakeDecoder` to module top) + add the sync peer**

Use Edit tool.

old_string:
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

new_string:
```python
class _FakeDecoder:
    """Test stand-in for ResponseDecoder; never called at runtime."""

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

- [ ] **Step 3: Run the tests**

```bash
uv run pytest tests/test_optional_extras_pydantic_missing.py -x --no-cov -q
```

Expected: all PASS (the original async test still works with the hoisted `_FakeDecoder`; the new sync test passes because `Client(decoder=...)` bypasses the pydantic fail-fast for the same reason `AsyncClient(decoder=...)` does).

- [ ] **Step 4: Lint**

```bash
just lint-ci
```

Expected: green.

- [ ] **Step 5: Commit**

```bash
git add tests/test_optional_extras_pydantic_missing.py
git commit -m "$(cat <<'EOF'
test(optional-extras-pydantic): add sync Client peer for escape-hatch test

`test_async_client_accepts_explicit_decoder_without_pydantic` covered the
AsyncClient escape hatch (explicit `decoder=` bypasses the pydantic
fail-fast). The sync Client has the same `_default_pydantic_decoder()`
gate at the same point in `__init__`, but no test asserted the parallel
behavior.

Add `test_sync_client_accepts_explicit_decoder_without_pydantic` as the
sync mirror; hoist `_FakeDecoder` to module top to keep the two tests DRY.

Closes audit Nit finding (test_optional_extras_pydantic_missing.py:41)
from planning/audit/2026-06-07-deep-audit.md.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: New file — `tests/test_bulkhead_sync_props.py`

**Files:**
- Create: `tests/test_bulkhead_sync_props.py`

Closes audit Low finding #1 (sync `Bulkhead` Hypothesis-property parity gap).

- [ ] **Step 1: Create the new test file**

Write `tests/test_bulkhead_sync_props.py` with exactly this content:

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
    pool = ThreadPoolExecutor(max_workers=max_concurrent + extra_requests)
    holders = [pool.submit(client.get, f"https://example.test/hold-{i}") for i in range(max_concurrent)]
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

- [ ] **Step 2: Run the new file**

```bash
uv run pytest tests/test_bulkhead_sync_props.py -x --no-cov -q
```

Expected: all 3 property tests pass.

If the `max_in_flight <= max_concurrent` assertion FAILS sporadically (Hypothesis shrinks to a flaky case), the implementer should:
- First, drop `max_examples` to 10 in all three `@settings(...)` and retry.
- If still flaky, escalate as DONE_WITH_CONCERNS — the threading + MockTransport scheduling may have a deeper interaction that wants a different test design.

- [ ] **Step 3: Run the broader test suite for regressions**

```bash
uv run pytest tests/test_bulkhead_sync.py tests/test_bulkhead_sync_props.py tests/test_bulkhead.py tests/test_bulkhead_props.py -x --no-cov -q
```

Expected: all pass.

- [ ] **Step 4: Lint**

```bash
just lint-ci
```

Expected: green. The new file's structure mirrors the existing async props file's, so existing lint config should accept it without per-file ignores.

- [ ] **Step 5: Commit**

```bash
git add tests/test_bulkhead_sync_props.py
git commit -m "$(cat <<'EOF'
test(bulkhead-sync-props): Hypothesis property tests for sync Bulkhead

Adds tests/test_bulkhead_sync_props.py mirroring the async file's three
property tests, using threading.Thread + ThreadPoolExecutor + a
lock-guarded shared counter instead of asyncio.gather:

1. in_flight_never_exceeds_max_concurrent (under any thread interleaving)
2. fail_fast_rejects_when_at_capacity (acquire_timeout=0 raises BulkheadFullError)
3. no_slot_leak_after_drain (behavioral check, no _value peek)

Strategies match the async file: max_concurrent ∈ [1, 8],
n_requests ∈ [1, 32], delay ∈ [0.001, 0.005] s. Async file is unchanged;
the new file establishes sync/async parity for the resilience
property-test surface.

Closes audit Low finding (test_bulkhead_props.py:1, sync gap) from
planning/audit/2026-06-07-deep-audit.md.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: `test_on_error_lets_*_propagate` — sync mirror tests

**Files:**
- Modify: `tests/test_middleware_sync.py` (append at end of file)

Closes audit Low finding #2.

- [ ] **Step 1: Confirm imports in tests/test_middleware_sync.py**

Read the top of the file:

```bash
head -20 tests/test_middleware_sync.py
```

Confirm: `from httpware.middleware import on_error`, `from httpware.middleware.chain import compose`, `import httpx2`, `import pytest`, and helper `_make_request` are all available. (Per the read I did during planning, all of these exist at lines 1-19.)

- [ ] **Step 2: Append the two new tests at the END of `tests/test_middleware_sync.py`**

```python
def test_on_error_lets_keyboardinterrupt_propagate() -> None:
    """on_error catches Exception, NOT BaseException — KeyboardInterrupt must escape.

    Sync mirror of test_middleware.py::test_on_error_lets_cancelled_propagate. The
    async test pins asyncio.CancelledError (a BaseException). The sync world's
    equivalents are KeyboardInterrupt and SystemExit; they too must propagate.
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

- [ ] **Step 3: Run the new tests**

```bash
uv run pytest tests/test_middleware_sync.py::test_on_error_lets_keyboardinterrupt_propagate tests/test_middleware_sync.py::test_on_error_lets_systemexit_propagate -x --no-cov -q
```

Expected: both PASS. The sync `on_error` decorator (`src/httpware/middleware/__init__.py:121-143`) uses `except Exception` which does NOT catch `KeyboardInterrupt` or `SystemExit` (both inherit from `BaseException`, not `Exception`). So the BaseException propagates through `compose` cleanly and the test's `with pytest.raises(KeyboardInterrupt):` matches.

If the test FAILS, that would indicate a real bug in the sync `on_error` decorator (e.g., accidentally using `except BaseException` instead of `except Exception`). STOP and report — that would warrant a production fix, not a test-only PR.

- [ ] **Step 4: Run the full middleware test suites**

```bash
uv run pytest tests/test_middleware.py tests/test_middleware_sync.py -x --no-cov -q
```

Expected: all pass.

- [ ] **Step 5: Lint**

```bash
just lint-ci
```

Expected: green.

- [ ] **Step 6: Commit**

```bash
git add tests/test_middleware_sync.py
git commit -m "$(cat <<'EOF'
test(middleware-sync): on_error must let BaseException propagate

test_middleware.py::test_on_error_lets_cancelled_propagate pinned the
async invariant: on_error catches Exception, NOT BaseException, so
asyncio.CancelledError propagates through compose_async unchanged.

The sync `on_error` decorator has the same `except Exception` clause but
no test asserted the parallel KeyboardInterrupt / SystemExit invariant.
Add two sync mirror tests so a future regression that widens the catch
to BaseException surfaces immediately.

Closes audit Low finding (test_middleware.py:162 sync parity gap) from
planning/audit/2026-06-07-deep-audit.md.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Draft 0.8.6 release notes + open PR

**Files:**
- Create: `planning/releases/0.8.6.md`

- [ ] **Step 1: Skim the 0.8.5 release notes**

```bash
cat planning/releases/0.8.5.md
```

- [ ] **Step 2: Write `planning/releases/0.8.6.md`**

Create with exactly this content:

```markdown
# httpware 0.8.6 — test mop-up

**Patch release. Test-only changes. No API change, no production code change, no behavior change for users.** Closes 5 audit findings — all in the test suite.

## What changed

- **`test_no_slot_leak_after_drain` is behavioral, not internals-peek.** The Hypothesis property test for `AsyncBulkhead` no longer asserts against `bulkhead._sem._value`; it submits `max_concurrent` fresh acquires after drain and confirms they all succeed under a tight `acquire_timeout`.
- **`test_threading_with_shared_budget` asserts the exact deposit count.** The previous `len(budget._deposits) > 0` was a smoke check that would have passed under deque corruption with even one survivor. The new assertion locks the count to `(N_SYNC_THREADS * N_OPS_PER_THREAD) + N_ASYNC_TASKS` = 220, made deterministic by the 0.8.3 deposit-hoist.
- **`test_optional_extras_pydantic_missing.py` covers the sync `Client` escape hatch.** The async test pinned `AsyncClient(decoder=fake)` bypassing the pydantic fail-fast; the sync `Client` had no peer. Now it does. `_FakeDecoder` hoisted to module top to keep the two tests DRY.
- **Sync `Bulkhead` has Hypothesis property tests.** New file `tests/test_bulkhead_sync_props.py` mirrors `tests/test_bulkhead_props.py` using `threading.Thread` + `ThreadPoolExecutor` instead of `asyncio.gather`. Three properties: in-flight never exceeds cap; fail-fast rejects at capacity; no slot leak after drain.
- **Sync `on_error` `BaseException` propagation is tested.** Two new tests in `test_middleware_sync.py` pin the invariant that the sync `on_error` decorator's `except Exception` clause does NOT catch `KeyboardInterrupt` or `SystemExit` — both must propagate through `compose`.

## Audit status

35 audit findings, all addressed across 0.8.1 → 0.8.6 plus the in-place doc-staleness sweep on `main`. One chunk-3 hand-review item was excluded as INVALID (the audit looked for `AsyncClient` construction tests in `tests/test_client_methods.py` — they actually live in `tests/test_client_construction.py` + `tests/test_client_lifecycle.py`).

## Upgrade

```bash
uv add httpware==0.8.6
# or
pip install -U 'httpware==0.8.6'
```

No import changes. No API changes. Nothing observable from the consumer side.
```

- [ ] **Step 3: Lint**

```bash
just lint-ci
```

Expected: green. eof-fixer may add a trailing newline.

- [ ] **Step 4: Commit**

```bash
git add planning/releases/0.8.6.md
git commit -m "$(cat <<'EOF'
docs(release): draft 0.8.6 notes — test mop-up

Five test-only fixes close the last actionable audit findings: behavioral
drain check, exact threading-budget deposit total, sync Client decoder-
escape peer, sync Bulkhead Hypothesis suite, sync on_error BaseException
propagation tests. No production code change, no behavior change.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 5: Push the branch + open the PR**

```bash
git push -u origin fix/test-mop-up
```

```bash
gh pr create --base main --head fix/test-mop-up --title "test(mop-up): close 5 audit findings (0.8.6)" --body "$(cat <<'EOF'
## Summary

Closes the last 5 actionable audit findings — all in the test suite. See [\`planning/specs/2026-06-08-test-mop-up-design.md\`](planning/specs/2026-06-08-test-mop-up-design.md) for the design and [\`planning/releases/0.8.6.md\`](planning/releases/0.8.6.md) for the user-facing release notes.

## What changes

- \`test_no_slot_leak_after_drain\` is behavioral (no internals peek).
- \`test_threading_with_shared_budget\` asserts the exact deposit count.
- \`test_optional_extras_pydantic_missing\` has a sync \`Client\` peer.
- New \`tests/test_bulkhead_sync_props.py\` (Hypothesis suite for sync Bulkhead).
- Two new sync \`on_error\` BaseException propagation tests.

## Audit findings closed

| # | Severity | File:line | Closed by |
|---|---|---|---|
| 1 | Nit | \`test_bulkhead_props.py:113\` | behavioral drain check |
| 2 | Nit | \`test_threading_with_shared_budget.py:77\` | exact deposit count (220) |
| 3 | Nit | \`test_optional_extras_pydantic_missing.py:41\` | sync Client peer test |
| 4 | Low | new \`test_bulkhead_sync_props.py\` | sync Hypothesis property suite |
| 5 | Low | new \`test_middleware_sync.py\` tests | KeyboardInterrupt + SystemExit propagation |

One chunk-3 finding (\`test_client_methods.py has no construction tests\`) was excluded as INVALID — the async construction and lifecycle tests live in dedicated files, not the per-method file.

## Test plan

- [x] All new tests pass; all existing tests continue to pass.
- [x] \`just lint-ci\` green after each commit.
- [x] No production code changed (verify with \`git diff main..HEAD -- src/\`).

## Release

Tag \`0.8.6\` from the merge SHA after this PR lands.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Capture the PR URL.

- [ ] **Step 6: Final verification**

```bash
git log --oneline -10
gh pr view --json url,state,title
```

Expected: 6 commits on the branch (5 test-only + release notes); PR open.

## Reporting

Return DONE with the PR URL.

---

## Self-review notes

- **Spec coverage:** Spec finding #3 → T1; #4 → T2; #5 → T3; #1 → T4; #2 → T5. Release notes + PR → T6. All five findings covered. The INVALID finding (chunk-3 client construction tests) is explicitly excluded with rationale in T6's release notes.
- **Placeholder scan:** All code blocks complete with verbatim test bodies. Commit messages filled. No "TBD" / "similar to".
- **Type/name consistency:** `_FakeDecoder` defined at module level in T3 is used in both async and sync tests (consistent). `_InFlightHandler` in T4's new file mirrors the async file's class name (intentional). The shared counter pattern uses `_lock` consistently.
- **TDD ordering:** T1-T3 each have a verify-state step before the fix; T4 is a new-file addition with the existing async file as the reference template; T5 appends to an existing file. All tasks have "run the test" steps that establish PASS as the success criterion.
- **Risks:** T4 (threading + ThreadPoolExecutor + MockTransport) is the highest-flake risk. The plan includes escalation guidance for the implementer: drop `max_examples` to 10, then DONE_WITH_CONCERNS if still flaky.
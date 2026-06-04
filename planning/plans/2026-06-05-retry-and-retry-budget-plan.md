# Retry middleware + RetryBudget (0.4.0 slice 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the `Retry` middleware and Finagle-style `RetryBudget` token bucket. Retry automatically retries transient failures (network errors, timeouts, and selected 5xx/429/408 status codes) on idempotent methods, with exponential-with-full-jitter backoff, `Retry-After` honoring, an optional per-attempt wall-clock cap, and a budget that prevents retry storms when downstream services degrade.

**Architecture:** New `src/httpware/middleware/resilience/` subpackage holds three small, independently-testable units: `RetryBudget` (pure token-bucket math), a private `_backoff.py` helper (pure full-jitter math), and the `Retry` middleware that orchestrates them. A new `NetworkError(TransportError)` exception isolates transient-network failures from non-retryable transport failures (`InvalidURL`, `CookieConflict`), so Retry can confidently retry network blips without retrying typos. Retry sees `StatusError` subclasses as exceptions raised by the `AsyncClient` terminal (the terminal already raises on 4xx/5xx), so the retry decision for status codes lives in an `except StatusError as exc:` branch that inspects `exc.response.status_code`.

**Tech Stack:** Python 3.11+ (`asyncio.timeout()` requires 3.11), `httpx2`, `pytest` / `pytest-asyncio` (auto mode), `hypothesis`, `uv`, `just`, `ruff`, `ty`.

**Target branch:** `feat/v0.4-retry-and-budget`. Create from `main` before Task 1: `git checkout main && git pull && git checkout -b feat/v0.4-retry-and-budget`.

**Source spec:** [`planning/specs/2026-06-05-retry-and-retry-budget-design.md`](../specs/2026-06-05-retry-and-retry-budget-design.md). Read it before starting — the *why* for each decision lives there.

---

## File structure

**New files:**
- `src/httpware/middleware/resilience/__init__.py` — re-exports `Retry`, `RetryBudget`.
- `src/httpware/middleware/resilience/budget.py` — `RetryBudget` token bucket.
- `src/httpware/middleware/resilience/_backoff.py` — private full-jitter exponential helper.
- `src/httpware/middleware/resilience/retry.py` — `Retry` middleware + module-level constants + private `_parse_retry_after`.
- `tests/test_budget.py` — `RetryBudget` unit tests (deterministic `_now`).
- `tests/test_budget_props.py` — Hypothesis property tests for `RetryBudget`.
- `tests/test_retry.py` — `Retry` middleware integration tests via injected `httpx2.MockTransport`.
- `tests/test_retry_props.py` — Hypothesis property tests for `Retry`.

**Modified files:**
- `src/httpware/errors.py` — add `NetworkError(TransportError)` and `RetryBudgetExhaustedError(ClientError)`.
- `src/httpware/client.py` — refine terminal mapping to raise `NetworkError` from `httpx2`'s transient-network exception family.
- `src/httpware/__init__.py` — export `Retry`, `RetryBudget`, `RetryBudgetExhaustedError`, `NetworkError`.
- `tests/test_errors.py` — assert the two new exceptions exist and their inheritance is correct.
- `tests/test_error_mapping_terminal.py` — update existing connect-error test to expect `NetworkError` instead of bare `TransportError`; add a new test asserting `InvalidURL` still maps to bare `TransportError`.
- `tests/test_public_api.py` — add the four new symbols to the expected exports set.

**Commit cadence:** each Task ends with a `git add` + `git commit`. Per-task commits keep history reviewable; the branch is squash-mergeable.

---

## Task 1: Branch + scaffold `resilience/` subpackage

**Files:**
- Create: `src/httpware/middleware/resilience/__init__.py`
- Create: `src/httpware/middleware/resilience/budget.py` (stub)
- Create: `src/httpware/middleware/resilience/retry.py` (stub)
- Create: `src/httpware/middleware/resilience/_backoff.py` (stub)

- [ ] **Step 1: Create the branch**

Run:
```bash
git checkout main && git pull && git checkout -b feat/v0.4-retry-and-budget
```
Expected: switched to a new branch.

- [ ] **Step 2: Create the package directory and four stub files**

Run:
```bash
mkdir -p src/httpware/middleware/resilience
```

Then create each file with the contents below. Use the Write tool, not bash heredocs.

`src/httpware/middleware/resilience/__init__.py`:
```python
"""Resilience primitives: Retry middleware and RetryBudget token bucket."""

from httpware.middleware.resilience.budget import RetryBudget
from httpware.middleware.resilience.retry import Retry
```

`src/httpware/middleware/resilience/budget.py`:
```python
"""Finagle-style token-bucket retry budget. See planning/specs/2026-06-05-retry-and-retry-budget-design.md."""
```

`src/httpware/middleware/resilience/retry.py`:
```python
"""Retry middleware. See planning/specs/2026-06-05-retry-and-retry-budget-design.md."""
```

`src/httpware/middleware/resilience/_backoff.py`:
```python
"""Full-jitter exponential backoff helper (private)."""
```

- [ ] **Step 3: Verify imports load cleanly**

The package `__init__.py` references `RetryBudget` and `Retry`, neither of which exists yet. Defer importing the package itself; for this step just check the files exist.

Run:
```bash
ls src/httpware/middleware/resilience/
```
Expected: `__init__.py  _backoff.py  budget.py  retry.py`

- [ ] **Step 4: Stage and commit**

Run:
```bash
git add src/httpware/middleware/resilience/
git commit -m "scaffold(resilience): empty subpackage for Retry + RetryBudget"
```

---

## Task 2: Add `NetworkError(TransportError)` + refine terminal mapping

**Files:**
- Modify: `src/httpware/errors.py` (add class)
- Modify: `src/httpware/client.py` (refine terminal mapping)
- Modify: `tests/test_errors.py` (assert inheritance)
- Modify: `tests/test_error_mapping_terminal.py` (existing `connect_error` test now expects `NetworkError`; add new `invalid_url` assertion)

This unblocks Task 7's `Retry` middleware: without `NetworkError`, Retry can't distinguish transient network failures from non-retryable transport failures like `InvalidURL`.

- [ ] **Step 1: Write failing inheritance test in `tests/test_errors.py`**

Append to `tests/test_errors.py`:
```python
from httpware.errors import NetworkError


def test_network_error_is_transport_error() -> None:
    exc = NetworkError("connection refused")
    assert isinstance(exc, TransportError)
    assert isinstance(exc, ClientError)
```

Run: `uv run pytest tests/test_errors.py::test_network_error_is_transport_error -v`
Expected: FAIL (`ImportError: cannot import name 'NetworkError'`).

- [ ] **Step 2: Add `NetworkError` to `src/httpware/errors.py`**

Edit `src/httpware/errors.py`. Add a new class immediately after the existing `class TransportError`:
```python
class NetworkError(TransportError):
    """Transient network-layer failure (connect/read/write/pool). Safe to retry."""
```

Run: `uv run pytest tests/test_errors.py::test_network_error_is_transport_error -v`
Expected: PASS.

- [ ] **Step 3: Add a `NetworkError` import in `tests/test_error_mapping_terminal.py`**

`NetworkError` isn't exported from `httpware/__init__.py` until Task 13. Add a direct import from `httpware.errors` (a separate line from the existing `from httpware import (...)` block at the top of the file):

```python
from httpware.errors import NetworkError
```

- [ ] **Step 4: Update `test_httpx2_connect_error_maps_to_transport_error` test**

In `tests/test_error_mapping_terminal.py`, rename the test and change the assertion:
```python
async def test_httpx2_connect_error_maps_to_network_error() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        msg = "connect refused"
        raise httpx2.ConnectError(msg)

    client = _client_with_handler(handler)
    with pytest.raises(NetworkError, match="connect refused"):
        await client.send(httpx2.Request("GET", "https://example.test/x"))
```

Run: `uv run pytest tests/test_error_mapping_terminal.py::test_httpx2_connect_error_maps_to_network_error -v`
Expected: FAIL (still maps to bare `TransportError`).

- [ ] **Step 5: Refine the terminal mapping in `src/httpware/client.py`**

Update the imports block at the top of `client.py` to add `NetworkError`:
```python
from httpware.errors import (
    STATUS_TO_EXCEPTION,
    ClientStatusError,
    NetworkError,
    ServerStatusError,
    TimeoutError,  # noqa: A004
    TransportError,
)
```

Update the `_terminal` method's `except` chain. The current block:
```python
        try:
            response = await self._httpx2_client.send(request)
        except httpx2.TimeoutException as exc:
            raise TimeoutError(str(exc)) from exc
        except (httpx2.InvalidURL, httpx2.CookieConflict) as exc:
            raise TransportError(str(exc)) from exc
        except httpx2.HTTPError as exc:
            raise TransportError(str(exc)) from exc
        except RuntimeError as exc:
            if "closed" in str(exc):
                raise TransportError(str(exc)) from exc
            raise
```

Becomes:
```python
        try:
            response = await self._httpx2_client.send(request)
        except httpx2.TimeoutException as exc:
            raise TimeoutError(str(exc)) from exc
        except (httpx2.InvalidURL, httpx2.CookieConflict) as exc:
            raise TransportError(str(exc)) from exc
        except httpx2.NetworkError as exc:
            raise NetworkError(str(exc)) from exc
        except httpx2.HTTPError as exc:
            raise TransportError(str(exc)) from exc
        except RuntimeError as exc:
            if "closed" in str(exc):
                raise TransportError(str(exc)) from exc
            raise
```

The `httpx2.NetworkError` branch must come BEFORE `httpx2.HTTPError` (HTTPError is the broader base). `httpx2.NetworkError` is httpx's documented base for `ConnectError`, `ReadError`, `WriteError`, `PoolTimeout` — if `httpx2`'s symbol name differs (e.g., `httpx2.exceptions.NetworkError`), use whichever import path mirrors the existing `httpx2.ConnectError` import in `tests/test_error_mapping_terminal.py` (which works via top-level `httpx2`).

If `httpx2.NetworkError` does not exist, fall back to enumerating the transient subset explicitly: `except (httpx2.ConnectError, httpx2.ReadError, httpx2.WriteError, httpx2.PoolTimeout) as exc:`. The plan author has confirmed `httpx2.ConnectError` and `httpx2.ReadTimeout` already work in the existing tests; the enumeration fallback is safe.

- [ ] **Step 6: Run the new terminal-mapping test**

Run: `uv run pytest tests/test_error_mapping_terminal.py::test_httpx2_connect_error_maps_to_network_error -v`
Expected: PASS.

- [ ] **Step 7: Add a regression test that bare `TransportError` still applies to `InvalidURL`**

This test already exists as `test_httpx2_invalid_url_maps_to_transport_error`. Verify it still passes:

Run: `uv run pytest tests/test_error_mapping_terminal.py::test_httpx2_invalid_url_maps_to_transport_error -v`
Expected: PASS — `InvalidURL` continues to map to bare `TransportError`, NOT `NetworkError`.

- [ ] **Step 8: Add explicit assertion that `InvalidURL` does NOT map to NetworkError**

Append to `tests/test_error_mapping_terminal.py`:
```python
async def test_httpx2_invalid_url_does_not_map_to_network_error() -> None:
    """Regression: only transient errors map to NetworkError; InvalidURL stays bare TransportError."""

    def handler(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        msg = "bad url"
        raise httpx2.InvalidURL(msg)

    client = _client_with_handler(handler)
    with pytest.raises(TransportError) as info:
        await client.send(httpx2.Request("GET", "https://example.test/x"))
    assert not isinstance(info.value, NetworkError)
```

Run: `uv run pytest tests/test_error_mapping_terminal.py::test_httpx2_invalid_url_does_not_map_to_network_error -v`
Expected: PASS.

- [ ] **Step 9: Run the full error-mapping test file**

Run: `uv run pytest tests/test_error_mapping_terminal.py tests/test_errors.py -v`
Expected: all PASS.

- [ ] **Step 10: Stage and commit**

Run:
```bash
git add src/httpware/errors.py src/httpware/client.py tests/test_errors.py tests/test_error_mapping_terminal.py
git commit -m "feat(errors): add NetworkError(TransportError) for transient httpx2 failures

Refines _terminal so httpx2.NetworkError-family exceptions (ConnectError, ReadError,
WriteError, PoolTimeout) map to httpware.NetworkError. InvalidURL and CookieConflict
stay bare TransportError. Prerequisite for the Retry middleware so it can retry
transient failures without retrying typos."
```

---

## Task 3: Add `RetryBudgetExhaustedError` to errors.py

**Files:**
- Modify: `src/httpware/errors.py`
- Modify: `tests/test_errors.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_errors.py`:
```python
from httpware.errors import RetryBudgetExhaustedError


def test_retry_budget_exhausted_error_is_client_error() -> None:
    exc = RetryBudgetExhaustedError(last_response=None, last_exception=None, attempts=3)
    assert isinstance(exc, ClientError)
    assert exc.last_response is None
    assert exc.last_exception is None
    assert exc.attempts == 3


def test_retry_budget_exhausted_error_carries_last_response_and_exception() -> None:
    response = _make_response(503, url="https://example.test/x")
    inner = RuntimeError("boom")
    exc = RetryBudgetExhaustedError(last_response=response, last_exception=inner, attempts=2)
    assert exc.last_response is response
    assert exc.last_exception is inner
    assert exc.attempts == 2


def test_retry_budget_exhausted_error_summary_mentions_attempts() -> None:
    exc = RetryBudgetExhaustedError(last_response=None, last_exception=None, attempts=5)
    assert "5" in str(exc)
```

Run: `uv run pytest tests/test_errors.py::test_retry_budget_exhausted_error_is_client_error -v`
Expected: FAIL (`ImportError`).

- [ ] **Step 2: Add the class to `src/httpware/errors.py`**

Append at the end of `src/httpware/errors.py` (after the `STATUS_TO_EXCEPTION` mapping):

```python
class RetryBudgetExhaustedError(ClientError):
    """Raised when a retry was needed but the RetryBudget refused to permit it.

    Carries the last response and/or exception observed before the budget refused,
    plus the number of attempts already completed.
    """

    last_response: httpx2.Response | None
    last_exception: BaseException | None
    attempts: int

    def __init__(
        self,
        *,
        last_response: httpx2.Response | None,
        last_exception: BaseException | None,
        attempts: int,
    ) -> None:
        self.last_response = last_response
        self.last_exception = last_exception
        self.attempts = attempts
        super().__init__(f"retry budget exhausted after {attempts} attempt(s)")
```

Run: `uv run pytest tests/test_errors.py -v -k "retry_budget_exhausted"`
Expected: all three new tests PASS.

- [ ] **Step 3: Stage and commit**

Run:
```bash
git add src/httpware/errors.py tests/test_errors.py
git commit -m "feat(errors): add RetryBudgetExhaustedError

Distinct exception raised by the Retry middleware when the RetryBudget
refuses to permit a retry. Carries last_response / last_exception / attempts.
Inherits ClientError so callers catching ClientError already handle it."
```

---

## Task 4: Implement `RetryBudget` with unit tests

**Files:**
- Modify: `src/httpware/middleware/resilience/budget.py`
- Create: `tests/test_budget.py`

- [ ] **Step 1: Write failing tests in `tests/test_budget.py`**

Create `tests/test_budget.py`:
```python
"""Unit tests for RetryBudget token-bucket math.

Tests inject a deterministic `_now` callable rather than monkeypatching `time.monotonic`,
so they cannot be perturbed by other tests sharing the same module.
"""

from collections.abc import Callable

import pytest

from httpware.middleware.resilience.budget import RetryBudget


class _Clock:
    """Mutable clock for deterministic tests. Pass `clock.now` as `_now`."""

    def __init__(self, start: float = 0.0) -> None:
        self._t = start

    def now(self) -> float:
        return self._t

    def advance(self, seconds: float) -> None:
        self._t += seconds


def _budget(
    *,
    ttl: float = 10.0,
    min_retries_per_sec: float = 10.0,
    percent_can_retry: float = 0.2,
    now: Callable[[], float] | None = None,
) -> RetryBudget:
    clock = _Clock()
    return RetryBudget(
        ttl=ttl,
        min_retries_per_sec=min_retries_per_sec,
        percent_can_retry=percent_can_retry,
        _now=now if now is not None else clock.now,
    )


def test_defaults_match_spec() -> None:
    budget = RetryBudget()
    # Defaults: ttl=10.0, min_retries_per_sec=10.0, percent_can_retry=0.2
    assert budget._ttl == 10.0  # noqa: SLF001
    assert budget._min_retries_per_sec == 10.0  # noqa: SLF001
    assert budget._percent_can_retry == 0.2  # noqa: SLF001


def test_floor_permits_min_retries_per_sec_times_ttl_with_zero_deposits() -> None:
    # floor = min_retries_per_sec * ttl = 10 * 10 = 100 permitted withdrawals
    clock = _Clock()
    budget = RetryBudget(ttl=10.0, min_retries_per_sec=10.0, percent_can_retry=0.0, _now=clock.now)
    permitted = sum(1 for _ in range(101) if budget.try_withdraw())
    assert permitted == 100


def test_percent_can_retry_ceiling_with_deposits() -> None:
    # 1000 deposits * 0.2 = 200 retries permitted (plus floor 100 = 300 total)
    clock = _Clock()
    budget = RetryBudget(ttl=10.0, min_retries_per_sec=10.0, percent_can_retry=0.2, _now=clock.now)
    for _ in range(1000):
        budget.deposit()
    permitted = sum(1 for _ in range(500) if budget.try_withdraw())
    assert permitted == 300


def test_ttl_expiry_purges_old_deposits() -> None:
    clock = _Clock()
    budget = RetryBudget(ttl=1.0, min_retries_per_sec=0.0, percent_can_retry=0.5, _now=clock.now)
    for _ in range(10):
        budget.deposit()
    # 10 deposits * 0.5 = 5 retries available immediately
    assert budget.try_withdraw() is True
    # Advance past TTL; deposits expire
    clock.advance(2.0)
    # With min_retries_per_sec=0 and no live deposits, no retries permitted
    assert budget.try_withdraw() is False


def test_try_withdraw_returns_false_when_exhausted() -> None:
    clock = _Clock()
    budget = RetryBudget(ttl=10.0, min_retries_per_sec=1.0, percent_can_retry=0.0, _now=clock.now)
    # floor = 1 * 10 = 10 retries
    for _ in range(10):
        assert budget.try_withdraw() is True
    assert budget.try_withdraw() is False


def test_deposit_after_exhaustion_does_not_immediately_unblock() -> None:
    """A single deposit at 20% percent_can_retry contributes 0.2 → floor (int truncation) → 0 new retries."""
    clock = _Clock()
    budget = RetryBudget(ttl=10.0, min_retries_per_sec=1.0, percent_can_retry=0.2, _now=clock.now)
    # exhaust the floor (10)
    for _ in range(10):
        budget.try_withdraw()
    assert budget.try_withdraw() is False
    # one deposit: 1 * 0.2 = 0.2 → int() → 0
    budget.deposit()
    assert budget.try_withdraw() is False
    # 5 more deposits: 6 * 0.2 = 1.2 → int() → 1 new retry permitted
    for _ in range(5):
        budget.deposit()
    assert budget.try_withdraw() is True
    assert budget.try_withdraw() is False


def test_withdrawn_also_expires_after_ttl() -> None:
    """After TTL passes, prior withdrawals no longer count against the budget."""
    clock = _Clock()
    budget = RetryBudget(ttl=1.0, min_retries_per_sec=10.0, percent_can_retry=0.0, _now=clock.now)
    for _ in range(10):
        budget.try_withdraw()
    assert budget.try_withdraw() is False
    clock.advance(2.0)
    assert budget.try_withdraw() is True


def test_default_now_is_time_monotonic() -> None:
    """When _now is not passed, the budget uses time.monotonic by default."""
    import time

    budget = RetryBudget()
    assert budget._now is time.monotonic  # noqa: SLF001
```

Run: `uv run pytest tests/test_budget.py -v`
Expected: all FAIL with `ImportError`.

- [ ] **Step 2: Implement `RetryBudget` in `src/httpware/middleware/resilience/budget.py`**

Replace the stub with:
```python
"""Finagle-style token-bucket retry budget.

See planning/specs/2026-06-05-retry-and-retry-budget-design.md for the contract.
No locking: asyncio runs coroutines cooperatively on a single thread, so deque
mutations between await points are atomic with respect to other coroutines on
the same event loop. Cross-thread use is out of scope.
"""

import time
from collections import deque
from collections.abc import Callable


class RetryBudget:
    """Token-bucket budget bounding retry rate to prevent retry storms.

    Each request deposits a token; each retry attempts to withdraw one.
    Available retries are bounded by `percent_can_retry` of recent deposits,
    plus a `min_retries_per_sec * ttl` floor.
    """

    def __init__(
        self,
        *,
        ttl: float = 10.0,
        min_retries_per_sec: float = 10.0,
        percent_can_retry: float = 0.2,
        _now: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl = ttl
        self._min_retries_per_sec = min_retries_per_sec
        self._percent_can_retry = percent_can_retry
        self._now = _now
        self._deposits: deque[float] = deque()
        self._withdrawn: deque[float] = deque()

    def _purge(self, now: float) -> None:
        cutoff = now - self._ttl
        while self._deposits and self._deposits[0] < cutoff:
            self._deposits.popleft()
        while self._withdrawn and self._withdrawn[0] < cutoff:
            self._withdrawn.popleft()

    def deposit(self) -> None:
        """Record a request (success or failure attempt). Adds one token."""
        now = self._now()
        self._purge(now)
        self._deposits.append(now)

    def try_withdraw(self) -> bool:
        """Atomically attempt to spend one retry token.

        Returns True if a retry is permitted, False if the budget is exhausted.
        Never blocks.
        """
        now = self._now()
        self._purge(now)
        floor = int(self._min_retries_per_sec * self._ttl)
        ceiling = int(len(self._deposits) * self._percent_can_retry) + floor
        if len(self._withdrawn) >= ceiling:
            return False
        self._withdrawn.append(now)
        return True
```

- [ ] **Step 3: Run the budget tests**

Run: `uv run pytest tests/test_budget.py -v`
Expected: all PASS.

- [ ] **Step 4: Run the full lint**

Run: `uv run ruff check src/httpware/middleware/resilience/budget.py tests/test_budget.py && uv run ty check src/httpware/middleware/resilience/budget.py`
Expected: clean.

- [ ] **Step 5: Stage and commit**

Run:
```bash
git add src/httpware/middleware/resilience/budget.py tests/test_budget.py
git commit -m "feat(resilience): RetryBudget token-bucket math + tests

Finagle-style: ttl=10s, min_retries_per_sec=10, percent_can_retry=0.2.
Deterministic time via injected _now callable for tests."
```

---

## Task 5: Hypothesis property tests for `RetryBudget`

**Files:**
- Create: `tests/test_budget_props.py`

- [ ] **Step 1: Create the property-test file**

```python
"""Hypothesis property tests for RetryBudget.

Properties verified:
1. `try_withdraw()` never permits more than `floor + int(deposits * percent)` over any window.
2. After advancing the clock past `ttl`, all prior deposits expire (no retries permitted
   beyond the floor).
3. `deposit()` is monotonically non-decreasing in permitted retries (more deposits cannot
   reduce the budget).
"""

from collections.abc import Callable

from hypothesis import given, settings, strategies as st

from httpware.middleware.resilience.budget import RetryBudget


class _Clock:
    def __init__(self) -> None:
        self._t = 0.0

    def now(self) -> float:
        return self._t

    def advance(self, seconds: float) -> None:
        self._t += seconds


def _budget(
    *,
    ttl: float,
    min_retries_per_sec: float,
    percent_can_retry: float,
    now: Callable[[], float],
) -> RetryBudget:
    return RetryBudget(
        ttl=ttl,
        min_retries_per_sec=min_retries_per_sec,
        percent_can_retry=percent_can_retry,
        _now=now,
    )


@given(
    ttl=st.floats(min_value=0.1, max_value=60.0, allow_nan=False, allow_infinity=False),
    min_rps=st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False),
    percent=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    deposits=st.integers(min_value=0, max_value=10_000),
)
@settings(max_examples=200, deadline=None)
def test_try_withdraw_never_exceeds_theoretical_bound(
    ttl: float, min_rps: float, percent: float, deposits: int,
) -> None:
    clock = _Clock()
    budget = _budget(ttl=ttl, min_retries_per_sec=min_rps, percent_can_retry=percent, now=clock.now)
    for _ in range(deposits):
        budget.deposit()
    floor = int(min_rps * ttl)
    ceiling = int(deposits * percent) + floor
    permitted = 0
    # Try up to ceiling + 10 times to confirm the cap holds.
    for _ in range(ceiling + 10):
        if budget.try_withdraw():
            permitted += 1
    assert permitted <= ceiling


@given(
    ttl=st.floats(min_value=0.1, max_value=10.0, allow_nan=False, allow_infinity=False),
    deposits=st.integers(min_value=1, max_value=1000),
    percent=st.floats(min_value=0.01, max_value=1.0, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=100, deadline=None)
def test_advancing_past_ttl_purges_deposits(ttl: float, deposits: int, percent: float) -> None:
    clock = _Clock()
    budget = _budget(ttl=ttl, min_retries_per_sec=0.0, percent_can_retry=percent, now=clock.now)
    for _ in range(deposits):
        budget.deposit()
    clock.advance(ttl + 0.1)
    # After purge, no deposits remain; floor is 0 → no retries permitted.
    assert budget.try_withdraw() is False


@given(
    extra_deposits=st.integers(min_value=0, max_value=100),
)
@settings(max_examples=50, deadline=None)
def test_more_deposits_never_decreases_budget(extra_deposits: int) -> None:
    clock = _Clock()
    budget = _budget(ttl=10.0, min_retries_per_sec=1.0, percent_can_retry=0.5, now=clock.now)
    # Establish a baseline
    for _ in range(10):
        budget.deposit()
    initial_permitted = sum(1 for _ in range(100) if budget.try_withdraw())
    # Reset by creating a fresh budget with the same starting deposits + extra
    budget2 = _budget(ttl=10.0, min_retries_per_sec=1.0, percent_can_retry=0.5, now=clock.now)
    for _ in range(10 + extra_deposits):
        budget2.deposit()
    new_permitted = sum(1 for _ in range(100 + extra_deposits) if budget2.try_withdraw())
    assert new_permitted >= initial_permitted
```

Run: `uv run pytest tests/test_budget_props.py -v`
Expected: all PASS.

- [ ] **Step 2: Stage and commit**

```bash
git add tests/test_budget_props.py
git commit -m "test(resilience): Hypothesis property tests for RetryBudget"
```

---

## Task 6: Implement `_backoff.py` full-jitter helper

**Files:**
- Modify: `src/httpware/middleware/resilience/_backoff.py`

The helper is so small (one function) that a dedicated test file is overkill; coverage comes from `test_retry.py` integration tests. We add one focused unit test inline at the bottom of `test_retry.py` once Task 7 lands.

- [ ] **Step 1: Implement the helper**

Replace the stub `_backoff.py` with:
```python
"""Full-jitter exponential backoff helper (private)."""

import random
from collections.abc import Callable


def full_jitter_delay(
    attempt_index: int,
    *,
    base_delay: float,
    max_delay: float,
    _random_uniform: Callable[[float, float], float] = random.uniform,
) -> float:
    """Return a backoff delay using AWS's "full jitter" formulation.

    sleep = uniform(0, min(max_delay, base_delay * 2 ** attempt_index))

    `attempt_index` is 0 for the first retry, 1 for the second, etc.
    """
    ceiling = min(max_delay, base_delay * (2 ** attempt_index))
    return _random_uniform(0.0, ceiling)
```

- [ ] **Step 2: Quick smoke check via Python REPL**

Run:
```bash
uv run python -c "from httpware.middleware.resilience._backoff import full_jitter_delay; print(full_jitter_delay(0, base_delay=0.1, max_delay=5.0))"
```
Expected: prints a float between 0.0 and 0.1.

- [ ] **Step 3: Lint**

Run: `uv run ruff check src/httpware/middleware/resilience/_backoff.py && uv run ty check src/httpware/middleware/resilience/_backoff.py`
Expected: clean.

- [ ] **Step 4: Stage and commit**

```bash
git add src/httpware/middleware/resilience/_backoff.py
git commit -m "feat(resilience): full-jitter exponential backoff helper"
```

---

## Task 7: Implement `Retry` middleware — skeleton + status-code retry + exhaustion

**Files:**
- Modify: `src/httpware/middleware/resilience/retry.py`
- Create: `tests/test_retry.py`

This task implements the happy path (no retry needed), status-code retry on 503, idempotency gate (POST not retried by default), exhaustion (max_attempts reached → re-raise with PEP-678 note), and the module-level constants. Exception-based retry (NetworkError, TimeoutError, attempt_timeout, Retry-After, budget) come in Tasks 8-11.

- [ ] **Step 1: Write the failing tests in `tests/test_retry.py`**

Create `tests/test_retry.py`:
```python
"""Tests for the Retry middleware.

Mocks the transport via httpx2.MockTransport; injects a recording `_sleep`
callable so the suite runs instantly without freezegun.
"""

from collections.abc import Callable
from http import HTTPStatus

import httpx2
import pytest

from httpware import AsyncClient, NotFoundError, ServiceUnavailableError
from httpware.middleware.resilience.budget import RetryBudget
from httpware.middleware.resilience.retry import (
    DEFAULT_IDEMPOTENT_METHODS,
    DEFAULT_RETRY_STATUS_CODES,
    Retry,
)


class _SleepRecorder:
    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, delay: float) -> None:
        self.calls.append(delay)


class _ResponseSequence:
    """Mock-transport handler that returns a fixed sequence of responses."""

    def __init__(self, statuses: list[int]) -> None:
        self._statuses = list(statuses)
        self.calls: int = 0

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.calls += 1
        status = self._statuses.pop(0) if self._statuses else HTTPStatus.OK
        return httpx2.Response(status, request=request)


def _client(handler: Callable[[httpx2.Request], httpx2.Response], *, retry: Retry) -> AsyncClient:
    transport = httpx2.MockTransport(handler)
    return AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=transport),
        middleware=[retry],
    )


def test_default_retry_status_codes_match_spec() -> None:
    assert DEFAULT_RETRY_STATUS_CODES == frozenset({408, 429, 502, 503, 504})


def test_default_idempotent_methods_match_spec() -> None:
    assert DEFAULT_IDEMPOTENT_METHODS == frozenset({"GET", "HEAD", "OPTIONS", "PUT", "DELETE"})


async def test_succeeds_first_try_no_sleep() -> None:
    sleeper = _SleepRecorder()
    handler = _ResponseSequence([HTTPStatus.OK])
    client = _client(handler, retry=Retry(_sleep=sleeper))
    response = await client.get("https://example.test/x")
    assert response.status_code == HTTPStatus.OK
    assert handler.calls == 1
    assert sleeper.calls == []


async def test_retries_503_then_succeeds() -> None:
    sleeper = _SleepRecorder()
    handler = _ResponseSequence([HTTPStatus.SERVICE_UNAVAILABLE, HTTPStatus.OK])
    client = _client(handler, retry=Retry(_sleep=sleeper, base_delay=0.01, max_delay=0.02))
    response = await client.get("https://example.test/x")
    assert response.status_code == HTTPStatus.OK
    assert handler.calls == 2
    assert len(sleeper.calls) == 1
    assert 0.0 <= sleeper.calls[0] <= 0.02


async def test_gives_up_after_max_attempts_and_reraises_status_error() -> None:
    sleeper = _SleepRecorder()
    handler = _ResponseSequence([HTTPStatus.SERVICE_UNAVAILABLE] * 3)
    client = _client(handler, retry=Retry(_sleep=sleeper, base_delay=0.01, max_delay=0.02, max_attempts=3))
    with pytest.raises(ServiceUnavailableError) as info:
        await client.get("https://example.test/x")
    assert handler.calls == 3
    assert len(sleeper.calls) == 2  # max_attempts=3 → 2 sleeps between 3 attempts
    notes = getattr(info.value, "__notes__", [])
    assert any("gave up after 3 attempts" in note for note in notes)


async def test_does_not_retry_non_retryable_status() -> None:
    sleeper = _SleepRecorder()
    handler = _ResponseSequence([HTTPStatus.NOT_FOUND])
    client = _client(handler, retry=Retry(_sleep=sleeper))
    with pytest.raises(NotFoundError):
        await client.get("https://example.test/x")
    assert handler.calls == 1
    assert sleeper.calls == []


async def test_does_not_retry_non_idempotent_methods_by_default() -> None:
    sleeper = _SleepRecorder()
    handler = _ResponseSequence([HTTPStatus.SERVICE_UNAVAILABLE])
    client = _client(handler, retry=Retry(_sleep=sleeper))
    with pytest.raises(ServiceUnavailableError):
        await client.post("https://example.test/x", json={"x": 1})
    assert handler.calls == 1
    assert sleeper.calls == []


async def test_retries_post_when_method_explicitly_included() -> None:
    sleeper = _SleepRecorder()
    handler = _ResponseSequence([HTTPStatus.SERVICE_UNAVAILABLE, HTTPStatus.OK])
    methods = frozenset(DEFAULT_IDEMPOTENT_METHODS | {"POST"})
    client = _client(
        handler,
        retry=Retry(_sleep=sleeper, retry_methods=methods, base_delay=0.01, max_delay=0.02),
    )
    response = await client.post("https://example.test/x", json={"x": 1})
    assert response.status_code == HTTPStatus.OK
    assert handler.calls == 2


async def test_max_attempts_one_means_no_retries() -> None:
    sleeper = _SleepRecorder()
    handler = _ResponseSequence([HTTPStatus.SERVICE_UNAVAILABLE])
    client = _client(handler, retry=Retry(_sleep=sleeper, max_attempts=1))
    with pytest.raises(ServiceUnavailableError):
        await client.get("https://example.test/x")
    assert handler.calls == 1
    assert sleeper.calls == []


def test_max_attempts_zero_rejected() -> None:
    with pytest.raises(ValueError, match="max_attempts must be >= 1"):
        Retry(max_attempts=0)
```

Run: `uv run pytest tests/test_retry.py -v`
Expected: all FAIL (`ImportError` for `Retry`, `DEFAULT_RETRY_STATUS_CODES`, etc.).

- [ ] **Step 2: Implement the `Retry` middleware skeleton**

Replace the `src/httpware/middleware/resilience/retry.py` stub with:
```python
"""Retry middleware — automatic retry of transient failures with budget control.

See planning/specs/2026-06-05-retry-and-retry-budget-design.md for the full contract.

Status-code retry: the AsyncClient terminal raises StatusError subclasses on 4xx/5xx,
so Retry catches StatusError and inspects exc.response.status_code. The original
StatusError subclass is re-raised unwrapped on exhaustion, with a PEP 678 note added.
"""

import asyncio
from collections.abc import Awaitable, Callable
from http import HTTPStatus

import httpx2

from httpware.errors import RetryBudgetExhaustedError, StatusError
from httpware.middleware import Next
from httpware.middleware.resilience._backoff import full_jitter_delay
from httpware.middleware.resilience.budget import RetryBudget


DEFAULT_RETRY_STATUS_CODES = frozenset({
    int(HTTPStatus.REQUEST_TIMEOUT),
    int(HTTPStatus.TOO_MANY_REQUESTS),
    int(HTTPStatus.BAD_GATEWAY),
    int(HTTPStatus.SERVICE_UNAVAILABLE),
    int(HTTPStatus.GATEWAY_TIMEOUT),
})

DEFAULT_IDEMPOTENT_METHODS = frozenset({
    "GET", "HEAD", "OPTIONS", "PUT", "DELETE",
})

_MAX_ATTEMPTS_INVALID = "max_attempts must be >= 1"


class Retry:
    """Retry middleware. See module docstring for default policy."""

    def __init__(
        self,
        *,
        max_attempts: int = 3,
        base_delay: float = 0.1,
        max_delay: float = 5.0,
        attempt_timeout: float | None = None,
        retry_status_codes: frozenset[int] = DEFAULT_RETRY_STATUS_CODES,
        retry_methods: frozenset[str] = DEFAULT_IDEMPOTENT_METHODS,
        respect_retry_after: bool = True,
        budget: RetryBudget | None = None,
        _sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if max_attempts < 1:
            raise ValueError(_MAX_ATTEMPTS_INVALID)
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.attempt_timeout = attempt_timeout
        self.retry_status_codes = retry_status_codes
        self.retry_methods = retry_methods
        self.respect_retry_after = respect_retry_after
        self.budget = budget if budget is not None else RetryBudget()
        self._sleep = _sleep

    async def __call__(self, request: httpx2.Request, next: Next) -> httpx2.Response:  # noqa: A002
        """Process a request through the retry loop. See module docstring."""
        method_eligible = request.method.upper() in self.retry_methods
        last_exc: BaseException | None = None
        last_response: httpx2.Response | None = None

        for attempt in range(self.max_attempts):
            is_last = attempt + 1 >= self.max_attempts
            self.budget.deposit()
            try:
                return await next(request)
            except StatusError as exc:
                if not method_eligible or exc.response.status_code not in self.retry_status_codes:
                    raise
                last_exc = exc
                last_response = exc.response

            # ---- retryable failure path
            if is_last:
                assert last_exc is not None  # noqa: S101 — invariant from the except branch
                last_exc.add_note(f"httpware: gave up after {attempt + 1} attempts")
                raise last_exc

            if not self.budget.try_withdraw():
                raise RetryBudgetExhaustedError(
                    last_response=last_response,
                    last_exception=last_exc,
                    attempts=attempt + 1,
                ) from last_exc

            delay = full_jitter_delay(attempt, base_delay=self.base_delay, max_delay=self.max_delay)
            await self._sleep(delay)

        raise AssertionError("unreachable")  # pragma: no cover
```

- [ ] **Step 3: Run the Task 7 tests**

Run: `uv run pytest tests/test_retry.py -v`
Expected: all PASS.

- [ ] **Step 4: Lint**

Run: `uv run ruff check src/httpware/middleware/resilience/retry.py tests/test_retry.py && uv run ty check src/httpware/middleware/resilience/retry.py`
Expected: clean. If ruff flags `Callable` / `Awaitable` import paths, adjust per existing project pattern (see `middleware/__init__.py` which uses `from collections.abc import Awaitable, Callable`).

- [ ] **Step 5: Stage and commit**

```bash
git add src/httpware/middleware/resilience/retry.py tests/test_retry.py
git commit -m "feat(resilience): Retry middleware — status-code retry + exhaustion

Covers: happy path, 503-then-200, max_attempts exhaustion with PEP-678 note,
idempotency gate (POST not retried by default, opt-in via retry_methods),
non-retryable status passthrough (404 raised immediately).
Exception-based retry, attempt_timeout, Retry-After, and budget integration
follow in subsequent commits."
```

---

## Task 8: `Retry` — exception-based retry (NetworkError, TimeoutError, bare TransportError passthrough)

**Files:**
- Modify: `src/httpware/middleware/resilience/retry.py`
- Modify: `tests/test_retry.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_retry.py` (NetworkError isn't on `httpware/__init__.py` until Task 13, so import from `httpware.errors` directly):

```python
from httpware import TransportError
from httpware.errors import NetworkError, TimeoutError as HttpwareTimeoutError


async def test_retries_on_network_error() -> None:
    sleeper = _SleepRecorder()
    call_count = {"n": 0}

    def handler(request: httpx2.Request) -> httpx2.Response:
        call_count["n"] += 1
        if call_count["n"] < 2:
            msg = "transient"
            raise httpx2.ConnectError(msg)
        return httpx2.Response(HTTPStatus.OK, request=request)

    client = _client(handler, retry=Retry(_sleep=sleeper, base_delay=0.01, max_delay=0.02))
    response = await client.get("https://example.test/x")
    assert response.status_code == HTTPStatus.OK
    assert call_count["n"] == 2
    assert len(sleeper.calls) == 1


async def test_retries_on_httpware_timeout_error() -> None:
    sleeper = _SleepRecorder()
    call_count = {"n": 0}

    def handler(request: httpx2.Request) -> httpx2.Response:
        call_count["n"] += 1
        if call_count["n"] < 2:
            msg = "read timeout"
            raise httpx2.ReadTimeout(msg)
        return httpx2.Response(HTTPStatus.OK, request=request)

    client = _client(handler, retry=Retry(_sleep=sleeper, base_delay=0.01, max_delay=0.02))
    response = await client.get("https://example.test/x")
    assert response.status_code == HTTPStatus.OK
    assert call_count["n"] == 2


async def test_does_not_retry_on_bare_transport_error_like_invalid_url() -> None:
    sleeper = _SleepRecorder()

    def handler(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        msg = "bad url"
        raise httpx2.InvalidURL(msg)

    client = _client(handler, retry=Retry(_sleep=sleeper))
    with pytest.raises(TransportError) as info:
        await client.get("https://example.test/x")
    assert not isinstance(info.value, NetworkError)
    assert sleeper.calls == []


async def test_network_error_exhaustion_reraises_with_note() -> None:
    sleeper = _SleepRecorder()

    def handler(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        msg = "never works"
        raise httpx2.ConnectError(msg)

    client = _client(handler, retry=Retry(_sleep=sleeper, max_attempts=2, base_delay=0.01, max_delay=0.02))
    with pytest.raises(NetworkError) as info:
        await client.get("https://example.test/x")
    notes = getattr(info.value, "__notes__", [])
    assert any("gave up after 2 attempts" in note for note in notes)


async def test_does_not_retry_network_error_on_non_idempotent_method() -> None:
    sleeper = _SleepRecorder()
    call_count = {"n": 0}

    def handler(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        call_count["n"] += 1
        msg = "transient"
        raise httpx2.ConnectError(msg)

    client = _client(handler, retry=Retry(_sleep=sleeper))
    with pytest.raises(NetworkError):
        await client.post("https://example.test/x", json={"x": 1})
    assert call_count["n"] == 1
    assert sleeper.calls == []
```

Run: `uv run pytest tests/test_retry.py -v -k "network_error or transport_error or timeout"`
Expected: tests FAIL — current Retry only catches `StatusError`, not network/timeout exceptions.

- [ ] **Step 2: Extend the `except` chain in `Retry.__call__`**

Update the `try`/`except` block. Add an additional import at the top of `retry.py`:
```python
from httpware.errors import NetworkError, RetryBudgetExhaustedError, StatusError, TimeoutError  # noqa: A004
```

Replace the `try`/`except` block inside the for-loop with:
```python
            try:
                return await next(request)
            except StatusError as exc:
                if not method_eligible or exc.response.status_code not in self.retry_status_codes:
                    raise
                last_exc = exc
                last_response = exc.response
            except (NetworkError, TimeoutError) as exc:
                if not method_eligible:
                    raise
                last_exc = exc
                last_response = None
```

- [ ] **Step 3: Run the tests**

Run: `uv run pytest tests/test_retry.py -v`
Expected: all PASS, including the new exception-retry tests.

- [ ] **Step 4: Stage and commit**

```bash
git add src/httpware/middleware/resilience/retry.py tests/test_retry.py
git commit -m "feat(resilience): Retry — network/timeout exception retry

Retries NetworkError and TimeoutError on idempotent methods.
Bare TransportError (e.g., InvalidURL) is NOT retried since it
escaped the NetworkError refinement in errors.py."
```

---

## Task 9: `Retry` — `attempt_timeout` (asyncio.timeout → httpware.TimeoutError)

**Files:**
- Modify: `src/httpware/middleware/resilience/retry.py`
- Modify: `tests/test_retry.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_retry.py`:
```python
async def test_attempt_timeout_fires_and_retries() -> None:
    sleeper = _SleepRecorder()
    call_count = {"n": 0}

    async def handler_async(request: httpx2.Request) -> httpx2.Response:
        call_count["n"] += 1
        if call_count["n"] < 2:
            await asyncio.sleep(1.0)  # exceeds attempt_timeout
        return httpx2.Response(HTTPStatus.OK, request=request)

    # MockTransport's handler can be async; route through httpx2.MockTransport.
    transport = httpx2.MockTransport(handler_async)
    client = AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=transport),
        middleware=[Retry(_sleep=sleeper, attempt_timeout=0.05, base_delay=0.01, max_delay=0.02)],
    )
    response = await client.get("https://example.test/x")
    assert response.status_code == HTTPStatus.OK
    assert call_count["n"] == 2


async def test_attempt_timeout_exhaustion_raises_httpware_timeout() -> None:
    sleeper = _SleepRecorder()

    async def slow_handler(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        await asyncio.sleep(1.0)
        msg = "should not reach"
        raise AssertionError(msg)  # pragma: no cover

    transport = httpx2.MockTransport(slow_handler)
    client = AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=transport),
        middleware=[Retry(_sleep=sleeper, attempt_timeout=0.05, max_attempts=2, base_delay=0.01, max_delay=0.02)],
    )
    with pytest.raises(HttpwareTimeoutError) as info:
        await client.get("https://example.test/x")
    notes = getattr(info.value, "__notes__", [])
    assert any("gave up after 2 attempts" in note for note in notes)


async def test_attempt_timeout_does_not_retry_on_non_idempotent_method() -> None:
    sleeper = _SleepRecorder()

    async def slow_handler(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        await asyncio.sleep(1.0)
        msg = "should not reach"
        raise AssertionError(msg)  # pragma: no cover

    transport = httpx2.MockTransport(slow_handler)
    client = AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=transport),
        middleware=[Retry(_sleep=sleeper, attempt_timeout=0.05)],
    )
    with pytest.raises(HttpwareTimeoutError):
        await client.post("https://example.test/x", json={"x": 1})
    assert sleeper.calls == []  # not retried
```

Add `import asyncio` to the test imports at the top of `tests/test_retry.py` if not already present.

Run: `uv run pytest tests/test_retry.py -v -k "attempt_timeout"`
Expected: FAIL — Retry doesn't wrap `next(request)` in `asyncio.timeout()` yet.

- [ ] **Step 2: Wrap the call in `asyncio.timeout()` and catch `asyncio.TimeoutError`**

Inside `Retry.__call__`, replace the `try` block:
```python
            try:
                if self.attempt_timeout is not None:
                    async with asyncio.timeout(self.attempt_timeout):
                        return await next(request)
                else:
                    return await next(request)
            except StatusError as exc:
                if not method_eligible or exc.response.status_code not in self.retry_status_codes:
                    raise
                last_exc = exc
                last_response = exc.response
            except (NetworkError, TimeoutError) as exc:
                if not method_eligible:
                    raise
                last_exc = exc
                last_response = None
            except asyncio.TimeoutError as exc:
                wrapped = TimeoutError("attempt timed out")
                wrapped.__cause__ = exc
                if not method_eligible:
                    raise wrapped from exc
                last_exc = wrapped
                last_response = None
```

NOTE: `asyncio.TimeoutError` is an alias for `builtins.TimeoutError` in Python 3.11+. `httpware.TimeoutError` ALSO inherits from `builtins.TimeoutError`. So `except asyncio.TimeoutError` would also catch the `httpware.TimeoutError` from the second except — but Python tries the except clauses in order, so the more-specific `(NetworkError, TimeoutError)` branch handles `httpware.TimeoutError` first.

However, there's a subtlety: `asyncio.timeout()` raises `asyncio.TimeoutError`, which IS the same class as `builtins.TimeoutError` in 3.11+. `httpware.TimeoutError` is a SUBCLASS of `builtins.TimeoutError`. So `except (NetworkError, TimeoutError)` catches `httpware.TimeoutError` and any `httpware.TimeoutError` raised below (e.g., from the terminal mapping httpx2.ReadTimeout). The bare `asyncio.TimeoutError` raised by `asyncio.timeout()` is caught by the third clause `except asyncio.TimeoutError`. Order matters.

If `httpx2.TimeoutException` from the terminal is mapped to `httpware.TimeoutError` (it is), and `httpware.TimeoutError` is a subclass of `builtins.TimeoutError`, then `except asyncio.TimeoutError` would catch it too if the second clause is removed. The second clause must stay so we don't wrap an already-`httpware.TimeoutError` again.

- [ ] **Step 3: Run the tests**

Run: `uv run pytest tests/test_retry.py -v`
Expected: all PASS.

- [ ] **Step 4: Stage and commit**

```bash
git add src/httpware/middleware/resilience/retry.py tests/test_retry.py
git commit -m "feat(resilience): Retry.attempt_timeout (wall-clock per-attempt cap)

Wraps each attempt in asyncio.timeout(); maps asyncio.TimeoutError to
httpware.TimeoutError. Caught timeouts count as retryable failures
subject to the idempotency + attempt-count gates."
```

---

## Task 10: `Retry` — `Retry-After` honoring (int, HTTP-date, cap, malformed)

**Files:**
- Modify: `src/httpware/middleware/resilience/retry.py`
- Modify: `tests/test_retry.py`

- [ ] **Step 1: Add imports + failing tests**

At the TOP of `tests/test_retry.py` (with the other top-level imports — ruff E402 will flag mid-file imports), add:
```python
import datetime
import email.utils
```

Then append to the bottom of `tests/test_retry.py`:
```python
async def test_retry_after_seconds_overrides_backoff() -> None:
    sleeper = _SleepRecorder()
    handler = _ResponseSequenceWithHeaders([
        (HTTPStatus.SERVICE_UNAVAILABLE, {"Retry-After": "2"}),
        (HTTPStatus.OK, {}),
    ])
    client = _client(handler, retry=Retry(_sleep=sleeper, base_delay=0.01, max_delay=5.0))
    response = await client.get("https://example.test/x")
    assert response.status_code == HTTPStatus.OK
    assert sleeper.calls == [2.0]  # Retry-After overrode the backoff


async def test_retry_after_http_date_overrides_backoff() -> None:
    sleeper = _SleepRecorder()
    future = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=3)
    http_date = email.utils.format_datetime(future, usegmt=True)
    handler = _ResponseSequenceWithHeaders([
        (HTTPStatus.SERVICE_UNAVAILABLE, {"Retry-After": http_date}),
        (HTTPStatus.OK, {}),
    ])
    client = _client(handler, retry=Retry(_sleep=sleeper, base_delay=0.01, max_delay=10.0))
    response = await client.get("https://example.test/x")
    assert response.status_code == HTTPStatus.OK
    assert len(sleeper.calls) == 1
    assert 2.0 <= sleeper.calls[0] <= 4.0  # ~3 seconds, with clock-skew tolerance


async def test_retry_after_capped_at_max_delay() -> None:
    sleeper = _SleepRecorder()
    handler = _ResponseSequenceWithHeaders([
        (HTTPStatus.SERVICE_UNAVAILABLE, {"Retry-After": "9999"}),
        (HTTPStatus.OK, {}),
    ])
    client = _client(handler, retry=Retry(_sleep=sleeper, base_delay=0.01, max_delay=2.5))
    await client.get("https://example.test/x")
    assert sleeper.calls == [2.5]  # capped


async def test_malformed_retry_after_falls_back_to_backoff() -> None:
    sleeper = _SleepRecorder()
    handler = _ResponseSequenceWithHeaders([
        (HTTPStatus.SERVICE_UNAVAILABLE, {"Retry-After": "not-a-number"}),
        (HTTPStatus.OK, {}),
    ])
    client = _client(handler, retry=Retry(_sleep=sleeper, base_delay=0.01, max_delay=0.05))
    await client.get("https://example.test/x")
    assert len(sleeper.calls) == 1
    assert 0.0 <= sleeper.calls[0] <= 0.05


async def test_respect_retry_after_false_ignores_header() -> None:
    sleeper = _SleepRecorder()
    handler = _ResponseSequenceWithHeaders([
        (HTTPStatus.SERVICE_UNAVAILABLE, {"Retry-After": "5"}),
        (HTTPStatus.OK, {}),
    ])
    client = _client(
        handler,
        retry=Retry(_sleep=sleeper, respect_retry_after=False, base_delay=0.01, max_delay=0.02),
    )
    await client.get("https://example.test/x")
    assert 0.0 <= sleeper.calls[0] <= 0.02  # backoff range, not 5
```

Add at the top of `tests/test_retry.py`:
```python
class _ResponseSequenceWithHeaders:
    """Mock handler that returns (status, headers) tuples in sequence."""

    def __init__(self, responses: list[tuple[int, dict[str, str]]]) -> None:
        self._responses = list(responses)
        self.calls = 0

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.calls += 1
        status, headers = self._responses.pop(0)
        return httpx2.Response(status, request=request, headers=headers)
```

Run: `uv run pytest tests/test_retry.py -v -k "retry_after or respect_retry_after"`
Expected: FAIL.

- [ ] **Step 2: Add the `_parse_retry_after` helper to `retry.py`**

Add this module-level private function near the top of `retry.py` (after the constants):
```python
import datetime
import email.utils


def _parse_retry_after(value: str) -> float | None:
    """Parse a Retry-After header value. Returns None on malformed input."""
    try:
        return float(int(value))
    except ValueError:
        pass
    try:
        parsed = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if parsed is None:
        return None
    now = datetime.datetime.now(datetime.timezone.utc)
    delta = (parsed - now).total_seconds()
    return max(0.0, delta)
```

- [ ] **Step 3: Use `_parse_retry_after` in the retry loop**

Inside `Retry.__call__`, after the except chain, BEFORE the budget/sleep block, compute the effective delay:

Replace the existing sleep computation:
```python
            delay = full_jitter_delay(attempt, base_delay=self.base_delay, max_delay=self.max_delay)
            await self._sleep(delay)
```

With:
```python
            retry_after: float | None = None
            if self.respect_retry_after and last_response is not None:
                header = last_response.headers.get("Retry-After")
                if header is not None:
                    retry_after = _parse_retry_after(header)

            if retry_after is not None:
                delay = min(retry_after, self.max_delay)
            else:
                delay = full_jitter_delay(
                    attempt, base_delay=self.base_delay, max_delay=self.max_delay,
                )
            await self._sleep(delay)
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_retry.py -v`
Expected: all PASS.

- [ ] **Step 5: Stage and commit**

```bash
git add src/httpware/middleware/resilience/retry.py tests/test_retry.py
git commit -m "feat(resilience): Retry honors Retry-After header (seconds + HTTP-date)

Parsed delay overrides backoff and is capped at max_delay. Malformed values
fall back to backoff. respect_retry_after=False disables the override."
```

---

## Task 11: `Retry` — budget gate + sharing across instances

**Files:**
- Modify: `src/httpware/middleware/resilience/retry.py`
- Modify: `tests/test_retry.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_retry.py`:
```python
from httpware.errors import RetryBudgetExhaustedError


def _zero_budget() -> RetryBudget:
    """A budget that always refuses withdrawal (floor=0, percent=0)."""
    return RetryBudget(ttl=10.0, min_retries_per_sec=0.0, percent_can_retry=0.0)


async def test_budget_exhausted_raises_specific_exception() -> None:
    sleeper = _SleepRecorder()
    handler = _ResponseSequence([HTTPStatus.SERVICE_UNAVAILABLE, HTTPStatus.OK])
    client = _client(
        handler,
        retry=Retry(_sleep=sleeper, budget=_zero_budget(), base_delay=0.01, max_delay=0.02),
    )
    with pytest.raises(RetryBudgetExhaustedError) as info:
        await client.get("https://example.test/x")
    assert info.value.attempts == 1  # one attempt made, budget refused before retry
    assert info.value.last_response is not None
    assert info.value.last_response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
    assert isinstance(info.value.last_exception, ServiceUnavailableError)


async def test_budget_exhausted_on_network_error_carries_exception_not_response() -> None:
    sleeper = _SleepRecorder()

    def handler(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        msg = "transient"
        raise httpx2.ConnectError(msg)

    client = _client(
        handler,
        retry=Retry(_sleep=sleeper, budget=_zero_budget(), base_delay=0.01, max_delay=0.02),
    )
    with pytest.raises(RetryBudgetExhaustedError) as info:
        await client.get("https://example.test/x")
    assert info.value.last_response is None
    assert isinstance(info.value.last_exception, NetworkError)


async def test_default_budget_is_fresh_per_instance() -> None:
    r1 = Retry()
    r2 = Retry()
    assert r1.budget is not r2.budget


async def test_explicit_budget_shared_across_retry_instances() -> None:
    shared = RetryBudget(ttl=10.0, min_retries_per_sec=1.0, percent_can_retry=0.0)
    r1 = Retry(budget=shared)
    r2 = Retry(budget=shared)
    assert r1.budget is r2.budget
    # 10 retries total before exhaustion (floor=10)
    for _ in range(10):
        assert shared.try_withdraw() is True
    assert shared.try_withdraw() is False
```

Run: `uv run pytest tests/test_retry.py -v -k "budget"`
Expected: tests reference behavior already in the impl from Task 7 — most should PASS. The fresh-per-instance and sharing tests pass trivially. The `budget_exhausted_*` tests should already pass since Task 7 wired `RetryBudgetExhaustedError`. If they fail, it's because the budget never refuses a withdrawal with default settings; the `_zero_budget()` fixture above ensures refusal.

If `test_budget_exhausted_on_network_error_carries_exception_not_response` fails, check that the `(NetworkError, TimeoutError)` except branch in Task 8 correctly sets `last_exc = exc; last_response = None`.

- [ ] **Step 2: Run the tests; fix anything that fails**

Run: `uv run pytest tests/test_retry.py -v -k "budget"`
Expected: all PASS.

- [ ] **Step 3: Stage and commit (only if changes were needed)**

If tests pass without code changes, this commit just adds the budget tests:
```bash
git add tests/test_retry.py
git commit -m "test(resilience): Retry budget gate + sharing across instances"
```

If you needed to fix the impl, include `src/httpware/middleware/resilience/retry.py` in the add.

---

## Task 12: Hypothesis property tests for `Retry`

**Files:**
- Create: `tests/test_retry_props.py`

- [ ] **Step 1: Create the property-test file**

```python
"""Hypothesis property tests for Retry.

Properties verified:
1. Total attempts never exceed max_attempts.
2. Total sleep time never exceeds max_attempts * max_delay.
3. Non-retryable statuses (NOT in retry_status_codes) cause exactly one attempt.
4. Non-idempotent methods (NOT in retry_methods) cause exactly one attempt,
   regardless of response status.
"""

from http import HTTPStatus

import httpx2
from hypothesis import given, settings, strategies as st

from httpware import AsyncClient
from httpware.middleware.resilience.budget import RetryBudget
from httpware.middleware.resilience.retry import (
    DEFAULT_IDEMPOTENT_METHODS,
    DEFAULT_RETRY_STATUS_CODES,
    Retry,
)


class _SleepRecorder:
    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, delay: float) -> None:
        self.calls.append(delay)


def _always_status(status: int) -> httpx2.MockTransport:
    return httpx2.MockTransport(lambda req: httpx2.Response(status, request=req))


_RETRYABLE_STATUS_STRATEGY = st.sampled_from(sorted(DEFAULT_RETRY_STATUS_CODES))
_NON_RETRYABLE_STATUS_STRATEGY = st.sampled_from([
    HTTPStatus.BAD_REQUEST, HTTPStatus.UNAUTHORIZED, HTTPStatus.NOT_FOUND, HTTPStatus.CONFLICT,
])
_IDEMPOTENT_METHODS = st.sampled_from(sorted(DEFAULT_IDEMPOTENT_METHODS))
_NON_IDEMPOTENT_METHODS = st.sampled_from(["POST", "PATCH"])


@given(
    max_attempts=st.integers(min_value=1, max_value=5),
    status=_RETRYABLE_STATUS_STRATEGY,
    method=_IDEMPOTENT_METHODS,
)
@settings(max_examples=50, deadline=None)
async def test_total_attempts_never_exceeds_max_attempts(
    max_attempts: int, status: int, method: str,
) -> None:
    sleeper = _SleepRecorder()
    call_count = {"n": 0}

    def handler(request: httpx2.Request) -> httpx2.Response:
        call_count["n"] += 1
        return httpx2.Response(status, request=request)

    transport = httpx2.MockTransport(handler)
    client = AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=transport),
        middleware=[Retry(
            _sleep=sleeper,
            max_attempts=max_attempts,
            base_delay=0.001,
            max_delay=0.002,
            budget=RetryBudget(ttl=60.0, min_retries_per_sec=1000.0),
        )],
    )
    try:
        await client.request(method, "https://example.test/x")
    except Exception:  # noqa: BLE001 — we only care about call count
        pass
    assert call_count["n"] <= max_attempts


@given(
    max_attempts=st.integers(min_value=1, max_value=5),
    base_delay=st.floats(min_value=0.001, max_value=0.01),
    max_delay=st.floats(min_value=0.001, max_value=0.05),
)
@settings(max_examples=30, deadline=None)
async def test_total_sleep_never_exceeds_max_attempts_times_max_delay(
    max_attempts: int, base_delay: float, max_delay: float,
) -> None:
    sleeper = _SleepRecorder()
    transport = _always_status(HTTPStatus.SERVICE_UNAVAILABLE)
    client = AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=transport),
        middleware=[Retry(
            _sleep=sleeper,
            max_attempts=max_attempts,
            base_delay=base_delay,
            max_delay=max_delay,
            budget=RetryBudget(ttl=60.0, min_retries_per_sec=1000.0),
        )],
    )
    try:
        await client.get("https://example.test/x")
    except Exception:  # noqa: BLE001
        pass
    total = sum(sleeper.calls)
    assert total <= max_attempts * max_delay + 1e-9


@given(
    status=_NON_RETRYABLE_STATUS_STRATEGY,
    method=_IDEMPOTENT_METHODS,
)
@settings(max_examples=30, deadline=None)
async def test_non_retryable_status_causes_one_attempt(status: int, method: str) -> None:
    sleeper = _SleepRecorder()
    call_count = {"n": 0}

    def handler(request: httpx2.Request) -> httpx2.Response:
        call_count["n"] += 1
        return httpx2.Response(status, request=request)

    transport = httpx2.MockTransport(handler)
    client = AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=transport),
        middleware=[Retry(_sleep=sleeper, max_attempts=3, base_delay=0.001, max_delay=0.002)],
    )
    try:
        await client.request(method, "https://example.test/x")
    except Exception:  # noqa: BLE001
        pass
    assert call_count["n"] == 1
    assert sleeper.calls == []


@given(
    status=_RETRYABLE_STATUS_STRATEGY,
    method=_NON_IDEMPOTENT_METHODS,
)
@settings(max_examples=30, deadline=None)
async def test_non_idempotent_method_causes_one_attempt(status: int, method: str) -> None:
    sleeper = _SleepRecorder()
    call_count = {"n": 0}

    def handler(request: httpx2.Request) -> httpx2.Response:
        call_count["n"] += 1
        return httpx2.Response(status, request=request)

    transport = httpx2.MockTransport(handler)
    client = AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=transport),
        middleware=[Retry(_sleep=sleeper, max_attempts=3, base_delay=0.001, max_delay=0.002)],
    )
    try:
        await client.request(method, "https://example.test/x")
    except Exception:  # noqa: BLE001
        pass
    assert call_count["n"] == 1
    assert sleeper.calls == []
```

Run: `uv run pytest tests/test_retry_props.py -v`
Expected: all PASS.

- [ ] **Step 2: Stage and commit**

```bash
git add tests/test_retry_props.py
git commit -m "test(resilience): Hypothesis property tests for Retry"
```

---

## Task 13: Public API exports + final verification

**Files:**
- Modify: `src/httpware/__init__.py`
- Modify: `tests/test_public_api.py`
- Modify: `tests/test_optional_extras_isolation.py` (only if it asserts a closed set)

- [ ] **Step 1: Read the current public API**

Run: `cat src/httpware/__init__.py`

Note the existing pattern: imports grouped by source module, then `__all__` lists every exported name alphabetically.

- [ ] **Step 2: Add the four new symbols to `httpware/__init__.py`**

Update the imports block to add `NetworkError` and `RetryBudgetExhaustedError` to the `from httpware.errors import (...)` block (alphabetical order).

Add a new import after the existing `from httpware.middleware import ...` line:
```python
from httpware.middleware.resilience import Retry, RetryBudget
```

Add the four new symbols to `__all__` in alphabetical order:
- `"NetworkError"`
- `"Retry"`
- `"RetryBudget"`
- `"RetryBudgetExhaustedError"`

- [ ] **Step 3: Read and update the public-API test**

Run: `cat tests/test_public_api.py`

The test most likely asserts `set(httpware.__all__) == EXPECTED_SET`. Add the four new symbols to `EXPECTED_SET`.

- [ ] **Step 4: Run the public-API test**

Run: `uv run pytest tests/test_public_api.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full test suite with coverage gate**

Run: `just test` (or `uv run pytest`)
Expected: ALL tests PASS, coverage ≥ 100%.

If coverage falls below 100%, add targeted tests for the uncovered branches. Common offenders:
- `_parse_retry_after` malformed-date branch (parsedate_to_datetime returning None, raising TypeError, raising ValueError) — add explicit-value tests
- The `raise AssertionError("unreachable")` branch (covered by `# pragma: no cover`)
- The `assert last_exc is not None` invariant (covered structurally by the except branches)

- [ ] **Step 6: Run the full lint**

Run: `just lint-ci` (or `uv run ruff format . --check && uv run ruff check . && uv run ty check`)
Expected: clean.

- [ ] **Step 7: Verify the architecture invariants from `CLAUDE.md`**

Run each in turn:
```bash
grep -rE 'httpx2\._' src/httpware/ || echo "PASS: no httpx2 private API"
grep -rE 'from __future__ import annotations' src/httpware/ || echo "PASS: no __future__ annotations"
grep -rE '\bprint\(' src/httpware/ || echo "PASS: no print()"
grep -rE 'logging\.(basicConfig|getLogger)\(\)' src/httpware/ || echo "PASS: no global logging"
grep -rE '# (type|mypy): ignore' src/httpware/ || echo "PASS: no type/mypy ignore"
```

Each should print the `PASS` line (the grep returns no matches).

- [ ] **Step 8: Verify the optional-extras isolation invariant**

The `Retry` middleware lives in core (no extra). Verify importing httpware doesn't pull in pydantic/msgspec/otel:
```bash
uv run pytest tests/test_optional_extras_isolation.py -v
```
Expected: PASS.

- [ ] **Step 9: Stage and commit**

```bash
git add src/httpware/__init__.py tests/test_public_api.py
git commit -m "feat(api): export Retry, RetryBudget, RetryBudgetExhaustedError, NetworkError

Completes the 0.4.0 slice 1: retry middleware + Finagle-style budget
+ NetworkError refinement for transient httpx2 failures."
```

- [ ] **Step 10: Update `planning/engineering.md` §8 to reflect the slice landing**

Open `planning/engineering.md`, find §8 "Remaining roadmap", under the "Surviving" subsection. Move stories 3-1 (dissolved), 3-2, 3-3, 3-4 out of the "land in subsequent PRs" list. Add a brief note that these landed in the v0.4 slice, similar to how the v0.2/v0.3 sections track shipped work.

Also: under the architecture invariants table (CI-enforced, §2), no changes needed — `NetworkError` does not introduce a new invariant.

Add the streaming-body deferred entry to `planning/deferred-work.md`:
```markdown
### Retry + streaming bodies (Epic 4 interaction)

- **`Retry` re-invokes `next(request)` with the same `httpx2.Request` on each attempt.** Safe for in-memory bytes/JSON bodies; unsafe for streaming/async-iterable bodies (consumed iterator can't replay). When Epic 4 ships `AsyncClient.stream` (`4-3`), Retry needs to refuse to retry streamed-body requests (or document that callers supply a body factory). Spec: `planning/specs/2026-06-05-retry-and-retry-budget-design.md` §"Open questions".
```

- [ ] **Step 11: Final commit**

```bash
git add planning/engineering.md planning/deferred-work.md
git commit -m "docs(planning): track retry+budget landing + streaming deferred follow-up"
```

- [ ] **Step 12: Push the branch and open the PR**

```bash
git push -u origin feat/v0.4-retry-and-budget
```

Then create a PR per the project's normal cadence (gh pr create). The PR body should reference both the spec (`planning/specs/2026-06-05-retry-and-retry-budget-design.md`) and this plan. Do NOT bundle release-notes work or version bumps into this PR — those happen in a separate release-prep PR.

---

## Out of scope for this plan (per the spec)

These items are deliberately deferred. Do NOT implement them as part of this slice; if the implementation pulls toward them, stop and surface to the user instead.

- Per-call retry override via `extensions["httpware_retry"]` — would be additive later.
- `Backoff` protocol abstraction — single hardcoded full-jitter exponential is the only strategy.
- `retry_on_exception=` parameter — retryable-exception set is hardcoded.
- `Bulkhead` middleware — slice 2 of Epic 3, separate spec.
- Standalone per-attempt-timeout middleware — folded into `Retry.attempt_timeout=`.
- Streaming request bodies — out of scope until Epic 4 lands `AsyncClient.stream`.
- Release notes / version bump for 0.4.0 — happens in a separate release-prep PR after subsequent Epic 3 slices land.

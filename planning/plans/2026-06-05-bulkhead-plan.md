# Bulkhead middleware (0.4.0, Epic 3 slice 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the `Bulkhead` middleware — a concurrency limiter via `asyncio.Semaphore` — plus a `BulkheadFullError` exception. Bulkhead caps in-flight requests at the caller layer (distinct from `httpx2.Limits`, which caps the connection pool). A required `max_concurrent` parameter forces an explicit choice; `acquire_timeout` (default 1.0s, `None` = wait forever, `0` = fail fast) bounds the time spent waiting for a slot.

**Architecture:** New `bulkhead.py` under `src/httpware/middleware/resilience/`, mirroring the slice-1 layout (`retry.py`, `budget.py`, `_backoff.py`). The middleware owns an `asyncio.Semaphore(max_concurrent)`, wraps `acquire()` in `asyncio.timeout(acquire_timeout)`, and uses an explicit `try/finally` around `next(request)` to guarantee release on every exit path (success, exception, cancellation). `BulkheadFullError(ClientError)` is picklable via the same `__reduce__` + module-level reconstructor pattern used by `StatusError` and `RetryBudgetExhaustedError`.

**Tech Stack:** Python 3.11+ (`asyncio.timeout` requires 3.11), `httpx2`, `pytest` / `pytest-asyncio` (auto mode), `hypothesis`, `uv`, `just`, `ruff`, `ty`.

**Target branch:** `feat/v0.4-bulkhead`. Create from `main` before Task 1: `git checkout main && git pull && git checkout -b feat/v0.4-bulkhead`.

**Source spec:** [`planning/specs/2026-06-05-bulkhead-design.md`](../specs/2026-06-05-bulkhead-design.md). Read it before starting — the *why* for each decision lives there.

---

## File structure

**New files:**
- `src/httpware/middleware/resilience/bulkhead.py` — `Bulkhead` middleware class.
- `tests/test_bulkhead.py` — unit tests via `httpx2.MockTransport`.
- `tests/test_bulkhead_props.py` — Hypothesis property tests for the concurrency invariant.

**Modified files:**
- `src/httpware/errors.py` — add `BulkheadFullError(ClientError)` + `_reconstruct_bulkhead_full` reconstructor.
- `src/httpware/middleware/resilience/__init__.py` — add `Bulkhead` to the re-exports.
- `src/httpware/__init__.py` — export `Bulkhead` and `BulkheadFullError`.
- `tests/test_errors.py` — add inheritance + pickle tests for `BulkheadFullError`.
- `tests/test_public_api.py` — add `Bulkhead` and `BulkheadFullError` to the expected exports set.
- `planning/engineering.md` — §8 mark `3-5` shipped; remaining Epic 3 is just `3-6` extension-slot docs.

**Commit cadence:** each Task ends with a `git add` + `git commit`. Per-task commits keep history reviewable; the branch is squash-mergeable.

---

## Task 1: Branch + scaffold `bulkhead.py`

**Files:**
- Create: `src/httpware/middleware/resilience/bulkhead.py` (docstring-only stub)

This task creates only the empty module. The class arrives in Task 3 and the `resilience/__init__.py` re-export wiring also lands in Task 3 (so we don't trip an `ImportError` during the intermediate Task 2 — same lesson as slice 1).

- [ ] **Step 1: Create the branch**

Run:
```bash
git checkout main && git pull && git checkout -b feat/v0.4-bulkhead
```
Expected: switched to a new branch.

- [ ] **Step 2: Create the stub file**

Create `src/httpware/middleware/resilience/bulkhead.py` with:
```python
"""Bulkhead middleware — concurrency limiter via asyncio.Semaphore.

See planning/specs/2026-06-05-bulkhead-design.md for the contract.
"""
```

- [ ] **Step 3: Verify file exists**

Run:
```bash
ls src/httpware/middleware/resilience/
```
Expected: `__init__.py  _backoff.py  budget.py  bulkhead.py  retry.py`

- [ ] **Step 4: Lint (sanity)**

Run: `just lint`
Expected: clean (the docstring-only stub passes ruff/ty).

- [ ] **Step 5: Stage and commit**

```bash
git add src/httpware/middleware/resilience/bulkhead.py
git commit -m "scaffold(resilience): empty bulkhead.py stub"
```

---

## Task 2: Add `BulkheadFullError` to `errors.py`

**Files:**
- Modify: `src/httpware/errors.py`
- Modify: `tests/test_errors.py`

- [ ] **Step 1: Write failing tests in `tests/test_errors.py`**

Append to `tests/test_errors.py`:
```python
from httpware.errors import BulkheadFullError


_MAX_CONCURRENT_5 = 5
_ACQUIRE_TIMEOUT_1_0 = 1.0


def test_bulkhead_full_error_is_client_error() -> None:
    exc = BulkheadFullError(max_concurrent=_MAX_CONCURRENT_5, acquire_timeout=_ACQUIRE_TIMEOUT_1_0)
    assert isinstance(exc, ClientError)
    assert exc.max_concurrent == _MAX_CONCURRENT_5
    assert exc.acquire_timeout == _ACQUIRE_TIMEOUT_1_0


def test_bulkhead_full_error_accepts_none_acquire_timeout() -> None:
    exc = BulkheadFullError(max_concurrent=_MAX_CONCURRENT_5, acquire_timeout=None)
    assert exc.acquire_timeout is None


def test_bulkhead_full_error_summary_mentions_caps() -> None:
    exc = BulkheadFullError(max_concurrent=_MAX_CONCURRENT_5, acquire_timeout=_ACQUIRE_TIMEOUT_1_0)
    assert str(exc) == "bulkhead full (max_concurrent=5, acquire_timeout=1.0)"


def test_bulkhead_full_error_pickleable() -> None:
    exc = BulkheadFullError(max_concurrent=_MAX_CONCURRENT_5, acquire_timeout=_ACQUIRE_TIMEOUT_1_0)
    restored = pickle.loads(pickle.dumps(exc))  # noqa: S301
    assert isinstance(restored, BulkheadFullError)
    assert restored.max_concurrent == _MAX_CONCURRENT_5
    assert restored.acquire_timeout == _ACQUIRE_TIMEOUT_1_0
```

Run: `uv run pytest tests/test_errors.py -v -k "bulkhead"`
Expected: FAIL (`ImportError: cannot import name 'BulkheadFullError'`).

- [ ] **Step 2: Add `BulkheadFullError` to `src/httpware/errors.py`**

Append at the end of `src/httpware/errors.py` (after the existing `RetryBudgetExhaustedError` block — `_reconstruct_bulkhead_full` goes above the class, mirroring the existing reconstructor pattern):

```python
def _reconstruct_bulkhead_full(
    cls: "type[BulkheadFullError]",
    max_concurrent: int,
    acquire_timeout: float | None,
) -> "BulkheadFullError":
    return cls(max_concurrent=max_concurrent, acquire_timeout=acquire_timeout)


class BulkheadFullError(ClientError):
    """Raised when ``acquire_timeout`` elapses before a Bulkhead slot becomes available.

    Carries the configured caps for caller logging/alerting.
    """

    max_concurrent: int
    acquire_timeout: float | None

    def __init__(self, *, max_concurrent: int, acquire_timeout: float | None) -> None:
        self.max_concurrent = max_concurrent
        self.acquire_timeout = acquire_timeout
        super().__init__(
            f"bulkhead full (max_concurrent={max_concurrent}, acquire_timeout={acquire_timeout})"
        )

    def __reduce__(self) -> tuple[Any, ...]:
        return (
            _reconstruct_bulkhead_full,
            (type(self), self.max_concurrent, self.acquire_timeout),
        )
```

- [ ] **Step 3: Run the bulkhead tests**

Run: `uv run pytest tests/test_errors.py -v -k "bulkhead"`
Expected: all 4 PASS.

- [ ] **Step 4: Run the full suite + lint**

Run: `just lint && just test`
Expected: clean lint, 100% coverage.

- [ ] **Step 5: Stage and commit**

```bash
git add src/httpware/errors.py tests/test_errors.py
git commit -m "feat(errors): add BulkheadFullError(ClientError)

Distinct exception raised by the Bulkhead middleware when acquire_timeout
elapses without acquiring a slot. Carries max_concurrent + acquire_timeout
for caller logging. Picklable via _reconstruct_bulkhead_full + __reduce__,
mirroring the existing StatusError / RetryBudgetExhaustedError pattern.

Inherits ClientError (not TimeoutError) because a bulkhead-full event is
a backpressure signal, not a network timeout."
```

---

## Task 3: Implement `Bulkhead` middleware — happy path + validation + capacity serialization

**Files:**
- Modify: `src/httpware/middleware/resilience/bulkhead.py`
- Modify: `src/httpware/middleware/resilience/__init__.py`
- Create: `tests/test_bulkhead.py`

This task implements the middleware skeleton with: constructor validation, the basic acquire→try/finally→release pattern, capacity serialization (second request waits for first to release), and re-export wiring.

- [ ] **Step 1: Write failing tests in `tests/test_bulkhead.py`**

Create `tests/test_bulkhead.py`:
```python
"""Tests for the Bulkhead middleware.

Mocks the transport via httpx2.MockTransport. Concurrency tests use real
asyncio coroutines with sub-100ms timeouts so the suite stays fast.
"""

import asyncio
from collections.abc import Callable
from http import HTTPStatus

import httpx2
import pytest

from httpware import AsyncClient
from httpware.errors import BulkheadFullError
from httpware.middleware.resilience.bulkhead import Bulkhead


_MAX_CONCURRENT_1 = 1
_MAX_CONCURRENT_2 = 2


class _SlowHandler:
    """Mock handler that blocks for `delay` seconds before returning 200 OK."""

    def __init__(self, delay: float) -> None:
        self.delay = delay
        self.in_flight = 0
        self.max_in_flight = 0
        self.calls = 0

    async def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.calls += 1
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            await asyncio.sleep(self.delay)
            return httpx2.Response(HTTPStatus.OK, request=request)
        finally:
            self.in_flight -= 1


def _client(handler: Callable[[httpx2.Request], httpx2.Response], *, bulkhead: Bulkhead) -> AsyncClient:
    transport = httpx2.MockTransport(handler)
    return AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=transport),
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


async def test_succeeds_when_slot_available() -> None:
    handler = _SlowHandler(delay=0.0)
    client = _client(handler, bulkhead=Bulkhead(max_concurrent=_MAX_CONCURRENT_2))
    response = await client.get("https://example.test/x")
    assert response.status_code == HTTPStatus.OK
    assert handler.calls == 1


async def test_serializes_at_capacity() -> None:
    """With max_concurrent=1 and 3 concurrent calls, in-flight count never exceeds 1."""
    handler = _SlowHandler(delay=0.02)
    client = _client(
        handler,
        bulkhead=Bulkhead(max_concurrent=_MAX_CONCURRENT_1, acquire_timeout=None),
    )
    await asyncio.gather(
        client.get("https://example.test/a"),
        client.get("https://example.test/b"),
        client.get("https://example.test/c"),
    )
    assert handler.calls == 3  # noqa: PLR2004 — three concurrent gets above
    assert handler.max_in_flight == 1  # cap honored


async def test_max_concurrent_2_observes_at_most_2_in_flight() -> None:
    handler = _SlowHandler(delay=0.02)
    client = _client(handler, bulkhead=Bulkhead(max_concurrent=_MAX_CONCURRENT_2, acquire_timeout=None))
    await asyncio.gather(
        client.get("https://example.test/a"),
        client.get("https://example.test/b"),
        client.get("https://example.test/c"),
        client.get("https://example.test/d"),
    )
    assert handler.calls == 4  # noqa: PLR2004 — four concurrent gets above
    assert handler.max_in_flight <= _MAX_CONCURRENT_2
```

Run: `uv run pytest tests/test_bulkhead.py -v`
Expected: all FAIL (`ImportError` for `Bulkhead`).

- [ ] **Step 2: Implement the `Bulkhead` middleware**

Replace `src/httpware/middleware/resilience/bulkhead.py` content with:
```python
"""Bulkhead middleware — concurrency limiter via asyncio.Semaphore.

See planning/specs/2026-06-05-bulkhead-design.md for the contract.

The middleware owns an asyncio.Semaphore(max_concurrent). On each request,
it acquires a slot (bounded by acquire_timeout via asyncio.timeout) and
releases the slot in a try/finally so success, exceptions, and cancellation
all release deterministically.

Bulkhead is the sharable unit — pass the same instance to multiple
AsyncClient(middleware=[shared]) calls to enforce a joint cap across clients.
"""

import asyncio

import httpx2

from httpware.errors import BulkheadFullError
from httpware.middleware import Next


_MAX_CONCURRENT_INVALID = "max_concurrent must be >= 1"
_ACQUIRE_TIMEOUT_INVALID = "acquire_timeout must be >= 0"


class Bulkhead:
    """Concurrency limiter middleware. See module docstring for behavior."""

    def __init__(
        self,
        *,
        max_concurrent: int,
        acquire_timeout: float | None = 1.0,
    ) -> None:
        if max_concurrent < 1:
            raise ValueError(_MAX_CONCURRENT_INVALID)
        if acquire_timeout is not None and acquire_timeout < 0:
            raise ValueError(_ACQUIRE_TIMEOUT_INVALID)
        self._max_concurrent = max_concurrent
        self._acquire_timeout = acquire_timeout
        self._sem = asyncio.Semaphore(max_concurrent)

    async def __call__(self, request: httpx2.Request, next: Next) -> httpx2.Response:  # noqa: A002
        """Acquire a slot (bounded by acquire_timeout), invoke next, release."""
        try:
            if self._acquire_timeout is None:
                await self._sem.acquire()
            else:
                async with asyncio.timeout(self._acquire_timeout):
                    await self._sem.acquire()
        except asyncio.TimeoutError as exc:
            raise BulkheadFullError(
                max_concurrent=self._max_concurrent,
                acquire_timeout=self._acquire_timeout,
            ) from exc

        try:
            return await next(request)
        finally:
            self._sem.release()
```

- [ ] **Step 3: Wire `Bulkhead` into `resilience/__init__.py`**

Read `src/httpware/middleware/resilience/__init__.py`. Add `Bulkhead` to the re-exports and `__all__`. The full file becomes:
```python
"""Resilience primitives: Retry middleware and RetryBudget token bucket."""

from httpware.middleware.resilience.budget import RetryBudget
from httpware.middleware.resilience.bulkhead import Bulkhead
from httpware.middleware.resilience.retry import Retry


__all__ = ["Bulkhead", "Retry", "RetryBudget"]
```

- [ ] **Step 4: Run the Task 3 tests**

Run: `uv run pytest tests/test_bulkhead.py -v`
Expected: all PASS.

- [ ] **Step 5: Run lint + full suite**

Run: `just lint && just test`
Expected: clean, 100% coverage.

- [ ] **Step 6: Stage and commit**

```bash
git add src/httpware/middleware/resilience/bulkhead.py src/httpware/middleware/resilience/__init__.py tests/test_bulkhead.py
git commit -m "feat(resilience): Bulkhead middleware — happy path + validation + capacity

Constructor validates max_concurrent >= 1 and acquire_timeout >= 0
(None and 0 both accepted). asyncio.Semaphore enforces the cap; the
explicit acquire + try/finally around next() guarantees release on
every exit path. Acquire failures map to BulkheadFullError.

Subsequent tasks cover fail-fast / wait-forever modes, exception +
cancellation release semantics, cross-client sharing, and property tests."
```

---

## Task 4: `Bulkhead` — `acquire_timeout` behaviors (bounded wait, fail-fast, wait-forever)

**Files:**
- Modify: `tests/test_bulkhead.py`

The implementation already supports all three modes. This task adds explicit tests that pin each mode.

- [ ] **Step 1: Append tests to `tests/test_bulkhead.py`**

```python
_ACQUIRE_TIMEOUT_SHORT = 0.02
_ACQUIRE_TIMEOUT_LONG = 0.1


async def test_bounded_wait_raises_bulkhead_full_error() -> None:
    """With max_concurrent=1 and acquire_timeout=0.02, the second call raises after ~20ms."""
    handler = _SlowHandler(delay=_ACQUIRE_TIMEOUT_LONG)  # holds slot for 100ms
    client = _client(
        handler,
        bulkhead=Bulkhead(max_concurrent=_MAX_CONCURRENT_1, acquire_timeout=_ACQUIRE_TIMEOUT_SHORT),
    )

    first = asyncio.create_task(client.get("https://example.test/a"))
    await asyncio.sleep(0.005)  # let first acquire the slot
    with pytest.raises(BulkheadFullError) as info:
        await client.get("https://example.test/b")
    assert info.value.max_concurrent == _MAX_CONCURRENT_1
    assert info.value.acquire_timeout == _ACQUIRE_TIMEOUT_SHORT
    await first  # cleanup


async def test_acquire_timeout_zero_fails_fast() -> None:
    """With acquire_timeout=0, the second call raises immediately without waiting."""
    handler = _SlowHandler(delay=_ACQUIRE_TIMEOUT_LONG)
    client = _client(
        handler,
        bulkhead=Bulkhead(max_concurrent=_MAX_CONCURRENT_1, acquire_timeout=0),
    )

    first = asyncio.create_task(client.get("https://example.test/a"))
    await asyncio.sleep(0.005)
    with pytest.raises(BulkheadFullError) as info:
        await client.get("https://example.test/b")
    assert info.value.acquire_timeout == 0
    await first


async def test_acquire_timeout_none_waits_forever() -> None:
    """With acquire_timeout=None, the second call waits until the first releases."""
    handler = _SlowHandler(delay=_ACQUIRE_TIMEOUT_SHORT)
    client = _client(
        handler,
        bulkhead=Bulkhead(max_concurrent=_MAX_CONCURRENT_1, acquire_timeout=None),
    )

    first = asyncio.create_task(client.get("https://example.test/a"))
    second = asyncio.create_task(client.get("https://example.test/b"))
    responses = await asyncio.wait_for(asyncio.gather(first, second), timeout=1.0)
    assert all(r.status_code == HTTPStatus.OK for r in responses)
    assert handler.calls == 2  # noqa: PLR2004 — both eventually succeeded
```

- [ ] **Step 2: Run the tests**

Run: `uv run pytest tests/test_bulkhead.py -v -k "bounded_wait or fails_fast or waits_forever"`
Expected: all PASS.

- [ ] **Step 3: Run lint + full suite**

Run: `just lint && just test`
Expected: clean, 100% coverage.

- [ ] **Step 4: Stage and commit**

```bash
git add tests/test_bulkhead.py
git commit -m "test(resilience): Bulkhead acquire_timeout modes — bounded / fail-fast / forever

Pins the three acquire_timeout modes: bounded wait raises BulkheadFullError
after the configured timeout, =0 fails fast without waiting, =None waits
until a slot frees."
```

---

## Task 5: `Bulkhead` — release semantics (exception, cancellation)

**Files:**
- Modify: `tests/test_bulkhead.py`

The `try/finally` in `__call__` already releases on every exit. This task pins the behavior with explicit tests so a future refactor that drops the `finally` is caught immediately.

- [ ] **Step 1: Append tests to `tests/test_bulkhead.py`**

```python
async def test_slot_released_after_exception_in_next() -> None:
    """If next() raises, the slot is released — subsequent calls succeed immediately."""
    call_count = {"n": 0}

    def handler(request: httpx2.Request) -> httpx2.Response:
        call_count["n"] += 1
        if call_count["n"] == 1:
            msg = "boom"
            raise RuntimeError(msg)
        return httpx2.Response(HTTPStatus.OK, request=request)

    client = _client(handler, bulkhead=Bulkhead(max_concurrent=_MAX_CONCURRENT_1, acquire_timeout=0))

    # First call raises; slot must release.
    with pytest.raises(RuntimeError, match="boom"):
        await client.get("https://example.test/a")

    # Second call must succeed immediately — fail-fast=0 proves the slot is free.
    response = await client.get("https://example.test/b")
    assert response.status_code == HTTPStatus.OK
    assert call_count["n"] == 2  # noqa: PLR2004 — second call reached handler


async def test_slot_released_on_cancellation() -> None:
    """If the calling task is cancelled while next() runs, the slot is released."""
    handler = _SlowHandler(delay=0.5)  # would block indefinitely
    bulkhead = Bulkhead(max_concurrent=_MAX_CONCURRENT_1, acquire_timeout=0)
    client = _client(handler, bulkhead=bulkhead)

    first = asyncio.create_task(client.get("https://example.test/a"))
    await asyncio.sleep(0.01)  # let first acquire and start sleeping in handler
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first

    # Slot must now be released — fail-fast=0 next call proves it.
    handler.delay = 0.0  # speed up the next request
    response = await client.get("https://example.test/b")
    assert response.status_code == HTTPStatus.OK


async def test_cancellation_before_acquire_does_not_hold_slot() -> None:
    """Cancellation while waiting for a slot must not leak the slot to the cancelled task."""
    handler = _SlowHandler(delay=0.05)
    bulkhead = Bulkhead(max_concurrent=_MAX_CONCURRENT_1, acquire_timeout=None)
    client = _client(handler, bulkhead=bulkhead)

    first = asyncio.create_task(client.get("https://example.test/a"))
    await asyncio.sleep(0.005)  # first acquires
    second = asyncio.create_task(client.get("https://example.test/b"))  # waits for slot
    await asyncio.sleep(0.005)  # ensure second is parked on acquire
    second.cancel()
    with pytest.raises(asyncio.CancelledError):
        await second

    # First should still complete normally.
    response = await first
    assert response.status_code == HTTPStatus.OK
    assert handler.calls == 1  # second never reached the handler
```

- [ ] **Step 2: Run the tests**

Run: `uv run pytest tests/test_bulkhead.py -v -k "released or cancellation"`
Expected: all PASS.

- [ ] **Step 3: Run lint + full suite**

Run: `just lint && just test`
Expected: clean, 100% coverage.

- [ ] **Step 4: Stage and commit**

```bash
git add tests/test_bulkhead.py
git commit -m "test(resilience): Bulkhead release semantics on exception + cancellation

Pins the try/finally release: exception in next() releases the slot,
cancellation during next() releases the slot, cancellation while
parked on acquire() does not hold a slot."
```

---

## Task 6: `Bulkhead` — sharing across clients + construct-outside-loop sanity

**Files:**
- Modify: `tests/test_bulkhead.py`

- [ ] **Step 1: Append tests to `tests/test_bulkhead.py`**

```python
# Constructed at module scope on purpose — pins the construct-outside-loop behavior.
_MODULE_SCOPE_BULKHEAD = Bulkhead(max_concurrent=_MAX_CONCURRENT_1, acquire_timeout=None)


async def test_construct_outside_event_loop_then_use_inside() -> None:
    """Bulkhead constructed at module scope must work when used inside an event loop."""
    handler = _SlowHandler(delay=0.0)
    client = _client(handler, bulkhead=_MODULE_SCOPE_BULKHEAD)
    response = await client.get("https://example.test/x")
    assert response.status_code == HTTPStatus.OK


async def test_shared_bulkhead_enforces_joint_cap() -> None:
    """One Bulkhead shared across two AsyncClients enforces the joint cap."""
    # Both clients use ONE handler that tracks combined in-flight across all calls.
    # asyncio is single-threaded so a plain dict counter is safe between awaits.
    state = {"in_flight": 0, "max_in_flight": 0}

    async def shared_handler(request: httpx2.Request) -> httpx2.Response:
        state["in_flight"] += 1
        state["max_in_flight"] = max(state["max_in_flight"], state["in_flight"])
        try:
            await asyncio.sleep(0.02)
            return httpx2.Response(HTTPStatus.OK, request=request)
        finally:
            state["in_flight"] -= 1

    shared = Bulkhead(max_concurrent=_MAX_CONCURRENT_1, acquire_timeout=None)
    client_a = AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=httpx2.MockTransport(shared_handler)),
        middleware=[shared],
    )
    client_b = AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=httpx2.MockTransport(shared_handler)),
        middleware=[shared],
    )

    await asyncio.gather(
        client_a.get("https://upstream-a.example.test/x"),
        client_a.get("https://upstream-a.example.test/y"),
        client_b.get("https://upstream-b.example.test/x"),
        client_b.get("https://upstream-b.example.test/y"),
    )

    # The shared bulkhead enforces max=1 across BOTH clients combined.
    assert state["max_in_flight"] <= _MAX_CONCURRENT_1
```

- [ ] **Step 2: Run the tests**

Run: `uv run pytest tests/test_bulkhead.py -v -k "construct_outside or shared_bulkhead"`
Expected: PASS.

- [ ] **Step 3: Run lint + full suite**

Run: `just lint && just test`
Expected: clean, 100% coverage.

- [ ] **Step 4: Stage and commit**

```bash
git add tests/test_bulkhead.py
git commit -m "test(resilience): Bulkhead sharing across clients + construct-outside-loop

Pins two behaviors: a Bulkhead instantiated at module scope (outside any
event loop) works correctly when used inside one, and a single Bulkhead
instance passed to multiple AsyncClient instances enforces the joint cap
across all of them."
```

---

## Task 7: Hypothesis property tests for `Bulkhead`

**Files:**
- Create: `tests/test_bulkhead_props.py`

- [ ] **Step 1: Create the property-test file**

```python
"""Hypothesis property tests for Bulkhead.

Properties verified:
1. Observed in-flight count never exceeds max_concurrent under any interleaving.
2. With acquire_timeout=0 and a full bulkhead, the call raises BulkheadFullError.
3. Successful acquisitions are released — back-to-back calls eventually drain
   without leaking slots.
"""

import asyncio
from http import HTTPStatus

import httpx2
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from httpware import AsyncClient
from httpware.errors import BulkheadFullError
from httpware.middleware.resilience.bulkhead import Bulkhead


class _InFlightHandler:
    """Tracks max simultaneous in-flight count across all calls."""

    def __init__(self, delay: float) -> None:
        self.delay = delay
        self.in_flight = 0
        self.max_in_flight = 0
        self.calls = 0

    async def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.calls += 1
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            await asyncio.sleep(self.delay)
            return httpx2.Response(HTTPStatus.OK, request=request)
        finally:
            self.in_flight -= 1


@given(
    max_concurrent=st.integers(min_value=1, max_value=8),
    n_requests=st.integers(min_value=1, max_value=32),
    delay=st.floats(min_value=0.001, max_value=0.005),
)
@settings(max_examples=30, deadline=None)
async def test_in_flight_never_exceeds_max_concurrent(
    max_concurrent: int, n_requests: int, delay: float,
) -> None:
    handler = _InFlightHandler(delay=delay)
    transport = httpx2.MockTransport(handler)
    client = AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=transport),
        middleware=[Bulkhead(max_concurrent=max_concurrent, acquire_timeout=None)],
    )
    await asyncio.gather(
        *(client.get(f"https://example.test/{i}") for i in range(n_requests))
    )
    assert handler.calls == n_requests
    assert handler.max_in_flight <= max_concurrent


@given(
    max_concurrent=st.integers(min_value=1, max_value=4),
    extra_requests=st.integers(min_value=1, max_value=8),
)
@settings(max_examples=20, deadline=None)
async def test_fail_fast_rejects_when_at_capacity(
    max_concurrent: int, extra_requests: int,
) -> None:
    handler = _InFlightHandler(delay=0.05)  # hold slots long enough for fail-fast to fire
    transport = httpx2.MockTransport(handler)
    client = AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=transport),
        middleware=[Bulkhead(max_concurrent=max_concurrent, acquire_timeout=0)],
    )

    # Fill the bulkhead with max_concurrent long-running tasks.
    holders = [
        asyncio.create_task(client.get(f"https://example.test/hold-{i}"))
        for i in range(max_concurrent)
    ]
    await asyncio.sleep(0.005)  # let the holders acquire their slots

    # Any extra requests should fail fast with BulkheadFullError.
    for i in range(extra_requests):
        with pytest.raises(BulkheadFullError):
            await client.get(f"https://example.test/extra-{i}")

    # Cleanup the holders.
    await asyncio.gather(*holders)


@given(
    max_concurrent=st.integers(min_value=1, max_value=4),
    n_requests=st.integers(min_value=4, max_value=16),
)
@settings(max_examples=20, deadline=None)
async def test_no_slot_leak_after_drain(max_concurrent: int, n_requests: int) -> None:
    """After all calls complete, the bulkhead has its full capacity available."""
    handler = _InFlightHandler(delay=0.001)
    bulkhead = Bulkhead(max_concurrent=max_concurrent, acquire_timeout=None)
    transport = httpx2.MockTransport(handler)
    client = AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=transport),
        middleware=[bulkhead],
    )

    await asyncio.gather(
        *(client.get(f"https://example.test/{i}") for i in range(n_requests))
    )

    # Bulkhead should be drained — _value equals max_concurrent again.
    # asyncio.Semaphore._value is implementation detail but reliable across CPython 3.11+.
    assert bulkhead._sem._value == max_concurrent  # noqa: SLF001
```

Add `import pytest` at the top alongside the existing imports.

- [ ] **Step 2: Run the property tests**

Run: `uv run pytest tests/test_bulkhead_props.py -v`
Expected: all PASS.

- [ ] **Step 3: Run lint + full suite**

Run: `just lint && just test`
Expected: clean, 100% coverage.

- [ ] **Step 4: Stage and commit**

```bash
git add tests/test_bulkhead_props.py
git commit -m "test(resilience): Hypothesis property tests for Bulkhead

Three invariants: in-flight never exceeds max_concurrent under any
interleaving; fail-fast (acquire_timeout=0) raises BulkheadFullError
when at capacity; after all calls drain, the bulkhead has full capacity
available again (no slot leak)."
```

---

## Task 8: Public API exports + final verification

**Files:**
- Modify: `src/httpware/__init__.py`
- Modify: `tests/test_public_api.py`
- Modify: `planning/engineering.md`

- [ ] **Step 1: Add `Bulkhead` + `BulkheadFullError` to `src/httpware/__init__.py`**

Read `src/httpware/__init__.py`. Add `BulkheadFullError` to the `from httpware.errors import (...)` block in alphabetical position (between `BadRequestError` and `ClientError`).

Update the resilience import line from:
```python
from httpware.middleware.resilience import Retry, RetryBudget
```
to:
```python
from httpware.middleware.resilience import Bulkhead, Retry, RetryBudget
```

Add both new symbols to `__all__` in alphabetical order:
- `"Bulkhead"` (between `"BadRequestError"` and `"ClientError"`)
- `"BulkheadFullError"` (immediately after `"Bulkhead"`)

- [ ] **Step 2: Update `tests/test_public_api.py`**

In `test_expected_exports`, add `"Bulkhead"` and `"BulkheadFullError"` to the `expected` set. Insertion point: alphabetical, between `"AsyncClient"` and `"ClientError"` (the file's `expected` is unordered as a set, but insert visually in the same alphabetic neighborhood).

- [ ] **Step 3: Run the public-API test**

Run: `uv run pytest tests/test_public_api.py -v`
Expected: PASS.

- [ ] **Step 4: Update `planning/engineering.md` §8**

Find §8 "Remaining roadmap" and the Epic 3 subsection. Current text:
```
- **Epic 3 — Resilience:**
  - **Shipped in v0.4 slice 1:** `Retry` middleware + Finagle-style `RetryBudget` token bucket + `attempt_timeout=` parameter (folded-in 3-1). ...
  - **Remaining:** `3-5` `Bulkhead`, `3-6` extension-slot docs.
```

Update to:
```
- **Epic 3 — Resilience:**
  - **Shipped in v0.4 slice 1:** `Retry` middleware + Finagle-style `RetryBudget` token bucket + `attempt_timeout=` parameter (folded-in 3-1). See [`planning/specs/2026-06-05-retry-and-retry-budget-design.md`](specs/2026-06-05-retry-and-retry-budget-design.md) and [`planning/plans/2026-06-05-retry-and-retry-budget-plan.md`](plans/2026-06-05-retry-and-retry-budget-plan.md).
  - **Shipped in v0.4 slice 2:** `Bulkhead` middleware (concurrency limiter via `asyncio.Semaphore` with bounded acquire wait). See [`planning/specs/2026-06-05-bulkhead-design.md`](specs/2026-06-05-bulkhead-design.md) and [`planning/plans/2026-06-05-bulkhead-plan.md`](plans/2026-06-05-bulkhead-plan.md).
  - **Remaining:** `3-6` extension-slot docs.
```

- [ ] **Step 5: Run the full suite with coverage gate**

Run: `just test`
Expected: ALL tests PASS, coverage = 100%.

- [ ] **Step 6: Run the full lint**

Run: `just lint-ci`
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

Bulkhead is pure stdlib; importing httpware should not pull pydantic/msgspec/otel:
```bash
uv run pytest tests/test_optional_extras_isolation.py -v
```
Expected: PASS.

- [ ] **Step 9: Stage and commit**

```bash
git add src/httpware/__init__.py tests/test_public_api.py
git commit -m "feat(api): export Bulkhead and BulkheadFullError

Completes the v0.4 slice 2 slice: Bulkhead concurrency limiter middleware + its
backpressure exception. Pure-stdlib core, no new optional extra."
```

- [ ] **Step 10: Final commit for planning docs**

```bash
git add planning/engineering.md
git commit -m "docs(planning): mark 3-5 Bulkhead shipped in v0.4 slice 2"
```

- [ ] **Step 11: Push the branch and open the PR**

```bash
git push -u origin feat/v0.4-bulkhead
```

Then create a PR per the project's normal cadence (`gh pr create`). The PR body should reference both the spec (`planning/specs/2026-06-05-bulkhead-design.md`) and this plan. The PR includes an amendment to `planning/releases/0.4.0.md` describing Bulkhead alongside Retry (per the decision to ship Bulkhead in 0.4.0). The amendment commit lives at the start of the branch.

---

## Out of scope for this plan (per the spec)

These items are deliberately deferred. Do NOT implement them as part of this slice; if the implementation pulls toward them, stop and surface to the user instead.

- Per-host / per-route partitioning of the cap.
- Separate `BulkheadLimit` public type.
- Queue-depth / in-flight metrics on the `Bulkhead` object.
- Fallback / shed-load callbacks.
- Connection-pool integration with `httpx2.Limits`.
- Version bump for 0.4.0 — happens in a separate release-prep PR. Release notes for 0.4.0 are amended in this branch to describe Bulkhead alongside Retry.

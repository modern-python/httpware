---
status: shipped
date: 2026-06-13
slug: circuit-breaker-and-timeout
spec: circuit-breaker-and-timeout
pr: 51
---

# CircuitBreaker + AsyncTimeout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a classic consecutive-failure `CircuitBreaker`/`AsyncCircuitBreaker` and an async-only `AsyncTimeout` (overall pipeline deadline) to httpware's resilience suite, shipping as `0.10.0`.

**Architecture:** Two new middleware modules under `src/httpware/middleware/resilience/`, plus one new error (`CircuitOpenError`). The breaker's transition logic lives in a lock-free private `_CircuitBreakerState` shared by both wrappers; `AsyncCircuitBreaker` relies on asyncio atomicity + a single-event-loop guard (carried from `AsyncBulkhead`), `CircuitBreaker` serializes transitions with a `threading.Lock`. `AsyncTimeout` wraps `next` in `asyncio.timeout` and uses `cm.expired()` to re-wrap only its own deadline. All observability flows through the existing `_emit_event` helper. Pure stdlib; no new optional extra.

**Tech Stack:** Python 3.11+, `httpx2`, `asyncio.timeout`, `time.monotonic`, `threading.Lock`, `enum`. Tests: `pytest` (+ `pytest-asyncio` auto mode), `httpx2.MockTransport`, `hypothesis`. Lint: `ruff` + `ty`. Coverage is enforced at 100% (`--cov-fail-under=100`).

**Spec:** `planning/specs/2026-06-13-circuit-breaker-and-timeout-design.md`

**Branch:** `feat/circuit-breaker-timeout` (already created off `main`; the spec is committed there).

---

## File Structure

| File | Responsibility | Tasks |
|------|----------------|-------|
| `src/httpware/errors.py` | + `CircuitOpenError` (`ClientError`, `retry_after` field, `__reduce__`) | 1 |
| `src/httpware/middleware/resilience/timeout.py` | NEW — `AsyncTimeout` | 2 |
| `src/httpware/middleware/resilience/circuit_breaker.py` | NEW — `_CircuitBreakerState`, `AsyncCircuitBreaker`, `CircuitBreaker` | 3, 4 |
| `src/httpware/middleware/resilience/__init__.py` | re-export new names | 2, 3, 4 |
| `src/httpware/__init__.py` | re-export new names + `__all__` | 1, 2, 3, 4 |
| `tests/test_errors.py` | `CircuitOpenError` fields/summary/pickle | 1 |
| `tests/test_timeout.py` | NEW — `AsyncTimeout` | 2 |
| `tests/test_circuit_breaker.py` | NEW — async breaker, all branches + cross-loop | 3 |
| `tests/test_circuit_breaker_sync.py` | NEW — sync breaker mirror | 4 |
| `tests/test_circuit_breaker_props.py` | NEW — hypothesis invariant | 5 |
| `docs/resilience.md`, `README.md`, `planning/releases/0.10.0.md` | docs + release | 6 |

**Note on `test_observability.py`:** it tests the `_emit_event` helper only — there is no central event-name registry to extend. Event-name assertions live in the feature test files via `caplog` (Tasks 2–4). Do **not** modify `test_observability.py`.

**Export ordering invariant:** the project has a test asserting `__init__.py` imports and `__all__` stay symmetric. Every task that adds a public name must add it to **both** the import block and `__all__`, alphabetically, in the same commit.

---

## Task 1: `CircuitOpenError`

**Files:**
- Modify: `src/httpware/errors.py` (append after `BulkheadFullError`, ~line 214)
- Modify: `src/httpware/__init__.py` (imports block + `__all__`)
- Test: `tests/test_errors.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_errors.py` (the file already imports `pickle`, `ClientError`, and defines module-level int constants; add the import of `CircuitOpenError` to the existing `from httpware.errors import (...)` block, alphabetically):

```python
def test_circuit_open_error_is_client_error() -> None:
    exc = CircuitOpenError(retry_after=2.5)
    assert isinstance(exc, ClientError)
    assert exc.retry_after == 2.5


def test_circuit_open_error_accepts_none_retry_after() -> None:
    exc = CircuitOpenError(retry_after=None)
    assert exc.retry_after is None


def test_circuit_open_error_summary_with_retry_after() -> None:
    exc = CircuitOpenError(retry_after=2.5)
    assert str(exc) == "circuit open (retry_after=2.500s)"


def test_circuit_open_error_summary_with_none_retry_after() -> None:
    exc = CircuitOpenError(retry_after=None)
    assert str(exc) == "circuit open (a probe request is already in flight)"


def test_circuit_open_error_pickleable_with_float() -> None:
    exc = CircuitOpenError(retry_after=2.5)
    restored = pickle.loads(pickle.dumps(exc))  # noqa: S301
    assert isinstance(restored, CircuitOpenError)
    assert restored.retry_after == 2.5


def test_circuit_open_error_pickleable_with_none() -> None:
    exc = CircuitOpenError(retry_after=None)
    restored = pickle.loads(pickle.dumps(exc))  # noqa: S301
    assert isinstance(restored, CircuitOpenError)
    assert restored.retry_after is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `just test tests/test_errors.py -k circuit_open`
Expected: FAIL — `ImportError: cannot import name 'CircuitOpenError'`.

- [ ] **Step 3: Implement `CircuitOpenError`**

Append to `src/httpware/errors.py` (after `BulkheadFullError`, before `_reconstruct_decode_error`). `Any` is already imported at the top of the file.

```python
def _reconstruct_circuit_open(
    cls: "type[CircuitOpenError]",
    retry_after: float | None,
) -> "CircuitOpenError":
    return cls(retry_after=retry_after)


class CircuitOpenError(ClientError):
    """Raised when a CircuitBreaker refuses a request because the circuit is not closed.

    Fires when the circuit is OPEN, or when it is HALF_OPEN and the single probe
    slot is already taken. The request is never forwarded to ``next``. ``retry_after``
    carries the seconds until the circuit will next admit a probe, when known
    (``None`` when a concurrent probe is already in flight).
    """

    retry_after: float | None

    def __init__(self, *, retry_after: float | None) -> None:
        self.retry_after = retry_after
        if retry_after is None:
            super().__init__("circuit open (a probe request is already in flight)")
        else:
            super().__init__(f"circuit open (retry_after={retry_after:.3f}s)")

    def __reduce__(self) -> tuple[Any, ...]:
        return (_reconstruct_circuit_open, (type(self), self.retry_after))
```

- [ ] **Step 4: Export from `httpware/__init__.py`**

In `src/httpware/__init__.py`, add `CircuitOpenError` to the `from httpware.errors import (...)` block and to `__all__`. Alphabetically, `"Circuit…"` sorts **before** `"Client…"` (`i` < `l` at the 3rd char) and after `"Bulkhead…"`:

Import block (errors) — insert after `BulkheadFullError,`, before `ClientError,`:
```python
    CircuitOpenError,
```
`__all__` — insert after `"BulkheadFullError",`, before `"Client",`:
```python
    "CircuitOpenError",
```

> If `ruff`'s RUF022/import sorting is enabled, `just lint` will finalize ordering automatically; the requirement is only that the name appears in **both** lists (the symmetric-`__all__` test).

- [ ] **Step 5: Run tests + import check to verify pass**

Run: `just test tests/test_errors.py -k circuit_open`
Expected: PASS (6 tests).
Run: `uv run python -c "import httpware; assert httpware.CircuitOpenError"`
Expected: no output, exit 0.

- [ ] **Step 6: Lint**

Run: `just lint`
Expected: clean (no errors).

- [ ] **Step 7: Commit**

```bash
git add src/httpware/errors.py src/httpware/__init__.py tests/test_errors.py
git commit -m "feat(errors): add CircuitOpenError

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Task 2: `AsyncTimeout`

**Files:**
- Create: `src/httpware/middleware/resilience/timeout.py`
- Modify: `src/httpware/middleware/resilience/__init__.py`
- Modify: `src/httpware/__init__.py`
- Test: `tests/test_timeout.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_timeout.py`. Tests call the middleware directly with an injected `next` — fully deterministic, no client/transport needed. Expiry uses a tiny timeout against a long sleep (100×+ margin, never flaky).

```python
"""Tests for the AsyncTimeout middleware.

Calls the middleware directly with an injected `next` callable. Expiry tests use a
tiny timeout against a long sleep (large margin → not wall-clock flaky); the
inner-timeout test raises immediately so no real time passes.
"""

import asyncio
import builtins
import logging

import httpx2
import pytest

from httpware.errors import TimeoutError as HttpwareTimeoutError  # noqa: A004
from httpware.middleware.resilience.timeout import AsyncTimeout


def _request() -> httpx2.Request:
    return httpx2.Request("GET", "https://example.test/x")


async def test_passes_through_response_when_under_budget() -> None:
    async def _next(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, request=request)

    middleware = AsyncTimeout(timeout=10.0)
    response = await middleware(_request(), _next)
    assert response.status_code == 200


async def test_expiry_raises_httpware_timeout_chained_from_builtin(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def _next(request: httpx2.Request) -> httpx2.Response:
        await asyncio.sleep(5.0)
        return httpx2.Response(200, request=request)  # pragma: no cover — deadline fires first

    middleware = AsyncTimeout(timeout=0.01)
    with (
        caplog.at_level(logging.WARNING, logger="httpware.timeout"),
        pytest.raises(HttpwareTimeoutError) as info,
    ):
        await middleware(_request(), _next)

    assert "overall timeout of 0.01s exceeded" in str(info.value)
    assert isinstance(info.value.__cause__, builtins.TimeoutError)

    records = [r for r in caplog.records if r.name == "httpware.timeout"]
    assert len(records) == 1
    assert records[0].levelno == logging.WARNING
    assert records[0].timeout == 0.01  # ty: ignore[unresolved-attribute]
    assert records[0].method == "GET"  # ty: ignore[unresolved-attribute]
    assert "example.test/x" in records[0].url  # ty: ignore[unresolved-attribute]


async def test_inner_timeout_propagates_unchanged() -> None:
    """A TimeoutError from next (not our deadline) is re-raised untouched."""

    async def _next(request: httpx2.Request) -> httpx2.Response:
        raise HttpwareTimeoutError("inner read timeout")

    middleware = AsyncTimeout(timeout=10.0)
    with pytest.raises(HttpwareTimeoutError) as info:
        await middleware(_request(), _next)

    assert "inner read timeout" in str(info.value)
    assert "overall timeout" not in str(info.value)


def test_zero_timeout_rejected() -> None:
    with pytest.raises(ValueError, match="timeout must be > 0"):
        AsyncTimeout(timeout=0)


def test_negative_timeout_rejected() -> None:
    with pytest.raises(ValueError, match="timeout must be > 0"):
        AsyncTimeout(timeout=-1.0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `just test tests/test_timeout.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'httpware.middleware.resilience.timeout'`.

- [ ] **Step 3: Implement `AsyncTimeout`**

Create `src/httpware/middleware/resilience/timeout.py`:

```python
"""AsyncTimeout middleware — overall wall-clock deadline across the inner pipeline.

See planning/specs/2026-06-13-circuit-breaker-and-timeout-design.md for the contract.

This is NOT a per-call timeout — httpx2's connect/read/write/pool timeouts are the
right tool for bounding a single outbound call, and AsyncTimeout does not duplicate
them. What httpx2 cannot bound is the total wall-clock across the whole middleware
pipeline (most importantly across an AsyncRetry loop, whose attempts and backoff
sleeps it knows nothing about). Place AsyncTimeout outermost to enforce
"this whole operation must finish within `timeout` seconds, even across retries."

Async-only by design: a sync total-deadline cannot interrupt a blocking httpx2 call
mid-flight (sync Python has no cancellation), and httpx2 already covers sync per-call
timeouts. Sync callers configure httpx2's timeouts directly; there is no sync Timeout.
"""

import asyncio
import logging

import httpx2

from httpware._internal.observability import _emit_event
from httpware.errors import TimeoutError as HttpwareTimeoutError  # noqa: A004
from httpware.middleware import AsyncNext


_TIMEOUT_INVALID = "timeout must be > 0"

_LOGGER = logging.getLogger("httpware.timeout")


class AsyncTimeout:
    """Bounds total wall-clock time spent in the inner pipeline.

    Parameters
    ----------
    timeout
        Required. Overall deadline in seconds for ``next(request)`` to complete,
        including everything it wraps (retries, backoff sleeps, the call itself).
        Must be ``> 0``. On expiry the middleware raises ``httpware.TimeoutError``.

    Place outermost in the chain for an overall-operation deadline. For bounding a
    single outbound call (connect/read/write/pool), configure ``httpx2`` instead.
    """

    def __init__(self, *, timeout: float) -> None:
        if timeout <= 0:
            raise ValueError(_TIMEOUT_INVALID)
        self._timeout = timeout

    async def __call__(self, request: httpx2.Request, next: AsyncNext) -> httpx2.Response:  # noqa: A002
        """Invoke next under an asyncio.timeout; raise httpware.TimeoutError on expiry.

        Only a deadline THIS middleware imposed is re-wrapped: ``cm.expired()``
        distinguishes our own expiry from an inner ``TimeoutError`` (e.g. an httpx2
        per-call timeout surfacing through a retry), which propagates unchanged.
        """
        try:
            async with asyncio.timeout(self._timeout) as cm:
                return await next(request)
        except TimeoutError as exc:
            if not cm.expired():
                raise  # inner TimeoutError, not our deadline — leave it untouched
            _emit_event(
                _LOGGER,
                "timeout.exceeded",
                level=logging.WARNING,
                message="overall timeout exceeded",
                attributes={
                    "timeout": self._timeout,
                    "method": request.method,
                    "url": str(request.url),
                },
            )
            raise HttpwareTimeoutError(f"overall timeout of {self._timeout}s exceeded") from exc
```

- [ ] **Step 4: Export `AsyncTimeout`**

In `src/httpware/middleware/resilience/__init__.py`, update the docstring and add the import + `__all__` entry:

```python
"""Resilience primitives: Bulkhead, Retry, RetryBudget, AsyncTimeout."""

from httpware.middleware.resilience.budget import RetryBudget
from httpware.middleware.resilience.bulkhead import AsyncBulkhead, Bulkhead
from httpware.middleware.resilience.retry import AsyncRetry, Retry
from httpware.middleware.resilience.timeout import AsyncTimeout


__all__ = ["AsyncBulkhead", "AsyncRetry", "AsyncTimeout", "Bulkhead", "Retry", "RetryBudget"]
```

In `src/httpware/__init__.py`: change the resilience import line and add to `__all__`:

```python
from httpware.middleware.resilience import AsyncBulkhead, AsyncRetry, AsyncTimeout, Bulkhead, Retry, RetryBudget
```
`__all__` — insert `"AsyncTimeout",` after `"AsyncRetry",`.

- [ ] **Step 5: Run tests + import check**

Run: `just test tests/test_timeout.py`
Expected: PASS (5 tests).
Run: `uv run python -c "import httpware; assert httpware.AsyncTimeout"`
Expected: exit 0.

- [ ] **Step 6: Lint**

Run: `just lint`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add src/httpware/middleware/resilience/timeout.py src/httpware/middleware/resilience/__init__.py src/httpware/__init__.py tests/test_timeout.py
git commit -m "feat(resilience): add AsyncTimeout overall-deadline middleware

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Task 3: `_CircuitBreakerState` + `AsyncCircuitBreaker`

**Files:**
- Create: `src/httpware/middleware/resilience/circuit_breaker.py`
- Modify: `src/httpware/middleware/resilience/__init__.py`
- Modify: `src/httpware/__init__.py`
- Test: `tests/test_circuit_breaker.py`

**Design note (deliberate deviation from pure async/sync duplication):** `bulkhead.py` and `retry.py` fully duplicate their async and sync classes. The breaker's state machine is far more complex, and duplicating it twice is exactly the parity-bug risk the delta audit surfaced. Instead, the lock-free transition logic lives once in a private `_CircuitBreakerState`; both wrappers are thin. This preserves the three properties the spec requires (shared/sharable instance, async loop-guard, sync `threading.Lock`).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_circuit_breaker.py`. A `_Clock` drives `_now` deterministically; a `_FailFor`/sequence handler drives responses; `httpx2.ConnectError` from the handler maps to `NetworkError` at the terminal.

```python
"""Tests for the AsyncCircuitBreaker middleware.

Time is driven by an injected _now (a _Clock); the transport is mocked via
httpx2.MockTransport. 5xx responses surface as StatusError at the client terminal;
httpx2.ConnectError surfaces as NetworkError.
"""

import asyncio
import logging
from collections.abc import Callable
from http import HTTPStatus

import httpx2
import pytest

from httpware import AsyncClient, CircuitOpenError, InternalServerError, NetworkError, NotFoundError
from httpware.middleware.resilience.circuit_breaker import AsyncCircuitBreaker


class _Clock:
    """Manually-advanced monotonic clock for deterministic reset_timeout tests."""

    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


class _StatusSequence:
    """Mock-transport handler returning a fixed sequence of status codes (default 200)."""

    def __init__(self, statuses: list[int]) -> None:
        self._statuses = list(statuses)
        self.calls = 0

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.calls += 1
        status = self._statuses.pop(0) if self._statuses else HTTPStatus.OK
        return httpx2.Response(status, request=request)


def _client(
    handler: Callable[[httpx2.Request], httpx2.Response],
    *,
    breaker: AsyncCircuitBreaker,
) -> AsyncClient:
    return AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
        middleware=[breaker],
    )


# ───── construction validation ──────────────────────────────────────────────


def test_failure_threshold_below_one_rejected() -> None:
    with pytest.raises(ValueError, match="failure_threshold must be >= 1"):
        AsyncCircuitBreaker(failure_threshold=0)


def test_negative_reset_timeout_rejected() -> None:
    with pytest.raises(ValueError, match="reset_timeout must be >= 0"):
        AsyncCircuitBreaker(reset_timeout=-1.0)


def test_success_threshold_below_one_rejected() -> None:
    with pytest.raises(ValueError, match="success_threshold must be >= 1"):
        AsyncCircuitBreaker(success_threshold=0)


# ───── closed-state behavior ────────────────────────────────────────────────


async def test_closed_passes_through() -> None:
    handler = _StatusSequence([HTTPStatus.OK])
    breaker = AsyncCircuitBreaker(failure_threshold=3, _now=_Clock())
    async with _client(handler, breaker=breaker) as client:
        response = await client.get("https://example.test/x")
    assert response.status_code == HTTPStatus.OK
    assert handler.calls == 1


async def test_consecutive_failures_open_the_circuit(caplog: pytest.LogCaptureFixture) -> None:
    handler = _StatusSequence([500, 500, 500])
    breaker = AsyncCircuitBreaker(failure_threshold=3, _now=_Clock())
    async with _client(handler, breaker=breaker) as client:
        for _ in range(3):
            with pytest.raises(InternalServerError):
                await client.get("https://example.test/x")
        # circuit is now OPEN — the 4th call must NOT reach the transport
        with pytest.raises(CircuitOpenError) as info:
            await client.get("https://example.test/x")
    assert handler.calls == 3  # 4th was short-circuited
    assert info.value.retry_after is not None
    # (the circuit.opened event is asserted in test_open_emits_opened_event_and_rejects)


async def test_open_emits_opened_event_and_rejects(caplog: pytest.LogCaptureFixture) -> None:
    handler = _StatusSequence([500, 500])
    breaker = AsyncCircuitBreaker(failure_threshold=2, _now=_Clock())
    async with _client(handler, breaker=breaker) as client:
        with caplog.at_level(logging.WARNING, logger="httpware.circuit_breaker"):
            for _ in range(2):
                with pytest.raises(InternalServerError):
                    await client.get("https://example.test/x")
            with pytest.raises(CircuitOpenError):
                await client.get("https://example.test/y")
    records = [r for r in caplog.records if r.name == "httpware.circuit_breaker"]
    opened = [r for r in records if "opened" in r.message]
    rejected = [r for r in records if "rejecting" in r.message]
    assert len(opened) == 1
    assert opened[0].failure_threshold == 2  # ty: ignore[unresolved-attribute]
    assert opened[0].failures == 2  # ty: ignore[unresolved-attribute]
    assert len(rejected) == 1
    assert rejected[0].retry_after is not None  # ty: ignore[unresolved-attribute]
    assert rejected[0].method == "GET"  # ty: ignore[unresolved-attribute]


async def test_success_resets_failure_streak() -> None:
    handler = _StatusSequence([500, 500, 200, 500, 500])
    breaker = AsyncCircuitBreaker(failure_threshold=3, _now=_Clock())
    async with _client(handler, breaker=breaker) as client:
        for _ in range(2):
            with pytest.raises(InternalServerError):
                await client.get("https://example.test/x")
        await client.get("https://example.test/x")  # 200 resets the streak
        for _ in range(2):
            with pytest.raises(InternalServerError):
                await client.get("https://example.test/x")
        # only 2 consecutive failures after the reset — still CLOSED
        response = await client.get("https://example.test/x")  # 6th -> default 200
    assert response.status_code == HTTPStatus.OK
    assert handler.calls == 6


async def test_404_and_429_do_not_count_as_failures() -> None:
    handler = _StatusSequence([404, 429, 404, 429, 404])
    breaker = AsyncCircuitBreaker(failure_threshold=2, _now=_Clock())
    async with _client(handler, breaker=breaker) as client:
        for _ in range(5):
            with pytest.raises((NotFoundError, type(None))):  # 404 -> NotFoundError; 429 -> RateLimitedError
                await client.get("https://example.test/x")
    # never opened — all 5 reached the transport
    assert handler.calls == 5


async def test_network_error_counts_as_failure() -> None:
    def _raise(request: httpx2.Request) -> httpx2.Response:
        msg = "connect failed"
        raise httpx2.ConnectError(msg)

    breaker = AsyncCircuitBreaker(failure_threshold=2, _now=_Clock())
    async with _client(_raise, breaker=breaker) as client:
        for _ in range(2):
            with pytest.raises(NetworkError):
                await client.get("https://example.test/x")
        with pytest.raises(CircuitOpenError):
            await client.get("https://example.test/x")


async def test_non_counted_exception_propagates_without_state_change() -> None:
    """A ValueError from inner middleware is neither success nor failure; state unchanged."""

    class _Boom:
        async def __call__(self, request: httpx2.Request, next: object) -> httpx2.Response:
            msg = "boom"
            raise ValueError(msg)

    handler = _StatusSequence([200])
    breaker = AsyncCircuitBreaker(failure_threshold=1, _now=_Clock())
    client = AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
        middleware=[breaker, _Boom()],
    )
    async with client:
        for _ in range(3):
            with pytest.raises(ValueError, match="boom"):
                await client.get("https://example.test/x")
        # failure_threshold=1 but ValueError never counted -> still CLOSED, transport reachable
        # (remove _Boom by using a fresh client would change state; instead assert no CircuitOpenError raised above)


# ───── half-open / reset_timeout ────────────────────────────────────────────


async def test_reset_timeout_admits_probe_then_closes(caplog: pytest.LogCaptureFixture) -> None:
    clock = _Clock()
    handler = _StatusSequence([500, 500, 200])  # 2 fails -> open; probe (3rd) -> 200 -> close
    breaker = AsyncCircuitBreaker(failure_threshold=2, reset_timeout=30.0, success_threshold=1, _now=clock)
    async with _client(handler, breaker=breaker) as client:
        for _ in range(2):
            with pytest.raises(InternalServerError):
                await client.get("https://example.test/x")
        # OPEN; before reset_timeout -> rejected, transport untouched
        with pytest.raises(CircuitOpenError):
            await client.get("https://example.test/x")
        assert handler.calls == 2
        clock.advance(30.0)
        with caplog.at_level(logging.INFO, logger="httpware.circuit_breaker"):
            response = await client.get("https://example.test/x")  # probe admitted -> 200 -> CLOSED
    assert response.status_code == HTTPStatus.OK
    assert handler.calls == 3
    messages = [r.message for r in caplog.records if r.name == "httpware.circuit_breaker"]
    assert any("half-open" in m for m in messages)
    assert any("closed" in m for m in messages)


async def test_probe_failure_reopens_circuit() -> None:
    clock = _Clock()
    handler = _StatusSequence([500, 500, 500])  # open after 2; probe (3rd) fails -> reopen
    breaker = AsyncCircuitBreaker(failure_threshold=2, reset_timeout=10.0, _now=clock)
    async with _client(handler, breaker=breaker) as client:
        for _ in range(2):
            with pytest.raises(InternalServerError):
                await client.get("https://example.test/x")
        clock.advance(10.0)
        with pytest.raises(InternalServerError):  # probe runs, fails
            await client.get("https://example.test/x")
        # reopened with fresh opened_at; immediate retry is rejected
        with pytest.raises(CircuitOpenError):
            await client.get("https://example.test/x")
    assert handler.calls == 3


async def test_success_threshold_requires_multiple_probes() -> None:
    clock = _Clock()
    handler = _StatusSequence([500, 500, 200, 200])  # open; then 2 successful probes to close
    breaker = AsyncCircuitBreaker(failure_threshold=2, reset_timeout=5.0, success_threshold=2, _now=clock)
    async with _client(handler, breaker=breaker) as client:
        for _ in range(2):
            with pytest.raises(InternalServerError):
                await client.get("https://example.test/x")
        clock.advance(5.0)
        await client.get("https://example.test/x")  # probe 1 -> 200 (still HALF_OPEN, 1/2)
        await client.get("https://example.test/x")  # probe 2 -> 200 -> CLOSED
        response = await client.get("https://example.test/x")  # default 200, CLOSED
    assert response.status_code == HTTPStatus.OK
    assert handler.calls == 4


async def test_half_open_second_concurrent_request_rejected_with_none_retry_after() -> None:
    """While the single probe is in flight, a concurrent request fast-fails (retry_after=None)."""
    clock = _Clock()
    probe_started = asyncio.Event()
    release_probe = asyncio.Event()

    async def _handler_async(request: httpx2.Request) -> httpx2.Response:
        probe_started.set()
        await release_probe.wait()
        return httpx2.Response(HTTPStatus.OK, request=request)

    breaker = AsyncCircuitBreaker(failure_threshold=1, reset_timeout=1.0, _now=clock)
    # open the circuit with one 500
    open_handler = _StatusSequence([500])
    async with _client(open_handler, breaker=breaker) as opener:
        with pytest.raises(InternalServerError):
            await opener.get("https://example.test/x")
    clock.advance(1.0)

    client = AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=httpx2.MockTransport(_handler_async)),
        middleware=[breaker],
    )
    async with client:
        probe_task = asyncio.create_task(client.get("https://example.test/probe"))
        await probe_started.wait()  # probe is now in flight, HALF_OPEN
        with pytest.raises(CircuitOpenError) as info:
            await client.get("https://example.test/concurrent")
        assert info.value.retry_after is None
        release_probe.set()
        await probe_task


# ───── single-event-loop guard ──────────────────────────────────────────────


def test_cross_loop_use_raises_runtimeerror() -> None:
    breaker = AsyncCircuitBreaker(_now=_Clock())
    handler = _StatusSequence([200])

    async def _run_once() -> None:
        async with _client(handler, breaker=breaker) as client:
            await client.get("https://example.test/x")

    asyncio.run(_run_once())  # binds to loop L1
    with pytest.raises(RuntimeError, match="bound to a single event loop"):
        asyncio.run(_run_once())
```

> Note for the implementer: in `test_404_and_429_do_not_count_as_failures` import `RateLimitedError` too and use `pytest.raises((NotFoundError, RateLimitedError))`. Replace the `(NotFoundError, type(None))` placeholder with `(NotFoundError, RateLimitedError)` and add `RateLimitedError` to the `from httpware import ...` line. In `test_non_counted_exception_propagates_without_state_change`, assert that no `CircuitOpenError` was raised across the three `ValueError`s (the `pytest.raises(ValueError)` already guarantees each call raised `ValueError`, not `CircuitOpenError`).

- [ ] **Step 2: Run tests to verify they fail**

Run: `just test tests/test_circuit_breaker.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'httpware.middleware.resilience.circuit_breaker'`.

- [ ] **Step 3: Implement `_CircuitBreakerState` + `AsyncCircuitBreaker`**

Create `src/httpware/middleware/resilience/circuit_breaker.py`:

```python
"""CircuitBreaker + AsyncCircuitBreaker — classic consecutive-failure circuit breaker.

See planning/specs/2026-06-13-circuit-breaker-and-timeout-design.md for the contract.

A counted failure is a NetworkError, an httpware TimeoutError, or a StatusError whose
status_code is in the effective failure set (default: all 5xx). 4xx — including 429 —
count as successes: 429 means healthy-but-throttling, and tripping on it amplifies
incidents. Any other exception propagates without affecting circuit state.

State machine (classic / consecutive-failure):
    CLOSED    — forward; count consecutive counted-failures; open at failure_threshold.
    OPEN      — fast-fail with CircuitOpenError; after reset_timeout the next request
                becomes the half-open probe.
    HALF_OPEN — admit exactly one probe at a time; success_threshold consecutive probe
                successes close the circuit; one probe failure re-opens it.

The lock-free _CircuitBreakerState holds the transition logic, shared by both wrappers.
AsyncCircuitBreaker relies on asyncio atomicity (no await inside a transition) plus a
single-event-loop guard; CircuitBreaker serializes transitions with a threading.Lock.
Both are sharable across clients (one shared circuit); a sync instance cannot be shared
with an async one.
"""

import asyncio
import enum
import logging
import threading
import time
import typing
from collections.abc import Callable

import httpx2

from httpware._internal.observability import _emit_event
from httpware.errors import CircuitOpenError, NetworkError, StatusError, TimeoutError  # noqa: A004
from httpware.middleware import AsyncNext, Next


_FAILURE_THRESHOLD_INVALID = "failure_threshold must be >= 1"
_RESET_TIMEOUT_INVALID = "reset_timeout must be >= 0"
_SUCCESS_THRESHOLD_INVALID = "success_threshold must be >= 1"
_CROSS_LOOP_MSG = (
    "AsyncCircuitBreaker is bound to a single event loop. First seen on {first!r}; "
    "current request is on {current!r}. Use one AsyncCircuitBreaker per loop; "
    "cross-thread sharing requires the sync CircuitBreaker primitive."
)

_DEFAULT_FAILURE_STATUS_CODES = frozenset(range(500, 600))

_ROLE_CLOSED = "closed"
_ROLE_PROBE = "probe"

_LOGGER = logging.getLogger("httpware.circuit_breaker")


class _CircuitState(enum.Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class _CircuitBreakerState:
    """Lock-free circuit-breaker state machine shared by the sync + async wrappers.

    Every method is synchronous and performs no I/O beyond logging. The async wrapper
    calls these directly (atomic under a single event loop because no await occurs
    inside a transition); the sync wrapper wraps each call in a threading.Lock.
    """

    def __init__(
        self,
        *,
        failure_threshold: int,
        reset_timeout: float,
        success_threshold: int,
        failure_status_codes: frozenset[int] | None,
        now: Callable[[], float],
    ) -> None:
        if failure_threshold < 1:
            raise ValueError(_FAILURE_THRESHOLD_INVALID)
        if reset_timeout < 0:
            raise ValueError(_RESET_TIMEOUT_INVALID)
        if success_threshold < 1:
            raise ValueError(_SUCCESS_THRESHOLD_INVALID)
        self._failure_threshold = failure_threshold
        self._reset_timeout = reset_timeout
        self._success_threshold = success_threshold
        self._failure_status_codes = (
            failure_status_codes if failure_status_codes is not None else _DEFAULT_FAILURE_STATUS_CODES
        )
        self._now = now
        self._state = _CircuitState.CLOSED
        self._consecutive_failures = 0
        self._consecutive_successes = 0
        self._opened_at = 0.0
        self._probe_in_flight = False

    def is_failure_status(self, status_code: int) -> bool:
        return status_code in self._failure_status_codes

    def admit(self, request: httpx2.Request) -> str:
        """Decide the request's role, or raise CircuitOpenError. No await inside."""
        if self._state is _CircuitState.CLOSED:
            return _ROLE_CLOSED
        if self._state is _CircuitState.OPEN:
            elapsed = self._now() - self._opened_at
            if elapsed >= self._reset_timeout:
                self._state = _CircuitState.HALF_OPEN
                self._probe_in_flight = True
                self._emit(request, "circuit.half_open", logging.INFO, "circuit half-open — admitting probe", {})
                return _ROLE_PROBE
            retry_after = max(0.0, self._reset_timeout - elapsed)
            self._emit(
                request,
                "circuit.rejected",
                logging.WARNING,
                "circuit open — rejecting request",
                {"retry_after": retry_after},
            )
            raise CircuitOpenError(retry_after=retry_after)
        # HALF_OPEN
        if self._probe_in_flight:
            self._emit(
                request,
                "circuit.rejected",
                logging.WARNING,
                "circuit half-open — rejecting request (probe in flight)",
                {"retry_after": None},
            )
            raise CircuitOpenError(retry_after=None)
        self._probe_in_flight = True
        return _ROLE_PROBE

    def on_success(self, role: str, request: httpx2.Request) -> None:
        if role == _ROLE_PROBE:
            self._probe_in_flight = False
        if self._state is _CircuitState.CLOSED:
            self._consecutive_failures = 0
        elif self._state is _CircuitState.HALF_OPEN:
            self._consecutive_successes += 1
            if self._consecutive_successes >= self._success_threshold:
                self._state = _CircuitState.CLOSED
                self._consecutive_failures = 0
                self._consecutive_successes = 0
                self._emit(request, "circuit.closed", logging.INFO, "circuit closed — service recovered", {})

    def on_failure(self, role: str, request: httpx2.Request) -> None:
        if role == _ROLE_PROBE:
            self._probe_in_flight = False
        if self._state is _CircuitState.CLOSED:
            self._consecutive_failures += 1
            if self._consecutive_failures >= self._failure_threshold:
                self._open(request, failures=self._consecutive_failures)
        elif self._state is _CircuitState.HALF_OPEN:
            self._consecutive_successes = 0
            self._open(request, failures=1)

    def release_probe(self, role: str) -> None:
        """Release the probe slot without recording success or failure (non-counted exc)."""
        if role == _ROLE_PROBE:
            self._probe_in_flight = False

    def _open(self, request: httpx2.Request, *, failures: int) -> None:
        self._state = _CircuitState.OPEN
        self._opened_at = self._now()
        self._emit(
            request,
            "circuit.opened",
            logging.WARNING,
            "circuit opened — failure threshold reached",
            {"failure_threshold": self._failure_threshold, "failures": failures},
        )

    def _emit(
        self,
        request: httpx2.Request,
        event_name: str,
        level: int,
        message: str,
        attributes: dict[str, typing.Any],
    ) -> None:
        _emit_event(
            _LOGGER,
            event_name,
            level=level,
            message=message,
            attributes={**attributes, "method": request.method, "url": str(request.url)},
        )


class AsyncCircuitBreaker:
    """Async classic circuit breaker middleware. See the module docstring for the contract."""

    def __init__(
        self,
        *,
        failure_threshold: int = 5,
        reset_timeout: float = 30.0,
        success_threshold: int = 1,
        failure_status_codes: frozenset[int] | None = None,
        _now: Callable[[], float] = time.monotonic,
    ) -> None:
        self._state = _CircuitBreakerState(
            failure_threshold=failure_threshold,
            reset_timeout=reset_timeout,
            success_threshold=success_threshold,
            failure_status_codes=failure_status_codes,
            now=_now,
        )
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_lock = threading.Lock()

    def _check_loop(self) -> None:
        current = asyncio.get_running_loop()
        cached = self._loop
        if cached is current:
            return
        if cached is not None:
            raise RuntimeError(_CROSS_LOOP_MSG.format(first=cached, current=current))
        with self._loop_lock:
            if self._loop is None:
                self._loop = current
            # pragma below: inner double-check-with-lock race arm; only reachable when
            # two threads simultaneously pass the outer check, which single-threaded
            # tests can't trigger.
            elif self._loop is not current:  # pragma: no cover
                raise RuntimeError(_CROSS_LOOP_MSG.format(first=self._loop, current=current))

    async def __call__(self, request: httpx2.Request, next: AsyncNext) -> httpx2.Response:  # noqa: A002
        """Admit, forward, then record the outcome. Fast-fail when the circuit is not closed."""
        self._check_loop()
        role = self._state.admit(request)
        try:
            response = await next(request)
        except StatusError as exc:
            if self._state.is_failure_status(exc.response.status_code):
                self._state.on_failure(role, request)
            else:
                self._state.on_success(role, request)
            raise
        except (NetworkError, TimeoutError):
            self._state.on_failure(role, request)
            raise
        except BaseException:
            self._state.release_probe(role)
            raise
        self._state.on_success(role, request)
        return response
```

- [ ] **Step 4: Export `AsyncCircuitBreaker`**

In `src/httpware/middleware/resilience/__init__.py` add the import and `__all__` entry (only the async name in this task; the sync name lands in Task 4):

```python
from httpware.middleware.resilience.circuit_breaker import AsyncCircuitBreaker
```
Update docstring to mention CircuitBreaker, and `__all__` — insert `"AsyncCircuitBreaker",` after `"AsyncBulkhead",`.

In `src/httpware/__init__.py` change the resilience import to include `AsyncCircuitBreaker` (alphabetical: after `AsyncBulkhead`) and add `"AsyncCircuitBreaker",` to `__all__` after `"AsyncBulkhead",`:

```python
from httpware.middleware.resilience import (
    AsyncBulkhead,
    AsyncCircuitBreaker,
    AsyncRetry,
    AsyncTimeout,
    Bulkhead,
    Retry,
    RetryBudget,
)
```

- [ ] **Step 5: Run tests + import check**

Run: `just test tests/test_circuit_breaker.py`
Expected: PASS (all async breaker tests).
Run: `uv run python -c "import httpware; assert httpware.AsyncCircuitBreaker"`
Expected: exit 0.

- [ ] **Step 6: Lint + coverage check for this module**

Run: `just lint`
Expected: clean.
Run: `just test tests/test_circuit_breaker.py --cov=httpware.middleware.resilience.circuit_breaker --cov-report=term-missing`
Expected: PASS; note any uncovered lines in `circuit_breaker.py`. The only acceptable uncovered line is the `# pragma: no cover` race arm in `_check_loop`. (Full-suite 100% is verified in Task 4 once the sync class lands.)

- [ ] **Step 7: Commit**

```bash
git add src/httpware/middleware/resilience/circuit_breaker.py src/httpware/middleware/resilience/__init__.py src/httpware/__init__.py tests/test_circuit_breaker.py
git commit -m "feat(resilience): add AsyncCircuitBreaker (classic consecutive-failure breaker)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Task 4: `CircuitBreaker` (sync)

**Files:**
- Modify: `src/httpware/middleware/resilience/circuit_breaker.py` (append `CircuitBreaker`)
- Modify: `src/httpware/middleware/resilience/__init__.py`
- Modify: `src/httpware/__init__.py`
- Test: `tests/test_circuit_breaker_sync.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_circuit_breaker_sync.py` — the sync mirror. Uses `Client` + `httpx2.Client(transport=...)`. These are plain sync tests (no `async def`).

```python
"""Tests for the sync CircuitBreaker middleware (mirror of AsyncCircuitBreaker)."""

import logging
import threading
from collections.abc import Callable
from http import HTTPStatus

import httpx2
import pytest

from httpware import CircuitOpenError, Client, InternalServerError, NetworkError, NotFoundError, RateLimitedError
from httpware.middleware.resilience.circuit_breaker import CircuitBreaker


class _Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


class _StatusSequence:
    def __init__(self, statuses: list[int]) -> None:
        self._statuses = list(statuses)
        self.calls = 0

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.calls += 1
        status = self._statuses.pop(0) if self._statuses else HTTPStatus.OK
        return httpx2.Response(status, request=request)


def _client(handler: Callable[[httpx2.Request], httpx2.Response], *, breaker: CircuitBreaker) -> Client:
    return Client(
        httpx2_client=httpx2.Client(transport=httpx2.MockTransport(handler)),
        middleware=[breaker],
    )


def test_failure_threshold_below_one_rejected() -> None:
    with pytest.raises(ValueError, match="failure_threshold must be >= 1"):
        CircuitBreaker(failure_threshold=0)


def test_negative_reset_timeout_rejected() -> None:
    with pytest.raises(ValueError, match="reset_timeout must be >= 0"):
        CircuitBreaker(reset_timeout=-1.0)


def test_success_threshold_below_one_rejected() -> None:
    with pytest.raises(ValueError, match="success_threshold must be >= 1"):
        CircuitBreaker(success_threshold=0)


def test_closed_passes_through() -> None:
    handler = _StatusSequence([HTTPStatus.OK])
    breaker = CircuitBreaker(failure_threshold=3, _now=_Clock())
    with _client(handler, breaker=breaker) as client:
        response = client.get("https://example.test/x")
    assert response.status_code == HTTPStatus.OK


def test_open_emits_opened_event_and_rejects(caplog: pytest.LogCaptureFixture) -> None:
    handler = _StatusSequence([500, 500])
    breaker = CircuitBreaker(failure_threshold=2, _now=_Clock())
    with _client(handler, breaker=breaker) as client:
        with caplog.at_level(logging.WARNING, logger="httpware.circuit_breaker"):
            for _ in range(2):
                with pytest.raises(InternalServerError):
                    client.get("https://example.test/x")
            with pytest.raises(CircuitOpenError) as info:
                client.get("https://example.test/y")
    assert info.value.retry_after is not None
    assert handler.calls == 2
    records = [r for r in caplog.records if r.name == "httpware.circuit_breaker"]
    assert any("opened" in r.message for r in records)
    assert any("rejecting" in r.message for r in records)


def test_success_resets_failure_streak() -> None:
    handler = _StatusSequence([500, 500, 200, 500, 500])
    breaker = CircuitBreaker(failure_threshold=3, _now=_Clock())
    with _client(handler, breaker=breaker) as client:
        for _ in range(2):
            with pytest.raises(InternalServerError):
                client.get("https://example.test/x")
        client.get("https://example.test/x")
        for _ in range(2):
            with pytest.raises(InternalServerError):
                client.get("https://example.test/x")
        response = client.get("https://example.test/x")
    assert response.status_code == HTTPStatus.OK
    assert handler.calls == 6


def test_404_and_429_do_not_count_as_failures() -> None:
    handler = _StatusSequence([404, 429, 404, 429, 404])
    breaker = CircuitBreaker(failure_threshold=2, _now=_Clock())
    with _client(handler, breaker=breaker) as client:
        for _ in range(5):
            with pytest.raises((NotFoundError, RateLimitedError)):
                client.get("https://example.test/x")
    assert handler.calls == 5


def test_network_error_counts_as_failure() -> None:
    def _raise(request: httpx2.Request) -> httpx2.Response:
        msg = "connect failed"
        raise httpx2.ConnectError(msg)

    breaker = CircuitBreaker(failure_threshold=2, _now=_Clock())
    with _client(_raise, breaker=breaker) as client:
        for _ in range(2):
            with pytest.raises(NetworkError):
                client.get("https://example.test/x")
        with pytest.raises(CircuitOpenError):
            client.get("https://example.test/x")


def test_non_counted_exception_propagates_without_state_change() -> None:
    class _Boom:
        def __call__(self, request: httpx2.Request, next: object) -> httpx2.Response:
            msg = "boom"
            raise ValueError(msg)

    handler = _StatusSequence([200])
    breaker = CircuitBreaker(failure_threshold=1, _now=_Clock())
    client = Client(
        httpx2_client=httpx2.Client(transport=httpx2.MockTransport(handler)),
        middleware=[breaker, _Boom()],
    )
    with client:
        for _ in range(3):
            with pytest.raises(ValueError, match="boom"):
                client.get("https://example.test/x")


def test_reset_timeout_admits_probe_then_closes(caplog: pytest.LogCaptureFixture) -> None:
    clock = _Clock()
    handler = _StatusSequence([500, 500, 200])
    breaker = CircuitBreaker(failure_threshold=2, reset_timeout=30.0, success_threshold=1, _now=clock)
    with _client(handler, breaker=breaker) as client:
        for _ in range(2):
            with pytest.raises(InternalServerError):
                client.get("https://example.test/x")
        with pytest.raises(CircuitOpenError):
            client.get("https://example.test/x")
        assert handler.calls == 2
        clock.advance(30.0)
        with caplog.at_level(logging.INFO, logger="httpware.circuit_breaker"):
            response = client.get("https://example.test/x")
    assert response.status_code == HTTPStatus.OK
    assert handler.calls == 3
    messages = [r.message for r in caplog.records if r.name == "httpware.circuit_breaker"]
    assert any("half-open" in m for m in messages)
    assert any("closed" in m for m in messages)


def test_probe_failure_reopens_circuit() -> None:
    clock = _Clock()
    handler = _StatusSequence([500, 500, 500])
    breaker = CircuitBreaker(failure_threshold=2, reset_timeout=10.0, _now=clock)
    with _client(handler, breaker=breaker) as client:
        for _ in range(2):
            with pytest.raises(InternalServerError):
                client.get("https://example.test/x")
        clock.advance(10.0)
        with pytest.raises(InternalServerError):
            client.get("https://example.test/x")
        with pytest.raises(CircuitOpenError):
            client.get("https://example.test/x")
    assert handler.calls == 3


def test_success_threshold_requires_multiple_probes() -> None:
    clock = _Clock()
    handler = _StatusSequence([500, 500, 200, 200])
    breaker = CircuitBreaker(failure_threshold=2, reset_timeout=5.0, success_threshold=2, _now=clock)
    with _client(handler, breaker=breaker) as client:
        for _ in range(2):
            with pytest.raises(InternalServerError):
                client.get("https://example.test/x")
        clock.advance(5.0)
        client.get("https://example.test/x")
        client.get("https://example.test/x")
        response = client.get("https://example.test/x")
    assert response.status_code == HTTPStatus.OK
    assert handler.calls == 4


def test_half_open_second_concurrent_request_rejected_with_none_retry_after() -> None:
    """Two threads hit a half-open breaker; exactly one is the probe, the other is rejected."""
    clock = _Clock()
    probe_started = threading.Event()
    release_probe = threading.Event()

    def _handler(request: httpx2.Request) -> httpx2.Response:
        probe_started.set()
        release_probe.wait(timeout=5.0)
        return httpx2.Response(HTTPStatus.OK, request=request)

    breaker = CircuitBreaker(failure_threshold=1, reset_timeout=1.0, _now=clock)
    open_handler = _StatusSequence([500])
    with _client(open_handler, breaker=breaker) as opener:
        with pytest.raises(InternalServerError):
            opener.get("https://example.test/x")
    clock.advance(1.0)

    client = Client(
        httpx2_client=httpx2.Client(transport=httpx2.MockTransport(_handler)),
        middleware=[breaker],
    )
    rejected: list[CircuitOpenError] = []

    def _probe() -> None:
        client.get("https://example.test/probe")

    with client:
        t = threading.Thread(target=_probe)
        t.start()
        assert probe_started.wait(timeout=5.0)
        with pytest.raises(CircuitOpenError) as info:
            client.get("https://example.test/concurrent")
        rejected.append(info.value)
        release_probe.set()
        t.join(timeout=5.0)

    assert rejected[0].retry_after is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `just test tests/test_circuit_breaker_sync.py`
Expected: FAIL — `ImportError: cannot import name 'CircuitBreaker' from 'httpware.middleware.resilience.circuit_breaker'`.

- [ ] **Step 3: Implement `CircuitBreaker` (sync)**

Append to `src/httpware/middleware/resilience/circuit_breaker.py`:

```python
class CircuitBreaker:
    """Sync classic circuit breaker middleware. Mirror of AsyncCircuitBreaker.

    Serializes every state transition with a threading.Lock. Sharable across Clients
    (one shared circuit); a sync instance cannot be shared with an AsyncClient.
    """

    def __init__(
        self,
        *,
        failure_threshold: int = 5,
        reset_timeout: float = 30.0,
        success_threshold: int = 1,
        failure_status_codes: frozenset[int] | None = None,
        _now: Callable[[], float] = time.monotonic,
    ) -> None:
        self._state = _CircuitBreakerState(
            failure_threshold=failure_threshold,
            reset_timeout=reset_timeout,
            success_threshold=success_threshold,
            failure_status_codes=failure_status_codes,
            now=_now,
        )
        self._lock = threading.Lock()

    def __call__(self, request: httpx2.Request, next: Next) -> httpx2.Response:  # noqa: A002
        """Admit, forward, then record the outcome. Fast-fail when the circuit is not closed."""
        with self._lock:
            role = self._state.admit(request)
        try:
            response = next(request)
        except StatusError as exc:
            with self._lock:
                if self._state.is_failure_status(exc.response.status_code):
                    self._state.on_failure(role, request)
                else:
                    self._state.on_success(role, request)
            raise
        except (NetworkError, TimeoutError):
            with self._lock:
                self._state.on_failure(role, request)
            raise
        except BaseException:
            with self._lock:
                self._state.release_probe(role)
            raise
        with self._lock:
            self._state.on_success(role, request)
        return response
```

- [ ] **Step 4: Export `CircuitBreaker`**

In `src/httpware/middleware/resilience/__init__.py`:
```python
from httpware.middleware.resilience.circuit_breaker import AsyncCircuitBreaker, CircuitBreaker
```
`__all__` — insert `"CircuitBreaker",` after `"Bulkhead",`.

In `src/httpware/__init__.py` add `CircuitBreaker` to the resilience import (after `Bulkhead`) and `"CircuitBreaker",` to `__all__`. Alphabetical order around it: `BulkheadFullError`, **`CircuitBreaker`**, `CircuitOpenError`, `Client` — so insert `"CircuitBreaker",` after `"BulkheadFullError",` and before `"CircuitOpenError",` (added in Task 1).

```python
from httpware.middleware.resilience import (
    AsyncBulkhead,
    AsyncCircuitBreaker,
    AsyncRetry,
    AsyncTimeout,
    Bulkhead,
    CircuitBreaker,
    Retry,
    RetryBudget,
)
```

- [ ] **Step 5: Run sync tests + import check**

Run: `just test tests/test_circuit_breaker_sync.py`
Expected: PASS.
Run: `uv run python -c "import httpware; assert httpware.CircuitBreaker"`
Expected: exit 0.

- [ ] **Step 6: Full suite + 100% coverage**

Run: `just test`
Expected: PASS, coverage 100% (`--cov-fail-under=100` does not fail). If any line in `circuit_breaker.py` is uncovered (other than the `_check_loop` race `# pragma: no cover`), add the missing test before committing.

- [ ] **Step 7: Lint**

Run: `just lint`
Expected: clean.

- [ ] **Step 8: Commit**

```bash
git add src/httpware/middleware/resilience/circuit_breaker.py src/httpware/middleware/resilience/__init__.py src/httpware/__init__.py tests/test_circuit_breaker_sync.py
git commit -m "feat(resilience): add sync CircuitBreaker

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Task 5: Property test — OPEN-state invariant

**Files:**
- Test: `tests/test_circuit_breaker_props.py`

- [ ] **Step 1: Write the property test**

Create `tests/test_circuit_breaker_props.py`. Invariant: while OPEN and before `reset_timeout` elapses, `next` is never called (the transport call-count does not advance). Exercises the state machine directly (no HTTP) for speed and determinism.

```python
"""Property test: while OPEN and before reset_timeout, the breaker never forwards.

Drives the state machine directly via the public AsyncCircuitBreaker with a stub
`next` that records calls. Hypothesis generates random advance/outcome sequences.
"""

import httpx2
import pytest
from hypothesis import given, strategies as st

from httpware import CircuitOpenError, InternalServerError
from httpware.middleware.resilience.circuit_breaker import AsyncCircuitBreaker


class _Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def _request() -> httpx2.Request:
    return httpx2.Request("GET", "https://example.test/x")


@given(
    failure_threshold=st.integers(min_value=1, max_value=5),
    reset_timeout=st.floats(min_value=1.0, max_value=100.0),
    advances=st.lists(st.floats(min_value=0.0, max_value=0.5), min_size=1, max_size=20),
)
async def test_open_circuit_never_forwards_before_reset_timeout(
    failure_threshold: int,
    reset_timeout: float,
    advances: list[float],
) -> None:
    clock = _Clock()
    breaker = AsyncCircuitBreaker(
        failure_threshold=failure_threshold,
        reset_timeout=reset_timeout,
        _now=clock,
    )
    forwarded = 0

    async def _ok(request: httpx2.Request) -> httpx2.Response:
        nonlocal forwarded
        forwarded += 1
        return httpx2.Response(500, request=request)

    # Open the circuit: failure_threshold consecutive 500s (500 -> InternalServerError -> failure).
    async def _five_hundred(request: httpx2.Request) -> httpx2.Response:
        raise InternalServerError(httpx2.Response(500, request=request))

    for _ in range(failure_threshold):
        with pytest.raises(InternalServerError):
            await breaker(_request(), _five_hundred)

    # Now OPEN. Each advance stays strictly below reset_timeout (sum of advances <= 10 < reset_timeout
    # is NOT guaranteed; clamp by only advancing while total < reset_timeout).
    calls_before = forwarded
    total = 0.0
    for step in advances:
        if total + step >= reset_timeout:
            break
        total += step
        clock.t = total
        with pytest.raises(CircuitOpenError):
            await breaker(_request(), _ok)

    assert forwarded == calls_before  # next was never called while OPEN pre-timeout
```

- [ ] **Step 2: Run the property test to verify it passes**

Run: `just test tests/test_circuit_breaker_props.py`
Expected: PASS (hypothesis explores many sequences; no `next` call while OPEN pre-timeout).

- [ ] **Step 3: Lint**

Run: `just lint`
Expected: clean (confirm `InternalServerError` is imported at module top, no `PLC0415`).

- [ ] **Step 4: Commit**

```bash
git add tests/test_circuit_breaker_props.py
git commit -m "test(circuit-breaker): property test — OPEN never forwards pre-timeout

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Task 6: Docs + release notes

**Files:**
- Modify: `docs/resilience.md`
- Modify: `README.md`
- Create: `planning/releases/0.10.0.md`

- [ ] **Step 1: Read the existing docs to match tone/structure**

Read `docs/resilience.md` (existing Retry + Bulkhead sections) and the resilience paragraph in `README.md`. Match heading depth, code-fence style, and the "why" framing used for Bulkhead.

- [ ] **Step 2: Add the CircuitBreaker section to `docs/resilience.md`**

Add a `## Circuit breaker` section covering: what it does (classic consecutive-failure breaker), the three states, the constructor knobs (`failure_threshold`, `reset_timeout`, `success_threshold`, `failure_status_codes`), the failure classification (5xx + network + timeout; **429/4xx count as successes** — explain why tripping on 429 amplifies incidents), `CircuitOpenError` (and its `retry_after`), the observability events, and that the instance is sharable across clients (one shared circuit) but a sync instance can't be shared with an async one. Include a short async example and a sync example using `CircuitBreaker`.

- [ ] **Step 3: Add the AsyncTimeout section to `docs/resilience.md`**

Add a `## Overall timeout (async only)` section: what it bounds (total wall-clock across the inner pipeline, especially across an `AsyncRetry` loop), the `cm.expired()` distinction (our deadline → `httpware.TimeoutError`; inner timeout → propagates), and the two "why" notes: **why there is no sync `Timeout`** (no cancellation in sync Python) and **why it does not duplicate httpx2's per-call timeouts**.

- [ ] **Step 4: Add the recommended ordering note**

Add a short subsection (or extend the existing ordering guidance) documenting the recommended chain order and that it is **not enforced**:

```
AsyncTimeout → AsyncCircuitBreaker → AsyncBulkhead → AsyncRetry → terminal
```

Explain the consequence of breaker-outside-retry: an open circuit short-circuits the whole retry loop, and the breaker counts one outcome per fully-exhausted retry sequence.

- [ ] **Step 5: Update the README resilience paragraph**

In `README.md`, extend the resilience paragraph from "Retry + Bulkhead" to also list CircuitBreaker and AsyncTimeout (one phrase each), consistent with the existing style.

- [ ] **Step 6: Write `planning/releases/0.10.0.md`**

Create `planning/releases/0.10.0.md` following the format of the most recent release note in `planning/releases/`. Cover: new public names (`CircuitBreaker`, `AsyncCircuitBreaker`, `AsyncTimeout`, `CircuitOpenError`), the new observability events (`circuit.opened`, `circuit.rejected`, `circuit.half_open`, `circuit.closed`, `timeout.exceeded`), the additive/non-breaking nature, and the recommended ordering. Read an existing release note first to match structure.

- [ ] **Step 7: Build docs locally (if the project supports it) or sanity-check links**

Run: `uv run mkdocs build --strict` (if `mkdocs` is configured; otherwise skip)
Expected: builds without warnings. If `mkdocs` is not available, manually verify no broken internal links in the edited sections.

- [ ] **Step 8: Commit**

```bash
git add docs/resilience.md README.md planning/releases/0.10.0.md
git commit -m "docs(resilience): document CircuitBreaker + AsyncTimeout (0.10.0)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Final verification

- [ ] **Run the full gate**

Run: `just lint-ci && just test`
Expected: lint clean (no auto-fix needed), all tests pass, coverage 100%.

- [ ] **Confirm exports**

Run: `uv run python -c "import httpware; [getattr(httpware, n) for n in ('CircuitBreaker','AsyncCircuitBreaker','AsyncTimeout','CircuitOpenError')]; print('ok')"`
Expected: `ok`.

- [ ] **Architecture invariants**

Run: `grep -rE 'httpx2\._' src/httpware/ || echo "no private httpx2 access"`
Expected: `no private httpx2 access`.
Run: `grep -rn 'from __future__ import annotations' src/httpware/ || echo "clean"`
Expected: `clean`.

The branch is ready for `requesting-code-review` → `finishing-a-development-branch`. Release tagging (`0.10.0`) happens via the existing release flow: the tag name *is* the version (`uv version $GITHUB_REF_NAME`); do **not** bump `pyproject.toml`.

---

## Self-Review notes (author)

- **Spec coverage:** CircuitOpenError (T1), AsyncTimeout incl. `cm.expired()` inner-vs-deadline (T2), breaker state machine + classification + concurrency + loop guard (T3/T4), events (asserted in T2–T4 via caplog), property invariant (T5), docs/ordering/release (T6). All spec sections map to a task.
- **`test_observability.py`:** spec mentioned a centralized assertion "if asserted centrally" — there is none, so events are asserted in the feature files. Noted at the top of File Structure.
- **Type/name consistency:** `_CircuitBreakerState` methods (`admit`, `on_success`, `on_failure`, `release_probe`, `is_failure_status`, `_open`, `_emit`) are referenced identically in both wrappers. Role constants `_ROLE_CLOSED`/`_ROLE_PROBE`. Logger `httpware.circuit_breaker`. Event names match the spec table exactly.
- **Shared-core deviation** from bulkhead/retry duplication is called out in Task 3 with rationale; preserves the three spec-required properties.
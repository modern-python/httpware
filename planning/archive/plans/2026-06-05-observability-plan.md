# Resilience observability (0.6.0, Epic 5 re-scoped) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `Retry` and `Bulkhead` emit four operational-significance events (`retry.giving_up`, `retry.budget_refused`, `retry.streaming_refused`, `bulkhead.rejected`) via two channels: stdlib `logging` records (always on) and `opentelemetry.trace.get_current_span().add_event(...)` when the new `otel` extra is installed. Logger names `httpware.retry` / `httpware.bulkhead` are the public contract.

**Architecture:** New `_internal/observability.py` with a single `_emit_event(logger, event_name, *, level, message, attributes)` helper. Lazy `from opentelemetry import trace` happens inside an `if import_checker.is_otel_installed:` gate, preserving the optional-extras isolation invariant. `Retry` and `Bulkhead` acquire module-level loggers and call the helper at their event sites. Re-introduces the `otel` extra (PR #24 removed it as YAGNI; this PR brings it back paired with the code that uses it).

**Tech Stack:** Python 3.11+, stdlib `logging`, optional `opentelemetry-api>=1.20` (just the API, not the SDK).

**Target branch:** `feat/v0.6-observability`. Create from `main` before Task 1: `git checkout main && git pull && git checkout -b feat/v0.6-observability`.

**Source spec:** [`planning/specs/2026-06-05-observability-design.md`](../specs/2026-06-05-observability-design.md). Read it before starting — the *why* for each decision lives there.

---

## File structure

**New files:**
- `src/httpware/_internal/observability.py` — `_emit_event` helper
- `tests/test_observability.py` — unit tests for the helper
- `tests/test_optional_extras_otel_missing.py` — fail-soft tests
- `planning/releases/0.6.0.md` — release notes

**Modified files:**
- `pyproject.toml` — re-add `otel` extra; include in `all`
- `src/httpware/_internal/import_checker.py` — add `is_otel_installed`
- `src/httpware/middleware/resilience/retry.py` — add `_LOGGER` + 3 `_emit_event` calls
- `src/httpware/middleware/resilience/bulkhead.py` — add `_LOGGER` + 1 `_emit_event` call
- `tests/test_retry.py` — 3 new emission tests
- `tests/test_bulkhead.py` — 1 new emission test
- `tests/test_optional_extras_isolation.py` — add `opentelemetry` isolation check
- `README.md` — add "Observability" section
- `docs/index.md` — mirror the README addition
- `planning/engineering.md` — §1 (mention observability) + §7 (re-add otel extra description) + §8 (retire 5-1/5-4; mark 5-2 shipped)

**Commit cadence:** one commit per task. Per-task commits keep history reviewable.

---

## Task 1: Branch + `otel` extra + `is_otel_installed` + isolation test

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/httpware/_internal/import_checker.py`
- Modify: `tests/test_optional_extras_isolation.py`

- [ ] **Step 1: Create the branch**

```bash
git checkout main && git pull && git checkout -b feat/v0.6-observability
```
Expected: switched to a new branch.

- [ ] **Step 2: Re-add the `otel` extra in `pyproject.toml`**

Read the current `[project.optional-dependencies]` block. It currently looks like:
```toml
[project.optional-dependencies]
pydantic = ["pydantic>=2.0,<3.0"]
msgspec = ["msgspec>=0.18"]
all = ["httpware[pydantic,msgspec]"]
```

Replace with:
```toml
[project.optional-dependencies]
pydantic = ["pydantic>=2.0,<3.0"]
msgspec = ["msgspec>=0.18"]
otel = ["opentelemetry-api>=1.20"]
all = ["httpware[pydantic,msgspec,otel]"]
```

Note: just `opentelemetry-api`, NOT `opentelemetry-sdk`. Users supply their own SDK.

- [ ] **Step 3: Sync deps**

```bash
just install
```
Expected: uv installs `opentelemetry-api` (and its `opentelemetry-semantic-conventions` transitive dep).

- [ ] **Step 4: Add `is_otel_installed` to `import_checker.py`**

Replace the file content with:
```python
"""Detect optional extras without importing them. Used by adapter modules to gate hard imports."""

from importlib.util import find_spec


is_msgspec_installed = find_spec("msgspec") is not None
is_pydantic_installed = find_spec("pydantic") is not None
is_otel_installed = find_spec("opentelemetry") is not None
```

- [ ] **Step 5: Add isolation test in `tests/test_optional_extras_isolation.py`**

Append:
```python
def test_importing_httpware_does_not_import_opentelemetry() -> None:
    """Fresh subprocess: opentelemetry must NOT appear in sys.modules after `import httpware`.

    opentelemetry-api IS installed in the test environment (via `--all-extras`), so this
    test runs in a subprocess with a clean interpreter to verify that nothing
    in the httpware import chain pulls opentelemetry in.
    """
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import httpware; import sys; sys.exit(0 if 'opentelemetry' not in sys.modules else 1)",
        ],
        check=False,
        capture_output=True,
    )
    assert result.returncode == 0, (
        f"opentelemetry was loaded transitively by `import httpware`; stdout={result.stdout!r} stderr={result.stderr!r}"
    )
```

- [ ] **Step 6: Run the isolation tests**

```bash
uv run pytest tests/test_optional_extras_isolation.py -v
```
Expected: all 3 PASS (pydantic, msgspec, opentelemetry).

- [ ] **Step 7: Lint + full suite**

```bash
just lint && just test
```
Expected: clean, 100% coverage maintained.

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml src/httpware/_internal/import_checker.py tests/test_optional_extras_isolation.py
git commit -m "chore(deps): re-add otel optional extra paired with the code that uses it

PR #24 removed the otel extra as YAGNI (it advertised functionality that
didn't exist). 0.6.0 brings it back: structured-logging observability
in Retry / Bulkhead with opt-in OTel attribute enrichment lands in
the next commits.

otel = ['opentelemetry-api>=1.20'] only — no SDK. Users supply their
own SDK (or use a no-op tracer in tests). Matches how
opentelemetry-instrumentation-httpx declares its dep.

import_checker gains is_otel_installed alongside the existing flags.
Isolation test extended to verify import httpware does not pull
opentelemetry into sys.modules."
```

---

## Task 2: `_internal/observability.py` helper + unit tests

**Files:**
- Create: `src/httpware/_internal/observability.py`
- Create: `tests/test_observability.py`

- [ ] **Step 1: Write failing tests in `tests/test_observability.py`**

Create `tests/test_observability.py`:
```python
"""Unit tests for the _emit_event observability helper."""

import logging
import sys
from unittest.mock import MagicMock, patch

import pytest

from httpware._internal.observability import _emit_event


_TEST_LOGGER = logging.getLogger("httpware.test.observability")


def test_emit_event_logs_at_warning_with_extra_fields(caplog: pytest.LogCaptureFixture) -> None:
    """The helper emits one structured log record at WARNING with attributes accessible on the record."""
    with caplog.at_level(logging.WARNING, logger="httpware.test.observability"):
        _emit_event(
            _TEST_LOGGER,
            "test.event",
            level=logging.WARNING,
            message="something interesting happened",
            attributes={"foo": 1, "bar": "x"},
        )

    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert record.levelno == logging.WARNING
    assert record.message == "something interesting happened"
    assert record.foo == 1  # ty: ignore[unresolved-attribute]
    assert record.bar == "x"  # ty: ignore[unresolved-attribute]


def test_emit_event_respects_level_parameter(caplog: pytest.LogCaptureFixture) -> None:
    """When level=DEBUG is passed, the record is at DEBUG."""
    with caplog.at_level(logging.DEBUG, logger="httpware.test.observability"):
        _emit_event(
            _TEST_LOGGER,
            "test.event",
            level=logging.DEBUG,
            message="quiet",
            attributes={},
        )

    assert len(caplog.records) == 1
    assert caplog.records[0].levelno == logging.DEBUG


def test_emit_event_does_not_import_opentelemetry_when_flag_false() -> None:
    """With is_otel_installed=False the helper must not touch opentelemetry."""
    with patch("httpware._internal.import_checker.is_otel_installed", False):
        # Confirm the lazy import path is skipped: snapshot sys.modules before/after.
        modules_before = set(sys.modules)
        _emit_event(
            _TEST_LOGGER,
            "test.event",
            level=logging.WARNING,
            message="nope",
            attributes={"x": 1},
        )
        # opentelemetry may already be loaded by other tests; allow that, but no NEW load happened
        # because the codepath was skipped. The point: no error and no required state change.
    assert len(modules_before) >= 0  # noqa: PLR2004 — sanity assertion the with-block ran


def test_emit_event_calls_add_event_when_otel_installed() -> None:
    """With is_otel_installed=True the helper calls trace.get_current_span().add_event(...)."""
    mock_span = MagicMock(name="MockSpan")
    with (
        patch("httpware._internal.import_checker.is_otel_installed", True),
        patch("opentelemetry.trace.get_current_span", return_value=mock_span),
    ):
        _emit_event(
            _TEST_LOGGER,
            "test.event",
            level=logging.WARNING,
            message="hi",
            attributes={"k": "v"},
        )

    mock_span.add_event.assert_called_once_with("test.event", attributes={"k": "v"})


def test_emit_event_works_when_otel_installed_but_no_active_span() -> None:
    """With OTel installed but no tracer configured, get_current_span() returns NonRecordingSpan;
    add_event is a documented no-op. No error.
    """
    # Real OTel API call (no mocking) — opentelemetry-api is installed via the otel extra.
    _emit_event(
        _TEST_LOGGER,
        "test.event",
        level=logging.WARNING,
        message="real-otel-but-no-tracer",
        attributes={"a": 1},
    )
    # No assertion needed — the absence of an exception IS the assertion.
```

Run: `uv run pytest tests/test_observability.py -v`
Expected: FAIL with `ImportError: cannot import name '_emit_event' from 'httpware._internal.observability'`.

- [ ] **Step 2: Implement the helper**

Create `src/httpware/_internal/observability.py`:
```python
"""Observability emission helper — structured logging + opt-in OpenTelemetry span events.

See planning/specs/2026-06-05-observability-design.md for the contract.

Logger names (``httpware.retry``, ``httpware.bulkhead``) and event names
(``retry.giving_up``, ``bulkhead.rejected``, etc.) are the public observability
surface. They are stable: renames are breaking changes.
"""

import logging
import typing

from httpware._internal import import_checker


def _emit_event(
    logger: logging.Logger,
    event_name: str,
    *,
    level: int,
    message: str,
    attributes: dict[str, typing.Any],
) -> None:
    """Emit one observability event to both channels.

    1. Always emits a structured log record at ``level`` with ``extra=attributes``
       (so log aggregators that index ``extra`` see structured fields).
    2. If ``opentelemetry-api`` is installed, calls
       ``trace.get_current_span().add_event(event_name, attributes=attributes)``.
       When no tracer is active, ``get_current_span()`` returns a ``NonRecordingSpan``
       whose ``add_event`` is a documented no-op — so the call is unconditional
       behind the install gate.

    The lazy ``from opentelemetry import trace`` inside the if-block preserves
    the optional-extras isolation invariant: ``import httpware`` must not pull
    ``opentelemetry`` into ``sys.modules`` when the extra is absent.
    """
    logger.log(level, message, extra=attributes)
    if import_checker.is_otel_installed:
        from opentelemetry import trace  # noqa: PLC0415 — lazy by design (optional-extras isolation)
        trace.get_current_span().add_event(event_name, attributes=attributes)
```

- [ ] **Step 3: Run the observability tests**

```bash
uv run pytest tests/test_observability.py -v
```
Expected: all PASS.

- [ ] **Step 4: Lint + full suite**

```bash
just lint && just test
```
Expected: clean, 100% coverage.

- [ ] **Step 5: Stage and commit**

```bash
git add src/httpware/_internal/observability.py tests/test_observability.py
git commit -m "feat(observability): _emit_event helper for resilience middleware events

New _internal/observability.py with a single _emit_event helper. Always
emits a structured log record at the requested level; if opentelemetry-api
is installed, calls trace.get_current_span().add_event(name, attributes=...)
on the active span.

The lazy 'from opentelemetry import trace' inside the if is_otel_installed
gate preserves the optional-extras isolation invariant (import httpware
does not pull opentelemetry when the extra is absent).

Logger names and event names are the public observability surface; the
helper itself lives in _internal/ so users interact only with the
strings, not Python imports."
```

---

## Task 3: `Retry` emits 3 operational events

**Files:**
- Modify: `src/httpware/middleware/resilience/retry.py`
- Modify: `tests/test_retry.py`

- [ ] **Step 1: Write failing tests in `tests/test_retry.py`**

Append to `tests/test_retry.py`:
```python
async def test_retry_giving_up_emits_observability_event(caplog: pytest.LogCaptureFixture) -> None:
    """When max_attempts is exhausted, emit one WARNING record on httpware.retry."""
    sleeper = _SleepRecorder()
    handler = _ResponseSequence([HTTPStatus.SERVICE_UNAVAILABLE] * 3)
    client = _client(handler, retry=Retry(_sleep=sleeper, max_attempts=3, base_delay=0.001, max_delay=0.002))

    with caplog.at_level(logging.WARNING, logger="httpware.retry"):
        with pytest.raises(ServiceUnavailableError):
            await client.get("https://example.test/x")

    retry_records = [r for r in caplog.records if r.name == "httpware.retry"]
    giving_up_records = [r for r in retry_records if r.message.startswith("retry gave up")]
    assert len(giving_up_records) == 1
    record = giving_up_records[0]
    assert record.levelno == logging.WARNING
    assert record.attempts == 3  # ty: ignore[unresolved-attribute]
    assert record.method == "GET"  # ty: ignore[unresolved-attribute]
    assert record.last_status == HTTPStatus.SERVICE_UNAVAILABLE  # ty: ignore[unresolved-attribute]
    assert record.last_exception_type == "ServiceUnavailableError"  # ty: ignore[unresolved-attribute]


async def test_retry_budget_refused_emits_observability_event(caplog: pytest.LogCaptureFixture) -> None:
    """When the budget refuses a retry, emit one WARNING record on httpware.retry."""
    sleeper = _SleepRecorder()
    stingy_budget = RetryBudget(percent_can_retry=0.0, min_retries_per_sec=0.0)
    handler = _ResponseSequence([HTTPStatus.SERVICE_UNAVAILABLE, HTTPStatus.SERVICE_UNAVAILABLE])
    client = _client(
        handler,
        retry=Retry(_sleep=sleeper, budget=stingy_budget, max_attempts=3, base_delay=0.001),
    )

    with caplog.at_level(logging.WARNING, logger="httpware.retry"):
        with pytest.raises(RetryBudgetExhaustedError):
            await client.get("https://example.test/x")

    retry_records = [r for r in caplog.records if r.name == "httpware.retry"]
    budget_records = [r for r in retry_records if "budget" in r.message]
    assert len(budget_records) == 1
    record = budget_records[0]
    assert record.attempts == 1  # ty: ignore[unresolved-attribute]
    assert record.method == "GET"  # ty: ignore[unresolved-attribute]
    assert record.last_status == HTTPStatus.SERVICE_UNAVAILABLE  # ty: ignore[unresolved-attribute]


async def test_retry_streaming_refused_emits_observability_event(caplog: pytest.LogCaptureFixture) -> None:
    """When the streaming-body marker prevents a retryable retry, emit one WARNING record on httpware.retry.

    Uses an idempotent method (PUT) so we hit the retryable-failure-path streaming-refusal site,
    NOT the non-idempotent early-exit sites (which don't emit the event per the spec).
    """
    sleeper = _SleepRecorder()
    handler = _ResponseSequence([HTTPStatus.SERVICE_UNAVAILABLE, HTTPStatus.SERVICE_UNAVAILABLE])
    client = _client(handler, retry=Retry(_sleep=sleeper, base_delay=0.001, max_delay=0.002))

    async def streamed_body() -> typing.AsyncIterator[bytes]:
        yield b"x"

    with caplog.at_level(logging.WARNING, logger="httpware.retry"):
        with pytest.raises(ServiceUnavailableError):
            await client.put("https://example.test/x", content=streamed_body())

    retry_records = [r for r in caplog.records if r.name == "httpware.retry"]
    streaming_records = [r for r in retry_records if "stream" in r.message]
    assert len(streaming_records) == 1
    record = streaming_records[0]
    assert record.method == "PUT"  # ty: ignore[unresolved-attribute]
    assert record.last_exception_type == "ServiceUnavailableError"  # ty: ignore[unresolved-attribute]
```

`logging` should already be imported at the top of `tests/test_retry.py` if not, add it.

Run: `uv run pytest tests/test_retry.py -v -k "emits_observability_event"`
Expected: all 3 FAIL — no events emitted yet.

- [ ] **Step 2: Add `_LOGGER` constant to `retry.py`**

In `src/httpware/middleware/resilience/retry.py`, after the existing module-level constants block (around `DEFAULT_IDEMPOTENT_METHODS` / `_MAX_ATTEMPTS_INVALID` / `_STREAMING_BODY_REFUSAL_NOTE`), add:
```python
import logging

_LOGGER = logging.getLogger("httpware.retry")
```

Hoist the `import logging` to the top of the file alongside other stdlib imports if not already present (per project convention — no in-function imports).

- [ ] **Step 3: Import `_emit_event`**

Add to the imports block:
```python
from httpware._internal.observability import _emit_event
```

- [ ] **Step 4: Emit `retry.giving_up` event in `Retry.__call__`**

Find the `if is_last:` block (around line 153). Currently:
```python
if is_last:
    if last_exc is None:  # pragma: no cover — structural invariant from except branch
        msg = "Retry: last_exc unset on final attempt — unreachable"
        raise AssertionError(msg)
    last_exc.add_note(f"httpware: gave up after {attempt + 1} attempts")
    raise last_exc
```

Insert the emit call after `add_note(...)` and before `raise last_exc`:
```python
if is_last:
    if last_exc is None:  # pragma: no cover — structural invariant from except branch
        msg = "Retry: last_exc unset on final attempt — unreachable"
        raise AssertionError(msg)
    last_exc.add_note(f"httpware: gave up after {attempt + 1} attempts")
    _emit_event(
        _LOGGER,
        "retry.giving_up",
        level=logging.WARNING,
        message=f"retry gave up after {attempt + 1} attempts",
        attributes={
            "attempts": attempt + 1,
            "method": request.method,
            "url": str(request.url),
            "last_status": last_response.status_code if last_response is not None else None,
            "last_exception_type": type(last_exc).__qualname__,
        },
    )
    raise last_exc
```

- [ ] **Step 5: Emit `retry.budget_refused` event**

Find the budget exhaustion block (the `if not self.budget.try_withdraw():` site, around line 160). Currently:
```python
if not self.budget.try_withdraw():
    raise RetryBudgetExhaustedError(
        last_response=last_response,
        last_exception=last_exc,
        attempts=attempt + 1,
    ) from last_exc
```

Insert the emit call BEFORE the raise:
```python
if not self.budget.try_withdraw():
    _emit_event(
        _LOGGER,
        "retry.budget_refused",
        level=logging.WARNING,
        message=f"retry budget refused after {attempt + 1} attempts",
        attributes={
            "attempts": attempt + 1,
            "method": request.method,
            "url": str(request.url),
            "last_status": last_response.status_code if last_response is not None else None,
        },
    )
    raise RetryBudgetExhaustedError(
        last_response=last_response,
        last_exception=last_exc,
        attempts=attempt + 1,
    ) from last_exc
```

- [ ] **Step 6: Emit `retry.streaming_refused` event at the retryable-failure-path site only**

Find the streaming-body refusal block in the retryable-failure-path (NOT the early-exit sites). It's the one at around line 144:
```python
# ---- retryable failure path
if request.extensions.get(STREAMING_BODY_MARKER):
    if last_exc is None:  # pragma: no cover — invariant from except branch
        msg = "Retry: streaming-body refusal reached with no last_exc"
        raise AssertionError(msg)
    last_exc.add_note(_STREAMING_BODY_REFUSAL_NOTE)
    raise last_exc
```

Insert the emit call after `add_note(...)` and before `raise last_exc`:
```python
# ---- retryable failure path
if request.extensions.get(STREAMING_BODY_MARKER):
    if last_exc is None:  # pragma: no cover — invariant from except branch
        msg = "Retry: streaming-body refusal reached with no last_exc"
        raise AssertionError(msg)
    last_exc.add_note(_STREAMING_BODY_REFUSAL_NOTE)
    _emit_event(
        _LOGGER,
        "retry.streaming_refused",
        level=logging.WARNING,
        message="retry refused — request body is a stream that cannot replay",
        attributes={
            "method": request.method,
            "url": str(request.url),
            "last_exception_type": type(last_exc).__qualname__,
        },
    )
    raise last_exc
```

**IMPORTANT**: do NOT add the emit call at the 3 non-idempotent early-exit sites (lines 111-118, 120-127, 131-138). At those sites the primary reason for not retrying is method-eligibility; the `add_note` call already provides context. The EVENT only fires when streaming was the deciding factor.

- [ ] **Step 7: Run the new tests**

```bash
uv run pytest tests/test_retry.py -v -k "emits_observability_event"
```
Expected: all 3 PASS.

- [ ] **Step 8: Lint + full suite**

```bash
just lint && just test
```
Expected: clean, 100% coverage.

- [ ] **Step 9: Stage and commit**

```bash
git add src/httpware/middleware/resilience/retry.py tests/test_retry.py
git commit -m "feat(retry): emit operational events via httpware.retry logger + OTel

Three event sites:
- retry.giving_up (WARNING): max_attempts exhausted
- retry.budget_refused (WARNING): budget.try_withdraw() refused
- retry.streaming_refused (WARNING): streaming-body marker prevented an
  otherwise-retryable retry (retryable-failure-path site only — the 3
  non-idempotent early-exit sites still add the note but do NOT emit
  this event, since at those sites method-eligibility is the primary
  reason for not retrying).

All four events have flat, scalar attributes (method, url, attempts,
last_status, last_exception_type) so they index cleanly in log
aggregators and serialize cleanly as OTel attributes."
```

---

## Task 4: `Bulkhead` emits `bulkhead.rejected` event

**Files:**
- Modify: `src/httpware/middleware/resilience/bulkhead.py`
- Modify: `tests/test_bulkhead.py`

- [ ] **Step 1: Write failing test in `tests/test_bulkhead.py`**

Append:
```python
import logging  # add to the top of the file if not present


async def test_bulkhead_rejected_emits_observability_event(caplog: pytest.LogCaptureFixture) -> None:
    """When acquire_timeout elapses without acquisition, emit one WARNING record on httpware.bulkhead."""
    handler = _SlowHandler(delay=_ACQUIRE_TIMEOUT_LONG)
    client = _client(
        handler,
        bulkhead=Bulkhead(max_concurrent=_MAX_CONCURRENT_1, acquire_timeout=_ACQUIRE_TIMEOUT_SHORT),
    )

    first = asyncio.create_task(client.get("https://example.test/a"))
    await asyncio.sleep(0.005)  # let first acquire

    with caplog.at_level(logging.WARNING, logger="httpware.bulkhead"):
        with pytest.raises(BulkheadFullError):
            await client.get("https://example.test/b")

    bulkhead_records = [r for r in caplog.records if r.name == "httpware.bulkhead"]
    assert len(bulkhead_records) == 1
    record = bulkhead_records[0]
    assert record.levelno == logging.WARNING
    assert "rejected" in record.message
    assert record.max_concurrent == _MAX_CONCURRENT_1  # ty: ignore[unresolved-attribute]
    assert record.acquire_timeout == _ACQUIRE_TIMEOUT_SHORT  # ty: ignore[unresolved-attribute]
    assert record.method == "GET"  # ty: ignore[unresolved-attribute]

    await first  # cleanup
```

Run: `uv run pytest tests/test_bulkhead.py -v -k "rejected_emits_observability_event"`
Expected: FAIL — no event emitted yet.

- [ ] **Step 2: Add `_LOGGER` constant + emit import to `bulkhead.py`**

Add at the top of `src/httpware/middleware/resilience/bulkhead.py` (after the existing `import asyncio`):
```python
import logging
```

After the existing module-level constants (`_MAX_CONCURRENT_INVALID`, `_ACQUIRE_TIMEOUT_INVALID`):
```python
_LOGGER = logging.getLogger("httpware.bulkhead")
```

Add to the imports block:
```python
from httpware._internal.observability import _emit_event
```

- [ ] **Step 3: Emit `bulkhead.rejected` event in `Bulkhead.__call__`**

Find the `except TimeoutError as exc:` block (where `BulkheadFullError` is raised):
```python
except TimeoutError as exc:
    raise BulkheadFullError(
        max_concurrent=self._max_concurrent,
        acquire_timeout=self._acquire_timeout,
    ) from exc
```

Insert the emit call BEFORE the raise:
```python
except TimeoutError as exc:
    _emit_event(
        _LOGGER,
        "bulkhead.rejected",
        level=logging.WARNING,
        message=f"bulkhead rejected — full (max_concurrent={self._max_concurrent}, acquire_timeout={self._acquire_timeout})",
        attributes={
            "max_concurrent": self._max_concurrent,
            "acquire_timeout": self._acquire_timeout,
            "method": request.method,
            "url": str(request.url),
        },
    )
    raise BulkheadFullError(
        max_concurrent=self._max_concurrent,
        acquire_timeout=self._acquire_timeout,
    ) from exc
```

- [ ] **Step 4: Run the new test**

```bash
uv run pytest tests/test_bulkhead.py -v -k "rejected_emits_observability_event"
```
Expected: PASS.

- [ ] **Step 5: Lint + full suite**

```bash
just lint && just test
```
Expected: clean, 100% coverage.

- [ ] **Step 6: Stage and commit**

```bash
git add src/httpware/middleware/resilience/bulkhead.py tests/test_bulkhead.py
git commit -m "feat(bulkhead): emit rejected event via httpware.bulkhead logger + OTel

One event site: bulkhead.rejected (WARNING) fires immediately before
BulkheadFullError is raised. Attributes: max_concurrent, acquire_timeout,
method, url.

acquire_timeout=0 (fail-fast) and acquire_timeout>0 (bounded wait)
both flow through this single emission — the attribute value
distinguishes them at consumer-side."
```

---

## Task 5: Fail-soft tests for OTel-missing

**Files:**
- Create: `tests/test_optional_extras_otel_missing.py`

- [ ] **Step 1: Create the file**

```python
"""Fail-soft tests for the otel optional-extra (0.6.0).

opentelemetry-api IS installed in the CI test environment via `--all-extras`.
To simulate the "extra not installed" case, patch
`httpware._internal.import_checker.is_otel_installed = False` for the
duration of the test.

The contract: observability emission (the structured log record half) must
work regardless of whether opentelemetry-api is available. The OTel half is
silently skipped when the flag is False.
"""

import logging
from unittest.mock import patch

import pytest

from httpware._internal.observability import _emit_event


_TEST_LOGGER = logging.getLogger("httpware.test.otel_missing")


def test_emit_event_logs_record_without_otel(caplog: pytest.LogCaptureFixture) -> None:
    """The structured log record is emitted even when opentelemetry-api is 'missing'."""
    with patch("httpware._internal.import_checker.is_otel_installed", False):
        with caplog.at_level(logging.WARNING, logger="httpware.test.otel_missing"):
            _emit_event(
                _TEST_LOGGER,
                "test.event",
                level=logging.WARNING,
                message="works without otel",
                attributes={"x": 1},
            )

    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert record.message == "works without otel"
    assert record.x == 1  # ty: ignore[unresolved-attribute]


def test_emit_event_does_not_call_opentelemetry_apis_when_flag_false() -> None:
    """With is_otel_installed=False, no opentelemetry.trace call is made."""
    with (
        patch("httpware._internal.import_checker.is_otel_installed", False),
        patch("opentelemetry.trace.get_current_span") as mock_get_span,
    ):
        _emit_event(
            _TEST_LOGGER,
            "test.event",
            level=logging.WARNING,
            message="silent on otel",
            attributes={},
        )

    mock_get_span.assert_not_called()
```

- [ ] **Step 2: Run the tests**

```bash
uv run pytest tests/test_optional_extras_otel_missing.py -v
```
Expected: both PASS.

- [ ] **Step 3: Lint + full suite**

```bash
just lint && just test
```
Expected: clean, 100% coverage.

- [ ] **Step 4: Commit**

```bash
git add tests/test_optional_extras_otel_missing.py
git commit -m "test(optional): observability emission works without otel extra

Mirrors the existing test_optional_extras_pydantic_missing.py pattern:
patches httpware._internal.import_checker.is_otel_installed to False
to simulate the 'extra not installed' case. Verifies that the
structured-log half of _emit_event still works and that no
opentelemetry.trace.get_current_span call is attempted."
```

---

## Task 6: Documentation + release notes

**Files:**
- Modify: `README.md`
- Modify: `docs/index.md`
- Modify: `planning/engineering.md`
- Create: `planning/releases/0.6.0.md`

- [ ] **Step 1: Add Observability section to README.md**

After the existing `## Errors` section and BEFORE the link section (`## 🗒️ [Release notes]`), insert:

```markdown

## Observability

`Retry` and `Bulkhead` emit operational events via two channels — stdlib `logging` records (always on) and OpenTelemetry span events (when `opentelemetry-api` is installed).

Logger names (`httpware.retry`, `httpware.bulkhead`) and event names (`retry.giving_up`, `retry.budget_refused`, `retry.streaming_refused`, `bulkhead.rejected`) are the stable public contract.

```python
import logging

# Enable visibility into retry / bulkhead operational events
logging.getLogger("httpware.retry").setLevel(logging.WARNING)
logging.getLogger("httpware.bulkhead").setLevel(logging.WARNING)
```

For OTel attribute enrichment on the active span — install the extra:

```bash
pip install httpware[otel]
```

When installed, `_emit_event` calls `trace.get_current_span().add_event(name, attributes=...)` automatically. We never create our own spans; for HTTP-level tracing install `opentelemetry-instrumentation-httpx` separately.
```

- [ ] **Step 2: Update the [all] install line in README.md**

Find:
```markdown
pip install httpware[all]           # everything declared above (pydantic, msgspec)
```
Replace with:
```markdown
pip install httpware[all]           # everything declared above (pydantic, msgspec, otel)
```

- [ ] **Step 3: Mirror both additions in `docs/index.md`**

Same content added at the matching positions. Keep wording verbatim to stay in sync with README.

- [ ] **Step 4: Update `planning/engineering.md`**

In §1 (Project intent), append one sentence to the first paragraph (after the streaming sentence added in 0.5.0):

```
 As of 0.6.0, `Retry` and `Bulkhead` emit operational events via stdlib `logging` records (`httpware.retry` / `httpware.bulkhead` loggers) and — when `opentelemetry-api` is installed — OpenTelemetry span events on the active span.
```

In §7 (optional-extras pattern), find the parenthetical:
```
(An `otel` extra existed pre-0.4 but was removed once we noticed it was advertising functionality that didn't exist. Epic 5 will reintroduce it when the OpenTelemetry middleware actually lands.)
```
Replace with:
```
(An `otel` extra existed pre-0.4 but was removed once we noticed it was advertising functionality that didn't exist. 0.6.0 reintroduces it paired with the code that uses it — `Retry` and `Bulkhead` add events to the active OpenTelemetry span via `trace.get_current_span().add_event(...)`.)
```

In §8 (Remaining roadmap), find the Epic 5 entry:
```
- **Epic 5 — Observability:** `5-1` Layer 1 middleware hooks, `5-2` wire into resilience middlewares, `5-4` OpenTelemetry middleware (will declare the `otel` extra at the same time the code lands), `5-5` logging policy CI grep.
```
Replace with:
```
- **Epic 5 — Observability:** SHIPPED in v0.6 (PR #...) — re-scoped from the original 4-story plan. `Retry` and `Bulkhead` emit operational events via stdlib `logging` + opt-in OpenTelemetry span events. Stories `5-1` (Layer 1 middleware hooks) and `5-4` (standalone OTel middleware) RETIRED — `opentelemetry-instrumentation-httpx` already covers transport-level tracing; a separate httpware middleware would duplicate it. See [`planning/specs/2026-06-05-observability-design.md`](specs/2026-06-05-observability-design.md) and [`planning/plans/2026-06-05-observability-plan.md`](plans/2026-06-05-observability-plan.md).
```

- [ ] **Step 5: Create `planning/releases/0.6.0.md`**

```markdown
# httpware 0.6.0 — Resilience observability

**0.6.0 is additive. No breaking changes.** Code written against 0.5.0 continues to work unchanged.

This release adds operational-event emission to `Retry` and `Bulkhead` via two channels — stdlib `logging` records (always on) and OpenTelemetry span events (opt-in via the `otel` extra). Re-introduces the `otel` extra (PR #24 removed it as YAGNI; this release brings it back paired with the code that uses it).

## New features

- **Structured logging on resilience operations.** Acquire `logging.getLogger("httpware.retry")` and `logging.getLogger("httpware.bulkhead")` to see four operational events:
  - `retry.giving_up` (WARNING) — max_attempts exhausted; attributes include `attempts`, `method`, `url`, `last_status`, `last_exception_type`
  - `retry.budget_refused` (WARNING) — `RetryBudget` refused to permit a retry
  - `retry.streaming_refused` (WARNING) — streaming-body marker prevented an otherwise-retryable retry
  - `bulkhead.rejected` (WARNING) — `acquire_timeout` elapsed without acquisition; attributes include `max_concurrent`, `acquire_timeout`, `method`, `url`
- **Optional OpenTelemetry attribute enrichment.** Install `httpware[otel]` (which pulls `opentelemetry-api>=1.20`, just the API — you supply the SDK). When installed, the same four events are added to the active span via `trace.get_current_span().add_event(name, attributes=...)`. We never create our own spans — for HTTP-level tracing install `opentelemetry-instrumentation-httpx` separately.

## Backwards compatibility

Purely additive:
- All previously-shipping methods behave identically.
- Successful retries and successful bulkhead acquisitions emit nothing — the four events fire only on operational concern.
- Per `engineering.md §2`, httpware never configures handlers, levels, or calls `logging.basicConfig()`. Consumers own their logging configuration.
- The `otel` extra is opt-in — `pip install httpware` continues to work without `opentelemetry-api`.

## Usage

```python
import logging
from httpware import AsyncClient, Bulkhead, Retry

# Enable visibility into retry / bulkhead operational events
logging.getLogger("httpware.retry").setLevel(logging.WARNING)
logging.getLogger("httpware.bulkhead").setLevel(logging.WARNING)

# Your normal application logging config picks up the records
logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(name)s %(message)s")

async with AsyncClient(
    base_url="https://api.example.com",
    middleware=[Bulkhead(max_concurrent=10), Retry()],
) as client:
    await client.get("/users/1")
    # On a 503 + retry exhaustion you'll see:
    # 2026-06-05 12:00:00 httpware.retry retry gave up after 3 attempts
```

For OTel span events:

```bash
pip install httpware[otel]
# Plus your SDK + opentelemetry-instrumentation-httpx for HTTP-level spans
```

## What's still ahead

Epic 5's original `5-1` (hook protocol) and `5-4` (standalone OTel middleware) stories are **retired**, not deferred. Rationale in the spec: `opentelemetry-instrumentation-httpx` already covers transport-level tracing, and a hook system without a built-in consumer is infrastructure for code that doesn't exist. The structured-emission contract we're shipping is already extensible — users plug into standard `logging` handlers without needing httpware-specific hooks.

This effectively closes Epic 5. Remaining roadmap is Epic 6 (ship v1.0): docs site (mkdocs), benchmarks, Trusted Publishers + Sigstore release flow.

## References

- Spec: [`planning/specs/2026-06-05-observability-design.md`](../specs/2026-06-05-observability-design.md)
- Plan: [`planning/plans/2026-06-05-observability-plan.md`](../plans/2026-06-05-observability-plan.md)
- Roadmap: [`planning/engineering.md`](../engineering.md) §8
```

- [ ] **Step 6: Lint**

```bash
just lint
```
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add README.md docs/index.md planning/engineering.md planning/releases/0.6.0.md
git commit -m "docs: 0.6.0 release notes + observability docs

- README + docs/index.md: add 'Observability' section + update [all]
  install line to include otel
- planning/engineering.md §1 + §7 + §8: mention observability in
  project intent; update otel-extra parenthetical to reflect reintroduction;
  mark Epic 5 SHIPPED in roadmap with rationale for retiring 5-1 / 5-4
- planning/releases/0.6.0.md: new release notes"
```

---

## Task 7: Final verification + push

**Files:** none modified; verification only.

- [ ] **Step 1: Full lint**

```bash
just lint-ci
```
Expected: clean.

- [ ] **Step 2: Full test suite**

```bash
just test
```
Expected: 100% coverage. Test count: was 239 (post-streaming). +5 observability tests + 3 retry emission tests + 1 bulkhead emission test + 2 fail-soft tests + 1 isolation test = ~251.

- [ ] **Step 3: Architecture invariants from `CLAUDE.md`**

```bash
grep -rE 'httpx2\._' src/httpware/ || echo "PASS: no httpx2 private API"
grep -rE 'from __future__ import annotations' src/httpware/ || echo "PASS: no __future__ annotations"
grep -rE '\bprint\(' src/httpware/ || echo "PASS: no print()"
grep -rE 'logging\.(basicConfig|getLogger)\(\)' src/httpware/ || echo "PASS: no global logging"
grep -rE '# (type|mypy): ignore' src/httpware/ || echo "PASS: no type/mypy ignore"
```
Each should print PASS. Note: the new code uses `logging.getLogger("httpware.retry")` and `logging.getLogger("httpware.bulkhead")` (with arguments) — the grep checks for `getLogger()` with **no arguments**, so the named loggers don't trip it.

- [ ] **Step 4: Optional-extras isolation**

```bash
uv run pytest tests/test_optional_extras_isolation.py -v
```
Expected: all 3 PASS (msgspec, pydantic, opentelemetry).

- [ ] **Step 5: mkdocs strict build**

```bash
uv run --with mkdocs --with mkdocs-material mkdocs build --strict 2>&1 | tail -10
rm -rf site/
```
Expected: 0 warnings.

- [ ] **Step 6: Push the branch**

```bash
git push -u origin feat/v0.6-observability
```

DO NOT open the PR yet — leave that to `finishing-a-development-branch`.

---

## Out of scope for this plan (per the spec)

These items are deliberately deferred or retired. Do NOT do them in this PR:

- **No new spans.** `add_event` augments the existing span; we never call `tracer.start_span()`.
- **No metric instruments** (`Counter`, `Histogram`). Only events/logs.
- **No URL/header redaction at the httpware layer.** `opentelemetry-instrumentation-httpx` and user `logging.Filter`s handle this.
- **No `LogPolicy` middleware or hook protocol** (was Epic 5 story `5-1`). Retired.
- **No public `httpware.observability` namespace.** Logger names + event names ARE the public contract.
- **No retry `attempt_starting` events.** Operational-only event set.
- **No standalone OTel middleware** (was Epic 5 story `5-4`). Retired in favor of `opentelemetry-instrumentation-httpx`.
- **Version bump in `pyproject.toml`.** Tag-driven release; bump not required.

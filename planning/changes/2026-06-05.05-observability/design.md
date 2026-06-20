---
status: shipped
date: 2026-06-05
slug: observability
summary: Shipped 0.6.0 — logging + OTel events
supersedes: null
superseded_by: null
pr: 27
outcome: 'Shipped 0.6.0 — logging + OTel events'
---

# Spec: Resilience observability — structured logging + opt-in OTel attribute enrichment (0.6.0, Epic 5)

**Date:** 2026-06-05
**Topic slug:** `observability`
**Status:** drafted, awaiting user review
**Target release:** 0.6.0
**Epic 5 stories rolled in:** Re-scoped from the original 5-1/5-2/5-4/5-5. See "Re-scoping rationale" below.

## Purpose

Emit four operational-significance events from `Retry` and `Bulkhead` via two channels:

1. **Structured `logging` records** (always on, no dependency). Users plug in any log aggregator.
2. **OpenTelemetry `add_event` calls on the active span** (when the `otel` extra is installed). Augments existing spans created by `opentelemetry-instrumentation-httpx`; we never create our own spans.

The contract is the *event names + attribute keys*. Logger names (`httpware.retry`, `httpware.bulkhead`) and event names (`retry.giving_up`, `bulkhead.rejected`, etc.) are the public observability surface.

## Re-scoping rationale

The original Epic 5 (5-1 Layer 1 middleware hooks, 5-2 wire into resilience middlewares, 5-4 OpenTelemetry middleware, 5-5 logging policy CI grep) was assessed against `opentelemetry-instrumentation-httpx` and judged ~70% duplicative:

- **5-4 OTel middleware** would emit per-request spans with standard semantic conventions — already done by `pip install opentelemetry-instrumentation-httpx` at the transport layer, where it sees more than our middleware ever could.
- **5-1 / 5-2 hook system** without a built-in consumer is infrastructure for code that doesn't exist.

The 30% that *is* genuinely additive: `Retry` and `Bulkhead` know things `opentelemetry-instrumentation-httpx` cannot — "retry budget exhausted after N attempts" vs "bulkhead refused admission" vs "transport-level network error." Those distinctions are operationally critical and have no other source of truth.

This spec ships the additive 30% and explicitly retires the duplicative work. `5-1` hooks and `5-4` standalone OTel middleware are dropped from the roadmap. `5-5` log-policy CI grep is folded into this slice (the grep already runs in the per-task verification step; no new code).

## Non-goals

Items deliberately deferred or retired so this slice ships clean:

- **No new spans.** `add_event` augments the existing span (from `opentelemetry-instrumentation-httpx` or any other span the caller has open). We never call `tracer.start_span()`.
- **No metric instruments** (`Counter`, `Histogram`). Only events/logs. Users wanting Prometheus-style counters can write a `logging.Handler` that counts records by event name.
- **No URL/header redaction at the httpware layer.** `opentelemetry-instrumentation-httpx` handles URL redaction per its config; users wanting redaction at our level supply a `logging.Filter`.
- **No `LogPolicy` middleware or hook protocol** (was Epic 5 story `5-1`). Defer until users actually ask. The structured-emission contract is already extensible via standard logging — users plug into their own handlers without needing httpware-specific hooks.
- **No public `httpware.observability` namespace.** The emission helper lives in `_internal/`; users interact via logger names and OTel event/attribute names — both well-documented strings.
- **No retry `attempt_starting` events.** Per the "operational-only" event-set decision — successful retries are silent.
- **No standalone OTel middleware** (was Epic 5 story `5-4`). Retired in favor of `opentelemetry-instrumentation-httpx`.

## Architecture

Three coordinated changes:

```text
src/httpware/
├── _internal/
│   ├── import_checker.py          # add is_otel_installed
│   └── observability.py           # NEW — _emit_event helper
└── middleware/resilience/
    ├── retry.py                   # add 3 _emit_event call sites
    └── bulkhead.py                # add 1 _emit_event call site
```

`pyproject.toml` re-introduces the `otel = ["opentelemetry-api>=1.20"]` extra (just the API; the SDK is users' responsibility). The `all` extra includes it.

### `_internal/observability.py`

Exports a single public-within-package helper:

```python
import logging
import typing

from httpware._internal import import_checker


def _emit_event(
    logger: logging.Logger,
    event_name: str,
    *,
    level: int = logging.WARNING,
    message: str,
    attributes: dict[str, typing.Any],
) -> None:
    """Emit one observability event to both channels.

    1. Always emits a structured log record at the requested level with
       ``extra=attributes`` (users see structured fields in their aggregator).
    2. If ``import_checker.is_otel_installed`` is True, calls
       ``trace.get_current_span().add_event(event_name, attributes=attributes)``.
       When no tracer is active, ``get_current_span`` returns a
       ``NonRecordingSpan`` whose ``add_event`` is a documented no-op — so the
       call is unconditional behind the install gate.
    """
    logger.log(level, message, extra=attributes)
    if import_checker.is_otel_installed:
        from opentelemetry import trace  # noqa: PLC0415 — lazy by design
        trace.get_current_span().add_event(event_name, attributes=attributes)
```

The lazy `from opentelemetry import trace` inside the `if` block preserves the optional-extras isolation invariant: `import httpware` must not pull `opentelemetry` into `sys.modules`.

### `Retry` and `Bulkhead` integration

Each middleware acquires a module-level logger:

```python
# in retry.py:
_LOGGER = logging.getLogger("httpware.retry")

# in bulkhead.py:
_LOGGER = logging.getLogger("httpware.bulkhead")
```

These are the **public contract**. Users name them in their logging config:

```python
logging.getLogger("httpware.retry").setLevel(logging.WARNING)
logging.getLogger("httpware.bulkhead").setLevel(logging.WARNING)
```

Per `planning/engineering.md §2`: we acquire loggers and emit; we **never** configure handlers, levels, or call `logging.basicConfig()`. Consumers own their handler/level configuration.

## Public API

No new top-level public symbols. The observability surface IS:

1. **Logger names**: `httpware.retry`, `httpware.bulkhead`. Documented in README + engineering.md.
2. **Event names**: `retry.giving_up`, `retry.budget_refused`, `retry.streaming_refused`, `bulkhead.rejected`. Stable strings.
3. **Event attribute keys**: per the event contract below. Stable keys.

Stable means: we treat changes as breaking. Adding new keys to an event is non-breaking; removing or renaming is breaking.

## Event contract

| Event name | Logger | Level | When fired | Attributes |
|---|---|---|---|---|
| `retry.giving_up` | `httpware.retry` | `WARNING` | `max_attempts` exhausted | `attempts: int`, `method: str`, `url: str`, `last_status: int \| None`, `last_exception_type: str \| None` |
| `retry.budget_refused` | `httpware.retry` | `WARNING` | `budget.try_withdraw()` returned False | `attempts: int`, `method: str`, `url: str`, `last_status: int \| None` |
| `retry.streaming_refused` | `httpware.retry` | `WARNING` | streaming-body marker present at the **retryable-failure-path** site only (the site where Retry would otherwise have retried but for the streaming body). The 3 non-idempotent early-exit sites also `add_note` for context but do NOT emit this event — at those sites the primary reason for not retrying is method-eligibility, not streaming. | `method: str`, `url: str`, `last_exception_type: str` |
| `bulkhead.rejected` | `httpware.bulkhead` | `WARNING` | `acquire_timeout` elapsed without acquisition (raises `BulkheadFullError`) | `max_concurrent: int`, `acquire_timeout: float \| None`, `method: str`, `url: str` |

Conventions:

- **Event names** use dotted lowercase (`subsystem.event`). Matches OTel semantic-convention style.
- **Attribute keys** are flat snake_case. No nested dicts — log aggregators handle flat structure better and OTel attribute values must be scalars (or sequences of scalars).
- **`method` and `url`**: always strings. URL is `str(request.url)`; method is `request.method` (already uppercase).
- **`last_status`**: from `exc.response.status_code` when the failure was a `StatusError` subclass; `None` for network/timeout failures.
- **`last_exception_type`**: `type(exc).__qualname__` — e.g., `"NotFoundError"`, `"NetworkError"`, `"TimeoutError"`.

### Log record format

```python
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
```

The `message` is a short human sentence. The `extra=attributes` dict makes the structured fields available to log aggregators that index `extra`.

### OTel emission

```python
trace.get_current_span().add_event("retry.giving_up", attributes={...})
```

`add_event` is documented as a no-op on `NonRecordingSpan`, so we call it unconditionally inside the `if is_otel_installed:` gate.

## Optional-extras pattern

Re-introduces the `otel` extra removed in PR #24. Critical difference: now there IS code that uses it.

`pyproject.toml`:
```toml
[project.optional-dependencies]
pydantic = ["pydantic>=2.0,<3.0"]
msgspec = ["msgspec>=0.18"]
otel = ["opentelemetry-api>=1.20"]
all = ["httpware[pydantic,msgspec,otel]"]
```

Just `opentelemetry-api`, **not** `opentelemetry-sdk`. Users supply their own SDK (or use a no-op tracer in tests). Matches how `opentelemetry-instrumentation-httpx` declares its own dependency — the API is the contract; the SDK is the runtime.

`_internal/import_checker.py`:
```python
from importlib.util import find_spec

is_msgspec_installed = find_spec("msgspec") is not None
is_pydantic_installed = find_spec("pydantic") is not None
is_otel_installed = find_spec("opentelemetry") is not None  # NEW
```

`tests/test_optional_extras_isolation.py`: extend to verify `opentelemetry` doesn't end up in `sys.modules` after a fresh-subprocess `import httpware`.

`engineering.md §7` (optional-extras pattern): update the parenthetical that says *"An `otel` extra existed pre-0.4 but was removed once we noticed it was advertising functionality that didn't exist. Epic 5 will reintroduce it when the OpenTelemetry middleware actually lands."* — replace with a note that 0.6.0 reintroduced it paired with the code that uses it.

## Testing

Per `planning/engineering.md §6`:

### `tests/test_observability.py` (NEW)

Unit tests for `_emit_event`:

- `test_emit_event_logs_at_level_with_extra` — uses `caplog`; assert one log record at WARNING with the structured fields accessible via `record.attempts`, `record.method`, etc. (logging puts `extra` into the LogRecord's `__dict__`).
- `test_emit_event_skips_otel_when_extra_missing` — patch `import_checker.is_otel_installed = False`; call `_emit_event`; assert no `opentelemetry` import was triggered (`assert "opentelemetry" not in sys.modules` snapshot — or patch `trace.get_current_span` to a fail-on-call mock).
- `test_emit_event_calls_add_event_when_otel_installed` — patch `import_checker.is_otel_installed = True`; patch `opentelemetry.trace.get_current_span` to return a mock; assert `mock.add_event("event.name", attributes={...})` called once with exact args.
- `test_emit_event_works_with_no_active_span` — `is_otel_installed = True` but no tracer configured; `get_current_span()` returns a `NonRecordingSpan`; `add_event` is a documented no-op; no error.

### `tests/test_retry.py` (extend)

- `test_retry_giving_up_emits_event` — caplog at WARNING; assert one record for `httpware.retry` logger after max_attempts exhaustion; assert structured fields (`attempts == 3`, `last_status == 503`, etc.).
- `test_retry_budget_refused_emits_event` — same shape for budget refusal.
- `test_retry_streaming_refused_emits_event` — caplog after streaming-body refusal (POST + 503 + streaming content).

### `tests/test_bulkhead.py` (extend)

- `test_bulkhead_rejected_emits_event` — caplog at WARNING after `BulkheadFullError` is raised; assert attributes (`max_concurrent == 1`, `acquire_timeout == 0.02`).

### `tests/test_optional_extras_isolation.py` (extend)

- `test_import_httpware_does_not_load_opentelemetry` — fresh-subprocess `import httpware`; assert `"opentelemetry"` not in `sys.modules`.

### `tests/test_optional_extras_otel_missing.py` (NEW)

Fail-soft tests gated by patched `is_otel_installed = False`:

- `test_retry_emits_log_record_without_otel` — emit a retry.giving_up event; log record still appears in caplog; no `ImportError`.
- `test_bulkhead_emits_log_record_without_otel` — same shape.

Coverage target: **100% line coverage** (project standard).

## Documentation updates

- **README.md**: add a short "Observability" section after "Errors" describing the four events + logger names + how to enable OTel (`pip install httpware[otel]`).
- **docs/index.md**: mirror the README addition.
- **planning/engineering.md §1**: append a sentence noting Retry/Bulkhead emit structured log records + optional OTel events as of 0.6.0.
- **planning/engineering.md §2** (architecture invariants): the existing "No global logging config" rule already documents the constraint — no change needed.
- **planning/engineering.md §7** (optional-extras pattern): update per the section above (re-add the `otel` extra; revise the parenthetical).
- **planning/engineering.md §8** (roadmap): retire Epic 5 stories `5-1` and `5-4` explicitly (with rationale); mark `5-2` shipped (this slice); fold `5-5` (no separate code needed — already CI-checked).
- **planning/deferred-work.md**: no new entries needed.
- **planning/releases/0.6.0.md**: new release notes.

## Open questions deferred to implementation

- **`record.method` vs `record.method_name`**: Python's `logging.LogRecord` has a `getMessage()` method (no attribute conflict) but adding `extra={"message": ...}` would clash with the record's own `message` attribute. Verify that our chosen attribute names (`method`, `url`, `attempts`, `last_status`, `last_exception_type`, `max_concurrent`, `acquire_timeout`) don't collide with reserved LogRecord attributes. The standard reserved names: `name`, `msg`, `args`, `levelname`, `levelno`, `pathname`, `filename`, `module`, `exc_info`, `exc_text`, `stack_info`, `lineno`, `funcName`, `created`, `msecs`, `relativeCreated`, `thread`, `threadName`, `processName`, `process`, `message`. None of our attribute names clash.
- **`is_otel_installed` evaluation timing**: the flag is computed at module import time. If a user `pip install opentelemetry-api` AFTER importing httpware, the flag stays False until restart. Acceptable for v1 — matches the existing `is_pydantic_installed` / `is_msgspec_installed` pattern.

## References

- `planning/engineering.md` §1 (project intent), §2 (no global logging config), §6 (testing patterns), §7 (optional-extras), §8 (Epic 5 roadmap entries to retire/ship)
- `planning/deferred-work.md` "Closed by the 0.4.0 release" — historical record of the `otel` extra removal; this PR brings it back paired with code
- `opentelemetry-instrumentation-httpx` (https://github.com/open-telemetry/opentelemetry-python-contrib/tree/main/instrumentation/opentelemetry-instrumentation-httpx) — the existing transport-level instrumentation we DON'T duplicate
- OTel semantic conventions for events: https://opentelemetry.io/docs/specs/semconv/general/events/

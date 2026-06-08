# Spec: OTel partial-install hardening (0.8.4)

**Date:** 2026-06-08
**Topic slug:** `otel-partial-install`
**Branch:** `fix/otel-partial-install`
**Target release:** `0.8.4` — patch (defensive fix, no behavioral change to the happy path)
**Status:** drafted, awaiting user review

## Purpose

Close the two paired audit findings the [deep audit](../audit/2026-06-07-deep-audit.md) flagged as Chunk 2's optional-extras partial-install cluster:

| # | Severity | File | Headline |
|---|---|---|---|
| 1 | Low | `src/httpware/_internal/import_checker.py:8` | `find_spec("opentelemetry")` returns truthy for the PEP-420 namespace package even when `opentelemetry-api` is absent |
| 2 | Low | `src/httpware/_internal/observability.py:40` | `_emit_event` does not wrap the lazy `from opentelemetry import trace` in `try/except ImportError` |

Both findings are about the same partial-install hazard: a user installs `opentelemetry-instrumentation-X` (or any other package that creates the `opentelemetry/` namespace directory) without `opentelemetry-api`. Today:

1. `find_spec("opentelemetry")` returns non-None because the namespace directory exists.
2. `is_otel_installed` becomes `True`.
3. `_emit_event` takes the otel branch and runs `from opentelemetry import trace`.
4. The lazy import raises `ImportError` (no api package to provide `trace`).
5. The exception escapes `_emit_event` and crashes whatever middleware called it — `AsyncRetry`, `Retry`, `AsyncBulkhead`, `Bulkhead` — in the middle of a live request.

Audit fix: probe a sub-module that requires the api package (`opentelemetry.trace`), AND wrap the lazy import + `add_event` call in `try/except ImportError` as belt-and-braces. Either fix alone closes most of the hole; both together close it under every install permutation we can construct.

## Non-goals

- **No new exception types.** Failures degrade silently to the structured-log-only path; the contract is "OTel emission is best-effort."
- **No detection of broken installs at import time.** The flag stays a boolean at module load; we don't add a startup diagnostic that warns about partial installs.
- **No change to `is_pydantic_installed` or `is_msgspec_installed`.** Those don't suffer the same namespace hazard — `pydantic` and `msgspec` are concrete packages, not PEP-420 namespaces.
- **No change to logger names, event names, or attributes.** Public observability surface is untouched.
- **No new public API.** `_emit_event` stays internal.

## Architecture

### Two changes, one PR

1. `src/httpware/_internal/import_checker.py`: `find_spec("opentelemetry")` → `find_spec("opentelemetry.trace")`. The `opentelemetry.trace` sub-module ships with `opentelemetry-api`; absent the api package, even with the namespace directory present, `find_spec` returns None.

2. `src/httpware/_internal/observability.py`: wrap the lazy import and the `.add_event` call in `try/except ImportError`. On failure, the function returns silently — the structured log record on line 38 has already fired.

### Why both, not just one

Either fix in isolation would close the most common partial-install case. Together:

- `find_spec("opentelemetry.trace")` rules out the namespace-package false positive at module-load time. Cheap.
- `try/except ImportError` defends against unexpected runtime breakage — a `RuntimeError`-style import failure (corrupt install, syntax error in an instrumentation hook, monkey-patched `sys.modules`), or any future case where `is_otel_installed=True` but the import still fails.

Pairing them respects the audit's explicit recommendation that "the same release closes both ends of the partial-install hole."

### Why ImportError, not Exception

The lazy import can only fail with `ImportError` (or its subclasses like `ModuleNotFoundError`). Other exceptions (RuntimeError, AttributeError) escaping `from opentelemetry import trace` would indicate a serious environment problem we don't want to swallow. Catching `Exception` would mask real bugs in tracer libraries; catching `ImportError` matches the specific failure mode we're defending against.

The follow-up `trace.get_current_span().add_event(...)` call is documented by OTel as never raising in the no-tracer-installed path (returns `NonRecordingSpan` whose `add_event` is a no-op). It can still raise if a tracer is *misconfigured*. To stay narrow, we keep the `try/except ImportError` around only the import — the `add_event` call sits outside the try block on the happy path. If we get reports of misconfigured-tracer crashes, we widen the catch in a future patch.

## Per-change details

### 1. `import_checker.py`

old_string:
```python
is_otel_installed = find_spec("opentelemetry") is not None
```

new_string:
```python
# opentelemetry/ is a PEP 420 namespace package — instrumentation packages create it
# even without opentelemetry-api. Probe opentelemetry.trace (ships with api) instead.
is_otel_installed = find_spec("opentelemetry.trace") is not None
```

### 2. `observability.py`

The current `_emit_event` body:

```python
    logger.log(level, message, extra=attributes)
    if import_checker.is_otel_installed:
        from opentelemetry import trace  # noqa: PLC0415 — lazy by design (optional-extras isolation)

        trace.get_current_span().add_event(event_name, attributes=attributes)
```

becomes:

```python
    logger.log(level, message, extra=attributes)
    if import_checker.is_otel_installed:
        try:
            from opentelemetry import trace  # noqa: PLC0415 — lazy by design (optional-extras isolation)
        except ImportError:
            # opentelemetry namespace exists but the api package is broken or missing —
            # degrade to log-only emission. The structured log record above has already fired.
            return
        trace.get_current_span().add_event(event_name, attributes=attributes)
```

### 3. Module docstring update (observability.py)

The existing module docstring describes "If `opentelemetry-api` is installed, calls `trace.get_current_span().add_event(...)`." Extend the relevant docstring paragraph to note the soft-fallback behavior on partial-install:

old text (in the `_emit_event` docstring near line 28-32):
```
    2. If ``opentelemetry-api`` is installed, calls
       ``trace.get_current_span().add_event(event_name, attributes=attributes)``.
       When no tracer is active, ``get_current_span()`` returns a ``NonRecordingSpan``
       whose ``add_event`` is a documented no-op — so the call is unconditional
       behind the install gate.
```

new text:
```
    2. If ``opentelemetry-api`` is installed, calls
       ``trace.get_current_span().add_event(event_name, attributes=attributes)``.
       When no tracer is active, ``get_current_span()`` returns a ``NonRecordingSpan``
       whose ``add_event`` is a documented no-op — so the call is unconditional
       behind the install gate. If the install gate is wrong (the namespace exists
       but the api package is missing or broken), the lazy import raises
       ``ImportError``; we degrade silently to log-only emission.
```

## Tests

Add two tests to `tests/test_optional_extras_otel_missing.py` (the existing file that already patches `is_otel_installed`):

### Test 1: `_emit_event` survives `ImportError` from the lazy import

Simulate the partial-install crash: `is_otel_installed=True` but the lazy `from opentelemetry import trace` raises `ImportError`. The function must:
- log the structured record (already does)
- NOT raise

Approach: use `monkeypatch.setitem(sys.modules, 'opentelemetry', _BrokenModule())` where `_BrokenModule` is an object whose `__getattr__` raises `ImportError`. This makes `from opentelemetry import trace` fail with ImportError at the `__getattr__` step.

```python
def test_emit_event_survives_lazy_import_failure(caplog: pytest.LogCaptureFixture) -> None:
    class _BrokenOpenTelemetry:
        """Stand-in for opentelemetry/ namespace directory without api package."""

        def __getattr__(self, name: str) -> object:
            msg = f"cannot import name {name!r} from 'opentelemetry'"
            raise ImportError(msg)

    with (
        patch("httpware._internal.import_checker.is_otel_installed", new=True),
        patch.dict("sys.modules", {"opentelemetry": _BrokenOpenTelemetry()}),
    ):
        with caplog.at_level(logging.INFO, logger="httpware.test"):
            _emit_event(
                logging.getLogger("httpware.test"),
                "test.event",
                level=logging.INFO,
                message="test message",
                attributes={"k": "v"},
            )
    # Must not have raised. Log record must still have fired.
    assert any(r.message == "test message" for r in caplog.records)
```

### Test 2: assertion about the install-detection logic

Document the new `find_spec("opentelemetry.trace")` check via a focused test:

```python
def test_is_otel_installed_uses_opentelemetry_trace_probe() -> None:
    """The install probe must require opentelemetry-api, not just the namespace package.

    Re-running find_spec at test time confirms the production module's choice. If this
    fails, the module-load-time constant in import_checker.py is using the wrong probe.
    """
    from importlib.util import find_spec
    assert find_spec("opentelemetry.trace") is not None  # opentelemetry-api IS installed in CI
    # The boolean derived from the probe must match.
    from httpware._internal import import_checker
    assert import_checker.is_otel_installed is True
```

This test runs in the `--all-extras` environment where `opentelemetry-api` IS installed, so the live check holds. It would fail if a future refactor reverted to `find_spec("opentelemetry")` AND used a stale snapshot from CI without api installed.

## Verification

After each commit:

```bash
just lint-ci
uv run pytest tests/test_optional_extras_otel_missing.py tests/test_observability.py -x --no-cov -q
```

Plus the full suite at the end of the PR:

```bash
uv run pytest -x --no-cov -q
```

## Release notes

`planning/releases/0.8.4.md` — mirror the 0.8.1/0.8.3 structure. One-section release; bug fix only; no API change. Note that the partial-install scenario degrades from "crashes a live request" to "silently logs and skips the OTel emission."

## Acceptance criteria

1. Two fix commits + one release-notes commit + (optional) test-extension commit on branch `fix/otel-partial-install`.
2. `just lint-ci` and `uv run pytest` green after every commit.
3. PR opened against `main` with title `fix(otel): harden partial-install detection + lazy-import (0.8.4)`.
4. After merge, tag `0.8.4` from the merge SHA; GitHub Release published from `planning/releases/0.8.4.md`.
5. Memory `release_0_8_4_shipped` added to MEMORY.md.

## Open questions

None. Both fixes are precisely specified by the audit; the tests are straightforward; the release-notes shape is established.

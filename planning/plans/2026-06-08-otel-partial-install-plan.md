# OTel Partial-Install Hardening Implementation Plan (0.8.4)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land 3 commits on branch `fix/otel-partial-install` that close the 2 OTel partial-install audit findings, draft release notes for 0.8.4, and open a PR.

**Architecture:** Two surgical defensive fixes: (1) `import_checker.is_otel_installed` probes `opentelemetry.trace` (a sub-module that ships with `opentelemetry-api`) instead of the bare `opentelemetry` namespace; (2) `_emit_event` wraps the lazy `from opentelemetry import trace` in `try/except ImportError` so a partial install degrades to log-only emission instead of crashing a live request. Tests exercise the broken-install crash path via `sys.modules` monkey-patching.

**Tech Stack:** Python 3.11+, `importlib.util.find_spec`, `pytest`. No new dependencies. No public API change.

---

## Spec reference

`planning/specs/2026-06-08-otel-partial-install-design.md`. Decisions locked there (not re-debated): probe target is `opentelemetry.trace`; the try/except catches `ImportError` only (not bare `Exception`); the `add_event` call stays outside the try block; module docstring grows one sentence about the soft-fallback behavior.

## File structure

```
src/httpware/_internal/import_checker.py     # Task 1 — find_spec target change + comment
src/httpware/_internal/observability.py      # Task 2 — try/except wrap + docstring sentence
tests/test_optional_extras_otel_missing.py   # Tasks 1, 2 — new tests
planning/releases/0.8.4.md                   # Task 3 — new file
```

No new source files. No file deletions. Branch is already created (`fix/otel-partial-install`); spec already committed at `a9858ea`.

## A note on testability

The `is_otel_installed` flag is computed at module load time. A unit test can confirm the LIVE probe matches expectations in the CI environment (where `opentelemetry-api` IS installed via `--all-extras`), but cannot directly exercise the "namespace-package false positive" without reinstalling packages. We do the next best thing: a test that documents the probe target, plus a runtime test that simulates `from opentelemetry import trace` failing via a broken `sys.modules['opentelemetry']` stand-in — this exercises the try/except path end-to-end without touching the install.

---

## Task 1: `find_spec("opentelemetry.trace")` probe + verification test

**Files:**
- Modify: `src/httpware/_internal/import_checker.py`
- Modify: `tests/test_optional_extras_otel_missing.py`

Closes audit Low finding (`import_checker.py:8`).

- [ ] **Step 1: Read current state**

```bash
cat src/httpware/_internal/import_checker.py
```

Confirm: the file has exactly 3 `is_*_installed` constants at module top; the `is_otel_installed` line currently reads `is_otel_installed = find_spec("opentelemetry") is not None`.

- [ ] **Step 2: Write the failing/regression-guard test FIRST**

Append to `tests/test_optional_extras_otel_missing.py`:

```python
def test_is_otel_installed_uses_opentelemetry_trace_probe() -> None:
    """The install probe must require opentelemetry-api, not just the namespace package.

    `opentelemetry` is a PEP 420 namespace — instrumentation packages create the
    directory even when `opentelemetry-api` is absent. Probing the bare namespace
    would return a non-None spec and `is_otel_installed` would become True, then
    the lazy import in `_emit_event` would raise ImportError at runtime.

    Probing `opentelemetry.trace` (which ships with `opentelemetry-api`) closes
    the gap. This test pins that contract: production must probe the trace
    sub-module, not the bare namespace.
    """
    from importlib.util import find_spec

    # In CI (opentelemetry-api IS installed), both probes return non-None.
    # The asserts below confirm the live state and document the chosen probe.
    assert find_spec("opentelemetry.trace") is not None
    from httpware._internal import import_checker
    assert import_checker.is_otel_installed is True

    # The structural assertion: the module-load-time constant must be derived
    # from the trace-sub-module probe. Read the source to enforce this.
    source = (
        __import__("inspect")
        .getsource(import_checker)
    )
    assert "find_spec(\"opentelemetry.trace\")" in source, (
        "import_checker must probe opentelemetry.trace (PEP 420 namespace hazard); "
        "see planning/audit/2026-06-07-deep-audit.md (Low finding on import_checker.py:8)."
    )
```

This test relies on the source check to guard against a future revert to `find_spec("opentelemetry")` — the live `find_spec` calls return non-None either way in CI, so source-level pinning is the regression guard.

- [ ] **Step 3: Run the test — confirm it FAILS against current production**

```bash
uv run pytest tests/test_optional_extras_otel_missing.py::test_is_otel_installed_uses_opentelemetry_trace_probe -x --no-cov -q
```

Expected: FAIL on the source-check assertion (production still has `find_spec("opentelemetry")`, not `find_spec("opentelemetry.trace")`).

- [ ] **Step 4: Fix production — change the find_spec target**

Edit `src/httpware/_internal/import_checker.py`. Use Edit tool with these exact strings:

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

- [ ] **Step 5: Run test — confirm it PASSES**

```bash
uv run pytest tests/test_optional_extras_otel_missing.py::test_is_otel_installed_uses_opentelemetry_trace_probe -x --no-cov -q
```

Expected: PASS.

- [ ] **Step 6: Run the full file**

```bash
uv run pytest tests/test_optional_extras_otel_missing.py tests/test_observability.py tests/test_optional_extras_isolation.py tests/test_optional_extras_pydantic_missing.py -x --no-cov -q
```

Expected: all pass. (Other extras tests use the same module-load-time `is_*_installed` flags; the change is isolated to OTel detection.)

- [ ] **Step 7: Lint**

```bash
just lint-ci
```

Expected: green.

- [ ] **Step 8: Commit**

```bash
git add src/httpware/_internal/import_checker.py tests/test_optional_extras_otel_missing.py
git commit -m "$(cat <<'EOF'
fix(import-checker): probe opentelemetry.trace, not the bare namespace

`opentelemetry` is a PEP 420 native namespace package — any
`opentelemetry-instrumentation-*` package creates the directory even when
`opentelemetry-api` is absent. `find_spec("opentelemetry")` then returns
non-None and `is_otel_installed` becomes True; the lazy
`from opentelemetry import trace` in `_emit_event` subsequently raises
ImportError mid-request.

Probe `opentelemetry.trace` instead — it ships with `opentelemetry-api`
and is absent when the api package is. The check is now cheap and
correct under every install permutation we can construct.

The new test source-checks the probe target so a future revert to the
bare-namespace probe trips the regression guard, even though the live
`find_spec` calls return non-None either way under `--all-extras`.

Closes audit Low finding (import_checker.py:8) from
planning/audit/2026-06-07-deep-audit.md.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Wrap the lazy OTel import in `try/except ImportError`

**Files:**
- Modify: `src/httpware/_internal/observability.py`
- Modify: `tests/test_optional_extras_otel_missing.py`

Closes audit Low finding (`observability.py:40`).

- [ ] **Step 1: Read current state**

```bash
cat src/httpware/_internal/observability.py
```

Confirm: `_emit_event` body (lines 38-42) is:

```python
    logger.log(level, message, extra=attributes)
    if import_checker.is_otel_installed:
        from opentelemetry import trace  # noqa: PLC0415 — lazy by design (optional-extras isolation)

        trace.get_current_span().add_event(event_name, attributes=attributes)
```

- [ ] **Step 2: Write the failing test FIRST**

Append to `tests/test_optional_extras_otel_missing.py`:

```python
def test_emit_event_survives_lazy_import_failure(caplog: pytest.LogCaptureFixture) -> None:
    """When is_otel_installed=True but `from opentelemetry import trace` raises ImportError,
    _emit_event must degrade to log-only emission rather than crash.

    Simulates the partial-install case: opentelemetry/ namespace directory exists (created by
    some instrumentation package) but opentelemetry-api is missing or broken, so importing
    `trace` from it fails.
    """
    import sys

    class _BrokenOpenTelemetry:
        """Stand-in for opentelemetry/ namespace directory without working api."""

        def __getattr__(self, name: str) -> object:
            msg = f"cannot import name {name!r} from 'opentelemetry'"
            raise ImportError(msg)

    # Save and replace the real opentelemetry module for the duration of the test.
    saved = sys.modules.pop("opentelemetry", None)
    sys.modules["opentelemetry"] = _BrokenOpenTelemetry()  # type: ignore[assignment]
    try:
        with (
            patch("httpware._internal.import_checker.is_otel_installed", True),
            caplog.at_level(logging.WARNING, logger="httpware.test.otel_missing"),
        ):
            _emit_event(
                _TEST_LOGGER,
                "test.event",
                level=logging.WARNING,
                message="survives broken otel",
                attributes={"k": "v"},
            )
    finally:
        if saved is not None:
            sys.modules["opentelemetry"] = saved
        else:
            sys.modules.pop("opentelemetry", None)

    # The structured log record still fired despite the OTel branch failing.
    assert any(r.message == "survives broken otel" for r in caplog.records)
```

The `_TEST_LOGGER` constant already exists in this file from Step 1's Task. `patch` and `pytest` are already imported.

- [ ] **Step 3: Run the test — confirm it FAILS**

```bash
uv run pytest tests/test_optional_extras_otel_missing.py::test_emit_event_survives_lazy_import_failure -x --no-cov -q
```

Expected: FAIL with `ImportError: cannot import name 'trace' from 'opentelemetry'` propagating out of `_emit_event`.

- [ ] **Step 4: Fix production — wrap the lazy import**

Edit `src/httpware/_internal/observability.py`. Use Edit tool:

old_string:
```python
    logger.log(level, message, extra=attributes)
    if import_checker.is_otel_installed:
        from opentelemetry import trace  # noqa: PLC0415 — lazy by design (optional-extras isolation)

        trace.get_current_span().add_event(event_name, attributes=attributes)
```

new_string:
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

- [ ] **Step 5: Update the `_emit_event` docstring**

In the same file (`src/httpware/_internal/observability.py`), update the second numbered point of the docstring (around lines 28-32). Use Edit tool:

old_string:
```python
    2. If ``opentelemetry-api`` is installed, calls
       ``trace.get_current_span().add_event(event_name, attributes=attributes)``.
       When no tracer is active, ``get_current_span()`` returns a ``NonRecordingSpan``
       whose ``add_event`` is a documented no-op — so the call is unconditional
       behind the install gate.
```

new_string:
```python
    2. If ``opentelemetry-api`` is installed, calls
       ``trace.get_current_span().add_event(event_name, attributes=attributes)``.
       When no tracer is active, ``get_current_span()`` returns a ``NonRecordingSpan``
       whose ``add_event`` is a documented no-op — so the call is unconditional
       behind the install gate. If the install gate is wrong (the namespace exists
       but the api package is missing or broken), the lazy import raises
       ``ImportError``; we degrade silently to log-only emission.
```

- [ ] **Step 6: Run the test — confirm it PASSES**

```bash
uv run pytest tests/test_optional_extras_otel_missing.py::test_emit_event_survives_lazy_import_failure -x --no-cov -q
```

Expected: PASS.

- [ ] **Step 7: Run the full OTel + observability test suite**

```bash
uv run pytest tests/test_optional_extras_otel_missing.py tests/test_observability.py tests/test_retry.py tests/test_retry_sync.py tests/test_bulkhead.py tests/test_bulkhead_sync.py -x --no-cov -q
```

Expected: all pass. (The retry + bulkhead tests exercise `_emit_event` indirectly through middleware; a regression in the try/except would surface here.)

- [ ] **Step 8: Lint**

```bash
just lint-ci
```

Expected: green.

- [ ] **Step 9: Commit**

```bash
git add src/httpware/_internal/observability.py tests/test_optional_extras_otel_missing.py
git commit -m "$(cat <<'EOF'
fix(observability): wrap lazy OTel import in try/except ImportError

_emit_event gated the OTel path on `if import_checker.is_otel_installed` but
ran `from opentelemetry import trace` unguarded. If is_otel_installed was
True yet the import failed (PEP 420 namespace false-positive in 0.8.3 and
earlier; or any future partial install / broken api package), the
ImportError escaped _emit_event and crashed the middleware calling it
(AsyncRetry, Retry, AsyncBulkhead, Bulkhead) mid-request.

Wrap the lazy import in `try/except ImportError`. On failure, return — the
structured log record on the line above has already fired, so emission
degrades to log-only.

Catch ImportError specifically, not bare Exception: misconfigured-tracer
crashes (RuntimeError, AttributeError) should still surface; only the
install-gate-is-wrong case is in scope.

_emit_event's docstring grows one sentence describing the soft-fallback.

Closes audit Low finding (observability.py:40) from
planning/audit/2026-06-07-deep-audit.md.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Draft 0.8.4 release notes + open PR

**Files:**
- Create: `planning/releases/0.8.4.md`

- [ ] **Step 1: Read the 0.8.1 release-notes file to mirror its shape**

```bash
cat planning/releases/0.8.1.md
```

(0.8.3 had three behavioral changes so its release notes are heavier — 0.8.4 is a single defensive fix and should match the 0.8.1 shape more closely: TL;DR + "The gap" + "The fix" + Upgrade.)

- [ ] **Step 2: Write `planning/releases/0.8.4.md`**

Create with this exact content:

```markdown
# httpware 0.8.4 — OTel partial-install no longer crashes a live request

**Patch release. Defensive fix. No API change.** Closes the two paired audit findings tracking the OpenTelemetry partial-install hazard.

## The gap

`httpware`'s observability layer treats `opentelemetry-api` as an optional extra. It detects whether the extra is installed via `find_spec("opentelemetry")` at module load time, then takes the OTel branch in `_emit_event` only if the flag is True.

Two flaws in that gate let a partial install crash a live request:

1. `opentelemetry` is a PEP 420 native namespace package. Any `opentelemetry-instrumentation-*` package creates the `opentelemetry/` directory, so `find_spec("opentelemetry")` returns a non-None spec even when `opentelemetry-api` is absent.
2. The lazy `from opentelemetry import trace` inside `_emit_event` was not wrapped in `try/except`. With the false-positive flag from (1), the import then raised `ImportError` mid-emit, crashing the middleware calling `_emit_event` — `AsyncRetry`, `Retry`, `AsyncBulkhead`, `Bulkhead` — in the middle of a live HTTP request.

The audit's [chunk-2 finding](../audit/2026-06-07-deep-audit.md) named both halves of the hole; this release closes both.

## The fix

Two changes:

- `import_checker.is_otel_installed` now probes `find_spec("opentelemetry.trace")`. The `opentelemetry.trace` sub-module ships with `opentelemetry-api`, so the flag is True only when the api package is actually importable.
- `_emit_event` wraps the lazy import in `try/except ImportError`. On failure (corrupt install, future namespace surprise, monkey-patched `sys.modules`), emission degrades to log-only — the structured log record fires unconditionally; the OTel `add_event` call is skipped.

We catch `ImportError` specifically, not bare `Exception`. Misconfigured-tracer crashes (RuntimeError, AttributeError out of `trace.get_current_span().add_event(...)`) still surface; only the install-gate-is-wrong case is in scope.

## Upgrade

```bash
uv add httpware==0.8.4
# or
pip install -U 'httpware==0.8.4'
```

No import changes. No API surface changes. No behavior change on the happy path (api package installed and importable). The only observable change is "no longer crashes" on partial installs.
```

- [ ] **Step 3: Lint**

```bash
just lint-ci
```

Expected: green. eof-fixer may add a trailing newline.

- [ ] **Step 4: Commit**

```bash
git add planning/releases/0.8.4.md
git commit -m "$(cat <<'EOF'
docs(release): draft 0.8.4 notes — OTel partial-install hardening

Two paired defensive fixes (find_spec target + try/except wrap) close
the chunk-2 partial-install audit findings. No API change; the only
observable behavior change is "no longer crashes" on partial installs.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 5: Push the branch + open the PR**

```bash
git push -u origin fix/otel-partial-install
```

```bash
gh pr create --base main --head fix/otel-partial-install --title "fix(otel): harden partial-install detection + lazy-import (0.8.4)" --body "$(cat <<'EOF'
## Summary

Closes 2 of the remaining audit findings — the OpenTelemetry partial-install hazard from chunk 2. See [`planning/specs/2026-06-08-otel-partial-install-design.md`](planning/specs/2026-06-08-otel-partial-install-design.md) for the design and [`planning/releases/0.8.4.md`](planning/releases/0.8.4.md) for the user-facing release notes.

## The hazard

- `find_spec("opentelemetry")` returns truthy because `opentelemetry/` is a PEP 420 namespace package — created by any `opentelemetry-instrumentation-*` install.
- `is_otel_installed` becomes True even when `opentelemetry-api` is absent.
- The lazy `from opentelemetry import trace` in `_emit_event` was unguarded — raised ImportError mid-request, crashing the middleware.

## The fixes (paired per the audit's recommendation)

- `import_checker.is_otel_installed = find_spec("opentelemetry.trace") is not None` — closes the false-positive at detection time.
- `_emit_event` wraps the lazy import in `try/except ImportError` — closes the runtime crash, degrades to log-only emission.

## Audit findings closed

| Severity | File:line | Closed by |
|---|---|---|
| Low | \`_internal/import_checker.py:8\` | find_spec("opentelemetry.trace") probe |
| Low | \`_internal/observability.py:40\` | try/except ImportError wrap |

## Test plan

- [x] New test pins the probe target via source-level assertion (\`find_spec("opentelemetry.trace")\` must appear in import_checker.py).
- [x] New test simulates the partial-install crash via \`sys.modules['opentelemetry'] = _BrokenOpenTelemetry()\` and verifies \`_emit_event\` returns without raising while still emitting the structured log record.
- [x] \`just lint-ci\` and full test suite green after each commit.

## Release

Tag \`0.8.4\` from the merge SHA after this PR lands.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Verify the PR URL is returned.

- [ ] **Step 6: Final verification**

```bash
git log --oneline -5
gh pr view --json url,state,title
```

Expected: 3 commits on top of the spec (`a9858ea`) — `import_checker` fix, `observability` fix, release notes. PR open against main.

Report the PR URL.

---

## Self-review notes

- **Spec coverage:** Spec finding #1 = T1 (import_checker probe target). Spec finding #2 = T2 (try/except wrap + docstring extension). Spec tests section = T1 + T2 test steps. Spec release notes section = T3. PR opening = T3 Step 5.
- **Placeholder scan:** All code blocks are complete with verbatim old_string / new_string. Test bodies are complete. Commit messages are filled in. No "TBD" / "similar to".
- **Type/name consistency:** `_TEST_LOGGER` is reused from the existing file in Task 2 (the test file already defines it). The `_BrokenOpenTelemetry` class is local to one test. `find_spec("opentelemetry.trace")` is the exact same string in source and test source-check.
- **TDD ordering:** T1 and T2 each follow red-green-commit. T1's red is a source-level assertion (the live `find_spec` calls pass either way under `--all-extras`, so source-pinning is the regression guard). T2's red is a real runtime ImportError out of `_emit_event`.

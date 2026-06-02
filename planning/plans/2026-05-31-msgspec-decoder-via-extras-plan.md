# msgspec decoder via extras Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship Story 1-6: a `MsgspecDecoder` adapter at `src/httpware/decoders/msgspec.py` backed by `msgspec.json.decode`, gated behind the `[msgspec]` extra via a new `find_spec`-based `import_checker` module borrowed from lite-bootstrap.

**Architecture:** Two new source modules (an `import_checker` and the decoder), two new test files (decoder behavior + subprocess-based import isolation), and one CHANGELOG entry. No package-root re-export — the decoder honors seam #5 by requiring the explicit `from httpware.decoders.msgspec import MsgspecDecoder` path.

**Tech Stack:** Python 3.11 floor; `msgspec>=0.18` via the `[msgspec]` extra already declared in `pyproject.toml`; `importlib.util.find_spec` for extra detection.

**Branch:** `story/1-6-msgspec-decoder-via-extras` (already created; spec commit `b12a989` is on it).

**Spec:** `planning/specs/2026-05-31-msgspec-decoder-via-extras-design.md`.

---

## File Structure

**New files:**
- `src/httpware/_internal/import_checker.py` — `find_spec`-based detection flags. Initial content: `is_msgspec_installed`.
- `src/httpware/decoders/msgspec.py` — `MsgspecDecoder` class plus `MISSING_DEPENDENCY_MESSAGE` constant.
- `tests/test_decoders_msgspec.py` — 8 behavioral tests for the decoder.
- `tests/test_optional_extras_isolation.py` — subprocess-based test that `import httpware` does not load `msgspec`.

**Modified files:**
- `CHANGELOG.md` — append Story 1.6 bullet under `[Unreleased]` / `### Added`.

**Files NOT touched:**
- `pyproject.toml` — `msgspec = ["msgspec>=0.18"]` is already declared from Story 1-1.
- `src/httpware/__init__.py` — no package-root re-export (seam contract).
- `src/httpware/decoders/__init__.py` — `ResponseDecoder` Protocol stays as-is.

---

## Task 1: `_internal/import_checker.py`

Create the find_spec-based detection module. One line of state, no behavior to TDD — but include a quick sanity test that the flag is True in the test environment (where `msgspec` is installed).

**Files:**
- Create: `src/httpware/_internal/import_checker.py`

- [ ] **Step 1: Create the module**

Create `src/httpware/_internal/import_checker.py`:

```python
"""Detect optional extras without importing them. Used by adapter modules to gate hard imports."""

from importlib.util import find_spec


is_msgspec_installed = find_spec("msgspec") is not None
```

No `__all__` (project convention — see memory `user-no-all-in-submodules`).

- [ ] **Step 2: Sanity-check the flag in a Python REPL**

Run: `uv run python -c "from httpware._internal import import_checker; print(import_checker.is_msgspec_installed)"`
Expected: `True` (msgspec is installed in the dev environment via `--all-extras`).

- [ ] **Step 3: Lint and ty**

Run: `uv run ruff check src/httpware/_internal/import_checker.py`
Run: `uv run ty check src/httpware/_internal/import_checker.py`
Expected: both clean.

- [ ] **Step 4: Commit**

```bash
git add src/httpware/_internal/import_checker.py
git commit -m "$(cat <<'EOF'
feat(story-1.6): _internal/import_checker.py for find_spec-based extra detection

Adds is_msgspec_installed flag computed once at module import time via
importlib.util.find_spec. No actual import of msgspec happens — only
the importlib check. Future opt-in extras (otel in Story 5-4, etc.)
extend this module with their own flags.

Pattern adapted from modern-python/lite-bootstrap.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `MsgspecDecoder` + 8 decoder tests

TDD the decoder. Start with the protocol-satisfaction test, then the happy-path decode, then add error and construction-failure tests.

**Files:**
- Create: `src/httpware/decoders/msgspec.py`
- Create: `tests/test_decoders_msgspec.py`

- [ ] **Step 1: Add the first failing test (protocol satisfaction)**

Create `tests/test_decoders_msgspec.py`:

```python
"""Unit tests for httpware.decoders.msgspec.MsgspecDecoder."""

import msgspec
import pytest
from pydantic import BaseModel

from httpware._internal import import_checker
from httpware.decoders import ResponseDecoder
from httpware.decoders.msgspec import MISSING_DEPENDENCY_MESSAGE, MsgspecDecoder


class _Item(msgspec.Struct):
    name: str
    qty: int


class _ItemModel(BaseModel):
    name: str
    qty: int


def test_decoder_satisfies_response_decoder_protocol() -> None:
    assert isinstance(MsgspecDecoder(), ResponseDecoder)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_decoders_msgspec.py::test_decoder_satisfies_response_decoder_protocol -v`
Expected: `ModuleNotFoundError: No module named 'httpware.decoders.msgspec'`.

- [ ] **Step 3: Implement the decoder module**

Create `src/httpware/decoders/msgspec.py`:

```python
"""MsgspecDecoder — opt-in ResponseDecoder backed by msgspec.json.decode."""

from typing import TypeVar

from httpware._internal import import_checker


if import_checker.is_msgspec_installed:
    import msgspec


MISSING_DEPENDENCY_MESSAGE = (
    "MsgspecDecoder requires the 'msgspec' extra. "
    "Install with: pip install httpware[msgspec]"
)

T = TypeVar("T")


class MsgspecDecoder:
    """Decode raw response bytes via `msgspec.json.decode(content, type=model)`.

    Requires the `msgspec` extra: `pip install httpware[msgspec]`. Importing
    this module without the extra works (the `msgspec` import is guarded by a
    `find_spec` check), but instantiating the decoder raises `ImportError` with
    the install hint.
    """

    def __init__(self) -> None:
        if not import_checker.is_msgspec_installed:
            raise ImportError(MISSING_DEPENDENCY_MESSAGE)

    def decode(self, content: bytes, model: type[T]) -> T:
        """Validate `content` as JSON against `model` in a single parse pass."""
        return msgspec.json.decode(content, type=model)
```

No `__all__`.

If `ty check` rejects the `msgspec.json.decode(...)` line because `msgspec` is imported inside a runtime `if` block, add `# ty: ignore[unresolved-reference]` to the `return` line with a brief comment pointing at the `import_checker` guard. Verify via Step 6 first.

- [ ] **Step 4: Run the protocol test to verify it passes**

Run: `uv run pytest tests/test_decoders_msgspec.py::test_decoder_satisfies_response_decoder_protocol -v`
Expected: PASS.

- [ ] **Step 5: Add the remaining 7 tests**

Append to `tests/test_decoders_msgspec.py`:

```python
def test_decode_into_msgspec_struct() -> None:
    result = MsgspecDecoder().decode(b'{"name":"x","qty":1}', _Item)
    assert result == _Item(name="x", qty=1)


def test_decode_into_pydantic_model() -> None:
    result = MsgspecDecoder().decode(b'{"name":"y","qty":2}', _ItemModel)
    assert result == _ItemModel(name="y", qty=2)


def test_decode_into_builtin_type() -> None:
    result = MsgspecDecoder().decode(b"42", int)
    assert result == 42  # noqa: PLR2004


def test_decode_into_list_of_struct() -> None:
    result = MsgspecDecoder().decode(b'[{"name":"a","qty":1}]', list[_Item])
    assert result == [_Item(name="a", qty=1)]


def test_decode_validation_error_propagates() -> None:
    with pytest.raises(msgspec.ValidationError):
        MsgspecDecoder().decode(b'{"name":"x","qty":"not-an-int"}', _Item)


def test_decode_json_parse_error_propagates() -> None:
    with pytest.raises(msgspec.DecodeError):
        MsgspecDecoder().decode(b"{", _Item)


def test_construction_raises_without_extra_via_monkeypatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(import_checker, "is_msgspec_installed", False)
    with pytest.raises(ImportError, match="MsgspecDecoder requires the 'msgspec' extra"):
        MsgspecDecoder()
```

- [ ] **Step 6: Run all 8 tests to verify they pass**

Run: `uv run pytest tests/test_decoders_msgspec.py -v`
Expected: 8 passed.

- [ ] **Step 7: Lint and ty**

Run: `uv run ruff check src/httpware/decoders/msgspec.py tests/test_decoders_msgspec.py`
Run: `uv run ty check src/httpware/decoders/msgspec.py`
Expected: both clean.

If ruff flags `PLR2004` (magic number) on the `42` literal beyond what `# noqa: PLR2004` already covers, add suppressions per the existing test pattern.

- [ ] **Step 8: Commit**

```bash
git add src/httpware/decoders/msgspec.py tests/test_decoders_msgspec.py
git commit -m "$(cat <<'EOF'
feat(story-1.6): MsgspecDecoder adapter behind [msgspec] extra

Adds src/httpware/decoders/msgspec.py with:
- MISSING_DEPENDENCY_MESSAGE constant (module-level, not class attribute)
- MsgspecDecoder class: __init__ raises ImportError with install hint
  if msgspec isn't installed; decode() calls msgspec.json.decode(
  content, type=model) in a single C-level parse pass.

The msgspec import is gated by import_checker.is_msgspec_installed,
so the module imports cleanly without the extra — only construction
fails. No __all__ (project convention). No caching (msgspec.json.decode
is a free function with no per-model adapter overhead).

Eight tests cover: protocol satisfaction, decode-into-Struct,
decode-into-pydantic-model, decode-into-builtin, decode-into-list,
ValidationError propagation, DecodeError propagation, and the
construction-failure path via monkeypatch.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Subprocess-based import-isolation test

Add the subprocess test that verifies `import httpware` does NOT transitively load `msgspec`. This is the test for AC4 from the archived spec ("importing httpware without msgspec installed does not import msgspec"). Because `msgspec` IS installed in the test environment, the check must run in a fresh subprocess to see a clean `sys.modules`.

**Files:**
- Create: `tests/test_optional_extras_isolation.py`

- [ ] **Step 1: Create the test file**

Create `tests/test_optional_extras_isolation.py`:

```python
"""Verify that `import httpware` does not transitively load opt-in extras."""

import subprocess
import sys


def test_importing_httpware_does_not_import_msgspec() -> None:
    """Fresh subprocess: msgspec must NOT appear in sys.modules after `import httpware`.

    msgspec IS installed in the test environment (via `--all-extras`), so this
    test runs in a subprocess with a clean interpreter to verify that nothing
    in the httpware import chain pulls msgspec in.
    """
    result = subprocess.run(  # noqa: S603
        [
            sys.executable,
            "-c",
            "import httpware; import sys; "
            "sys.exit(0 if 'msgspec' not in sys.modules else 1)",
        ],
        check=False,
        capture_output=True,
    )
    assert result.returncode == 0, (
        "msgspec was loaded transitively by `import httpware`; "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
```

The `# noqa: S603` suppresses ruff's "subprocess without shell=False explicit" warning — the call uses a list of args, not shell=True, so it's safe; the rule is overly cautious for this case. If S603 isn't flagged, drop the noqa.

- [ ] **Step 2: Run the test**

Run: `uv run pytest tests/test_optional_extras_isolation.py -v`
Expected: 1 passed.

If it fails, the subprocess output identifies what's pulling msgspec in. Likely culprit: a re-export from `src/httpware/__init__.py`. The spec explicitly forbids this.

- [ ] **Step 3: Lint**

Run: `uv run ruff check tests/test_optional_extras_isolation.py`
Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add tests/test_optional_extras_isolation.py
git commit -m "$(cat <<'EOF'
test(story-1.6): subprocess-based import-isolation guard for opt-in extras

Verifies that `import httpware` does not transitively load msgspec. msgspec
is installed in the test env (via --all-extras), so the check runs in a
fresh subprocess with a clean sys.modules. Future stories (5-4 otel) extend
this file with their own subprocess tests for each opt-in extra.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: CHANGELOG bullet

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Append the bullet**

Edit `CHANGELOG.md`. The `## [Unreleased]` / `### Added` section currently ends with the Story 2.3 bullet. Append a new bullet immediately after Story 2.3 (still before the `[Unreleased]: ...` reference link line):

```markdown
- `MsgspecDecoder` opt-in `ResponseDecoder` adapter behind the `[msgspec]` extra; `msgspec.json.decode(content, type=model)` in a single C-level parse pass. Accepts `msgspec.Struct`, pydantic `BaseModel`, and builtin types as `model`. `msgspec.ValidationError` and `msgspec.DecodeError` propagate unchanged. Module import is safe without the extra (gated by `httpware._internal.import_checker.is_msgspec_installed`); only `MsgspecDecoder()` construction raises `ImportError` with an install hint when the extra is missing. `import httpware` does NOT eagerly load `msgspec` — `MsgspecDecoder` is reachable only via `from httpware.decoders.msgspec import MsgspecDecoder` (Story 1.6).
```

- [ ] **Step 2: Commit**

```bash
git add CHANGELOG.md
git commit -m "$(cat <<'EOF'
docs(story-1.6): CHANGELOG entry for MsgspecDecoder via extras

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Verify, push, PR, merge

End-to-end sanity check, push, open PR, wait for CI, merge.

- [ ] **Step 1: Run the full test suite with coverage**

Run: `just test`
Expected: 207 passed (198 baseline post-2.3 + 8 decoder tests + 1 isolation test), 1 deselected (perf), 100% line coverage including the new `import_checker.py` and `decoders/msgspec.py`.

If coverage is below 100% on the new modules, identify the uncovered branch. The construction-failure path is exercised by the monkeypatch test; the happy path by the decode tests.

- [ ] **Step 2: Run full lint and type checks**

Run: `just lint-ci`
Expected: `eof-fixer`, `ruff format --check`, `ruff check --no-fix`, `ty check` all clean.

- [ ] **Step 3: Confirm the working tree is clean**

Run: `git status --short`
Expected: only the untracked plan file `planning/plans/2026-05-31-msgspec-decoder-via-extras-plan.md`.

- [ ] **Step 4: Review the branch diff**

Run: `git log --oneline main..HEAD`
Expected: five or six commits — spec (`docs(story-1.6): design...`), Task 1, Task 2, Task 3, Task 4.

Run: `git diff --stat main..HEAD`
Expected: changes to `CHANGELOG.md`, plus the four new files: `planning/specs/2026-05-31-msgspec-decoder-via-extras-design.md`, `src/httpware/_internal/import_checker.py`, `src/httpware/decoders/msgspec.py`, `tests/test_decoders_msgspec.py`, `tests/test_optional_extras_isolation.py`. No other source files touched.

- [ ] **Step 5: Stage and commit the plan file**

```bash
git add planning/plans/2026-05-31-msgspec-decoder-via-extras-plan.md
git commit -m "docs(story-1.6): implementation plan for MsgspecDecoder via extras

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 6: Push the branch**

Run: `git push -u origin story/1-6-msgspec-decoder-via-extras`
Expected: push succeeds; GitHub prints a "Create a pull request for ..." URL.

- [ ] **Step 7: Open the PR**

```bash
gh pr create --title "feat(story-1.6): MsgspecDecoder via the [msgspec] extra" --body "$(cat <<'EOF'
## Summary

- Adds `src/httpware/decoders/msgspec.py` with `MsgspecDecoder`, the second `ResponseDecoder` adapter. Backed by `msgspec.json.decode(content, type=model)` — single C-level parse pass, no adapter caching needed (msgspec doesn't have pydantic's `TypeAdapter` overhead).
- Adds `src/httpware/_internal/import_checker.py` with `is_msgspec_installed` (`find_spec`-based detection — does NOT import msgspec). Pattern adapted from `modern-python/lite-bootstrap`. Future opt-in extras (otel in Story 5-4, etc.) extend this module.
- Module import is safe without the extra — only `MsgspecDecoder()` construction raises `ImportError` with the install hint. Enables capability-probe code.
- No package-root re-export. Honors seam #5 ("never import an extra at package top-level"). Consumers use `from httpware.decoders.msgspec import MsgspecDecoder`.
- 8 behavioral tests + 1 subprocess-based import-isolation test (in new `tests/test_optional_extras_isolation.py`, which future opt-in extras will extend).
- 207 passing total; 100% coverage on the new modules.

Out of scope (subsequent stories): `AsyncClient` wiring (Story 1-7), `RecordedTransport` (Story 1-8), follow-up cleanup of legacy `__all__` exports in existing submodules.

Spec + plan: `planning/specs/2026-05-31-msgspec-decoder-via-extras-design.md`, `planning/plans/2026-05-31-msgspec-decoder-via-extras-plan.md`.

## Test plan

- [x] `just test` — 207 passed, 1 deselected, 100% line coverage including the new modules.
- [x] `just lint-ci` clean.
- [x] `tests/test_no_httpx2_leakage.py` still passes.
- [x] `tests/test_optional_extras_isolation.py::test_importing_httpware_does_not_import_msgspec` passes — subprocess verifies `import httpware` does not load `msgspec`.
- [ ] CI green on all matrix entries (3.11/3.12/3.13/3.14 + lint).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 8: Wait for CI**

Run: `gh pr checks <PR_NUMBER>` (the number is printed by `gh pr create`).
Expected: all five jobs (`lint`, `pytest (3.11)`, `pytest (3.12)`, `pytest (3.13)`, `pytest (3.14)`) green.

If `pytest (3.14)` fails on `codecov/codecov-action@v4.0.1` with EPIPE (transient pattern seen on this repo), re-run with `gh run rerun <RUN_ID> --failed`.

- [ ] **Step 9: Merge**

Once CI is green:

Run: `gh pr merge <PR_NUMBER> --merge --delete-branch`
Run: `git checkout main && git pull --ff-only && git log --oneline -3`

Story 1-6 is complete. Story 1-7 (`AsyncClient` with HTTP methods, `response_model`, `with_options`, lifecycle) is the next normal-flow item in Epic 1.

---

## Definition of done

- `src/httpware/_internal/import_checker.py` exists with `is_msgspec_installed`.
- `src/httpware/decoders/msgspec.py` exists with `MISSING_DEPENDENCY_MESSAGE` constant and `MsgspecDecoder` class. No `__all__`.
- `tests/test_decoders_msgspec.py` contains 8 passing tests.
- `tests/test_optional_extras_isolation.py` contains the subprocess-based import-isolation test; passes.
- `CHANGELOG.md` has a Story 1.6 bullet under `[Unreleased]` / `### Added`.
- `just test` shows 207 passed, 1 deselected, 100% line coverage.
- `just lint-ci` clean.
- `tests/test_no_httpx2_leakage.py` still passes.
- Story 1-6 lands as a single PR off `main` via the branch `story/1-6-msgspec-decoder-via-extras`.

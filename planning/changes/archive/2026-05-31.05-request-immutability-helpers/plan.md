---
status: shipped
date: 2026-05-31
slug: request-immutability-helpers
spec: request-immutability-helpers
pr: 10
---

# Request / Response immutability helper expansion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship Story 2-3: add 5 new `with_*` helpers to `Request` (`with_headers`, `with_cookie`, `with_cookies`, `with_extension`, `with_extensions`) and 2 to `Response` (`with_headers`, `with_status`).

**Architecture:** All seven helpers are one-line `dataclasses.replace(...)` calls following the existing Story-1-2 pattern (`with_header`, `with_url`, `with_body`, `with_query`). Plural helpers merge: `{**existing, **incoming}`. Singular helpers (`with_cookie`, `with_extension`) take `(name, value)` and add/replace one entry. No validation, no case normalization.

**Tech Stack:** Python 3.11 floor; `dataclasses.replace` on frozen+slots dataclasses. No new dependencies.

**Branch:** `story/2-3-request-immutability-helpers` (already created; spec commit `5bcf9a4` is on it).

**Spec:** `planning/specs/2026-05-31-request-immutability-helpers-design.md`.

---

## File Structure

**Modified files:**
- `src/httpware/request.py` — append 5 helper methods (~20 lines added).
- `src/httpware/response.py` — append 2 helper methods + add `Self` and `dataclasses` imports (~10 lines added).
- `tests/test_request.py` — append 10 new tests.
- `tests/test_response.py` — append 4 new tests.
- `CHANGELOG.md` — append Story 2.3 bullet under `[Unreleased]` / `### Added`.

**Files not touched:** everything else. Purely additive.

---

## Task 1: `Request.with_headers` (merge headers)

TDD cycle for the plural-merge helper on Request. Four tests cover add, override, preserve, and empty-input cases.

**Files:**
- Modify: `src/httpware/request.py` (append method)
- Modify: `tests/test_request.py` (append 4 tests)

- [ ] **Step 1: Add the failing tests**

Append to `tests/test_request.py`:

```python
def test_with_headers_merges_new_headers() -> None:
    r = Request(method="GET", url="/")
    new = r.with_headers({"X-Trace": "abc", "X-Other": "1"})
    assert new.headers == {"X-Trace": "abc", "X-Other": "1"}
    assert r.headers == {}


def test_with_headers_overrides_existing_key() -> None:
    r = Request(method="GET", url="/", headers={"X-Trace": "old"})
    new = r.with_headers({"X-Trace": "new"})
    assert new.headers == {"X-Trace": "new"}
    assert r.headers == {"X-Trace": "old"}


def test_with_headers_preserves_other_keys() -> None:
    r = Request(method="GET", url="/", headers={"Keep": "1", "Replace": "old"})
    new = r.with_headers({"Replace": "new", "Add": "2"})
    assert new.headers == {"Keep": "1", "Replace": "new", "Add": "2"}


def test_with_headers_empty_mapping_returns_distinct_copy() -> None:
    r = Request(method="GET", url="/", headers={"A": "1"})
    new = r.with_headers({})
    assert new == r
    assert new is not r
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_request.py -k "with_headers" -v`
Expected: 4 errors with `AttributeError: 'Request' object has no attribute 'with_headers'`.

- [ ] **Step 3: Implement `with_headers`**

Append to `src/httpware/request.py`, immediately after the existing `with_query` method (i.e., as the last method of the `Request` class):

```python
    def with_headers(self, headers: Mapping[str, str]) -> Self:
        """Return a copy with the given headers merged in (incoming keys override existing)."""
        return dataclasses.replace(self, headers={**self.headers, **headers})
```

(Note: four-space indentation since this is a class method.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_request.py -k "with_headers" -v`
Expected: 4 passed.

- [ ] **Step 5: Lint and ty**

Run: `uv run ruff check src/httpware/request.py tests/test_request.py`
Run: `uv run ty check src/httpware/request.py`
Expected: both clean.

- [ ] **Step 6: Commit**

```bash
git add src/httpware/request.py tests/test_request.py
git commit -m "$(cat <<'EOF'
feat(story-2.3): Request.with_headers merge helper

Adds Request.with_headers(headers: Mapping[str, str]) -> Self that
merges the incoming mapping into the existing headers; incoming keys
override existing. Four tests cover add, override, preserve-others,
and empty-input semantics.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `Request.with_cookie` and `Request.with_cookies`

The cookies pair mirrors `with_header` / `with_headers`: singular adds/replaces one entry, plural merges.

**Files:**
- Modify: `src/httpware/request.py` (append two methods)
- Modify: `tests/test_request.py` (append 3 tests)

- [ ] **Step 1: Add the failing tests**

Append to `tests/test_request.py`:

```python
def test_with_cookie_adds_single_cookie() -> None:
    r = Request(method="GET", url="/")
    new = r.with_cookie("session", "abc")
    assert new.cookies == {"session": "abc"}
    assert r.cookies == {}


def test_with_cookie_replaces_existing_cookie() -> None:
    r = Request(method="GET", url="/", cookies={"session": "old"})
    new = r.with_cookie("session", "new")
    assert new.cookies == {"session": "new"}
    assert r.cookies == {"session": "old"}


def test_with_cookies_merges_new_cookies() -> None:
    r = Request(method="GET", url="/", cookies={"keep": "1", "replace": "old"})
    new = r.with_cookies({"replace": "new", "add": "2"})
    assert new.cookies == {"keep": "1", "replace": "new", "add": "2"}
    assert r.cookies == {"keep": "1", "replace": "old"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_request.py -k "with_cookie" -v`
Expected: 3 errors with `AttributeError: 'Request' object has no attribute 'with_cookie'` (and `with_cookies`).

- [ ] **Step 3: Implement both methods**

Append to `src/httpware/request.py`, immediately after `with_headers`:

```python
    def with_cookie(self, name: str, value: str) -> Self:
        """Return a copy with the given cookie added or replaced."""
        return dataclasses.replace(self, cookies={**self.cookies, name: value})

    def with_cookies(self, cookies: Mapping[str, str]) -> Self:
        """Return a copy with the given cookies merged in (incoming keys override existing)."""
        return dataclasses.replace(self, cookies={**self.cookies, **cookies})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_request.py -k "with_cookie" -v`
Expected: 3 passed.

- [ ] **Step 5: Lint and ty**

Run: `uv run ruff check src/httpware/request.py tests/test_request.py`
Run: `uv run ty check src/httpware/request.py`
Expected: both clean.

- [ ] **Step 6: Commit**

```bash
git add src/httpware/request.py tests/test_request.py
git commit -m "$(cat <<'EOF'
feat(story-2.3): Request.with_cookie and with_cookies helpers

Adds Request.with_cookie(name, value) -> Self and
Request.with_cookies(cookies: Mapping) -> Self. Singular adds/replaces
one cookie; plural merges a mapping with incoming keys overriding.
Three tests cover the add, replace, and merge cases.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `Request.with_extension` and `Request.with_extensions`

The extensions pair mirrors `with_cookie` / `with_cookies` but values are `Any` (extensions are opaque user payloads passed to the transport).

**Files:**
- Modify: `src/httpware/request.py` (append two methods)
- Modify: `tests/test_request.py` (append 3 tests)

- [ ] **Step 1: Add the failing tests**

Append to `tests/test_request.py`:

```python
def test_with_extension_adds_single_entry() -> None:
    r = Request(method="GET", url="/")
    new = r.with_extension("timeout", 5.0)
    assert new.extensions == {"timeout": 5.0}
    assert r.extensions == {}


def test_with_extensions_merges_new_entries() -> None:
    r = Request(method="GET", url="/", extensions={"keep": 1, "replace": "old"})
    new = r.with_extensions({"replace": "new", "add": [1, 2]})
    assert new.extensions == {"keep": 1, "replace": "new", "add": [1, 2]}
    assert r.extensions == {"keep": 1, "replace": "old"}


def test_with_extension_accepts_any_value_type() -> None:
    class _Marker:
        pass

    marker = _Marker()
    r = Request(method="GET", url="/")
    new = r.with_extension("marker", marker)
    assert new.extensions == {"marker": marker}
    assert new.extensions["marker"] is marker
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_request.py -k "with_extension" -v`
Expected: 3 errors with `AttributeError: 'Request' object has no attribute 'with_extension'` (and `with_extensions`).

- [ ] **Step 3: Implement both methods**

Append to `src/httpware/request.py`, immediately after `with_cookies`:

```python
    def with_extension(self, name: str, value: Any) -> Self:  # noqa: ANN401
        """Return a copy with the given extension entry added or replaced."""
        return dataclasses.replace(self, extensions={**self.extensions, name: value})

    def with_extensions(self, extensions: Mapping[str, Any]) -> Self:
        """Return a copy with the given extensions merged in (incoming keys override existing)."""
        return dataclasses.replace(self, extensions={**self.extensions, **extensions})
```

The `# noqa: ANN401` on `with_extension`'s `value: Any` is intentional — extensions are opaque user payloads. Matches the existing `# noqa: ANN401` pattern on `Response.json()`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_request.py -k "with_extension" -v`
Expected: 3 passed.

- [ ] **Step 5: Full Request test pass + lint**

Run: `uv run pytest tests/test_request.py -v`
Expected: All previously-passing tests plus 10 new ones (4 from Task 1 + 3 from Task 2 + 3 from Task 3) pass.

Run: `uv run ruff check src/httpware/request.py tests/test_request.py`
Run: `uv run ty check src/httpware/request.py`
Expected: both clean.

- [ ] **Step 6: Commit**

```bash
git add src/httpware/request.py tests/test_request.py
git commit -m "$(cat <<'EOF'
feat(story-2.3): Request.with_extension and with_extensions helpers

Adds Request.with_extension(name, value: Any) -> Self and
Request.with_extensions(extensions: Mapping[str, Any]) -> Self.
Extensions hold opaque user payloads (transport hints, debug
attachments) — the Any value type is intentional and noqa'd. Three
tests cover add-single, merge-plural, and Any-value-type behavior.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: `Response.with_headers` and `Response.with_status`

Response gets the same merge-headers helper as Request, plus `with_status` for status code replacement.

**Files:**
- Modify: `src/httpware/response.py` (add imports + two methods)
- Modify: `tests/test_response.py` (append 4 tests)

- [ ] **Step 1: Add the failing tests**

Append to `tests/test_response.py`:

```python
def test_response_with_headers_merges_new_headers() -> None:
    resp = Response(status=200, headers={"keep": "1"}, content=b"", url="/", elapsed=0.0)
    new = resp.with_headers({"x-trace": "abc"})
    assert new.headers == {"keep": "1", "x-trace": "abc"}
    assert resp.headers == {"keep": "1"}


def test_response_with_headers_overrides_existing_key() -> None:
    resp = Response(status=200, headers={"x-trace": "old"}, content=b"", url="/", elapsed=0.0)
    new = resp.with_headers({"x-trace": "new"})
    assert new.headers == {"x-trace": "new"}
    assert resp.headers == {"x-trace": "old"}


def test_response_with_status_replaces_status() -> None:
    resp = Response(status=200, headers={"a": "1"}, content=b"body", url="/x", elapsed=0.5)
    new = resp.with_status(503)
    assert new.status == 503
    assert new.headers == {"a": "1"}
    assert new.content == b"body"
    assert new.url == "/x"
    assert new.elapsed == 0.5
    assert resp.status == 200


def test_response_with_status_accepts_arbitrary_int() -> None:
    resp = Response(status=200, headers={}, content=b"", url="/", elapsed=0.0)
    # No validation by design — value objects don't enforce protocol semantics.
    new = resp.with_status(99)
    assert new.status == 99
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_response.py -k "with_" -v`
Expected: 4 errors with `AttributeError: 'Response' object has no attribute 'with_headers'` (and `with_status`).

- [ ] **Step 3: Add imports to `src/httpware/response.py`**

Edit the top of `src/httpware/response.py`. The current imports are:

```python
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
```

Change them to:

```python
import dataclasses
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Self
```

(`import dataclasses` is added so that `dataclasses.replace(...)` works inside the new methods. `Self` is added to `typing` for the return type.)

- [ ] **Step 4: Implement both methods on `Response`**

In `src/httpware/response.py`, append to the `Response` class (after the existing `json` method, before the `StreamResponse` class):

```python
    def with_headers(self, headers: Mapping[str, str]) -> Self:
        """Return a copy with the given headers merged in (incoming keys override existing)."""
        return dataclasses.replace(self, headers={**self.headers, **headers})

    def with_status(self, status: int) -> Self:
        """Return a copy with the given status code."""
        return dataclasses.replace(self, status=status)
```

(Four-space indentation for class methods.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_response.py -v`
Expected: All previously-passing tests plus 4 new ones pass.

- [ ] **Step 6: Lint and ty**

Run: `uv run ruff check src/httpware/response.py tests/test_response.py`
Run: `uv run ty check src/httpware/response.py`
Expected: both clean.

- [ ] **Step 7: Commit**

```bash
git add src/httpware/response.py tests/test_response.py
git commit -m "$(cat <<'EOF'
feat(story-2.3): Response.with_headers and with_status helpers

Adds Response.with_headers(headers: Mapping[str, str]) -> Self and
Response.with_status(status: int) -> Self for ergonomic Response
rewriting from middleware. Both use the existing dataclasses.replace
pattern. with_status applies no validation by design — value objects
don't enforce protocol semantics.

Adds `import dataclasses` and `Self` to response.py's typing imports.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: CHANGELOG bullet

Record the Story 2.3 surface under `[Unreleased]` / `### Added`.

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Append the CHANGELOG bullet**

Edit `CHANGELOG.md`. The `## [Unreleased]` / `### Added` section currently ends with the Story 2.2 bullet about the phase-shortcut decorators. Append a new bullet immediately after the Story 2.2 bullet (still before the `[Unreleased]: ...` reference link at the bottom):

```markdown
- Request and Response immutability helper expansion: `Request.with_headers`, `with_cookie`, `with_cookies`, `with_extension`, `with_extensions`; `Response.with_headers`, `with_status`. Plural helpers merge mappings (incoming keys override existing); singular helpers add or replace a single entry. No validation, no header-key normalization — matches the existing `with_header` semantics from Story 1.2 (Story 2.3).
```

- [ ] **Step 2: Commit**

```bash
git add CHANGELOG.md
git commit -m "$(cat <<'EOF'
docs(story-2.3): CHANGELOG entry for immutability helper expansion

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Verify, push, PR, merge

End-to-end sanity check on the branch, push, open PR, wait for CI, merge.

- [ ] **Step 1: Run the full test suite with coverage**

Run: `just test`
Expected: 198 passed (184 baseline post-2-2 + 14 new), 1 deselected (perf), 100% line coverage including the seven new helpers.

If coverage is below 100% on `request.py` or `response.py`, identify the uncovered line. The new helpers are all one-line bodies that are exercised by their dedicated tests — uncovered lines indicate a missing test.

- [ ] **Step 2: Run full lint and type checks**

Run: `just lint-ci`
Expected: `eof-fixer`, `ruff format --check`, `ruff check --no-fix`, `ty check` all clean.

- [ ] **Step 3: Confirm the working tree is clean**

Run: `git status --short`
Expected: only the untracked plan file `planning/plans/2026-05-31-request-immutability-helpers-plan.md`.

- [ ] **Step 4: Review the branch diff**

Run: `git log --oneline main..HEAD`
Expected: six or seven commits — the spec commit (`docs(story-2.3): design...`), Task 1, Task 2, Task 3, Task 4, Task 5.

Run: `git diff --stat main..HEAD`
Expected: changes to `CHANGELOG.md`, `planning/specs/2026-05-31-request-immutability-helpers-design.md`, `src/httpware/request.py`, `src/httpware/response.py`, `tests/test_request.py`, `tests/test_response.py`. No other files touched.

- [ ] **Step 5: Stage and commit the plan file**

```bash
git add planning/plans/2026-05-31-request-immutability-helpers-plan.md
git commit -m "docs(story-2.3): implementation plan for immutability helpers

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 6: Push the branch**

Run: `git push -u origin story/2-3-request-immutability-helpers`
Expected: push succeeds; GitHub prints a "Create a pull request for ..." URL.

- [ ] **Step 7: Open the PR**

```bash
gh pr create --title "feat(story-2.3): Request/Response immutability helper expansion" --body "$(cat <<'EOF'
## Summary

- Adds 5 helpers to \`Request\`: \`with_headers\` (merge), \`with_cookie\` / \`with_cookies\` (singular add/replace + plural merge), \`with_extension\` / \`with_extensions\` (same pattern, value type \`Any\`).
- Adds 2 helpers to \`Response\`: \`with_headers\` (merge) and \`with_status\` (replace).
- Convention: singular \`with_X(name, value)\` adds/replaces one entry; plural \`with_Xs(items)\` merges with incoming keys overriding.
- Existing helpers untouched, including \`with_query\`'s REPLACE semantics — the asymmetry vs \`with_headers\` MERGE is justified by usage patterns, HTTP semantics, and the singular-helper escape hatch (full rationale in the spec).
- 14 new tests (10 on Request, 4 on Response); 100% line coverage on new helpers; \`just test\` shows 198 passed.

Out of scope (subsequent stories): auth coercion (2-4), AsyncClient wiring (2-5), \`StreamResponse.with_*\` (Story 4-1), case-insensitive header keys (existing deferred-work entry).

Spec + plan: \`planning/specs/2026-05-31-request-immutability-helpers-design.md\`, \`planning/plans/2026-05-31-request-immutability-helpers-plan.md\`.

## Test plan

- [x] \`just test\` — 198 passed, 1 deselected, 100% line coverage.
- [x] \`just lint-ci\` clean.
- [x] \`tests/test_no_httpx2_leakage.py\` still passes.
- [ ] CI green on all matrix entries (3.11/3.12/3.13/3.14 + lint).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 8: Wait for CI**

Run: `gh pr checks <PR_NUMBER>` (the number is printed by `gh pr create`).
Expected: all five jobs green.

If `pytest (3.14)` fails on the `codecov/codecov-action@v4.0.1` step (transient EPIPE has been observed twice in this repo), re-run with `gh run rerun <RUN_ID> --failed`.

- [ ] **Step 9: Merge**

Once CI is green:

Run: `gh pr merge <PR_NUMBER> --merge --delete-branch`
Run: `git checkout main && git pull --ff-only && git log --oneline -3`

Story 2-3 is complete. Story 2-4 (auth coercion as middleware) is the next normal-flow item.

---

## Definition of done

- `src/httpware/request.py` has 5 new methods: `with_headers`, `with_cookie`, `with_cookies`, `with_extension`, `with_extensions`. Existing methods untouched.
- `src/httpware/response.py` has 2 new methods: `with_headers`, `with_status`. Imports updated to include `dataclasses` and `Self`.
- `tests/test_request.py` contains 10 new tests; all pass.
- `tests/test_response.py` contains 4 new tests; all pass.
- `CHANGELOG.md` has a Story 2.3 bullet under `[Unreleased]` / `### Added`.
- `just test` shows 198 passed, 1 deselected, 100% line coverage.
- `just lint-ci` clean.
- `tests/test_no_httpx2_leakage.py` still passes.
- Both spec and plan committed on `story/2-3-request-immutability-helpers` and land via a single PR.

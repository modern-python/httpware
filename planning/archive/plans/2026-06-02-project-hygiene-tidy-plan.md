# Project hygiene tidy implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land four small hygiene fixes in one PR: a `just publish` env-var guard, a widened `uv_build` band, project-wide `http.HTTPStatus` substitution for status-code `PLR2004` noqas, and a two-line `Response.json()` correctness fix (honors declared charset).

**Architecture:** Six atomic-commit tasks executed in dependency order. Tasks 1–2 are config-only (Justfile, pyproject.toml). Tasks 3–4 are behavior-preserving refactors (HTTPStatus substitutions in tests and one source file). Task 5 is a proper TDD cycle for `Response.json()` (failing test first, then fix). Task 6 closes the deferred-work entries this PR resolves. No CI invariants change; no public API break.

**Tech Stack:** `uv` (build system + package manager), `just` (task runner), `pytest`, `ruff` (lint, with `RUF100` to catch unused noqas), `http.HTTPStatus` (stdlib).

---

## Pre-flight

Plan assumes a clean working tree at the spec's commit (`2026-06-02-project-hygiene-tidy-design.md` is already committed). Verify before starting:

```bash
git status              # should be clean
git log --oneline -3    # confirm the hygiene spec commit is present
```

The spec lives at `planning/specs/2026-06-02-project-hygiene-tidy-design.md` — read it once if you haven't.

Establish the baseline:

```bash
just lint-ci
just test
```

Both must exit 0 before any task. If either fails on `main`, stop and surface it to the user — this plan assumes a green baseline.

---

### Task 1: `just publish` env-var guard

**Goal:** Refuse to run the publish recipe when `GITHUB_REF_NAME` or `PYPI_TOKEN` is unset, so that local invocations cannot corrupt `pyproject.toml` via `uv version ""`.

**Files:**
- Modify: `Justfile` (the `publish` recipe at lines 25-29)

- [ ] **Step 1: Read current `publish` recipe**

Run: `sed -n '25,29p' Justfile`

Expected output:

```
publish:
    rm -rf dist
    uv version $GITHUB_REF_NAME
    uv build
    uv publish --token $PYPI_TOKEN
```

- [ ] **Step 2: Replace the recipe**

Edit `Justfile`, replacing the existing `publish` recipe with:

```just
publish:
    @test -n "$GITHUB_REF_NAME" || (echo "GITHUB_REF_NAME is required; refusing to run outside CI" >&2; exit 1)
    @test -n "$PYPI_TOKEN" || (echo "PYPI_TOKEN is required" >&2; exit 1)
    rm -rf dist
    uv version $GITHUB_REF_NAME
    uv build
    uv publish --token $PYPI_TOKEN
```

(The `@` prefix suppresses just's echoing of the guard line itself; the actual error message still reaches stderr via `echo … >&2`.)

- [ ] **Step 3: Verify the guard rejects empty env**

Run: `env -i PATH="$PATH" HOME="$HOME" just publish`

Expected: exits non-zero, prints `GITHUB_REF_NAME is required; refusing to run outside CI` on stderr.

- [ ] **Step 4: Verify `pyproject.toml` was NOT mutated**

Run: `git status pyproject.toml`

Expected: empty output (no changes to `pyproject.toml`). If `pyproject.toml` shows as modified, the guard failed — STOP and investigate.

- [ ] **Step 5: Verify the recipe still parses for the happy path**

Run: `just --show publish`

Expected: prints the new recipe body, confirming `just` parsed it without error.

- [ ] **Step 6: Commit**

```bash
git add Justfile
git commit -m "$(cat <<'EOF'
build: guard just publish against missing env vars

Refuse to run when GITHUB_REF_NAME or PYPI_TOKEN is unset, so local
invocations cannot corrupt pyproject.toml via uv version "".

Closes deferred-work entry: "just publish lacks env-var validation".
EOF
)"
```

---

### Task 2: Widen `uv_build` band to `<1.0`

**Goal:** Stop the every-minor bump treadmill on `uv_build`. Any 0.x release is accepted; an incompatible bump (hypothetical) surfaces as a loud build error in CI, not a silent regression.

**Files:**
- Modify: `pyproject.toml` line 49 (`[build-system] requires`)

- [ ] **Step 1: Read the current `[build-system]`**

Run: `grep -A2 '^\[build-system\]' pyproject.toml`

Expected:

```
[build-system]
requires = ["uv_build>=0.11,<0.12"]
build-backend = "uv_build"
```

- [ ] **Step 2: Widen the band**

Edit `pyproject.toml`, changing the `requires` line from:

```toml
requires = ["uv_build>=0.11,<0.12"]
```

to:

```toml
requires = ["uv_build>=0.11,<1.0"]
```

- [ ] **Step 3: Refresh the lockfile**

Run: `uv lock --upgrade`

Expected: exits 0. May or may not change `uv.lock` depending on whether a newer `uv_build` 0.x exists; either outcome is fine.

- [ ] **Step 4: Verify install still works**

Run: `just install`

Expected: exits 0.

- [ ] **Step 5: Verify build still works**

Run: `rm -rf dist && uv build`

Expected: exits 0; `dist/` contains an `.whl` and a `.tar.gz`.

Then clean up: `rm -rf dist`.

- [ ] **Step 6: Verify tests still pass**

Run: `just test`

Expected: exits 0.

- [ ] **Step 7: Commit**

Stage `pyproject.toml` and `uv.lock` together (the lock may or may not have changed; if it did, it ships with the band widening).

```bash
git add pyproject.toml uv.lock
git commit -m "$(cat <<'EOF'
build: widen uv_build band to <1.0

Accept all 0.x releases; stops the every-minor bump treadmill. An
incompatible 0.x bump (hypothetical) surfaces as a loud build error
in CI, not a silent regression.

Closes deferred-work entry: "uv_build>=0.11,<0.12 narrow window".
EOF
)"
```

(If `uv.lock` was unchanged, `git add uv.lock` is a no-op and the commit only includes `pyproject.toml` — that's fine.)

---

### Task 3: HTTPStatus substitution in test files

**Goal:** Replace status-code integer literals with `http.HTTPStatus` constants across the three test files that hold them. Each substitution removes a `# noqa: PLR2004`. Eleven instances total.

**Why one commit for three files:** All three files implement the same conceptual change (`literal → HTTPStatus.X`) with no logic change. Splitting per-file adds three commits with identical justifications.

**Files:**
- Modify: `tests/test_transports_httpx2.py` (lines 72, 103, 135, 146)
- Modify: `tests/test_response.py` (lines 111, 116; line 123 stays — `status == 99` is intentionally invalid)
- Modify: `tests/test_middleware.py` (lines 67, 195, 268, 335)

**HTTPStatus mapping (verified for Python 3.11+):**

| Literal | HTTPStatus member |
|---|---|
| `200` | `HTTPStatus.OK` |
| `418` | `HTTPStatus.IM_A_TEAPOT` |
| `503` | `HTTPStatus.SERVICE_UNAVAILABLE` |
| `504` | `HTTPStatus.GATEWAY_TIMEOUT` |

- [ ] **Step 1: Edit `tests/test_transports_httpx2.py`**

Add at the top of the imports block (after the stdlib imports; ruff isort will land it correctly):

```python
from http import HTTPStatus
```

Then replace these four lines:

```python
# Line 72:
    assert resp.status == 200  # noqa: PLR2004
# →
    assert resp.status == HTTPStatus.OK

# Line 103:
    assert resp.status == 200  # noqa: PLR2004
# →
    assert resp.status == HTTPStatus.OK

# Line 135:
    assert info.value.status == 418  # noqa: PLR2004
# →
    assert info.value.status == HTTPStatus.IM_A_TEAPOT

# Line 146:
    assert info.value.status == 504  # noqa: PLR2004
# →
    assert info.value.status == HTTPStatus.GATEWAY_TIMEOUT
```

- [ ] **Step 2: Edit `tests/test_response.py`**

Add at the top:

```python
from http import HTTPStatus
```

Replace these lines:

```python
# Line 111:
    assert new.status == 503  # noqa: PLR2004
# →
    assert new.status == HTTPStatus.SERVICE_UNAVAILABLE

# Line 116:
    assert resp.status == 200  # noqa: PLR2004
# →
    assert resp.status == HTTPStatus.OK
```

Do NOT touch line 123 (`assert new.status == 99  # noqa: PLR2004`) — that test deliberately exercises an invalid status; `99` is not an `HTTPStatus` member.

Do NOT touch line 115 (`assert new.elapsed == 0.5  # noqa: PLR2004`) — float, not a status code.

- [ ] **Step 3: Edit `tests/test_middleware.py`**

Add at the top:

```python
from http import HTTPStatus
```

Replace these lines:

```python
# Line 67:
    assert response.status == 200  # noqa: PLR2004
# →
    assert response.status == HTTPStatus.OK

# Line 195:
    assert response.status == 418  # noqa: PLR2004
# →
    assert response.status == HTTPStatus.IM_A_TEAPOT

# Line 268:
        assert response.status == 200  # noqa: PLR2004
# →
        assert response.status == HTTPStatus.OK

# Line 335:
    assert response.status == 503  # noqa: PLR2004
# →
    assert response.status == HTTPStatus.SERVICE_UNAVAILABLE
```

Do NOT touch line 270 (`assert count == 3  # noqa: PLR2004`) — count, not a status code.

- [ ] **Step 4: Run tests to verify no behavior change**

Run: `just test tests/test_transports_httpx2.py tests/test_response.py tests/test_middleware.py`

Expected: all tests pass. `HTTPStatus` members are `IntEnum`, so `assert response.status == HTTPStatus.OK` is equivalent to `assert response.status == 200`.

- [ ] **Step 5: Run lint to catch unused noqas**

Run: `just lint-ci`

Expected: exits 0. Specifically, `RUF100` should NOT flag the removed noqas (because they were removed in this commit). If any of the three test files still has a bare `# noqa: PLR2004` on a status-code line that this task missed, ruff will pass but the grep in step 6 will catch it.

- [ ] **Step 6: Grep to confirm no leftover status-code noqas**

Run:

```bash
grep -n 'PLR2004' tests/test_transports_httpx2.py tests/test_response.py tests/test_middleware.py
```

Expected: only non-status lines remain:
- `tests/test_response.py:115` (elapsed)
- `tests/test_response.py:123` (intentionally invalid status 99)
- `tests/test_middleware.py:270` (count == 3)

If any status-code line is still listed, you missed a substitution — go back to the relevant step.

- [ ] **Step 7: Commit**

```bash
git add tests/test_transports_httpx2.py tests/test_response.py tests/test_middleware.py
git commit -m "$(cat <<'EOF'
test: use http.HTTPStatus constants for status-code assertions

Replaces 11 instances of `assert status == <int>  # noqa: PLR2004`
with `assert status == HTTPStatus.<NAME>` across three test files.
Each substitution removes a noqa; HTTPStatus members are IntEnum so
behavior is unchanged.

Non-status-code PLR2004 noqas (counts, elapsed, intentionally-invalid
status==99) are out of scope.

Partial: deferred-work "PLR2004 per-file-ignores" entry.
EOF
)"
```

---

### Task 4: HTTPStatus substitution in `src/httpware/transports/httpx2.py`

**Goal:** Replace the `400` and `500` literals in the status-code dispatch block with `HTTPStatus` constants. The `< 600` synthetic upper bound has no stdlib equivalent; keep its noqa but add a per-line justification (matching the user's lint-suppression hierarchy).

**Files:**
- Modify: `src/httpware/transports/httpx2.py` (lines 144-148, plus an import)

- [ ] **Step 1: Read the current dispatch block**

Run: `sed -n '140,160p' src/httpware/transports/httpx2.py`

Expected (relevant lines):

```python
        if 400 <= status < 600:  # noqa: PLR2004
            exc_class = STATUS_TO_EXCEPTION.get(
                status,
                ClientStatusError if status < 500 else ServerStatusError,  # noqa: PLR2004
            )
```

- [ ] **Step 2: Add the import**

Add to the stdlib imports block at the top of the file (after `import json`, before `import time` — alphabetical, ruff isort will sort if needed):

```python
from http import HTTPStatus
```

- [ ] **Step 3: Replace the dispatch block**

Replace lines 144-148 (the `if 400 <= status < 600:` block) with:

```python
        if HTTPStatus.BAD_REQUEST <= status < 600:  # noqa: PLR2004 — 600 is the synthetic 5xx upper bound
            exc_class = STATUS_TO_EXCEPTION.get(
                status,
                ClientStatusError if status < HTTPStatus.INTERNAL_SERVER_ERROR else ServerStatusError,
            )
```

(The first line keeps its `# noqa: PLR2004` because `600` is still a literal; the inline justification documents why no constant replaces it. The second line loses its noqa because `HTTPStatus.INTERNAL_SERVER_ERROR` is not a magic number.)

- [ ] **Step 4: Run transport tests to verify no behavior change**

Run: `just test tests/test_transports_httpx2.py tests/test_errors.py`

Expected: all tests pass. `HTTPStatus.BAD_REQUEST` is `400` as an `IntEnum`; comparisons work identically.

- [ ] **Step 5: Run full lint**

Run: `just lint-ci`

Expected: exits 0. `RUF100` would flag the removed inner noqa as unused if you forgot to remove it; the new outer noqa is fine because `600` is still a magic literal.

- [ ] **Step 6: Run full test suite**

Run: `just test`

Expected: exits 0.

- [ ] **Step 7: Commit**

```bash
git add src/httpware/transports/httpx2.py
git commit -m "$(cat <<'EOF'
refactor: use HTTPStatus constants in transport status dispatch

Replaces 400 → HTTPStatus.BAD_REQUEST and 500 →
HTTPStatus.INTERNAL_SERVER_ERROR in the 4xx/5xx exception dispatch
block. The < 600 synthetic upper bound has no stdlib equivalent, so
its PLR2004 noqa stays — now with an inline justification.

Closes deferred-work entry: "PLR2004 per-file-ignores" (for status
codes; non-status instances remain open).
EOF
)"
```

---

### Task 5: `Response.json()` charset fix (TDD)

**Goal:** Route `Response.json()` through `self.text` so it honors the declared charset, and document the `json.JSONDecodeError` raise contract. Two-line behavior change; one new test.

**Files:**
- Test: `tests/test_response.py` (new test function)
- Modify: `src/httpware/response.py:50-52` (the `.json()` method)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_response.py`, immediately after `test_response_json_parses_body` (around line 84):

```python
def test_response_json_uses_declared_charset() -> None:
    body = '{"name": "café"}'.encode("iso-8859-1")
    resp = Response(
        status=HTTPStatus.OK,
        headers={"content-type": "application/json; charset=iso-8859-1"},
        content=body,
        url="/",
        elapsed=0.0,
    )
    assert resp.json() == {"name": "café"}
```

(Uses `HTTPStatus.OK` because Task 3 added the import to this file. If you're executing Task 5 before Task 3 — don't, follow the plan order — substitute `200` and add `# noqa: PLR2004`.)

- [ ] **Step 2: Run the test to verify it fails**

Run: `just test tests/test_response.py::test_response_json_uses_declared_charset -v`

Expected: FAIL. The body `b'{"name": "caf\xe9"}'` is invalid UTF-8 (the `\xe9` byte is Latin-1's `é`, not a valid UTF-8 continuation). `json.loads(self.content)` raises `json.JSONDecodeError` (or a `UnicodeDecodeError` wrapped inside one, depending on Python's exact error chain).

If the test PASSES, something is wrong with your test setup — `self.content` should be raw bytes and `json.loads` should fail on invalid UTF-8. Verify by adding `print(resp.content)` temporarily and re-running.

- [ ] **Step 3: Read the current `.json()` implementation**

Run: `sed -n '50,53p' src/httpware/response.py`

Expected:

```python
    def json(self) -> Any:  # noqa: ANN401
        """Parse `content` as JSON."""
        return json.loads(self.content)
```

- [ ] **Step 4: Update `.json()`**

Replace those three lines with:

```python
    def json(self) -> Any:  # noqa: ANN401
        """Parse `content` as JSON using the declared charset (default UTF-8).

        Raises:
            json.JSONDecodeError: if the body is not valid JSON.
        """
        return json.loads(self.text)
```

- [ ] **Step 5: Run the new test to verify it passes**

Run: `just test tests/test_response.py::test_response_json_uses_declared_charset -v`

Expected: PASS. `self.text` decodes the body via `_parse_charset` → `"iso-8859-1"` → correct `"café"` string; `json.loads(str)` then parses cleanly.

- [ ] **Step 6: Run the existing `.json()` test to verify no regression**

Run: `just test tests/test_response.py::test_response_json_parses_body -v`

Expected: PASS. UTF-8 body still decodes correctly through `self.text` (no charset declared → defaults to UTF-8).

- [ ] **Step 7: Run the full response-tests file**

Run: `just test tests/test_response.py`

Expected: all tests pass.

- [ ] **Step 8: Run full test suite + lint**

Run: `just test && just lint-ci`

Expected: both exit 0.

- [ ] **Step 9: Commit**

```bash
git add tests/test_response.py src/httpware/response.py
git commit -m "$(cat <<'EOF'
fix: Response.json() honors declared charset

Routes the body through self.text instead of json.loads(self.content),
so a declared charset (e.g. iso-8859-1) is respected before JSON
parsing. ASCII / UTF-8 bodies are unchanged. Docstring now explicitly
documents the json.JSONDecodeError raise contract.

Wrapping JSONDecodeError in a domain exception is left to a future
response-API revision.

Closes deferred-work entries: "Response.json() raises raw and ignores
charset" (retro) and "Response.json() honor declared charset" (1-2).
EOF
)"
```

---

### Task 6: Update `planning/deferred-work.md`

**Goal:** Remove the entries this PR closes and reword the PLR2004 entry to reflect what was actually done.

**Files:**
- Modify: `planning/deferred-work.md`

**Entries to remove:**
- "Story 1-2" section: `Response.json()` honor declared charset (consolidated with the retro entry — both are now resolved by Task 5)
- "Retrospective review" section: `Response.json()` raises raw and ignores charset (resolved by Task 5)
- "Story 1-1" section: `just publish` lacks env-var validation (Task 1)
- "Story 1-1" section: `uv_build>=0.11,<0.12` narrow window (Task 2)

**Entry to reword:**
- "Story 1-5" section: PLR2004 per-file-ignores. The deferred-work proposal (per-file-ignores) was rejected at the spec stage; the actual fix (HTTPStatus substitution for status-code instances) shipped in Tasks 3-4. Reword to document the remaining ~11 non-status PLR2004 noqas as the still-open scope.

- [ ] **Step 1: Read the current deferred-work entries to be touched**

Run: `grep -n 'Response.json\|just publish\|uv_build\|PLR2004' planning/deferred-work.md`

Expected: lines covering the four removals and one reword listed above.

- [ ] **Step 2: Remove the Retro `Response.json()` bullet**

In `planning/deferred-work.md`, delete the bullet that starts:

```markdown
- **`Response.json()` raises raw `JSONDecodeError` and ignores declared charset** — `json.loads(self.content)` …
```

It's in the "Deferred from: retrospective review of stories 1-1 through 1-5 (2026-05-31)" section.

- [ ] **Step 3: Reword the PLR2004 entry**

In the "Story 1-5" section, replace the existing PLR2004 bullet:

```markdown
- **`PLR2004` per-file-ignores** — `# noqa: PLR2004` repeated 5× in this test file; idiomatic fix is `tool.ruff.lint.per-file-ignores` for `tests/*`. Project-wide lint-config tidy. (`tests/test_decoders_pydantic.py:63,67,83,107,153`)
```

with:

```markdown
- **`PLR2004` noqas on non-status-code literals** — status-code instances were migrated to `http.HTTPStatus` constants (no noqa needed). ~11 instances remain on counts, list lengths, primitive-decode assertions, `elapsed` floats, and intentionally-invalid status values across `tests/test_decoders_pydantic.py`, `tests/test_decoders_msgspec.py`, `tests/test_client_methods.py`, `tests/test_internal_auth.py`, `tests/test_transports_recorded.py`, `tests/test_client_lifecycle.py`, and `tests/test_response.py`. No stdlib constant exists for "I made two calls in this test"; either accept the bare noqas or add per-line justifications. Per the user's lint-suppression hierarchy, `per-file-ignores` is the *least-preferred* form and should not be used.
```

- [ ] **Step 4: Remove the Story 1-2 `Response.json()` bullet**

In the "Story 1-2" section, delete the bullet:

```markdown
- **`Response.json()` honor declared charset** — `json.loads(bytes)` auto-detects only UTF-8/16/32. Real APIs vary. (`src/httpware/response.py:44-45`)
```

- [ ] **Step 5: Remove the Story 1-1 `just publish` bullet**

In the "Story 1-1" section, delete the bullet:

```markdown
- **`just publish` lacks env-var validation** — recipe assumes `GITHUB_REF_NAME` and `PYPI_TOKEN` are set; running locally could corrupt the version. Add `test -n "$GITHUB_REF_NAME"` guard before release work. (`Justfile:25-29`)
```

- [ ] **Step 6: Remove the Story 1-1 `uv_build` bullet**

In the "Story 1-1" section, delete the bullet:

```markdown
- **`uv_build>=0.11,<0.12` narrow window** — single-minor band will expire as soon as uv_build 0.12 ships; bump when that happens. (`pyproject.toml:49`)
```

- [ ] **Step 7: Verify the file**

Run: `grep -n 'Response.json\|just publish\|uv_build>=0.11,<0.12' planning/deferred-work.md`

Expected: empty output. All four removals confirmed.

Run: `grep -n 'PLR2004' planning/deferred-work.md`

Expected: one line — the reworded bullet describing the remaining ~11 non-status noqas.

- [ ] **Step 8: Commit**

```bash
git add planning/deferred-work.md
git commit -m "$(cat <<'EOF'
docs: close deferred-work entries resolved by hygiene tidy PR

Removes four entries closed by this PR (just publish guard, uv_build
band, Response.json() charset+raise — last one was duplicated across
the retro section and the original Story 1-2 review).

Rewords the PLR2004 entry to document what was actually done (status
codes migrated to http.HTTPStatus) and what remains open (~11 non-
status noqas on counts and primitive values).
EOF
)"
```

---

### Task 7: Final verification

**Goal:** Confirm the PR is internally consistent and ready for review.

- [ ] **Step 1: Full lint + test**

Run: `just lint-ci && just test`

Expected: both exit 0.

- [ ] **Step 2: Confirm the publish guard still works**

Run: `env -i PATH="$PATH" HOME="$HOME" just publish; echo "exit=$?"; git status pyproject.toml`

Expected: prints the guard error message, `exit=1`, and `git status pyproject.toml` shows no diff.

- [ ] **Step 3: Confirm no bare status-code PLR2004 noqas remain**

Run:

```bash
grep -rn 'PLR2004' src/ tests/
```

Expected: only non-status instances plus the one justified `< 600` noqa in `src/httpware/transports/httpx2.py`. Specifically, you should see:
- `src/httpware/transports/httpx2.py:NNN` — the `< 600` line with its inline `— 600 is the synthetic 5xx upper bound` justification
- `tests/test_decoders_pydantic.py` — 5 lines (out of scope per spec)
- `tests/test_decoders_msgspec.py` — 1 line
- `tests/test_client_methods.py` — 1 line
- `tests/test_internal_auth.py` — 1 line
- `tests/test_transports_recorded.py` — 1 line
- `tests/test_client_lifecycle.py` — 1 line
- `tests/test_response.py:115,123` — 2 lines (elapsed, intentional invalid status)
- `tests/test_middleware.py:270` — 1 line (count)

No status-code (200/418/503/504) lines should be in this list.

- [ ] **Step 4: Confirm closed deferred-work entries are gone**

Run:

```bash
grep -E 'just publish|uv_build>=0\.11,<0\.12|Response\.json' planning/deferred-work.md
```

Expected: empty output.

- [ ] **Step 5: Review the commit log**

Run: `git log --oneline origin/main..HEAD`

Expected: six commits, in order:

```
<hash> docs: close deferred-work entries resolved by hygiene tidy PR
<hash> fix: Response.json() honors declared charset
<hash> refactor: use HTTPStatus constants in transport status dispatch
<hash> test: use http.HTTPStatus constants for status-code assertions
<hash> build: widen uv_build band to <1.0
<hash> build: guard just publish against missing env vars
```

(Commit order is bottom-up because git log shows newest first.)

- [ ] **Step 6: PR readiness check**

Run: `git diff origin/main --stat`

Expected ~7 files touched:
- `Justfile`
- `pyproject.toml`
- `uv.lock` (possibly)
- `src/httpware/transports/httpx2.py`
- `src/httpware/response.py`
- `tests/test_transports_httpx2.py`
- `tests/test_response.py`
- `tests/test_middleware.py`
- `planning/deferred-work.md`

If any file outside this list shows up, investigate before pushing.

---

## After completion

The branch is ready to push and PR. Suggested PR title:

> `chore: project hygiene tidy — publish guard, uv_build band, HTTPStatus, Response.json() charset`

PR description should reference the spec at `planning/specs/2026-06-02-project-hygiene-tidy-design.md` and list the closed deferred-work entries.

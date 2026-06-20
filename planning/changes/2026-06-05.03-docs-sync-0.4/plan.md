---
status: shipped
date: 2026-06-05
slug: docs-sync-0.4
spec: docs-sync-0.4
pr: 25
---

# Docs-sync 0.4 (Epic 3 story 3-6) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Edit five files to bring the live user-facing docs in sync with what's actually shipped on `main` (Retry, RetryBudget, Bulkhead, NetworkError, BulkheadFullError, RetryBudgetExhaustedError). README + `docs/index.md` + `docs/dev/contributing.md` + `mkdocs.yml` + `planning/engineering.md`.

**Architecture:** Docs-only PR. No source/test changes. Each task is one file, one commit, with concrete before/after blocks the implementer can apply mechanically. Verification: `just lint` (eof-fixer might touch markdown), `just test` (sanity that nothing broke), and `uv run --with mkdocs --with mkdocs-material mkdocs build --strict` (currently emits 2 nav warnings; must drop to 0 after this PR).

**Tech Stack:** Markdown + YAML. No Python changes. `mkdocs` + `mkdocs-material` invoked via uv `--with` (they're in `docs/requirements.txt` but not the default dev group).

**Target branch:** `docs/sync-0.4`.

**Source spec:** [`planning/specs/2026-06-05-docs-sync-0.4-design.md`](../specs/2026-06-05-docs-sync-0.4-design.md). Read the spec for the "why" behind each change.

---

## File structure

**Modified files (5):**
- `README.md`
- `docs/index.md`
- `docs/dev/contributing.md`
- `mkdocs.yml`
- `planning/engineering.md`

No new files. No deletions.

**Commit cadence:** one commit per file (six commits total including the branch-setup verify). Per-task commits keep diff review per-file.

---

## Task 1: Branch setup + README.md

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Ensure local `main` is fully pushed, then branch off**

The spec commit was made directly on `main` earlier. Verify it's pushed before branching so the new PR diff only contains docs changes:

```bash
git checkout main && git status
git push origin main 2>&1 | tail -3
git checkout -b docs/sync-0.4
```

If `git push origin main` reports "Everything up-to-date", continue. If it pushes one commit (the spec), that's expected.

- [ ] **Step 2: Read the current README to confirm line targets**

```bash
cat README.md
```

Confirm the file matches what the spec expected (status line at L12, dead link at L45, etc.). If line numbers have drifted, locate the target text instead.

- [ ] **Step 3: Apply Status-line edit**

Replace:
```markdown
> **Status:** Pre-1.0 (0.3.0). Public API is subject to change between minor releases until v1.0. Resilience middleware (retry / timeout / bulkhead), streaming, and observability are not yet shipped.
```
With:
```markdown
> **Status:** Pre-1.0. Public API is subject to change between minor releases until v1.0. Streaming and observability are not yet shipped.
```

- [ ] **Step 4: Apply Project-description edit**

Find this paragraph (currently around L9):
```markdown
`httpware` is a thin opinionated wrapper around `httpx2`. It re-exports `httpx2.Request`/`httpx2.Response`, adds a middleware chain composed at client construction, supports opt-in typed response decoding (pydantic and msgspec are both extras), and raises a status-keyed exception tree automatically on 4xx/5xx.
```

Append (do not replace) one sentence so the paragraph becomes:
```markdown
`httpware` is a thin opinionated wrapper around `httpx2`. It re-exports `httpx2.Request`/`httpx2.Response`, adds a middleware chain composed at client construction, supports opt-in typed response decoding (pydantic and msgspec are both extras), and raises a status-keyed exception tree automatically on 4xx/5xx. It also ships a small resilience suite — `Retry` middleware with a Finagle-style `RetryBudget`, plus a `Bulkhead` concurrency limiter — under `httpware.middleware.resilience`.
```

- [ ] **Step 5: Add Resilience snippet + Errors section to Quickstart**

Find the existing Quickstart code block (ends with `print(user.name)`). Immediately after the closing triple-backticks of that block, insert this new content (preserving a blank line between the closing fence and the new H3):

```markdown

### With resilience middleware

Compose resilience middleware at construction; `Bulkhead` goes outside `Retry` so one slot covers all retry attempts.

```python
from httpware import AsyncClient, Bulkhead, Retry


async def main() -> None:
    async with AsyncClient(
        base_url="https://api.example.com",
        middleware=[
            Bulkhead(max_concurrent=10),  # cap total in-flight
            Retry(),                       # default: 3 attempts, full-jitter backoff
        ],
    ) as client:
        user = await client.get("/users/1", response_model=User)
```

## Errors

All 4xx/5xx responses raise typed exceptions automatically: `NotFoundError`, `ServiceUnavailableError`, `RateLimitedError`, etc. — all subclasses of `httpware.StatusError`. Transport-layer transient failures raise `NetworkError`; the resilience middleware raise `RetryBudgetExhaustedError` and `BulkheadFullError`. Everything inherits `httpware.ClientError`.
```

- [ ] **Step 6: Replace the dead Documentation link**

Find:
```markdown
## 📚 [Documentation](https://httpware.readthedocs.io)
```

Replace with:
```markdown
## 📝 [Release notes](https://github.com/modern-python/httpware/releases)
```

- [ ] **Step 7: Sanity-check the file**

```bash
cat README.md
```

Read through end-to-end. Make sure:
- Status line is on a single line, no version number
- Project description ends with the new "It also ships..." sentence
- "Quickstart" section now has TWO code blocks (the original + the new "With resilience middleware" subsection)
- "Errors" section appears between the resilience snippet and the link section
- The Documentation link is gone; Release notes link replaces it

- [ ] **Step 8: Lint**

```bash
just lint
```

Expected: clean. (eof-fixer + ruff format may normalize trailing whitespace in the markdown; that's fine.)

- [ ] **Step 9: Commit**

```bash
git add README.md
git commit -m "docs(readme): sync with shipped 0.4 features

- Drop the '0.3.0' version from the status line (pyproject is source of truth)
- Drop the now-false 'retry / timeout / bulkhead not yet shipped' claim
- Mention the resilience suite (Retry + RetryBudget, Bulkhead) in the
  project description
- Add a 'With resilience middleware' Quickstart subsection showing the
  recommended [Bulkhead, Retry] ordering
- Add an 'Errors' section so users know StatusError / NetworkError /
  RetryBudgetExhaustedError / BulkheadFullError exist
- Replace the dead readthedocs.io link with the GH Releases page"
```

---

## Task 2: docs/index.md

**Files:**
- Modify: `docs/index.md`

- [ ] **Step 1: Read current state**

```bash
cat docs/index.md
```

- [ ] **Step 2: Replace the Status line**

Replace:
```markdown
> **Status:** Pre-1.0 (0.1.0 alpha). Public API is subject to change between minor releases until v1.0.
```
With:
```markdown
> **Status:** Pre-1.0. Public API is subject to change between minor releases until v1.0. Streaming and observability are not yet shipped.
```

- [ ] **Step 3: Rewrite the project description paragraph**

Replace this paragraph (currently L3):
```markdown
A Python async HTTP client framework for building resilient service clients. `httpware` owns the abstraction layer above the underlying HTTP client (`httpx2` by default); consumers never import the transport directly.
```
With:
```markdown
A Python async HTTP client framework for building resilient service clients. `httpware` is a thin opinionated wrapper around `httpx2` — it re-exports `httpx2.Request`/`httpx2.Response` as the public request/response surface, adds a middleware chain (with a built-in resilience suite: `Retry` + `RetryBudget`, `Bulkhead`), opt-in typed response decoding, and a status-keyed exception tree raised automatically on 4xx/5xx.
```

Rationale (for the implementer): the original wording dates from before the v0.2 thin-wrapper pivot. v0.2 explicitly walked back the "owns the abstraction layer" framing and made `httpx2.Request`/`httpx2.Response` part of the public surface. Continuing to claim "consumers never import the transport directly" is no longer true.

- [ ] **Step 4: Expand the Install section's optional extras**

Find:
```markdown
Optional extras:

```bash
pip install httpware[msgspec]    # MsgspecDecoder
```
```

Replace with:
```markdown
Optional extras:

```bash
pip install httpware[pydantic]   # PydanticDecoder (the default decoder path)
pip install httpware[msgspec]    # MsgspecDecoder
```
```

(The `pydantic` extra was added in 0.3.0; the docs/index.md only mentioned `msgspec`.)

- [ ] **Step 5: Add a "With resilience middleware" subsection + Errors section**

Find the existing First-request code block (ends with `asyncio.run(main())`). Immediately after the closing triple-backticks, insert this new content (preserving a blank line between the closing fence and the new H3):

```markdown

### With resilience middleware

Compose resilience middleware at construction; `Bulkhead` goes outside `Retry` so one slot covers all retry attempts.

```python
from httpware import AsyncClient, Bulkhead, Retry


async def main() -> None:
    async with AsyncClient(
        base_url="https://api.example.com",
        middleware=[
            Bulkhead(max_concurrent=10),  # cap total in-flight
            Retry(),                       # default: 3 attempts, full-jitter backoff
        ],
    ) as client:
        user = await client.get("/users/1", response_model=User)
```

## Errors

All 4xx/5xx responses raise typed exceptions automatically: `NotFoundError`, `ServiceUnavailableError`, `RateLimitedError`, etc. — all subclasses of `httpware.StatusError`. Transport-layer transient failures raise `NetworkError`; the resilience middleware raise `RetryBudgetExhaustedError` and `BulkheadFullError`. Everything inherits `httpware.ClientError`.
```

- [ ] **Step 6: Fix the "Where to go next" links**

Replace the existing bulleted list:
```markdown
- **[Engineering Notes](dev/engineering.md)** — design invariants, the five protocol seams, exception contract, module layout, testing patterns, optional-extras pattern.
- **[Contributing](dev/contributing.md)** — setup, conventions, workflow.
```
With:
```markdown
- **[Engineering Notes](https://github.com/modern-python/httpware/blob/main/planning/engineering.md)** — design invariants, the three protocol seams, exception contract, module layout, testing patterns, optional-extras pattern. Lives in the repo at `planning/engineering.md`.
- **[Contributing](dev/contributing.md)** — setup, conventions, workflow.
- **[Release notes](https://github.com/modern-python/httpware/releases)** — per-version changelogs.
```

Notes for the implementer:
- "five protocol seams" → "three protocol seams" — the engineering doc was updated in the v0.2 pivot (5 seams collapsed to 3). The index.md text predates that update.
- The link uses an absolute GH URL (not a relative `../planning/engineering.md`) because mkdocs only indexes files under `docs/`; a relative link out of `docs/` would 404 in the rendered site.

- [ ] **Step 7: Sanity-check the file**

```bash
cat docs/index.md
```

Read end-to-end. Make sure:
- Status line is single, version-number-free
- Project description reads as the new v0.2+ wording
- Install block shows both `[pydantic]` and `[msgspec]`
- "First request" code block is followed by the "With resilience middleware" subsection
- "Errors" section appears between the resilience snippet and "Where to go next"
- "Where to go next" has three items: Engineering Notes (GH URL), Contributing (relative), Release notes (GH URL)

- [ ] **Step 8: Lint**

```bash
just lint
```

Expected: clean.

- [ ] **Step 9: Commit**

```bash
git add docs/index.md
git commit -m "docs(index): sync with shipped 0.4 features

- Drop '0.1.0 alpha' from the status line
- Rewrite the project description (pre-v0.2 wording claimed 'owns the
  abstraction layer / consumers never import the transport' — both
  walked back in v0.2)
- Add the pydantic extra to the install block (was added in 0.3.0)
- Add a 'With resilience middleware' subsection mirroring the README
- Add an 'Errors' section
- Fix the dead 'Engineering Notes' link (target file doesn't exist in
  docs/ tree; point to GH URL of planning/engineering.md instead)
- Fix the now-incorrect 'five protocol seams' claim (v0.2 collapsed to three)
- Add a Release notes link"
```

---

## Task 3: docs/dev/contributing.md

**Files:**
- Modify: `docs/dev/contributing.md`

- [ ] **Step 1: Read current state**

```bash
cat docs/dev/contributing.md
```

- [ ] **Step 2: Update the Architecture invariants list**

Find the bulleted list under `## Architecture invariants` (currently lines 32-38):
```markdown
These are enforced by CI grep gates. Do not break them in pull requests:

- No `import httpx2` outside `src/httpware/transports/httpx2.py`.
- No `httpx2._*` (private API) usage anywhere in the library.
- No `from __future__ import annotations`.
- No `print()` calls.
- No `logging.basicConfig()` or bare `logging.getLogger()`.
```

Replace with:
```markdown
These are enforced by CI grep gates. Do not break them in pull requests:

- No `httpx2._*` (private API) usage anywhere in the library.
- No `from __future__ import annotations`.
- No `print()` calls.
- No `logging.basicConfig()` or bare `logging.getLogger()`.
- Type suppressions use `# ty: ignore[<rule>]`, never `# type: ignore` or `# mypy: ignore`.
```

Two changes:
- **Removed**: the first bullet (`No import httpx2 outside transports/httpx2.py`) — retired in v0.2 (per engineering.md §2: *"The 0.1.0 'no httpx2 leakage outside transports/httpx2.py' invariant is retired in v0.2."*). The `transports/` directory doesn't exist anymore.
- **Added** (last bullet): the `# ty: ignore[<rule>]` rule. Already in CLAUDE.md and engineering.md §2 as a current CI-enforced invariant; was missing from this contributor-facing list.

- [ ] **Step 3: Sanity-check**

```bash
cat docs/dev/contributing.md
```

Read the Architecture invariants list. Make sure:
- Bullet about `transports/httpx2.py` is gone
- New bullet about `# ty: ignore[<rule>]` is present
- Other bullets unchanged

- [ ] **Step 4: Lint**

```bash
just lint
```

- [ ] **Step 5: Commit**

```bash
git add docs/dev/contributing.md
git commit -m "docs(contributing): drop retired invariant + add ty-suppression rule

- Remove 'No import httpx2 outside transports/httpx2.py' — retired in
  the v0.2 thin-wrapper pivot; transports/ directory no longer exists.
  Continuing to list this rule misleads contributors.
- Add 'Type suppressions use # ty: ignore[<rule>]' — current
  CI-enforced invariant that was missing from this list."
```

---

## Task 4: mkdocs.yml

**Files:**
- Modify: `mkdocs.yml`

- [ ] **Step 1: Read current state**

```bash
cat mkdocs.yml
```

- [ ] **Step 2: Drop the dead nav entry**

Find the `nav:` block:
```yaml
nav:
  - Quick-Start: index.md
  - Development:
      - Engineering Notes: dev/engineering.md
      - Contributing: dev/contributing.md
```

Replace with:
```yaml
nav:
  - Quick-Start: index.md
  - Development:
      - Contributing: dev/contributing.md
```

Rationale: `dev/engineering.md` doesn't exist (the live file is `planning/engineering.md`). `mkdocs build --strict` reports "A reference to 'dev/engineering.md' is included in the 'nav' configuration, which is not found in the documentation files." This drops the broken entry. The Engineering Notes are reachable via the GH URL added in `docs/index.md` (Task 2).

`site_url: https://httpware.readthedocs.io/` is **intentionally left untouched** — fixing it is project-tree-hygiene unrelated to this sync pass.

- [ ] **Step 3: Verify mkdocs build is now clean**

```bash
uv run --with mkdocs --with mkdocs-material mkdocs build --strict 2>&1 | tail -10
```

Expected: build completes without warnings. (Before this task: 2 warnings about `dev/engineering.md`. After Tasks 2 + 4: 0 warnings. Task 2 fixed the inline link; Task 4 fixed the nav reference.)

If the output still shows warnings, the most likely cause is Task 2 left an inline link to `dev/engineering.md` somewhere. Re-check `docs/index.md`.

- [ ] **Step 4: Cleanup the generated site/ directory**

`mkdocs build` creates a `site/` directory. It's gitignored, but remove it to avoid clutter:

```bash
rm -rf site/
```

- [ ] **Step 5: Lint**

```bash
just lint
```

- [ ] **Step 6: Commit**

```bash
git add mkdocs.yml
git commit -m "docs(mkdocs): drop dead nav entry for dev/engineering.md

The file doesn't exist (the live engineering reference is
planning/engineering.md). mkdocs build --strict was emitting a
'file referenced in nav not found' warning. Drop the broken entry;
docs/index.md now links to the GH URL of planning/engineering.md.

site_url left as-is (fictional RTD URL is unrelated project hygiene
to be addressed separately)."
```

---

## Task 5: planning/engineering.md

**Files:**
- Modify: `planning/engineering.md`

- [ ] **Step 1: Read current state**

```bash
cat planning/engineering.md
```

- [ ] **Step 2: Append a resilience-suite sentence to §1 Project intent**

Find the §1 first paragraph (currently around L7). Append one sentence so the paragraph ends with the new content:

Current ending: `... callers can supply an explicit \`decoder=\` argument to escape the default.`

New ending: `... callers can supply an explicit \`decoder=\` argument to escape the default. As of 0.4.0, the package ships a small resilience suite under \`httpware.middleware.resilience\` — a \`Retry\` middleware with a Finagle-style \`RetryBudget\`, plus a \`Bulkhead\` concurrency limiter — composed via the standard middleware chain.`

- [ ] **Step 3: Refresh §5 Module layout**

Find the existing tree block:
````markdown
```text
src/httpware/
├── __init__.py            # public exports
├── py.typed
├── client.py              # AsyncClient
├── errors.py              # status-keyed exception tree (response: httpx2.Response)
├── middleware/
│   ├── __init__.py        # Middleware protocol, Next type, @before_request/@after_response/@on_error
│   └── chain.py           # compose(middleware, terminal) -> Next
├── decoders/
│   ├── __init__.py        # ResponseDecoder protocol
│   ├── pydantic.py        # PydanticDecoder (extra: pydantic)
│   └── msgspec.py         # MsgspecDecoder (extra: msgspec)
└── _internal/
    └── import_checker.py  # is_msgspec_installed, is_pydantic_installed
```
````

Replace with:
````markdown
```text
src/httpware/
├── __init__.py            # public exports
├── py.typed
├── client.py              # AsyncClient
├── errors.py              # status-keyed exception tree + NetworkError + RetryBudgetExhaustedError + BulkheadFullError
├── middleware/
│   ├── __init__.py        # Middleware protocol, Next type, @before_request/@after_response/@on_error
│   ├── chain.py           # compose(middleware, terminal) -> Next
│   └── resilience/
│       ├── __init__.py    # re-exports Bulkhead, Retry, RetryBudget
│       ├── bulkhead.py    # Bulkhead middleware (concurrency limiter)
│       ├── budget.py      # RetryBudget (Finagle-style token bucket)
│       ├── retry.py       # Retry middleware
│       └── _backoff.py    # full-jitter exponential backoff helper (private)
├── decoders/
│   ├── __init__.py        # ResponseDecoder protocol
│   ├── pydantic.py        # PydanticDecoder (extra: pydantic)
│   └── msgspec.py         # MsgspecDecoder (extra: msgspec)
└── _internal/
    └── import_checker.py  # is_msgspec_installed, is_pydantic_installed
```
````

Two changes:
- `errors.py` comment extended to mention the new exception subclasses
- New `resilience/` block under `middleware/` showing all four modules

- [ ] **Step 4: Sanity-check**

```bash
cat planning/engineering.md
```

Read §1 and §5. Make sure:
- §1 paragraph ends with the new "As of 0.4.0..." sentence
- §5 tree includes the resilience/ block with bulkhead.py, budget.py, retry.py, _backoff.py
- §5 errors.py comment mentions NetworkError + RetryBudgetExhaustedError + BulkheadFullError

- [ ] **Step 5: Lint**

```bash
just lint
```

- [ ] **Step 6: Commit**

```bash
git add planning/engineering.md
git commit -m "docs(engineering): §1 resilience suite + §5 module-layout refresh

- §1: append a sentence noting the resilience suite ships in 0.4
- §5: add middleware/resilience/ subpackage (bulkhead, budget, retry,
  _backoff) to the module tree; extend errors.py comment to mention
  NetworkError + RetryBudgetExhaustedError + BulkheadFullError"
```

---

## Task 6: Final verification + push

**Files:** none modified; verification only.

- [ ] **Step 1: Full lint**

```bash
just lint-ci
```

Expected: clean. (`lint-ci` is the non-fixing variant; if it complains, run `just lint` once locally and re-stage any fixes.)

- [ ] **Step 2: Full test suite**

```bash
just test
```

Expected: 209 tests pass, 100% coverage. No source changed so nothing should regress.

- [ ] **Step 3: mkdocs strict build**

```bash
uv run --with mkdocs --with mkdocs-material mkdocs build --strict 2>&1 | tail -10
```

Expected: build completes with **0 warnings**. Before this PR there were 2 warnings about `dev/engineering.md`; Tasks 2 + 4 should have resolved both.

If warnings remain, investigate before pushing.

- [ ] **Step 4: Cleanup**

```bash
rm -rf site/
git status
```

`site/` should be gone; `git status` should show "clean — nothing to commit".

- [ ] **Step 5: Review the branch diff one last time**

```bash
git log --oneline main..HEAD
git diff main..HEAD --stat
```

Expected: 5 commits, 5 files changed, all under the limits below:

```
README.md                                 |  ~25 insertions
docs/index.md                             |  ~25 insertions, ~5 deletions
docs/dev/contributing.md                  |  ~2 insertions, ~1 deletion
mkdocs.yml                                |  ~1 deletion
planning/engineering.md                   |  ~10 insertions, ~1 deletion
```

(Numbers are approximate — eof-fixer / ruff format may add/remove trailing whitespace.)

- [ ] **Step 6: Push the branch**

```bash
git push -u origin docs/sync-0.4
```

DO NOT open the PR yet — leave that to the `finishing-a-development-branch` skill.

---

## Out of scope for this plan (per the spec)

These items are deliberately deferred. Do NOT do them in this PR:

- **No tutorial / extension-slot walkthrough.** The original 3-6 framing was re-scoped during brainstorming.
- **No moving `planning/engineering.md` into `docs/dev/`.** Dead link is fixed by GH URL.
- **No `pyproject.toml` version bump.** Lives in the next PR (release prep).
- **No `mkdocs.yml` `site_url` fix.** Project-tree hygiene unrelated to this sync.
- **No CLAUDE.md changes.** Contributor-facing.
- **No module-docstring rewrites.** Already current.
- **No new `docs/` files.** Just edits to existing ones.

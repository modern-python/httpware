---
story_key: 1-1-project-scaffold-and-tooling
epic: 1
story: 1
title: Project scaffold and tooling
status: done
created: 2026-05-12
completed: 2026-05-13
input_documents:
  - docs/prd.md
  - docs/architecture.md
  - docs/epics.md
---

# Story 1.1: Project scaffold and tooling

## Story

**As a** `httpware` maintainer,
**I want** a fully-configured project skeleton with the org's conventions,
**So that** subsequent stories can implement library code without fighting tooling.

## Acceptance Criteria

**AC1.** **Given** a fresh checkout of a new GitHub repo at `modern-python/httpware`, **When** I run `uv init --lib httpware` followed by the org-convention port from `modern-python/modern-di`, **Then** the repo has `src/httpware/__init__.py`, `src/httpware/py.typed`, and a `pyproject.toml` declaring `httpx2>=2.0.0,<3.0` and `pydantic>=2.0,<3.0` as dependencies.

**AC2.** **And** extras `[msgspec]`, `[otel]`, `[niquests]`, `[all]` are declared.

**AC3.** **And** dev/lint dep groups match `modern-di` (pytest, pytest-cov, pytest-asyncio, pytest-repeat, pytest-benchmark; ruff, ty, eof-fixer, typing-extensions); plus `hypothesis` in dev for property-based tests.

**AC4.** **And** `[tool.ruff]`, `[tool.pytest.ini_options]` match `modern-di` with `target-version = "py311"`.

**AC5.** **And** root files exist: `Justfile`, `LICENSE` (MIT), `SECURITY.md`, `CONTRIBUTING.md`, `CHANGELOG.md`, `CLAUDE.md`, `context7.json`, `.gitignore`.

**AC6.** **And** `.github/workflows/ci.yml` runs `ruff check`, `ty`, `pytest --cov` on Python 3.11–3.14.

**AC7.** **And** `uv build` produces a wheel and `pip install dist/*.whl` succeeds in a clean venv (smoke-import: `python -c "import httpware"` exits 0).

## Tasks/Subtasks

- [x] **Task 1: Initialize uv library scaffold**
  - [x] 1.1: Run `uv init --lib` in `/Users/kevinsmith/src/pypi/httpware/`
  - [x] 1.2: Verify `src/httpware/__init__.py` exists
  - [x] 1.3: Add `src/httpware/py.typed` zero-byte marker (auto-created by `uv init --lib`)

- [x] **Task 2: Configure pyproject.toml**
  - [x] 2.1: Set `[project]` metadata (name, description, authors, requires-python>=3.11, license=MIT, classifiers for Python 3.11-3.14, `Typing :: Typed`)
  - [x] 2.2: Declare main dependencies: `httpx2>=2.0.0,<3.0` (tightened from `b1` after smoke install verified GA is on PyPI), `pydantic>=2.0,<3.0`
  - [x] 2.3: Declare extras: `[project.optional-dependencies]` for `msgspec`, `otel`, `niquests`, `all`
  - [x] 2.4: Configure `[build-system]` with `uv_build>=0.11,<0.12` (upper-bounded per uv's recommendation)
  - [x] 2.5: Configure `[tool.uv.build-backend]` (module-name = "httpware", module-root = "src")
  - [x] 2.6: Add `[project.urls]` for repository and docs

- [x] **Task 3: Port modern-di conventions to pyproject.toml**
  - [x] 3.1: Fetched live `modern-python/modern-di/pyproject.toml`, `Justfile`, `.github/workflows/{ci,publish}.yml`, `.gitignore`, `CLAUDE.md`, `context7.json` via `gh api`
  - [x] 3.2: Copied `[tool.ruff]` (line-length=120, target-version="py311", fix=true, unsafe-fixes=true) and `[tool.ruff.lint]` (select=ALL, ignore set: D1, S101, TCH, FBT, D203, D213, COM812, ISC001)
  - [x] 3.3: Copied `[tool.pytest.ini_options]` (asyncio_mode="auto", asyncio_default_fixture_loop_scope="function"); adjusted `pythonpath` to `["src"]` and `--cov` to `src/httpware` for src/-layout
  - [x] 3.4: Copied `[tool.coverage]` config
  - [x] 3.5: Added dev dep group: pytest, pytest-cov, pytest-asyncio, pytest-repeat, pytest-benchmark, hypothesis
  - [x] 3.6: Added lint dep group: ruff, ty, eof-fixer, typing-extensions

- [x] **Task 4: Add root configuration files**
  - [x] 4.1: `LICENSE` — MIT, copyright "Modern Python contributors"
  - [x] 4.2: `Justfile` with `install`, `lint`, `lint-ci`, `test`, `test-branch`, `publish` recipes (verbatim from modern-di)
  - [x] 4.3: `SECURITY.md` documenting GitHub Security Advisories disclosure channel and 90-day private-disclosure window (per NFR10)
  - [x] 4.4: `CONTRIBUTING.md` — development workflow + architecture invariants
  - [x] 4.5: `CHANGELOG.md` — Keep-a-Changelog format with `Unreleased` section populated with scaffold-story changes
  - [x] 4.6: `CLAUDE.md` — AI-agent guidance pointing at base-client/docs/{prd,architecture,epics}.md, CI-enforced invariants, code conventions, module layout, 5 protocol seams
  - [x] 4.7: `context7.json` — minimal config matching modern-di style (URL only; public_key TBD)
  - [x] 4.8: `.gitignore` — Python standard ignores from modern-di + `uv.lock` in ignore list (library convention)

- [x] **Task 5: GitHub Actions CI workflow**
  - [x] 5.1: `.github/workflows/ci.yml` runs ruff lint (via `just lint-ci`), pytest with coverage upload to Codecov
  - [x] 5.2: Python matrix: 3.11, 3.12, 3.13, 3.14 (matches our floor; modern-di had 3.10 included but our PRD raised the floor)
  - [x] 5.3: Uses `astral-sh/setup-uv@v3` + `extractions/setup-just@v2` (matches modern-di)

- [x] **Task 6: Verify build and install**
  - [x] 6.1: `uv build` produced `dist/httpware-0-py3-none-any.whl` (3.0K) and `dist/httpware-0.tar.gz` (3.0K)
  - [x] 6.2: Installed wheel into clean tempdir venv via `uv venv --python 3.11` + `uv pip install`; 12 packages resolved (httpware + httpx2==2.0.0 + pydantic==2.13.4 + transitive deps)
  - [x] 6.3: Smoke-import: `python -c "import httpware"` exits 0; `__all__ == []`
  - [x] 6.4: `ruff format`, `ruff check`, `ty check` all pass on empty `src/httpware/__init__.py`; `pytest` collected 0 tests (expected — scaffold story has no library code yet)
  - [x] 6.5: Initialized git repo (auto-created by `uv init --lib`), staged all scaffold files, committed as `fe4df95 chore: initial project scaffold (Story 1.1)` on `main`

## Dev Notes

**Architecture references** (all in `docs/`):

- `architecture.md` § Starter Template Evaluation — selected starter is `uv init --lib` + port from `modern-python/modern-di`
- `architecture.md` § Project Structure & Boundaries — full directory tree and root-file enumeration
- `architecture.md` § Implementation Patterns — naming, structure, type-hint style, etc.
- `prd.md` § Developer Tool Specific Requirements — language matrix, install methods, IDE integration

**Key design decisions affecting this story:**

- **Build backend:** `uv_build` (PEP 517 compliant). `[build-system] requires = ["uv_build"]`, `build-backend = "uv_build"`.
- **Layout:** src/-layout. `[tool.uv.build-backend] module-name = "httpware"`, `module-root = "src"`. (modern-di uses flat layout; we use src/ because it's the safer default for new repos and `uv init --lib` defaults to it.)
- **Type checker:** `ty` (Astral), NOT mypy. Suppression comments are `# ty: ignore[<rule>]`.
- **Python floor:** 3.11+ (`TaskGroup`, `except*`).
- **License:** MIT (matches modern-di and modern-python org default).

**Reference URLs to fetch live during implementation:**

- `https://api.github.com/repos/modern-python/modern-di/contents/pyproject.toml` — authoritative ruff/pytest/coverage config
- `https://api.github.com/repos/modern-python/modern-di/contents/Justfile` — recipes to port
- `https://api.github.com/repos/modern-python/modern-di/contents/.github/workflows` — CI workflow structure

**No tests required for this story** beyond the build-verify smoke checks. Tests for library functionality begin in Story 1.2.

**Definition of Done for this story:**

- All AC criteria pass
- `uv build` succeeds
- Clean-venv install + smoke import works
- `ruff check`, `ty check` pass on empty src/ tree (the package exists but contains no code yet, so these should pass trivially)
- Git repo initialized with first commit

## Dev Agent Record

### Implementation Plan

1. **Initialize via `uv init --lib`** in the empty `/Users/kevinsmith/src/pypi/httpware/` directory — single command sets up `src/httpware/__init__.py`, `py.typed`, minimal `pyproject.toml`, `.gitignore`, `.python-version`, `README.md`, and a fresh `.git/` repo.
2. **Fetch the authoritative `modern-python/modern-di` config files** via `gh api` (pyproject.toml, Justfile, .github/workflows/{ci,publish}.yml, .gitignore, CLAUDE.md, context7.json) and use them as the verbatim source for org conventions, adjusting only:
   - Python floor: `>=3.10,<4` → `>=3.11,<4` (per PRD Story 1.1 AC and architecture decision to use `TaskGroup`/`except*`)
   - ruff `target-version`: `py310` → `py311`
   - Layout: flat (`modern_di/`) → src/ (`src/httpware/`); set `[tool.uv.build-backend] module-root = "src"`
   - pytest `pythonpath`: `["."]` → `["src"]`; `--cov` source: `.` → `src/httpware`
   - Drop Python 3.10 from CI matrix
3. **Override `__init__.py`** content from the default `def hello()` stub to a docstring + empty `__all__`.
4. **Override `.python-version`** from `3.14` (uv's default) to `3.11` (our declared floor).
5. **Add new content not in modern-di**: dependencies (`httpx2>=2.0,<3.0`, `pydantic>=2.0,<3.0`), install extras, `LICENSE`, `SECURITY.md`, `CONTRIBUTING.md`, `CHANGELOG.md`, populated `README.md`.
6. **Validate**: `uv sync` → `ruff format` → `ruff check` → `ty check` → `pytest` → `uv build` → clean-venv install + smoke import.
7. **Commit**: stage everything except gitignored files (`.python-version`, `.venv`, `uv.lock`), single initial commit on `main`.

### Debug Log

- `uv init --lib` auto-created `py.typed` (good — no need to add manually as originally planned in subtask 1.3).
- Initial `httpx2>=2.0.0b1,<3.0` constraint (from the original AC1) caused `uv pip install` (without `--prerelease=allow`) to skip httpx2 in clean-venv smoke test. Tightened to `>=2.0.0,<3.0` after verifying `httpx2==2.0.0` GA was published on PyPI on 2026-05-12. AC1, base-client/docs/{prd,architecture,epics}.md, and this story file have all been updated in a follow-up commit to match the implemented constraint.
- `uv build` warned about `[build-system] requires = ["uv_build"]` lacking an upper bound. Pinned to `>=0.11,<0.12` to silence the warning and prevent future breakage when uv_build 0.12 ships.
- `git add` initially refused `.python-version` (in `.gitignore` from modern-di's convention); kept it untracked. Same for `uv.lock` (added to `.gitignore` after initial commit attempt staged it).

### Completion Notes

**AC verification — all 7 satisfied:**

- **AC1** ✓ `src/httpware/__init__.py` and `src/httpware/py.typed` exist; `pyproject.toml` declares `httpx2>=2.0.0,<3.0` and `pydantic>=2.0,<3.0`.
- **AC2** ✓ Extras `[msgspec]`, `[otel]`, `[niquests]`, `[all]` all declared in `[project.optional-dependencies]`.
- **AC3** ✓ Dev group: pytest, pytest-cov, pytest-asyncio, pytest-repeat, pytest-benchmark, hypothesis. Lint group: ruff, ty, eof-fixer, typing-extensions. Match modern-di + hypothesis addition.
- **AC4** ✓ `[tool.ruff]` and `[tool.pytest.ini_options]` ported verbatim from modern-di with `target-version = "py311"` (raised from `py310`).
- **AC5** ✓ All eight root files exist: Justfile, LICENSE, SECURITY.md, CONTRIBUTING.md, CHANGELOG.md, CLAUDE.md, context7.json, .gitignore.
- **AC6** ✓ `.github/workflows/ci.yml` runs ruff/ty/pytest with coverage upload on Python 3.11–3.14 matrix (3.10 dropped per our floor; 3.14 included since GA is on `actions/setup-python`).
- **AC7** ✓ `uv build` produced wheel+sdist; clean-venv install of the wheel resolved 12 packages (httpware + httpx2 2.0.0 + pydantic 2.13.4 + transitive); `python -c "import httpware"` exited 0 with `__all__ == []`.

**Definition of Done:**

- All Tasks/Subtasks marked `[x]`
- All 7 AC pass
- `ruff format` + `ruff check` + `ty check` + `pytest` all pass locally
- `uv build` succeeds; wheel installs and imports cleanly in a fresh venv
- File List complete; Change Log updated
- Initial commit on `main` (`fe4df95`)

**Deviations from PRD/Architecture docs (worth noting for future cleanup):**

- Original AC1 specified `httpx2>=2.0.0b1,<3.0` (written when only the beta was published). Story tightened to `>=2.0.0,<3.0` after verifying GA shipped on PyPI 2026-05-12; planning artifacts (PRD, Architecture, Epics, AC1) updated to match in a follow-up commit. Deviation resolved.
- `module-name = "httpware"` and `module-root = "src"` (src/ layout) chosen over modern-di's flat layout, per architecture decision §Starter Template (rationale: src/ layout prevents test code from accidentally importing local source).

**Tests written:** None — scaffold story has no library code. Tests begin in Story 1.2.

## File List

Files added (14 total):

- `.github/workflows/ci.yml` — CI workflow (ruff/ty/pytest, Python 3.11-3.14 matrix)
- `.gitignore` — modern-di convention + project-specific ignores
- `CHANGELOG.md` — Keep-a-Changelog format
- `CLAUDE.md` — AI-agent guidance for working in this repo
- `CONTRIBUTING.md` — contributor workflow and architecture invariants
- `Justfile` — install/lint/test/publish recipes (verbatim from modern-di)
- `LICENSE` — MIT
- `README.md` — project overview, install, quickstart, highlights
- `SECURITY.md` — disclosure policy with 90-day window
- `context7.json` — context7 docs index pointer
- `docs/stories/1-1-project-scaffold-and-tooling.md` — this story file
- `pyproject.toml` — full project config (deps, extras, ruff, pytest, coverage, dep groups)
- `src/httpware/__init__.py` — package init with docstring and empty `__all__`
- `src/httpware/py.typed` — zero-byte typing marker

Generated/transient (not committed):

- `.python-version` — gitignored per modern-di convention
- `uv.lock` — gitignored per modern-di convention (library project)
- `.venv/` — gitignored
- `dist/` — gitignored

## Change Log

| Date | Change | Notes |
|---|---|---|
| 2026-05-12 | Story created | Extracted from `base-client/docs/epics.md` Story 1.1; reorganized into tasks/subtasks for dev workflow. |
| 2026-05-13 | Story completed | All 7 AC pass; initial commit `fe4df95` on `main`; lint+typecheck+build+smoke-install verified. |

## Status

`done`

### Review Findings

_Code review run: 2026-05-13. Reviewers: Blind Hunter, Edge Case Hunter, Acceptance Auditor. 6 patches applied, 3 dismissed by maintainer (not errors), 6 deferred, 20 dismissed as noise (2 decision-needed items were resolved → dismissed: `.gitignore plan.md` blacklist is intentional convention; AC6 lint-on-single-version matches modern-di canon and is accepted)._

- [x] [Review][Patch] CHANGELOG declared `httpx2>=2.0.0b1,<3.0` while pyproject shipped `>=2.0.0,<3.0`. [`CHANGELOG.md:13`] — applied
- [x] [Review][Patch] CHANGELOG `[Unreleased]` link was `compare/HEAD...HEAD` — replaced with `commits/main` until first tag. [`CHANGELOG.md:20`] — applied
- [x] [Review][Dismissed] `version = "0"` placeholder. [`pyproject.toml:29`] — dismissed by maintainer, not an error
- [x] [Review][Patch] `[all]` extra refactored to self-reference siblings: `all = ["httpware[msgspec,otel,niquests]"]`. [`pyproject.toml:42-47`] — applied
- [x] [Review][Patch] README "Optional extras" snippet — added `pip install httpware[niquests]`. [`README.md:22-26`] — applied
- [x] [Review][Dismissed] CI `timeout-minutes`. [`.github/workflows/ci.yml:14, 26`] — dismissed by maintainer, not an error
- [x] [Review][Dismissed] CI explicit `permissions:` block. [`.github/workflows/ci.yml:1-12`] — dismissed by maintainer, not an error
- [x] [Review][Patch] Duplicate `--cov` flag — dropped `--cov=src/httpware` from CI invocation; `addopts` is now the single source of `--cov` source. [`.github/workflows/ci.yml:45`] — applied
- [x] [Review][Patch] File List header `15 total` → `14 total`. [`docs/stories/1-1-project-scaffold-and-tooling.md:171`] — applied

- [x] [Review][Defer] Codecov upload fails on fork PRs without `CODECOV_TOKEN`; matches modern-di pattern, accepted tradeoff. [`.github/workflows/ci.yml:46-52`] — deferred, pre-existing
- [x] [Review][Defer] `just publish` does not validate `GITHUB_REF_NAME` / `PYPI_TOKEN`; local invocation could corrupt the version. [`Justfile:25-29`] — deferred, release-flow hygiene
- [x] [Review][Defer] `uv_build>=0.11,<0.12` is a one-minor-version window that will expire fast. [`pyproject.toml:54`] — deferred, will bump on release
- [x] [Review][Defer] Python 3.14 in CI matrix; httpx2 / pydantic / uv_build wheels may not yet exist on 3.14, causing the matrix entry to fail. [`.github/workflows/ci.yml:30-33`] — deferred, wait-and-see
- [x] [Review][Defer] `[tool.ruff.lint] select = ["ALL"]` paired with unpinned `ruff`/`ty` — any new ruff release adds rules and breaks CI overnight. [`pyproject.toml:70-72, 84-85`] — deferred, matches modern-di
- [x] [Review][Defer] No `[test]` extra declared; CI relies on `--all-extras`, so any future heavy extra is pulled into every CI run. [`pyproject.toml:35-47`] — deferred, scope creep concern

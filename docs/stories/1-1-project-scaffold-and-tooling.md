---
story_key: 1-1-project-scaffold-and-tooling
epic: 1
story: 1
title: Project scaffold and tooling
status: in-progress
created: 2026-05-12
input_documents:
  - /Users/kevinsmith/src/pypi/base-client/docs/prd.md
  - /Users/kevinsmith/src/pypi/base-client/docs/architecture.md
  - /Users/kevinsmith/src/pypi/base-client/docs/epics.md
---

# Story 1.1: Project scaffold and tooling

## Story

**As a** `httpware` maintainer,
**I want** a fully-configured project skeleton with the org's conventions,
**So that** subsequent stories can implement library code without fighting tooling.

## Acceptance Criteria

**AC1.** **Given** a fresh checkout of a new GitHub repo at `modern-python/httpware`, **When** I run `uv init --lib httpware` followed by the org-convention port from `modern-python/modern-di`, **Then** the repo has `src/httpware/__init__.py`, `src/httpware/py.typed`, and a `pyproject.toml` declaring `httpx2>=2.0.0b1,<3.0` and `pydantic>=2.0,<3.0` as dependencies.

**AC2.** **And** extras `[msgspec]`, `[otel]`, `[niquests]`, `[all]` are declared.

**AC3.** **And** dev/lint dep groups match `modern-di` (pytest, pytest-cov, pytest-asyncio, pytest-repeat, pytest-benchmark; ruff, ty, eof-fixer, typing-extensions); plus `hypothesis` in dev for property-based tests.

**AC4.** **And** `[tool.ruff]`, `[tool.pytest.ini_options]` match `modern-di` with `target-version = "py311"`.

**AC5.** **And** root files exist: `Justfile`, `LICENSE` (MIT), `SECURITY.md`, `CONTRIBUTING.md`, `CHANGELOG.md`, `CLAUDE.md`, `context7.json`, `.gitignore`.

**AC6.** **And** `.github/workflows/ci.yml` runs `ruff check`, `ty`, `pytest --cov` on Python 3.11–3.14.

**AC7.** **And** `uv build` produces a wheel and `pip install dist/*.whl` succeeds in a clean venv (smoke-import: `python -c "import httpware"` exits 0).

## Tasks/Subtasks

- [ ] **Task 1: Initialize uv library scaffold**
  - [ ] 1.1: Run `uv init --lib` in `/Users/kevinsmith/src/pypi/httpware/`
  - [ ] 1.2: Verify `src/httpware/__init__.py` exists
  - [ ] 1.3: Add `src/httpware/py.typed` zero-byte marker

- [ ] **Task 2: Configure pyproject.toml**
  - [ ] 2.1: Set `[project]` metadata (name, description, authors, requires-python>=3.11, license=MIT, classifiers for Python 3.11-3.14, `Typing :: Typed`)
  - [ ] 2.2: Declare main dependencies: `httpx2>=2.0.0b1,<3.0`, `pydantic>=2.0,<3.0`
  - [ ] 2.3: Declare extras: `[project.optional-dependencies]` for `msgspec`, `otel`, `niquests`, `all`
  - [ ] 2.4: Configure `[build-system]` with `uv_build`
  - [ ] 2.5: Configure `[tool.uv.build-backend]` (module-name = "httpware", module-root = "src")
  - [ ] 2.6: Add `[project.urls]` for repository and docs

- [ ] **Task 3: Port modern-di conventions to pyproject.toml**
  - [ ] 3.1: Fetch the live `modern-python/modern-di/pyproject.toml` to copy authoritative config sections
  - [ ] 3.2: Copy `[tool.ruff]` (line-length=120, target-version="py311", fix=true, unsafe-fixes=true) and `[tool.ruff.lint]` (select=ALL, ignore set: D1, S101, TCH, FBT, D203, D213, COM812, ISC001)
  - [ ] 3.3: Copy `[tool.pytest.ini_options]` (asyncio_mode="auto", asyncio_default_fixture_loop_scope="function", --cov enabled)
  - [ ] 3.4: Copy `[tool.coverage]` config
  - [ ] 3.5: Add dev dep group: pytest, pytest-cov, pytest-asyncio, pytest-repeat, pytest-benchmark, hypothesis
  - [ ] 3.6: Add lint dep group: ruff, ty, eof-fixer, typing-extensions

- [ ] **Task 4: Add root configuration files**
  - [ ] 4.1: `LICENSE` — MIT, copyright "Modern Python contributors"
  - [ ] 4.2: `Justfile` with `install`, `test`, `lint`, `format`, `release` recipes (port from modern-di)
  - [ ] 4.3: `SECURITY.md` documenting CVE disclosure channel and 90-day private-disclosure window (per NFR10)
  - [ ] 4.4: `CONTRIBUTING.md` — short, points to docs site (placeholder URL until docs live)
  - [ ] 4.5: `CHANGELOG.md` — Keep-a-Changelog format with an `Unreleased` section
  - [ ] 4.6: `CLAUDE.md` — AI-agent guidance (architecture pointers, "use ty: ignore not type: ignore", "no from __future__ import annotations", etc.)
  - [ ] 4.7: `context7.json` — minimal config matching modern-di style
  - [ ] 4.8: `.gitignore` — Python standard ignores plus uv lockfile direction

- [ ] **Task 5: GitHub Actions CI workflow**
  - [ ] 5.1: Create `.github/workflows/ci.yml` running ruff lint, ty type check, pytest --cov
  - [ ] 5.2: Configure Python matrix: 3.11, 3.12, 3.13 (3.14 once GA on actions/setup-python)
  - [ ] 5.3: Use `uv` for env setup (matches modern-di)

- [ ] **Task 6: Verify build and install**
  - [ ] 6.1: Run `uv build` → wheel + sdist produced in `dist/`
  - [ ] 6.2: Install wheel into clean venv via `uv venv` + `uv pip install`
  - [ ] 6.3: Smoke-import: `python -c "import httpware"` exits 0
  - [ ] 6.4: Run `ruff check`, `ty check`, `pytest` locally — all pass (no tests yet; pytest should exit 5 = "no tests collected", treat as pass for scaffold)
  - [ ] 6.5: Initialize git repo with first commit on `main`

## Dev Notes

**Architecture references** (all in `/Users/kevinsmith/src/pypi/base-client/docs/`):

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

To be filled in during Step 5.

### Debug Log

(empty)

### Completion Notes

(to be filled at story completion)

## File List

To be populated as files are created.

## Change Log

| Date | Change | Notes |
|---|---|---|
| 2026-05-12 | Story created | Extracted from `base-client/docs/epics.md` Story 1.1; reorganized into tasks/subtasks for dev workflow. |

## Status

`in-progress`

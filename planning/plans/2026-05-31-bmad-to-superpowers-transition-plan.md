# bmad → superpowers transition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cutover the `httpware` project from bmad to superpowers in a single PR. After merge, all future work runs through the superpowers flow (brainstorming → writing-plans → executing-plans → requesting-code-review).

**Architecture:** Docs-only refactor. Move five large bmad planning files plus the `docs/stories/` directory into `docs/archive/`. Write one new distilled `docs/dev/engineering.md` (~250–350 lines) sourcing content from the archived docs and `CLAUDE.md`. Update `CLAUDE.md` to point at the new structure. Delete `.review-tmp/`. No source code changes.

**Tech Stack:** Markdown only. Git for renames. `just lint` and `just test` for regression verification (they should remain green; the cutover touches no source).

**Branch:** `chore/bmad-to-superpowers-transition` (already exists; the brainstorming spec is the only commit on it as of plan creation).

**Prereqs already satisfied:**
- Story 1-5 merged to `main` (PR #5).
- Branch rebased onto post-1-5 `main`.
- Spec at `planning/specs/2026-05-31-bmad-to-superpowers-transition-design.md` (committed).
- This plan file exists at `planning/plans/2026-05-31-bmad-to-superpowers-transition-plan.md` (untracked until Task 6 stages it).

---

## File Structure

**Files created:**
- `docs/dev/engineering.md` — the distilled doc (~250–350 lines). Single source for design rationale + roadmap.
- `docs/archive/README.md` — ~1 paragraph framing the archive as historical reference.
- `planning/plans/2026-05-31-bmad-to-superpowers-transition-plan.md` — this file.

**Files moved (git mv, preserves history):**
- `docs/prd.md` → `docs/archive/prd.md`
- `docs/architecture.md` → `docs/archive/architecture.md`
- `docs/epics.md` → `docs/archive/epics.md`
- `docs/product-brief-httpware.md` → `docs/archive/product-brief-httpware.md`
- `docs/product-brief-httpware-distillate.md` → `docs/archive/product-brief-httpware-distillate.md`
- `docs/stories/` → `docs/archive/stories/` (entire directory)

**Files modified:**
- `CLAUDE.md` — rewrite the "Project Overview" section and add a one-liner about the per-feature flow. Keep the "Architecture invariants (CI-enforced)", "Commands", "Code conventions", "Module layout", "Protocol seams", "Testing", and "When in doubt" sections verbatim except for archived-path references.

**Files deleted:**
- `.review-tmp/` (entire directory) — bmad code-review artifact dump.

**Files untouched (deliberate):**
- `planning/deferred-work.md` — kept at repo root as the active deferral log.
- All `src/httpware/**`, `tests/**`, `pyproject.toml`, `Justfile`, `.github/**`, `CHANGELOG.md`, `README.md`, `CONTRIBUTING.md`, `SECURITY.md`, `LICENSE` — no source/CI changes.

---

## Task 1: Move bmad artifacts to `docs/archive/`

**Files:**
- Move: `docs/prd.md` → `docs/archive/prd.md`
- Move: `docs/architecture.md` → `docs/archive/architecture.md`
- Move: `docs/epics.md` → `docs/archive/epics.md`
- Move: `docs/product-brief-httpware.md` → `docs/archive/product-brief-httpware.md`
- Move: `docs/product-brief-httpware-distillate.md` → `docs/archive/product-brief-httpware-distillate.md`
- Move: `docs/stories/` → `docs/archive/stories/`

- [ ] **Step 1: Verify branch and working-tree state**

Run: `git branch --show-current && git status --short`
Expected: branch is `chore/bmad-to-superpowers-transition`. Working tree has untracked `planning/plans/2026-05-31-bmad-to-superpowers-transition-plan.md` (this file) and nothing else.

If anything else is dirty, stop and resolve before proceeding.

- [ ] **Step 2: Create the archive directory**

Run: `mkdir -p docs/archive`
Expected: silent success. Verify with `ls -d docs/archive`.

- [ ] **Step 3: Move the five top-level bmad docs with git mv**

Run:
```bash
git mv docs/prd.md docs/archive/prd.md
git mv docs/architecture.md docs/archive/architecture.md
git mv docs/epics.md docs/archive/epics.md
git mv docs/product-brief-httpware.md docs/archive/product-brief-httpware.md
git mv docs/product-brief-httpware-distillate.md docs/archive/product-brief-httpware-distillate.md
```

Expected: each command silent on success.

- [ ] **Step 4: Move the stories directory**

Run: `git mv docs/stories docs/archive/stories`
Expected: silent success.

- [ ] **Step 5: Verify the move**

Run: `git status --short | head -20`
Expected: six rename entries (`R  docs/prd.md -> docs/archive/prd.md` and so on, including the stories directory contents shown as individual renames). Untracked plan file still listed.

Run: `ls docs/`
Expected: `archive/`, `deferred-work.md`, `superpowers/`. (No `prd.md`, `architecture.md`, etc., at the top of `docs/`.)

Run: `ls docs/archive/`
Expected: `architecture.md  epics.md  prd.md  product-brief-httpware-distillate.md  product-brief-httpware.md  stories/`.

---

## Task 2: Write `docs/archive/README.md`

**Files:**
- Create: `docs/archive/README.md`

- [ ] **Step 1: Write the archive README**

Contents:

```markdown
# Archive

This directory contains the bmad-era planning artifacts for `httpware`:

- `prd.md` — 47 functional and 25 non-functional requirements.
- `architecture.md` — twelve architectural decisions, the five protocol seams, full module layout.
- `epics.md` — six epics with 32 stories.
- `product-brief-httpware.md` and `product-brief-httpware-distillate.md` — executive brief and detail pack from the predecessor `community-of-python/base-client` scoping exercise.
- `stories/` — per-story specs (1-1 through 1-5) and the retired `sprint-status.yaml`.

These files are **historical reference, not authoritative**. The load-bearing decisions were distilled into [`../engineering.md`](../engineering.md) on 2026-05-31 when the project switched workflows from bmad to superpowers. Consult these archived files only when you need:

- Original rationale behind a decision (e.g., "why did we choose `httpx2` over `aiohttp`?").
- The specific FR/NFR numbers that a future spec wants to cite (e.g., `archive/prd.md#NFR-12`).
- The Given/When/Then acceptance criteria from a completed story.

For everything else — invariants, seams, module layout, conventions, the remaining roadmap — read `../engineering.md` and `../../CLAUDE.md`.
```

- [ ] **Step 2: Verify it exists**

Run: `wc -l docs/archive/README.md`
Expected: ~18 lines.

---

## Task 3: Write `docs/dev/engineering.md`

This is the largest task. The doc has nine sections (per the spec). Build it section by section. Final length target: 250–350 lines.

**Files:**
- Create: `docs/dev/engineering.md`

**Source material:**
- `CLAUDE.md` — invariants and conventions (current file at repo root).
- `docs/archive/architecture.md` — protocol seams details (lines 198–225 transport, 225–270 middleware, 270–294 validation/decoding), module layout, exception contract context.
- `docs/archive/prd.md` — project intent, optional-extras pattern.
- `docs/archive/stories/sprint-status.yaml` — full backlog for the roadmap section.
- `src/httpware/` — current module tree (post-1.5), needed for accurate Section 5.

- [ ] **Step 1: Write Section 1 — Project intent (3–4 sentences)**

Append to `docs/dev/engineering.md`:

```markdown
# `httpware` engineering notes

This doc is the single distilled reference for `httpware` design rationale, protocol seams, and remaining roadmap. It complements [`../CLAUDE.md`](../CLAUDE.md): `CLAUDE.md` holds AI-enforced invariants and operational commands; this file holds the reasoning and the structural map. Historical planning artifacts live in [`archive/`](./archive/) and are cited only for original rationale.

## 1. Project intent

`httpware` is a Python async HTTP client framework for building resilient service clients. It supersedes `community-of-python/base-client` and ships under the `modern-python` org. The framework owns the abstraction layer above the underlying HTTP client (`httpx2` by default); consumers never import the transport directly.
```

- [ ] **Step 2: Write Section 2 — Architectural invariants (with "why" per item)**

Append:

```markdown
## 2. Architectural invariants (CI-enforced)

These are non-negotiable. CI rejects PRs that violate them. The "why" exists so future contributors can judge edge cases instead of blindly following the rule.

- **No `httpx2` leakage outside `src/httpware/transports/httpx2.py`.** *Why:* the whole point of the framework is to own the abstraction above the underlying client. Any consumer that imports `httpx2` directly defeats the abstraction and pins us to the current transport choice.
- **No `httpx2` private API.** *Why:* private symbols can change between patch releases. We accept the public-API surface as the contract.
- **No `from __future__ import annotations`.** *Why:* Python 3.11+ floor. PEP 604/585 syntax is native; the future-import would only add noise and inconsistency.
- **No `print()`.** *Why:* ruff-enforced. Libraries log; they do not print to stdout. Stray prints leak into consumer applications.
- **No global logging config.** *Why:* `logging.basicConfig()` from a library mutates the consumer's logging tree. We only acquire `logging.getLogger("httpware")` or namespaced child loggers and let consumers configure handlers.
- **Type suppressions use `# ty: ignore[<rule>]`.** *Why:* this project uses `ty`, not `mypy`. `# type: ignore` is silently accepted by `ty` but ambiguous; `# ty: ignore[<rule>]` is checked and rule-specific.
```

- [ ] **Step 3: Write Section 3 — The five protocol seams**

Append:

```markdown
## 3. The five protocol seams

A protocol seam is a documented internal boundary. AI agents and contributors must respect it — never cross a seam except through its protocol.

### Seam 1: `Middleware ↔ Transport`

- **Where:** `src/httpware/middleware/` (chain) ↔ `src/httpware/transports/` (any `Transport` implementation).
- **Contract:** the chain bottom calls `transport.__call__(request) -> Response`.
- **Rule:** middleware never instantiates a transport; the `AsyncClient` injects it at construction.

### Seam 2: `AsyncClient ↔ Middleware`

- **Where:** `src/httpware/client.py` ↔ `src/httpware/middleware/`.
- **Contract:** the middleware chain is composed at `AsyncClient.__init__` and frozen for the client's lifetime.
- **Rule:** mutating the chain after construction is not supported. Per-request middleware is expressed via the `Request` extensions field, not by rebuilding the chain.

### Seam 3: `AsyncClient ↔ ResponseDecoder`

- **Where:** `src/httpware/client.py` ↔ `src/httpware/decoders/`.
- **Contract:** the decoder is invoked when the caller passes `response_model=`. The protocol is `decode(content: bytes, model: type[T]) -> T`.
- **Rule:** the decoder must operate on raw bytes in a single parse pass. Two-pass decoding (`json.loads` then `validate_python`) is rejected — see `archive/architecture.md` Validation & Decoding for rationale.

### Seam 4: `Httpx2Transport ↔ httpx2`

- **Where:** `src/httpware/transports/httpx2.py` is the only file that may import `httpx2`.
- **Contract:** `httpx2` exceptions are mapped to `httpware` exceptions at this seam.
- **Rule:** CI grep checks enforce zero `httpx2` imports outside this file and zero `httpx2._` private references anywhere.

### Seam 5: `httpware ↔ optional extras`

- **Where:** `pyproject.toml` extras (`[project.optional-dependencies]`) ↔ the adapter modules that import them.
- **Contract:** each optional dependency is imported only inside its own dedicated module (e.g., `pydantic` in `decoders/pydantic.py`; `msgspec` in `decoders/msgspec.py` when 1-6 lands; `opentelemetry` in `middleware/observability/otel.py` when 5-4 lands).
- **Rule:** never import an extra at package top-level. The package must import cleanly when the extra is not installed.
```

- [ ] **Step 4: Write Section 4 — Exception contract**

Append:

```markdown
## 4. Exception contract

All `httpware` HTTP exceptions are constructed with **keyword arguments only**. The mandatory fields on every `StatusError` (and its 4xx/5xx subclasses) are:

| Field | Type | Source |
| --- | --- | --- |
| `status` | `int` | response status code |
| `body` | `bytes` | full response body |
| `headers` | `Mapping[str, str]` | lowercased response headers (v0 contract) |
| `json` | `Any \| None` | parsed JSON if `application/json` content-type; else `None` |
| `request_method` | `str` | uppercased request method |
| `request_url` | `str` | request URL, may include userinfo (Redactor sanitizes — Story 5.3) |

The mapping table from `httpx2` errors to `httpware` errors lives at Seam 4 (`src/httpware/transports/httpx2.py`). Status-keyed exceptions are looked up via the `STATUS_TO_EXCEPTION` table in `src/httpware/errors.py`.

Constructing any of these exceptions positionally is a programming error caught by `ty`. The keyword-only signature is enforced via `__init__` definitions, not docstrings.
```

- [ ] **Step 5: Write Section 5 — Module layout**

Read the current `src/httpware/` tree.

Run: `find src/httpware -type d -o -name '*.py' | sort`

Append (verifying tree against actual output):

```markdown
## 5. Module layout

Current tree (post-story-1.5):

```text
src/httpware/
├── __init__.py                       # public exports + __all__
├── py.typed
├── config.py                         # Limits, Timeout, ClientConfig
├── request.py                        # Request + with_* helpers
├── response.py                       # Response (StreamResponse pending in Epic 4)
├── errors.py                         # status-keyed exception hierarchy
├── decoders/
│   ├── __init__.py                   # ResponseDecoder protocol (Seam 3)
│   └── pydantic.py                   # PydanticDecoder adapter
└── transports/
    ├── __init__.py                   # Transport protocol
    └── httpx2.py                     # Httpx2Transport adapter (Seam 4)
```

Planned modules (filled in as the roadmap lands):

```text
src/httpware/
├── client.py                         # AsyncClient (Story 1.7)
├── decoders/msgspec.py               # MsgspecDecoder via extra (Story 1.6)
├── transports/recorded.py            # RecordedTransport for testing (Story 1.8)
├── middleware/                       # protocols + built-in middleware (Epic 2)
│   ├── __init__.py                   # Middleware protocol, Next type
│   ├── chain.py                      # chain composition
│   ├── auth.py                       # auth coercion (Story 2.4)
│   ├── timeout.py                    # per-attempt timeout (Story 3.1)
│   ├── retry.py                      # retry + RetryBudget (Stories 3.2–3.4)
│   ├── bulkhead.py                   # concurrency limit (Story 3.5)
│   └── observability/                # Layer 1 emission + OTEL (Epic 5)
└── _internal/                        # private cross-module helpers
```
```

- [ ] **Step 6: Write Section 6 — Testing patterns**

Append:

```markdown
## 6. Testing patterns

- **`pytest-asyncio` auto mode.** Async test functions do not require `@pytest.mark.asyncio`. The setting lives in `pyproject.toml` under `[tool.pytest.ini_options]`.
- **`RecordedTransport` for transport mocking, not `respx`.** Once Story 1.8 lands, transport-level tests instantiate `RecordedTransport` (shipped with the library) instead of patching `httpx2` calls. This keeps tests aligned with the public seam and avoids `respx`'s private-API risk.
- **Hypothesis property-based tests** for concurrency-sensitive code: `RetryBudget`, `Bulkhead`, retry interleaving. Files are named `test_*_props.py` so they are easy to grep and treat separately in CI.
- **Performance tests are opt-in.** The `perf` pytest marker is registered in `pyproject.toml`; the default `addopts` line includes `-m 'not perf'`. Run benchmarks explicitly with `pytest -m perf`.
- **Coverage is 100% line coverage.** The five merged stories ship at 100% line coverage. New code is expected to maintain this.
```

- [ ] **Step 7: Write Section 7 — Optional-extras pattern**

Append:

```markdown
## 7. Optional-extras pattern

`httpware` core has a small dependency set. Capabilities that pull in heavyweight dependencies (`pydantic`, `msgspec`, `opentelemetry`) live behind extras declared in `pyproject.toml`:

```toml
[project.optional-dependencies]
pydantic = ["pydantic>=2"]
msgspec = ["msgspec>=0.18"]
otel = ["opentelemetry-api>=1.20", "opentelemetry-sdk>=1.20"]
```

Each extra's code lives in a single dedicated module (e.g., `decoders/pydantic.py`, `decoders/msgspec.py`, `middleware/observability/otel.py`). The `import` of the extra happens **inside** that module — never at package top level. This way, `import httpware` works cleanly without the extras installed, and the seam stays observable: grep for `import pydantic` should return exactly one file.

Caller-facing pattern: consumers select the implementation by passing it explicitly, e.g., `AsyncClient(decoder=PydanticDecoder())`. There is no auto-detection or implicit registry.
```

- [ ] **Step 8: Write Section 8 — Remaining roadmap**

Append:

```markdown
## 8. Remaining roadmap

Twenty-seven stories remain. Topic slugs in `planning/specs/` and `planning/plans/` use kebab-case descriptions, not the story IDs — these IDs are kept here only as a stable mapping to the archived epic specs (`archive/epics.md`).

### Epic 1 — Make typed HTTP requests with sensible defaults

- **1-6** `msgspec` decoder via extras — second `ResponseDecoder` adapter, opt-in.
- **1-7** `AsyncClient` with HTTP methods, `response_model`, `with_options`, lifecycle — the main public surface.
- **1-8** `RecordedTransport` for testing — ships with the library; replaces `respx` for transport-level tests.

### Epic 2 — Compose request-handling logic via middleware

- **2-1** `Middleware` protocol, `Next` type, chain composition.
- **2-2** Phase shortcut decorators (`@on_request`, `@on_response`, `@on_error`).
- **2-3** `Request` immutability helpers (`with_headers`, `with_cookie`, `with_extension`, etc.).
- **2-4** Auth coercion as middleware.
- **2-5** Wire middleware into `AsyncClient`.

### Epic 3 — Survive upstream failures with composable resilience

- **3-1** Per-attempt timeout middleware.
- **3-2** Retry middleware.
- **3-3** `RetryBudget` data structure.
- **3-4** `RetryBudget` middleware integration.
- **3-5** `Bulkhead` middleware.
- **3-6** Document the extension slot for custom resilience policies.

### Epic 4 — Stream responses without buffering

- **4-1** `StreamResponse` type.
- **4-2** Transport stream implementation in `Httpx2Transport`.
- **4-3** `AsyncClient.stream` context manager.

### Epic 5 — Observe and instrument the client

- **5-1** Layer 1 observability — middleware lifecycle hooks.
- **5-2** Wire emission into resilience middlewares.
- **5-3** `Redactor` class and integration (closes deferred work on URL/header/userinfo sanitization).
- **5-4** OpenTelemetry middleware via the `otel` extra.
- **5-5** Logging policy enforcement (CI grep on `logging.basicConfig`, `logging.getLogger()` without a name).

### Epic 6 — Ship v1.0

- **6-1** Migration guide from `base-client`.
- **6-2** Documentation site (`mkdocs`).
- **6-3** Public benchmark suite.
- **6-4** CI enforcement gates (codify the invariants in Section 2 as CI jobs).
- **6-5** Release flow with Trusted Publishers + Sigstore.

When work starts on a roadmap item, it gets a superpowers spec at `planning/specs/YYYY-MM-DD-<topic>-design.md` and a plan at `planning/plans/YYYY-MM-DD-<topic>-plan.md`. The bmad-era 40KB story specs in `archive/stories/` cover 1-1 through 1-5 and are retired going forward.
```

- [ ] **Step 9: Write Section 9 — Deferred work pointer**

Append:

```markdown
## 9. Deferred work

Review-surfaced items that are real but not actionable now live in [`./deferred-work.md`](./deferred-work.md). Each entry cites the originating story and the file/line, and explains why the fix is deferred (cross-story dependency, scope, performance/security tradeoff, etc.). When a deferred item becomes actionable, it migrates into the spec for the story that resolves it.
```

- [ ] **Step 10: Verify the engineering doc**

Run: `wc -l docs/dev/engineering.md`
Expected: between 250 and 350 lines. If significantly shorter, sections were skipped; if longer, tighten the prose.

Run: `grep -c "^## " docs/dev/engineering.md`
Expected: `9` (nine top-level sections, one per spec requirement).

Run: `grep -n "TBD\|TODO\|XXX" docs/dev/engineering.md`
Expected: no matches.

Run (sanity-check internal links):
```bash
grep -oE '\]\([^)]+\)' docs/dev/engineering.md | sort -u
```
Expected: every relative link points to a file that exists. Specifically `../CLAUDE.md`, `./archive/`, `./deferred-work.md`, `archive/architecture.md` should all be reachable from `docs/`. Verify each:

```bash
ls ../CLAUDE.md docs/archive planning/deferred-work.md docs/archive/architecture.md
```

Each should exist.

---

## Task 4: Update `CLAUDE.md`

**Files:**
- Modify: `CLAUDE.md` — replace the "Project Overview" section; add a workflow one-liner.

- [ ] **Step 1: Read current `CLAUDE.md`**

The current file has these sections (line ranges approximate):
- `# CLAUDE.md` header
- `## Project Overview` — currently references `docs/prd.md`, `docs/architecture.md`, `docs/epics.md`, `docs/product-brief-httpware.md`, `docs/product-brief-httpware-distillate.md`, `docs/stories/`, and notes about the predecessor `community-of-python/base-client`.
- `## Commands` — `just` recipes
- `## Architecture invariants (CI-enforced)` — the six rules
- `## Code conventions`
- `## Module layout`
- `## Protocol seams`
- `## Testing`
- `## When in doubt`

Read it to get the exact existing text of the "Project Overview" section.

Run: `sed -n '/^## Project Overview/,/^## Commands/p' CLAUDE.md`

- [ ] **Step 2: Replace the "Project Overview" section**

Replace the entire `## Project Overview` section (between the heading and the start of `## Commands`) with:

```markdown
## Project Overview

`httpware` is a Python async HTTP client framework for building resilient service clients. It supersedes `community-of-python/base-client` and ships under the `modern-python` org. The framework owns the abstraction layer above the underlying HTTP client (`httpx2` by default); consumers never import the transport.

**Where to find what:**

- [`docs/dev/engineering.md`](docs/dev/engineering.md) — the distilled design reference: invariants and *why*, the five protocol seams, exception contract, module layout, testing patterns, optional-extras pattern, remaining roadmap. Read this before adding any new module or extension point.
- [`planning/deferred-work.md`](planning/deferred-work.md) — review-surfaced items that are real but not actionable now.
- [`planning/specs/`](planning/specs/) and [`planning/plans/`](planning/plans/) — per-feature design specs and implementation plans (active work).
- [`docs/archive/`](docs/archive/) — historical bmad-era planning bundle (PRD, architecture, epics, product briefs, per-story specs for 1-1 through 1-5). Consult only for original rationale or specific FR/NFR citations.

**Per-feature workflow:** brainstorming → spec in `planning/specs/` → writing-plans → plan in `planning/plans/` → executing-plans (or subagent-driven-development) → requesting-code-review → finishing-a-development-branch. Topic slugs are kebab-case descriptions (`msgspec-decoder-adapter`), not story IDs.
```

The "Architecture invariants (CI-enforced)", "Code conventions", "Module layout", "Protocol seams", "Testing", "Commands", and "When in doubt" sections stay **verbatim**. These are operational rules and quick references that the AI applies directly; they are not duplicated in `engineering.md` (which holds the rationale, not the rules).

- [ ] **Step 3: Update the "When in doubt" section**

The existing "When in doubt" section may reference `base-client/docs/architecture.md`. Update any such reference to `docs/dev/engineering.md` (primary) and `docs/archive/architecture.md` (historical detail).

Run: `grep -n "base-client/docs\|docs/prd.md\|docs/architecture.md\|docs/epics.md\|docs/stories\|product-brief" CLAUDE.md`

Each match needs to be rewritten or removed. After fixing, re-run the grep — expected: no matches (every reference to a moved file is gone or rewritten to `docs/archive/<file>`).

- [ ] **Step 4: Verify the updated CLAUDE.md**

Run: `wc -l CLAUDE.md`
Expected: roughly 105–120 lines (the original was 104; the new Project Overview is slightly longer than the old one).

Run: `grep -c "^## " CLAUDE.md`
Expected: matches the original section count (no sections lost). The original had Project Overview, Commands, Architecture invariants (CI-enforced), Code conventions, Module layout, Protocol seams, Testing, When in doubt — count `8`.

Run: `grep -n "docs/dev/engineering.md\|docs/archive" CLAUDE.md`
Expected: multiple matches in the new Project Overview section.

---

## Task 5: Delete `.review-tmp/`

**Files:**
- Delete: `.review-tmp/` (entire directory, untracked — never committed).

- [ ] **Step 1: Verify the directory is untracked**

Run: `git ls-files .review-tmp/`
Expected: no output (zero tracked files).

Run: `ls .review-tmp/`
Expected: `story-1-1.diff`, `story-1-2.diff`, `story-1-4.diff`, `story-1-5.bundle.md` (and possibly others).

- [ ] **Step 2: Delete it**

Run: `rm -rf .review-tmp/`

Run: `ls .review-tmp/ 2>&1 | head -2`
Expected: `ls: .review-tmp/: No such file or directory`.

Run: `git status --short | grep review-tmp || echo "GONE"`
Expected: `GONE`.

---

## Task 6: Verify and commit

- [ ] **Step 1: Run the test suite**

Run: `just test`
Expected: 157 passed, 1 deselected (the perf bench), 100% coverage. No changes vs. post-1-5 baseline because no source was touched.

- [ ] **Step 2: Run lint**

Run: `just lint-ci`
Expected: clean. No markdown lint is configured; this just confirms the source/CI state is unchanged.

- [ ] **Step 3: Verify the pre-staging diff**

Run: `git status --short`

Expected output (order may vary). The renames from Task 1 are already staged (via `git mv`); the new files from Tasks 2 and 3 and this plan file are untracked; `CLAUDE.md` is modified but unstaged:

```
M  CLAUDE.md                                                           # unstaged modification (space + M)
R  docs/architecture.md -> docs/archive/architecture.md                # staged rename
R  docs/epics.md -> docs/archive/epics.md
R  docs/prd.md -> docs/archive/prd.md
R  docs/product-brief-httpware-distillate.md -> docs/archive/product-brief-httpware-distillate.md
R  docs/product-brief-httpware.md -> docs/archive/product-brief-httpware.md
R  docs/stories/1-1-project-scaffold-and-tooling.md -> docs/archive/stories/1-1-project-scaffold-and-tooling.md
R  docs/stories/1-2-core-data-types.md -> docs/archive/stories/1-2-core-data-types.md
R  docs/stories/1-3-exception-hierarchy-with-plain-fields.md -> docs/archive/stories/1-3-exception-hierarchy-with-plain-fields.md
R  docs/stories/1-4-transport-protocol-and-httpx2transport-adapter.md -> docs/archive/stories/1-4-transport-protocol-and-httpx2transport-adapter.md
R  docs/stories/1-5-responsedecoder-protocol-and-pydantic-adapter.md -> docs/archive/stories/1-5-responsedecoder-protocol-and-pydantic-adapter.md
R  docs/stories/sprint-status.yaml -> docs/archive/stories/sprint-status.yaml
?? docs/archive/README.md                                              # untracked
?? docs/dev/engineering.md
?? planning/plans/2026-05-31-bmad-to-superpowers-transition-plan.md
```

No `.review-tmp/` anywhere. No source/`pyproject.toml`/CI changes.

If any line begins with `??` for a file not in the list above, or any source file appears, stop and resolve.

- [ ] **Step 4: Stage everything**

Run: `git add CLAUDE.md docs/`

(`git add docs/` picks up the new `docs/archive/README.md`, `docs/dev/engineering.md`, and `planning/plans/2026-05-31-...-plan.md` in one step.)

Re-run: `git status --short`
Expected: every line begins with a capital letter (`A`, `M`, or `R`) in column 1 and a space in column 2 (everything staged, nothing left in the working tree).

- [ ] **Step 5: Commit**

Run:
```bash
git commit -m "$(cat <<'EOF'
chore: cutover from bmad to superpowers workflow

Distills the bmad-era PRD / architecture / epics into a single
docs/dev/engineering.md (~300 lines) covering project intent, the six
CI-enforced invariants with rationale, the five protocol seams,
the exception contract, current + planned module layout, testing
patterns, the optional-extras pattern, the remaining 27-story
roadmap, and a pointer to deferred-work.md.

Moves prd.md, architecture.md, epics.md, both product briefs, and
the per-story specs (1-1 through 1-5 + sprint-status.yaml) into
docs/archive/ with a README framing them as historical reference.

Rewrites CLAUDE.md "Project Overview" to point at engineering.md
and the new docs/superpowers/{specs,plans}/ flow. All operational
sections (invariants, conventions, module layout, seams, testing,
commands, when in doubt) are kept verbatim.

Deletes the .review-tmp/ bmad code-review artifact dump.

No source / CI changes. 157 tests still pass at 100% coverage.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

Run: `git log --oneline -3`
Expected: the cutover commit on top, then the spec commit (`docs(superpowers): brainstorming spec...`), then the 1-5 merge commit.

---

## Task 7: Push and open the cutover PR

- [ ] **Step 1: Push the branch**

Run: `git push -u origin chore/bmad-to-superpowers-transition`
Expected: push succeeds; GitHub prints a "Create a pull request for ..." URL.

- [ ] **Step 2: Open the PR**

Run:
```bash
gh pr create --title "chore: cutover from bmad to superpowers workflow" --body "$(cat <<'EOF'
## Summary

- Distills the bmad-era PRD / architecture / epics into a single `docs/dev/engineering.md` (~300 lines): project intent, six CI-enforced invariants with rationale, the five protocol seams, exception contract, module layout, testing patterns, optional-extras pattern, remaining 27-story roadmap, deferred-work pointer.
- Moves `prd.md`, `architecture.md`, `epics.md`, both product briefs, and `docs/stories/` (1-1 through 1-5 + `sprint-status.yaml`) into `docs/archive/` with a framing README.
- Rewrites `CLAUDE.md` "Project Overview" to point at `engineering.md` and the new `docs/superpowers/{specs,plans}/` flow. Operational sections (invariants, conventions, module layout, seams, testing, commands, when-in-doubt) are kept verbatim.
- Deletes the `.review-tmp/` bmad code-review artifact dump.

After this lands, future per-feature work uses the superpowers flow: brainstorming → spec in `planning/specs/` → writing-plans → plan in `planning/plans/` → executing-plans (or subagent-driven-development) → requesting-code-review → finishing-a-development-branch. Story IDs are retired as topic slugs; the bmad backlog mapping lives in `engineering.md`'s roadmap section.

The driving design + plan for this PR are at `planning/specs/2026-05-31-bmad-to-superpowers-transition-design.md` and `planning/plans/2026-05-31-bmad-to-superpowers-transition-plan.md`.

## Test plan

- [x] No source or CI changes; the 157-test suite continues to pass at 100% coverage on the branch.
- [x] `just lint-ci` clean.
- [x] `git status --short` shows only renames, three new docs files, one modified `CLAUDE.md`, and the `.review-tmp/` deletion.
- [x] All internal links in `docs/dev/engineering.md` and `CLAUDE.md` resolve to files that exist post-move.
- [ ] CI green on the PR.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Run: `gh pr view --json url,state | head -5`
Expected: state `OPEN`, URL printed.

- [ ] **Step 3: Wait for CI**

Run: `gh pr checks` (or wait for the existing `lint` + `pytest (3.11)` / `pytest (3.12)` / `pytest (3.13)` / `pytest (3.14)` jobs).
Expected: all checks green. The PR touches no source so failures would indicate a CLAUDE.md / engineering.md formatting issue or a broken internal link only.

- [ ] **Step 4: Merge**

Once CI is green and the PR is approved (or self-approved if working solo):

Run: `gh pr merge --merge --delete-branch`
Expected: PR merged, branch deleted locally and on remote.

Run: `git checkout main && git pull --ff-only && git log --oneline -3`
Expected: the cutover commit at HEAD, then the spec commit, then the 1-5 merge.

The cutover is complete. Task 1 (retrospective code review) is the next normal-flow item.

---

## Definition of done

- `docs/dev/engineering.md` exists (250–350 lines) and is referenced from `CLAUDE.md`.
- `docs/archive/` contains the six top-level moves plus the `stories/` directory and a framing `README.md`.
- `planning/specs/2026-05-31-bmad-to-superpowers-transition-design.md` and `planning/plans/2026-05-31-bmad-to-superpowers-transition-plan.md` are committed.
- `.review-tmp/` is gone.
- `CLAUDE.md` no longer references `docs/prd.md`, `docs/architecture.md`, `docs/epics.md`, `docs/stories/`, or the product briefs at their original paths.
- The cutover commit is a single commit on `chore/bmad-to-superpowers-transition`, merged to `main` via one PR.
- `just test` and `just lint-ci` remain green; no source/CI changes.

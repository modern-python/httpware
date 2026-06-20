---
status: shipped
date: 2026-06-02
slug: docs-reorg-and-mkdocs
spec: docs-reorg-and-mkdocs
pr: 17
---

# Docs reorg + minimal mkdocs site implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Delete `docs/archive/`, move agent/contributor workflow artifacts to a tool-neutral `planning/` directory at the repo root, and stand up a minimal mkdocs site published via Read the Docs — without breaking any internal markdown link, the CI lint/test pipeline, or git history for moved files.

**Architecture:** Pure structural reorganization. Eleven atomic-commit tasks executed in dependency order: (1) preserve the one load-bearing archive citation by inlining it into engineering.md, (2) move workflow artifacts via `git mv` so history follows, (3) move engineering docs into a `docs/dev/` subtree that the mkdocs site will publish, (4) bulk-update path references across CLAUDE.md and every existing spec/plan, (5) refactor README.md to align with the modern-python org pattern, (6) add the mkdocs/RTD config files, (7) delete the archive, (8) verify everything builds and lints. No source code touched. No CI grep invariants change. The `src/` layout is unchanged.

**Tech Stack:** `mkdocs` + `mkdocs-material` (Read the Docs published), `uv`, `just`, `git mv` for history preservation.

---

## Pre-flight

Plan assumes you are on a clean working tree at the spec's current commit (`a2abca4` or descendant). Verify before starting:

```bash
git status              # should be clean
git rev-parse HEAD      # record starting commit for sanity
```

The spec lives at `docs/superpowers/specs/2026-06-02-docs-reorg-and-mkdocs-design.md` — read it once if you haven't.

---

### Task 1: Inline the load-bearing decoder rationale into engineering.md

**Goal:** Before `archive/` is deleted, port the one rationale that `engineering.md` externalizes — the "two-pass decoding is rejected" reasoning at Seam 3 — into `engineering.md` itself. This must happen first so nothing is lost when archive is removed in Task 10.

**Files:**
- Modify: `docs/engineering.md` line 40 (Seam 3 "Rule" bullet)

**Reference (source of inlined text):** `docs/archive/architecture.md` lines 270–283 ("Decision 8 — ResponseDecoder protocol").

- [ ] **Step 1: Read the archive section once**

Run: `sed -n '270,283p' docs/archive/architecture.md`

Confirm you see the "ResponseDecoder protocol" decision: single parse pass (NFR3), `TypeAdapter.validate_json` with `lru_cache` (NFR2), `msgspec.json.decode` for the extras adapter.

- [ ] **Step 2: Edit engineering.md line 40**

Replace this exact line in `docs/engineering.md`:

```markdown
- **Rule:** the decoder must operate on raw bytes in a single parse pass. Two-pass decoding (`json.loads` then `validate_python`) is rejected — see `archive/architecture.md` Validation & Decoding for rationale.
```

With:

```markdown
- **Rule:** the decoder must operate on raw bytes in a single parse pass. Two-pass decoding (`json.loads` then `validate_python`) is rejected: a single bytes-in / typed-object-out pass avoids the redundant intermediate `dict` allocation and parses faster. The Pydantic adapter implements this as `TypeAdapter(model).validate_json(content)` with `@functools.lru_cache(maxsize=None)` on `TypeAdapter` construction (the adapter object is the expensive part to build, keyed by `model`). The msgspec adapter implements it as `msgspec.json.decode(content, type=model)`.
```

- [ ] **Step 3: Confirm no other archive citation is load-bearing**

Run: `grep -n "archive/" docs/engineering.md`

Expected output (exactly three remaining lines):
```
3:This doc is the single distilled reference for `httpware` design rationale, protocol seams, and remaining roadmap. ...
134:Twenty-seven stories remain. Topic slugs in `docs/superpowers/specs/` and `docs/superpowers/plans/` use kebab-case descriptions, not the story IDs — these IDs are kept here only as a stable mapping to the archived epic specs (`archive/epics.md`).
181:When work starts on a roadmap item, it gets a superpowers spec at `docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md` and a plan at `docs/superpowers/plans/YYYY-MM-DD-<topic>-plan.md`. The bmad-era 40KB story specs in `archive/stories/` cover 1-1 through 1-5 and are retired going forward.
```

These three remaining references are *soft* — Task 2 strips them. Line 40 no longer mentions archive: verify with `grep -n "archive/architecture.md" docs/engineering.md` returning **no output**.

- [ ] **Step 4: Commit**

```bash
git add docs/engineering.md
git commit -m "docs: inline decoder rationale before archive deletion"
```

---

### Task 2: Strip remaining soft archive references from engineering.md

**Goal:** Remove the three remaining `archive/` mentions (lines 3, 134, 181) and any pointer that will be broken when archive is deleted. These are informational, not load-bearing; they just get deleted/rephrased.

**Files:**
- Modify: `docs/engineering.md` (three edits)

- [ ] **Step 1: Edit line 3 — drop the archive pointer sentence**

Replace this exact line in `docs/engineering.md`:

```markdown
This doc is the single distilled reference for `httpware` design rationale, protocol seams, and remaining roadmap. It complements [`../CLAUDE.md`](../CLAUDE.md): `CLAUDE.md` holds AI-enforced invariants and operational commands; this file holds the reasoning and the structural map. Historical planning artifacts live in [`archive/`](./archive/) and are cited only for original rationale.
```

With:

```markdown
This doc is the single distilled reference for `httpware` design rationale, protocol seams, and remaining roadmap. It complements [`../CLAUDE.md`](../CLAUDE.md): `CLAUDE.md` holds AI-enforced invariants and operational commands; this file holds the reasoning and the structural map.
```

- [ ] **Step 2: Edit line 134 — drop the archived-epics parenthetical**

Replace this exact line in `docs/engineering.md`:

```markdown
Twenty-seven stories remain. Topic slugs in `docs/superpowers/specs/` and `docs/superpowers/plans/` use kebab-case descriptions, not the story IDs — these IDs are kept here only as a stable mapping to the archived epic specs (`archive/epics.md`).
```

With:

```markdown
Twenty-seven stories remain. Topic slugs in `docs/superpowers/specs/` and `docs/superpowers/plans/` use kebab-case descriptions, not the story IDs — these IDs are retained as a stable identifier convention from the original epic structure.
```

(Note: this line still references `docs/superpowers/...` — those references get rewritten in Task 7.)

- [ ] **Step 3: Edit line 181 — drop the retired-stories sentence**

Replace this exact line in `docs/engineering.md`:

```markdown
When work starts on a roadmap item, it gets a superpowers spec at `docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md` and a plan at `docs/superpowers/plans/YYYY-MM-DD-<topic>-plan.md`. The bmad-era 40KB story specs in `archive/stories/` cover 1-1 through 1-5 and are retired going forward.
```

With:

```markdown
When work starts on a roadmap item, it gets a spec at `docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md` and a plan at `docs/superpowers/plans/YYYY-MM-DD-<topic>-plan.md`.
```

(The `docs/superpowers/` paths here also get rewritten in Task 7.)

- [ ] **Step 4: Verify no archive references remain**

Run: `grep -n "archive/" docs/engineering.md`

Expected output: **(nothing)** — all archive citations are gone from engineering.md.

- [ ] **Step 5: Commit**

```bash
git add docs/engineering.md
git commit -m "docs: drop soft archive references from engineering.md"
```

---

### Task 3: Move workflow artifacts to planning/ (preserves git history)

**Goal:** Relocate the `docs/superpowers/` subtree to a tool-neutral `planning/` directory at the repository root, and move `docs/deferred-work.md` alongside. Use `git mv` so history follows. This is a pure rename — no content changes.

**Files:**
- Move: `docs/superpowers/specs/` → `planning/specs/`
- Move: `docs/superpowers/plans/` → `planning/plans/`
- Move: `docs/deferred-work.md` → `planning/deferred-work.md`
- Delete: `docs/superpowers/` (empty after the moves)

- [ ] **Step 1: Create the parent planning/ directory**

```bash
mkdir -p planning
```

- [ ] **Step 2: Move the specs and plans subdirectories**

```bash
git mv docs/superpowers/specs planning/specs
git mv docs/superpowers/plans planning/plans
```

- [ ] **Step 3: Move deferred-work.md**

```bash
git mv docs/deferred-work.md planning/deferred-work.md
```

- [ ] **Step 4: Remove the now-empty docs/superpowers/ directory**

```bash
rmdir docs/superpowers
```

If `rmdir` complains the directory is not empty, list the contents (`ls -la docs/superpowers/`) and resolve before proceeding.

- [ ] **Step 5: Verify history is preserved**

```bash
git log --follow --oneline -n 3 planning/specs/2026-06-01-auth-coercion-design.md
```

Expected: shows commits from before the rename. If git shows only one commit, the move did not preserve history — abort and investigate.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "docs: rename docs/superpowers/ to planning/ (history-preserving)"
```

---

### Task 4: Move engineering.md and CONTRIBUTING.md into docs/dev/

**Goal:** Establish the `docs/dev/` subtree that the mkdocs site will publish under "Development". Move `docs/engineering.md` and the root `CONTRIBUTING.md` into it.

**Files:**
- Move: `docs/engineering.md` → `docs/dev/engineering.md`
- Move: `CONTRIBUTING.md` (root) → `docs/dev/contributing.md`
- Create directory: `docs/dev/`

- [ ] **Step 1: Create docs/dev/**

```bash
mkdir -p docs/dev
```

- [ ] **Step 2: Move engineering.md**

```bash
git mv docs/engineering.md docs/dev/engineering.md
```

- [ ] **Step 3: Move root CONTRIBUTING.md**

```bash
git mv CONTRIBUTING.md docs/dev/contributing.md
```

- [ ] **Step 4: Verify history is preserved**

```bash
git log --follow --oneline -n 3 docs/dev/engineering.md
```

Expected: shows multiple historical commits (the file has been edited several times).

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "docs: move engineering.md and CONTRIBUTING.md into docs/dev/"
```

---

### Task 5: Create thin root CONTRIBUTING.md stub

**Goal:** Replace the moved-out root `CONTRIBUTING.md` with a tiny stub that points to the published docs URL and the in-repo source path. Preserves GitHub's "open a PR" UI integration (which surfaces a root `CONTRIBUTING.md` to PR authors).

**Files:**
- Create: `CONTRIBUTING.md` (at repo root)

- [ ] **Step 1: Write the stub**

Create `CONTRIBUTING.md` with exactly this content:

```markdown
# Contributing

The contributing guide is published as part of the project documentation:
**https://httpware.readthedocs.io/en/latest/dev/contributing/**

Source: [`docs/dev/contributing.md`](docs/dev/contributing.md).
```

- [ ] **Step 2: Commit**

```bash
git add CONTRIBUTING.md
git commit -m "docs: add thin root CONTRIBUTING.md stub pointing to published guide"
```

---

### Task 6: Bulk-update path references across CLAUDE.md and the planning tree

**Goal:** Every file that referenced `docs/superpowers/...`, `docs/engineering.md`, `docs/deferred-work.md`, or `docs/archive/...` is now pointing at paths that have moved (or will not exist post-Task 10). This task mechanically rewrites the safe-to-transform references and manually fixes the context-sensitive ones (archive removals).

**Files to update (21 total):**
- `CLAUDE.md` (root)
- `docs/dev/engineering.md`
- `planning/specs/2026-05-31-*.md` (9 files)
- `planning/specs/2026-06-01-auth-coercion-design.md`
- `planning/specs/2026-06-02-docs-reorg-and-mkdocs-design.md` (self-reference — see Step 6 below)
- `planning/plans/2026-05-31-*.md` (8 files)
- `planning/plans/2026-06-01-auth-coercion-plan.md`

Note: `README.md` does NOT contain these old paths; it's refactored separately in Task 7.

- [ ] **Step 1: Mechanical replacements across CLAUDE.md and planning/**

These four substitutions are safe to apply via `sed` because they always mean the same thing in every context:

**Important:** this plan and the spec live inside `planning/` and *intentionally* contain old-path references (in `git mv` commands and narrative). They are excluded from the rewrite.

```bash
# macOS sed uses -i '' (BSD); replace with -i (GNU) on Linux if needed.
SED_INPLACE=(-i '')

find CLAUDE.md planning/ docs/dev/ -type f -name '*.md' \
  ! -name '2026-06-02-docs-reorg-and-mkdocs-design.md' \
  ! -name '2026-06-02-docs-reorg-and-mkdocs-plan.md' \
  -print0 |
  xargs -0 sed "${SED_INPLACE[@]}" \
    -e 's|docs/superpowers/specs/|planning/specs/|g' \
    -e 's|docs/superpowers/plans/|planning/plans/|g' \
    -e 's|docs/engineering\.md|docs/dev/engineering.md|g' \
    -e 's|docs/deferred-work\.md|planning/deferred-work.md|g'
```

If you are on Linux: change `SED_INPLACE=(-i '')` to `SED_INPLACE=(-i)`.

- [ ] **Step 2: Verify mechanical replacements landed**

Run:
```bash
grep -rn "docs/superpowers/\|docs/engineering\.md\|docs/deferred-work\.md" CLAUDE.md planning/ docs/dev/ \
  | grep -v "2026-06-02-docs-reorg-and-mkdocs-design.md" \
  | grep -v "2026-06-02-docs-reorg-and-mkdocs-plan.md"
```

Expected output: **(nothing)**. The only files that legitimately still contain the old paths are this plan and its spec — both excluded from the find pass above and from this grep.

If hits appear in any other file, investigate and fix manually before continuing.

- [ ] **Step 3: Update CLAUDE.md archive references (context-sensitive — manual)**

Edit `CLAUDE.md`. Two distinct edits.

Edit A — delete the archive bullet from "Where to find what" section. Replace this exact line:

```markdown
- [`docs/archive/`](docs/archive/) — historical bmad-era planning bundle (PRD, architecture, epics, product briefs, per-story specs for 1-1 through 1-5). Consult only for original rationale or specific FR/NFR citations.
```

With: **(delete entirely — no replacement)**

Edit B — strip the archive trailer from the "When in doubt" bullet. Replace this exact line:

```markdown
- Check [`docs/engineering.md`](docs/engineering.md) before adding a new module or extension point; `docs/archive/architecture.md` has the deeper historical rationale if needed.
```

With (note: the `docs/engineering.md` → `docs/dev/engineering.md` part was already handled by Step 1's sed, so the line currently reads `Check [\`docs/dev/engineering.md\`](docs/dev/engineering.md) before adding a new module or extension point; \`docs/archive/architecture.md\` has the deeper historical rationale if needed.` — the edit removes only the trailing semicolon-clause):

```markdown
- Check [`docs/dev/engineering.md`](docs/dev/engineering.md) before adding a new module or extension point.
```

- [ ] **Step 4: Sweep for any remaining archive references**

Run: `grep -rn "docs/archive\|archive/" CLAUDE.md planning/ docs/dev/`

Expected hits are only inside `planning/specs/2026-06-02-docs-reorg-and-mkdocs-design.md` (the spec narrates the deletion). Anywhere else, investigate.

- [ ] **Step 5: Sweep for any remaining references to the root CONTRIBUTING.md (which is now a stub)**

References to `CONTRIBUTING.md` from within planning/ or docs/dev/ should point at `docs/dev/contributing.md`. Currently there are none (verify):

Run: `grep -rn "CONTRIBUTING\.md" planning/ docs/dev/ CLAUDE.md`

Expected: no hits (the contributing doc isn't cross-referenced from other files). If hits appear, replace each with `docs/dev/contributing.md` as appropriate to the link context.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "docs: update path references for docs reorg"
```

---

### Task 7: Refactor README.md

**Goal:** Slim README to align with the modern-python org pattern (project intent, install, runnable snippet, links to docs site / PyPI / license, org positioning). The current README is good content but lacks the docs-site link and has a "What ships in 0.1.0" section that duplicates engineering notes. Trim it.

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Replace README.md entirely**

Overwrite `README.md` with this content:

````markdown
# httpware

[![Test](https://github.com/modern-python/httpware/actions/workflows/ci.yml/badge.svg)](https://github.com/modern-python/httpware/actions/workflows/ci.yml)
[![PyPI version](https://badge.fury.io/py/httpware.svg)](https://pypi.org/project/httpware/)
[![Python versions](https://img.shields.io/pypi/pyversions/httpware.svg)](https://pypi.org/project/httpware/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Async HTTP client framework for Python.**

`httpware` is a typed, async HTTP client library with a protocol-based seam so the transport is swappable (`httpx2` ships as the default). Middleware composes via an onion model. Pydantic and msgspec response decoding ship out of the box. `RecordedTransport` replaces `respx` for transport-level tests.

> **Status:** Pre-1.0 (0.1.0 alpha). Public API is subject to change between minor releases until v1.0. Resilience middleware (retry / timeout / bulkhead), streaming, and observability are not yet shipped.

## Install

```bash
pip install httpware
```

Optional extras:

```bash
pip install httpware[msgspec]    # MsgspecDecoder
```

(`otel`, `niquests`, and `all` extras are declared; integrations have not shipped yet.)

## Quickstart

```python
from httpware import AsyncClient
from pydantic import BaseModel


class User(BaseModel):
    id: int
    name: str


async def main() -> None:
    async with AsyncClient(base_url="https://api.example.com") as client:
        user = await client.get("/users/1", response_model=User)
        print(user.name)
```

## 📚 [Documentation](https://httpware.readthedocs.io)

## 📦 [PyPI](https://pypi.org/project/httpware)

## 📝 [License](./LICENSE)

## Part of `modern-python`

Browse the full list of templates and libraries in [`modern-python`](https://github.com/modern-python) — see the org profile for the categorized index.
````

(The "What ships in 0.1.0" section is removed — that level of detail belongs on the docs site, not the README. The badges and the runnable Quickstart stay.)

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: refactor README to link to published docs site"
```

---

### Task 8: Add mkdocs.yml, .readthedocs.yaml, docs/requirements.txt, docs/index.md

**Goal:** Stand up the minimal mkdocs site. Four new files. After this task, `mkdocs build --strict` should succeed against the new structure.

**Files:**
- Create: `mkdocs.yml`
- Create: `.readthedocs.yaml`
- Create: `docs/requirements.txt`
- Create: `docs/index.md`

- [ ] **Step 1: Create mkdocs.yml**

Create `mkdocs.yml` with exactly this content:

```yaml
site_name: httpware
site_url: https://httpware.readthedocs.io/
repo_url: https://github.com/modern-python/httpware
docs_dir: docs
edit_uri: edit/main/docs/

nav:
  - Quick-Start: index.md
  - Development:
      - Engineering Notes: dev/engineering.md
      - Contributing: dev/contributing.md

theme:
  name: material
  features:
    - content.code.copy
    - content.action.edit
    - navigation.footer
    - navigation.sections
    - navigation.top
    - header.autohide
  palette:
    - media: "(prefers-color-scheme: light)"
      scheme: default
      primary: black
      accent: pink
      toggle:
        icon: material/brightness-7
        name: Switch to dark mode
    - media: "(prefers-color-scheme: dark)"
      scheme: slate
      primary: black
      accent: pink
      toggle:
        icon: material/brightness-4
        name: Switch to system preference

markdown_extensions:
  - toc:
      permalink: true
  - pymdownx.highlight:
      anchor_linenums: true
  - pymdownx.inlinehilite
  - pymdownx.superfences
  - admonition
  - attr_list
```

- [ ] **Step 2: Create .readthedocs.yaml**

Create `.readthedocs.yaml` with exactly this content:

```yaml
version: 2

build:
  os: "ubuntu-22.04"
  tools:
    python: "3.12"

python:
  install:
    - requirements: docs/requirements.txt

mkdocs:
  configuration: mkdocs.yml
```

- [ ] **Step 3: Create docs/requirements.txt**

Create `docs/requirements.txt` with exactly this content:

```
mkdocs
mkdocs-material
```

- [ ] **Step 4: Create docs/index.md**

Create `docs/index.md` with exactly this content:

````markdown
# httpware

A Python async HTTP client framework for building resilient service clients. `httpware` owns the abstraction layer above the underlying HTTP client (`httpx2` by default); consumers never import the transport directly.

> **Status:** Pre-1.0 (0.1.0 alpha). Public API is subject to change between minor releases until v1.0.

## Install

```bash
pip install httpware
```

Optional extras:

```bash
pip install httpware[msgspec]    # MsgspecDecoder
```

## First request

```python
import asyncio

from httpware import AsyncClient
from pydantic import BaseModel


class User(BaseModel):
    id: int
    name: str


async def main() -> None:
    async with AsyncClient(base_url="https://api.example.com") as client:
        user = await client.get("/users/1", response_model=User)
        print(user.name)


asyncio.run(main())
```

## Where to go next

- **[Engineering Notes](dev/engineering.md)** — design invariants, the five protocol seams, exception contract, module layout, testing patterns, optional-extras pattern.
- **[Contributing](dev/contributing.md)** — setup, conventions, workflow.

## Part of `modern-python`

`httpware` ships under the [`modern-python`](https://github.com/modern-python) org. See the org profile for the categorized index of related templates and libraries.
````

- [ ] **Step 5: Build the site locally to catch broken links now**

Run: `uv run --with mkdocs --with mkdocs-material mkdocs build --strict`

Expected: exits 0 with no warnings. A `site/` directory is produced (ignore it; do not commit).

If the build fails with a "doc file is not included in the 'nav'" warning for `dev/engineering.md` or `dev/contributing.md`, the nav block in `mkdocs.yml` is wrong — recheck Step 1.

If the build fails with a broken-link warning, follow the link in the error to find the offending file and fix its reference. Common cases:

- A link to `engineering.md` from a sibling file under `dev/` should be a relative `engineering.md`, not `dev/engineering.md`.
- A link from `index.md` to a file under `dev/` should be `dev/engineering.md`.

- [ ] **Step 6: Confirm site/ is gitignored**

Run: `grep -n "^site" .gitignore`

If `site/` is not gitignored, add it:

```bash
echo "site/" >> .gitignore
git add .gitignore
```

Then remove the local build artifact:

```bash
rm -rf site/
```

- [ ] **Step 7: Commit**

```bash
git add mkdocs.yml .readthedocs.yaml docs/requirements.txt docs/index.md
# Also stage .gitignore if you modified it in Step 6
git add .gitignore 2>/dev/null || true
git commit -m "docs: add minimal mkdocs site published via Read the Docs"
```

---

### Task 9: Delete docs/archive/

**Goal:** Remove the bmad-era archive. Everything load-bearing has been ported. After this commit, `git grep -n "docs/archive"` should return zero hits (outside the spec/plan files that narrate the deletion).

**Files:**
- Delete: `docs/archive/` (entire subtree)

- [ ] **Step 1: Confirm contents about to be deleted**

```bash
ls docs/archive/
ls docs/archive/stories/
```

Expected files:
- `docs/archive/`: `README.md`, `architecture.md`, `epics.md`, `prd.md`, `product-brief-httpware.md`, `product-brief-httpware-distillate.md`, `stories/`
- `docs/archive/stories/`: `1-1-project-scaffold-and-tooling.md`, `1-2-core-data-types.md`, `1-3-exception-hierarchy-with-plain-fields.md`, `1-4-transport-protocol-and-httpx2transport-adapter.md`, `1-5-responsedecoder-protocol-and-pydantic-adapter.md`, `sprint-status.yaml`

If the inventory differs, **stop** and investigate before deleting.

- [ ] **Step 2: Delete the directory**

```bash
git rm -rf docs/archive
```

- [ ] **Step 3: Verify nothing in the published tree references archive**

```bash
grep -rn "docs/archive\|archive/architecture\.md\|archive/epics\.md\|archive/stories" docs/ CLAUDE.md README.md
```

Expected: **(no output)**. Files under `docs/` no longer mention archive at all.

- [ ] **Step 4: Final repo-wide sweep, excluding the migration spec and plan**

```bash
grep -rn "docs/archive" . \
  --exclude-dir=.git --exclude-dir=.venv --exclude-dir=site \
  | grep -v "planning/specs/2026-06-02-docs-reorg-and-mkdocs-design.md" \
  | grep -v "planning/plans/2026-06-02-docs-reorg-and-mkdocs-plan.md"
```

Expected: **(no output)**. The migration's own spec and plan narrate the deletion and are the only allowed mentions.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "docs: delete bmad-era archive (rationale inlined into engineering.md)"
```

---

### Task 10: Run lint, tests, and final mkdocs strict build

**Goal:** Confirm nothing in the source tree, the test suite, or the docs build regressed.

- [ ] **Step 1: Lint**

Run: `just lint-ci`

Expected: exits 0. If ruff or ty fail, the cause is unrelated to the docs reorg (no Python files were touched) — investigate before continuing.

- [ ] **Step 2: Tests**

Run: `just test`

Expected: exits 0, all tests pass, coverage unchanged.

- [ ] **Step 3: Docs build**

Run: `uv run --with mkdocs --with mkdocs-material mkdocs build --strict`

Expected: exits 0 with no warnings. Remove the build artifact afterward: `rm -rf site/`.

- [ ] **Step 4: History-preservation spot check**

```bash
git log --follow --oneline -n 3 docs/dev/engineering.md
git log --follow --oneline -n 3 planning/specs/2026-06-01-auth-coercion-design.md
git log --follow --oneline -n 3 docs/dev/contributing.md
```

Expected: each shows historical commits from before the rename. If any of them shows only the rename commit, history was not preserved — `git mv` was missed somewhere and the file was re-created instead of moved. Investigate and fix.

- [ ] **Step 5: No commit needed**

Task 10 only runs verifications. If everything passed, the working tree is clean and you are done with the implementation.

---

### Task 11: Post-merge follow-up (out of band, manual, not part of the PR)

**Goal:** Document the manual steps required after the PR merges. These are NOT part of the implementation — they're a checklist for the human reviewer/maintainer.

**Out-of-band steps:**

1. **Create the Read the Docs project.** Log in at https://readthedocs.org, add `modern-python/httpware` as a new project. The webhook is set up automatically when the project is added via the GitHub integration.
2. **Verify the build.** First build kicks off when the PR merges to `main`. Confirm at the RTD project dashboard that the build succeeds.
3. **Claim the subdomain.** Default subdomain will be `httpware.readthedocs.io` if available. If taken, update `site_url` in `mkdocs.yml` and the docs link in `README.md` accordingly.
4. **Set default branch / version.** Confirm RTD is tracking the `main` branch as the default version.
5. **Add the RTD badge to the README** (optional, follow-up):
   ```markdown
   [![Documentation Status](https://readthedocs.org/projects/httpware/badge/?version=latest)](https://httpware.readthedocs.io/en/latest/?badge=latest)
   ```

This task does not require any commit.

---

## Verification summary

Every task above should leave the working tree in a state where:

- `just lint-ci` exits 0 (Tasks 1–10)
- `just test` exits 0 (Tasks 1–10)
- `git status` is clean after each task's commit
- `git log --follow` shows preserved history for every moved file
- After Task 8 onwards, `mkdocs build --strict` exits 0 with zero warnings

The final repository layout matches the spec's "File structure" section:

```
/
├─ README.md, SECURITY.md, CLAUDE.md, LICENSE, Justfile, pyproject.toml, ...
├─ CONTRIBUTING.md             ← thin stub
├─ .readthedocs.yaml           ← NEW
├─ mkdocs.yml                  ← NEW
├─ docs/
│  ├─ index.md                 ← NEW
│  ├─ requirements.txt         ← NEW
│  └─ dev/
│     ├─ engineering.md
│     └─ contributing.md
├─ planning/
│  ├─ specs/
│  ├─ plans/
│  └─ deferred-work.md
├─ src/httpware/               ← unchanged
└─ tests/                      ← unchanged
```

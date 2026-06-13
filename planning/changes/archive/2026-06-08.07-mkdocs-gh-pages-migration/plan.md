---
status: shipped
date: 2026-06-08
slug: mkdocs-gh-pages-migration
spec: mkdocs-gh-pages-migration
pr: 38
---

# mkdocs GitHub Pages Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move httpware's docs hosting from ReadTheDocs to GitHub Pages at `httpware.modern-python.org`, modeled on the `modern-di` pipeline, as a single structural PR.

**Architecture:** A GitHub Actions workflow (`docs.yml`) runs `just docs-deploy` on every push to `main` that touches docs, mkdocs config, or the workflow itself. The recipe uses `uvx --with-requirements docs/requirements.txt mkdocs gh-deploy --force`, which builds the site and force-pushes it to the `gh-pages` branch. A `docs/CNAME` file pins the custom domain across deploys. ReadTheDocs config is deleted as part of the cutover.

**Tech Stack:** GitHub Actions, mkdocs + mkdocs-material, `just`, `uv` / `uvx`, GitHub Pages.

**Spec:** [`planning/specs/2026-06-08-mkdocs-gh-pages-migration-design.md`](../specs/2026-06-08-mkdocs-gh-pages-migration-design.md)

---

## Working assumptions

- You are working on a branch off `main` (not directly on `main`). If unsure, create one: `git checkout -b docs/migrate-to-gh-pages`.
- `just`, `uv` (which provides `uvx`), and Python ≥3.11 are installed locally.
- DNS for `httpware.modern-python.org` and the Settings → Pages bootstrap are OPERATIONAL prerequisites and are NOT part of this plan — they're called out in the spec for the PR description.
- The current working directory throughout the plan is the repo root: `/Users/kevinsmith/src/pypi/httpware` (or your equivalent checkout).

## File map

**Create:**
- `docs/CNAME` — pins the custom domain.
- `.github/workflows/docs.yml` — GitHub Actions deploy workflow.

**Modify:**
- `Justfile` — add `docs-deploy` recipe.
- `mkdocs.yml` — flip `site_url`.
- `pyproject.toml` — flip `docs` project URL.
- `CONTRIBUTING.md` — flip docs link, drop RTD versioning path.
- `planning/engineering.md` — flip RTD URL.
- `docs/recipes/modern-di.md` — flip two dead `modern-di.readthedocs.io` URLs.
- `planning/plans/2026-06-06-modern-di-recipe-plan.md` — flip two dead modern-di URLs.
- `planning/specs/2026-06-06-modern-di-recipe-design.md` — flip one dead modern-di URL.

**Delete:**
- `.readthedocs.yaml`.

---

## Task 1: Add the `docs-deploy` recipe to the Justfile

**Files:**
- Modify: `Justfile`

- [ ] **Step 1: Append the recipe to the Justfile**

Append to the bottom of `Justfile` (after the existing `publish:` recipe):

```
# Force-pushes built site to gh-pages; CI runs this on push to main.
# Manual invocation from a stale checkout will roll the live site back.
docs-deploy:
    uvx --with-requirements docs/requirements.txt mkdocs gh-deploy --force
```

The comment is intentional — `--force` makes local invocation destructive if `main` is stale.

- [ ] **Step 2: Verify the recipe is registered**

Run: `just --list`

Expected output includes:
```
Available recipes:
    default
    docs-deploy   # Force-pushes built site to gh-pages; CI runs this on push to main.
    install
    lint
    lint-ci
    publish
    test *args
    test-branch
```

- [ ] **Step 3: Smoke-test that the mkdocs build still succeeds with the current config**

This catches any pre-existing site-build failure before the cutover changes. Run:

```
uvx --with-requirements docs/requirements.txt mkdocs build --strict --site-dir /tmp/httpware-docs-smoke
```

Expected: `INFO    -  Documentation built in <N>s` with no warnings (because `--strict`).

If this fails with broken-link warnings unrelated to this PR, STOP and surface them — that's a pre-existing problem, not a migration issue.

- [ ] **Step 4: Commit**

```bash
git add Justfile
git commit -m "build(just): add docs-deploy recipe for mkdocs gh-deploy"
```

---

## Task 2: Add `docs/CNAME` to pin the custom domain

**Files:**
- Create: `docs/CNAME`

- [ ] **Step 1: Create the file**

Content of `docs/CNAME` (single line, no trailing data):

```
httpware.modern-python.org
```

- [ ] **Step 2: Verify mkdocs treats it as a static asset**

Run: `uvx --with-requirements docs/requirements.txt mkdocs build --strict --site-dir /tmp/httpware-docs-smoke`

Then check the build output includes the CNAME file at the root:

```bash
test -f /tmp/httpware-docs-smoke/CNAME && cat /tmp/httpware-docs-smoke/CNAME
```

Expected: prints `httpware.modern-python.org`. If the file is absent, mkdocs is not copying it — abort and investigate before continuing.

- [ ] **Step 3: Commit**

```bash
git add docs/CNAME
git commit -m "docs(cname): pin httpware.modern-python.org for GitHub Pages"
```

---

## Task 3: Flip `site_url` in `mkdocs.yml`

**Files:**
- Modify: `mkdocs.yml` line 2

- [ ] **Step 1: Edit the file**

Change line 2 of `mkdocs.yml` from:

```yaml
site_url: https://httpware.readthedocs.io/
```

to:

```yaml
site_url: https://httpware.modern-python.org
```

(No trailing slash, matching the modern-di convention.)

- [ ] **Step 2: Verify the build still passes and the new URL is baked in**

Run: `uvx --with-requirements docs/requirements.txt mkdocs build --strict --site-dir /tmp/httpware-docs-smoke`

Expected: build succeeds. Then confirm the new URL is embedded:

```bash
grep -c "httpware.modern-python.org" /tmp/httpware-docs-smoke/index.html
```

Expected: a positive integer (the URL appears in canonical/og meta tags).

```bash
grep -c "httpware.readthedocs.io" /tmp/httpware-docs-smoke/index.html
```

Expected: `0`. If positive, find the leftover reference and resolve it before proceeding.

- [ ] **Step 3: Commit**

```bash
git add mkdocs.yml
git commit -m "docs(mkdocs): switch site_url to httpware.modern-python.org"
```

---

## Task 4: Update the `docs` project URL in `pyproject.toml`

**Files:**
- Modify: `pyproject.toml` line 42

- [ ] **Step 1: Edit the file**

Change line 42 of `pyproject.toml` from:

```toml
docs = "https://httpware.readthedocs.io"
```

to:

```toml
docs = "https://httpware.modern-python.org"
```

- [ ] **Step 2: Verify the project still resolves**

Run: `uv lock --check`

Expected: exits 0 with no output (or a brief "Resolved N packages in <time>" line). If it errors with anything other than network issues, the TOML edit went wrong — re-check the file.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "build(pyproject): point project.urls.docs at GitHub Pages site"
```

---

## Task 5: Update the docs URL in `CONTRIBUTING.md`

**Files:**
- Modify: `CONTRIBUTING.md` line 4

- [ ] **Step 1: Edit the file**

Change line 4 of `CONTRIBUTING.md` from:

```
**https://httpware.readthedocs.io/en/latest/dev/contributing/**
```

to:

```
**https://httpware.modern-python.org/dev/contributing/**
```

(The `/en/latest/` segment is ReadTheDocs-specific versioning; GH Pages serves the site at the root, and the page lives at `dev/contributing.md` per `mkdocs.yml`.)

- [ ] **Step 2: Confirm the target path matches `mkdocs.yml`**

Run:

```bash
grep -A1 "Development:" mkdocs.yml
```

Expected output contains `Contributing: dev/contributing.md`. This confirms the URL `httpware.modern-python.org/dev/contributing/` resolves to the same page as before.

- [ ] **Step 3: Commit**

```bash
git add CONTRIBUTING.md
git commit -m "docs(contributing): repoint at GitHub Pages docs URL"
```

---

## Task 6: Update `planning/engineering.md` reference

**Files:**
- Modify: `planning/engineering.md` line 145

- [ ] **Step 1: Edit the file**

On line 145 of `planning/engineering.md`, change:

```
`6-2` docs site live at <https://httpware.readthedocs.io/>
```

to:

```
`6-2` docs site live at <https://httpware.modern-python.org/>
```

(Keep the trailing slash — it's the angle-bracket autolink form.)

- [ ] **Step 2: Verify there are no remaining `httpware.readthedocs.io` references**

Run:

```bash
grep -rn "httpware.readthedocs.io" . --include="*.md" --include="*.toml" --include="*.yml" --include="*.yaml" --include="*.json" --include="*.txt" --include="Justfile" 2>/dev/null | grep -v "\.venv\|\.git\|planning/archive\|planning/audit"
```

Expected: zero matches (excluding `.readthedocs.yaml` itself, which we delete in Task 9).

Run again, without excluding `.readthedocs.yaml`:

```bash
grep -rn "httpware.readthedocs.io" . --include="*.md" --include="*.toml" --include="*.yml" --include="*.yaml" --include="*.json" --include="*.txt" --include="Justfile" 2>/dev/null | grep -v "\.venv\|\.git"
```

If anything in active (non-`planning/archive`, non-`planning/audit`) files shows up, fix it before continuing.

- [ ] **Step 3: Commit**

```bash
git add planning/engineering.md
git commit -m "docs(planning): repoint engineering.md docs URL"
```

---

## Task 7: Fix dead `modern-di.readthedocs.io` URLs in live docs

**Files:**
- Modify: `docs/recipes/modern-di.md` lines 37 and 138

- [ ] **Step 1: Edit line 37**

Change:

```
See the [`modern-di` factories docs](https://modern-di.readthedocs.io/providers/factories/) for the broader `CacheSettings` story (scopes, `clear_cache`, sync vs async finalizers).
```

to:

```
See the [`modern-di` factories docs](https://modern-di.modern-python.org/providers/factories/) for the broader `CacheSettings` story (scopes, `clear_cache`, sync vs async finalizers).
```

- [ ] **Step 2: Edit line 138**

Change:

```
- **[`modern-di` factories](https://modern-di.readthedocs.io/providers/factories/)** — `CacheSettings`, scopes, the broader provider story.
```

to:

```
- **[`modern-di` factories](https://modern-di.modern-python.org/providers/factories/)** — `CacheSettings`, scopes, the broader provider story.
```

- [ ] **Step 3: Verify no remaining `modern-di.readthedocs.io` in `docs/`**

Run:

```bash
grep -rn "modern-di.readthedocs.io" docs/ 2>/dev/null
```

Expected: zero matches.

- [ ] **Step 4: Rebuild the docs to confirm no broken links from this change**

Run: `uvx --with-requirements docs/requirements.txt mkdocs build --strict --site-dir /tmp/httpware-docs-smoke`

Expected: build succeeds. (mkdocs does not validate external URLs — this is just a "did I break the markdown?" check.)

- [ ] **Step 5: Commit**

```bash
git add docs/recipes/modern-di.md
git commit -m "docs(recipes): retarget modern-di factories link at its new GH Pages site"
```

---

## Task 8: Fix dead `modern-di.readthedocs.io` URLs in planning artifacts

**Files:**
- Modify: `planning/plans/2026-06-06-modern-di-recipe-plan.md` lines 207 and 307
- Modify: `planning/specs/2026-06-06-modern-di-recipe-design.md` line 209

- [ ] **Step 1: Edit `planning/plans/2026-06-06-modern-di-recipe-plan.md` line 207**

Change:

```
See the [`modern-di` factories docs](https://modern-di.readthedocs.io/providers/factories/) for the broader `CacheSettings` story (scopes, `clear_cache`, sync vs async finalizers).
```

to:

```
See the [`modern-di` factories docs](https://modern-di.modern-python.org/providers/factories/) for the broader `CacheSettings` story (scopes, `clear_cache`, sync vs async finalizers).
```

- [ ] **Step 2: Edit `planning/plans/2026-06-06-modern-di-recipe-plan.md` line 307**

Change:

```
- **[`modern-di` factories](https://modern-di.readthedocs.io/providers/factories/)** — `CacheSettings`, scopes, the broader provider story.
```

to:

```
- **[`modern-di` factories](https://modern-di.modern-python.org/providers/factories/)** — `CacheSettings`, scopes, the broader provider story.
```

- [ ] **Step 3: Edit `planning/specs/2026-06-06-modern-di-recipe-design.md` line 209**

Change:

```
- `modern-di` **Factories** docs (https://modern-di.readthedocs.io/providers/factories/) — `CacheSettings`, scopes, the broader provider story.
```

to:

```
- `modern-di` **Factories** docs (https://modern-di.modern-python.org/providers/factories/) — `CacheSettings`, scopes, the broader provider story.
```

- [ ] **Step 4: Verify no remaining `modern-di.readthedocs.io` references outside archive**

Run:

```bash
grep -rn "modern-di.readthedocs.io" . --include="*.md" 2>/dev/null | grep -v "\.venv\|\.git\|planning/archive\|planning/audit"
```

Expected: zero matches.

- [ ] **Step 5: Commit**

```bash
git add planning/plans/2026-06-06-modern-di-recipe-plan.md planning/specs/2026-06-06-modern-di-recipe-design.md
git commit -m "docs(planning): retarget modern-di factories link in planning artifacts"
```

---

## Task 9: Delete `.readthedocs.yaml`

**Files:**
- Delete: `.readthedocs.yaml`

- [ ] **Step 1: Remove the file via git**

Run:

```bash
git rm .readthedocs.yaml
```

Expected: `rm '.readthedocs.yaml'`.

- [ ] **Step 2: Confirm the file is gone and staged for removal**

Run: `git status`

Expected: under "Changes to be committed:" you see `deleted:   .readthedocs.yaml`.

- [ ] **Step 3: Commit**

```bash
git commit -m "build(rtd): drop .readthedocs.yaml; cutting over to GitHub Pages"
```

---

## Task 10: Add the GitHub Actions deploy workflow

**Files:**
- Create: `.github/workflows/docs.yml`

- [ ] **Step 1: Create the workflow file**

Write to `.github/workflows/docs.yml`:

```yaml
name: Deploy Docs

on:
  push:
    branches: [main]
    paths:
      - "docs/**"
      - "mkdocs.yml"
      - ".github/workflows/docs.yml"
  workflow_dispatch:

concurrency:
  group: docs-deploy
  cancel-in-progress: true

permissions:
  contents: write

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: extractions/setup-just@v2
      - uses: astral-sh/setup-uv@v3
      - run: just docs-deploy
```

This is the exact contents of `modern-di/.github/workflows/docs.yml` (commit `a3c5aa7` on 2026-06-07). Key elements:

- `fetch-depth: 0` — `mkdocs gh-deploy` needs full history to manage the `gh-pages` branch.
- `permissions: contents: write` — required to push `gh-pages`.
- `concurrency` block — newer runs supersede older in-flight ones to avoid racing force-pushes.
- Path filters keep code-only PRs from triggering a docs rebuild.

- [ ] **Step 2: Validate the YAML parses**

Run:

```bash
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/docs.yml'))" && echo "YAML OK"
```

Expected: `YAML OK`.

- [ ] **Step 3: Sanity-check the workflow side-by-side against modern-di's**

Run:

```bash
diff .github/workflows/docs.yml ../modern-di/.github/workflows/docs.yml
```

Expected: no output (files identical). If the path `../modern-di` doesn't exist on this machine, skip — the YAML validation in step 2 is the load-bearing check.

- [ ] **Step 4: Final mkdocs strict build**

One last local rebuild to confirm everything still composes:

```bash
uvx --with-requirements docs/requirements.txt mkdocs build --strict --site-dir /tmp/httpware-docs-smoke
test -f /tmp/httpware-docs-smoke/CNAME && grep -q "httpware.modern-python.org" /tmp/httpware-docs-smoke/CNAME && echo "CNAME present and correct"
grep -q "httpware.modern-python.org" /tmp/httpware-docs-smoke/index.html && echo "site_url baked into index.html"
```

Expected: `CNAME present and correct` and `site_url baked into index.html`, with no warnings from `mkdocs build --strict`.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/docs.yml
git commit -m "ci(docs): add GitHub Pages deploy workflow for mkdocs"
```

---

## Task 11: Open the PR

**Files:** none

- [ ] **Step 1: Push the branch**

```bash
git push -u origin HEAD
```

- [ ] **Step 2: Open the PR with operational prerequisites in the description**

```bash
gh pr create --title "docs: migrate to GitHub Pages (httpware.modern-python.org)" --body "$(cat <<'EOF'
## Summary

- Replaces ReadTheDocs with GitHub Pages as the authoritative docs host, modeled on the sibling `modern-di` setup.
- New URL: `https://httpware.modern-python.org`.
- Adds `.github/workflows/docs.yml`, `docs/CNAME`, and a `docs-deploy` recipe in the Justfile.
- Deletes `.readthedocs.yaml` (clean cutover).
- Repoints all references: `mkdocs.yml`, `pyproject.toml`, `CONTRIBUTING.md`, `planning/engineering.md`. Also fixes already-dead `modern-di.readthedocs.io` URLs in `docs/recipes/modern-di.md` and two planning artifacts.

Spec: `planning/specs/2026-06-08-mkdocs-gh-pages-migration-design.md`

## Operational prerequisites (NOT in this diff)

These must be done by a repo admin around the merge — flagging here so they don't get forgotten:

1. **DNS**: add a `CNAME` record `httpware.modern-python.org` → `modern-python.github.io` on the `modern-python.org` zone.
2. **First-deploy bootstrap**: after the first workflow run, go to **Settings → Pages** and set **Source = Deploy from a branch**, **Branch = `gh-pages` / (root)**.
3. **HTTPS**: once Pages serves the custom domain, tick **Enforce HTTPS** in Settings → Pages.

## Follow-up (separate work, not blocking merge)

- Archive the ReadTheDocs project at `readthedocs.org/projects/httpware/` so the old URL stops serving stale content.

## Test plan

- [ ] Mkdocs `--strict` build succeeds locally.
- [ ] `CNAME` lands in the built site at root.
- [ ] `httpware.modern-python.org` baked into `index.html`.
- [ ] After merge: `Deploy Docs` workflow run on `main` succeeds.
- [ ] After admin completes prereqs above: `https://httpware.modern-python.org/` loads and matches current RTD content.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Expected: PR URL printed. Capture it for handoff.

- [ ] **Step 3: Confirm the diff is what you expect**

Run:

```bash
gh pr diff
```

Expected files in the diff (skim, don't memorize): `.github/workflows/docs.yml` (added), `.readthedocs.yaml` (deleted), `CONTRIBUTING.md`, `Justfile`, `docs/CNAME` (added), `docs/recipes/modern-di.md`, `mkdocs.yml`, `planning/engineering.md`, `planning/plans/2026-06-06-modern-di-recipe-plan.md`, `planning/specs/2026-06-06-modern-di-recipe-design.md`, `pyproject.toml`.

That's 11 files total (1 added workflow + 1 added CNAME + 1 deleted RTD config + 8 modified). No surprises.

---

## Post-merge verification (for the human, not the agent)

These steps happen on `main` after the PR merges, in coordination with the repo admin completing the DNS + Settings → Pages prerequisites. They are NOT executed by the implementation agent.

1. Watch the first `Deploy Docs` workflow run on `main` succeed.
2. Confirm `git ls-remote origin gh-pages` returns a non-empty SHA (branch was created).
3. Confirm the `gh-pages` branch contains `CNAME` with `httpware.modern-python.org`.
4. After admin sets Pages source + DNS resolves, load `https://httpware.modern-python.org/` and verify content matches the previous RTD site.
5. Push a trivial docs edit in a follow-up commit; confirm the workflow re-triggers and the live site updates within ~2 minutes.

If any post-merge step fails, the rollback is `git revert` of the merge commit. ReadTheDocs remains live and unaltered until manually archived, so reverting cleanly restores the prior state.
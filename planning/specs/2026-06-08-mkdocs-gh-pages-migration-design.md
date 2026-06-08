# Spec: Migrate docs hosting from ReadTheDocs to GitHub Pages

**Date:** 2026-06-08
**Topic slug:** `mkdocs-gh-pages-migration`
**Status:** Approved, awaiting plan

## Goal

Replace ReadTheDocs (`httpware.readthedocs.io`) with GitHub Pages (`httpware.modern-python.org`) as the authoritative host for the mkdocs site, modeled on `modern-di`'s setup. Single structural PR — docs content unchanged.

## Motivation

- Parity with the sibling `modern-di` project, which already runs this pipeline.
- Custom subdomain on `modern-python.org` reads as part of the org rather than a generic ReadTheDocs project.
- Removes ReadTheDocs as a third-party build dependency; the workflow lives in the repo alongside `ci.yml` / `publish.yml`.

## Non-goals

- Archiving the ReadTheDocs project on `readthedocs.org` (manual web-UI action; flagged as a post-merge follow-up).
- Changing docs content, navigation, or theme.
- Versioned docs (mkdocs `mike` style). Site stays single-version, latest-only.

## Architecture

```
push to main (docs/** | mkdocs.yml | .github/workflows/docs.yml changed)
        │
        ▼
 docs.yml workflow ── checkout (fetch-depth: 0) ── setup-just ── setup-uv
        │
        ▼
 just docs-deploy  →  uvx --with-requirements docs/requirements.txt mkdocs gh-deploy --force
        │
        ▼
 mkdocs writes built site to gh-pages branch (force-push)
        │
        ▼
 GitHub Pages serves gh-pages, sees docs/CNAME → routes httpware.modern-python.org
```

This is a direct mirror of `modern-di`'s pipeline (its current `docs.yml`, last touched 2026-06-07 in commit `a3c5aa7`).

## File changes

### Add

- **`.github/workflows/docs.yml`** — verbatim port of `modern-di/.github/workflows/docs.yml`:
  - Triggers: `push` to `main` filtered on `docs/**`, `mkdocs.yml`, `.github/workflows/docs.yml`; plus `workflow_dispatch` for manual reruns.
  - `concurrency: { group: docs-deploy, cancel-in-progress: true }` so newer runs supersede older in-flight ones.
  - `permissions: contents: write` — required for `mkdocs gh-deploy --force` to push the `gh-pages` branch.
  - Single `deploy` job: `actions/checkout@v4` with `fetch-depth: 0`, `extractions/setup-just@v2`, `astral-sh/setup-uv@v3`, `just docs-deploy`.

- **`docs/CNAME`** — single line `httpware.modern-python.org`. Lives under `docs/` so mkdocs treats it as a static asset and copies it into the built site on every deploy. Without this, every `gh-deploy --force` wipes the custom-domain setting GitHub stores on `gh-pages` (modern-di learned this the hard way in commit `5eac5fa`).

- **Justfile `docs-deploy` recipe** — append:
  ```
  # Force-pushes built site to gh-pages; CI runs this on push to main.
  # Manual invocation from a stale checkout will roll the live site back.
  docs-deploy:
      uvx --with-requirements docs/requirements.txt mkdocs gh-deploy --force
  ```
  Uses `uvx` (not `uv run`) so CI doesn't need a full project `uv sync` just to publish docs. The warning comment is intentional — `--force` makes local invocation from an out-of-date `main` destructive.

### Modify

- **`mkdocs.yml`** line 2: `site_url: https://httpware.readthedocs.io/` → `site_url: https://httpware.modern-python.org`.
- **`pyproject.toml`** line 42: `docs = "https://httpware.readthedocs.io"` → `docs = "https://httpware.modern-python.org"`.
- **`CONTRIBUTING.md`** line 4: `https://httpware.readthedocs.io/en/latest/dev/contributing/` → `https://httpware.modern-python.org/dev/contributing/`. Drop the `/en/latest/` segment — that's ReadTheDocs versioning; GH Pages serves at the root.
- **`planning/engineering.md`** line 145: replace RTD URL with the new one.
- **`docs/recipes/modern-di.md`** lines 37 and 138: replace `https://modern-di.readthedocs.io/providers/factories/` with `https://modern-di.modern-python.org/providers/factories/`. (modern-di already moved to GH Pages; its RTD URL is dead.)
- **`planning/plans/2026-06-06-modern-di-recipe-plan.md`** lines 207 and 307, and **`planning/specs/2026-06-06-modern-di-recipe-design.md`** line 209: same modern-di URL replacement.

### Delete

- **`.readthedocs.yaml`** — RTD config file. After deletion, RTD will keep building from the latest commit it saw, but the project effectively becomes unmaintained.

### Unchanged

- **`docs/requirements.txt`** — already `mkdocs` + `mkdocs-material`, identical to modern-di's. Consumed by `uvx --with-requirements`.
- All other files in `docs/`, the existing `ci.yml` and `publish.yml` workflows.

## Operational prerequisites (NOT code changes — flag in PR description)

These must happen for the deployed site to actually serve. They are outside the PR's diff but inside the work's scope.

1. **DNS:** A `CNAME` record for `httpware.modern-python.org` → `modern-python.github.io` must exist before the custom domain resolves. Org-level action on `modern-python.org`'s DNS.
2. **First-deploy bootstrap:** The `gh-pages` branch doesn't exist yet. The first workflow run creates it via `gh-deploy --force`. After it runs, a repo admin must go to **Settings → Pages** and set **Source = Deploy from a branch**, **Branch = `gh-pages` / (root)**. One-time manual step; can't be done from a workflow.
3. **HTTPS:** Once Pages serves the custom domain, tick **Enforce HTTPS** in Settings → Pages (auto-eligible after Let's Encrypt provisions).

## Post-merge follow-ups (out of scope for this PR)

1. **Archive the ReadTheDocs project** at `readthedocs.org/projects/httpware/` so `httpware.readthedocs.io` stops serving stale content. Manual web-UI action.
2. Update any external references that point at the old URL (PyPI project page picks up `pyproject.toml` automatically on next publish; GitHub repo "About" sidebar may need a manual nudge).

## Edge cases and verification

- **Concurrency:** `cancel-in-progress: true` on the `docs-deploy` group prevents two simultaneous force-pushes racing each other.
- **CNAME preservation:** Verified by inspecting the `gh-pages` branch after the first deploy — `CNAME` must be present at root with the custom domain.
- **Path filter correctness:** The workflow trigger watches `docs/**`, `mkdocs.yml`, and `.github/workflows/docs.yml`. Other changes (code, tests, planning) won't trigger a docs rebuild — matches modern-di's behavior.
- **Manual local rollback risk:** `just docs-deploy` from a developer machine on a stale `main` will roll the live site back. The warning comment in the Justfile is the only mitigation; we accept this trade-off (modern-di does too) because the alternative — locking the recipe behind an env check — adds complexity disproportionate to the risk.

## Testing

The workflow itself can't be unit-tested. Verification path:

1. After merge, watch the first `Deploy Docs` workflow run on `main` succeed.
2. Confirm the `gh-pages` branch exists and contains `CNAME` with the custom domain.
3. Complete the operational prerequisites (DNS + Settings → Pages).
4. Load `https://httpware.modern-python.org/` and verify the rendered site matches the current RTD content.
5. Touch a doc file in a follow-up PR; confirm the workflow re-triggers and the site updates.

If any step fails, the rollback is to revert the PR — RTD remains live and unaltered, so the old URL keeps serving.

## Scope check

This is a single-PR structural change. No decomposition needed. Aligns with the stated preference: clean cutover landing as one structural PR before any substantive follow-up work.

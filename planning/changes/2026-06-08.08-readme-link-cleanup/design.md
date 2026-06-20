---
status: shipped
date: 2026-06-08
slug: readme-link-cleanup
summary: README link cleanup
supersedes: null
superseded_by: null
pr: 39
outcome: 'README link cleanup'
---

# Spec: README + top-level link cleanup, plus one-shot link audit

**Date:** 2026-06-08
**Topic slug:** `readme-link-cleanup`
**Status:** Approved, awaiting plan

## Goal

Fix repo-relative and bare-`.md` links in user-facing top-level files (README, CONTRIBUTING) so they point at the rendered docs site and work across all rendering contexts (GitHub, PyPI, anywhere README is shown). One-shot sweep for additional broken or stale links in the docs site as a side activity, fix anything surfaced, ship as a single PR.

## Motivation

The README is also the PyPI long description. PyPI does not resolve repo-relative paths, so any `[text](docs/foo.md)` or `[text](./LICENSE)` link in the README is broken for users browsing pypi.org/project/httpware. The links also degrade the user experience on GitHub (they navigate into raw `.md` source instead of the rendered docs site).

User reported: "in readme there are links to just md files in repo, but should be to docs rendered." This spec captures the fix plus a small audit of nearby link health.

## Non-goals

- Re-validating docs content correctness. The 2026-06-07 deep audit (closed in 0.8.3–0.8.6) already covered that.
- Re-running code-example validation. Same reason.
- Adding link-checking to CI. This is a one-shot, not a permanent gate.
- Changing the mkdocs intra-doc `.md`-link convention (e.g., `[Errors reference](errors.md)` inside `docs/*.md`). Mkdocs rewrites these to `href="../errors/"` at build time. Changing them would break `mkdocs serve` and produce no benefit.

## Findings (pre-spec audit)

Top-level user-facing files inspected: `README.md`, `CONTRIBUTING.md`, `SECURITY.md`, `docs/*.md`, `docs/recipes/*.md`, `docs/dev/*.md`.

| File | Line | Current | Issue | Fix |
|---|---|---|---|---|
| `README.md` | 91 | `[Middleware guide](docs/middleware.md)` | Repo-relative `.md` link. Broken on PyPI; routes to raw GitHub markdown on github.com instead of the rendered docs page. | → `https://httpware.modern-python.org/middleware/` (verified 200) |
| `README.md` | 142 | `[License](./LICENSE)` | Relative path. Resolves on GitHub, broken on PyPI. | → `https://github.com/modern-python/httpware/blob/main/LICENSE` (absolute, works everywhere) |
| `CONTRIBUTING.md` | 6 | `[\`docs/dev/contributing.md\`](docs/dev/contributing.md)` | Repo-relative `.md` link in a "Source:" pointer. Works on GitHub-rendered CONTRIBUTING; broken anywhere else; not the link a reader wants (line 4 already points at the rendered docs URL). | → `https://github.com/modern-python/httpware/blob/main/docs/dev/contributing.md` (absolute GitHub URL) |
| `SECURITY.md` | — | Single absolute URL only | No issue | — |
| `docs/**/*.md` intra-doc `[…](*.md)` links | many | All use `.md` extension | Standard mkdocs convention; rewritten to clean URLs at build | **No change** |
| `docs/index.md` | 174 | Absolute GitHub URL to `planning/engineering.md` | Correct — engineering.md is intentionally not in the published site | — |
| `CLAUDE.md` | 11, 12, 95 | Repo-relative `planning/*.md` links | Internal AI-guidance file, not user-facing | — |

## Architecture

Plain text edits to three lines in two files, plus a one-shot external-link audit of the built docs site.

```
┌─ Fix top-level user-facing links ──┐    ┌─ One-shot link audit ──────────────────┐
│ README.md:91   → rendered URL      │    │ uvx --from lychee lychee <built site>  │
│ README.md:142  → absolute GitHub   │    │  + filter for known-failing patterns   │
│ CONTRIBUTING.md:6 → absolute GitHub│    │ Triage:                                 │
└────────────────────────────────────┘    │  - real broken → fix in source         │
                                          │  - false positive (rate-limited /       │
                                          │    transient) → skip                    │
                                          └─────────────────────────────────────────┘
                          │                              │
                          └──────────┬───────────────────┘
                                     ▼
                       mkdocs build --strict (already passes; re-run after edits)
                                     │
                                     ▼
                              Single PR
```

### Three units

1. **README.md edit** — two single-line replacements. Verified targets: `https://httpware.modern-python.org/middleware/` returns 200; absolute GitHub URL to `LICENSE` always works.
2. **CONTRIBUTING.md edit** — one single-line replacement. Absolute GitHub URL to the doc source.
3. **One-shot link audit** — invoke `lychee` (or equivalent — `linkchecker`, `mkdocs-htmlproofer-plugin`) against the built `site/` directory. Don't add it to CI. Triage and fix; report what was found. This MAY surface additional broken external URLs in `docs/`; fix them in the same PR.

### Tool choice for link audit

Recommended: `lychee` via `uvx --from lychee lychee --offline=false /tmp/httpware-site` (Rust-based, fast, modern, good defaults). If `lychee` isn't available via `uvx`, fall back to `linkchecker` (Python, available via `pip`) or `mkdocs-htmlproofer-plugin` (mkdocs plugin run once). The implementation plan picks based on what installs cleanly without further deps.

### Operational risk

Near-zero. All changes are text-only in markdown files. No code changes. No CI changes. Worst case: link audit takes a few minutes to run and we discover a stale link to fix.

## Testing

- After the three edits, render README.md and CONTRIBUTING.md locally (`grip` or VS Code preview) and click each affected link to confirm it resolves.
- `mkdocs build --strict` continues to pass (no docs/ files changed).
- `lychee` (or chosen tool) reports no broken links in the built site, OR all surfaced links have been fixed.
- The live URLs referenced still return 200: `https://httpware.modern-python.org/middleware/`, `https://github.com/modern-python/httpware/blob/main/LICENSE`, `https://github.com/modern-python/httpware/blob/main/docs/dev/contributing.md`.

## Out-of-scope follow-ups

- If the link audit surfaces a structural issue (e.g., many internal docs links pointing to since-renamed pages), capture findings as a follow-up spec rather than expanding scope here.
- Archiving the ReadTheDocs project (unchanged from the GH Pages migration spec — separate manual action).

## Scope check

Single-PR, low-risk change. Three line-edits + a one-shot script run. No decomposition needed.

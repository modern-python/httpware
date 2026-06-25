---
summary: Docs reorg + mkdocs scaffolding
---

# Docs reorg and minimal mkdocs site (design)

- **Date:** 2026-06-02
- **Status:** approved, ready for plan
- **Scope:** Structural reorganization of the repository's documentation surface. Deletes the bmad-era `docs/archive/`, splits agent/contributor workflow artifacts away from user-facing documentation, and introduces a minimal mkdocs site published via Read the Docs (modeled on `modern-di`'s setup). No source code changes. No CI grep invariants change. The `src/` layout stays.
- **Roadmap pointer:** none — this is a one-off structural cutover, not an Epic item. Follows the same "single structural PR before substantive follow-up work" pattern used for the bmad → superpowers transition (`2026-05-31-bmad-to-superpowers-transition-design.md`).

## Why

Today, `docs/` mixes two unrelated layers:

1. **Engineering reference** — `engineering.md`, `deferred-work.md`, `archive/` (≈250 KB of historical bmad-era PRD / architecture / epics / product briefs / per-story specs for 1-1 through 1-5).
2. **Agent workflow artifacts** — `superpowers/specs/`, `superpowers/plans/` (per-feature design + implementation docs, grows every PR).

`modern-di`'s `docs/` is structurally different: it is a published mkdocs site (Read the Docs), with `introduction/`, `providers/`, `integrations/`, `testing/`, `migration/`, `troubleshooting/`, `dev/`. No archive, no workflow artifacts — purely user-facing.

The two repos answer different questions. `httpware`'s current `docs/` is contributor-and-agent-facing; `modern-di`'s is user-facing. This spec aligns `httpware` with the published-docs model used across the `modern-python` org so the project has a public documentation surface ready when 0.2.0 (Epic 3 resilience middleware) ships, while also clearing out the bmad archive that is no longer load-bearing.

Three independent drivers:

- **Archive isn't load-bearing.** `docs/engineering.md` was distilled from the archive on 2026-05-31 and is intended to be self-contained. A grep finds only five soft citations of `archive/` across `engineering.md` and `CLAUDE.md`, all "for original rationale" / "if you need FR/NFR numbers" — no spec or plan in the last month has actually relied on archive content. One citation (`engineering.md` line 40 → `archive/architecture.md` Validation & Decoding) externalizes a rationale that should have been inlined; this spec closes that gap before deletion.
- **Workflow artifacts pollute a published docs tree.** `docs/superpowers/specs/` and `docs/superpowers/plans/` are intentionally tied to a specific Claude Code plugin name. They will not be published, do not belong under a `docs_dir` that mkdocs builds, and should be renamed to something tool-neutral that describes the contents.
- **No published docs site yet.** Pre-0.2 the project has no user-facing landing page beyond the GitHub README. Setting up a minimal mkdocs site now (one quick-start, one engineering page, one contributing page) is cheap and establishes the publishing path before docs content grows.

## Decisions

| Decision | Choice |
| --- | --- |
| Delete `docs/archive/` | Yes — bmad-era artifacts (PRD, architecture, epics, product briefs, stories 1-1 through 1-5) removed entirely. ~250 KB across six files + `stories/` subdir + `sprint-status.yaml` + `README.md`. |
| Inline-before-delete | Yes — `engineering.md` line 40 currently externalizes the "two-pass decoding is rejected" rationale to `archive/architecture.md` § "Validation & Decoding" (around lines 270–283). That rationale (single parse pass, `TypeAdapter.validate_json` cached, `msgspec.json.decode`) gets inlined into `engineering.md` § "Seam 3" (or wherever the decoder rule appears) before archive deletion. |
| Rename `docs/superpowers/` → `planning/` (at repo root) | Tool-neutral name describing the activity. Moves out of `docs/` so the published site doesn't include workflow artifacts. New layout: `planning/specs/`, `planning/plans/`. |
| Move `docs/deferred-work.md` → `planning/deferred-work.md` | It is planning material (review-surfaced not-actionable items), not user docs. Belongs alongside the specs/plans, not in the published site. |
| Move `docs/engineering.md` → `docs/dev/engineering.md` | Becomes part of the published site under a "Development" nav section (mirrors `modern-di`'s `dev/key-concepts.md` pattern). Keeps the engineering reference public for transparency, accessible to outside contributors. |
| Move root `CONTRIBUTING.md` → `docs/dev/contributing.md` | Single source of truth in the published site. |
| Thin root `CONTRIBUTING.md` stub | Yes — keep a one-paragraph root file pointing to the published docs URL and the in-repo source path. Preserves GitHub's "open a PR" UI integration, which surfaces `CONTRIBUTING.md` from the repository root. |
| Root `SECURITY.md` | Unchanged. Stays at root for GitHub Security-tab integration. Small file, no churn warranted. |
| Refactor `README.md` | Yes, slim it and align with `modern-di`'s pattern: project intent, install snippet, runnable first-request example, links to docs site / PyPI / license, `modern-python` org positioning. Single runnable snippet stays so GitHub viewers don't have to click through. |
| Set up minimal mkdocs site | Yes — new `mkdocs.yml`, `.readthedocs.yaml`, `docs/requirements.txt`, `docs/index.md`. Site is published via Read the Docs (RTD project provisioning happens manually post-merge). |
| mkdocs theme | `mkdocs-material` with the same palette pattern as `modern-di` (black/pink, light + dark, header autohide). |
| mkdocs nav (day one) | Two sections: "Quick-Start" (`index.md`) and "Development" (`dev/engineering.md`, `dev/contributing.md`). User-guide nav grows as user-facing pages are written. |
| `docs/requirements.txt` contents | Two lines: `mkdocs` and `mkdocs-material`. `pymdown-extensions` is a transitive dependency of `mkdocs-material`. Matches `modern-di` exactly. |
| Justfile changes | None. Local docs preview is `uv run --with mkdocs --with mkdocs-material mkdocs serve`; CI / RTD installs from `docs/requirements.txt`. Matches `modern-di`. |
| `pyproject.toml` `[dependency-groups]` for docs | None added. Docs tooling isn't a project dependency group. Matches `modern-di`. |
| `src/` layout | Unchanged. PyPA-recommended; flipping to flat layout for `modern-di` parity is rejected — high cost (CI grep regex, every doc path, every existing planning file) for no functional gain. If pursued later, lands as a separate follow-up PR. |
| RTD provisioning | Out of scope. Manual step (create RTD project, point webhook at the repo) tracked as a post-merge follow-up. Documented in the implementation plan's "verification" section. |

## File structure

**New files:**

- `mkdocs.yml` — mkdocs configuration (site name, nav, theme, markdown extensions). Modeled on `modern-di/mkdocs.yml`, trimmed.
- `.readthedocs.yaml` — RTD build config (Ubuntu 22.04, Python 3.12, mkdocs build, install from `docs/requirements.txt`). Modeled on `modern-di/.readthedocs.yaml`.
- `docs/requirements.txt` — `mkdocs\nmkdocs-material\n`.
- `docs/index.md` — quick-start landing page: one-paragraph project intent, `pip install httpware`, one runnable async snippet (basic `AsyncClient.get`), links to engineering notes + contributing.
- `docs/dev/engineering.md` — moved from `docs/engineering.md`; one inline edit (the Decoder rationale formerly externalized to archive).
- `docs/dev/contributing.md` — moved from root `CONTRIBUTING.md`, content unchanged.
- `planning/specs/` — moved from `docs/superpowers/specs/`. Contains every existing spec including this one (which itself moves as part of the migration).
- `planning/plans/` — moved from `docs/superpowers/plans/`.
- `planning/deferred-work.md` — moved from `docs/deferred-work.md`.

**Modified files:**

- `README.md` — refactored. Slimmer, modern-python org positioning, docs site link, single runnable snippet. Project intent and CI-enforced invariants summary preserved.
- `CONTRIBUTING.md` (root) — replaced with a thin stub: one paragraph pointing to `https://httpware.readthedocs.io/en/latest/dev/contributing/` and `docs/dev/contributing.md` as the in-repo source path.
- `CLAUDE.md` — every path reference updated: `docs/engineering.md` → `docs/dev/engineering.md`; `docs/superpowers/specs/` → `planning/specs/`; `docs/superpowers/plans/` → `planning/plans/`; `docs/archive/` references removed (two lines); `docs/deferred-work.md` → `planning/deferred-work.md`. The "Where to find what" bullet list and the "Per-feature workflow" line both touched.
- `docs/dev/engineering.md` — in addition to the move, two edits: (a) the line 3 archive pointer is removed (archive no longer exists); (b) the line 40 "see `archive/architecture.md` Validation & Decoding for rationale" pointer becomes an inlined paragraph describing the single-parse-pass principle, the `TypeAdapter.validate_json` cached pattern, and the `msgspec.json.decode` alternative. The roadmap-pointer references to `archive/epics.md` and `archive/stories/` are removed (a single sentence noting "story IDs map to the bmad-era epic structure, retained as a stable identifier convention" replaces them).
- Every existing file under `planning/specs/` and `planning/plans/` — path references updated where they cite `docs/superpowers/specs/`, `docs/superpowers/plans/`, `docs/engineering.md`, `docs/archive/`, or `docs/deferred-work.md`. Expected to be ≤30 edits across ≈20 files; mechanical search-and-replace.

**Deleted files:**

- `docs/archive/` (entire subtree): `README.md`, `architecture.md`, `epics.md`, `prd.md`, `product-brief-httpware.md`, `product-brief-httpware-distillate.md`, `stories/1-1-project-scaffold-and-tooling.md`, `stories/1-2-core-data-types.md`, `stories/1-3-exception-hierarchy-with-plain-fields.md`, `stories/1-4-transport-protocol-and-httpx2transport-adapter.md`, `stories/1-5-responsedecoder-protocol-and-pydantic-adapter.md`, `stories/sprint-status.yaml`.
- `docs/engineering.md` (moved to `docs/dev/engineering.md` — git history follows the move).
- `docs/deferred-work.md` (moved to `planning/deferred-work.md`).
- `docs/superpowers/` (entire subtree, after contents move to `planning/`).

## Migration order (dependencies)

The implementation plan will spell out exact commands and per-step verification. High-level dependency order:

1. **Inline the load-bearing archive citation** into `docs/engineering.md` (still at its current path at this point). Verifies nothing in archive is needed before the deletion step.
2. **Move workflow artifacts:** `docs/superpowers/specs/` → `planning/specs/`, `docs/superpowers/plans/` → `planning/plans/`, `docs/deferred-work.md` → `planning/deferred-work.md`. Use `git mv` so history is preserved.
3. **Move engineering refs:** `docs/engineering.md` → `docs/dev/engineering.md`, root `CONTRIBUTING.md` → `docs/dev/contributing.md`.
4. **Bulk path-reference update:** `CLAUDE.md`, every file under `planning/specs/`, `planning/plans/`, the new `docs/dev/engineering.md`, and `README.md`. Mechanical replacement.
5. **Refactor README.md** — content edit (not just paths).
6. **Add new files:** `mkdocs.yml`, `.readthedocs.yaml`, `docs/requirements.txt`, `docs/index.md`, the thin root `CONTRIBUTING.md` stub.
7. **Delete `docs/archive/`** — last step, after everything else verified.
8. **Verification:** `just lint-ci` and `just test` both pass; `uv run --with mkdocs --with mkdocs-material mkdocs build --strict` builds with zero broken internal links and zero warnings.

## Out of scope

- **User-guide content** beyond the index page. Writing real user-facing documentation (installation specifics, `AsyncClient` API guide, middleware tour, decoder configuration, transport mocking, error handling) is follow-up work — separate specs after the structural cutover lands. The site exists with a Quick-Start + Development section only.
- **RTD project provisioning.** Creating the RTD project, configuring the webhook, setting the default branch, claiming the `httpware.readthedocs.io` subdomain — manual steps performed once after the PR merges. Plan will list them as post-merge instructions.
- **`src/` → flat layout flip.** Explicitly rejected for this spec; if pursued, separate follow-up PR.
- **CHANGELOG / GitHub Releases changes.** Release-notes pipeline (per memory: bare-semver tag convention, no CHANGELOG, notes on GitHub Releases) is unchanged.
- **SECURITY.md edits.** Unchanged for this PR.
- **mkdocs custom CSS / branding** beyond the material theme defaults + black/pink palette. Visual polish is follow-up.
- **mkdocs versioned documentation** (`mike` plugin). Not needed pre-1.0.
- **Adding `mkdocs build --strict` to CI.** Possible follow-up; for this PR the build is verified locally only.

## Verification

- `just lint-ci` exits 0 (no ruff/format/ty regressions from the moved file paths).
- `just test` exits 0 (no test references any moved path; tests do not depend on `docs/`).
- `uv run --with mkdocs --with mkdocs-material mkdocs build --strict` exits 0 with zero warnings (catches broken internal links between `index.md` ↔ `dev/engineering.md` ↔ `dev/contributing.md`).
- Manual: `grep -rn "docs/archive\|docs/superpowers\|docs/engineering\|docs/deferred-work" . --exclude-dir=.git --exclude-dir=.venv | grep -v "2026-06-02-docs-reorg-and-mkdocs-design.md"` returns no results (this spec itself self-references the old paths in its "Why" section and is the only allowed match).
- Manual: `git log --follow docs/dev/engineering.md` shows the full history of the original `docs/engineering.md` (validates the move preserved history).

## Risks

- **Stale path references in existing planning artifacts.** Risk: a spec or plan in `planning/specs/` or `planning/plans/` references `docs/superpowers/...` or `docs/engineering.md` and gets missed. Mitigation: the bulk-update step (5) is followed by the verification grep above; CI doesn't enforce internal markdown links but the grep does.
- **RTD subdomain claim.** Risk: `httpware.readthedocs.io` is taken or requires the `modern-python` org account. Mitigation: post-merge follow-up; if the canonical subdomain isn't available, the `site_url` in `mkdocs.yml` is updated and the README docs-link adjusted. Low cost.
- **Inlining the decoder rationale incompletely.** Risk: the inlined paragraph misses a nuance from `archive/architecture.md` § Validation & Decoding (NFR3, `TypeAdapter` caching, `msgspec.json.decode`). Mitigation: implementer reads the archived section in full, ports the substance into `docs/dev/engineering.md`, and `git diff` on `docs/dev/engineering.md` is reviewed before archive deletion.

## Related work

- `docs/superpowers/specs/2026-05-31-bmad-to-superpowers-transition-design.md` — established the per-feature workflow that the rename in this spec is renaming away from.
- `docs/engineering.md` — the canonical design reference being moved.
- `modern-di/mkdocs.yml`, `modern-di/.readthedocs.yaml`, `modern-di/docs/requirements.txt` — the model this spec follows.

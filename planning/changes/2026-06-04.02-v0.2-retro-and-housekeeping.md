---
summary: Post-0.2 retro + housekeeping
---

# Spec: v0.2 retrospective and planning/ housekeeping

**Date:** 2026-06-04
**Topic slug:** `v0.2-retro-and-housekeeping`
**Status:** drafted, awaiting user review

## Purpose

Close the books on the v0.2 thin-httpx2-wrapper pivot (shipped 2026-06-04 as PR #20, tag `0.2.0`) before opening the 0.3.0 work cycle. Three deliverables:

1. A written retrospective on the pivot.
2. Cleanup of `planning/` so `specs/` and `plans/` are empty for the next active feature.
3. Triage of `planning/deferred-work.md` so it reflects what is actually in scope for 0.3.0.

Auto-memory updates land as part of the same bundle so future sessions start with an accurate model of the repo.

A separate spec — `planning/specs/2026-06-04-pydantic-optional-extra-design.md` — will cover the 0.3.0 feature work (pydantic as an optional extra + payload-edge tests for `PydanticDecoder`). That spec is **out of scope here**; this one only closes out v0.2.

## Non-goals

- No code changes to `src/httpware/`.
- No version bump, no release.
- No mkdocs site or CI changes.
- No resolution of the `_get_adapter` per-instance scoping question (stays open in `deferred-work.md`).

## Deliverable 1 — Retrospective doc

**Path:** `planning/retros/2026-06-04-v0.2-thin-wrapper-pivot.md`

The `planning/retros/` directory is new; this is the first entry. Future retros (release-level, epic-level) land here with the same date-prefixed naming.

**Required sections:**

1. **What shipped (0.1.0 → 0.2.0).** Bullets citing PR #20, key commits (`ce293c1` tear-down, `974d84c` errors, `635de95` middleware, `ab262b4` AsyncClient construction, `1e4a027` version bump), and `pre-v0.2-pivot` tag as the recovery anchor.
2. **What the pivot bought us.** Concrete wins: surface shrank from 14 files to 8; the `Transport` abstraction is gone; `httpx2.Response` lives inside every `StatusError` (callers get full request/response context for free); `httpx2.MockTransport` replaces the bespoke `RecordedTransport` and cuts a maintenance burden.
3. **What the pivot cost.** Public 0.x break for any consumer of `httpware.Request`/`Response`/`StreamResponse`/`Limits`/`Timeout`/`ClientConfig`/`Transport`/`Httpx2Transport`/`RecordedTransport`. Six specs in `planning/specs/` went from "ship roadmap" to archive material (Story 1-8 RecordedTransport, 2-3 immutability helpers, 2-4 auth coercion, 4-1 StreamResponse, 4-2 transport stream impl, 5-3 Redactor). The auth-coercion feature shipped in Epic 2 and was removed in the same release cycle.
4. **Decisions worth keeping.** The three-seam architecture (AsyncClient ↔ Middleware, AsyncClient ↔ ResponseDecoder, httpware ↔ optional extras). Status-keyed exceptions taking a single positional `response: httpx2.Response`. Single-pass decoder protocol (`decode(content: bytes, model: type[T]) -> T`). Optional-extras pattern (one extra per dedicated module).
5. **Decisions to revisit before 1.0.** Pydantic-required-vs-optional (resolved into 0.3.0 work in a follow-up spec); default-decoder model; periodic `grep -rE 'httpx2\._' src/httpware/` audit on each release.
6. **Lessons.** Three terse lines: writing `engineering.md` *after* the pivot was the right ordering — it captured the actual design instead of an aspirational one; `deferred-work.md` made the pivot's blast radius obvious because every closed item cited a host file that no longer existed; specs survive their own death — `planning/archive/` keeps the road-not-taken legible.

The doc targets ≈1.5 pages. No code blocks beyond minimal commit citations.

## Deliverable 2 — Planning directory cleanup

### 2.1 New directory structure

```
planning/
├── engineering.md
├── deferred-work.md
├── retros/
│   └── 2026-06-04-v0.2-thin-wrapper-pivot.md
├── releases/
│   └── 0.2.0.md
├── specs/          # empty after this PR
├── plans/          # empty after this PR
└── archive/
    ├── specs/      # 15 files
    └── plans/      # 13 files
```

### 2.2 Archive moves (`git mv`, preserves history)

All 15 design specs in `planning/specs/` except `2026-06-03-release-notes-0.2.0.md` get moved to `planning/archive/specs/`:

- `2026-05-31-asyncclient-design.md`
- `2026-05-31-bmad-to-superpowers-transition-design.md`
- `2026-05-31-middleware-protocol-and-chain-design.md`
- `2026-05-31-msgspec-decoder-via-extras-design.md`
- `2026-05-31-phase-shortcut-decorators-design.md`
- `2026-05-31-recordedtransport-design.md`
- `2026-05-31-release-0.1.0-prep-design.md`
- `2026-05-31-request-immutability-helpers-design.md`
- `2026-05-31-shipped-work-review.md`
- `2026-06-01-auth-coercion-design.md`
- `2026-06-02-docs-reorg-and-mkdocs-design.md`
- `2026-06-02-project-hygiene-tidy-design.md`
- `2026-06-03-input-validation-pass-design.md`
- `2026-06-03-thin-httpx2-wrapper-design.md`

All 13 plans in `planning/plans/` get moved to `planning/archive/plans/`:

- `2026-05-31-asyncclient-plan.md`
- `2026-05-31-bmad-to-superpowers-transition-plan.md`
- `2026-05-31-middleware-protocol-and-chain-plan.md`
- `2026-05-31-msgspec-decoder-via-extras-plan.md`
- `2026-05-31-phase-shortcut-decorators-plan.md`
- `2026-05-31-recordedtransport-plan.md`
- `2026-05-31-release-0.1.0-prep-plan.md`
- `2026-05-31-request-immutability-helpers-plan.md`
- `2026-06-01-auth-coercion-plan.md`
- `2026-06-02-docs-reorg-and-mkdocs-plan.md`
- `2026-06-02-project-hygiene-tidy-plan.md`
- `2026-06-03-input-validation-pass-plan.md`
- `2026-06-03-thin-httpx2-wrapper-plan.md`

### 2.3 Release-notes relocation

`planning/specs/2026-06-03-release-notes-0.2.0.md` is misfiled — it's release-note content, not a design. `git mv` it to `planning/releases/0.2.0.md`. The `planning/releases/` directory is new. Future releases land there as `0.3.0.md`, etc.

### 2.4 This spec stays at top level

The current file (`planning/specs/2026-06-04-v0.2-retro-and-housekeeping-design.md`) remains in `planning/specs/` because it is the active design for this PR. After the housekeeping PR merges, it gets archived along with the next batch of delivered specs.

### 2.5 CLAUDE.md update

Update the "Where to find what" bullet list in `CLAUDE.md` (repo root) to reference `planning/archive/`, `planning/retros/`, and `planning/releases/`:

Bullet content (executor should match the existing markdown-link style — `[`path`](path)` — already used in CLAUDE.md):

- `planning/engineering.md` — canonical design reference.
- `planning/deferred-work.md` — review-surfaced items not actionable now.
- `planning/specs/` and `planning/plans/` — per-feature design specs and implementation plans (active work).
- `planning/archive/{specs,plans}/` — shipped/superseded work, kept for historical context.
- `planning/retros/` — release- and epic-level retrospectives.
- `planning/releases/` — per-version release notes (also published on GitHub Releases).

## Deliverable 3 — deferred-work.md triage

### 3.1 Items to delete entirely

These no longer reflect intended direction; remove from `planning/deferred-work.md` rather than keeping them open:

- **"Unpinned `ruff`/`ty` with `select=["ALL"]`"** — current floating-version policy is intentional; CI breakage on new rules will be addressed reactively.
- **"No `[test]` extra; CI installs all extras"** — the bundled install pattern is intentional; the cost is acceptable.

### 3.2 Items to keep open (unchanged)

- **`_get_adapter` `lru_cache` is module-global, not per-decoder instance** — still genuinely deferred (no configurable `PydanticDecoder` exists yet).
- **Empty/malformed payload tests** — folded into the 0.3.0 follow-up spec; mark as "in progress for 0.3.0" rather than deleting, so the trail is visible.

### 3.3 Items to update with progress link

- **"`pydantic` import not guarded the way `msgspec` is"** — annotate with "→ resolved in 0.3.0 by `2026-06-04-pydantic-optional-extra-design.md`" (the follow-up spec). Keep the entry until the follow-up PR merges, then move to a "Closed" section.

### 3.4 Resulting deferred-work.md structure

After this PR:

- **Open / Decoder-side:** `_get_adapter` scoping (1 item).
- **Open / Decoder-side, in progress for 0.3.0:** malformed-payload tests, pydantic optional-extra guard (2 items).
- **Closed by the v0.2 thin-wrapper pivot (2026-06-03):** unchanged (12 items, already present).

## Deliverable 4 — Auto-memory updates

Path: `/Users/kevinsmith/.claude/projects/-Users-kevinsmith-src-pypi-httpware/memory/`.

### 4.1 Edit existing memories

- **`epic_2_complete.md`** — strike "Next ship target is Epic 3 (resilience middleware) for 0.2.0". Replace with: "0.2.0 shipped as the thin-httpx2-wrapper pivot (PR #20, 2026-06-04). Epic 3 (resilience) is the surviving roadmap target post-pivot but is not the next ship."
- **`workflow_superpowers_cutover.md`** — replace `docs/superpowers/{specs,plans}/` with `planning/{specs,plans}/`. Note the 2026-06-02 rename (commit `d295fd4`). Add: `planning/archive/` for shipped/superseded work.

### 4.2 Add new memory

- **`release_0_2_0_shipped.md`** — date 2026-06-04, PR #20, thin-httpx2-wrapper pivot. Reference the retro doc. Note: tag `pre-v0.2-pivot` is the recovery anchor for the pre-pivot tree.

### 4.3 Update MEMORY.md index

Add the new memory line, refresh the descriptions for the edited memories.

## Out of scope (handled in the follow-up 0.3.0 spec)

The follow-up spec at `planning/specs/2026-06-04-pydantic-optional-extra-design.md` covers:

- Adding `is_pydantic_installed` to `_internal/import_checker.py`.
- Guarding the `pydantic` import in `decoders/pydantic.py` like `decoders/msgspec.py`.
- Removing the unconditional `from httpware.decoders.pydantic import PydanticDecoder` from `client.py`.
- Lazy default-decoder construction with fail-fast at `AsyncClient.__init__` when `decoder is None` and pydantic is not installed.
- Moving `pydantic` from `[project] dependencies` to `[project.optional-dependencies]`.
- Adding `pydantic` to the `all` extra.
- Updating `README.md` install instructions.
- Updating `planning/engineering.md` §1 and §7.
- Adding empty/malformed payload tests for `PydanticDecoder`.

This is breaking and ships as 0.3.0.

## Execution order

The housekeeping is mostly file moves and doc edits. No tests to run, no CI to pass other than docs-lint. Suggested commit grouping (one PR, several commits):

1. `docs(retro): v0.2 thin-wrapper pivot retrospective`
2. `docs(planning): archive delivered specs and plans`
3. `docs(planning): relocate 0.2.0 release notes to planning/releases/`
4. `docs(planning): triage deferred-work — drop ruff/test-extra items, annotate pydantic-guard`
5. `docs(claude): point at planning/archive, planning/retros, planning/releases`

Memory edits land separately (they live outside the repo).

## Acceptance

- `planning/specs/` contains only this spec.
- `planning/plans/` is empty.
- `planning/retros/2026-06-04-v0.2-thin-wrapper-pivot.md` exists with the six sections.
- `planning/releases/0.2.0.md` exists; the old spec path no longer does.
- `planning/archive/specs/` contains 14 files; `planning/archive/plans/` contains 13.
- `planning/deferred-work.md` has 3 open items (1 decoder cache + 2 in-progress for 0.3.0) and the existing closed section unchanged; the two dropped tooling items are gone.
- `CLAUDE.md` "Where to find what" mentions `archive/`, `retros/`, `releases/`.
- Auto-memory: `epic_2_complete.md` corrected; `workflow_superpowers_cutover.md` corrected; `release_0_2_0_shipped.md` added; `MEMORY.md` updated.

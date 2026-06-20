---
status: shipped
date: 2026-06-13
slug: portable-planning-convention
summary: Adopt the portable two-axis convention: per-capability `architecture/` truth files + `changes/` bundles, full history backfill, byte-identical Conventions.
supersedes: null
superseded_by: null
pr: 55
outcome: 'Shipped via PR #55 — two-axis convention adopted: architecture/ truth + planning/changes/ bundles; engineering.md split into 8 files; 40 pairs archived.'
---

# Design: Adopt the portable two-axis planning convention

## Summary

Replace `httpware`'s current `planning/specs/` + `planning/plans/` +
`planning/archive/` layout with the portable two-axis convention already
running in `faststream-outbox`: a **truth axis** (per-capability
`architecture/` files at the repo root, present-tense living prose) and a
**history axis** (`planning/changes/{active,archive}/<YYYY-MM-DD.NN-slug>/`
change bundles, frozen on ship). The single `planning/engineering.md` truth
file is **split** into eight capability files under `architecture/`; the ~38
existing spec/plan pairs are regrouped into dated change bundles with full
backfilled frontmatter; the `planning/README.md` carries a byte-identical
`## Conventions` block plus a repo-specific Index. This change is itself the
inaugural `changes/active/` bundle, demonstrating the convention it defines.

## Motivation

- **Cross-repo consistency.** `faststream-outbox` and `httpware` are sibling
  `modern-python` packages. A single portable convention (same README
  `Conventions` block, same `_templates/`, same bundle shape) means an agent
  or contributor moving between them sees one workflow, not two.
- **The current layout mixes the two axes.** `planning/specs/` /
  `planning/plans/` are flat and split a single change across two
  directories; the spec↔plan pair for one feature lives in two places.
  Worse, "active" has drifted: per the project's own record every roadmap
  item is shipped (0.10.1 shipped 2026-06-13), yet 17 shipped pairs still sit
  in the flat `specs/`/`plans/` dirs because nothing moved them to
  `archive/`. The archive only reaches 2026-06-05. The layout no longer
  tells the truth about what is in flight.
- **`engineering.md` is becoming a bottleneck and is already stale.** It is a
  single 20 KB file written as history ("as of 0.9.0…"), and it predates the
  0.10.0 CircuitBreaker/AsyncTimeout work — it documents neither. A truth
  home should be present-tense and current; splitting into capability files
  makes each one small, owned, and individually promotable on ship.

## Non-goals

- **No rewrite of capability content** beyond the present-tense reflow and
  the one currency fix (CircuitBreaker/AsyncTimeout, below). The split moves
  and reframes existing prose; it does not re-litigate any design.
- **No change to `releases/` or `retros/`.** Both already match the target
  shape and stay put.
- **No production-code change.** This touches `architecture/`, `planning/`,
  `docs/`, and `CLAUDE.md` only. `src/` and `tests/` are untouched.
- **No new audit/retro content.** Existing audit reports and retros move or
  stay; none are authored here.

## Design

### 1. Two axes

Adopt the `faststream-outbox` model verbatim:

- **`architecture/` (repo root) — the present.** One file per capability,
  living present-tense prose, no frontmatter, dated by git. The truth home;
  shipping a change **promotes** its conclusions here by hand.
- **`planning/changes/` — the past-and-pending.** One folder per change,
  frozen on ship.

### 2. Split `engineering.md` into `architecture/` (the re-projection)

This is not a mechanical carve. `engineering.md` is written as history; the
truth axis is the present. So the split **re-projects** onto two axes:
present-tense capability prose goes to `architecture/`; history, roadmap, and
deferred items go to the history axis (change bundles, `releases/`,
`deferred.md`) or are dropped. The "as of 0.x …" narration is flattened to
present tense.

Eight capability files, aligned to the codebase seams and to the docs that
reference `engineering.md` by section number:

| `architecture/` file | Source in `engineering.md` | Docs repointed here |
|----------------------|----------------------------|---------------------|
| `overview.md` | §1 intent (present tense), §2 CI-enforced invariants, §5 module-layout map | `docs/index.md` blob link |
| `client.md` | `Client`/`AsyncClient` surface, the internal terminal, error-mapping location, sync/async parity, `stream()` | — |
| `middleware.md` | §3 Seam A (chain, `compose`/`compose_async`, frozen-at-construction, phase decorators) + "why no standalone OTel middleware" | `docs/middleware.md` `§3`, `§8` |
| `decoders.md` | §3 Seam B (`can_decode`/`decode` dispatch, default-list resolution, single-pass rule, per-instance cache, `MissingDecoderError` pre-flight) | — |
| `errors.md` | §4 exception contract (`StatusError` tree, single positional `response`, `STATUS_TO_EXCEPTION`, dual-inherit `TimeoutError`, `DecodeError`, credential stripping) | `docs/errors.md` `§4` |
| `resilience.md` | Retry/`RetryBudget`/Bulkhead/backoff **+ CircuitBreaker/AsyncTimeout** + the logging/OTel events those middlewares emit | `docs/resilience.md` `§3` |
| `extras.md` | §3 Seam C + §7 optional-extras pattern + the extra-isolation test | — |
| `testing.md` | §6 testing patterns | `docs/testing.md` `§6` |

**What dissolves** (does *not* become an `architecture/` file, because it is
history not present):

- §8 roadmap — every item is shipped or retired; the record now lives in the
  archived change bundles + `releases/`.
- The v0.1→v0.2 "deleted / rewritten by the pivot" archaeology — lives in the
  v0.2 pivot retro and its archived bundle.
- §9 deferred-work stub — its only content is a pointer to `deferred.md`.

`planning/engineering.md` is **deleted** once its content lands in
`architecture/`. `CLAUDE.md` names `architecture/` as the promotion target in
its place.

### 3. Currency fix: CircuitBreaker / AsyncTimeout

`engineering.md` predates 0.10.0 and documents neither `CircuitBreaker` nor
`AsyncTimeout`. A `resilience.md` that omitted them would publish a knowingly
stale truth file, so `resilience.md` folds in a present-tense paragraph for
both, sourced from the shipped
`changes/2026-06-13.02-circuit-breaker-and-timeout/design.md`. This is
the smallest honest content addition; no broader rewrite.

### 4. `planning/README.md`

- **Intro paragraph** (repo-specific): truth lives in `architecture/` at the
  repo root; this directory records how it got there.
- **`## Conventions`** (portable): copied **byte-identical** from
  `faststream-outbox/planning/README.md` — including its
  `architecture/<capability>.md` / "one file per capability" language, which
  is now literally accurate for this repo.
- **`## Index`** (repo-specific): **Active** (this convention change) and
  **Archived (shipped)** lists; **Other** points at `architecture/`,
  `audits/`, `deferred.md`.

### 5. `_templates/`

Copy `design.md`, `plan.md`, `change.md` from
`faststream-outbox/planning/_templates/` **as-is**.

### 6. Change-bundle migration (full backfill)

- **`changes/active/`** holds exactly one bundle after migration: this
  change, `2026-06-13.NN-portable-planning-convention/`. Every other existing
  spec/plan is shipped.
- **`changes/`** — all 17 flat `specs/`+`plans/` pairs and the ~21
  `archive/specs/`+`archive/plans/` pairs regroup into
  `<YYYY-MM-DD.NN-slug>/{design,plan}.md`. `.NN` ordering is derived from
  **git merge order / PR number** (several dates collide — 2026-05-31 ×8,
  2026-06-05 ×7, 2026-06-08 ×8, 2026-06-13 dense). Frontmatter is fully
  backfilled: `status: shipped`, `date`, `slug`, `pr:`, `outcome:`, and
  `supersedes`/`superseded_by` where a v0.1 surface was superseded by the
  v0.2 pivot.
- **Orphans** (design with no matching plan) become **design-only bundles**
  (no `plan.md`): `2026-05-31-shipped-work-review.md` and
  `2026-06-04-v0.2-retro-and-housekeeping-design.md`.
- **Audit pairs vs reports.** The "run an audit" design+plan pairs
  (`deep-audit`, `delta-audit`) are change bundles like any other. The
  resulting **findings reports** (`planning/audit/2026-06-*.md`) are not
  bundles — see §7.

### 7. Other directory moves

- `planning/audit/2026-06-*.md` (reports) → `planning/audits/`.
- `planning/audit/{workflow,workflow-delta}.mjs`, `_discover.json` (tooling)
  → `planning/audits/scripts/`.
- `planning/retros/`, `planning/releases/` — unchanged.
- `planning/deferred-work.md` → `planning/deferred.md` (rename for cross-repo
  consistency).

### 8. Link repointing

- **`docs/` (published site, 6 refs).** `planning/engineering.md §N` →
  `architecture/<file>.md#anchor` per the §2 table. The
  `docs/index.md` GitHub blob link → `architecture/` (or `overview.md`).
  `mkdocs build --strict` is the backstop that proves none was missed.
- **`CLAUDE.md`.** Rewrite "Where to find what", the Per-feature Workflow
  line, the Seam B link, and "When in doubt" to name `architecture/` as the
  promotion target and the `planning/changes/` flow as the lane. Keep all
  architecture-invariant content intact.
- **`engineering.md` internal links** disappear with the file; the content
  they sat in moves into the right `architecture/` file using in-file anchors
  rather than `planning/...` paths.
- **`releases/`** — scan for any inbound `planning/specs|plans|archive`
  references and repoint to the archived bundle path.

## Operations

None. No DNS, infra, or external-account changes. (The docs site rebuilds
from `main` on the existing workflow; no config change.)

## Out of scope

- Coarser/finer `architecture/` granularity than the eight files above — the
  eight mirror the codebase seams and make every docs `§N` repoint a clean
  file+anchor.
- Splitting `faststream-outbox` further or changing its convention — this
  repo consumes that convention, it does not modify it.
- Any `src/`/`tests/` change.

## Testing

- `just lint` and `just lint-ci` — clean (markdown / eof-fixer / ruff scope
  is unaffected, but run to be sure no tracked file regressed).
- `mkdocs build --strict` — proves every repointed docs link resolves.
- Grep gates:
  - `planning/engineering.md` no longer exists.
  - No tracked file outside `planning/changes/` references
    `planning/(specs|plans|archive|audit|deferred-work)` or
    `planning/engineering.md`.
  - `architecture/` contains exactly the eight files; none carries
    frontmatter.
  - `changes/active/` contains exactly this bundle.

## Risk

- **Broken docs link slips through** (likely / medium). *Mitigation:*
  `mkdocs build --strict` fails the build on any unresolved internal link;
  the grep gate catches stale `planning/...` paths the strict build would not
  (e.g. links pointing outside `docs/`).
- **Wrong `.NN` ordering on collision-heavy dates** (medium / low).
  *Mitigation:* derive every `.NN` from `git log` merge order / PR number,
  not from guesswork; the ordering only affects timeline sort, not
  correctness of content.
- **Re-projection drops or distorts a fact** while flattening "as of 0.x"
  prose (medium / medium). *Mitigation:* the split is move-and-reframe, not
  rewrite; each `architecture/` file is diffable against the corresponding
  `engineering.md` section, and the currency fix is the only intentional
  content addition.
- **Scope creep** — the migration is large (~38 bundles, 8 files, full
  backfill). *Mitigation:* the plan sequences it into independent,
  verifiable tasks (templates+README first, then split, then bundle
  migration, then link repointing, then verification).

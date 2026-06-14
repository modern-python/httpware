# Planning

Specs, plans, and change history for `httpware`. The living truth about
*what the system does now* lives in [`architecture/`](../architecture/) at
the repo root; this directory records *how it got there*.

## Conventions

> This section is the portable convention — identical across the
> modern-python repos. The Index below is repo-specific. To adopt elsewhere,
> copy this section plus [`_templates/`](_templates/) and point that repo's
> `CLAUDE.md` Workflow + truth home at it.

### Two axes, never mixed

- **`architecture/` (repo root) — the present.** One file per capability,
  living prose, updated whenever a change ships. The truth home.
- **`planning/changes/` — the past-and-pending.** One folder per change,
  frozen once shipped.

Shipping a change **promotes** its conclusions into the affected
`architecture/<capability>.md` by hand, then archives the bundle. That
hand-edit is what keeps `architecture/` true; the archived bundle carries the
*why*.

### Change bundles

A change is a folder `changes/active/YYYY-MM-DD.NN-<slug>/`:

- `YYYY-MM-DD` — proposal date; `.NN` — zero-padded intra-day counter
  (`.01`, `.02`, …) that breaks same-date ties so the timeline sorts stably.
- `<slug>` — kebab-case description, not a story ID.

On merge the folder moves to `changes/archive/` with `status: shipped`, `pr:`,
and `outcome:` filled, and its line moves from **Active** to **Archived** in
the Index below.

### Three lanes

| Lane | Artifacts | Use when |
|------|-----------|----------|
| **Full** | `design.md` + `plan.md` | design judgment; new file/module; public-API change; cross-cutting/multi-file; non-trivial test design |
| **Lightweight** | `change.md` | small-but-real: ≲30 LOC net, ≤2 files, no new file, no public-API change, single straightforward test |
| **Tiny** | none — conventional commit | typo, dep bump, linter/formatter/CI tweak, mechanical rename, single-line config |

Heavier lane wins on ambiguity. A `change.md` that outgrows its lane splits
into `design.md` + `plan.md`.

### Artifacts at a glance

- **`design.md`** — the spec: the *thinking* (why, design, trade-offs, scope).
- **`plan.md`** — the plan: the *sequencing* (the executor's task checklist).
- **`change.md`** — both, condensed, for the lightweight lane.
- **`releases/<semver>.md`** — per-release user-facing notes.
- **`audits/<date>-<slug>.md`** — findings from a code/docs/bug-hunt sweep;
  spawns fix changes.
- **`retros/<date>-<slug>.md`** — what we learned after a body of work.
- **`deferred.md`** — real-but-unscheduled items, each with a revisit trigger.

Templates live in [`_templates/`](_templates/).

### Frontmatter

`design.md` / `change.md`: `status` (draft|approved|shipped|superseded),
`date`, `slug`, `supersedes`, `superseded_by`, `pr`, `outcome`.
`plan.md`: `status`, `date`, `slug`, `spec`, `pr`. Files in `architecture/`
carry **no** frontmatter — living prose, dated by git.

## Index

### Active

_None._

### Archived (shipped)

- **[docs-ux-restructure](changes/archive/2026-06-14.01-docs-ux-restructure/design.md)** (#60, 2026-06-14) — Thin README front-door + canonical `docs/index.md` (G3), why-httpware hook (G1), runnable jsonplaceholder example (G4), nav reorder + architecture links, base-client scrub. G2 dropped; G6 (decoder guide) still open.
- **[docs-audit-followups](changes/archive/2026-06-13.05-docs-audit-followups/change.md)** (#58, 2026-06-13) — Second docs-audit batch: corrected the overstated invariant-enforcement claims in `CLAUDE.md` + `architecture/overview.md` (only `print()`/blanket-`type: ignore` are machine-checked), readability findings R1–R3, and documented the public `STATUS_TO_EXCEPTION` (G5).
- **[docs-accuracy-fixes](changes/archive/2026-06-13.04-docs-accuracy-fixes/change.md)** (f203821, 2026-06-13) — Fixed 5 verified factual errors from the [docs audit](audits/2026-06-13-docs-audit.md): RetryBudget formula, modern-di 2.x recipe, contributing-doc CI/grep claim, `just lint` comment, middleware stable-contracts list (+ AsyncTimeout non-finite wording).
- **[portable-planning-convention](changes/archive/2026-06-13.03-portable-planning-convention/design.md)** (#55, 2026-06-13) — Adopt the portable two-axis convention: per-capability `architecture/` truth files + `changes/` bundles, full history backfill, byte-identical Conventions.
- **[circuit-breaker-and-timeout](changes/archive/2026-06-13.02-circuit-breaker-and-timeout/design.md)** (#51, 2026-06-13) — Shipped 0.10.0 — CircuitBreaker + AsyncTimeout
- **[msgspec-nested-customtype-fix](changes/archive/2026-06-13.01-msgspec-nested-customtype-fix/design.md)** (#43, 2026-06-13) — Shipped 0.9.1 — nested-CustomType guard
- **[delta-audit](changes/archive/2026-06-12.01-delta-audit/design.md)** (#43, 2026-06-12) — 0.9.0 delta audit; closed via 0.9.1
- **[decoder-instance-cache](changes/archive/2026-06-10.02-decoder-instance-cache/design.md)** (#42, 2026-06-10) — Shipped 0.9.0 — per-instance decoder cache
- **[multi-decoder](changes/archive/2026-06-10.01-multi-decoder/design.md)** (#41, 2026-06-10) — Shipped 0.9.0 — multi-decoder routing
- **[readme-link-cleanup](changes/archive/2026-06-08.08-readme-link-cleanup/design.md)** (#39, 2026-06-08) — README link cleanup
- **[mkdocs-gh-pages-migration](changes/archive/2026-06-08.07-mkdocs-gh-pages-migration/design.md)** (#38, 2026-06-08) — Docs host -> GitHub Pages
- **[test-mop-up](changes/archive/2026-06-08.06-test-mop-up/design.md)** (#37, 2026-06-08) — Shipped 0.8.6 — test-only audit findings
- **[small-fixes-mop-up](changes/archive/2026-06-08.05-small-fixes-mop-up/design.md)** (#36, 2026-06-08) — Shipped 0.8.5 — 4 small audit findings
- **[otel-partial-install](changes/archive/2026-06-08.04-otel-partial-install/design.md)** (#35, 2026-06-08) — Shipped 0.8.4 — OTel partial-install guards
- **[post-080-doc-sweep](changes/archive/2026-06-08.03-post-080-doc-sweep/design.md)** (#34, 2026-06-08) — Post-0.8.0 doc sweep
- **[retry-budget-cluster](changes/archive/2026-06-08.02-retry-budget-cluster/design.md)** (#34, 2026-06-08) — Shipped 0.8.3 — 7 RetryBudget findings
- **[send-with-response](changes/archive/2026-06-08.01-send-with-response/design.md)** (#33, 2026-06-08) — Shipped 0.8.2 — send_with_response
- **[deep-audit](changes/archive/2026-06-07.03-deep-audit/design.md)** (#32, 2026-06-07) — Deep audit; findings closed across 0.8.1-0.8.6
- **[decoder-error](changes/archive/2026-06-07.02-decoder-error/design.md)** (#32, 2026-06-07) — Shipped 0.8.1 — DecodeError at seam B
- **[sync-client](changes/archive/2026-06-07.01-sync-client/design.md)** (#31, 2026-06-07) — Shipped 0.8.0 — sync Client + Async* rename
- **[modern-di-recipe](changes/archive/2026-06-06.01-modern-di-recipe/design.md)** (#29, 2026-06-06) — modern-di DI recipe doc
- **[v0.7-docs-expansion](changes/archive/2026-06-05.07-v0.7-docs-expansion/design.md)** (#28, 2026-06-05) — Shipped 0.7.0 — first-cut user docs
- **[extension-slot-docs](changes/archive/2026-06-05.06-extension-slot-docs/design.md)** (#28, 2026-06-05) — Shipped 0.7.0 — middleware docs
- **[observability](changes/archive/2026-06-05.05-observability/design.md)** (#27, 2026-06-05) — Shipped 0.6.0 — logging + OTel events
- **[streaming](changes/archive/2026-06-05.04-streaming/design.md)** (#26, 2026-06-05) — Shipped 0.5.0 — stream()
- **[docs-sync-0.4](changes/archive/2026-06-05.03-docs-sync-0.4/design.md)** (#25, 2026-06-05) — 0.4 docs sync
- **[bulkhead](changes/archive/2026-06-05.02-bulkhead/design.md)** (#23, 2026-06-05) — Shipped 0.4.0 — Bulkhead
- **[retry-and-retry-budget](changes/archive/2026-06-05.01-retry-and-retry-budget/design.md)** (#22, 2026-06-05) — Shipped 0.4.0 — Retry + RetryBudget
- **[v0.2-retro-and-housekeeping](changes/archive/2026-06-04.02-v0.2-retro-and-housekeeping/design.md)** (#21, 2026-06-04) — Post-0.2 retro + housekeeping
- **[pydantic-optional-extra](changes/archive/2026-06-04.01-pydantic-optional-extra/design.md)** (#21, 2026-06-04) — Shipped 0.3.0 — pydantic moves to an extra
- **[thin-httpx2-wrapper](changes/archive/2026-06-03.02-thin-httpx2-wrapper/design.md)** (#20, 2026-06-03) — Shipped 0.2.0 — the thin-wrapper pivot
- **[input-validation-pass](changes/archive/2026-06-03.01-input-validation-pass/design.md)** (#19, 2026-06-03) — Input-validation hardening
- **[project-hygiene-tidy](changes/archive/2026-06-02.02-project-hygiene-tidy/design.md)** (#18, 2026-06-02) — Repo hygiene pass
- **[docs-reorg-and-mkdocs](changes/archive/2026-06-02.01-docs-reorg-and-mkdocs/design.md)** (#17, 2026-06-02) — Docs reorg + mkdocs scaffolding
- **[auth-coercion](changes/archive/2026-06-01.01-auth-coercion/design.md)** (#16, 2026-06-01) — Shipped (Epic 2); removed by the v0.2 pivot *(superseded by thin-httpx2-wrapper)*
- **[release-0.1.0-prep](changes/archive/2026-05-31.09-release-0.1.0-prep/design.md)** (#14, 2026-05-31) — 0.1.0 released
- **[recordedtransport](changes/archive/2026-05-31.08-recordedtransport/design.md)** (#13, 2026-05-31) — Shipped in 0.1.0; removed by the v0.2 pivot *(superseded by thin-httpx2-wrapper)*
- **[asyncclient](changes/archive/2026-05-31.07-asyncclient/design.md)** (#12, 2026-05-31) — Shipped in 0.1.0; rewritten by the v0.2 pivot *(superseded by thin-httpx2-wrapper)*
- **[msgspec-decoder-via-extras](changes/archive/2026-05-31.06-msgspec-decoder-via-extras/design.md)** (#11, 2026-05-31) — Shipped in 0.1.0; carry-forward decoder
- **[request-immutability-helpers](changes/archive/2026-05-31.05-request-immutability-helpers/design.md)** (#10, 2026-05-31) — Shipped in 0.1.0; removed by the v0.2 pivot *(superseded by thin-httpx2-wrapper)*
- **[phase-shortcut-decorators](changes/archive/2026-05-31.04-phase-shortcut-decorators/design.md)** (#9, 2026-05-31) — Shipped in 0.1.0; survived the v0.2 pivot
- **[middleware-protocol-and-chain](changes/archive/2026-05-31.03-middleware-protocol-and-chain/design.md)** (#8, 2026-05-31) — Shipped in 0.1.0; survived the v0.2 pivot
- **[shipped-work-review](changes/archive/2026-05-31.02-shipped-work-review/design.md)** (#7, 2026-05-31) — 0.1.0-era review of shipped stories
- **[bmad-to-superpowers-transition](changes/archive/2026-05-31.01-bmad-to-superpowers-transition/design.md)** (#6, 2026-05-31) — Bootstrapped the planning workflow

## Other

- **[`architecture/`](../architecture/)** at the repo root — the living
  per-capability truth (overview, client, middleware, decoders, errors,
  resilience, optional extras, testing). This is the promotion target on
  every ship.
- **[audits/](audits/)** — findings reports (deep audit + delta audits) and
  their `scripts/` tooling.
- **[deferred.md](deferred.md)** — real-but-unscheduled items with revisit
  triggers.

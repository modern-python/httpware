---
summary: Bootstrapped the planning workflow
---

# bmad → superpowers transition (design)

- **Date:** 2026-05-31
- **Status:** approved, ready for plan
- **Scope:** workflow transition for the `httpware` project from bmad to superpowers, plus the first two pieces of work under the new flow.

## Why

bmad's ceremony has outweighed its value on this project. The planning artifacts produced (59KB PRD, 57KB architecture, 57KB epics, 40KB+ per-story specs) hold genuinely useful decisions, but the per-story workflow — `create-story → dev-story → code-review → retro` with extensive Given/When/Then ACs — is slow and over-engineered for a five-person-equivalent OSS library. We're switching the workflow to superpowers (brainstorming → writing-plans → executing-plans → requesting-code-review) while preserving the load-bearing engineering decisions in a single distilled doc.

Five stories have shipped (1-1 through 1-5). Twenty-seven remain in the bmad backlog. The cutover happens between stories so the next story-1-6 starts on a clean flow.

## Decisions

| Decision | Choice |
| --- | --- |
| Workflow | Pure superpowers: brainstorming → spec → writing-plans → plan → executing-plans/subagent-driven → requesting-code-review → finishing-a-development-branch |
| Topic naming | Kebab-case descriptions (`msgspec-decoder-adapter`), not story IDs |
| Legacy planning docs | Distill load-bearing decisions into `docs/dev/engineering.md`; archive the rest under `docs/archive/` |
| AI entrypoint | `CLAUDE.md` stays the AI entrypoint and points at `docs/dev/engineering.md` |
| First task | Retrospective code review of shipped work (1-1 through 1-5) via `superpowers:requesting-code-review` |
| Second task | Refactor based on review findings, one cohesive PR per finding-group |
| Ordering | Transition (single PR) lands first; tasks 1–2 run on the new structure |
| `deferred-work.md` | Kept at repo root as-is; remains the "real but not actionable now" log |

## Distilled doc: `docs/dev/engineering.md`

One focused ~250–350 line document, written for both human contributors and AI agents. Sections:

1. **Project intent** — 3–4 sentences. What `httpware` is, what it supersedes (`community-of-python/base-client`), who consumes it.
2. **Architectural invariants** — the CI-enforced list from CLAUDE.md, plus one-line "why" for each so the next contributor can judge edge cases:
   - No `httpx2` leakage outside `src/httpware/transports/httpx2.py`.
   - No `httpx2` private API.
   - No `from __future__ import annotations` (Python 3.11+ floor).
   - No `print()` (ruff-enforced).
   - No global logging config; only `logging.getLogger("httpware")` or namespaced child loggers.
   - Type suppressions use `# ty: ignore[<rule>]`, never `# type: ignore` or `# mypy: ignore`.
3. **The five protocol seams** — name, location, contract, the rule across it:
   1. `Middleware ↔ Transport` (chain bottom calls `transport.__call__`)
   2. `AsyncClient ↔ Middleware` (chain composed at construction)
   3. `AsyncClient ↔ ResponseDecoder` (called when `response_model` provided)
   4. `Httpx2Transport ↔ httpx2` (only `transports/httpx2.py` imports `httpx2`)
   5. `httpware ↔ optional extras` (extras imported only inside their dedicated modules)
4. **Exception contract** — mandatory fields on `StatusError` (`status: int`, `body: bytes`, `headers: Mapping`, `json: Any | None`, `request_method: str`, `request_url: str`), keyword-args-only construction, the `httpx2 → httpware` mapping table at the transport seam.
5. **Module layout** — current tree (post-1.5) with which modules exist now vs. planned.
6. **Testing patterns** — `pytest-asyncio` auto mode (no `@pytest.mark.asyncio`); `RecordedTransport` for transport mocking, not `respx`; Hypothesis property-based tests for concurrency-sensitive code in files named `test_*_props.py`.
7. **Optional-extras pattern** — pydantic, msgspec, opentelemetry isolated to their own modules; import inside the module, never at package top-level.
8. **Remaining roadmap** — short bullets, one line per remaining story (1-6 through 6-5), grouped by epic. No 40KB specs. When work starts on a roadmap item, it gets a superpowers spec.
9. **Deferred work** — pointer to `planning/deferred-work.md`; not duplicated here.

Explicit omissions vs. the bmad planning bundle: the 47 numbered FRs, 25 NFRs, persona work, and long architecture-decision essays move to `docs/archive/` and are cited only when a future spec needs the original rationale (e.g., "we decided X because of NFR-12").

## Archive layout

Single commit moves bmad artifacts to `docs/archive/`:

```
docs/
├── engineering.md                   (NEW — the distilled doc)
├── deferred-work.md                 (KEEP at root — actively used)
├── superpowers/
│   ├── specs/                       (NEW — this spec is the first artifact)
│   └── plans/                       (NEW — implementation plans)
└── archive/
    ├── README.md                    (NEW — 1 paragraph framing)
    ├── prd.md
    ├── architecture.md
    ├── epics.md
    ├── product-brief-httpware.md
    ├── product-brief-httpware-distillate.md
    └── stories/
        ├── 1-1-project-scaffold-and-tooling.md
        ├── 1-2-core-data-types.md
        ├── 1-3-exception-hierarchy-with-plain-fields.md
        ├── 1-4-transport-protocol-and-httpx2transport-adapter.md
        ├── 1-5-responsedecoder-protocol-and-pydantic-adapter.md
        └── sprint-status.yaml
```

`docs/archive/README.md` (~1 paragraph) frames the archive: these files are historical reference, not authoritative; load-bearing parts were distilled into `../engineering.md` on 2026-05-31; consult these only for original rationale or to settle a "why did we decide X" question.

`.review-tmp/` at repo root (bmad code-review artifact dump) is deleted. The story diffs and bundle are recoverable from git history if ever needed.

`CLAUDE.md` updates:
- Replace the "Project Overview" bmad bullets with pointers to `engineering.md` (primary) and `docs/archive/` (history).
- Add a one-liner describing the per-feature flow: brainstorming → spec in `planning/specs/` → writing-plans → plan in `planning/plans/` → executing-plans → requesting-code-review.
- The "Architecture invariants (CI-enforced)" and "Code conventions" sections stay verbatim — these are AI-enforcement rules, not design rationale.

## New per-feature workflow

For every future piece of work — story 1-6 onwards, the upcoming refactor, anything else:

```
1. brainstorming             →  planning/specs/YYYY-MM-DD-<topic>-design.md
2. writing-plans             →  planning/plans/YYYY-MM-DD-<topic>-plan.md
3. using-git-worktrees       (isolate workspace)
4. executing-plans  OR  subagent-driven-development  (depending on task shape)
5. test-driven-development   (rigid skill, applied throughout step 4)
6. verification-before-completion  (before claiming done)
7. requesting-code-review    (before merge)
8. finishing-a-development-branch  (merge / PR / cleanup)
```

Topic slugs use kebab-case descriptions, not story IDs (`msgspec-decoder-adapter`, not `story-1-6`). The mapping to the old backlog lives in `engineering.md`'s roadmap section.

Gone:
- 40KB story files with extensive Given/When/Then ACs.
- `sprint-status.yaml`, retros (the existing five stories had retros marked `optional` anyway).
- The bmad code-review workflow / `.review-tmp/` bundle. Replaced by `superpowers:requesting-code-review`, which reviews the branch diff against the spec.
- The epics layer as a workflow construct. The "epic" framing survives only as a grouping in `engineering.md`'s roadmap bullets.

Kept implicitly:
- All architectural invariants and protocol seams enforced by CI (lint rules, grep checks, exception-construction contracts). These are code-level and survive any workflow change.
- `deferred-work.md` for review-surfaced items that are real but not actionable now.
- `CHANGELOG.md` per release.

Choice between executing-plans vs. subagent-driven-development: `executing-plans` with checkpoints for multi-day or multi-PR work; `subagent-driven-development` for smaller work that fits in one session and has independent sub-tasks.

## First-task plan

### Cutover PR (transition, executed first)

1. Write `docs/dev/engineering.md` distilled from PRD, architecture, the five merged stories.
2. Create `docs/archive/`; move `prd.md`, `architecture.md`, `epics.md`, both product briefs, and `stories/` into it.
3. Write `docs/archive/README.md`.
4. `planning/specs/` already contains this spec; the cutover commit adds the corresponding plan to `planning/plans/`.
5. Update `CLAUDE.md` per the rules above.
6. Delete `.review-tmp/`.
7. Single commit, single PR, merge to `main`. This is the cutover point.

### Task 1 — retrospective code review of shipped work

- Invoke `superpowers:requesting-code-review` against `main` with everything merged through story 1-5 as the review target.
- Scope: stories 1-1 through 1-5 (scaffold, core data types, exception hierarchy, transport + httpx2 adapter, decoder protocol + pydantic adapter).
- Triage findings into three buckets:
  - **Refactor now** — feeds Task 2.
  - **Defer** — added to `planning/deferred-work.md`.
  - **Discard** — noise / disagree, with one-line rationale.
- Output: triaged review report committed at `planning/specs/YYYY-MM-DD-shipped-work-review.md`.

### Task 2 — refactor based on review

- Brainstorm scope from the "Refactor now" bucket → spec → plan → execute → review → merge.
- One refactor PR per logically-cohesive group of findings. Avoid one-giant-PR.
- Brainstorming for Task 2 is short: the discovery happened in Task 1, so the brainstorm is mostly grouping findings and ordering them.

### Out of scope for this design's first execution

- Story 1-6 (msgspec decoder). It's the next normal-flow item after Tasks 1–2 settle.
- Migrating any merged code to a new pattern uncovered during review. That belongs inside Task 2, not bundled into the cutover.

## Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| `engineering.md` and `CLAUDE.md` drift apart. | Boundary rule: `CLAUDE.md` = AI invariants and commands; `engineering.md` = design rationale, seams, roadmap. If a rule belongs in both, it lives in `CLAUDE.md` and is referenced from `engineering.md`, not copied. |
| Retrospective review surfaces too many findings to triage usefully. | The three-bucket triage is the relief valve: "Defer" is a real outcome, not a failure. `deferred-work.md` already absorbs review fallout; the new flow extends that pattern. |
| Loss of the FR/NFR numbering convenience when future specs need to cite a constraint. | The archive preserves the numbered lists; specs can cite `archive/prd.md#NFR-12`. |
| Distilled doc misses a load-bearing decision. | Archive is preserved; if a missing decision surfaces, it's added to `engineering.md` rather than restored. The archive remains the fallback. |

## Definition of done

- `docs/dev/engineering.md` exists and replaces the per-document references in CLAUDE.md.
- `docs/archive/` contains the listed files with a framing README.
- `planning/specs/` and `planning/plans/` exist; this spec is committed there.
- `.review-tmp/` is removed.
- `CLAUDE.md` no longer references bmad artifacts as authoritative.
- The cutover lands as a single PR, merged before Task 1 begins.

---
status: draft
date: 2026-06-13
slug: portable-planning-convention
spec: portable-planning-convention
pr: null
---

# portable-planning-convention — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate `httpware`'s planning layout to the portable two-axis
convention: per-capability `architecture/` truth files + `planning/changes/`
bundles, with all history backfilled and every inbound link repointed.

**Architecture:** Split `planning/engineering.md` into eight present-tense
`architecture/` capability files; regroup the ~38 existing spec/plan pairs
into `planning/changes/archive/<YYYY-MM-DD.NN-slug>/` bundles with full
frontmatter (PR + outcome from the embedded map below); author a
byte-identical `## Conventions` README; repoint the six `docs/` references and
`CLAUDE.md`. Docs-only change — no `src/` or `tests/` edits.

**Tech stack:** Markdown, `git mv`, `just lint-ci`, `mkdocs build --strict`.

**Spec:** [`design.md`](./design.md)

**Branch:** `chore/portable-planning-convention` (already created; the active
bundle's `design.md` + this `plan.md` are already committed there).

**Commit strategy:** One commit per task.

---

## Reference: the complete bundle map

Every archived bundle below. `id` = `<date>.NN-<slug>` (date = the proposal
date on the existing filename; `.NN` = PR-merge order within that date). Each
bundle gets `design.md` (+ `plan.md` unless marked **design-only**). Source
files are the current `planning/{specs,plans,archive/specs,archive/plans}/`
paths sharing the `<date>-<slug>` stem.

| Bundle id | PR | outcome (frontmatter `outcome:`) | supersedes / superseded_by |
|-----------|----|----------------------------------|----------------------------|
| `2026-05-31.01-bmad-to-superpowers-transition` | #6 | Bootstrapped the planning workflow | — |
| `2026-05-31.02-shipped-work-review` **design-only** | #7 | 0.1.0-era review of shipped stories | — |
| `2026-05-31.03-middleware-protocol-and-chain` | #8 | Shipped in 0.1.0; survived the v0.2 pivot | — |
| `2026-05-31.04-phase-shortcut-decorators` | #9 | Shipped in 0.1.0; survived the v0.2 pivot | — |
| `2026-05-31.05-request-immutability-helpers` | #10 | Shipped in 0.1.0; removed by the v0.2 pivot | superseded_by: `2026-06-03.02-thin-httpx2-wrapper` |
| `2026-05-31.06-msgspec-decoder-via-extras` | #11 | Shipped in 0.1.0; carry-forward decoder | — |
| `2026-05-31.07-asyncclient` | #12 | Shipped in 0.1.0; rewritten by the v0.2 pivot | superseded_by: `2026-06-03.02-thin-httpx2-wrapper` |
| `2026-05-31.08-recordedtransport` | #13 | Shipped in 0.1.0; removed by the v0.2 pivot | superseded_by: `2026-06-03.02-thin-httpx2-wrapper` |
| `2026-05-31.09-release-0.1.0-prep` | #14 | 0.1.0 released | — |
| `2026-06-01.01-auth-coercion` | #16 | Shipped (Epic 2); removed by the v0.2 pivot | superseded_by: `2026-06-03.02-thin-httpx2-wrapper` |
| `2026-06-02.01-docs-reorg-and-mkdocs` | #17 | Docs reorg + mkdocs scaffolding | — |
| `2026-06-02.02-project-hygiene-tidy` | #18 | Repo hygiene pass | — |
| `2026-06-03.01-input-validation-pass` | #19 | Input-validation hardening | — |
| `2026-06-03.02-thin-httpx2-wrapper` | #20 | Shipped 0.2.0 — the thin-wrapper pivot | supersedes: `2026-05-31.05`, `.07`, `.08`, `2026-06-01.01` |
| `2026-06-04.01-pydantic-optional-extra` | #21 | Shipped 0.3.0 — pydantic moves to an extra | — |
| `2026-06-04.02-v0.2-retro-and-housekeeping` **design-only** | #21 | Post-0.2 retro + housekeeping | — |
| `2026-06-05.01-retry-and-retry-budget` | #22 | Shipped 0.4.0 — Retry + RetryBudget | — |
| `2026-06-05.02-bulkhead` | #23 | Shipped 0.4.0 — Bulkhead | — |
| `2026-06-05.03-docs-sync-0.4` | #25 | 0.4 docs sync | — |
| `2026-06-05.04-streaming` | #26 | Shipped 0.5.0 — `stream()` | — |
| `2026-06-05.05-observability` | #27 | Shipped 0.6.0 — logging + OTel events | — |
| `2026-06-05.06-extension-slot-docs` | #28 | Shipped 0.7.0 — middleware docs | — |
| `2026-06-05.07-v0.7-docs-expansion` | #28 | Shipped 0.7.0 — first-cut user docs | — |
| `2026-06-06.01-modern-di-recipe` | #29 | modern-di DI recipe doc | — |
| `2026-06-07.01-sync-client` | #31 | Shipped 0.8.0 — sync `Client` + `Async*` rename | — |
| `2026-06-07.02-decoder-error` | #32 | Shipped 0.8.1 — `DecodeError` at seam B | — |
| `2026-06-07.03-deep-audit` | #32 | Deep audit; findings closed across 0.8.1–0.8.6 | — |
| `2026-06-08.01-send-with-response` | #33 | Shipped 0.8.2 — `send_with_response` | — |
| `2026-06-08.02-retry-budget-cluster` | #34 | Shipped 0.8.3 — 7 RetryBudget findings | — |
| `2026-06-08.03-post-080-doc-sweep` | #34 | Post-0.8.0 doc sweep | — |
| `2026-06-08.04-otel-partial-install` | #35 | Shipped 0.8.4 — OTel partial-install guards | — |
| `2026-06-08.05-small-fixes-mop-up` | #36 | Shipped 0.8.5 — 4 small audit findings | — |
| `2026-06-08.06-test-mop-up` | #37 | Shipped 0.8.6 — test-only audit findings | — |
| `2026-06-08.07-mkdocs-gh-pages-migration` | #38 | Docs host → GitHub Pages | — |
| `2026-06-08.08-readme-link-cleanup` | #39 | README link cleanup | — |
| `2026-06-10.01-multi-decoder` | #41 | Shipped 0.9.0 — multi-decoder routing | — |
| `2026-06-10.02-decoder-instance-cache` | #42 | Shipped 0.9.0 — per-instance decoder cache | — |
| `2026-06-12.01-delta-audit` | #43 | 0.9.0 delta audit; closed via 0.9.1 | — |
| `2026-06-13.01-msgspec-nested-customtype-fix` | #43 | Shipped 0.9.1 — nested-CustomType guard | — |
| `2026-06-13.02-circuit-breaker-and-timeout` | #51 | Shipped 0.10.0 — CircuitBreaker + AsyncTimeout | — |

`2026-06-13.03-portable-planning-convention` is **this** change — already in
`changes/active/`, frontmatter finalized at merge (Task 8).

Filename→stem note: the source plan for circuit-breaker is
`planning/plans/2026-06-13-circuit-breaker-and-timeout.md` (no `-plan`
suffix); everything else uses `-design.md` / `-plan.md`.

---

### Task 1: Bootstrap the convention skeleton

**Files:**
- Modify: `.gitignore` (remove the bare `plan.md` rule)
- Create: `planning/_templates/{design,plan,change}.md`
- Create dirs: `planning/changes/archive/`, `planning/audits/scripts/`
- Rename: `planning/deferred-work.md` → `planning/deferred.md`

- [ ] **Step 0: Remove the bare `plan.md` gitignore rule**

  Line 26 of `.gitignore` is a bare `plan.md` (intended for a root scratch
  file) that would make every bundle's `plan.md` untracked — incompatible
  with the convention. Delete that line. Verify:
  ```bash
  ! git check-ignore planning/changes/active/2026-06-13.03-portable-planning-convention/plan.md && echo "plan.md tracked"
  ```
  Expected: `plan.md tracked`. (Already applied during planning if committed
  with this bundle; confirm it stuck.)

- [ ] **Step 1: Copy the templates as-is**

  ```bash
  mkdir -p planning/_templates planning/changes/archive planning/audits/scripts
  cp /Users/kevinsmith/src/pypi/faststream-outbox/planning/_templates/design.md planning/_templates/design.md
  cp /Users/kevinsmith/src/pypi/faststream-outbox/planning/_templates/plan.md   planning/_templates/plan.md
  cp /Users/kevinsmith/src/pypi/faststream-outbox/planning/_templates/change.md planning/_templates/change.md
  ```

- [ ] **Step 2: Rename deferred-work.md and keep a `.gitkeep`-free clean tree**

  ```bash
  git mv planning/deferred-work.md planning/deferred.md
  ```

- [ ] **Step 3: Verify the templates are byte-identical to source**

  ```bash
  for f in design plan change; do
    diff -q /Users/kevinsmith/src/pypi/faststream-outbox/planning/_templates/$f.md planning/_templates/$f.md
  done
  ```
  Expected: no output (identical).

- [ ] **Step 4: Commit**

  The `git mv` in Step 2 already staged the rename; just add the templates.
  ```bash
  git add planning/_templates planning/deferred.md
  git commit -m "chore(planning): bootstrap convention skeleton (templates, deferred.md rename)

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 2: Split `engineering.md` into `architecture/` (and delete it)

**Files:**
- Create: `architecture/{overview,client,middleware,decoders,errors,resilience,extras,testing}.md`
- Delete: `planning/engineering.md`
- Source: `planning/engineering.md` (read in full first)

Re-projection rules for every file:
1. Relocate the mapped `engineering.md` content; **flatten "as of 0.x …"
   narration to present tense** (the truth axis is the present).
2. **Drop history pointers** (`see planning/archive/specs/…`, "Shipped in
   v0.X", roadmap "see …" links) — that record now lives in the bundles.
3. **No frontmatter** in any `architecture/` file (living prose, dated by git).
4. Do **not** carry §8 (roadmap), the v0.1→v0.2 "deleted/rewritten"
   archaeology, or the §9 deferred stub into any file — they dissolve.

Per-file source map:

| File | From `engineering.md` |
|------|-----------------------|
| `overview.md` | §1 (present-tense intent + the "three things" framing + "httpx2 is part of the public surface"), §2 invariants (keep the *why*), §5 module-layout tree |
| `client.md` | the `Client`/`AsyncClient` surface, the internal terminal + error-mapping location (from §3 intro + §4 paras 4–5), sync/async parity, `stream()` (from §1 0.5.0 line) |
| `middleware.md` | §3 Seam A in full + the "why no standalone OTel middleware" rationale (from §8's 5-4 retirement note) |
| `decoders.md` | §3 Seam B in full (dispatch, default-list, single-pass rule, per-instance cache, `MissingDecoderError`) |
| `errors.md` | §4 in full |
| `resilience.md` | Retry/`RetryBudget`/Bulkhead/backoff + the logging/OTel events they emit + **new** CircuitBreaker/AsyncTimeout paragraph |
| `extras.md` | §3 Seam C + §7 optional-extras pattern + the isolation test |
| `testing.md` | §6 in full |

- [ ] **Step 1: Read the source**

  Read `planning/engineering.md` end to end before writing any file.

- [ ] **Step 2: Author the eight files**

  Write each `architecture/*.md` per the map and the re-projection rules.
  Each file opens with an `#` H1 title (e.g. `# Errors`) and present-tense
  prose. Keep code samples (the `raise NotFoundError(response)` block, the
  `pyproject` extras block, the module tree) verbatim.

- [ ] **Step 3: Add the CircuitBreaker/AsyncTimeout paragraph to `resilience.md`**

  Source the present-tense facts from
  `planning/plans/2026-06-13-circuit-breaker-and-timeout.md` and
  `planning/specs/2026-06-13-circuit-breaker-and-timeout-design.md` (still at
  their pre-migration paths during this task). Cover: `AsyncCircuitBreaker`
  (classic consecutive-failure) + sync `CircuitBreaker`; `CircuitOpenError`;
  `AsyncTimeout` overall-deadline middleware (rejects non-finite timeouts);
  and the documented composition order (`AsyncBulkhead` → … per the shipped
  docs). Do not invent behavior not in those sources.

- [ ] **Step 4: Delete the old truth file**

  ```bash
  git rm planning/engineering.md
  ```

- [ ] **Step 5: Sanity-check no `architecture/` file carries frontmatter or history pointers**

  ```bash
  ! grep -rlE '^---$|planning/(specs|plans|archive)|^status:' architecture/ && echo OK
  ```
  Expected: `OK`.

- [ ] **Step 6: Commit**

  Step 4 already staged the deletion; just add the new files.
  ```bash
  git add architecture/
  git commit -m "docs(architecture): split engineering.md into per-capability truth files

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 3: Migrate the archive cohort (2026-05-31 → 2026-06-05)

**Files:** rows `2026-05-31.*` through `2026-06-05.*` of the bundle map.
Source dirs: `planning/archive/specs/`, `planning/archive/plans/`.

For each bundle:
- `mkdir -p planning/changes/archive/<id>`
- `git mv` the design source → `planning/changes/archive/<id>/design.md`
- `git mv` the plan source → `planning/changes/archive/<id>/plan.md` (skip for
  **design-only** rows)
- Prepend frontmatter to `design.md`: `status: shipped`, `date: <date>`,
  `slug: <slug>`, `supersedes`/`superseded_by` per the map (else `null`),
  `pr: <n>`, `outcome: '<map outcome>'`. To `plan.md`: `status: shipped`,
  `date`, `slug`, `spec: <slug>`, `pr: <n>`.
- If the file already has a leading `# …` H1, leave the body; insert
  frontmatter above it.

- [ ] **Step 1: Move + frontmatter the 2026-05-31 cohort (rows .01–.09)**

  Process each `2026-05-31.NN` row. Example for `.03`:
  ```bash
  mkdir -p planning/changes/archive/2026-05-31.03-middleware-protocol-and-chain
  git mv planning/archive/specs/2026-05-31-middleware-protocol-and-chain-design.md \
         planning/changes/archive/2026-05-31.03-middleware-protocol-and-chain/design.md
  git mv planning/archive/plans/2026-05-31-middleware-protocol-and-chain-plan.md \
         planning/changes/archive/2026-05-31.03-middleware-protocol-and-chain/plan.md
  ```
  Then add frontmatter per the rule above. `.02-shipped-work-review` is
  **design-only** (source `planning/archive/specs/2026-05-31-shipped-work-review.md`,
  no plan).

- [ ] **Step 2: Move + frontmatter the 2026-06-01 → 2026-06-05 cohort**

  Rows `2026-06-01.01` through `2026-06-05.07`. `.02-v0.2-retro-and-housekeeping`
  (2026-06-04) is **design-only**. Apply `supersedes:` to
  `2026-06-03.02-thin-httpx2-wrapper` and `superseded_by:` to its three
  superseded bundles per the map.

- [ ] **Step 3: Verify the source dirs are empty and removable**

  ```bash
  ls planning/archive/specs planning/archive/plans 2>/dev/null
  ```
  Expected: empty. Then `git rm -r --ignore-unmatch` is unnecessary (git mv
  already staged the moves); remove the now-empty `planning/archive/` tree:
  ```bash
  rmdir planning/archive/specs planning/archive/plans planning/archive 2>/dev/null || true
  ```

- [ ] **Step 4: Commit**

  ```bash
  git add planning/changes/archive
  git commit -m "docs(planning): migrate 0.1.0–0.7.0 specs/plans into change bundles

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 4: Migrate the flat cohort (2026-06-06 → 2026-06-13)

**Files:** rows `2026-06-06.*` through `2026-06-13.02` of the bundle map.
Source dirs: `planning/specs/`, `planning/plans/`.

Same move+frontmatter procedure as Task 3.

- [ ] **Step 1: Move + frontmatter rows 2026-06-06 → 2026-06-08**

  Process `2026-06-06.01` through `2026-06-08.08`. Both `decoder-error` and
  `deep-audit` are `pr: 32`; both `retry-budget-cluster` and
  `post-080-doc-sweep` are `pr: 34`. Example for `deep-audit`:
  ```bash
  mkdir -p planning/changes/archive/2026-06-07.03-deep-audit
  git mv planning/specs/2026-06-07-deep-audit-design.md \
         planning/changes/archive/2026-06-07.03-deep-audit/design.md
  git mv planning/plans/2026-06-07-deep-audit-plan.md \
         planning/changes/archive/2026-06-07.03-deep-audit/plan.md
  ```

- [ ] **Step 2: Move + frontmatter rows 2026-06-10 → 2026-06-13**

  Process `2026-06-10.01` through `2026-06-13.02`. For circuit-breaker the
  plan source has no `-plan` suffix:
  ```bash
  mkdir -p planning/changes/archive/2026-06-13.02-circuit-breaker-and-timeout
  git mv planning/specs/2026-06-13-circuit-breaker-and-timeout-design.md \
         planning/changes/archive/2026-06-13.02-circuit-breaker-and-timeout/design.md
  git mv planning/plans/2026-06-13-circuit-breaker-and-timeout.md \
         planning/changes/archive/2026-06-13.02-circuit-breaker-and-timeout/plan.md
  ```

- [ ] **Step 3: Verify flat source dirs are empty**

  ```bash
  ls planning/specs planning/plans 2>/dev/null
  ```
  Expected: empty. Then:
  ```bash
  rmdir planning/specs planning/plans 2>/dev/null || true
  ```

- [ ] **Step 4: Commit**

  ```bash
  git add planning/changes/archive
  git commit -m "docs(planning): migrate 0.8.0–0.10.0 specs/plans into change bundles

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 5: Move audit reports and tooling

**Files:**
- `planning/audit/2026-06-07-deep-audit.md` → `planning/audits/2026-06-07-deep-audit.md`
- `planning/audit/2026-06-12-delta-audit.md` → `planning/audits/2026-06-12-delta-audit.md`
- `planning/audit/2026-06-13-delta-audit.md` → `planning/audits/2026-06-13-delta-audit.md`
- `planning/audit/{workflow,workflow-delta}.mjs`, `_discover.json` → `planning/audits/scripts/`

- [ ] **Step 1: Move reports and tooling**

  ```bash
  git mv planning/audit/2026-06-07-deep-audit.md  planning/audits/2026-06-07-deep-audit.md
  git mv planning/audit/2026-06-12-delta-audit.md planning/audits/2026-06-12-delta-audit.md
  git mv planning/audit/2026-06-13-delta-audit.md planning/audits/2026-06-13-delta-audit.md
  git mv planning/audit/workflow.mjs       planning/audits/scripts/workflow.mjs
  git mv planning/audit/workflow-delta.mjs planning/audits/scripts/workflow-delta.mjs
  git mv planning/audit/_discover.json     planning/audits/scripts/_discover.json
  rmdir planning/audit 2>/dev/null || true
  ```

- [ ] **Step 2: Verify old audit dir is gone**

  ```bash
  test ! -d planning/audit && echo OK
  ```
  Expected: `OK`.

- [ ] **Step 3: Commit**

  ```bash
  git add planning/audits
  git commit -m "docs(planning): move audit reports to audits/, tooling to audits/scripts/

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 6: Author `planning/README.md`

**Files:**
- Create: `planning/README.md`
- Source for the `## Conventions` block: `faststream-outbox/planning/README.md`
  lines 7–67 (the `## Conventions` heading through the end of `### Frontmatter`).

- [ ] **Step 1: Write the repo-specific intro**

  ```markdown
  # Planning

  Specs, plans, and change history for `httpware`. The living truth about
  *what the system does now* lives in [`architecture/`](../architecture/) at
  the repo root; this directory records *how it got there*.
  ```

- [ ] **Step 2: Append the byte-identical `## Conventions` block**

  Copy `faststream-outbox/planning/README.md` lines 7–67 verbatim. Verify:
  ```bash
  sed -n '7,67p' /Users/kevinsmith/src/pypi/faststream-outbox/planning/README.md > /tmp/conv-src.md
  # after writing planning/README.md, extract the same block and diff:
  awk '/^## Conventions$/{f=1} f; /^### Frontmatter$/{c=1} c&&/^## Index$/{exit}' planning/README.md
  ```
  The `## Conventions` … through end-of-`### Frontmatter` text must match
  `/tmp/conv-src.md` exactly (modern-python repos share this block byte-for-byte).

- [ ] **Step 3: Write the repo-specific `## Index`**

  - `### Active` → one entry: **portable-planning-convention**
    (`changes/active/2026-06-13.03-portable-planning-convention/design.md`).
  - `### Archived (shipped)` → one bullet per archived bundle from the map,
    newest first, each linking `changes/archive/<id>/design.md` with `(#PR,
    date)` and a one-line gloss.
  - `## Other` → `architecture/` (the promotion target), `audits/`,
    `deferred.md`.

- [ ] **Step 4: Commit**

  ```bash
  git add planning/README.md
  git commit -m "docs(planning): add README with portable Conventions + repo Index

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 7: Repoint inbound links

**Files:**
- Modify: `docs/resilience.md:357`, `docs/middleware.md:113`, `docs/middleware.md:201`, `docs/errors.md:186`, `docs/testing.md:114`, `docs/index.md:186`
- Modify: `CLAUDE.md` (the "Where to find what" list, the Per-feature Workflow line, the Seam B link at ~:84, the "When in doubt" links at ~:90–95)
- Scan: `planning/releases/*.md`

Repoint map (prose `engineering.md §N` → `architecture/<file>`):

| Location | Old | New |
|----------|-----|-----|
| `docs/resilience.md:357` | `` `planning/engineering.md` §3 `` | `` `architecture/middleware.md` `` |
| `docs/middleware.md:113` | `` `planning/engineering.md` §8 `` | `` `architecture/middleware.md` `` |
| `docs/middleware.md:201` | `` `planning/engineering.md` §3 (Seam A) `` | `` `architecture/middleware.md` (Seam A) `` |
| `docs/errors.md:186` | `` `planning/engineering.md` §4 `` | `` `architecture/errors.md` `` |
| `docs/testing.md:114` | `` `planning/engineering.md` §6 `` | `` `architecture/testing.md` `` |
| `docs/index.md:186` | `[…](https://github.com/modern-python/httpware/blob/main/planning/engineering.md)` | `[…](https://github.com/modern-python/httpware/blob/main/architecture/overview.md)` and reword the gloss to point at the `architecture/` set |

- [ ] **Step 1: Edit the six `docs/` references**

  Apply the repoint map. These are inline-code prose refs (not mkdocs links),
  except `docs/index.md:186` which is an absolute GitHub URL — update the URL
  and adjust its description to "per-capability design notes under
  `architecture/`".

- [ ] **Step 2: Rewrite the `CLAUDE.md` planning section**

  - "Where to find what" list: replace the `planning/engineering.md`,
    `planning/specs/`/`planning/plans/`, `planning/archive/...`,
    `planning/deferred-work.md` bullets with: `architecture/` (the truth home
    / promotion target), `planning/changes/{active,archive}/` (change
    bundles), `planning/audits/`, `planning/retros/`, `planning/releases/`,
    `planning/deferred.md`, `planning/_templates/`.
  - Per-feature Workflow line: `brainstorming → design.md in
    changes/active/<id>/ → writing-plans → plan.md in the same bundle →
    executing-plans / subagent-driven-development → requesting-code-review →
    finishing-a-development-branch; on ship, promote into
    architecture/<capability>.md and move the bundle to changes/archive/`.
  - Seam B link (`[engineering.md](planning/engineering.md) §Seam B`) →
    `[architecture/decoders.md](architecture/decoders.md)`.
  - "When in doubt" links → `architecture/` (e.g.
    `[architecture/overview.md](architecture/overview.md)`).

- [ ] **Step 3: Scan and repoint `planning/releases/`**

  ```bash
  grep -rn -E 'planning/(specs|plans|archive|audit|deferred-work|engineering)' planning/releases/ || echo "none"
  ```
  Repoint any hit to the matching `changes/archive/<id>/` bundle (or
  `architecture/`/`audits/`/`deferred.md`). If `none`, no edit.

- [ ] **Step 4: Commit**

  ```bash
  git add docs CLAUDE.md planning/releases
  git commit -m "docs: repoint inbound links to architecture/ + changes/

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 8: Verify and finalize

**Files:** none created; verification + active-bundle frontmatter note.

- [ ] **Step 1: Grep gates — no stale paths remain**

  ```bash
  test ! -f planning/engineering.md && echo "engineering.md gone"
  # No tracked file outside changes/archive references the old paths:
  grep -rIn -E 'planning/(specs|plans|archive|audit|deferred-work)|planning/engineering\.md' \
    --include='*.md' --include='*.yml' --include='*.yaml' --include='*.toml' . \
    | grep -vE '^\./planning/changes/archive/' || echo "no stale refs"
  ```
  Expected: `engineering.md gone` and `no stale refs`.

- [ ] **Step 2: `architecture/` has exactly eight files, none with frontmatter**

  ```bash
  ls architecture/ | sort | tr '\n' ' '; echo
  ! grep -rl '^---$' architecture/ && echo "no frontmatter"
  ```
  Expected: the eight files; `no frontmatter`.

- [ ] **Step 3: `changes/active/` holds only this bundle**

  ```bash
  ls planning/changes/active/
  ```
  Expected: `2026-06-13.03-portable-planning-convention`.

- [ ] **Step 4: Lint**

  ```bash
  just lint-ci
  ```
  Expected: clean (no auto-fix needed; CI-equivalent check).

- [ ] **Step 5: Docs build strict**

  ```bash
  uv run mkdocs build --strict
  ```
  Expected: build succeeds, no warnings. (If `mkdocs` is not in the default
  env, use the docs group: `uv run --group docs mkdocs build --strict`, or
  the project's documented docs command.)

- [ ] **Step 6: Note — active-bundle frontmatter is finalized at merge**

  When this PR merges, set the active bundle's `design.md`/`plan.md`
  frontmatter to `status: shipped`, `pr: <this PR>`, fill `outcome:`, move
  the bundle to `changes/archive/2026-06-13.03-portable-planning-convention/`,
  and move its Index line from **Active** to **Archived**. (This is the first
  exercise of the promotion step the convention defines.)

- [ ] **Step 7: Commit any verification fixups**

  ```bash
  git add -A
  git commit -m "chore(planning): verification fixups for convention migration

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>" || echo "nothing to commit"
  ```

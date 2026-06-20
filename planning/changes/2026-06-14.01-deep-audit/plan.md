---
status: shipped
date: 2026-06-14
slug: deep-audit
spec: deep-audit
pr: null
---

# deep-audit — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps
> use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a refreshed multi-agent audit orchestrator
(`workflow-deep.mjs`) and run it to produce
`planning/audits/2026-06-14-deep-audit.md` — a full-codebase, report-only
deep audit covering performance, security/supply-chain, refactoring, and the
core correctness/concurrency/test dimensions.

**Spec:** [`design.md`](./design.md)

**Branch:** `audit/2026-06-14-deep-audit` (already created)

**Commit strategy:** Per-task commits. The script lands in its own commit;
the run produces the report in a synthesis-agent commit; the Index update is
a final commit.

> **Execution note — who runs which task.** Tasks 1–5 (build + syntax-check
> the script) are ordinary file edits and may be done by a subagent. **Task 6
> (run the audit) MUST be executed by the main session**, because it calls the
> `Workflow` tool, whose multi-agent fan-out the user explicitly opted into at
> the main loop — a sandboxed subagent cannot invoke it. Task 7 (validate +
> finalize) is also main-session.

---

### Task 1: Scaffold `workflow-deep.mjs` from the existing harness

**Files:**
- Create: `planning/audits/scripts/workflow-deep.mjs`
- Reference (read-only): `planning/audits/scripts/workflow.mjs`

Copy the delta-oriented harness into a new combined-run orchestrator, then
update only the `meta`, model IDs, and dimension list in this task. Prompts
and body come in later tasks.

- [ ] **Step 1: Copy the file**

  Run:
  ```bash
  cp planning/audits/scripts/workflow.mjs planning/audits/scripts/workflow-deep.mjs
  ```

- [ ] **Step 2: Replace the `meta` block** at the top of
  `workflow-deep.mjs` with:

  ```javascript
  export const meta = {
    name: 'httpware-deep-audit',
    description: 'Full-codebase deep audit: discover + 10 finders + 3-lens verify + single-report synthesis',
    phases: [
      { title: 'Discover', detail: 'Fresh module map' },
      { title: 'Find', detail: 'One finder per dimension (10)' },
      { title: 'Verify', detail: '3-lens panel per finding' },
      { title: 'Synthesize', detail: 'Triage + write the full report' },
    ],
  }
  ```

- [ ] **Step 3: Refresh the model IDs** near the bottom of the file. Replace:

  ```javascript
  const SONNET = 'claude-sonnet-4-6'
  const OPUS = 'claude-opus-4-7'
  ```

  with:

  ```javascript
  const SONNET = 'claude-sonnet-4-6'
  const OPUS = 'claude-opus-4-8'
  ```

- [ ] **Step 4: Syntax-check** (the body still references old prompts that
  exist, so this should parse):

  Run: `node --check planning/audits/scripts/workflow-deep.mjs`
  Expected: no output, exit 0.

  (Note: `node --check` validates syntax only; it does not resolve the
  workflow globals `agent`/`parallel`/`phase`/`log`, which is fine.)

---

### Task 2: Repoint the reused finder prompts and replace the doc finders

**Files:**
- Modify: `planning/audits/scripts/workflow-deep.mjs`

The reused finders (`correctness`, `concurrency`, `error_contract`, `tests`,
`public_api`, `optional_extras`) carry forward, but every prompt reference to
the old layout must point at current reality. The two old doc finders
(`docs`, `planning_docs`) are removed and replaced by a single
`architecture_docs` finder.

- [ ] **Step 1: Fix stale paths in the reused prompts.** In the
  `DIMENSION_PROMPTS` object, apply these substitutions wherever they appear
  in the `correctness`, `concurrency`, `error_contract`, `tests`,
  `public_api`, and `optional_extras` prompt strings:

  - `docs/*.md` / `docs/recipes/` / `docs/dev/` references → drop (those
    finders no longer cover the docs site; `architecture_docs` does).
  - `planning/engineering.md` → `CLAUDE.md` and `architecture/<capability>.md`.
  - Any `README.md` example references in `public_api` → keep `README.md` but
    add `architecture/*.md` as the doc cross-reference.
  - Leave the dimension-scoping ("out of scope: …") lines intact but update
    the parenthetical dimension numbers to names, since the dimension set
    changed (e.g. "(dimension 7-8)" → "(the architecture_docs finder)").

  The substantive instructions, targets ("6-12 findings"), and
  "default to silence" lines stay unchanged.

- [ ] **Step 2: Delete the `docs` and `planning_docs` prompts** from
  `DIMENSION_PROMPTS` entirely.

- [ ] **Step 3: Add the `architecture_docs` prompt** to `DIMENSION_PROMPTS`:

  ```javascript
    architecture_docs: `You are auditing architecture/*.md for DRIFT against
  the current code.

  Read every file: architecture/{overview,client,middleware,decoders,errors,
  resilience,extras,testing}.md. For each load-bearing claim, verify it
  against the actual src/httpware/ code, public API (__init__.py __all__),
  and tests.

  Look for:
  - Class/decorator/method names made stale by the 0.8.0 Async* rename or
    later changes (Middleware vs AsyncMiddleware, Retry vs AsyncRetry, etc.).
  - Described behavior the code no longer matches (circuit breaker states,
    async timeout non-finite handling, multi-decoder routing, per-instance
    decoder cache, send_with_response).
  - Invariants stated as enforced that are actually only review-enforced (the
    2026-06-13 docs work corrected some of these — check none regressed).
  - Import statements or code blocks that would not run against current
    src/httpware/.
  - Cross-references / links that do not resolve.

  Report each with the architecture file, the inaccurate quote, and the
  current truth. Out of scope: docs/ site content and planning/ docs.
  4-10 findings.`,
  ```

- [ ] **Step 4: Syntax-check.**

  Run: `node --check planning/audits/scripts/workflow-deep.mjs`
  Expected: no output, exit 0.

---

### Task 3: Add the three new finder prompts

**Files:**
- Modify: `planning/audits/scripts/workflow-deep.mjs`

Add `performance`, `security`, and `refactoring` to `DIMENSION_PROMPTS`.

- [ ] **Step 1: Add the `performance` prompt:**

  ```javascript
    performance: `You are auditing the httpware repository for PERFORMANCE
  issues only.

  Scope: src/httpware/ — the per-request hot path above all. Read client.py
  (send / send_with_response / stream, sync and async), middleware/chain.py
  (compose + Next), and middleware/resilience/{retry,bulkhead,budget,
  circuit_breaker,timeout}.py.

  Look for:
  - Allocations or work repeated per-request that could be hoisted to
    __init__ (chain re-composition, rebuilding decoder lists, recreating
    closures, redundant dict/list copies).
  - Lock-hold scope: work done while holding RetryBudget/Bulkhead/
    CircuitBreaker locks that could happen outside the critical section;
    contention hot spots under concurrency.
  - Decoder / TypeAdapter caching: is the per-instance cache (0.9.0) actually
    hit, or rebuilt? Any O(n) decoder-list scan that runs per response when it
    could be memoized per model.
  - Async overhead: event-loop-blocking sync calls inside async paths,
    sequential awaits that could be concurrent, needless gather/wrapping.
  - Response body handling: bytes read/copied more than once, eager reads on
    a streaming path.

  Quantify the cost where you can (per-request vs per-client, O(n) vs O(1)).
  This dimension is about COST, not safety — concurrency hazards and logic
  bugs belong to other finders. Default to NOT reporting micro-optimizations
  with no measurable payoff. 6-12 findings target.`,
  ```

- [ ] **Step 2: Add the `security` prompt:**

  ```javascript
    security: `You are auditing the httpware repository for SECURITY and
  SUPPLY-CHAIN issues only.

  Look for:
  - Untrusted-response trust boundaries: status code, headers, and body come
    from the server — anywhere httpware trusts them without bound (e.g.
    unbounded reads driven by a header, status used to index without guard).
  - Decoder deserialization safety: pydantic and msgspec run on
    attacker-controlled bytes in decoders/{pydantic,msgspec}.py. Any path that
    could be driven to excessive recursion, memory, or arbitrary type
    construction? Is body size ever bounded?
  - Inherited httpx2 surfaces: redirect-following, URL handling, proxy/SSRF
    exposure — does httpware widen or fail to constrain anything httpx2 leaves
    to the caller? Report the boundary even if the default is httpx2's.
  - Secret leakage: do exception messages, repr, or log/OTel events ever
    include auth headers, cookies, or URLs with embedded credentials? Check
    errors.py (StatusError holds the full Response) and
    _internal/observability.py.
  - Supply chain: version floors/ceilings in pyproject.toml for httpx2 and the
    optional extras (pydantic/msgspec/otel). Unpinned-floor or over-wide
    ranges that could pull a vulnerable transitive version.

  Report the trust boundary even when the current default is safe, but mark
  severity honestly (a documented httpx2 default is a nit; an unbounded
  attacker-driven allocation is high). 6-12 findings target.`,
  ```

- [ ] **Step 3: Add the `refactoring` prompt:**

  ```javascript
    refactoring: `You are auditing the httpware repository for REFACTORING
  opportunities and INCONSISTENCIES only — not bugs.

  Look for:
  - Sync/async duplication: logic copy-pasted between Client and AsyncClient
    (or Retry/AsyncRetry, Bulkhead/AsyncBulkhead) that could share a helper
    WITHOUT crossing a protocol seam (Seam A/B/C in CLAUDE.md). Note where a
    copy has already drifted.
  - Inconsistent patterns: error construction, naming, signatures, or control
    flow that differ for no reason across sibling modules. Cross-check the
    conventions in CLAUDE.md (StatusError vs other ClientError __init__ rules,
    naming, import style).
  - Dead or unreachable code; over-complex branching that flattens; module
    boundaries that have eroded.

  Every finding states the concrete payoff (what gets simpler / what
  divergence it prevents), not aesthetics. A suggestion the conventions are
  silent on is a nit or low at most. Never propose crossing a documented
  protocol seam. Default severity low/nit unless a duplication has already
  caused a real divergence. 5-10 findings target.`,
  ```

- [ ] **Step 4: Syntax-check.**

  Run: `node --check planning/audits/scripts/workflow-deep.mjs`
  Expected: no output, exit 0.

---

### Task 4: Rework Verify (keep refuted candidates) and Synthesize (single report)

**Files:**
- Modify: `planning/audits/scripts/workflow-deep.mjs`

Two structural changes: the verify pass must retain refuted candidates (for
the Negative-results section), and synthesis becomes a single-report writer
instead of a per-chunk appender.

- [ ] **Step 1: Replace the Verify `.then(...)` body** so non-survivors are
  kept rather than nulled. Find the block inside the `verified = await
  parallel(...)` call that ends with:

  ```javascript
        return surviving ? { ...f, final_severity: severity, lensesConfirming } : null
  ```

  Replace the whole `.then(verdicts => { ... })` callback with:

  ```javascript
      )).then(verdicts => {
        const live = verdicts.filter(Boolean)
        const confirms = live.filter(v => v.confirmed).length
        const surviving = confirms >= 2
        const lensesConfirming = live.filter(v => v.confirmed).map(v => v.lens)
        const adjustments = live.map(v => v.severity_adjustment).filter(Boolean)
        const raiseCount = adjustments.filter(a => a === 'raise').length
        const lowerCount = adjustments.filter(a => a === 'lower').length
        let severity = f.suspected_severity
        if (lowerCount >= 1) severity = lowerOne(severity)
        if (raiseCount >= 2) severity = raiseOne(severity)
        if (verdicts.every(v => v === null)) {
          log(`WARNING: all 3 verifiers failed for finding "${f.title}" (${f.file}:${f.line_hint}) — dropped`)
          return null
        }
        const refuteReason = live.find(v => !v.confirmed)?.reason ?? 'no verifier confirmed'
        return surviving
          ? { ...f, surviving: true, final_severity: severity, lensesConfirming }
          : { ...f, surviving: false, refuteReason }
      })
  ```

- [ ] **Step 2: Split confirmed vs refuted** after the verify block.
  Replace:

  ```javascript
  const confirmed = verified.filter(Boolean)
  log(`${confirmed.length}/${allFindings.length} findings confirmed by ≥2 verifiers`)
  ```

  with:

  ```javascript
  const triaged = verified.filter(Boolean)
  const confirmed = triaged.filter(v => v.surviving)
  const refuted = triaged.filter(v => !v.surviving)
  log(`${confirmed.length}/${allFindings.length} confirmed by ≥2 verifiers; ${refuted.length} refuted (kept for Negative results)`)
  ```

- [ ] **Step 3: Replace `SYNTHESIS_PROMPT`** (the whole `const
  SYNTHESIS_PROMPT = (...) => \`...\`` definition) with the single-report
  version:

  ```javascript
  const SYNTHESIS_PROMPT = (dims, confirmed, refuted, auditFile, discoverFile) => `
  You are writing the FINAL httpware deep-audit report. This is a single
  combined run (not chunked) — you write the whole file, including the
  top-of-file Summary.

  You have ${confirmed.length} CONFIRMED findings (survived ≥2/3 verifiers) and
  ${refuted.length} REFUTED candidates (investigated, did not survive) across
  dimensions: ${dims.join(', ')}.

  Tasks:
  1. Triage each confirmed finding into a bucket: blocker / high / medium /
     low / nit, applying severity strictly. If more than 4 nits share a
     dimension, roll them into one "<dimension> nits (rolled up)" entry (the
     rolled entry counts its constituents in the totals).
  2. Dedupe confirmed findings against each other (file + line ±5 + similar
     claim); fold duplicates into one entry.
  3. Write ${auditFile} with this structure:
     - "# httpware deep audit — 2026-06-14"
     - "**Status:** complete" and a one-line "**Method:**" (ten adversarial
       finders → 3-lens verify panel → ≥2/3 to survive → single synthesis).
     - "## Summary" — counts per bucket (Blockers/High/Medium/Low/Nits), the
       single headline finding in one sentence, and an explicit "Not covered"
       line.
     - "## Findings" — grouped by bucket. Each finding: a "#### " title, a
       "*(dimension — verified)*" tag line, file:line in \`code\` format, a
       ≤3-sentence claim, a fenced code block with the evidence quote, the
       verifier consensus (e.g. "panel 3/3: code_reality, reproducer,
       spec_grounded"), and a one-line suggested direction. Directions only —
       do NOT write fixes or patches.
     - "## Negative results (verified correct)" — a bulleted list built from
       the REFUTED candidates and invariants the finders checked and found
       held. One line each: what was checked and why it is fine. Summarize;
       do not dump raw JSON.
  4. Use the Write tool to create ${auditFile} (overwrite if present).
  5. Stage and commit ONLY the report and the discover map — NO source edits:
       git add ${auditFile} ${discoverFile}
       git commit -m "audit(deep): 2026-06-14 full-codebase audit — <N> confirmed (<bucket counts>)"
     Then run \`git status\` to confirm a clean tree. If git reports any
     modified src/ or tests/ file, STOP and report it — this pass must not
     touch source.

  CONFIRMED findings JSON:
  ${JSON.stringify(confirmed, null, 2)}

  REFUTED candidates JSON (for Negative results — summarize, do not dump):
  ${JSON.stringify(refuted, null, 2)}
  `
  ```

- [ ] **Step 4: Replace the Synthesize phase call and return value** at the
  bottom of the script body. Replace:

  ```javascript
  phase('Synthesize')
  await agent(
    SYNTHESIS_PROMPT(cfg.chunk_id, cfg.dimensions, confirmed, cfg.audit_file),
    { model: OPUS, label: `synthesize:chunk-${cfg.chunk_id}` },
  )

  return {
    chunk_id: cfg.chunk_id,
    candidates: allFindings.length,
    confirmed: confirmed.length,
    by_severity: countBySeverity(confirmed),
  }
  ```

  with:

  ```javascript
  phase('Synthesize')
  await agent(
    SYNTHESIS_PROMPT(cfg.dimensions, confirmed, refuted, cfg.audit_file, cfg.discover_file),
    { model: OPUS, label: 'synthesize:deep' },
  )

  return {
    candidates: allFindings.length,
    confirmed: confirmed.length,
    refuted: refuted.length,
    by_severity: countBySeverity(confirmed),
  }
  ```

- [ ] **Step 5: Make discover always run** for the combined run. Replace the
  guard:

  ```javascript
  if (cfg.run_discover) {
  ```

  with:

  ```javascript
  if (cfg.run_discover !== false) {
  ```

  (Discover defaults on; pass `run_discover: false` only to reuse an existing
  map.) Confirm `countBySeverity` reads `f.final_severity ?? f.suspected_severity`
  — it does in the helper; leave it.

- [ ] **Step 6: Syntax-check.**

  Run: `node --check planning/audits/scripts/workflow-deep.mjs`
  Expected: no output, exit 0.

---

### Task 5: Commit the orchestrator

**Files:**
- Commit: `planning/audits/scripts/workflow-deep.mjs`

- [ ] **Step 1: Final syntax + grep sanity.**

  Run:
  ```bash
  node --check planning/audits/scripts/workflow-deep.mjs && \
  grep -c "performance:\|security:\|refactoring:\|architecture_docs:" planning/audits/scripts/workflow-deep.mjs
  ```
  Expected: exit 0 and a count of `4` (one per new/repointed finder key).

- [ ] **Step 2: Confirm the old doc finders are gone.**

  Run: `grep -c "planning_docs:\|  docs:" planning/audits/scripts/workflow-deep.mjs || true`
  Expected: `0`.

- [ ] **Step 3: Commit.**

  ```bash
  git add planning/audits/scripts/workflow-deep.mjs
  git commit -m "audit(tooling): combined-run deep-audit orchestrator

  Forks workflow.mjs into workflow-deep.mjs: refreshed model IDs, paths
  repointed to architecture/ + planning/changes, three new finders
  (performance, security, refactoring), architecture_docs replaces the
  docs/planning_docs finders, and refuted candidates are kept for a
  Negative-results section in a single combined-run report.

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 6: Run the audit (main session only)

**Files:**
- Produces: `planning/audits/scripts/_discover-2026-06-14.json`
- Produces: `planning/audits/2026-06-14-deep-audit.md`

This task invokes the `Workflow` tool. It cannot be delegated to a sandboxed
subagent — run it from the main session.

- [ ] **Step 1: Invoke the Workflow** with the script path and config:

  ```
  Workflow({
    scriptPath: 'planning/audits/scripts/workflow-deep.mjs',
    args: {
      dimensions: [
        'correctness', 'concurrency', 'error_contract',
        'performance', 'security', 'refactoring',
        'tests', 'public_api', 'optional_extras', 'architecture_docs'
      ],
      run_discover: true,
      discover_file: 'planning/audits/scripts/_discover-2026-06-14.json',
      audit_file: 'planning/audits/2026-06-14-deep-audit.md'
    }
  })
  ```

  Expected: a `runId` returned immediately, then a `<task-notification>` when
  all four phases finish. Watch live progress with `/workflows`.

- [ ] **Step 2: Confirm the run returned a sane shape.** When the
  notification arrives, the workflow return value should report
  `confirmed > 0` across the ten finders. If `confirmed === 0` AND
  `candidates === 0`, the discover map or paths are broken — STOP and inspect
  `_discover-2026-06-14.json` before trusting a "clean" result (this is the
  failure mode that stalled the 2026-06-07 `tests` dimension).

---

### Task 7: Validate the report, reproduce the headline, finalize

**Files:**
- Verify: `planning/audits/2026-06-14-deep-audit.md`
- Modify: `planning/README.md` (Index)

- [ ] **Step 1: Confirm the report exists and has the required structure.**

  Run:
  ```bash
  test -f planning/audits/2026-06-14-deep-audit.md && \
  grep -c "^## Summary\|^## Findings\|^## Negative results" planning/audits/2026-06-14-deep-audit.md
  ```
  Expected: file exists and count is `3` (all three top-level sections
  present).

- [ ] **Step 2: Confirm the synthesis agent did not touch source.**

  Run: `git status --porcelain src tests`
  Expected: empty output. If anything appears, revert it — this audit is
  report-only.

- [ ] **Step 3: Reproduce the single highest-severity finding.** Read the
  top finding in the report. Write the 3–5 line reproducer it cites (in a
  scratch test or a `python -c`/`uv run pytest -k` invocation against
  `httpx2.MockTransport` per `architecture/testing.md`) and confirm it
  actually demonstrates the claimed behavior. If it does not reproduce, note
  it in the report as "could not reproduce — downgrade" rather than trusting
  the panel.

  (If the report has zero High/Blocker findings, skip repro and note in the
  report summary that the headline is Medium-or-below.)

- [ ] **Step 4: Add the Index entry.** In `planning/README.md`, under
  `### Active`, replace `_None._` with:

  ```markdown
  - **[deep-audit](changes/active/2026-06-14.01-deep-audit/design.md)** (2026-06-14) — Full-codebase deep audit covering the perf/security/supply-chain gaps the 2026-06-07 audit skipped, plus correctness, concurrency, refactoring, and test quality. Report: [audits/2026-06-14-deep-audit.md](audits/2026-06-14-deep-audit.md). Report-only; confirmed findings spawn follow-up bundles.
  ```

- [ ] **Step 5: Commit the Index update.**

  ```bash
  git add planning/README.md
  git commit -m "docs(planning): index the 2026-06-14 deep audit

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

- [ ] **Step 6: Report the outcome** to the user: bucket counts, the
  headline finding, whether it reproduced, and the recommended next step
  (triage confirmed findings into follow-up `planning/changes/active/`
  bundles in a separate session). Do not open fix PRs here.

---

## Notes for the executor

- **Report-only.** No source edits in any task. The synthesis agent is
  explicitly instructed to commit only the report + discover map and to stop
  if `git status` shows a dirty `src/` or `tests/`.
- **Token budget.** Roughly ten finders + (~80 candidates × 3 verifiers) +
  synthesis ≈ 250 mostly-Sonnet agents; Opus only for discover and synthesis.
  The 15/dimension cap and the ≥2/3 survive gate bound the verify fan-out.
- **Resumability.** If the Workflow dies mid-run, relaunch with
  `Workflow({ scriptPath, resumeFromRunId })` — unchanged `agent()` calls
  return cached results; only the failed/new calls re-run.

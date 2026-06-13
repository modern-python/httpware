---
status: shipped
date: 2026-06-07
slug: deep-audit
spec: deep-audit
pr: 32
---

# Deep Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a single triaged findings file at `planning/audit/2026-06-07-deep-audit.md` covering correctness, concurrency, error contract, public API, optional-extras boundary, tests, docs, and planning-doc accuracy across the httpware repo.

**Architecture:** Four chunked `Workflow` invocations of a single parametrized JS script (`planning/audit/workflow.mjs`). Each invocation runs a `Discover` (chunk 1 only) → fan-out finders (one per dimension, Sonnet 4.6) → per-finding 3-voter verifier panel (Sonnet 4.6, pipelined) → chunk synthesis (Opus 4.7) that appends to the audit file. User gates between chunks; a final merge pass (Opus 4.7) dedupes across chunks and rewrites the summary header.

**Tech Stack:** Workflow tool (JS scripts), Claude Sonnet 4.6 + Opus 4.7 subagents, JSON-schema-bound structured output, git for chunk-by-chunk commits.

---

## Spec reference

The validated spec is at `planning/specs/2026-06-07-deep-audit-design.md`. Read it before starting. Decisions locked there (not re-debated here): four-chunk structure, dimension list, model assignment, severity buckets, 2-of-3 verifier consensus, file layout, gate behavior.

This plan resolves the spec's "Open questions for writing-plans":

- `_discover.json` **is committed** alongside the audit file.
- Finder prompts are drafted in Task 2 below and **confirmed with the user in Task 3** before chunk 1 runs.
- Audit file lives under `planning/audit/` (new directory).
- Workflow script lives at `planning/audit/workflow.mjs` (committed; reusable for future audits via the `args` parameter).

## File structure

```
planning/audit/
├── workflow.mjs                            # Created in Task 2; parametrized by args
├── _discover.json                          # Created in Task 4; reused chunks 2-4
└── 2026-06-07-deep-audit.md                # Created in Task 1 (scaffold), grown by each chunk
```

No source code under `src/httpware/` is touched. No tests under `tests/` are added. This work produces only the artifacts above.

## A note on TDD here

This plan does **not** follow code-style TDD because the deliverable is a markdown report, not production code. The "verification" model is instead:

- **Schema-bound output** — finders and verifiers are forced to call `StructuredOutput` against a defined JSON schema, so malformed output cannot reach synthesis.
- **2-of-3 verifier consensus** — false positives are killed before they hit the file.
- **User review gates** — between every chunk, the user inspects the appended section and decides continue/adjust/stop.

The workflow script itself is small (~150 lines of JS) and its correctness is checked by a **dry-run on a single small dimension first** (Task 4, Step 1) before the full chunk 1 launches.

---

## Task 1: Scaffold `planning/audit/` and seed the audit file

**Files:**
- Create: `planning/audit/2026-06-07-deep-audit.md`

- [ ] **Step 1: Create the directory and the audit file with a header**

```bash
mkdir -p planning/audit
```

Write `planning/audit/2026-06-07-deep-audit.md` with:

```markdown
# httpware deep audit — 2026-06-07

**Status:** in progress
**Spec:** [planning/specs/2026-06-07-deep-audit-design.md](../specs/2026-06-07-deep-audit-design.md)
**Plan:** [planning/plans/2026-06-07-deep-audit-plan.md](../plans/2026-06-07-deep-audit-plan.md)

## Summary

_Counts updated after final merge._

- Blockers: —
- High: —
- Medium: —
- Low: —
- Nits: —

<!-- chunk sections appended below in order: 1, 2, 3, 4 -->
```

- [ ] **Step 2: Commit the scaffold**

```bash
git add planning/audit/2026-06-07-deep-audit.md
git commit -m "audit: scaffold audit report file"
```

Expected: clean commit; no other files staged.

---

## Task 2: Draft the parametrized Workflow script

**Files:**
- Create: `planning/audit/workflow.mjs`

The script is parameterized by `args` so the same file runs all four chunks. Inputs the script reads from `args`:

```js
args = {
  chunk_id: 1 | 2 | 3 | 4,
  dimensions: string[],          // e.g. ["correctness", "concurrency", "error_contract"]
  run_discover: boolean,         // true only for chunk 1
  audit_file: string,            // "planning/audit/2026-06-07-deep-audit.md"
  discover_file: string,         // "planning/audit/_discover.json"
}
```

- [ ] **Step 1: Write the script skeleton with meta, schemas, and prompts**

Write `planning/audit/workflow.mjs`:

```js
export const meta = {
  name: 'httpware-audit-chunk',
  description: 'Run one chunk of the deep audit (discover + finders + verifiers + synthesis)',
  phases: [
    { title: 'Discover', detail: 'Module map (chunk 1 only)' },
    { title: 'Find', detail: 'One finder per dimension' },
    { title: 'Verify', detail: '3-voter panel per finding' },
    { title: 'Synthesize', detail: 'Triage and append to audit file' },
  ],
}

// ───── Schemas ──────────────────────────────────────────────────────────────

const FINDING_SCHEMA = {
  type: 'object',
  required: ['findings'],
  properties: {
    findings: {
      type: 'array',
      items: {
        type: 'object',
        required: ['dimension', 'title', 'file', 'line_hint', 'claim',
                   'evidence_quote', 'suspected_severity'],
        properties: {
          dimension: { type: 'string' },
          title: { type: 'string' },
          file: { type: 'string' },
          line_hint: { type: 'integer' },
          claim: { type: 'string' },
          evidence_quote: { type: 'string' },
          suspected_severity: { enum: ['blocker', 'high', 'medium', 'low', 'nit'] },
          reproducer_hint: { type: ['string', 'null'] },
        },
      },
    },
  },
}

const VERDICT_SCHEMA = {
  type: 'object',
  required: ['lens', 'confirmed', 'reason'],
  properties: {
    lens: { enum: ['code_reality', 'reproducer', 'spec_grounded'] },
    confirmed: { type: 'boolean' },
    reason: { type: 'string' },
    quoted_evidence: { type: ['string', 'null'] },
    severity_adjustment: { enum: ['unchanged', 'raise', 'lower', null] },
  },
}

const DISCOVER_SCHEMA = {
  type: 'object',
  required: ['modules', 'tests', 'docs', 'invariants_to_check'],
  properties: {
    modules: { type: 'object' },
    tests: { type: 'object' },
    docs: { type: 'object' },
    invariants_to_check: { type: 'array', items: { type: 'string' } },
  },
}

// ───── Dimension prompts ────────────────────────────────────────────────────

const DIMENSION_PROMPTS = {
  correctness: `You are auditing the httpware repository for CORRECTNESS bugs only.
Read every file under src/httpware/ and look for: logic errors, off-by-ones,
wrong branches, dead code, broken control flow, mis-named variables,
accidentally swapped arguments, mishandled None/empty cases.

Out of scope for this dimension: concurrency races (dimension 2 handles those),
error-contract violations (dimension 3), public-API typing (dimension 4),
optional-extras leaks (dimension 5), tests (dimension 6), docs (dimensions 7-8).

Use the discover JSON as your file inventory. For each finding return: title,
file, approximate line, a 1-3 sentence claim explaining what is wrong AND why
it is wrong (not just what the code does), a verbatim 5-15 line evidence quote,
suspected severity, and a reproducer hint if applicable.

Default to NOT reporting when uncertain. Quality > quantity. Aim for 6-12 high-
signal findings, not 30 weak ones.`,

  concurrency: `You are auditing the httpware repository for CONCURRENCY hazards
and SYNC/ASYNC PARITY divergence.

Focus on: src/httpware/middleware/resilience/{retry,bulkhead,budget}.py and
their tests under tests/test_*_props.py, test_retry_budget_threadsafety.py,
test_threading_with_shared_budget.py.

Look for: missing locks, races on shared mutable state, threading.Semaphore vs
asyncio.Semaphore semantics mismatches, RetryBudget sharing between sync Client
and AsyncClient (new in 0.8.0), property-test strategies that don't actually
exercise the race they claim to, behavior divergence between sync Retry and
AsyncRetry / Bulkhead and AsyncBulkhead that isn't documented as intentional.

Out of scope: pure-correctness logic errors (dimension 1), error contract (3).

Schema as above. 6-12 findings target. Default to silence when uncertain.`,

  error_contract: `You are auditing the httpware repository against the
ERROR CONTRACT documented in CLAUDE.md:

- Status-keyed errors take a SINGLE positional response: httpx2.Response.
- Subclasses do NOT override __init__.
- All fields available via exc.response.*.
- 4xx and 5xx map to the appropriate StatusError subclass at the terminal call.

Check src/httpware/errors.py and the terminal in src/httpware/client.py.
Cross-reference tests/test_errors.py and tests/test_error_mapping_terminal.py:
do the tests actually prove the invariants, or do they pass for the wrong
reason?

Report any deviation from the invariants, even if minor. Also report places
where the docstring or type signature is silent on a contractual point.

Out of scope: other code correctness, concurrency. 4-8 findings target.`,

  public_api: `You are auditing the httpware PUBLIC API SURFACE.

Read src/httpware/__init__.py and src/httpware/middleware/__init__.py and
src/httpware/decoders/__init__.py. Compare against:
- tests/test_public_api.py
- README.md examples
- docs/*.md import statements

Look for: symbols exported but not in __all__, symbols in __all__ but not
defined, stale Async* aliases left over from the 0.8.0 rename, missing
type re-exports (re-exporting a class without its TypeVar bound is a smell),
imports that succeed but produce a partially-initialized object.

Per memory: the project keeps __all__ only in __init__.py (not submodules).

Out of scope: optional extras (dimension 5), internal modules. 4-8 findings.`,

  optional_extras: `You are auditing the OPTIONAL EXTRAS BOUNDARY.

Invariant: pydantic, msgspec, and otel must be importable ONLY inside their
dedicated modules. Top-level import httpware must not pull them. The fail-fast
error when a decoder is requested without its extra installed must trigger at
AsyncClient.__init__ / Client.__init__, NOT at first response decode.

Check:
- src/httpware/decoders/pydantic.py, src/httpware/decoders/msgspec.py
- src/httpware/_internal/import_checker.py
- src/httpware/_internal/observability.py (OTel hook)
- tests/test_optional_extras_isolation.py
- tests/test_optional_extras_otel_missing.py
- tests/test_optional_extras_pydantic_missing.py

Look for: stray top-level imports, lazy imports that defeat fail-fast,
ImportError handling that swallows the wrong exception, tests that don't
prove the isolation they claim to.

Out of scope: in-decoder bugs (dimension 1). 3-6 findings.`,

  tests: `You are auditing the httpware TEST SUITE.

Look for:
- Coverage gaps: code paths in src/httpware/ with no test (use the discover map).
- Hypothesis property tests with strategies too narrow to exercise the
  invariant they claim to (e.g. integers(min_value=0, max_value=1) won't find
  most off-by-one).
- Mock transports that hide real httpx2 behavior (e.g. returning bytes that
  httpx2 would never produce).
- Tests that pass for the wrong reason (assert True equivalents, no
  assertions, mocks that absorb the failure).
- Sync/async parity gaps: a thoroughly tested async behavior with no
  corresponding sync test, or vice versa (especially after 0.8.0).

Out of scope: production code bugs (dimensions 1-5), docs (7-8). 8-14 findings.`,

  docs: `You are auditing docs/*.md and docs/recipes/ for ACCURACY against
the current code.

For every code block in:
- docs/index.md, docs/errors.md, docs/middleware.md, docs/resilience.md,
  docs/testing.md
- docs/recipes/*.md
- docs/dev/*.md
- README.md

Verify:
- Imports resolve against the current src/httpware/ public API.
- After the 0.8.0 Async* rename, classes/decorators referenced are the right
  ones (Middleware vs AsyncMiddleware, Retry vs AsyncRetry, etc.).
- Code blocks would actually run (no obvious syntax/typo, methods exist).
- Cross-references and internal links resolve.
- mkdocs.yml nav matches the files that exist.

Report each broken or stale block as a finding with the doc location and the
exact line that needs to change.

Out of scope: planning docs (dimension 8). 4-10 findings.`,

  planning_docs: `You are auditing PLANNING DOCS against current repo reality.

Read:
- planning/engineering.md
- CLAUDE.md
- README.md
- planning/releases/0.8.0.md (if it exists)
- planning/deferred-work.md

Compare each load-bearing claim against the actual src/httpware/ layout,
public API, and tests. Special attention: does the module layout diagram in
CLAUDE.md still match? Does engineering.md still describe protocol seams
accurately after the sync Client landed? Are deferred-work items still
deferred or have they been quietly resolved or removed?

Report each stale claim with the file, the inaccurate quote, and what the
current truth is.

Out of scope: docs/ user-facing docs (dimension 7). 3-8 findings.`,
}

// ───── Verifier prompts ─────────────────────────────────────────────────────

const VERIFIER_PROMPTS = {
  code_reality: (f) => `Re-read ${f.file} around line ${f.line_hint} (±30 lines).
The finder claims:

Title: ${f.title}
Claim: ${f.claim}
Evidence quoted by finder:
${f.evidence_quote}

Does the claim match what the code actually does, or did the finder misread?
Default to confirmed: false if the cited code does not support the claim, or
if you can't locate the cited code. Return your verdict per schema.`,

  reproducer: (f) => `The finder claims:

Title: ${f.title}
Claim: ${f.claim}
Reproducer hint: ${f.reproducer_hint ?? '(none provided)'}

Could you sketch a test (3-5 lines) that demonstrates this bug? If the finding
is in docs or planning docs, reframe: would a reader making a reasonable choice
based on the doc be misled?

If you cannot construct a reproducer (or a misleading-reading), set
confirmed: false. Otherwise confirmed: true with the sketch in quoted_evidence.`,

  spec_grounded: (f) => `The finder claims:

Title: ${f.title}
Claim: ${f.claim}

Does this violate a stated invariant in CLAUDE.md or planning/engineering.md
(error contract, optional-extras pattern, no httpx2._ private API, no global
logging config, naming conventions, etc.)?

- If yes: confirmed: true, cite the invariant verbatim in quoted_evidence.
- If it's a judgment call with no spec backing: confirmed: false.

Severity adjustment: raise if this is a CLAUDE.md-listed invariant; lower if
the spec is silent and this is a hardening suggestion.`,
}

// ───── Synthesis prompt ─────────────────────────────────────────────────────

const SYNTHESIS_PROMPT = (chunkId, dims, confirmed, auditFile) => `
You are synthesizing chunk ${chunkId} of the httpware deep audit.

You have ${confirmed.length} confirmed findings across dimensions: ${dims.join(', ')}.

Tasks:
1. Read the existing ${auditFile} to see what chunks already landed.
2. Dedupe these confirmed findings against findings already in the file
   (match on file path + line ±5 + similar claim). If a duplicate, fold the
   new evidence into the existing entry rather than appending.
3. Triage each new finding into buckets: blocker / high / medium / low / nit.
   Apply the severity definitions from the spec strictly. Collapse nits into
   a single rolled-up entry per dimension if more than 4 nits surface.
4. Append a "## Chunk ${chunkId} — <title>" section to the audit file with:
   - One-paragraph chunk summary (N reviewed, M survived, dominant category).
   - Findings grouped by bucket, each with: title, file:line in code-format,
     claim (3 sentences max), evidence quote in a fenced code block, verifier
     consensus (2/3 or 3/3 + which lenses confirmed), suggested direction.
5. Do NOT rewrite the top-of-file Summary yet — that's the final merge step.

Use Edit/Write tools to update the file. Commit with:
  audit(chunk-${chunkId}): <one-line summary>

Confirmed findings JSON:
${JSON.stringify(confirmed, null, 2)}
`

// ───── Script body ──────────────────────────────────────────────────────────

const SONNET = 'claude-sonnet-4-6'
const OPUS = 'claude-opus-4-7'

if (args.run_discover) {
  phase('Discover')
  log('Building module map (one-shot)')
  // The discover agent both produces structured data AND writes it to disk;
  // schema validates the structure, the prompt requires it to call Write afterward.
  await agent(
    `Build a JSON module map of the httpware repo. List every file under src/httpware/,
tests/, docs/, and planning/. For each entry capture: line count, a one-sentence
purpose. Also extract the load-bearing invariants from CLAUDE.md verbatim.

After building the structure, write it as pretty-printed JSON to:
  ${args.discover_file}

Use the Write tool to create the file. Do NOT commit it; the outer plan handles that.
Return the structure per schema.`,
    { model: OPUS, schema: DISCOVER_SCHEMA, label: 'discover' },
  )
}

phase('Find')
const findings = await parallel(
  args.dimensions.map(dim => () =>
    agent(
      `${DIMENSION_PROMPTS[dim]}\n\nDiscover map: ${args.discover_file}\nReturn per schema.`,
      { model: SONNET, schema: FINDING_SCHEMA, label: `find:${dim}`, phase: 'Find' },
    )
  ),
)

const allFindings = findings.filter(Boolean).flatMap(r => r.findings)
log(`Found ${allFindings.length} candidate findings across ${args.dimensions.length} dimensions`)

phase('Verify')
const verified = await parallel(
  allFindings.map(f => () =>
    parallel(['code_reality', 'reproducer', 'spec_grounded'].map(lens => () =>
      agent(VERIFIER_PROMPTS[lens](f), {
        model: SONNET, schema: VERDICT_SCHEMA,
        label: `verify:${f.dimension}:${lens}`, phase: 'Verify',
      })
    )).then(verdicts => {
      const confirms = verdicts.filter(Boolean).filter(v => v.confirmed).length
      const surviving = confirms >= 2
      const lensesConfirming = verdicts.filter(Boolean).filter(v => v.confirmed).map(v => v.lens)
      const adjustments = verdicts.filter(Boolean).map(v => v.severity_adjustment).filter(Boolean)
      const raiseCount = adjustments.filter(a => a === 'raise').length
      const lowerCount = adjustments.filter(a => a === 'lower').length
      let severity = f.suspected_severity
      if (lowerCount >= 1) severity = lowerOne(severity)
      if (raiseCount >= 2) severity = raiseOne(severity)
      return surviving ? { ...f, final_severity: severity, lensesConfirming } : null
    })
  ),
)

const confirmed = verified.filter(Boolean)
log(`${confirmed.length}/${allFindings.length} findings confirmed by ≥2 verifiers`)

phase('Synthesize')
await agent(
  SYNTHESIS_PROMPT(args.chunk_id, args.dimensions, confirmed, args.audit_file),
  { model: OPUS, label: `synthesize:chunk-${args.chunk_id}` },
)

return {
  chunk_id: args.chunk_id,
  candidates: allFindings.length,
  confirmed: confirmed.length,
  by_severity: countBySeverity(confirmed),
}

// ───── Helpers ──────────────────────────────────────────────────────────────

function lowerOne(s) {
  const order = ['nit', 'low', 'medium', 'high', 'blocker']
  const i = order.indexOf(s)
  return i > 0 ? order[i - 1] : s
}
function raiseOne(s) {
  const order = ['nit', 'low', 'medium', 'high', 'blocker']
  const i = order.indexOf(s)
  return i < order.length - 1 ? order[i + 1] : s
}
function countBySeverity(arr) {
  const out = { blocker: 0, high: 0, medium: 0, low: 0, nit: 0 }
  for (const f of arr) out[f.final_severity ?? f.suspected_severity]++
  return out
}
```

- [ ] **Step 2: Manual review of the script**

Read the file you just wrote end-to-end. Confirm:

- `meta` is a pure literal — no variables, function calls, or interpolation.
- `Date.now()`, `Math.random()`, and `new Date()` are not used.
- Every `agent()` call has a model (Sonnet for find/verify, Opus for discover/synthesize).
- Every `agent()` call that returns structured data uses the `schema:` option.
- The pipeline is genuinely pipelined: verify nested inside the parallel map over findings, no barrier between Find and Verify groups beyond what's required for the per-finding tuple.

Fix anything that doesn't match.

- [ ] **Step 3: Commit the script**

```bash
git add planning/audit/workflow.mjs
git commit -m "audit: parametrized workflow script for chunked deep audit"
```

Expected: clean commit.

---

## Task 3: User reviews finder prompts before chunk 1 launches

This is a hard gate.

- [ ] **Step 1: Present the 8 finder prompts to the user**

Show the user the `DIMENSION_PROMPTS` block from `planning/audit/workflow.mjs` and ask:

> "These are the lens prompts each finder will run against. Want any rewritten, sharpened, or scoped differently before chunk 1 launches?"

- [ ] **Step 2: Apply any user-requested prompt edits**

If the user requests changes, edit `planning/audit/workflow.mjs` and amend the commit (or add a follow-up commit):

```bash
git add planning/audit/workflow.mjs
git commit --amend --no-edit   # if the prompts commit is still the tip
# or
git commit -m "audit: tighten finder prompts per review"
```

- [ ] **Step 3: Get explicit user approval to launch chunk 1**

Wait for explicit "go" before invoking Workflow.

---

## Task 4: Run chunk 1 — Discover + dimensions 1, 2, 3

Token budget: ~1.5M Sonnet + ~80k Opus.

- [ ] **Step 1: Dry-run on a single dimension first**

Before the full chunk, run a smoke test to catch any script bugs cheaply:

```js
Workflow({
  scriptPath: 'planning/audit/workflow.mjs',
  args: {
    chunk_id: 0,                       // dry-run marker
    dimensions: ['correctness'],
    run_discover: true,
    audit_file: 'planning/audit/_dryrun.md',
    discover_file: 'planning/audit/_discover.json',
  },
})
```

Expected: workflow returns `{chunk_id: 0, candidates: N, confirmed: M, by_severity: {...}}` with `N > 0`, `M ≤ N`. The dry-run file `_dryrun.md` should have a chunk-0 section. The real `_discover.json` should be created and committed.

If the workflow errors, fix the script and re-run before continuing.

- [ ] **Step 2: Clean up the dry-run artifact**

```bash
rm planning/audit/_dryrun.md
git add planning/audit/_discover.json
git commit -m "audit: module map for deep audit chunks"
```

Expected: only `_discover.json` staged.

- [ ] **Step 3: Run chunk 1 for real**

```js
Workflow({
  scriptPath: 'planning/audit/workflow.mjs',
  args: {
    chunk_id: 1,
    dimensions: ['correctness', 'concurrency', 'error_contract'],
    run_discover: false,               // already done
    audit_file: 'planning/audit/2026-06-07-deep-audit.md',
    discover_file: 'planning/audit/_discover.json',
  },
})
```

Long-running step (15-25 min wall-clock). The synthesis stage commits its own update to the audit file. Workflow returns `{chunk_id: 1, candidates, confirmed, by_severity}`.

- [ ] **Step 4: Report chunk 1 summary to the user**

Read the appended section in `planning/audit/2026-06-07-deep-audit.md` and report to the user in one paragraph: total candidates, total confirmed, breakdown by severity, 2-3 headline issues.

Then ask explicitly:

> "Chunk 1 complete: <summary>. Continue to chunk 2 (API & boundaries), adjust scope, or stop?"

Wait for the user's call. If "stop," skip to Task 9. If "adjust," update later chunks' args before launching them.

---

## Task 5: Run chunk 2 — dimensions 4, 5

Token budget: ~500k Sonnet + ~30k Opus.

- [ ] **Step 1: Run chunk 2**

```js
Workflow({
  scriptPath: 'planning/audit/workflow.mjs',
  args: {
    chunk_id: 2,
    dimensions: ['public_api', 'optional_extras'],
    run_discover: false,
    audit_file: 'planning/audit/2026-06-07-deep-audit.md',
    discover_file: 'planning/audit/_discover.json',
  },
})
```

Synthesis commits its own update.

- [ ] **Step 2: Report and gate**

Report one-paragraph summary; ask continue/adjust/stop. Wait for response.

---

## Task 6: Run chunk 3 — dimension 6 (tests)

Token budget: ~900k Sonnet + ~40k Opus.

- [ ] **Step 1: Run chunk 3**

```js
Workflow({
  scriptPath: 'planning/audit/workflow.mjs',
  args: {
    chunk_id: 3,
    dimensions: ['tests'],
    run_discover: false,
    audit_file: 'planning/audit/2026-06-07-deep-audit.md',
    discover_file: 'planning/audit/_discover.json',
  },
})
```

- [ ] **Step 2: Report and gate**

One-paragraph summary; continue/adjust/stop.

---

## Task 7: Run chunk 4 — dimensions 7, 8 (docs)

Token budget: ~600k Sonnet + ~30k Opus.

- [ ] **Step 1: Run chunk 4**

```js
Workflow({
  scriptPath: 'planning/audit/workflow.mjs',
  args: {
    chunk_id: 4,
    dimensions: ['docs', 'planning_docs'],
    run_discover: false,
    audit_file: 'planning/audit/2026-06-07-deep-audit.md',
    discover_file: 'planning/audit/_discover.json',
  },
})
```

- [ ] **Step 2: Report and gate**

Summary; continue to final merge or stop.

---

## Task 8: Run final merge

Token budget: ~80k Opus.

- [ ] **Step 1: Launch final merge as a one-shot Opus agent (not a Workflow)**

Use `Agent` (not Workflow) for this stage:

```js
Agent({
  description: 'Final dedup + summary header for audit',
  model: 'opus',
  prompt: `Read planning/audit/2026-06-07-deep-audit.md end to end.

Tasks:
1. Cross-chunk dedup: any two findings with the same (file path, line ±5) and
   similar claim get merged into one entry. Keep the higher-severity bucket;
   fold the dropped entry's evidence/lens-consensus into the kept one.
2. Rewrite the top-of-file Summary section with final counts per bucket.
3. Add a "## Cross-cutting themes" section ABOVE Chunk 1 if patterns emerge
   across chunks (e.g. multiple dimensions surfaced the same kind of missing
   safety check). Only include this section if there are real cross-chunk
   patterns; do not invent themes.
4. Flip the file's "Status:" line from "in progress" to "complete".
5. Commit with: audit(merge): final dedup and summary header

Use Edit/Write tools to modify the file. Use git to commit.`,
})
```

- [ ] **Step 2: Verify the merge landed**

```bash
git log --oneline -3
```

Expected: most-recent commit is `audit(merge): ...`. The audit file's Status line should read `complete`.

---

## Task 9: User final review and audit close

- [ ] **Step 1: Present the final report**

Tell the user:

> "Audit complete. Final report at `planning/audit/2026-06-07-deep-audit.md`. Summary counts: <quote from the rewritten header>. Want me to walk through any specific bucket, file specific findings as GitHub issues, or close the audit as-is?"

- [ ] **Step 2: Handle the user's choice**

- **"Close as-is"** — done. The audit is the deliverable.
- **"Walk through X"** — read the relevant section and discuss inline.
- **"File as issues"** — out of scope for this plan; offer to do it as a separate piece of work.
- **"Re-run dimension Y"** — invoke `Workflow` against the script with only that dimension, append to the file under a "## Re-run — <dim>" section, and re-run the final merge.

---

## Self-review notes

Done after writing the plan:

- **Spec coverage:** Every section in the spec maps to a task. Discover → Task 4 step 3 / dry-run step 1. 8 dimensions → Task 2's `DIMENSION_PROMPTS`. Schemas → Task 2. Verifier panel → Task 2 `VERIFIER_PROMPTS`. 2-of-3 consensus → Task 2 script body. Synthesis → Task 2 `SYNTHESIS_PROMPT`. Severity buckets → enforced in synthesis prompt. Gate behavior → Tasks 4-7 each have a "Report and gate" step. Final merge → Task 8. Open questions resolved at top of plan.
- **No placeholders:** All prompts written out verbatim. No "TBD" or "fill in." Schemas are concrete JSON Schema objects.
- **Type/name consistency:** `audit_file`, `discover_file`, `chunk_id`, `dimensions`, `run_discover` are used consistently across all tasks. Severity strings (`blocker|high|medium|low|nit`) match between spec and plan.

---
status: shipped
date: 2026-06-12
slug: delta-audit
spec: delta-audit
pr: 43
---

# 0.9.0 Delta Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **Task 2 must run inline in the main session** — the Workflow tool is a main-session orchestration tool and is not available to dispatched subagents.

**Goal:** Run a verified, severity-bucketed audit of everything changed since tag `0.8.6` (the 0.9.0 multi-decoder epic) plus a full-site docs consistency sweep, producing `planning/audit/2026-06-12-delta-audit.md`.

**Architecture:** Single-chunk adaptation of the proven deep-audit pipeline (`planning/audit/workflow.mjs`): 4 parallel finder agents with delta-scoped prompts → 3-voter verification panel per finding (≥2 consensus survives) → one synthesis agent that writes and commits the audit doc. No discover phase; file lists are inlined in prompts.

**Tech Stack:** Claude Code Workflow tool (`scriptPath` invocation), models `claude-sonnet-4-6` (finders 1/2/4, verifiers) and `claude-opus-4-8` (`new_tests` finder, synthesis).

**Spec:** [planning/specs/2026-06-12-delta-audit-design.md](../specs/2026-06-12-delta-audit-design.md)

---

### Task 1: Author the delta workflow script

**Files:**
- Create: `planning/audit/workflow-delta.mjs`

- [ ] **Step 1: Write the script**

Create `planning/audit/workflow-delta.mjs` with exactly this content:

```js
export const meta = {
  name: 'httpware-delta-audit',
  description: 'Delta audit of the 0.9.0 multi-decoder epic (find + verify + synthesize, single chunk)',
  phases: [
    { title: 'Find', detail: 'One finder per dimension (4)' },
    { title: 'Verify', detail: '3-voter panel per finding' },
    { title: 'Synthesize', detail: 'Triage and write the audit doc' },
  ],
}

// ───── Constants ────────────────────────────────────────────────────────────

const AUDIT_FILE = 'planning/audit/2026-06-12-delta-audit.md'
const PRIOR_AUDIT = 'planning/audit/2026-06-07-deep-audit.md'
const BASELINE = '0.8.6'

const DELTA_PREAMBLE = `Baseline context: everything up to tag ${BASELINE} was deep-audited on
2026-06-07 and all 35 findings were closed by release 0.8.6 (see ${PRIOR_AUDIT}).
You are auditing ONLY the delta since then: the 0.9.0 multi-decoder routing epic
(PRs #41, #42). Do NOT re-report items already recorded (closed or deferred) in
${PRIOR_AUDIT} or planning/deferred-work.md unless you have genuinely new evidence.

For change context on any in-scope file, run: git diff ${BASELINE}..HEAD -- <file>
Read the current file contents too — the diff alone lacks surrounding context.`

// ───── Schemas (unchanged from workflow.mjs) ────────────────────────────────

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

// ───── Dimension prompts ────────────────────────────────────────────────────

const DIMENSION_PROMPTS = {
  decoder_routing: `You are auditing the httpware 0.9.0 delta for DECODER ROUTING
correctness only.

${DELTA_PREAMBLE}

Files in scope:
- src/httpware/client.py (decoders=[...] parameter, type-dispatched routing,
  _build_default_decoders, MissingDecoderError pre-flight)
- src/httpware/decoders/__init__.py
- src/httpware/decoders/pydantic.py (can_decode, per-instance adapter cache)
- src/httpware/decoders/msgspec.py (can_decode, per-instance decoder cache)
- src/httpware/errors.py (MissingDecoderError)
- src/httpware/__init__.py (new exports)

Look for:
- can_decode first-match dispatch: is the order deterministic, and can an
  earlier decoder incorrectly shadow a later one for a model type both accept?
- MissingDecoderError pre-flight timing: it must raise BEFORE the request is
  sent when response_model matches no decoder. Verify where the check sits
  relative to the middleware chain / terminal send.
- _build_default_decoders resolution matrix: correct result for each
  installed-extras combination (neither, pydantic only, msgspec only, both),
  and a sensible deterministic order when both are installed.
- Per-instance caches (PR #42): no residual shared module state, no
  cross-instance leakage, unbounded-growth behavior on many model types.
- The msgspec CustomType trap: msgspec.json.Decoder(SomePydanticModel)
  SUCCEEDS via CustomType fallback rather than raising. can_decode must use
  msgspec.inspect.type_info with a CustomType filter, not try/except around
  Decoder construction. Verify the implementation avoids the trap for
  pydantic BaseModel subclasses AND other CustomType-falling types.

Out of scope: sync/async parity and Seam B contract (another finder covers
those), test quality, docs accuracy.

For each finding return: title, file, approximate line, a 1-3 sentence claim
explaining what is wrong AND why it is wrong, a verbatim 5-15 line evidence
quote, suspected severity, and a reproducer hint if applicable.

Default to NOT reporting when uncertain. Quality > quantity. 4-10 findings
target — fewer is fine if the code is clean.`,

  seam_parity: `You are auditing the httpware 0.9.0 delta for SEAM B CONTRACT
conformance and SYNC/ASYNC PARITY only.

${DELTA_PREAMBLE}

Files in scope:
- src/httpware/client.py — compare Client.send vs AsyncClient.send, and
  Client.send_with_response vs AsyncClient.send_with_response
- src/httpware/errors.py (MissingDecoderError, DecodeError)
- planning/engineering.md §Seam B and CLAUDE.md (the documented contracts)

Look for:
- Both send implementations must invoke decoder routing IDENTICALLY (same
  dispatch, same pre-flight, same error wrapping). Diff them side by side.
- send_with_response (both sides) must route through the same dispatch as
  send — no copy-paste divergence.
- DecodeError must still wrap decoder failures at Seam B (the 0.8.1
  contract): a decoder raising inside decode() must surface as DecodeError,
  catchable via except ClientError.
- MissingDecoderError vs the CLAUDE.md exception conventions: status-keyed
  errors take a single positional response and subclasses do not override
  __init__. MissingDecoderError is NOT status-keyed, so deviation may be
  deliberate — check what errors.py docstrings and engineering.md actually
  claim, and report only contradictions between code and documented contract.

Out of scope: dispatch-logic bugs within a single implementation (the
decoder_routing finder covers those), test quality, docs accuracy.

For each finding return: title, file, approximate line, a 1-3 sentence claim,
a verbatim 5-15 line evidence quote, suspected severity, reproducer hint.

Default to NOT reporting when uncertain. 3-8 findings target.`,

  new_tests: `You are auditing the QUALITY of the test code added or changed in
the httpware 0.9.0 delta. Production-code bugs are out of scope — only the
tests themselves.

${DELTA_PREAMBLE}

Files in scope (only these; pre-existing untouched test files are out of scope):
- tests/test_client_construction.py
- tests/test_client_decoders_default.py
- tests/test_client_dispatch.py
- tests/test_client_send_with_response.py
- tests/test_client_send_with_response_sync.py
- tests/test_client_sync.py
- tests/test_decoders_msgspec.py
- tests/test_decoders_pydantic.py
- tests/test_errors.py
- tests/test_optional_extras_pydantic_missing.py
- tests/test_public_api.py

Look for, in priority order:
- Tests that pass for the wrong reason: tautological asserts (a known
  reviewer blind spot in this repo), assertions on mock behavior rather than
  subject behavior, exception asserts that would also pass on the wrong
  exception type.
- Dispatch-matrix coverage gaps: decoder order significance, overlapping
  can_decode acceptance, a model type matching NO decoder, empty decoders
  list, explicit decoders vs default resolution.
- Sync/async parity gaps: a behavior tested on AsyncClient with no Client
  twin, or vice versa.
- MockTransport bytes that real httpx2 servers would never produce, hiding
  real decode behavior.

Conventions to respect (not findings): pytest-asyncio auto mode means async
tests need no marker; tests inject httpx2.MockTransport via
Client(httpx2_client=httpx2.Client(transport=mock)) — that pattern itself is
correct and documented.

For each finding return: title, file, approximate line, a 1-3 sentence claim,
a verbatim 5-15 line evidence quote, suspected severity, reproducer hint.

Default to NOT reporting when uncertain. Do not report style opinions.
4-10 findings target — fewer is fine.`,

  docs_consistency: `You are auditing the ENTIRE httpware documentation surface
for consistency with post-0.9.0 reality. The 0.9.0 release changed the decoder
story (decoder= became decoders=[...], type-dispatched via can_decode) and
REVERSED the 0.3.0 fail-fast behavior (missing-extra errors moved from
Client.__init__ to a MissingDecoderError pre-flight at send time). Unchanged
pages may therefore be stale — read them all.

${DELTA_PREAMBLE}

Files in scope (full sweep):
- docs/index.md, docs/errors.md, docs/middleware.md, docs/resilience.md,
  docs/testing.md
- docs/recipes/*.md, docs/dev/*.md
- README.md
- CLAUDE.md (module layout, Seam B description, exception contract)
- planning/engineering.md
- planning/deferred-work.md (items quietly resolved by 0.9.0 — e.g. the
  module-global lru_cache item looks closed by PR #42 but may still be
  listed as Open)
- planning/releases/0.9.0.md (claims vs actual code)
- mkdocs.yml nav vs files that exist on disk

Verify:
- Every code block imports resolve against the current public API and would
  actually run. Watch for residual singular decoder= usage anywhere.
- Every load-bearing prose claim about decoder behavior matches the code:
  fail-fast timing, default-decoder resolution, multi-decoder coexistence.
- Internal links resolve; mkdocs nav matches files on disk.

When you report a finding, state in the claim whether the fix belongs in the
DOC or in the CODE (i.e. the doc describes intended behavior the code fails
to deliver).

Out of scope per the project docs philosophy: absence of migration guides,
API autodoc, or benchmarks is NOT a finding; prose style and doc structure
opinions are NOT findings.

For each finding return: title, file, approximate line, a 1-3 sentence claim,
a verbatim 5-15 line evidence quote, suspected severity, reproducer hint
(for docs: the misleading-reading scenario).

Default to NOT reporting when uncertain. 5-12 findings target.`,
}

// ───── Verifier prompts ─────────────────────────────────────────────────────

const VERIFIER_PROMPTS = {
  code_reality: (f) => `Re-read ${f.file} around line ${f.line_hint} (±30 lines).
The finder claims:

Title: ${f.title}
Claim: ${f.claim}
Evidence quoted by finder:
${f.evidence_quote}

Does the claim match what the code/doc actually says, or did the finder
misread? Default to confirmed: false if the cited content does not support
the claim, or if you can't locate it.

If this is a docs finding, also state in your reason whether the fix belongs
in the DOC or in the CODE.

Return your verdict per schema.`,

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

Two checks:

1. Does this violate a stated invariant in CLAUDE.md or planning/engineering.md
   (error contract, Seam B decode contract, optional-extras pattern, no
   httpx2._ private API, no global logging config, naming conventions, etc.)?
   - If yes: confirmed: true, cite the invariant verbatim in quoted_evidence.
   - If it's a judgment call with no spec backing: confirmed: false.

2. Is this a re-report of an item already recorded in
   planning/audit/2026-06-07-deep-audit.md (closed by 0.8.6) or
   planning/deferred-work.md, with no new evidence? If so: confirmed: false
   and say which existing item it duplicates.

Severity adjustment: raise if this violates a CLAUDE.md-listed invariant;
lower if the spec is silent and this is a hardening suggestion.`,
}

// ───── Synthesis prompt ─────────────────────────────────────────────────────

const SYNTHESIS_PROMPT = (dims, confirmed) => `
You are synthesizing the httpware 0.9.0 delta audit (baseline ${BASELINE} -> HEAD).

You have ${confirmed.length} confirmed findings across dimensions: ${dims.join(', ')}.

HARD CONSTRAINT: you may create or edit ONLY ${AUDIT_FILE}. Do not create,
edit, or delete any other file. Do not fix any finding.

Tasks:
1. Read ${PRIOR_AUDIT} and planning/deferred-work.md. Drop any confirmed
   finding that merely restates an item recorded there (closed or deferred)
   without new evidence; note dropped duplicates in a short "Dropped as
   duplicates" list at the end of the file.
2. Recategorize: a docs_consistency finding whose verifier reasons say the
   fix belongs in CODE moves to the appropriate code dimension
   (decoder_routing or seam_parity) with a note.
3. Triage each finding into buckets using these definitions, strictly:
   - Blocker: wrong-correctness bug affecting users in normal usage; a
     documented invariant violated; a doc example that does not run.
   - High: bug behind a non-default path; missing safety check at a
     documented boundary; docs that mislead a reasonable reader.
   - Medium: works today but relies on undocumented invariants;
     accurate-but-ambiguous docs; test gaps in load-bearing primitives.
   - Low: minor inaccuracies, weak idioms, hardening suggestions.
   - Nit: style, naming, punctuation. If more than 4 nits surface in one
     dimension, collapse them into a single rolled-up entry.
4. Create ${AUDIT_FILE} with:
   - Header: title "httpware delta audit — 2026-06-12 (0.9.0 multi-decoder
     epic)", status complete, baseline ${BASELINE} -> current HEAD short SHA
     (run: git rev-parse --short HEAD), links to
     planning/specs/2026-06-12-delta-audit-design.md and
     planning/plans/2026-06-12-delta-audit-plan.md.
   - "## Summary": bucket counts (Blockers/High/Medium/Low/Nits) and a
     one-paragraph headline naming the most severe finding.
   - "## Findings" grouped by bucket (highest first). Each finding: title,
     file:line in code format, claim (3 sentences max), evidence quote in a
     fenced code block, verifier consensus (2/3 or 3/3 + which lenses
     confirmed), suggested direction (one sentence).
   - For any dimension with zero surviving findings, an explicit
     "no findings survived verification" line.
5. Commit exactly one file:
   git add ${AUDIT_FILE}
   git commit -m "audit(delta): 0.9.0 multi-decoder delta audit findings"
   Then run git status and confirm the tree is clean apart from untracked
   files that existed before your run.

Confirmed findings JSON:
${JSON.stringify(confirmed, null, 2)}
`

// ───── Script body ──────────────────────────────────────────────────────────

const SONNET = 'claude-sonnet-4-6'
const OPUS = 'claude-opus-4-8'

const FINDER_MODELS = {
  decoder_routing: SONNET,
  seam_parity: SONNET,
  new_tests: OPUS, // Sonnet stalled twice on meta-review dimensions in the deep audit
  docs_consistency: SONNET,
}

// args may arrive as a JSON string (depending on harness) — normalize.
const cfg = typeof args === 'string' ? JSON.parse(args) : (args ?? {})
const dims = cfg.dimensions ?? Object.keys(DIMENSION_PROMPTS)
const unknownDims = dims.filter(d => !DIMENSION_PROMPTS[d])
if (unknownDims.length) throw new Error(`Unknown dimensions: ${unknownDims.join(', ')}`)

phase('Find')
const findings = await parallel(
  dims.map(dim => () =>
    agent(`${DIMENSION_PROMPTS[dim]}\n\nReturn per schema.`, {
      model: FINDER_MODELS[dim], schema: FINDING_SCHEMA,
      label: `find:${dim}`, phase: 'Find',
    })
  ),
)

const FINDINGS_PER_DIM_CAP = 15
const rawDimensionResults = findings.filter(Boolean)
for (const r of rawDimensionResults) {
  if (r.findings.length > FINDINGS_PER_DIM_CAP) {
    const dimName = r.findings[0]?.dimension ?? '<unknown>'
    log(`WARNING: dimension ${dimName} returned ${r.findings.length} findings; capping at ${FINDINGS_PER_DIM_CAP}`)
  }
}
const allFindings = rawDimensionResults.flatMap(r => r.findings.slice(0, FINDINGS_PER_DIM_CAP))
log(`Found ${allFindings.length} candidate findings across ${dims.length} dimensions`)

phase('Verify')
const verified = await parallel(
  allFindings.map(f => () =>
    parallel(['code_reality', 'reproducer', 'spec_grounded'].map(lens => () =>
      agent(VERIFIER_PROMPTS[lens](f), {
        model: SONNET, schema: VERDICT_SCHEMA,
        label: `verify:${f.dimension}:${lens}`, phase: 'Verify',
      })
    )).then(verdicts => {
      const live = verdicts.filter(Boolean)
      const confirms = live.filter(v => v.confirmed).length
      const lensesConfirming = live.filter(v => v.confirmed).map(v => v.lens)
      const adjustments = live.map(v => v.severity_adjustment).filter(Boolean)
      let severity = f.suspected_severity
      if (adjustments.filter(a => a === 'lower').length >= 1) severity = lowerOne(severity)
      if (adjustments.filter(a => a === 'raise').length >= 2) severity = raiseOne(severity)
      if (live.length === 0) {
        log(`WARNING: all 3 verifiers failed for finding "${f.title}" (${f.file}:${f.line_hint}) — dropped`)
      }
      return confirms >= 2 ? { ...f, final_severity: severity, lensesConfirming } : null
    })
  ),
)

const confirmed = verified.filter(Boolean)
log(`${confirmed.length}/${allFindings.length} findings confirmed by ≥2 verifiers`)

phase('Synthesize')
await agent(SYNTHESIS_PROMPT(dims, confirmed), { model: OPUS, label: 'synthesize' })

return {
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

- [ ] **Step 2: Syntax-check the script**

`node --check` cannot be used: the script has a top-level `return`, which the Workflow harness allows (it wraps the body in an async function) but which is a SyntaxError in real ESM module scope. Mirror the harness wrapping instead:

```bash
node -e "
const s = require('fs').readFileSync('planning/audit/workflow-delta.mjs', 'utf8')
  .replace('export const meta', 'const meta');
new Function('args','agent','parallel','pipeline','phase','log','budget','workflow',
  'return (async () => {' + s + '})()');
console.log('syntax OK');
"
```

Expected output: `syntax OK` (exit 0). A SyntaxError here means the script is malformed — fix before committing.

- [ ] **Step 3: Commit**

```bash
git add planning/audit/workflow-delta.mjs
git commit -m "audit(delta): add 0.9.0 delta audit workflow script"
```

---

### Task 2: Run the delta audit workflow

**Files:**
- Created by the run: `planning/audit/2026-06-12-delta-audit.md` (written and committed by the synthesis agent, not by you)

**This task runs inline in the main session — do not dispatch it to a subagent.**

- [ ] **Step 1: Pre-flight checks**

Run: `git status --porcelain` — expected: empty (clean tree).
Run: `git tag --list 0.8.6` — expected: `0.8.6` (the baseline tag the finder prompts diff against exists).

- [ ] **Step 2: Invoke the workflow**

Call the Workflow tool with:

```
scriptPath: /Users/kevinsmith/src/pypi/httpware/planning/audit/workflow-delta.mjs
```

No `args` (defaults to all four dimensions). The tool returns immediately with a task ID; the run completes in the background and sends a task notification.

- [ ] **Step 3: Await completion and read the result**

Expected return shape: `{ candidates: N, confirmed: M, by_severity: { blocker, high, medium, low, nit } }`.

Failure handling:
- A finder returning `null` (skipped/terminal error) is logged by the script and the run continues with the remaining dimensions — note the gap for the final report.
- If the run dies mid-flight, resume with `Workflow({scriptPath, resumeFromRunId})` — completed finder/verifier calls return cached.
- Zero confirmed findings is a valid outcome; synthesis still writes the doc with per-dimension "no findings survived" notes.

---

### Task 3: Verify acceptance criteria and report

- [ ] **Step 1: Verify the synthesis commit touched only the audit doc**

Run: `git show --stat HEAD --format='%s'`
Expected: subject `audit(delta): 0.9.0 multi-decoder delta audit findings`, exactly one file changed: `planning/audit/2026-06-12-delta-audit.md`.

Run: `git status --porcelain`
Expected: empty. If the synthesis agent modified or created anything else, revert those changes (`git checkout -- <file>` / delete strays) and note the constraint violation in the report.

- [ ] **Step 2: Spot-check the audit doc format**

Read `planning/audit/2026-06-12-delta-audit.md` and confirm against the spec's acceptance criteria:
- Summary header with bucket counts and headline.
- Every finding has: title, `file:line`, claim ≤3 sentences, fenced evidence quote, verifier consensus with lenses, suggested direction.
- Each of the 4 dimensions either has findings or an explicit "no findings survived verification" line.

If format gaps exist, fix the doc directly (formatting only — never alter finding substance) and amend the synthesis commit.

- [ ] **Step 3: Report to the user**

Post a summary: bucket counts, the headline finding, any dimension gaps or constraint violations, and a pointer to the audit doc. Findings are the deliverable — do not start fixing them.

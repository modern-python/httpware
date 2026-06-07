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

6-12 findings target. Default to silence when uncertain.`,

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

Use Edit/Write tools to update the file. After updating, stage and commit with:
  git add ${auditFile}
  git commit -m "audit(chunk-${chunkId}): <one-line summary describing the ${confirmed.length} confirmed findings and dominant dimension>"

Run \`git status\` after the commit to confirm a clean tree.

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
const unknownDims = args.dimensions.filter(d => !DIMENSION_PROMPTS[d])
if (unknownDims.length) throw new Error(`Unknown dimensions: ${unknownDims.join(', ')}`)
const findings = await parallel(
  args.dimensions.map(dim => () =>
    agent(
      `${DIMENSION_PROMPTS[dim]}

Before you start, use the Read tool to load the discover map at ${args.discover_file}.
It contains the full file inventory (with line counts and purpose strings) and the
load-bearing invariants from CLAUDE.md. Use it to drive your search instead of
guessing at the codebase layout.

Return per schema.`,
      { model: SONNET, schema: FINDING_SCHEMA, label: `find:${dim}`, phase: 'Find' },
    )
  ),
)

const FINDINGS_PER_DIM_CAP = 15
const rawDimensionResults = findings.filter(Boolean)
const oversizedDims = rawDimensionResults.filter(r => r.findings.length > FINDINGS_PER_DIM_CAP)
for (const r of oversizedDims) {
  const dimName = r.findings[0]?.dimension ?? '<unknown>'
  log(`WARNING: dimension ${dimName} returned ${r.findings.length} findings; capping at ${FINDINGS_PER_DIM_CAP}`)
}
const allFindings = rawDimensionResults.flatMap(r => r.findings.slice(0, FINDINGS_PER_DIM_CAP))
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
      if (verdicts.every(v => v === null)) {
        log(`WARNING: all 3 verifiers failed for finding "${f.title}" (${f.file}:${f.line_hint}) — dropped`)
      }
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

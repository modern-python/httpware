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

Out of scope for this dimension: concurrency races (the concurrency finder
handles those), error-contract violations (the error_contract finder),
public-API typing (the public_api finder), optional-extras leaks (the
optional_extras finder), tests (the tests finder), docs (the architecture_docs
finder).

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

Out of scope: pure-correctness logic errors (the correctness finder), error
contract (the error_contract finder).

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
- architecture/*.md import statements

Look for: symbols exported but not in __all__, symbols in __all__ but not
defined, stale Async* aliases left over from the 0.8.0 rename, missing
type re-exports (re-exporting a class without its TypeVar bound is a smell),
imports that succeed but produce a partially-initialized object.

Per memory: the project keeps __all__ only in __init__.py (not submodules).

Out of scope: optional extras (the optional_extras finder), internal modules.
4-8 findings.`,

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

Out of scope: in-decoder bugs (the correctness finder). 3-6 findings.`,

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

Out of scope: production code bugs (the correctness/concurrency/error_contract/
public_api/optional_extras finders), docs (the architecture_docs finder).
8-14 findings.`,

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

// ───── Script body ──────────────────────────────────────────────────────────

const SONNET = 'claude-sonnet-4-6'
const OPUS = 'claude-opus-4-8'

// args may arrive as a JSON string (depending on harness) — normalize.
const cfg = typeof args === 'string' ? JSON.parse(args) : (args ?? {})

if (cfg.run_discover !== false) {
  phase('Discover')
  log('Building module map (one-shot)')
  // The discover agent both produces structured data AND writes it to disk;
  // schema validates the structure, the prompt requires it to call Write afterward.
  await agent(
    `Build a JSON module map of the httpware repo. List every file under src/httpware/,
tests/, docs/, and planning/. For each entry capture: line count, a one-sentence
purpose. Also extract the load-bearing invariants from CLAUDE.md verbatim.

After building the structure, write it as pretty-printed JSON to:
  ${cfg.discover_file}

Use the Write tool to create the file. Do NOT commit it; the outer plan handles that.
Return the structure per schema.`,
    { model: OPUS, schema: DISCOVER_SCHEMA, label: 'discover' },
  )
}

phase('Find')
const unknownDims = cfg.dimensions.filter(d => !DIMENSION_PROMPTS[d])
if (unknownDims.length) throw new Error(`Unknown dimensions: ${unknownDims.join(', ')}`)
const findings = await parallel(
  cfg.dimensions.map(dim => () =>
    agent(
      `${DIMENSION_PROMPTS[dim]}

Before you start, use the Read tool to load the discover map at ${cfg.discover_file}.
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
log(`Found ${allFindings.length} candidate findings across ${cfg.dimensions.length} dimensions`)

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
  ),
)

const triaged = verified.filter(Boolean)
const confirmed = triaged.filter(v => v.surviving)
const refuted = triaged.filter(v => !v.surviving)
log(`${confirmed.length}/${allFindings.length} confirmed by ≥2 verifiers; ${refuted.length} refuted (kept for Negative results)`)

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

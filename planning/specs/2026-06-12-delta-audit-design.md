# Spec: Delta audit of the 0.9.0 multi-decoder epic — code + docs

**Date:** 2026-06-12
**Baseline:** tag `0.8.6` (last commit covered by the 2026-06-07 deep audit, all findings closed by 0.8.6)
**Head:** current `main` (`ab25469`, post-0.9.0)
**Prior art:** [2026-06-07-deep-audit-design.md](2026-06-07-deep-audit-design.md), [planning/audit/workflow.mjs](../audit/workflow.mjs), [planning/audit/2026-06-07-deep-audit.md](../audit/2026-06-07-deep-audit.md)

## Purpose

Audit everything that changed since the deep audit closed — the 0.9.0 multi-decoder routing epic (PRs #41, #42) plus the docs rewrite and GH Pages migration — and sweep the *entire* docs surface for consistency with the new decoder story. The deep audit's machinery is proven; this run adapts it to a ~1k-line delta instead of the full repo.

The deliverable is a verified, severity-bucketed findings document. No fixes in this effort; fixes become follow-up specs, as with the prior audit.

## Non-goals

- Re-auditing unchanged code (`middleware/`, resilience internals, `_internal/`) — swept four days ago, untouched since.
- Performance, security, supply-chain dimensions (same exclusion as the deep audit).
- Fixing anything, including trivial typos.
- Re-running the stalled full-suite `tests` dimension from the deep audit; this run covers only the ~700 new test lines.

## Audit scope (what the finders read)

Code + tests, from `git diff 0.8.6..HEAD`:

- `src/httpware/client.py` — `decoders=[...]` parameter, type-dispatched routing, `_build_default_decoders`, `MissingDecoderError` pre-flight
- `src/httpware/decoders/__init__.py`, `decoders/pydantic.py`, `decoders/msgspec.py` — `can_decode` predicate, per-instance caches
- `src/httpware/errors.py` — `MissingDecoderError`
- `src/httpware/__init__.py` — new exports
- Changed tests: `test_client_construction.py`, `test_client_decoders_default.py`, `test_client_dispatch.py`, `test_client_send_with_response{,_sync}.py`, `test_client_sync.py`, `test_decoders_msgspec.py`, `test_decoders_pydantic.py`, `test_errors.py`, `test_optional_extras_pydantic_missing.py`, `test_public_api.py`

Docs surface (full sweep, not delta — 0.9.0 changed the decoder narrative and reversed the 0.3.0 fail-fast behavior, so unchanged pages may now be stale):

- `docs/index.md`, `docs/errors.md`, `docs/middleware.md`, `docs/resilience.md`, `docs/testing.md`, `docs/recipes/*.md`, `docs/dev/*.md`
- `README.md`, `CLAUDE.md`
- `planning/engineering.md`, `planning/deferred-work.md`, `planning/releases/0.9.0.md`
- `mkdocs.yml` nav vs. files on disk

## Architecture

Single Workflow run (one chunk — the delta is too small to justify the deep audit's 4-chunk gating). Pipeline reuses the deep-audit skeleton:

1. **Find** — 4 dimension finders in parallel (below). No discover phase: the file lists above are embedded verbatim in each finder prompt, replacing `_discover.json`.
2. **Verify** — every candidate finding judged by the existing 3-voter panel (`code_reality` / `reproducer` / `spec_grounded` lenses); survives at ≥2 confirms; severity raised on ≥2 `raise` votes, lowered on ≥1 `lower` vote. Per-dimension candidate cap: 15.
3. **Synthesize** — one agent writes the audit doc and commits it.

### Lessons from the deep audit baked in

- **Test-quality finder gets Opus.** Sonnet stalled twice (~1.5M tokens, zero findings) on meta-review dimensions; the `new_tests` finder runs on Opus with a narrower target (~700 lines, named files).
- **Synthesis must not create other files.** The synthesis prompt explicitly forbids writing or editing anything except the audit doc.
- **args JSON.parse shim retained.** `args` may arrive as a JSON string; normalize before use.

### Model assignment

- Finders 1, 2, 4: Sonnet (`claude-sonnet-4-6`)
- Finder 3 (`new_tests`): Opus (`claude-opus-4-8`)
- Verifiers: Sonnet
- Synthesis: Opus

## The 4 dimensions

### 1. `decoder_routing` (Sonnet)

Correctness of the new dispatch machinery: `can_decode` first-match ordering semantics; `MissingDecoderError` pre-flight timing (must raise before the request is sent, per the 0.9.0 spec); the default-decoder resolution matrix in `_build_default_decoders` (installed-extras detection); per-instance adapter/decoder cache behavior (PR #42 — no shared module state, no cross-instance leakage); the msgspec `CustomType` quirk — `msgspec.json.Decoder(BaseModel)` *succeeds* via CustomType fallback rather than raising, so `can_decode` must use `msgspec.inspect.type_info` filtering, not try/except.

Out of scope: sync/async divergence (dimension 2), test quality (3), docs (4).

### 2. `seam_parity` (Sonnet)

Seam B contract and sync/async parity of the changed code: both `Client.send` and `AsyncClient.send` must invoke decoder routing identically; `send_with_response` (both sides) must route through the same dispatch as `send`; `DecodeError` must still wrap decoder failures at Seam B (0.8.1 contract); `MissingDecoderError` must conform to the exception-construction conventions in CLAUDE.md (or be a documented deliberate deviation — it is not status-keyed, so the single-positional-`response` rule may legitimately not apply; the finder should check what the code does against what `errors.py` docstrings and `engineering.md` claim).

Out of scope: routing logic bugs (dimension 1), docs accuracy (4).

### 3. `new_tests` (Opus)

Quality of the changed/new test files only (named list above): tautological asserts (a known reviewer blind spot from the audit-closure retro); dispatch-matrix coverage gaps (decoder order, overlapping `can_decode`, zero-decoder client, model type matching no decoder); sync/async test parity for every new behavior; mocks/transports that hide real httpx2 behavior; tests passing for the wrong reason.

Out of scope: production-code bugs (1, 2), pre-existing test files untouched by the delta.

### 4. `docs_consistency` (Sonnet)

Every code block and load-bearing claim in the full docs surface, verified against 0.9.0 reality: residual `decoder=` (singular) usage anywhere; the fail-fast story — 0.3.0's "raise at `__init__` when extra missing" was *reversed* by 0.9.0's `MissingDecoderError` pre-flight, so any page still describing init-time failure is wrong; Seam B descriptions in `engineering.md` and CLAUDE.md vs. the actual `decode(content, model)` + `can_decode` surface; `planning/deferred-work.md` items quietly resolved (the module-global `lru_cache` item appears closed by PR #42); broken internal links; mkdocs nav vs. files on disk; release-notes claims in `planning/releases/0.9.0.md`.

When a docs finding is verified, the verifier must state whether the fix belongs in the doc or in the code; if code, synthesis recategorizes it to dimension 1 or 2.

Out of scope: prose style, doc structure opinions (the docs-philosophy memory: no autodoc, no migration guides — absence of a migration guide is not a finding).

## Schemas, verification, severity

Reuse the deep-audit schemas unchanged: `FINDING_SCHEMA` (dimension, title, file, line_hint, claim, evidence_quote, suspected_severity, reproducer_hint), `VERDICT_SCHEMA` (lens, confirmed, reason, quoted_evidence, severity_adjustment), and the severity bucket definitions:

- **Blocker** — wrong-correctness bug affecting users in normal usage; documented invariant violated; doc example that does not run.
- **High** — bug behind a non-default path; missing safety check at a documented boundary; docs that mislead a reasonable reader.
- **Medium** — works today but relies on undocumented invariants; accurate-but-ambiguous docs; test gaps in load-bearing primitives.
- **Low** — minor inaccuracies, weak idioms, hardening suggestions.
- **Nit** — style, naming, punctuation; collapsed into one rolled-up entry per dimension if more than 4 surface.

## Output

`planning/audit/2026-06-12-delta-audit.md`, same per-finding format as the deep audit (title, `file:line`, claim ≤3 sentences, fenced evidence quote, verifier consensus with lenses, suggested direction), but single-section — no chunk headers. Top-of-file summary with bucket counts and the headline finding. Synthesis commits the file as `audit(delta): 0.9.0 multi-decoder delta audit findings`.

The adapted script is saved as `planning/audit/workflow-delta.mjs` and committed alongside, mirroring how `workflow.mjs` was kept.

## File layout

```
planning/audit/
├── workflow.mjs                  # deep-audit script (unchanged, kept)
├── workflow-delta.mjs            # this run's adapted script (new)
└── 2026-06-12-delta-audit.md     # the report (new)
```

No `_discover.json` equivalent — file lists are inlined in prompts.

## Token budget (estimate)

One chunk: ~600k–900k Sonnet (3 finders + ~3 verifiers × ~20–35 surviving candidates) + ~150k Opus (`new_tests` finder + synthesis). Roughly a quarter of the deep audit's spend.

## Risks & mitigations

- **Finders re-surface closed deep-audit findings.** Mitigation: each finder prompt names the baseline (`0.8.6`) and links the prior audit doc; the `spec_grounded` verifier checks candidates against the prior audit's closed list; synthesis dedupes against it.
- **`docs_consistency` drowns in nits after a full-site sweep.** Mitigation: 15-candidate cap, nit roll-up rule, and the docs-philosophy exclusions stated in the prompt.
- **Opus `new_tests` finder over-reports style opinions.** Mitigation: prompt anchors on "passes for the wrong reason / gap in the dispatch matrix" framing with the same default-to-silence instruction as the other finders.
- **False positives.** Mitigation: unchanged 2-of-3 consensus with verifiers defaulting to `confirmed: false`.

## Open questions for writing-plans

- Exact finder prompt text (the plan drafts them; this spec fixes their scope and exclusions).
- Whether the `0.8.6..HEAD` diff itself (or just file lists) is embedded in finder prompts. Default: file lists + instruction to run `git diff 0.8.6..HEAD -- <file>` themselves, so finders see change context without bloating prompts.

## Acceptance criteria

1. `planning/audit/2026-06-12-delta-audit.md` exists, committed, with findings from all four dimensions (or an explicit "no findings survived" note per dimension).
2. Each finding carries title, `file:line`, claim, evidence quote, verifier consensus, suggested direction.
3. No file other than the audit doc and `workflow-delta.mjs` is created or modified by the run.
4. The user has reviewed the report as the audit deliverable.

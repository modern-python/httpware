---
summary: Full-codebase deep audit (perf/security/supply-chain gaps + correctness/concurrency/refactoring/test quality). [Report](audits/2026-06-14-deep-audit.md): 35 confirmed; all remediated across #62–#66 (non-streaming hard body cap deferred).
---

# Design: Full-codebase deep audit (perf · security · refactoring · bugs)

## Summary

Run a fresh full-codebase deep audit of `httpware` (code + tests +
`architecture/` docs) using a multi-agent Workflow, producing one findings
report at `planning/audits/2026-06-14-deep-audit.md` in the established
taxonomy (Blocker / High / Medium / Low / Nit + a Negative-results section).
The audit deliberately covers the dimensions the
[2026-06-07 deep audit](../../../audits/2026-06-07-deep-audit.md) explicitly
left uncovered — **performance, security, supply-chain** — plus correctness,
concurrency, refactoring, and test quality. **Report only: no code changes,
no fix PRs.** Confirmed findings spawn follow-up change bundles later, per the
normal audit→fix flow.

## Motivation

- The 2026-06-07 deep audit states in its own summary: *"No dedicated chunk
  covered performance, security, or supply-chain dimensions"* and its `tests`
  dimension stalled (~1.5M Sonnet tokens, zero findings). Those are real
  coverage gaps in the only full audit on record.
- Since 0.8.0 the codebase has grown materially (sync `Client`, circuit
  breaker, async timeout, multi-decoder routing, per-instance decoder cache).
  Delta audits covered each in isolation; nothing has swept the whole surface
  with the gap dimensions in mind.
- The existing harness (`planning/audits/scripts/workflow.mjs`) still encodes
  pre-restructure reality: it points finders at `docs/*.md` and
  `planning/engineering.md` (now `architecture/*.md` and `planning/changes/`),
  pins stale model IDs (`claude-opus-4-7`), and has no performance, security,
  or refactoring finders. A fresh run needs an updated orchestrator.

## Non-goals

- No code changes, fixes, or PRs — this pass produces a report only.
- No planning-doc staleness sweep beyond `architecture/` (the recent
  docs/UX work already churned `planning/` and the docs site).
- No re-audit of the docs site content (`docs/`) — it had its own
  2026-06-13 docs audit.
- Not a delta audit — scope is the whole `src/httpware/**` + `tests/**`
  surface, not a single version's diff.

## Design

### 1. New orchestrator: `workflow-deep.mjs`

Fork `planning/audits/scripts/workflow.mjs` into a sibling
`workflow-deep.mjs` rather than mutating the existing (delta-oriented) script.
Same four-phase pipeline — **Discover → Find → Verify → Synthesize** — same
schemas (`FINDING_SCHEMA`, `VERDICT_SCHEMA`, `DISCOVER_SCHEMA`). Differences:

- **Model IDs refreshed:** `claude-opus-4-8` for discover + synthesis,
  `claude-sonnet-4-6` for finders + verifiers.
- **Paths corrected** to current repo reality everywhere they appear in
  prompts: `architecture/*.md` (not `docs/*.md`), `planning/changes/` (not
  `planning/engineering.md` / `planning/specs/`), `CLAUDE.md` invariants.
- **Single combined run** (not per-chunk): all finders fan out in one
  `parallel()`, one verify pass, one synthesis writing the whole report.
  At ~11.8K LOC the synthesis context stays manageable, and a single run is
  simpler to reason about than the old chunk-and-commit-per-chunk flow.
- **Discover refresh:** rebuild the module map to a dated file
  `planning/audits/scripts/_discover-2026-06-14.json` so the run is
  reproducible and doesn't clobber the existing `_discover.json`.

### 2. Finder dimensions (one agent each)

The four selected areas expand to ten focused finders so each stays narrow
and adversarial (broad finders dilute signal):

| Area | Finders | Status |
|------|---------|--------|
| Correctness & concurrency | `correctness`, `concurrency` (sync/async parity), `error_contract` | reuse, path-refreshed |
| Performance | `performance` | **new** |
| Security & supply-chain | `security` | **new** |
| Refactoring & test quality | `refactoring`, `tests`, `public_api`, `optional_extras` | `refactoring` new; rest reused |
| Architecture docs | `architecture_docs` (drift of `architecture/*.md` vs code) | reuse, repointed from `docs`/`planning_docs` |

Each finder: reads the discover map first, targets 6–12 high-signal findings,
returns the `FINDING_SCHEMA` (dimension, title, file, line_hint, claim,
evidence_quote, suspected_severity, reproducer_hint), and **defaults to
silence when uncertain** (quality > quantity). Per-dimension cap stays at 15.

New finder prompt sketches:

- **`performance`** — hot-path allocations and redundant work in the
  middleware chain composition and per-request `send`; lock-hold scope and
  contention in `RetryBudget` / `Bulkhead` / `CircuitBreaker`; decoder /
  `TypeAdapter` caching effectiveness (the per-instance cache landed in 0.9.0);
  avoidable async overhead (gather vs sequential, event-loop-blocking calls);
  unnecessary `Response` body reads / copies. Out of scope: correctness,
  concurrency *hazards* (those are other finders) — this is cost, not safety.
- **`security`** — untrusted-response handling (status/header/body trust
  boundaries); decoder deserialization safety (pydantic/msgspec on attacker-
  controlled bytes, recursion/size limits); header, redirect-following, and
  URL/SSRF surfaces inherited from `httpx2`; exception messages or logs that
  could leak secrets (auth headers, URLs with credentials); dependency pinning
  and the optional-extras supply-chain surface (version floors in
  `pyproject.toml`). Out of scope: pure logic bugs.
- **`refactoring`** — duplication between sync and async surfaces that could
  share a helper without crossing a protocol seam; inconsistent naming /
  signatures / error-construction patterns; dead code; over-complex control
  flow; module-boundary smells. Findings are *suggestions* with a stated
  payoff, never style nits dressed up as bugs. Default severity low/nit unless
  the duplication has caused a real divergence.

Reused finders (`correctness`, `concurrency`, `error_contract`, `tests`,
`public_api`, `optional_extras`, `architecture_docs`) carry forward their
2026-06-07 prompts verbatim except for the path/model corrections in §1.

### 3. Verify — 3-lens panel per finding

Unchanged from the existing harness. Each surviving candidate gets three
independent Sonnet verifiers:

- **`code_reality`** — re-read the cited code ±30 lines; did the finder
  misread? Default `confirmed: false` if the code doesn't support the claim or
  can't be located.
- **`reproducer`** — sketch a 3–5 line test that demonstrates the bug (or, for
  a doc finding, a reasonable misleading read). No repro ⇒ `confirmed: false`.
- **`spec_grounded`** — does it violate a stated `CLAUDE.md` invariant (error
  contract, optional-extras isolation, no `httpx2._`, no global logging,
  naming)? Raise severity if it hits a listed invariant; lower if the spec is
  silent and it's a hardening suggestion.

A finding **survives on ≥2/3 confirms**. Severity is lowered if ≥1 verifier
says lower, raised if ≥2 say raise (existing `lowerOne`/`raiseOne` logic).

### 4. Synthesize — one report, with Negative results

A single Opus synthesis agent:

1. Triages surviving findings into Blocker / High / Medium / Low / Nit using
   the spec's severity definitions; rolls up >4 nits per dimension into one
   entry.
2. Dedups across dimensions (file + line ±5 + similar claim).
3. Writes `planning/audits/2026-06-14-deep-audit.md`: top Summary
   (counts + headline), per-bucket findings (each: `file:line` in code format,
   ≤3-sentence claim, fenced evidence quote, verifier consensus e.g. "3/3:
   code_reality, reproducer, spec_grounded", suggested direction), and a
   **Negative results** section.
4. **Negative results** are built from candidates the panel *refuted*
   (`surviving === false`) plus invariants the finders explicitly checked and
   found held — the "verified-correct surface" that is a signature of the
   prior reports. The new orchestrator passes the refuted candidates to
   synthesis instead of silently dropping them (the one structural change from
   the old harness, which discarded non-survivors).
5. Commits the report with an `audit(deep): …` message. **No source edits.**

## Operations

None. Entirely in-repo; no infra, DNS, or external accounts.

## Out of scope

Listed under Non-goals. The one explicit follow-up: confirmed findings feed
the normal audit→fix flow as new `planning/changes/active/` bundles, triaged
by severity, in a *separate* session.

## Testing

This change ships an audit report + an orchestrator script, not library code,
so "testing" means validating the *process*, not pytest:

- The Workflow completes all four phases without an unhandled throw; the
  discover JSON is written; the report file exists and parses as the expected
  Markdown structure (all five severity buckets present even if empty, a
  Negative-results section present).
- Spot-check: manually reproduce the single highest-severity finding (if any)
  to confirm the panel didn't pass a false positive — matching the prior
  audits' "headline findings reproduced directly" discipline.
- Sanity: total confirmed count is plausible (not 0 across all ten finders,
  which would signal a broken discover map or mispointed paths — the failure
  mode that stalled the 2026-06-07 `tests` dimension).

## Risk

- **Stale paths silently yield zero findings** (most likely × high impact):
  if a finder prompt still points at a moved/renamed file it returns nothing
  and looks "clean." Mitigation: every path in every prompt is rewritten in §1
  against the verified current tree; discover map is regenerated fresh and
  finders are required to read it before searching.
- **False positives surviving the panel** (medium × medium): three Sonnet
  verifiers can collectively confirm a plausible-but-wrong finding.
  Mitigation: `code_reality` defaults to false on any doubt; headline findings
  are hand-reproduced before the report is trusted.
- **Token cost overrun** (medium × low): ~10 finders + (~80 candidates × 3
  verifiers) + synthesis ≈ 250 mostly-Sonnet agents, Opus only for discover +
  synthesis — in line with the prior ~1M-token deep audit, which the user has
  opted into. The 15/dimension cap and ≥2/3 gate bound the verify fan-out.
- **Refactoring finder produces noise** (medium × low): subjective cleanup
  suggestions can crowd the report. Mitigation: prompt forces a stated payoff
  and low/nit default; the spec_grounded lens lowers anything the conventions
  are silent on.

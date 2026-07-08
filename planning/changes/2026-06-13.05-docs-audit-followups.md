---
summary: Second docs-audit batch: corrected the overstated invariant-enforcement claims in `CLAUDE.md` + `architecture/overview.md` (only `print()`/blanket-`type: ignore` are machine-checked), readability findings R1–R3, and documented the public `STATUS_TO_EXCEPTION` (G5).
---

# Change: Docs-audit follow-ups — invariant-enforcement wording + readability

**Lane:** lightweight — docs-only, no code, no public-API change. Touches a
handful of doc/truth files (above the usual ≤2 guard, but the guard proxies
*code* risk; these are mechanical/verified corrections whose thinking lives in
the audit). Spec is the audit, not a `design.md`.

Spec: [`planning/audits/2026-06-13-docs-audit.md`](../../../audits/2026-06-13-docs-audit.md)
— the second batch: the resolved `httpx2._` triage item plus findings R1, R2, R3, G5.
(First batch — the verified bugs B1/B2/I1/I2/I3 — shipped in
[`2026-06-13.04-docs-accuracy-fixes`](../2026-06-13.04-docs-accuracy-fixes/change.md).)

## Goal

Make the invariant-enforcement claims accurate and clear the concrete
readability/small-gap findings. No structural docs-UX work (de-dup, why-httpware,
migration guide, API reference) — that stays a separate, design-led change.

## Approach

- **Invariant enforcement (triage item, option 2 — "fix the claim").** Empirically
  confirmed against `ruff --select ALL`: only `print()` (`T201`) and a blanket
  `# type: ignore` (`PGH003`) are machine-checked; `httpx2._` is partial (`SLF001`
  catches attribute access, not a *used* private import); future-import / logging /
  `# ty:`-vs-`# type:` are review-only. Rewrote the overstated "(CI-enforced) / CI
  rejects PRs" heading + intro in `CLAUDE.md` and `architecture/overview.md` to the
  real split, and reframed the `httpx2._` grep as a review check (not a CI gate).
- **R3** `docs/errors.md` — examples used `_LOGGER` undefined (copy-paste `NameError`).
  Added `import logging` + `_LOGGER = logging.getLogger("myapp")` to the first block
  and a one-line note that the examples assume it.
- **G5** `docs/errors.md` — documented the public `STATUS_TO_EXCEPTION` mapping at the
  status-to-exception table (it was the lone undocumented `__all__` export).
- **R2** `README.md` — glossed "Finagle-style `RetryBudget`" as a token bucket that
  caps the global retry rate, on first use.
- **R1** `README.md` + `docs/resilience.md` — de-densified the decoder-resolution
  sentence and tightened the run-on `respect_retry_after` table cell; glossed
  "PEP 678 note" → "an exception note (PEP 678)".

## Files

- `CLAUDE.md` — invariant-enforcement heading/intro + `httpx2._` bullet
- `architecture/overview.md` — same, truth-home copy
- `docs/errors.md` — R3 (`_LOGGER`) + G5 (`STATUS_TO_EXCEPTION`)
- `README.md` — R2 (Finagle gloss) + R1 (decoder sentence)
- `docs/resilience.md` — R1 (`respect_retry_after` cell)
- `planning/audits/2026-06-13-docs-audit.md` — mark items resolved

## Verification

- [x] `mkdocs build --strict` succeeds (no broken refs).
- [x] `just lint` — clean (no source touched).
- [x] Enforcement claims match the empirical `ruff --select ALL` result
      (`T201`/`PGH003` fire; future-import, `basicConfig`, bare `getLogger`,
      and `from httpx2._x import …` do not).

## Deferred (still open after this change)

The structural docs-UX gaps need design, not mechanical edits: **G1** why-httpware,
**G2** base-client migration guide, **G3** de-dup README ↔ index.md, **G4** runnable
first quickstart (real endpoint), **G6** custom-`ResponseDecoder` guide + mkdocstrings
API reference, plus the nav-ordering nits. Tracked in the audit's onboarding/UX section.

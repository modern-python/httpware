---
status: shipped
date: 2026-06-13
slug: docs-accuracy-fixes
supersedes: null
superseded_by: null
pr: f203821
outcome: Shipped — 5 verified doc-accuracy fixes (B1 RetryBudget formula, B2 modern-di 2.x recipe, I1/I2 contributing-doc, I3 middleware contracts, AsyncTimeout wording). Pushed directly to main (no PR).
---

# Change: Fix verified doc-accuracy bugs from the docs audit

**Lane:** lightweight — docs-only, no code, no public-API change. Touches 4 doc
files (above the usual ≤2 guard, but the file-count guard proxies *code* risk;
these are mechanical corrections whose design thinking already lives in the
audit). Spec is the audit, not a `design.md`.

Spec: [`planning/audits/2026-06-13-docs-audit.md`](../../../audits/2026-06-13-docs-audit.md)
(findings B1, B2, I1, I2, I3 + the `AsyncTimeout`-validation wording).

## Goal

Correct the five verified factual errors in the user-facing docs so copy-pasted
examples run and documented behaviour matches the code. No prose-quality or
onboarding work (that is the separate, deferred docs-UX change).

## Approach

Each edit is pinned to a finding verified against source (or, for B2, the
official modern-di 2.x migration docs):

- **B1** `docs/resilience.md` token-bucket formula — `int(... * percent)` →
  `ceil(... * percent)`; floor term stays `int(...)`. Matches `budget.py:68`.
- **B2** `docs/recipes/modern-di.md` — drop `await` on every `container.resolve(...)`
  (2.x is sync-only); construct the root `Container` plainly + close it via
  `await container.close_async()` in `try/finally` (root is not an async CM in 2.x);
  soften the `inspect.iscoroutinefunction` claim to observable behaviour.
- **I1** `docs/dev/contributing.md` — "enforced by CI grep gates" → accurate
  enforcement (CI lint pass: ruff + ty; review for the rest). No grep runs in CI.
- **I2** `docs/dev/contributing.md` — add `eof-fixer` to the `just lint` comment.
- **I3** `docs/middleware.md` — list all four stable observability contracts
  (`retry`, `bulkhead`, `circuit_breaker`, `timeout`), not two.
- **AsyncTimeout wording** `docs/resilience.md` — note non-finite (`inf`/`nan`)
  rejection, matching `timeout.py:47` and `architecture/resilience.md:17`.

No `architecture/` promotion needed — these docs already lag the truth home; the
edits bring them back into line with it.

## Files

- `docs/resilience.md` — B1 formula + AsyncTimeout validation wording
- `docs/recipes/modern-di.md` — B2 modern-di 2.x API
- `docs/dev/contributing.md` — I1 grep-gates wording + I2 eof-fixer
- `docs/middleware.md` — I3 stable-contracts list

## Verification

- [x] Each edit matches its cited source line (B1↔`budget.py:68`,
      AsyncTimeout↔`timeout.py:47`, I2↔`justfile:7-11`, I3↔`architecture/resilience.md:23`;
      B2↔modern-di 2.x migration docs).
- [x] `mkdocs build --strict` succeeds (no broken links/refs introduced).
- [x] `just lint` — clean (no source touched, confirmed nothing regressed).
- [x] Final read-through — no residual `await container.resolve` / `async with Container`
      (root) / two-of-four contracts / `int(... * percent)` phrasing remains.

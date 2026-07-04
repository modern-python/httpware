---
summary: Reframe the "Why httpware" pitch benefit-first, boldly restructure the user docs for readability (real quickstart, promoted Observability page, trimmed resilience reference, usage-before-extension nav), and fix a batch of doc/code inconsistencies and incompletes surfaced by a paired audit.
---

# Design: Docs overhaul + audit fixes

## Summary

Two intertwined problems, one PR. **(1) Positioning + readability:** the docs
lead with `Typed errors, no raise_for_status()` — a benefit stated as the
negation of an httpx idiom that is never named as the baseline, so it reads as a
comparison against an unnamed solution. And the core pages are heavy (index.md
~1030 words doubling as three references; resilience.md ~2668). **(2)
Correctness:** a paired docs↔code audit found a batch of doc claims that state
the *opposite* of what the code does (notably two security-relevant redaction
claims), plus real features (`ResponseTooLargeError` / `max_response_body_bytes`)
absent from every user-facing doc.

This change reframes the pitch benefit-first, boldly restructures the user docs
(true quickstart, a promoted Observability page, a trimmed resilience reference,
and a usage-before-extension nav), and lands the audit fixes. It is
**docs-and-docstrings only** — no public API change and, by the maintainer's
ruling on the one behavioral finding, no runtime behavior change.

## Motivation

- **The lead bullet is confusing.** `Typed errors, no raise_for_status()`
  (README.md:25, index.md:7) requires the reader to already know
  `raise_for_status()` is an httpx method to parse the benefit. A newcomer reads
  it as a missing feature of some unnamed internal tool. It is the single
  highest-visibility line in the docs and it stalls a 15-second skim.
- **The core pages are too big.** ~6,160 of the corpus's ~10,455 words sit in
  four pages (index, middleware, decoders, resilience). index.md is a quickstart
  bolted to three reference sections; Observability — a ~50-line stable-contract
  reference deep-linked from four pages — is buried inside it.
- **Several docs are factually wrong or incomplete.** The audit confirmed doc
  claims that contradict the code, including two that tell users the opposite of
  the redaction behavior (a security footgun), and an entire shipped feature
  (`max_response_body_bytes` + `ResponseTooLargeError`) documented only in
  `architecture/`, never for users.

## Decisions taken (maintainer ruling)

- **"Why" framing → benefit-first, drop the jargon.** Lead with the payoff, no
  httpx prerequisite; `raise_for_status()` leaves the lead entirely.
- **Restructure appetite → bold.** Free to split/move content, reorder nav,
  de-duplicate across README/index.md, and add a new page.
- **Finding #9 (streaming-refusal note on the non-idempotent early-exit path) →
  fix the doc, not the code.** A non-idempotent request already refuses for a
  clearer reason (method not eligible); the extra note is redundant there. Zero
  behavior change.

## Non-goals

- **No public API change.** No class/param renames even where naming is awkward
  (e.g. nav labels vs. H1s are aligned in docs only).
- **No runtime behavior change.** Every code-vs-doc divergence is resolved by
  correcting the doc, because in each case the code's behavior is the intended
  one (confirmed against `architecture/` and re-read source).
- **Not restructuring `architecture/`.** It stays the AI-agent truth home;
  factual errors found there are still corrected, but its shape is untouched.
- **Not growing README.** It stays a lean shopfront pointing at the docs site.

## Design

### Part A — Positioning

Rewrite the "Why httpware" bullets benefit-first, and **de-duplicate**: README
owns the pitch; index.md's intro links rather than repeating it verbatim.

> - **Errors you can catch by name** — a 404 raises `NotFoundError`, a 429
>   `RateLimitedError`, automatically; everything else bubbles up under one
>   `StatusError` base.
> - **Typed response bodies** — `response_model=User` decodes straight to your
>   pydantic or msgspec type.
> - **Composable resilience** — retry, bulkhead, circuit breaker, timeout as
>   middleware over standard `httpx2`.

Applied to README.md:25-27; index.md:5-9 collapses to a one-line pitch + link so
the two no longer drift.

### Part B — Information architecture (bold restructure)

1. **`index.md` → a true quickstart** (~1030 → ~500 words). Keep: install, first
   request (async + sync), typed-decoding example, one resilience teaser,
   streaming, "where next." Collapse to a teaser-sentence-plus-link each:
   - Decoder-dispatch (index.md:74-101) → 3 lines + link to decoders.md (the
     canonical home).
   - Errors summary (index.md:141-150) → one sentence + link to errors.md.
   - Observability (index.md:152-183) → **moved out** (see 2).
2. **Promote Observability to its own page** `docs/observability.md`. It is the
   canonical stable-contract reference (logger/event table, OTel wiring) yet
   lives in the quickstart and is deep-linked as `index.md#observability` from
   resilience.md, middleware.md, and errors.md. Move it; repoint every inbound
   link to `observability.md`. (URL note below.)
3. **`resilience.md` → trim, do not split** (~2668 → ~2200). It is a scan-by-
   heading reference; splitting fragments it. Cut the real bloat — sync/async
   duplication: replace the repeated sync `Retry`/`Bulkhead` param tables
   (resilience.md:345-368) with "identical to the async table above; differences:
   uses `time.sleep` / `threading.Semaphore`, no sync `Timeout`, per-world
   bulkhead cap." Add a jump-link TOC of the six primitives at the top.
4. **Nav reorder — usage before extension.** New order:
   `Quick-Start → Resilience → Errors → Observability → Decoders → Middleware →
   Testing → Recipes → Development`. A newcomer reaches "what errors fire / how
   to add resilience" before the rarer "author your own seam" guides.
5. **Align page titles with reader intent.** Rename the H1s `Writing custom
   middleware` → `Middleware` and `Writing a custom decoder` → `Decoders`, each
   with an "authoring" section inside. (Docs only; no symbol change.)
6. **`middleware.md`** — consolidate the scattered "when NOT to write one" /
   "reach for X instead" asides (middleware.md:52-54, 108-113) into one decision
   note; replace the re-explained OTel-SDK setup (middleware.md:115-137) with a
   link to the new Observability page.

### Part C — Correctness fixes (audit findings)

**Doc corrections — code is correct, doc is wrong (re-verified against source):**

| # | Location | Fix |
|---|---|---|
| 3 | `errors.md:118` | "query-string secrets are NOT stripped" is false — `redaction.py:70-116` masks values of sensitive query keys (`token`, `api_key`, `secret`, …) *and* strips `user:pass@`. Rewrite to describe the real behavior. **(security-relevant)** |
| 5 | `middleware.md:110` | "httpware deliberately does no redaction in-library" is false — URLs are redacted at `observability.py:49-51,64` and `errors.py:69,75`. Rewrite. **(security-relevant)** |
| 1 | `resilience.md:32-33` | "clamped to `max_delay`" is wrong; `retry.py:181-188` **gives up and re-raises** when `Retry-After > max_delay`. Fix to match the same file's line 24. |
| 9 | `resilience.md:44-45` | Claims the streaming-refusal note is added at the non-idempotent early-exit sites; `retry.py:134-139` raise without it. Correct the doc (per ruling). |
| 6 | `testing.md:114` | Dead ref to "`RecordedTransport`-was-removed history" — the string exists nowhere in `architecture/testing.md`. Remove. |
| 7 | `index.md:3` | Intro undercounts the suite (omits CircuitBreaker + Timeout). Fix to match README:21. |
| 11 | `contributing.md:34` | `T20` → `T201` to match `architecture/overview.md` and CLAUDE.md. |

**Incompletes — document features that exist in code but not in user docs:**

| # | Feature | Fix |
|---|---|---|
| 4 / 8 | `ResponseTooLargeError` + `max_response_body_bytes` (client.py:238,1210; errors.py:328) | Add `ResponseTooLargeError` to the errors.md tree; document the `max_response_body_bytes` client param (and the cap behavior) where the client is introduced. |
| 2 | CircuitBreaker rate-mode params `failure_rate_threshold`, `window_seconds`, `minimum_calls` (circuit_breaker.py:315-326) | Add to the constructor param table in resilience.md (currently prose-only). |
| 12 | `httpx2_client=` exclusivity `TypeError` (client.py:251-252,1223-1224) | One-line note wherever `httpx2_client=` usage is shown (testing.md, architecture/client.md). |

**Source docstring cleanup:**

| # | Location | Fix |
|---|---|---|
| 10 | client.py:1121; observability.py:3; circuit_breaker.py:3; budget.py:3; bulkhead.py:3; retry.py:3 | All cite `planning/specs/2026-06-*.md`, a directory that does not exist. Repoint to the real `planning/changes/<bundle>/` or drop the reference. |

### `architecture/` promotion

Per house rule, the same PR hand-edits the affected `architecture/*.md`. The
audit found `architecture/errors.md` and `architecture/resilience.md` already
describe redaction correctly, so only the user docs move toward them. Any
capability whose user-facing wording changes gets its `architecture/` file
re-checked for agreement; expected edits are minimal (the truth home is already
ahead of the user docs here).

## Testing

Docs-and-docstrings only, so verification is correctness-of-claims, not runtime:

- **`mkdocs build --strict`** (or the repo's docs build) is green — no broken
  internal links after the Observability move and nav reorder. Every repointed
  `index.md#observability` link resolves to `observability.md`.
- **Every changed claim re-verified against source** at the cited file:line
  before the wording is finalized (the audit's line refs are the checklist).
- **`just check-planning`** passes for this bundle; **`just lint-ci`** stays
  green (docstring edits included).
- **No new pytest tests** — the maintainer ruled finding #9 a doc fix, so there
  is no behavior change to cover with a test. (Had we chosen the code fix, it
  would have been TDD: failing test first, sync + async parity.)

## Risk

- **Observability anchor URL changes** (certain × low). External links to
  `/#observability` break when it moves to `/observability/`. Acceptable pre-1.0;
  all *internal* links are repointed in the same PR. Page paths themselves are
  unchanged, so `/resilience/`, `/errors/`, etc. keep resolving.
- **Restructure drops a detail readers relied on** (unlikely × low). Mitigation:
  the trims target duplication (sync/async tables, cross-page repeats), not
  unique content; the audit's "verified correct" list bounds what must be
  preserved.
- **A doc "fix" mis-reads the code** (unlikely × medium). Mitigation: each of the
  seven corrections carries an exact source file:line; the two security-relevant
  ones (#3, #5) and #9/#1 were re-read directly during design.

## Operations

None — no out-of-repo steps. Docs deploy on merge via the existing pipeline.

## Out of scope

- Any public API rename or runtime behavior change.
- Restructuring `architecture/` (only factual corrections there).
- Growing README beyond the shopfront role.
- A separate `audits/` findings file — the findings are captured inline here
  since this is the single combined change that resolves them.

# docs-overhaul-and-audit-fixes — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps
> use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reframe the "Why httpware" pitch benefit-first, boldly restructure the
user docs (true quickstart, promoted Observability page, trimmed resilience
reference, usage-before-extension nav), and land the paired-audit doc/docstring
fixes — with zero API or runtime behavior change.

**Spec:** [`design.md`](./design.md)

**Branch:** `docs/overhaul-and-audit-fixes`

**Commit strategy:** Per-task commits. This is a **docs + docstrings** change:
there is no runtime behavior to test, so each task's "verification" is (a) a
`grep` that the wrong text is gone / the right text is present, and (b)
`just docs-build` (= `mkdocs build --strict`, fails on broken links / nav
warnings). Not TDD — no pytest tests are added (the one behavioral finding, #9,
was ruled a doc fix by the maintainer).

## Global Constraints

- **Docs + docstrings only.** No source under `src/httpware/*.py` changes except
  the six docstring header edits in Task 8. No public API rename, no behavior
  change.
- **Keep README lean** — a shopfront pointing at the docs site; do not grow it.
- **`architecture/` shape is fixed** — correct factual errors there if found, but
  do not restructure it (it is the AI-agent truth home).
- **Every changed claim must match source** at the file:line the design cites;
  re-read the code before finalizing wording.
- **House copy rules:** no em-dashes-as-quotes issues aside, keep existing voice;
  logger/event/exception names are the stable public contract — quote them
  verbatim.
- **Commit trailer** (every commit): `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
  Keep commit messages free of embedded double-quotes (use `-F` a message file if
  a message needs them).
- **Verification commands:** `just docs-build`, `just lint-ci`, `just check-planning`.

---

### Task 1: Positioning — benefit-first "Why", de-duplicated

**Files:**
- Modify: `README.md:23-29` (the "## Why httpware" block)
- Modify: `docs/index.md:5-9` (the duplicate "## Why httpware" block)

Rewrite the pitch benefit-first (drop the `raise_for_status()` jargon lead) and
stop README + index.md from carrying the same three bullets verbatim.

- [ ] **Step 1: Rewrite the README bullets**

  Replace the three bullets under `## Why httpware` in `README.md` with:

  ```markdown
  - **Errors you can catch by name** — a 404 raises `NotFoundError`, a 429
    `RateLimitedError`, automatically; everything else bubbles up under one
    `httpware.StatusError` base. No `raise_for_status()`, no status-code
    branching.
  - **Typed response bodies** — `response_model=User` decodes the body straight
    to your pydantic or msgspec type; a missing decoder fails fast, *before* the
    request goes out.
  - **Composable resilience** — retry + retry-budget, bulkhead, circuit breaker,
    and timeout as middleware over standard `httpx2`.
  ```

  (`raise_for_status()` now appears only as a trailing "no boilerplate" clause on
  bullet one, never as the lead.)

- [ ] **Step 2: Collapse the index.md duplicate to a pointer**

  In `docs/index.md`, replace the `## Why httpware` block (currently the same
  three bullets) with a one-line pitch that does not repeat the README verbatim,
  e.g.:

  ```markdown
  ## Why httpware

  Typed exceptions per HTTP status, typed response bodies, and composable
  resilience (retry, bulkhead, circuit breaker, timeout) — a thin wrapper over
  `httpx2`, not a new HTTP abstraction. See the
  [project README](https://github.com/modern-python/httpware#why-httpware) for
  the full pitch.
  ```

- [ ] **Step 3: Verify**

  Run: `grep -n "no \`raise_for_status" README.md` → expect a match on bullet one
  only. Run: `grep -rn "Errors you can catch by name" docs/index.md` → expect
  **no** match (index no longer duplicates). Run: `just docs-build` → green.

- [ ] **Step 4: Commit**

  ```
  git add README.md docs/index.md
  git commit -m "docs: reframe Why httpware benefit-first and de-duplicate

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 2: Promote Observability to its own page + final nav

**Files:**
- Create: `docs/observability.md`
- Modify: `docs/index.md:152-183` (remove the Observability section)
- Modify: `docs/resilience.md`, `docs/middleware.md`, `docs/errors.md` (repoint
  inbound `index.md#observability` links)
- Modify: `mkdocs.yml` (nav: add the page **and** apply the final usage-before-
  extension order)

Move the ~50-line stable-contract Observability reference out of the quickstart
into its own page, repoint every inbound link, and write the nav to its final
state in one edit (so nav is only touched once).

- [ ] **Step 1: Create `docs/observability.md`**

  Move the entire `## Observability` section from `docs/index.md:152-183` into a
  new `docs/observability.md`. Give it an H1 `# Observability` and a one-sentence
  intro. Preserve verbatim: the logger/event table (the four rows
  `httpware.retry` / `httpware.bulkhead` / `httpware.circuit_breaker` /
  `httpware.timeout` with their event names and levels), the `event=` field note,
  the `logging.getLogger(...).setLevel(...)` snippet, and the OTel `pip install
  httpware[otel]` / `_emit_event` → `add_event` paragraph. These names are the
  public contract — do not reword them.

- [ ] **Step 2: Leave a teaser in index.md**

  Where the Observability section was, leave a 2-line teaser + link:

  ```markdown
  ## Observability

  Every resilience middleware emits stdlib-`logging` records (always) and OTel
  span events (when `opentelemetry-api` is installed), under stable logger and
  event names. See **[Observability](observability.md)** for the full contract.
  ```

- [ ] **Step 3: Repoint inbound links**

  Run `grep -rn "index.md#observability" docs/` to find every inbound link
  (expected in `resilience.md`, `middleware.md`, `errors.md`). Repoint each to
  `observability.md` (same-dir relative link; drop the `index.md` prefix). If a
  link targets a sub-anchor, keep the anchor: `observability.md#...`.

- [ ] **Step 4: Write the final nav**

  In `mkdocs.yml`, replace the `nav:` block with the usage-before-extension order
  including the new page:

  ```yaml
  nav:
    - Quick-Start: index.md
    - Resilience: resilience.md
    - Errors: errors.md
    - Observability: observability.md
    - Decoders: decoders.md
    - Middleware: middleware.md
    - Testing: testing.md
    - Recipes:
        - modern-di: recipes/modern-di.md
        - Phase decorator patterns: recipes/phase-decorator-patterns.md
        - Link header pagination: recipes/link-header-pagination.md
    - Development:
        - Contributing: dev/contributing.md
  ```

- [ ] **Step 5: Verify**

  Run: `grep -rn "index.md#observability" docs/` → expect **no** matches. Run:
  `just docs-build` → green (strict mode fails on any broken link left behind).

- [ ] **Step 6: Commit**

  ```
  git add docs/observability.md docs/index.md docs/resilience.md docs/middleware.md docs/errors.md mkdocs.yml
  git commit -m "docs: promote Observability to its own page and reorder nav

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 3: Slim index.md to a true quickstart

**Files:**
- Modify: `docs/index.md` (Decoder-dispatch, Errors sections; intro line)

With Observability already moved out (Task 2), collapse the remaining reference
sections to teasers and fix the intro's suite undercount (finding #7).

- [ ] **Step 1: Fix the intro suite undercount (#7)**

  `docs/index.md:3` describes the resilience suite as "`AsyncRetry`/`Retry` +
  `RetryBudget`, `AsyncBulkhead`/`Bulkhead`" — it omits CircuitBreaker and
  Timeout. Extend it to match README:21, e.g. "…`AsyncRetry`/`Retry` +
  `RetryBudget`, `AsyncBulkhead`/`Bulkhead`, `AsyncCircuitBreaker`/`CircuitBreaker`,
  and `AsyncTimeout`".

- [ ] **Step 2: Collapse "Decoder dispatch" to a teaser**

  Replace the `### Decoder dispatch` block (`docs/index.md:74-101`) with ~3 lines:
  the client walks `decoders` in order and picks the first whose `can_decode`
  returns `True`; ordering encodes preference for shared shapes; `MissingDecoderError`
  fires *before* the HTTP call if none claims the type. End with:
  "See **[Decoders](decoders.md)** for the resolution rules and pydantic/msgspec
  routing." Do not keep the two `AsyncClient(decoders=[...])` examples here —
  they live in `decoders.md`.

- [ ] **Step 3: Collapse the "Errors" section to a teaser**

  Replace the `## Errors` block (`docs/index.md:141-150`) with one sentence: all
  errors inherit `httpware.ClientError`; 4xx/5xx raise a typed `StatusError`
  subclass automatically, decode failures raise `DecodeError`. End with:
  "See **[Errors](errors.md)** for the full tree and catching strategies."

- [ ] **Step 4: Verify**

  Run: `grep -c "AsyncClient(decoders=" docs/index.md` → expect `0`. Word-count
  check: `wc -w docs/index.md` → expect roughly 450-600 (down from ~1030). Run:
  `just docs-build` → green.

- [ ] **Step 5: Commit**

  ```
  git add docs/index.md
  git commit -m "docs: slim index.md to a true quickstart

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 4: Trim resilience.md + fix its factual claims

**Files:**
- Modify: `docs/resilience.md`

Cut the sync/async duplication, add a jump-TOC, and land findings #1, #9, #2.

- [ ] **Step 1: Fix the Retry-After claim (#1)**

  `docs/resilience.md:32-33` says an over-`max_delay` `Retry-After` is "clamped to
  `max_delay`". The code (`retry.py:181-188`) **gives up and re-raises**. Rewrite
  both bullets so they agree with line 24: integer `Retry-After: N` → sleep N
  seconds, but if N exceeds `max_delay`, `AsyncRetry` gives up and re-raises;
  HTTP-date form → same, computed delay floored at 0. Remove every "clamped to
  `max_delay`" phrase in this section.

- [ ] **Step 2: Fix the streaming-note claim (#9)**

  Delete the sentence at `docs/resilience.md:44-45` claiming the streaming-refusal
  note "is added at the non-idempotent early-exit sites". Replace with the true
  behavior: a non-idempotent request that also carries a streaming body is refused
  by the method-eligibility check first (`retry.py:134-139`) and raised without
  the streaming note; the streaming-refusal note is added only on the
  retryable-failure path.

- [ ] **Step 3: Add CircuitBreaker rate-mode params to the table (#2)**

  In the CircuitBreaker "Constructor" table (`docs/resilience.md:166-172`), add
  rows for the three rate-mode params from `circuit_breaker.py:315-326`:
  `failure_rate_threshold`, `window_seconds`, `minimum_calls` — with their types,
  defaults, and one-line meanings (mirror the prose already at :194-211). Keep the
  prose section but make the table complete.

- [ ] **Step 4: Cut the sync/async table duplication**

  Replace the duplicated sync param tables in the "Sync Retry and Bulkhead"
  section (`docs/resilience.md:345-368`) with prose: "`Retry` takes the identical
  parameters as `AsyncRetry` (table above); it sleeps with `time.sleep` between
  attempts. `Bulkhead` mirrors `AsyncBulkhead` on a `threading.Semaphore`." Keep
  only the genuinely sync-specific notes (no sync `Timeout`; the per-world
  bulkhead-cap caveat).

- [ ] **Step 5: Add a jump-TOC**

  At the top of `docs/resilience.md` (after the H1/intro), add a short bullet list
  linking to the six primitive sections (Retry, RetryBudget, Bulkhead,
  CircuitBreaker, Timeout, plus the sync notes) via their heading anchors.

- [ ] **Step 6: Verify**

  Run: `grep -n "clamped to" docs/resilience.md` → expect **no** matches. Run:
  `grep -n "failure_rate_threshold" docs/resilience.md` → expect a match in the
  table region (before line ~194). Run: `wc -w docs/resilience.md` → expect
  roughly 2200-2350 (down from ~2668). Run: `just docs-build` → green.

- [ ] **Step 7: Commit**

  ```
  git add docs/resilience.md
  git commit -m "docs: trim resilience.md and fix Retry-After, streaming, breaker-table claims

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 5: errors.md — redaction fix, missing error, cap feature

**Files:**
- Modify: `docs/errors.md`

Land findings #3 (security-relevant), #4, and the errors-side of #8.

- [ ] **Step 1: Fix the query-string redaction claim (#3)**

  `docs/errors.md:118` states "**Query-string secrets are NOT stripped**". The
  code (`_internal/redaction.py:70-116`) **does** mask sensitive query-key values.
  Replace the sentence with the accurate behavior:

  ```markdown
  `__repr__` and the exception's summary message strip `user:pass@` userinfo and
  mask the values of known-sensitive query parameters (`token`, `api_key`,
  `access_token`, `secret`, `password`, `authorization`, `signature`, …) as
  `REDACTED`, preserving the keys. Query values under other names are **not**
  masked, so still avoid putting non-standard secrets in query strings.
  ```

  (Confirm the key list against `SENSITIVE_QUERY_KEYS` in `redaction.py:12-34`
  before finalizing.)

- [ ] **Step 2: Add `ResponseTooLargeError` to the tree (#4)**

  Add `ResponseTooLargeError` to the exception tree diagram (`docs/errors.md:11-33`)
  as a non-status `ClientError` subclass, alongside `DecodeError` /
  `MissingDecoderError` / the resilience refusals. Confirm placement against
  `errors.py:328` and `architecture/errors.md:21`.

- [ ] **Step 3: Document the `max_response_body_bytes` cap (#8, errors side)**

  Add a short subsection (or extend the `ResponseTooLargeError` payload entry)
  explaining: `ResponseTooLargeError` is raised when a response body exceeds the
  client's `max_response_body_bytes` cap (default `None` = unbounded); it carries
  `limit`, `status_code`, `content_length`, and `reason` (`"declared"` |
  `"streamed"`). Cross-reference the client param (documented in Task 6).

- [ ] **Step 4: Verify**

  Run: `grep -n "NOT stripped" docs/errors.md` → expect **no** match. Run:
  `grep -n "ResponseTooLargeError" docs/errors.md` → expect matches (tree +
  payload). Run: `just docs-build` → green.

- [ ] **Step 5: Commit**

  ```
  git add docs/errors.md
  git commit -m "docs: correct query-redaction claim; document ResponseTooLargeError

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 6: middleware.md — redaction fix, consolidation, H1

**Files:**
- Modify: `docs/middleware.md`

Land finding #5 (security-relevant), consolidate the digressions, link to the new
Observability page, and rename the H1.

- [ ] **Step 1: Fix the "no redaction in-library" claim (#5)**

  `docs/middleware.md:110` states httpware "deliberately does no redaction
  in-library". The code redacts URLs at `_internal/observability.py:49-51,64`
  (event `url` attribute) and `errors.py:69,75` (StatusError message / `repr`).
  Replace with the accurate statement:

  ```markdown
  **Redaction:** httpware redacts URLs before they reach logs, telemetry, and
  error messages — `user:pass@` userinfo is stripped and sensitive query-parameter
  values are masked (`_internal/redaction.py`). It does **not** inspect or redact
  headers or request/response bodies, so if your own middleware logs those, redact
  them yourself.
  ```

- [ ] **Step 2: Consolidate the "when NOT to" asides**

  Merge the scattered "reach for X instead" / "when NOT to write a middleware"
  blocks (`docs/middleware.md:52-54, 108-113`) into a single decision note
  (middleware vs. `httpx2` event_hooks vs. transport). Remove the duplication;
  keep one clear home.

- [ ] **Step 3: Link OTel setup to the Observability page**

  Replace the re-explained OTel SDK/instrumentor setup (`docs/middleware.md:115-137`)
  with a short pointer to **[Observability](observability.md)** for the wiring,
  keeping only the middleware-specific bit (how a custom middleware enriches the
  active span).

- [ ] **Step 4: Rename the H1**

  Change the H1 from "Writing custom middleware" to `# Middleware`, with a
  `## Writing your own` section wrapping the authoring content. (Docs only — no
  symbol change; nav label already "Middleware".)

- [ ] **Step 5: Verify**

  Run: `grep -n "does no redaction" docs/middleware.md` → expect **no** match.
  Run: `grep -n "^# Middleware$" docs/middleware.md` → expect a match. Run:
  `just docs-build` → green.

- [ ] **Step 6: Commit**

  ```
  git add docs/middleware.md
  git commit -m "docs: correct redaction claim, consolidate asides, rename Middleware H1

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 7: Remaining doc corrections (decoders H1, testing, contributing, client cap)

**Files:**
- Modify: `docs/decoders.md` (H1)
- Modify: `docs/testing.md` (findings #6, #12)
- Modify: `docs/dev/contributing.md` (finding #11)
- Modify: `docs/index.md` (client-side of #8 — the `max_response_body_bytes` param)

The scattered small fixes, grouped.

- [ ] **Step 1: Rename the decoders H1**

  Change `docs/decoders.md:1` from "Writing a custom decoder" to `# Decoders`,
  with a `## Writing your own` section wrapping the authoring content.

- [ ] **Step 2: Remove the dead RecordedTransport ref (#6)**

  Delete the phrase at `docs/testing.md:114` claiming `architecture/testing.md`
  covers "the `RecordedTransport`-was-removed history" — that string exists
  nowhere in `architecture/testing.md` (confirm: `grep -rn RecordedTransport
  architecture/` → no output). Reword the cross-reference to what that file
  actually covers, or drop the clause.

- [ ] **Step 3: Note the `httpx2_client=` exclusivity (#12)**

  Where `docs/testing.md` shows `httpx2_client=` usage, add a one-line note:
  passing `httpx2_client=` is mutually exclusive with `base_url` / `headers` /
  other forwarded client kwargs — combining them raises `TypeError`
  (`client.py:251-252, 1223-1224`).

- [ ] **Step 4: Fix the ruff code (#11)**

  In `docs/dev/contributing.md:34`, change `T20` to `T201` to match
  `architecture/overview.md` and `CLAUDE.md`.

- [ ] **Step 5: Document `max_response_body_bytes` on the client (#8, client side)**

  In `docs/index.md`, where the client constructor / resilience is introduced, add
  a brief note that `Client`/`AsyncClient` accept `max_response_body_bytes: int |
  None = None` to cap decoded response-body size, raising `ResponseTooLargeError`
  (link to [Errors](errors.md)) when exceeded. Confirm the param against
  `client.py:238, 1210`.

- [ ] **Step 6: Verify**

  Run: `grep -rn "RecordedTransport" docs/` → expect **no** match. Run:
  `grep -n "T201" docs/dev/contributing.md` → expect a match. Run:
  `grep -n "^# Decoders$" docs/decoders.md` → expect a match. Run:
  `grep -n "max_response_body_bytes" docs/index.md` → expect a match. Run:
  `just docs-build` → green.

- [ ] **Step 7: Commit**

  ```
  git add docs/decoders.md docs/testing.md docs/dev/contributing.md docs/index.md
  git commit -m "docs: fix decoders H1, dead testing ref, ruff code, client cap note

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 8: Source docstring cleanup — dead `planning/specs/` refs (#10)

**Files:**
- Modify: `src/httpware/client.py:1121`
- Modify: `src/httpware/_internal/observability.py:3`
- Modify: `src/httpware/middleware/resilience/circuit_breaker.py:3`
- Modify: `src/httpware/middleware/resilience/budget.py:3`
- Modify: `src/httpware/middleware/resilience/bulkhead.py:3`
- Modify: `src/httpware/middleware/resilience/retry.py:3`

Each docstring cites `planning/specs/2026-06-*.md`, a directory that does not
exist. Repoint to the real bundle or drop the reference. **Docstring text only —
no code change.**

- [ ] **Step 1: Find the exact references**

  Run: `grep -rn "planning/specs/" src/httpware/` → lists all six. For each, note
  what capability it documents.

- [ ] **Step 2: Repoint or drop**

  For each, either repoint to the real bundle under `planning/changes/` that
  owns that capability (e.g. the retry/circuit-breaker/budget/bulkhead extraction
  bundles under `planning/changes/2026-06-23.*` / `2026-06-16.*`), or, if no
  single bundle is a clean match, drop the "see `planning/specs/...`" clause and
  point to `architecture/<capability>.md` instead (the living truth home). Do not
  invent a bundle path — verify it exists with `ls` before writing it.

- [ ] **Step 3: Verify**

  Run: `grep -rn "planning/specs/" src/httpware/` → expect **no** matches. Run:
  `just lint-ci` → green (docstring edits must not break format/lint/ty).

- [ ] **Step 4: Commit**

  ```
  git add src/httpware/
  git commit -m "docs: repoint dead planning/specs docstring references

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 9: architecture/ re-check, finalize summary, full verification, PR

**Files:**
- Modify: `architecture/*.md` (only if a factual disagreement is found)
- Modify: `planning/changes/2026-07-05.01-docs-overhaul-and-audit-fixes/design.md`
  (finalize `summary:` to the realized result)

Promote/reconcile, finalize the bundle, run the full gate, open the PR.

- [ ] **Step 1: Reconcile architecture/**

  For each capability whose user doc wording changed (errors, resilience,
  middleware, client), skim the matching `architecture/*.md` and confirm it still
  agrees with the code and the corrected user docs. The audit found
  `architecture/errors.md` and `architecture/resilience.md` already describe
  redaction correctly, so expect few or no edits. Fix any genuine disagreement;
  do **not** restructure.

- [ ] **Step 2: Finalize the bundle summary**

  Edit the `summary:` line in `design.md` to state what actually shipped (per the
  repo convention: written at creation, finalized at ship). Keep it one line.

- [ ] **Step 3: Full gate**

  ```
  just docs-build
  just lint-ci
  just check-planning
  ```

  All green. Grep guards:
  `grep -rn "planning/specs/" src/httpware/` → nothing;
  `grep -rn "index.md#observability" docs/` → nothing;
  `grep -rn "NOT stripped\|does no redaction\|clamped to" docs/` → nothing.

- [ ] **Step 4: Regenerate the index**

  ```
  just index
  ```

  Confirm the new bundle appears newest-first with the finalized summary.

- [ ] **Step 5: Commit + open the PR**

  ```
  git add architecture/ planning/
  git commit -m "docs: reconcile architecture and finalize bundle summary

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

  Then push and open the PR per `superpowers:finishing-a-development-branch`
  (never local-merge). Watch PR CI (`docs-build`, `lint-ci`) after pushing.

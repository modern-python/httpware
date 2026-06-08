# Spec: Post-0.8.0 doc-staleness sweep

**Date:** 2026-06-08
**Topic slug:** `post-080-doc-sweep`
**Status:** drafted, awaiting user review
**Target output:** 6 commits on `main`, no code-behavior changes

## Purpose

Close the doc-staleness findings the [deep audit](../audit/2026-06-07-deep-audit.md) identified as the dominant cross-cutting theme (cross-cutting themes §1) — eight Low findings spread across `CLAUDE.md`, `README.md`, `docs/index.md`, `docs/resilience.md`, and `planning/engineering.md`, plus three Nit sub-items in the audit's rolled-up `stale-doc` entry (`CLAUDE.md` Seam 2 wording, `CLAUDE.md` L91 testing pattern, `engineering.md` §8 closing version) and the related `decoders/__init__.py` Seam-3 docstring label. The sweep also fixes one un-audited consistency leftover (`CLAUDE.md` L7 still says "async HTTP client framework" — the same wording the audit flagged at `docs/index.md:3` and `README.md:8`, just in a different file). All findings trace back to the 0.8.0 release that added the sync `Client` and renamed the async surface to `Async*`. The doc surface didn't propagate those changes, so:

- The two landing pages (`README.md`, `docs/index.md`) still call httpware "an async HTTP client framework."
- `docs/resilience.md` still says "three resilience primitives" when there are five.
- The two observability paragraphs (in README + docs/index.md) still name only `AsyncRetry`/`AsyncBulkhead` although the sync versions emit identical events.
- `CLAUDE.md` (the AI-agent reference) still annotates `client.py` as AsyncClient-only and labels Protocol Seams `1/2/3` while `engineering.md` uses `A/B/C`.
- `planning/engineering.md` §1 still reads in future tense for shipped work and §8's v0.4 entry still credits `attempt_timeout=` as a v0.4 feature (0.8.0 removed it).

The sweep brings every load-bearing doc statement into alignment with the 0.8.x reality, in a single pass.

## Non-goals

- **No code changes.** Production code under `src/httpware/` is unchanged except for `decoders/__init__.py`'s module docstring (a one-word edit). No tests change.
- **No new content beyond what the audit recommends.** The opening paragraphs are rewritten to be accurate; they are not expanded with new marketing copy, examples, or links. New v0.8.0 entry in `engineering.md` §8 captures only what shipped, not commentary.
- **No CHANGELOG, no migration guide, no version-history page.** The project's docs philosophy ([memory: user_docs_philosophy](../../.claude/projects/-Users-kevinsmith-src-pypi-httpware/memory/user_docs_philosophy.md)) excludes those.
- **No restructuring of `docs/resilience.md` beyond the intro fix.** The body already documents sync `Retry`/`Bulkhead`; only the opening "three primitives" count is wrong.
- **No site-nav changes (mkdocs.yml).** Audit confirmed nav is current.
- **No follow-up sweep deferred.** This pass closes every doc-staleness audit finding flagged in the cross-cutting theme; no nits intentionally skipped.

## Architecture

### Six commits, one per file

Order tuned so the highest-impact reader-facing surfaces land first; AI-agent reference (`CLAUDE.md`) leads because every other doc change refers to the canonical Seam-naming style:

1. **`CLAUDE.md`** — 4 findings + Seam 1/2/3 → A/B/C rename throughout
2. **`README.md`** — 2 findings (opening framing + observability paragraph)
3. **`docs/index.md`** — 2 findings (mirror of README's two)
4. **`docs/resilience.md`** — 1 finding (intro primitive count)
5. **`planning/engineering.md`** — 3 findings (§1 tense, §8 v0.4 line, §8 closing version)
6. **`src/httpware/decoders/__init__.py`** — 1 finding (docstring "Seam 3" → "Seam B")

Each commit message names the audit finding(s) it closes, e.g. `closes Low #L5 / Low #L6 in planning/audit/2026-06-07-deep-audit.md`.

### Why one commit per file

Single-file revert granularity if any change reads wrong on review. Six small commits beat one large one for diff review. Memory note ([user_prefers_clean_cutover_ordering](../../.claude/projects/-Users-kevinsmith-src-pypi-httpware/memory/user_prefers_clean_cutover_ordering.md)) prefers clean per-concern commits.

### Why CLAUDE.md first

Two reasons: (1) the Seam A/B/C rename in CLAUDE.md is the canonical-naming source-of-truth for the `decoders/__init__.py` docstring fix (commit #6), so #6 must follow #1; (2) CLAUDE.md is the AI-agent reference — every agent reading the repo starts there, so reducing its staleness first reduces the chance of further drift during the sweep.

## Per-file change list

### 1. `CLAUDE.md`

Closes Low findings: **opening framing**, **module layout**, **Seam 1 wording**; Nits: **Seam 2 wording**, **testing section sync pattern**.

- **L7 opening:** "A Python async HTTP client framework for building resilient service clients." → "A Python HTTP client framework with sync and async clients for building resilient service clients."
- **L71 module layout** annotation in the Module layout block:
  ```
  ├── client.py                      # AsyncClient (thin wrapper over httpx2.AsyncClient)
  ```
  →
  ```
  ├── client.py                      # AsyncClient + Client (thin wrappers over httpx2.AsyncClient / httpx2.Client)
  ```
- **L83 Protocol Seams renumbering** — the section heading and bullets switch from `1./2./3.` to `**Seam A** / **Seam B** / **Seam C**` matching `engineering.md` §3 style:
  - Seam A: "`Client`/`AsyncClient` ↔ `Middleware`/`AsyncMiddleware`" — body says: "Middleware chain composed at `Client.__init__` and `AsyncClient.__init__`, frozen for the client's lifetime. Internal terminal calls `httpx2.Client.send` or `httpx2.AsyncClient.send`, maps exceptions, raises `StatusError` on 4xx/5xx. Sync and async surfaces are kept at parity."
  - Seam B: "`Client`/`AsyncClient` ↔ `ResponseDecoder`" — body covers both `send` methods.
  - Seam C: "`httpware` ↔ optional extras" — unchanged in content.
- **L91 Testing section** — current line:
  ```
  - Tests inject `httpx2.MockTransport` via `AsyncClient(httpx2_client=httpx2.AsyncClient(transport=mock))`. No `respx`, no `RecordedTransport`.
  ```
  →
  ```
  - Tests inject `httpx2.MockTransport` via `AsyncClient(httpx2_client=httpx2.AsyncClient(transport=mock))` for async or `Client(httpx2_client=httpx2.Client(transport=mock))` for sync. No `respx`, no `RecordedTransport`.
  ```

### 2. `README.md`

Closes Low findings: **opening framing**, **observability paragraph**.

- **L8 opening sentence** (currently `A Python async HTTP client framework for building resilient service clients. ...`) — rewrite to match the new CLAUDE.md opening; the resilience teaser in the same sentence already lists `AsyncRetry` + `RetryBudget`, `AsyncBulkhead` — extend it to "`AsyncRetry`/`Retry` + `RetryBudget`, `AsyncBulkhead`/`Bulkhead`".
- **L~75 "With resilience middleware" code block** — keep the async example as the primary; add a one-line preceding note that the sync `Client` accepts identical `middleware=[...]` and that swapping `AsyncClient` → `Client` and `AsyncRetry` → `Retry` produces the same shape.
- **L116 observability paragraph** — current:
  ```
  `AsyncRetry` and `AsyncBulkhead` emit operational events via two channels — stdlib `logging` records (always on) and OpenTelemetry span events (when `opentelemetry-api` is installed).
  ```
  →
  ```
  `AsyncRetry`/`Retry` and `AsyncBulkhead`/`Bulkhead` emit operational events via two channels — stdlib `logging` records (always on) and OpenTelemetry span events (when `opentelemetry-api` is installed). Event names and payloads are identical across sync and async; dashboards built against one class apply unchanged to the other.
  ```

### 3. `docs/index.md`

Closes Low findings: **opening framing**, **observability paragraph**.

- **L3 opening paragraph** — currently:
  ```
  A Python async HTTP client framework for building resilient service clients. `httpware` is a thin opinionated wrapper around `httpx2` — it re-exports `httpx2.Request`/`httpx2.Response` as the public request/response surface, adds a middleware chain (with a built-in resilience suite: `AsyncRetry` + `RetryBudget`, `AsyncBulkhead`), opt-in typed response decoding, and a status-keyed exception tree raised automatically on 4xx/5xx.
  ```
  →
  ```
  A Python HTTP client framework with sync and async clients for building resilient service clients. `httpware` is a thin opinionated wrapper around `httpx2` — it re-exports `httpx2.Request`/`httpx2.Response` as the public request/response surface, adds a middleware chain (with a built-in resilience suite: `AsyncRetry`/`Retry` + `RetryBudget`, `AsyncBulkhead`/`Bulkhead`), opt-in typed response decoding, and a status-keyed exception tree raised automatically on 4xx/5xx.
  ```
- **L109 observability paragraph** — identical treatment to README L116 above.

### 4. `docs/resilience.md`

Closes Low finding: **"three primitives" intro stale**.

- **L3 intro** — currently:
  ```
  `httpware` ships three resilience primitives under `httpware.middleware.resilience`, all composable through the standard [AsyncMiddleware](middleware.md) chain:

  - **`AsyncRetry`** — automatic retry of transient failures with full-jitter exponential backoff
  - **`RetryBudget`** — Finagle-style token bucket...
  - **`AsyncBulkhead`** — concurrency limiter via `asyncio.Semaphore` with bounded acquire-wait
  ```
  →
  ```
  `httpware` ships these resilience primitives under `httpware.middleware.resilience`, all composable through the standard [Middleware](middleware.md) / [AsyncMiddleware](middleware.md) chain:

  - **`Retry` / `AsyncRetry`** — automatic retry of transient failures with full-jitter exponential backoff
  - **`RetryBudget`** — Finagle-style token bucket; safe to share across sync `Client` and `AsyncClient` in the same process
  - **`Bulkhead` / `AsyncBulkhead`** — concurrency limiter with bounded acquire-wait (`threading.Semaphore` and `asyncio.Semaphore` respectively)
  ```

Grouping sync/async pairs mirrors the layout the rest of the file already uses for the client classes.

### 5. `planning/engineering.md`

Closes Low findings: **§1 future tense**, **§8 `attempt_timeout=` line**; Nit: **§8 closing version stale**.

- **§1 paragraphs 2-3 (L9-11)** — currently:
  ```
  The next release renames the async middleware surface to use the `Async*`/`async_*` prefix (aligning with httpx2's convention) and removes the seldom-used `attempt_timeout=` kwarg from `AsyncRetry` — see `planning/specs/2026-06-07-sync-client-design.md` for the rationale.

  The same release also adds a sync `Client` with full feature parity...
  ```
  → rewrite in past tense, fold into the existing as-of narrative. New wording:
  ```
  As of 0.8.0 the async middleware surface uses the `Async*`/`async_*` prefix (aligning with httpx2's convention); the `attempt_timeout=` kwarg was removed from `AsyncRetry` in the same release — see `planning/specs/2026-06-07-sync-client-design.md` for the rationale.

  0.8.0 also shipped a sync `Client` with full feature parity...
  ```
- **§8 v0.4 entry (L138)** — append parenthetical:
  ```
  **v0.4 slice 1:** `Retry` middleware + Finagle-style `RetryBudget` token bucket + `attempt_timeout=` parameter (folded-in 3-1).
  ```
  →
  ```
  **v0.4 slice 1:** `Retry` middleware + Finagle-style `RetryBudget` token bucket + `attempt_timeout=` parameter (folded-in 3-1; `attempt_timeout=` was removed in 0.8.0 — see v0.8.0 entry below).
  ```
- **§8 new v0.8.0 entry** — insert immediately after the last v0.7.0 entry:
  ```
  **v0.8.0:** sync `Client` with full feature parity (middleware chain, decoder seam, `Retry`, `Bulkhead`, `stream()`); async surface renamed to `Async*`/`async_*` prefix; `attempt_timeout=` removed from `AsyncRetry`. Breaking release for every public async middleware import.
  ```
- **§8 closing paragraph (L148)** — currently:
  ```
  All planned epics are closed as of v0.7.0. The next semver bump is a judgment call...
  ```
  →
  ```
  All planned epics are closed as of v0.8.0. The next semver bump is a judgment call...
  ```

### 6. `src/httpware/decoders/__init__.py`

Closes Nit finding: **docstring "Seam 3" label stale**.

- **L1 module docstring** — currently:
  ```
  """ResponseDecoder protocol — the AsyncClient ↔ ResponseDecoder seam (Seam 3)..."""
  ```
  →
  ```
  """ResponseDecoder protocol — the Client/AsyncClient ↔ ResponseDecoder seam (Seam B)..."""
  ```

If there are peer "Seam 3" references in `chain.py` or `client.py` discovered during the sweep, they get the same treatment; otherwise this is the only line.

## Verification

After each commit:

```bash
grep -nE '<phrase>' <changed-file>
# expected: zero matches
```

Specific per-file greps:

- After commit 1 (`CLAUDE.md`):
  ```bash
  grep -nE 'async HTTP client framework|AsyncClient \(thin wrapper|AsyncClient ↔ Middleware|AsyncClient ↔ ResponseDecoder' CLAUDE.md
  ```
- After commit 2 (`README.md`):
  ```bash
  grep -nE 'async HTTP client framework|AsyncRetry and AsyncBulkhead emit' README.md
  ```
- After commit 3 (`docs/index.md`):
  ```bash
  grep -nE 'async HTTP client framework|AsyncRetry and AsyncBulkhead emit' docs/index.md
  ```
- After commit 4 (`docs/resilience.md`):
  ```bash
  grep -nE 'three resilience primitives' docs/resilience.md
  ```
- After commit 5 (`planning/engineering.md`):
  ```bash
  grep -nE 'next release renames|attempt_timeout= parameter \(folded-in 3-1\)\.$|epics are closed as of v0\.7\.0' planning/engineering.md
  ```
- After commit 6 (`decoders/__init__.py`):
  ```bash
  grep -nE 'Seam 3' src/httpware/decoders/__init__.py src/httpware/middleware/chain.py src/httpware/client.py
  ```

After all 6 commits:

```bash
just lint-ci                    # ruff + ty + eof-fixer all green
grep -nE 'three resilience primitives|next release renames|AsyncRetry and AsyncBulkhead emit|AsyncClient ↔ Middleware|AsyncClient ↔ ResponseDecoder|Seam 3' CLAUDE.md README.md docs/ planning/engineering.md src/httpware/
# expected: zero matches across all 6 files
```

## Risks & mitigations

- **Rewriting the opening paragraphs subtly changes the project's framing** — readers who skim only the first sentence form an impression. Mitigation: the new wording adds "with sync and async clients" — a factual addition, not a positioning shift. No marketing rewrite; only what the audit cited.
- **The Seam 1/2/3 → A/B/C rename in `CLAUDE.md` may surprise readers who memorized the numbering.** Mitigation: `engineering.md` already uses A/B/C; the rename brings the two canonical references into alignment rather than introducing a third style. The decoders docstring fix in commit 6 (the only place a `Seam 3` reference still survives in production code) closes the same gap.
- **The new v0.8.0 entry in `engineering.md` §8 adds prose that wasn't there before.** Mitigation: entry shape matches the existing v0.4-v0.7 entries; content is a one-line summary of what shipped; no commentary or marketing. Locked to the audit's suggested wording.
- **One stale phrase may have been missed by the audit.** Mitigation: the final cross-file grep in Verification catches any verbatim leftover of the known stale phrases.

## Open questions for writing-plans

None deferred. Every change is specified concretely above. The plan will translate the per-file change list into bite-sized verified steps.

## Acceptance criteria

1. All six per-file commits land on `main` with messages naming the audit findings they close.
2. `just lint-ci` is green after every commit and after the final one.
3. The post-sweep grep returns zero matches for every stale phrase listed in Verification.
4. The audit file itself is unchanged by this work — findings stay where they are; future readers can match each commit's message back to the audit by file:line.

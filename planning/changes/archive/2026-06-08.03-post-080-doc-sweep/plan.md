---
status: shipped
date: 2026-06-08
slug: post-080-doc-sweep
spec: post-080-doc-sweep
pr: 34
---

# Post-0.8.0 Doc-Staleness Sweep Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land 6 commits on `main`, one per file, that close every doc-staleness audit finding tracing back to the 0.8.0 release (sync `Client` + `Async*` rename + `attempt_timeout=` removal).

**Architecture:** Sequential file-by-file sweep. Each task reads the current file at the affected lines, applies precise edits whose before/after text is fully specified in the spec, runs a targeted `grep` to confirm the stale phrase is gone, then commits. No code behavior changes. CLAUDE.md leads (canonical Seam-naming source); `decoders/__init__.py` comes last to pick up the Seam A/B/C rename.

**Tech Stack:** Markdown editing, `ruff`/`ty` via `just lint-ci`, `grep` for verification. No runtime code path changes.

---

## Spec reference

The validated spec is at `planning/specs/2026-06-08-post-080-doc-sweep-design.md`. Read its **Per-file change list** section before starting each task — every concrete before/after string this plan uses comes from there. Decisions locked in the spec (not re-debated here): one commit per file, CLAUDE.md first, all 11 findings in scope, Seam renumber 1/2/3 → A/B/C.

## File structure

```
CLAUDE.md                                    # Task 1
README.md                                    # Task 2
docs/index.md                                # Task 3
docs/resilience.md                           # Task 4
planning/engineering.md                      # Task 5
src/httpware/decoders/__init__.py            # Task 6
```

No new files. No file moves. No imports change.

## A note on verification

This plan does **not** use code-style TDD because no behavior changes — every task edits prose or comments. The verification model is instead:

- **Targeted `grep` before the edit** — confirms the stale phrase is present at the cited line.
- **Edit** — apply the exact before/after string from the spec.
- **Targeted `grep` after the edit** — confirms zero matches for the stale phrase.
- **`just lint-ci` after every commit** — catches any markdown rendering or eof-fixer regression.
- **Sweep `grep` after the final commit** (Task 7) — proves no stale phrase survives anywhere.

`just lint-ci` and `grep` are the substitute for unit tests here.

---

## Task 1: `CLAUDE.md`

**Files:**
- Modify: `CLAUDE.md` lines 7, 71, 83, 84, ~85, 91 (and the Protocol Seams numbered list header structure)

Closes audit findings: **module layout (L71)**, **Seam 1 wording (L83)**, **Seam 2 wording (L84, nit)**, **testing section sync pattern (L91, nit)**, plus the L7 opening framing consistency fix.

- [ ] **Step 1: Confirm current state matches the spec**

```bash
grep -nE 'async HTTP client framework|AsyncClient \(thin wrapper|AsyncClient ↔ Middleware|AsyncClient ↔ ResponseDecoder' CLAUDE.md
```

Expected: matches at lines 7, 71, 83, 84 (4 lines).

```bash
sed -n '85,95p' CLAUDE.md
```

Expected: line 91 still reads `- Tests inject \`httpx2.MockTransport\` via \`AsyncClient(httpx2_client=httpx2.AsyncClient(transport=mock))\`. No \`respx\`, no \`RecordedTransport\`.`

- [ ] **Step 2: Rewrite L7 opening sentence**

Replace exactly:

```
`httpware` is a Python async HTTP client framework for building resilient service clients.
```

With:

```
`httpware` is a Python HTTP client framework with sync and async clients for building resilient service clients.
```

- [ ] **Step 3: Update L71 module layout annotation**

Replace exactly:

```
├── client.py                      # AsyncClient (thin wrapper over httpx2.AsyncClient)
```

With:

```
├── client.py                      # AsyncClient + Client (thin wrappers over httpx2.AsyncClient / httpx2.Client)
```

- [ ] **Step 4: Renumber Protocol Seams 1/2/3 → A/B/C and rewrite Seam A + Seam B bodies**

Find the section heading (likely `## Protocol seams` or similar around L80). Renumber the three numbered list items so:

- Old `1. **\`AsyncClient ↔ Middleware\`** — ...` → `**Seam A** — \`Client\`/\`AsyncClient\` ↔ \`Middleware\`/\`AsyncMiddleware\` — middleware chain composed at \`Client.__init__\` and \`AsyncClient.__init__\`, frozen for the client's lifetime. Internal terminal calls \`httpx2.Client.send\` or \`httpx2.AsyncClient.send\`, maps exceptions, raises \`StatusError\` on 4xx/5xx. Sync and async surfaces are kept at parity.`
- Old `2. **\`AsyncClient ↔ ResponseDecoder\`** — ...` → `**Seam B** — \`Client\`/\`AsyncClient\` ↔ \`ResponseDecoder\` — called when \`response_model\` is provided. Signature: \`decode(content: bytes, model: type[T]) -> T\`. Implementations of both \`send\` methods call the decoder identically.`
- Old `3. **\`httpware ↔ optional extras\`** — ...` → `**Seam C** — \`httpware\` ↔ optional extras — each opt-in dependency imported only inside its dedicated module.`

The list markup (whether `1./2./3.` or `-`) should match `engineering.md` §3 style — read engineering.md §3 first to mirror its presentation.

```bash
grep -n -A 1 'Seam A\|Seam B\|Seam C' planning/engineering.md | head -20
```

Use the exact bullet/heading shape that file uses.

- [ ] **Step 5: Update L91 testing section to mention both client classes**

Replace exactly:

```
- Tests inject `httpx2.MockTransport` via `AsyncClient(httpx2_client=httpx2.AsyncClient(transport=mock))`. No `respx`, no `RecordedTransport`.
```

With:

```
- Tests inject `httpx2.MockTransport` via `AsyncClient(httpx2_client=httpx2.AsyncClient(transport=mock))` for async or `Client(httpx2_client=httpx2.Client(transport=mock))` for sync. No `respx`, no `RecordedTransport`.
```

- [ ] **Step 6: Verify all stale phrases gone**

```bash
grep -nE 'async HTTP client framework|AsyncClient \(thin wrapper|AsyncClient ↔ Middleware|AsyncClient ↔ ResponseDecoder' CLAUDE.md
```

Expected: **zero matches.**

```bash
grep -nE 'Seam A|Seam B|Seam C' CLAUDE.md
```

Expected: at least 3 matches (the three Seam headings).

- [ ] **Step 7: Run lint**

```bash
just lint-ci
```

Expected: all green (no code changes, but eof-fixer/markdown formatting can still trip).

- [ ] **Step 8: Commit**

```bash
git add CLAUDE.md
git commit -m "$(cat <<'EOF'
docs(claude-md): post-0.8.0 sweep — sync surface, Seam rename, sync test pattern

Closes audit Low findings (CLAUDE.md:71 module layout, CLAUDE.md:83 Seam 1
wording) and Nit findings (CLAUDE.md:84 Seam 2, CLAUDE.md:91 testing) from
planning/audit/2026-06-07-deep-audit.md. Renumbers Protocol Seams 1/2/3 →
A/B/C to match planning/engineering.md §3 style.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

Expected: clean commit; `git status` shows nothing else pending.

---

## Task 2: `README.md`

**Files:**
- Modify: `README.md` lines 8, ~75, 116

Closes audit Low findings: **L8 opening framing**, **L116 observability paragraph**.

- [ ] **Step 1: Confirm current state**

```bash
grep -nE 'async HTTP client framework|AsyncRetry and AsyncBulkhead emit' README.md
```

Expected: 2 matches (one around L8, one around L116).

```bash
sed -n '70,80p' README.md
```

Find the "With resilience middleware" code block. Note the line.

- [ ] **Step 2: Rewrite L8 opening sentence**

Replace exactly:

```
A Python async HTTP client framework for building resilient service clients.
```

With:

```
A Python HTTP client framework with sync and async clients for building resilient service clients.
```

If the same paragraph contains a resilience teaser like "`AsyncRetry` + `RetryBudget`, `AsyncBulkhead`", extend it to "`AsyncRetry`/`Retry` + `RetryBudget`, `AsyncBulkhead`/`Bulkhead`". Inspect the L8 paragraph after the opening-sentence edit to determine if this extension is present.

- [ ] **Step 3: Add a sync-mirror note to the "With resilience middleware" code block**

The block shows an async example. Add a single sentence directly above the code fence (before the triple-backtick) reading:

```
The sync `Client` accepts identical `middleware=[...]`; swap `AsyncClient` → `Client` and `AsyncRetry` → `Retry` for the sync version.
```

Do NOT duplicate the code block for the sync variant — one example plus the note is enough.

- [ ] **Step 4: Rewrite L116 observability paragraph**

Replace exactly:

```
`AsyncRetry` and `AsyncBulkhead` emit operational events via two channels — stdlib `logging` records (always on) and OpenTelemetry span events (when `opentelemetry-api` is installed).
```

With:

```
`AsyncRetry`/`Retry` and `AsyncBulkhead`/`Bulkhead` emit operational events via two channels — stdlib `logging` records (always on) and OpenTelemetry span events (when `opentelemetry-api` is installed). Event names and payloads are identical across sync and async; dashboards built against one class apply unchanged to the other.
```

- [ ] **Step 5: Verify**

```bash
grep -nE 'async HTTP client framework|AsyncRetry and AsyncBulkhead emit' README.md
```

Expected: **zero matches.**

- [ ] **Step 6: Run lint**

```bash
just lint-ci
```

Expected: green.

- [ ] **Step 7: Commit**

```bash
git add README.md
git commit -m "$(cat <<'EOF'
docs(readme): post-0.8.0 sweep — sync framing + observability paragraph

Closes audit Low findings (README.md:8 async-only framing folded with
docs/index.md:3, README.md:116 observability paragraph) from
planning/audit/2026-06-07-deep-audit.md. Sync Retry/Bulkhead now named in
the observability paragraph; event names/payloads called out as identical
across sync and async.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `docs/index.md`

**Files:**
- Modify: `docs/index.md` lines 3, 109

Closes audit Low findings: **L3 opening paragraph**, **L109 observability paragraph**.

- [ ] **Step 1: Confirm current state**

```bash
grep -nE 'async HTTP client framework|AsyncRetry and AsyncBulkhead emit' docs/index.md
```

Expected: 2 matches.

- [ ] **Step 2: Rewrite L3 opening paragraph**

Replace exactly:

```
A Python async HTTP client framework for building resilient service clients. `httpware` is a thin opinionated wrapper around `httpx2` — it re-exports `httpx2.Request`/`httpx2.Response` as the public request/response surface, adds a middleware chain (with a built-in resilience suite: `AsyncRetry` + `RetryBudget`, `AsyncBulkhead`), opt-in typed response decoding, and a status-keyed exception tree raised automatically on 4xx/5xx.
```

With:

```
A Python HTTP client framework with sync and async clients for building resilient service clients. `httpware` is a thin opinionated wrapper around `httpx2` — it re-exports `httpx2.Request`/`httpx2.Response` as the public request/response surface, adds a middleware chain (with a built-in resilience suite: `AsyncRetry`/`Retry` + `RetryBudget`, `AsyncBulkhead`/`Bulkhead`), opt-in typed response decoding, and a status-keyed exception tree raised automatically on 4xx/5xx.
```

- [ ] **Step 3: Rewrite L109 observability paragraph**

Identical treatment to README L116 (see Task 2 Step 4). Replace the same `AsyncRetry and AsyncBulkhead emit ...` sentence with the same `AsyncRetry/Retry and AsyncBulkhead/Bulkhead emit ...` sentence plus the same "identical across sync and async" note.

- [ ] **Step 4: Verify**

```bash
grep -nE 'async HTTP client framework|AsyncRetry and AsyncBulkhead emit' docs/index.md
```

Expected: **zero matches.**

- [ ] **Step 5: Run lint**

```bash
just lint-ci
```

Expected: green.

- [ ] **Step 6: Commit**

```bash
git add docs/index.md
git commit -m "$(cat <<'EOF'
docs(index): post-0.8.0 sweep — sync framing + observability paragraph

Closes audit Low findings (docs/index.md:3 async-only framing, docs/index.md:109
observability paragraph) from planning/audit/2026-06-07-deep-audit.md.
Mirrors the README treatment landed in the previous commit.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: `docs/resilience.md`

**Files:**
- Modify: `docs/resilience.md` line 3 + the intro bullet list immediately below

Closes audit Low finding: **"three resilience primitives" intro stale**.

- [ ] **Step 1: Confirm current state**

```bash
sed -n '1,12p' docs/resilience.md
```

Expected: opening reads `\`httpware\` ships three resilience primitives under \`httpware.middleware.resilience\`, all composable through the standard [AsyncMiddleware](middleware.md) chain:` followed by three bullets `AsyncRetry`, `RetryBudget`, `AsyncBulkhead`.

- [ ] **Step 2: Rewrite the intro paragraph + bullets**

Replace exactly:

```
`httpware` ships three resilience primitives under `httpware.middleware.resilience`, all composable through the standard [AsyncMiddleware](middleware.md) chain:

- **`AsyncRetry`** — automatic retry of transient failures with full-jitter exponential backoff
- **`RetryBudget`** — Finagle-style token bucket...
- **`AsyncBulkhead`** — concurrency limiter via `asyncio.Semaphore` with bounded acquire-wait
```

(The `RetryBudget` bullet may run longer than `...` shows — read it from the file and preserve the body unchanged.)

With:

```
`httpware` ships these resilience primitives under `httpware.middleware.resilience`, all composable through the standard [Middleware](middleware.md) / [AsyncMiddleware](middleware.md) chain:

- **`Retry` / `AsyncRetry`** — automatic retry of transient failures with full-jitter exponential backoff
- **`RetryBudget`** — Finagle-style token bucket; safe to share across sync `Client` and `AsyncClient` in the same process
- **`Bulkhead` / `AsyncBulkhead`** — concurrency limiter with bounded acquire-wait (`threading.Semaphore` and `asyncio.Semaphore` respectively)
```

Preserve any continuation of the `RetryBudget` body that existed before; replace only the bullet's lead-in if the original had more text.

- [ ] **Step 3: Verify**

```bash
grep -nE 'three resilience primitives' docs/resilience.md
```

Expected: **zero matches.**

```bash
grep -nE '^- \*\*`Retry` / `AsyncRetry`\*\*|^- \*\*`Bulkhead` / `AsyncBulkhead`\*\*' docs/resilience.md
```

Expected: 2 matches (one for each pair bullet).

- [ ] **Step 4: Run lint**

```bash
just lint-ci
```

Expected: green.

- [ ] **Step 5: Commit**

```bash
git add docs/resilience.md
git commit -m "$(cat <<'EOF'
docs(resilience): post-0.8.0 sweep — intro counts five primitives, not three

Closes audit Low finding (docs/resilience.md:3 "three resilience primitives"
stale post-0.8.0) from planning/audit/2026-06-07-deep-audit.md. Pairs the
bullets sync/async to match the layout the rest of the file already uses.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: `planning/engineering.md`

**Files:**
- Modify: `planning/engineering.md` §1 (~L9-L11), §8 v0.4 entry (L138), §8 new v0.8.0 entry (insert after the existing v0.7.0 entry), §8 closing line (L148)

Closes audit Low findings: **§1 future tense**, **§8 v0.4 attempt_timeout= line**; Nit: **§8 closing version**.

- [ ] **Step 1: Confirm current state**

```bash
grep -nE 'next release renames|attempt_timeout= parameter \(folded-in 3-1\)\.$|epics are closed as of v0\.7\.0' planning/engineering.md
```

Expected: 3 matches.

```bash
sed -n '130,150p' planning/engineering.md
```

Read §8's last two existing entries (the v0.6 and v0.7 ones) — the new v0.8.0 entry's tone and shape should mirror them.

- [ ] **Step 2: Rewrite §1 paragraphs 2-3 in past tense**

Replace exactly:

```
The next release renames the async middleware surface to use the `Async*`/`async_*` prefix (aligning with httpx2's convention) and removes the seldom-used `attempt_timeout=` kwarg from `AsyncRetry` — see `planning/specs/2026-06-07-sync-client-design.md` for the rationale.

The same release also adds a sync `Client` with full feature parity
```

With:

```
As of 0.8.0 the async middleware surface uses the `Async*`/`async_*` prefix (aligning with httpx2's convention); the `attempt_timeout=` kwarg was removed from `AsyncRetry` in the same release — see `planning/specs/2026-06-07-sync-client-design.md` for the rationale.

0.8.0 also shipped a sync `Client` with full feature parity
```

- [ ] **Step 3: Append the attempt_timeout parenthetical to the §8 v0.4 entry**

Replace exactly:

```
**v0.4 slice 1:** `Retry` middleware + Finagle-style `RetryBudget` token bucket + `attempt_timeout=` parameter (folded-in 3-1).
```

With:

```
**v0.4 slice 1:** `Retry` middleware + Finagle-style `RetryBudget` token bucket + `attempt_timeout=` parameter (folded-in 3-1; `attempt_timeout=` was removed in 0.8.0 — see v0.8.0 entry below).
```

- [ ] **Step 4: Insert a new v0.8.0 entry immediately after the last v0.7 entry**

Find the last v0.7-numbered entry in §8 (read Step 1's `sed` output to locate it). Insert this line on its own bullet immediately after, before the closing paragraph:

```
**v0.8.0:** sync `Client` with full feature parity (middleware chain, decoder seam, `Retry`, `Bulkhead`, `stream()`); async surface renamed to `Async*`/`async_*` prefix; `attempt_timeout=` removed from `AsyncRetry`. Breaking release for every public async middleware import.
```

Match the existing v0.4-v0.7 entry shape — same `**vX.Y[.Z]:**` lead-in, same prose style.

- [ ] **Step 5: Update the §8 closing version**

Replace exactly:

```
All planned epics are closed as of v0.7.0. The next semver bump is a judgment call
```

With:

```
All planned epics are closed as of v0.8.0. The next semver bump is a judgment call
```

- [ ] **Step 6: Verify**

```bash
grep -nE 'next release renames|attempt_timeout= parameter \(folded-in 3-1\)\.$|epics are closed as of v0\.7\.0' planning/engineering.md
```

Expected: **zero matches** (the v0.4 line's body still contains `attempt_timeout=` but the regex anchors on the now-removed `.$` ending; the closing version line should also have changed).

```bash
grep -nE '\*\*v0\.8\.0:\*\*' planning/engineering.md
```

Expected: 1 match (the new entry).

- [ ] **Step 7: Run lint**

```bash
just lint-ci
```

Expected: green.

- [ ] **Step 8: Commit**

```bash
git add planning/engineering.md
git commit -m "$(cat <<'EOF'
docs(engineering): post-0.8.0 sweep — §1 past tense + §8 v0.8 entry + closing version

Closes audit Low findings (engineering.md:9 §1 future tense, engineering.md:136
§8 v0.4 attempt_timeout= line) and Nit (engineering.md:146 §8 closing v0.7.0)
from planning/audit/2026-06-07-deep-audit.md. Adds a v0.8.0 entry to the
shipped-work log capturing sync Client + Async* rename + attempt_timeout=
removal.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: `src/httpware/decoders/__init__.py`

**Files:**
- Modify: `src/httpware/decoders/__init__.py` line 1

Closes audit Nit finding: **decoders/__init__.py "Seam 3" docstring label stale**.

- [ ] **Step 1: Confirm current state**

```bash
sed -n '1,5p' src/httpware/decoders/__init__.py
```

Expected: line 1 reads `"""ResponseDecoder protocol — the AsyncClient ↔ ResponseDecoder seam (Seam 3)...`.

```bash
grep -nE 'Seam 3' src/httpware/middleware/chain.py src/httpware/client.py
```

Expected: zero matches (audit confirmed this is the only `Seam 3` reference in src/httpware/). If matches surface, treat them as in-scope for this task — apply the same `Seam 3` → `Seam B` rename and `AsyncClient ↔` → `Client/AsyncClient ↔` rewrite where the surrounding context supports it.

- [ ] **Step 2: Rewrite the docstring opening**

Replace exactly:

```
"""ResponseDecoder protocol — the AsyncClient ↔ ResponseDecoder seam (Seam 3)
```

With:

```
"""ResponseDecoder protocol — the Client/AsyncClient ↔ ResponseDecoder seam (Seam B)
```

Preserve the rest of the docstring body unchanged. Read lines 2 onward before editing to confirm what follows.

- [ ] **Step 3: Verify**

```bash
grep -nE 'Seam 3' src/httpware/decoders/__init__.py src/httpware/middleware/chain.py src/httpware/client.py
```

Expected: **zero matches.**

- [ ] **Step 4: Run lint + tests**

This is the only production-code change in the sweep. Run both:

```bash
just lint-ci
```

Expected: green.

```bash
uv run pytest -x --no-cov -q
```

Expected: full test suite passes (the docstring change is non-behavioral, but run for safety).

- [ ] **Step 5: Commit**

```bash
git add src/httpware/decoders/__init__.py
git commit -m "$(cat <<'EOF'
docs(decoders): post-0.8.0 sweep — docstring Seam 3 → Seam B

Closes audit Nit finding (decoders/__init__.py:1 "Seam 3" label stale) from
planning/audit/2026-06-07-deep-audit.md. Aligns with the Seam A/B/C
numbering that CLAUDE.md (commit 1 of this sweep) and engineering.md §3
already use.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Final cross-file verification

**Files:** none modified; verification only.

- [ ] **Step 1: Sweep grep for every stale phrase**

```bash
grep -nE 'three resilience primitives|next release renames|AsyncRetry and AsyncBulkhead emit|AsyncClient ↔ Middleware|AsyncClient ↔ ResponseDecoder|Seam 3|async HTTP client framework|AsyncClient \(thin wrapper|epics are closed as of v0\.7\.0' CLAUDE.md README.md docs/ planning/engineering.md src/httpware/
```

Expected: **zero matches** across every searched file.

- [ ] **Step 2: Run final lint**

```bash
just lint-ci
```

Expected: green.

- [ ] **Step 3: Run full test suite**

```bash
uv run pytest -x --no-cov -q
```

Expected: full test suite passes. The only code change in the sweep is the decoders docstring (Task 6); confirm no regressions.

- [ ] **Step 4: Confirm 6 commits landed in order**

```bash
git log --oneline -7
```

Expected: 6 most-recent commits are the per-file commits from Tasks 1-6, in order, all with messages referencing audit findings.

- [ ] **Step 5: Report completion**

Report to the user: 6 commits ready, every audit doc-staleness finding from the cross-cutting theme is now closed, push when ready.

---

## Self-review notes

- **Spec coverage:** Every change in the spec's "Per-file change list" maps to a task. CLAUDE.md → Task 1; README.md → Task 2; docs/index.md → Task 3; docs/resilience.md → Task 4; planning/engineering.md → Task 5; decoders/__init__.py → Task 6. Verification → Task 7.
- **Placeholder scan:** All before/after strings are verbatim. No "TBD" / "TODO" / "similar to Task N" patterns. Each task's grep commands and expected outputs are concrete.
- **Type/name consistency:** "Seam A/B/C" used consistently from Task 1 (CLAUDE.md introduces them) through Task 6 (decoders picks them up). The `Retry`/`AsyncRetry` and `Bulkhead`/`AsyncBulkhead` pairings are formatted identically in Tasks 2, 3, and 4.
- **Order dependency:** Task 6 depends on Task 1 (decoders docstring uses the Seam-B label CLAUDE.md establishes). Task 7 depends on Tasks 1-6. Tasks 2, 3, 4, 5 are mutually independent and could in principle run in parallel, but the plan executes sequentially to keep the diff stream readable.
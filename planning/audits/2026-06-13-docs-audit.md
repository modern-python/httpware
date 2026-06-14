# httpware documentation audit — 2026-06-13

**Status:** complete
**Scope:** the user-facing documentation surface — `README.md`, the published
mkdocs site (`docs/index.md`, `docs/errors.md`, `docs/middleware.md`,
`docs/resilience.md`, `docs/testing.md`, `docs/recipes/*`, `docs/dev/contributing.md`),
and `mkdocs.yml`. The internal `architecture/` and `planning/` trees were used
as the source-of-truth cross-reference, not themselves audited.
**Method:** four parallel auditors over distinct slices (README+index accuracy,
capability-page accuracy, recipe accuracy, and a cross-corpus readability/UX/navigation
pass). Every concrete code/API claim was verified against the real source in
`src/httpware/`; the modern-di recipe claim was verified against the official
modern-di 2.x migration docs via Context7. The five headline accuracy findings
were reproduced directly against the code before this report was written.

## Summary

- Bugs (false claim / broken copy-paste example): **2**
- Inconsistencies (contradicts code or another doc): **3**
- Readability: **3**
- Onboarding / UX gaps: **6**

**Verdict.** For a developer who already knows what they want, these docs are
strong: the reference pages (`errors.md`, `resilience.md`) are thorough and —
`errors.md` and `testing.md` entirely — accurate down to byte-for-byte hint
strings and payload-field lists; example code is unusually well-commented;
terminology discipline is excellent (always `httpx2`, `AsyncClient`/`Client`,
consistent capability names). The weaknesses cluster in two places: **a
newcomer's first ten minutes** (no "why httpware", a non-resolving first
example, no base-client migration path) and **a maintenance surface that will
silently drift** (README ↔ index.md duplicate ~70% of their prose, including the
full observability contract). Of ~30 checkable claims on the landing pages,
accuracy was near-perfect; the real bugs live in deeper reference prose and the
dev/recipe docs.

## Findings

### Bugs

**B1 — `docs/resilience.md:70` — RetryBudget token-bucket formula is wrong (rounding).**
The doc gives `ceiling = int(len(deposits_in_window) * percent_can_retry) + int(min_retries_per_sec * ttl)`.
The code (`src/httpware/middleware/resilience/budget.py:68`) is
`math.ceil(len(self._deposits) * self._percent_can_retry) + floor`, where
`floor = int(self._min_retries_per_sec * self._ttl)`. The percent term is
`math.ceil`, not `int` — a material difference, not a rounding nitpick. With the
default `percent_can_retry=0.2`: 3 deposits → doc says +0, code yields +1;
11 deposits → doc says +2, code yields +3. Anyone sizing a budget against the
documented formula under-counts permitted retries.
*Fix:* change the percent term to `ceil(...)`; the floor term stays `int(...)`.

**B2 — `docs/recipes/modern-di.md:24,33,99–101` — recipe is broken against current modern-di (2.x).**
The recipe uses `await container.resolve(...)` and `async with Container(scope=…, groups=[…]) as container:`.
Both are modern-di **1.x** shapes. Verified against the modern-di 2.x migration
docs (Context7, `/modern-python/modern-di`): resolution in 2.x is **sync-only**
— "the `await` keywords used for asynchronous resolution in 1.x are removed …
use `container.resolve(SomeType)` directly." The root `Container` is constructed
plainly and torn down with `await container.close_async()`; `async with` is shown
only for `build_child_container(...)`, never the root container. The recipe links
to the live (2.x) docs, so a user copy-pasting today hits `TypeError` on the
`await`. The `inspect.iscoroutinefunction` claim at line 33 is an unverifiable
internal-mechanism detail and should be softened to the observable behaviour.
*Fix:* drop `await` on every `resolve(...)`; construct the root container plainly
and close it in a `try/finally` via `await container.close_async()`; soften the
finalizer-detection sentence.

### Inconsistencies

**I1 — `docs/dev/contributing.md:32` — "enforced by CI grep gates" is false.**
No `grep` runs in any `.github/workflows/` file. CI runs only `just install
lint-ci` (ruff + ty) and `just test`. The `httpx2._` grep described in
`CLAUDE.md`/`architecture/overview.md` as CI-enforced is **not wired into any
workflow** — it is enforced, if at all, by review. (Separately: `CLAUDE.md` and
`architecture/overview.md` both assert these invariants are "CI-enforced / CI
rejects PRs"; that is true for `print()` via ruff `T20` but overstated for the
`httpx2._` and `from __future__` rules. Triage item, not fixed here — see below.)
*Fix:* replace "CI grep gates" with the accurate enforcement (CI lint pass:
ruff + ty; review for the rest).

**I2 — `docs/dev/contributing.md:11` — `just lint` comment omits `eof-fixer`.**
The inline comment reads `# ruff format + ruff check + ty check`; the real target
(`justfile:7–11`) runs four steps — `eof-fixer .`, `ruff format`, `ruff check
--fix`, `ty check`. `CLAUDE.md` lists all four correctly.
*Fix:* add `eof-fixer` to the comment.

**I3 — `docs/middleware.md:104` — stale "stable contracts" list (two of four).**
Names only `httpware.retry` and `httpware.bulkhead` as stable observability
contracts. Since the 0.10.0 circuit-breaker/timeout work, `httpware.circuit_breaker`
and `httpware.timeout` are equally stable — `index.md:153–159` lists all four and
`architecture/resilience.md:23` states their event names "join `retry.*` /
`bulkhead.*` as the stable observability surface; renames are breaking changes."
*Fix:* list all four.

(Also reclassified during audit: **`docs/resilience.md:236`** — the `AsyncTimeout`
parameter table says only "`≤0` raises `ValueError`", but the code
(`timeout.py:47`) and `architecture/resilience.md:17` also reject non-finite
values (`inf`/`nan`). Narrower than both code and the truth home. Fixed with the
batch.)

### Readability

**R1 — dense stacked-qualifier sentences in the hottest spots.** `README.md:31`
(decoder resolution) stacks two qualified clauses; the `respect_retry_after`
cell in `docs/resilience.md:24` is a four-sentence paragraph inside a table cell.
Correct, but hard on first read. **Resolved** (`2026-06-13.05`) — split the
decoder sentence and tightened the table cell.

**R2 — unglossed jargon on first use.** "Finagle-style" (`README.md:17`),
"full-jitter", "bulkhead", "PEP 678 note", "token bucket" — most are defined
later or never, but the README is first contact. **Resolved** (`2026-06-13.05`)
— glossed "Finagle-style `RetryBudget`" (token bucket capping the global retry
rate) and "PEP 678 note" → "an exception note (PEP 678)". ("bulkhead"/"full-jitter"
left as standard resilience vocabulary.)

**R3 — `_LOGGER` used in `errors.md` examples (lines 77, 130, 154) without
definition.** A literal copy-paste hits `NameError`. **Resolved** (`2026-06-13.05`)
— added `import logging` + `_LOGGER = logging.getLogger("myapp")` to the first
block and a one-line note that the examples assume it.

### Onboarding & UX gaps (the larger lane — not bugs)

These are the high-leverage adoption improvements; they require design, not
mechanical edits, and are recorded here for triage rather than fixed in the
accompanying change.

- **G1 — No "why httpware".** Both README and index lead with "thin wrapper over
  httpx2" + a feature list. The actual selling points (typed errors without
  `raise_for_status()`; typed bodies via `response_model=`) are buried mid-page.
  **Resolved** (`2026-06-14.01`) — 3-bullet "Why httpware" block added to the top
  of both README and `docs/index.md`.
- **G2 — No base-client migration guide.** **Won't do** (`2026-06-14.01`) — per
  the maintainer, base-client is scrubbed entirely, not documented; the lone live
  mention (`CLAUDE.md`) was removed and no migration guide is written.
- **G3 — README ↔ index.md ~70% duplicated**, including the entire observability
  contract table — guaranteed to drift on the next logger/event change. **Resolved**
  (`2026-06-14.01`) — README slimmed to a front-door (why + install + one runnable
  quickstart + links); `docs/index.md` is now the single canonical home for the
  full quickstart/resilience/streaming/errors/observability content.
- **G4 — First quickstart hits `https://example.test`**, which resolves to
  nothing — a newcomer's first paste yields `NetworkError`, not data. **Resolved**
  (`2026-06-14.01`) — leading examples (README + `docs/index.md`) now hit
  `jsonplaceholder.typicode.com/users/1`; verified to return a decoded `User` live.
- **G5 — `STATUS_TO_EXCEPTION` is a public `__all__` export
  (`src/httpware/__init__.py:54`) documented nowhere.** The lone undocumented
  public symbol. **Resolved** (`2026-06-13.05`) — documented at the
  status-to-exception table in `docs/errors.md` (public `Mapping[int,
  type[StatusError]]`, importable, fallback rows excluded).
- **G6 — No custom-`ResponseDecoder` guide and no API reference.** The decoder
  seam (Seam B) is a documented extension point but, unlike middleware, gets no
  "write your own" guide; and there is no generated symbol reference
  (mkdocstrings) for constructor/method signatures. *Suggest:* a short Decoders
  guide + minimal mkdocstrings page.

Navigation nits (LOW): mkdocs nav orders Resilience before Middleware though
Resilience is built on it and forward-references it; several `architecture/*.md`
references in published pages are bare paths, not links, so a site reader cannot
follow them. No orphan pages and no broken nav targets — the nav is otherwise clean.
**Resolved** (`2026-06-14.01`) — nav reordered (Middleware before Resilience) and
all five bare `architecture/*.md` references converted to absolute GitHub links.

Only **G6** (custom-`ResponseDecoder` guide; no API reference per maintainer)
remains open after `2026-06-14.01`.

### Verified correct (negative results)

- `README.md` + `docs/index.md`: every import resolves against `__all__`; all
  constructor signatures/params (`base_url`, `decoders`, `response_model`,
  `httpx2_client`, `middleware`, `max_concurrent`), the exception tree, the extras
  (`httpware[pydantic|msgspec|otel|all]` vs `pyproject.toml`), and the behavioural
  claims (auto-raise on 4xx/5xx, `MissingDecoderError` before the HTTP call,
  pydantic-first default, stream bypasses middleware + pre-reads body on error,
  `_emit_event` OTel call) are literally true. Zero bugs.
- `docs/errors.md`: exception tree, `STATUS_TO_EXCEPTION` mapping table, the
  400≤status<600 fallback, the StatusError-single-positional / ClientError-keyword
  `__init__` split, the doubly-inherited `TimeoutError`, every resilience-error
  payload field, and both `MissingDecoderError` hint strings match `errors.py`
  byte-for-byte.
- `docs/resilience.md`: every constructor default verified against source
  (`max_attempts=3`, `base_delay=0.1`, `max_delay=5.0`,
  `retry_status_codes={408,429,502,503,504}`, `failure_threshold=5`,
  `reset_timeout=30.0`, `success_threshold=1`, budget `ttl=10.0`,
  `min_retries_per_sec=10.0`, `percent_can_retry=0.2`, bulkhead `acquire_timeout=1.0`,
  …); 429-as-success, OPEN/HALF_OPEN/CLOSED behaviour, Retry-After parsing/clamping,
  and composition ordering all correct.
- `docs/middleware.md`: protocol definitions, `Next`/`AsyncNext` aliases, the three
  phase-decorator signatures (incl. `on_error` catching `Exception` not
  `BaseException`), and the compose-once-and-frozen claim all match.
- `docs/testing.md`: the `httpx2.MockTransport`-via-`httpx2_client=` pattern matches
  the real tests and `architecture/testing.md`; the "`RecordedTransport` removed"
  reference is correct.
- `docs/recipes/link-header-pagination.md` and `phase-decorator-patterns.md`: every
  API call matches source; both are copy-paste-safe.

## Spawned changes

- **`2026-06-13.04-docs-accuracy-fixes`** (lightweight) — fixes B1, B2, I1, I2, I3,
  and the `AsyncTimeout`-validation wording. All verified against code / official
  upstream docs.
- **`2026-06-13.05-docs-audit-followups`** (lightweight) — the invariant-enforcement
  wording fix (triage item below) plus readability/small-gap findings R1, R2, R3, G5.

## Deferred / triage

- The onboarding & UX gaps **G1, G2, G3, G4, G6** (why-httpware, base-client
  migration, README ↔ index de-dup, runnable quickstart, custom-decoder guide +
  API reference) — a separate, larger docs-UX change that needs design, not
  mechanical edits. Not yet scheduled. (G5 resolved in `2026-06-13.05`.)
- ~~The `httpx2._` invariant is documented as CI-enforced but no CI workflow runs
  the grep.~~ **Resolved (option 2 — fix the claim).** Empirically confirmed against
  the real `ruff --select ALL` ruleset: only `print()` (`T201`) and a *blanket*
  `# type: ignore` (`PGH003`) are machine-checked; the `httpx2._` ban is partial
  (`SLF001` catches private *attribute* access, e.g. `httpx2._foo`, but **not** a
  *used* private import like `from httpx2._internal import x`); the future-import,
  global-logging, and `# ty:`-vs-`# type:` rules are review-only. The blanket
  "(CI-enforced) / CI rejects PRs" heading in `CLAUDE.md` and
  `architecture/overview.md` was rewritten to state the actual enforcement split
  and to note the `httpx2._` grep is a review check, not a CI gate.
  `contributing.md` was already corrected in the `docs-accuracy-fixes` change.

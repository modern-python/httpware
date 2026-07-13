# httpware docs & comments audit — 2026-07-13

**Status:** complete
**Scope:** source-level docstrings/comments (`src/httpware/**/*.py`, 23 files) and
the living documentation surface (`README.md`, `docs/**`, `architecture/**`).
`planning/` was excluded — it is a kept historical record, not living truth,
per the planning convention. This is the first audit to cover source comments
and `architecture/` directly; the 2026-06-13 docs audit covered only the
user-facing `docs/`/README surface and used `architecture/` purely as a
reference.
**Method:** two parallel first-pass agents (one over `src/`, on a cheap model;
one over docs/architecture, on the standard model), each returning a compact
candidate list. Every candidate was then independently re-verified against the
real source before being written up here — several early candidates turned out
correct on inspection and are recorded under Verified correct rather than as
findings.

## Summary

- Stale/inconsistent comments or docstrings: **2** (both in `src/`)
- Cross-doc contradictions: **4** (all in `docs/`/`architecture/`)
- Duplication / compaction candidates: **3**

**Verdict on your compaction/dedup question:** worth doing, but narrowly — the
`src/` comment surface is already lean (the first-pass sweep found zero
comments that just restate obvious code; every comment/docstring earns its
keep). The dedup opportunity is entirely on the docs side, and it's
concentrated: `ResponseTooLargeError`'s behavior is spelled out near-verbatim
in **three** places (D1) and the "why not respx" paragraph in two (D2, tangled
up with the `httpx`/`httpx2` slip in I4) — both good candidates for "full
account in one place, cross-reference from the rest," the same pattern
`architecture/` already uses elsewhere. The `CircuitBreaker` overlap (D3) is a
lower-priority, mostly-intentional tutorial-vs-reference depth split.

## Findings

### Stale/inconsistent (source)

**C1 — `errors.py:184` — `BulkheadFullError` docstring says "AsyncBulkhead" but the error is shared by both bulkheads.**
Docstring: `"Raised when acquire_timeout elapses before an AsyncBulkhead slot becomes available."`
Both `AsyncBulkhead.acquire` (`bulkhead.py:133`) and sync `Bulkhead.acquire`
(`bulkhead.py:175`) raise it via the shared `_emit_bulkhead_rejected` helper
(`bulkhead.py:50-68`) — it is not async-specific.
*Fix:* drop "Async" — `"Raised when acquire_timeout elapses before a bulkhead slot becomes available."`
**Resolved** (`2026-07-13.07`).

**C2 — `client.py:1037` vs `client.py:2009` — `stream()` docstrings disagree on whether the middleware-bypass is version-scoped.**
`AsyncClient.stream()`: `"Bypasses the middleware chain (...) for v1 — see architecture/client.md for the contract."`
`Client.stream()`: `"Bypasses the middleware chain (...) — matches AsyncClient.stream() behavior."` (no "for v1").
`architecture/client.md:23` states the bypass as a permanent design choice ("Both bypass the middleware chain by design"), not a v1-only caveat — so the async docstring's "for v1" doesn't match the truth home either, and the two client docstrings say different things about the same shared behavior.
*Fix:* drop "for v1" from the async docstring (or, if the bypass genuinely is meant to be revisited post-v1, say so in `architecture/client.md` too and mirror the caveat into the sync docstring).
**Resolved** (`2026-07-13.07`) — "for v1" dropped; both client docstrings now agree with `architecture/client.md`.

### Cross-doc contradictions

**I1 — `architecture/errors.md:17` misstates where `DecodeError` wrapping happens.**
`errors.md`: `"The wrap happens at the seam in Client.send / AsyncClient.send — except Exception translates any decoder-side failure into DecodeError(...)."`
Verified against source: the `try/except Exception: raise DecodeError(...)` lives in `_BoundDecoder.decode` (`decoders/_resolver.py:38-43`), called from `client.py` as `bound.decode(response)` — not inline in `send`. `architecture/decoders.md:12` already states this correctly ("Any exception is wrapped by `_BoundDecoder.decode`"). The two truth-home files contradict each other on the same fact.
*Fix:* correct `errors.md:17` to point at `_BoundDecoder.decode` (`decoders/_resolver.py`), matching `decoders.md`.
**Resolved** (`2026-07-13.07`).

**I2 — `docs/dev/contributing.md:28` vs `architecture/conventions.md:24-25` — contradictory docstring requirement.**
`contributing.md`: `"Module docstrings are required; per-method docstrings only when types alone are insufficient."` (conditional)
`conventions.md`: `"Module / class / public-method docstrings are required ..."` (unconditional)
*Fix:* pick one policy and make both files say it — recommend keeping `conventions.md`'s unconditional wording since it's the capability truth home, and updating `contributing.md` to match.
**Resolved** (`2026-07-13.08`) — maintainer ruled unconditional; `contributing.md` now links to `conventions.md` instead of restating.

**I3 — `docs/dev/contributing.md:32-34` understates what CI machine-checks, vs `architecture/overview.md:9`.**
`contributing.md`: `"The CI lint pass (...) catches what the linters can see (e.g. print() via ruff T201); the rest are enforced in code review."` — reads as "only `print()` is machine-checked."
`overview.md`: documents two more checks contributing.md omits — `PGH003` (blanket `# type: ignore`) is machine-checked, and `SLF001` partially checks the `httpx2._` ban (attribute access, not import).
This is a fresh drift, not a re-flag of the 2026-06-13 audit's I1 (that finding was about a since-removed "CI grep gates" phrase, already fixed) — `overview.md`'s finer breakdown was apparently added after `contributing.md`'s wording was last touched.
*Fix:* replace `contributing.md`'s "the rest are enforced in code review" with the same three-tier breakdown `overview.md` uses (machine-checked / partially-checked / review-only), or have it link to `overview.md` instead of restating.
**Resolved** (`2026-07-13.08`) — maintainer ruled link-instead-of-restate, per the repo's truth-home principle.

**I4 — `docs/testing.md:110` says `httpx` where it means `httpx2`.**
`"MockTransport is the public test seam in httpx — supported by the maintainers, stable across versions ... respx patches private internals and has historically broken across httpx major versions."`
Every other reference in the same file (line 3) and in `architecture/testing.md:4` correctly says `httpx2` — a real, separate PyPI package (`httpx2>=2.0.0,<3.0`, maintained by Pydantic Services Inc.), not an alias for the original `httpx`. This line reads as a leftover phrase from before the `httpx2` rename, and as written it inaccurately implies `respx`'s breakage history is about `httpx2` specifically.
*Fix:* change both `httpx` occurrences on that line to `httpx2` (verify against `respx`'s actual `httpx2` support status if this section is touched — it may be that `respx` doesn't support `httpx2` at all, which is a stronger reason to use `MockTransport` than "it breaks across versions").
**Resolved** (`2026-07-13.07`) — both occurrences corrected to `httpx2`; the underlying "does respx support httpx2 at all" question is left as-is, not part of this mechanical fix.

### Duplication / compaction candidates

**D1 — `ResponseTooLargeError` behavior is spelled out near-verbatim in three files.**
`docs/errors.md:193-204`, `architecture/errors.md:23`, and `architecture/client.md:36` all restate the same handful of facts (status-agnostic, counts decoded bytes, fires from the non-streaming terminal and `stream()`'s error pre-read but not user-driven iteration, the `"declared"`/`"streamed"` reason split, "neither StatusError, NetworkError, nor TimeoutError — not retried, doesn't count toward the circuit breaker") in matching or near-matching phrasing. `docs/errors.md` has the fullest account.
*Suggest:* keep the full account in `docs/errors.md` (or `architecture/errors.md`, whichever is meant to be canonical for this fact), compress the other two to a one-line cross-reference.

**D2 — "why not respx" is duplicated between `docs/testing.md:108-110` and `architecture/testing.md:4`.**
Same argument, ~3 near-identical sentences in each. Bundle this cleanup with the I4 fix (same lines) — reconcile the `httpx`/`httpx2` wording and de-duplicate the reasoning in the same edit, keeping the fuller version in one file.

**D3 — `CircuitBreaker` states/failure-classification/rate-mode overlap between `docs/resilience.md:158-212` and `architecture/resilience.md:17,21`.** Lower priority: this is mostly a legitimate tutorial-vs-compressed-reference depth split, not verbatim duplication, but several exact clauses ("4xx including 429 count as successes," the `window_seconds=30.0`/`minimum_calls=20` defaults) are copied rather than merely covering the same ground. Worth a light pass if `resilience.md` is next revised for another reason — not worth a dedicated change on its own.

## Verified correct (negative results)

- **`src/` comment/docstring redundancy:** zero comments found that merely restate what well-named code already makes obvious — every inline comment explains a non-obvious constraint or invariant (e.g. wire-body header stripping, coverage pragmas, semaphore behavior).
- **README ↔ `docs/index.md` duplication (regression check):** the ~70% prose duplication fixed in change `2026-06-14.01` has **not** crept back. The only verbatim overlap remaining is short, non-prose boilerplate (the Pre-1.0 status line, the "Part of `modern-python`" footer) — not the capability-description duplication the prior fix targeted. The install-extras blocks differ in *coverage* (README documents the `[all]` extra, `docs/index.md` doesn't) rather than in duplicated content.
- Terminology elsewhere (`AsyncMiddleware`/`Middleware`, `AsyncNext`/`Next`, "terminal", "Seam A/B/C", phase-decorator names) is used consistently across every file checked — I4 is an isolated slip, not a pattern.

## Spawned changes

- **`2026-07-13.07-docs-comments-audit-fixes`** (lightweight) — fixes C1, C2,
  I1, I4. Verified against source; `just lint-ci`, `mkdocs build --strict`,
  and `just test` (780 passed, 100% coverage) all clean.
- **`2026-07-13.08-contributing-docstring-ci-wording`** (lightweight) — fixes
  I2, I3 per maintainer ruling (unconditional docstrings; link instead of
  restate). Verified: `mkdocs build --strict`, `just lint-ci` clean.

## Deferred / next steps

- **Compaction:** D1 (`ResponseTooLargeError` triplication) and D2 (bundled
  with I4's `httpx`/`httpx2` fix — the "why not respx" duplication itself
  wasn't touched by `2026-07-13.07`, only the terminology slip within it) are
  still open. D3 is a defer-until-touched item, not worth its own change.

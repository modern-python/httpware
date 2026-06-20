---
status: shipped
date: 2026-06-05
slug: docs-sync-0.4
summary: 0.4 docs sync
supersedes: null
superseded_by: null
pr: 25
outcome: '0.4 docs sync'
---

# Spec: User-docs freshness pass for 0.4 (Epic 3 story 3-6)

**Date:** 2026-06-05
**Topic slug:** `docs-sync-0.4`
**Status:** drafted, awaiting user review
**Target release:** 0.4.0 (lands BEFORE the 0.4.0 tag/release so the published docs match the published features)
**Epic 3 stories rolled in:** 3-6 (reframed from "extension-slot docs" to "sync user docs with shipped features").

## Purpose

Bring the live user-facing docs in sync with what's actually shipped on `main` (Retry, RetryBudget, Bulkhead, NetworkError, BulkheadFullError, RetryBudgetExhaustedError). The README, `docs/index.md`, and `docs/dev/contributing.md` all describe pre-pivot or pre-0.4 reality. `planning/engineering.md` is missing the resilience module layout. `mkdocs.yml` has a dead nav entry pointing to a file that doesn't exist. Fix all five in one PR, then cut the 0.4.0 release in a follow-up PR.

This is the closing story of Epic 3. The original framing ("document the extension slot for custom resilience policies") was re-scoped at brainstorming time — the user clarified that going forward docs will be written alongside features, but right now there's a 0.3→0.4 sync backlog that needs paying down first. A custom-middleware tutorial may follow as separate work.

## Non-goals

- **No tutorial / "write your own middleware" walkthrough.** Out of scope; possibly a future docs PR.
- **No move of `planning/engineering.md` → `docs/dev/engineering.md`.** The dead link in `docs/index.md` is fixed by pointing to the GitHub URL of the existing file. Restructuring the docs tree is a separate decision that touches CLAUDE.md's path reference.
- **No version bump in `pyproject.toml`.** Lives in the next PR (release prep).
- **No new `docs/` files.** Just edits to existing ones (incl. `mkdocs.yml`).
- **No CLAUDE.md changes.** Contributor-facing, not user-facing.
- **No module-docstring rewrites.** Retry/Bulkhead/RetryBudget docstrings are recent and reviewed; no factual drift to correct.

## File-by-file changes

### `README.md`

1. **Status line (~L12):**
   - Current: `> **Status:** Pre-1.0 (0.3.0). Public API is subject to change between minor releases until v1.0. Resilience middleware (retry / timeout / bulkhead), streaming, and observability are not yet shipped.`
   - New: `> **Status:** Pre-1.0. Public API is subject to change between minor releases until v1.0. Streaming and observability are not yet shipped.`
   - Why: drop the version number (pyproject is the source of truth); drop the now-false "retry / bulkhead not yet shipped" claim.

2. **Project description (L9):**
   - Append one sentence: `It also ships a small resilience suite — \`Retry\` middleware with a Finagle-style \`RetryBudget\`, plus a \`Bulkhead\` concurrency limiter — under \`httpware.middleware.resilience\`.`

3. **Quickstart section:**
   - Add a second code block after the existing one, showing recommended middleware composition:
     ```python
     from httpware import AsyncClient, Bulkhead, Retry

     async with AsyncClient(
         base_url="https://api.example.com",
         middleware=[
             Bulkhead(max_concurrent=10),  # cap total in-flight
             Retry(),                      # default: 3 attempts, full-jitter backoff
         ],
     ) as client:
         user = await client.get("/users/1", response_model=User)
     ```
   - Add one sentence above the snippet: "Compose resilience middleware at construction; `Bulkhead` goes outside `Retry` so one slot covers all retry attempts."

4. **New "Errors" section** after Quickstart (before the Documentation link):
   ```markdown
   ## Errors

   All 4xx/5xx responses raise typed exceptions automatically: `NotFoundError`, `ServiceUnavailableError`, `RateLimitedError`, etc. — all subclasses of `httpware.StatusError`. Transport-layer transient failures raise `NetworkError`; the resilience middleware raise `RetryBudgetExhaustedError` and `BulkheadFullError`. Everything inherits `httpware.ClientError`.
   ```

5. **Dead link (L45):**
   - Current: `## 📚 [Documentation](https://httpware.readthedocs.io)`
   - New: `## 📝 [Release notes](https://github.com/modern-python/httpware/releases)`
   - Why: no RTD site exists; the GH Releases page has the curated per-version notes (auto-generated from `planning/releases/`).

### `docs/index.md`

1. **Status line:**
   - Current: `> **Status:** Pre-1.0 (0.1.0 alpha). Public API is subject to change between minor releases until v1.0.`
   - New: `> **Status:** Pre-1.0. Public API is subject to change between minor releases until v1.0. Streaming and observability are not yet shipped.`

2. **Project description paragraph (top of file):**
   - Current: `A Python async HTTP client framework for building resilient service clients. \`httpware\` owns the abstraction layer above the underlying HTTP client (\`httpx2\` by default); consumers never import the transport directly.`
   - New: `A Python async HTTP client framework for building resilient service clients. \`httpware\` is a thin opinionated wrapper around \`httpx2\` — it re-exports \`httpx2.Request\`/\`httpx2.Response\` as the public request/response surface, adds a middleware chain (with a built-in resilience suite: \`Retry\` + \`RetryBudget\`, \`Bulkhead\`), opt-in typed response decoding, and a status-keyed exception tree raised automatically on 4xx/5xx.`
   - Why: the pre-pivot wording was retired in v0.2 (engineering.md §1: *"v0.2 walks that back: httpx2 is part of the public surface"*). Continuing to claim "consumers never import the transport directly" actively misleads.

3. **Optional extras block:** add `pip install httpware[pydantic]    # PydanticDecoder (the default decoder path)` above the `[msgspec]` line. (Currently shows only msgspec — predates 0.3 pydantic-as-extra.)

4. **First request snippet:** keep as-is (still accurate). Add a second snippet matching the README's Retry+Bulkhead one, with the same one-sentence intro.

5. **"Where to go next" section:**
   - The `[Engineering Notes](dev/engineering.md)` link is dead (`dev/engineering.md` doesn't exist; the live file lives at `planning/engineering.md` in the repo root).
   - Fix: change the link to `https://github.com/modern-python/httpware/blob/main/planning/engineering.md`. Rationale for using an absolute GH URL rather than a relative one: mkdocs renders only files under `docs/`, so a relative `../planning/engineering.md` wouldn't resolve in the rendered site. GH URL works in both rendered docs and raw markdown view.
   - Also add: `- **[Release notes](https://github.com/modern-python/httpware/releases)** — per-version changelogs.`

6. **Add an "Errors" section** mirroring the README's (same content, same position relative to Quickstart).

### `docs/dev/contributing.md`

1. **Line 34** (in the "Architecture invariants" list):
   - Current: `- No \`import httpx2\` outside \`src/httpware/transports/httpx2.py\`.`
   - Action: **delete this line**.
   - Why: invariant retired in v0.2 (engineering.md §2: *"The 0.1.0 'no httpx2 leakage outside transports/httpx2.py' invariant is retired in v0.2."*). The `transports/` directory doesn't exist anymore. Teaching contributors this rule actively confuses.

2. **Add one new invariant** to the same list (after the existing items, before "Code of Conduct"):
   - `- Type suppressions use \`# ty: ignore[<rule>]\`, never \`# type: ignore\` or \`# mypy: ignore\`.`
   - Why: this IS a current CI-enforced invariant (engineering.md §2 / CLAUDE.md "Architecture invariants"). It's already mentioned in the "Code style" section above but absent from the "Architecture invariants" enforcement list. Add for completeness with the others.

3. **No other changes.** Quick-start block, branch-naming rules, etc. are still accurate.

### `mkdocs.yml`

The `nav:` block currently references `dev/engineering.md`:

```yaml
nav:
  - Quick-Start: index.md
  - Development:
      - Engineering Notes: dev/engineering.md
      - Contributing: dev/contributing.md
```

That file doesn't exist (the live engineering reference lives at `planning/engineering.md`). `mkdocs serve` emits a "file referenced in nav not found" warning. Two valid fixes were considered:

- **(rejected)** Move `planning/engineering.md` → `docs/dev/engineering.md`. Would consolidate the design reference into the docs site but breaks CLAUDE.md path references and pulls in scope creep. User explicitly excluded this option in brainstorming.
- **(chosen)** Drop the dead nav entry. Smallest fix; the design reference stays in `planning/`. Users find it via the GH URL added to `docs/index.md`'s "Where to go next" section.

Change:
```yaml
nav:
  - Quick-Start: index.md
  - Development:
      - Contributing: dev/contributing.md
```

The `site_url: https://httpware.readthedocs.io/` is left untouched. No RTD site is currently deployed; the URL is fictional. Fixing that is project-tree hygiene unrelated to this PR (separate decision: do we want GH Pages? do we want an actual RTD deployment? out of scope here).

### `planning/engineering.md`

1. **§1 Project intent:**
   - Append one sentence to the first paragraph: `As of 0.4.0, the package ships a small resilience suite under \`httpware.middleware.resilience\` — a \`Retry\` middleware with a Finagle-style \`RetryBudget\`, plus a \`Bulkhead\` concurrency limiter — composed via the standard middleware chain.`

2. **§5 Module layout:**
   - Current tree omits `middleware/resilience/` entirely; the `_internal/` block shows only `import_checker.py` (which is correct — that's the sole file there).
   - New tree adds the resilience subpackage:
     ```text
     src/httpware/
     ├── __init__.py            # public exports
     ├── py.typed
     ├── client.py              # AsyncClient
     ├── errors.py              # status-keyed exception tree + NetworkError + RetryBudgetExhaustedError + BulkheadFullError
     ├── middleware/
     │   ├── __init__.py        # Middleware protocol, Next type, @before_request/@after_response/@on_error
     │   ├── chain.py           # compose(middleware, terminal) -> Next
     │   └── resilience/
     │       ├── __init__.py    # re-exports Bulkhead, Retry, RetryBudget
     │       ├── bulkhead.py    # Bulkhead middleware (concurrency limiter)
     │       ├── budget.py      # RetryBudget (Finagle-style token bucket)
     │       ├── retry.py       # Retry middleware
     │       └── _backoff.py    # full-jitter exponential backoff helper (private)
     ├── decoders/
     │   ├── __init__.py        # ResponseDecoder protocol
     │   ├── pydantic.py        # PydanticDecoder (extra: pydantic)
     │   └── msgspec.py         # MsgspecDecoder (extra: msgspec)
     └── _internal/
         └── import_checker.py  # is_msgspec_installed, is_pydantic_installed
     ```
   - Also update `errors.py` line to mention the new exception subclasses (`NetworkError`, `RetryBudgetExhaustedError`, `BulkheadFullError`).

## Verification

- Render `mkdocs serve` locally and visually confirm:
  - `docs/index.md` renders with the corrected status, description, and the new "Errors" section
  - The "Where to go next" links all resolve (the GH absolute URLs work in both the rendered site and raw GH view)
- Confirm `just lint` still passes (no Python/source changes, so this is mostly a no-op; eof-fixer might touch the markdown files).
- No tests change (this is a docs-only PR). Existing test suite continues to pass at 100% coverage.
- Confirm CI doesn't break: the `docs/requirements.txt` declares mkdocs deps; if there's a docs-build workflow it should still pass.

## Out of scope reminder

After this PR ships, the next PR is **0.4.0 release prep**: bump `pyproject.toml` version `0.3.0 → 0.4.0`, tag the commit, create GitHub Release from `planning/releases/0.4.0.md`, push tag to trigger PyPI publish.

## References

- `planning/engineering.md` §1, §2 (architecture invariants), §5 (module layout)
- `planning/releases/0.4.0.md` (the canonical description of what shipped — the README/index.md "errors" + "resilience" wording should be consistent with this)
- `CLAUDE.md` "Where to find what" section (defines the relationship between README, docs/, planning/)

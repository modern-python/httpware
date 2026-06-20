---
status: shipped
date: 2026-06-05
slug: extension-slot-docs
spec: extension-slot-docs
pr: 28
---

# Extension-slot docs (0.7.0, Epic 3 story 3-6) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `docs/middleware.md` — a user-facing guide to writing custom middleware against `httpware`'s Middleware protocol — plus the four small touchups that hang off it (mkdocs nav, README pointer, docs/index pointer, engineering.md §8 SHIPPED line) and 0.7.0 release notes. Closes Epic 3.

**Architecture:** Docs-only PR. One new markdown page (~150 lines), four small textual edits to existing files, one new release-notes file. No source code changes. Verification is `mkdocs build --strict` + link resolution + the existing test/lint suites as no-op confirmation.

**Tech Stack:** Markdown, mkdocs-material (strict build), no source code.

**Target branch:** `feat/v0.7-middleware-docs`. Create from `main` before Task 1: `git checkout main && git pull && git checkout -b feat/v0.7-middleware-docs`.

**Source spec:** [`planning/specs/2026-06-05-extension-slot-docs-design.md`](../specs/2026-06-05-extension-slot-docs-design.md). Read the spec's "Background" + "Deliverable" sections before starting — the *why* for non-resilience example choice and Seam-A-only scope lives there.

---

## File structure

**New files:**
- `docs/middleware.md` — the guide itself (~150 lines)
- `planning/releases/0.7.0.md` — release notes

**Modified files:**
- `mkdocs.yml` — add nav entry between Quick-Start and Development
- `README.md` — one-sentence pointer in the existing "With resilience middleware" subsection
- `docs/index.md` — one bullet in the existing "Where to go next" section
- `planning/engineering.md` §8 — replace the "**Remaining:** `3-6` extension-slot docs." line under Epic 3

**Commit cadence:** one commit per task. Per-task commits keep history reviewable.

---

## Task 1: Branch + create `docs/middleware.md`

**Files:**
- Create: `docs/middleware.md`

- [ ] **Step 1: Create the branch**

```bash
git checkout main && git pull && git checkout -b feat/v0.7-middleware-docs
```
Expected: switched to a new branch.

- [ ] **Step 2: Create `docs/middleware.md` with the full content below**

````markdown
# Writing custom middleware

`httpware`'s primary extension point is the **Middleware protocol**. Middleware lets you add cross-cutting behavior — request-ID propagation, auth header injection, structured tracing, custom resilience policies, anything that wraps "send a request, get a response" — without subclassing `AsyncClient` or touching the transport.

The built-in `Retry` and `Bulkhead` middleware are themselves implementations of this protocol; nothing about them is privileged. If you want a circuit breaker, a rate limiter, or a header-injecting auth layer, write a middleware. If your need is per-call (not cross-cutting), pass it through `request.extensions=` instead.

## The protocol

Two symbols, both exported from `httpware.middleware`:

```python
from collections.abc import Awaitable, Callable
from typing import Protocol, TypeAlias, runtime_checkable
import httpx2

Next: TypeAlias = Callable[[httpx2.Request], Awaitable[httpx2.Response]]


@runtime_checkable
class Middleware(Protocol):
    async def __call__(self, request: httpx2.Request, next: Next) -> httpx2.Response: ...
```

The chain is composed once at `AsyncClient.__init__` and frozen for the client's lifetime. The first entry in `middleware=[...]` is the outermost layer: when you write `middleware=[Bulkhead(...), Retry()]`, the bulkhead sees every request before the retry layer does, so one slot covers all retry attempts of the same call.

Calling `await next(request)` forwards to the next layer (or, eventually, to the terminal that hits `httpx2`). You can:

- **Forward unchanged:** `return await next(request)`
- **Modify the request first:** mutate `request.headers` (or build a replacement) before forwarding
- **Inspect or replace the response:** call `await next(...)`, then act on what comes back
- **Short-circuit:** return a synthesized `httpx2.Response` without calling `next` at all
- **Wrap the call in error handling:** `try: return await next(...) except ...` to translate failures

Whatever you do, return an `httpx2.Response`. Raising an exception propagates up the chain (Retry catches retryable exceptions; everything else surfaces to the caller).

## Phase decorators

For the common cases where you don't need state-keeping on `self` and don't need to wrap the full `await next(...)` call, `httpware.middleware` exports three decorators that turn a single async function into a `Middleware`:

```python
from httpware.middleware import before_request, after_response, on_error
```

| Decorator | Function signature | When to use |
|---|---|---|
| `@before_request` | `async (request) -> request` | Transform the outgoing request (add a header, rewrite a URL). |
| `@after_response` | `async (request, response) -> response` | Transform the incoming response (decode, log, attach metadata). |
| `@on_error` | `async (request, exc) -> response \| None` | Translate or absorb a failure. Return `None` to re-raise. Catches `Exception` (not `BaseException`), so `asyncio.CancelledError` propagates. |

Brief example — adding an `Authorization` header before every request:

```python
import httpx2

from httpware import AsyncClient
from httpware.middleware import before_request


@before_request
async def add_bearer(request: httpx2.Request) -> httpx2.Request:
    request.headers["Authorization"] = "Bearer secret-token"
    return request


async def main() -> None:
    async with AsyncClient(base_url="https://api.example.com", middleware=[add_bearer]) as client:
        await client.get("/me")
```

**Reach for the raw `Middleware` protocol when:** you need instance state (a counter, a CircuitBreaker's open/closed flag), you need to inspect both the request AND its response (e.g., timing), or you need to interleave behavior around the `await next(...)` call (e.g., emit one log line at the start and one at the end). The decorators are a convenience for the cases where a single function suffices.

## Worked example: request-ID propagation

A `RequestIdMiddleware` that assigns a per-call UUID, injects it as an outgoing header, and logs it alongside the response status. This is the canonical "trace every request through your distributed system" pattern.

```python
import logging
import uuid

import httpx2

from httpware import AsyncClient, Retry
from httpware.middleware import Next


_LOGGER = logging.getLogger("myapp.request_id")


class RequestIdMiddleware:
    """Assign a per-call X-Request-Id; log it on response.

    Place OUTSIDE Retry so all attempts of the same call share one ID
    (so a single call's retries all surface under the same correlation
    key in your logs, and match the URL attribute on httpware.retry's
    emitted events).
    """

    def __init__(self, *, header: str = "X-Request-Id") -> None:
        self._header = header

    async def __call__(self, request: httpx2.Request, next: Next) -> httpx2.Response:  # noqa: A002
        request_id = str(uuid.uuid4())
        request.headers[self._header] = request_id
        response = await next(request)
        _LOGGER.info(
            "request complete",
            extra={"request_id": request_id, "status": response.status_code},
        )
        return response


async def main() -> None:
    async with AsyncClient(
        base_url="https://api.example.com",
        middleware=[RequestIdMiddleware(), Retry()],  # ID outside Retry
    ) as client:
        await client.get("/users/1")
```

A note on logger names: the example logs under `myapp.request_id`, NOT under `httpware.*`. The `httpware.*` namespace is reserved for events emitted by the library itself (see [Observability](index.md#observability) — `httpware.retry` and `httpware.bulkhead` are stable contracts). Consumer middleware should use your application's own logger namespace.

The example pairs naturally with the 0.6.0 observability events: a `httpware.retry` `retry.giving_up` log record carries a `url` attribute, and your `RequestIdMiddleware` set an `X-Request-Id` for that same call. Correlate the two in your log aggregator and you have end-to-end visibility from "this user's request" to "we gave up after N retries."

## When NOT to write a middleware

- **Redaction:** Use a `logging.Filter` on the consumer side. `httpware` deliberately does no redaction in-library (per the 0.6.0 observability design).
- **URL or header validation:** `httpx2` owns it. Don't reimplement.
- **Per-call behavior that doesn't apply to other calls:** Pass through `request.extensions=` (or the `extensions=` kwarg at the call site) instead. Middleware exists for *cross-cutting* concerns.
- **HTTP-level span creation for tracing:** Install `opentelemetry-instrumentation-httpx` instead of writing an OTel middleware in httpware. We retired story `5-4` (standalone OTel middleware) for this reason — `opentelemetry-instrumentation-httpx` already covers transport-level tracing, and a separate httpware layer would duplicate it. See `planning/engineering.md` §8.

## See also

- **`planning/engineering.md` §3 (Seam A)** — the formal protocol contract and why the chain is frozen at construction.
- **`src/httpware/middleware/resilience/`** — `Retry`, `Bulkhead`, `RetryBudget` as real-world consumers of this exact protocol.
- **[Quick-Start composition example](index.md#with-resilience-middleware)** — composing built-in middleware.
````

- [ ] **Step 3: Commit**

```bash
git add docs/middleware.md
git commit -m "docs(middleware): write custom-middleware guide (3-6)

New docs/middleware.md covering:
- The Middleware Protocol + Next type, exported from httpware.middleware
- Phase decorators (@before_request, @after_response, @on_error) as
  ergonomic shortcuts for the no-state-keeping cases
- Worked example: a RequestIdMiddleware that assigns a per-call UUID
  via X-Request-Id and logs it alongside the response status. Placed
  outside Retry on purpose so all attempts of the same call share one
  ID and correlate with the 0.6.0 observability events' url attribute
- 'When NOT to write a middleware' section covering redaction (use a
  logging.Filter), URL/header validation (httpx2 owns it), per-call
  behavior (use request.extensions=), and HTTP-tracing (install
  opentelemetry-instrumentation-httpx instead)

Closes the deferred-tutorial half of story 3-6. See spec at
planning/specs/2026-06-05-extension-slot-docs-design.md."
```

---

## Task 2: Add nav entry to `mkdocs.yml` + verify strict build

**Files:**
- Modify: `mkdocs.yml`

- [ ] **Step 1: Add nav entry**

The current `nav:` block reads:
```yaml
nav:
  - Quick-Start: index.md
  - Development:
      - Contributing: dev/contributing.md
```

Change to:
```yaml
nav:
  - Quick-Start: index.md
  - Middleware: middleware.md
  - Development:
      - Contributing: dev/contributing.md
```

- [ ] **Step 2: Verify mkdocs strict build is clean**

```bash
uv run --with mkdocs --with mkdocs-material mkdocs build --strict 2>&1 | tail -20
```
Expected: `Documentation built in <time>` with no warnings about missing files, broken links, or unrecognized cross-references. Strict mode treats warnings as errors.

The new page links to `index.md#with-resilience-middleware`, `index.md#observability`, and uses the path `planning/engineering.md` (the latter is a repo path, not a docs path — mkdocs won't try to resolve it as an internal anchor, which is the intent).

If strict build complains about anchors, the failure mode is usually: header text in `docs/index.md` doesn't slug-to what we expected. The auto-generated slugs are:
- "## With resilience middleware" → `#with-resilience-middleware`
- "## Observability" → `#observability`

Both exist verbatim in the current `docs/index.md`.

- [ ] **Step 3: Clean up the local site/ directory and commit**

```bash
rm -rf site/
git add mkdocs.yml
git commit -m "docs(nav): add Middleware page to mkdocs nav (3-6)

Inserts between Quick-Start and Development. The page itself (added
in the prior commit) is reachable from the Quick-Start's resilience
section and the README; this nav slot is for users browsing the
docs site directly."
```

---

## Task 3: README.md pointer

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Append a pointer sentence to the existing "With resilience middleware" subsection**

The current subsection (around L45-L62) ends with the resilience code block. Append a one-sentence pointer immediately after the closing triple-backtick of that code block (so it sits above the next subsection `### Streaming responses`).

Find:
```markdown
    ) as client:
        user = await client.get("/users/1", response_model=User)
```
```

(The trailing ``` is the end of the code fence.)

Add ONE blank line, then this sentence, then another blank line before `### Streaming responses`:

```markdown
Need a custom middleware (auth, tracing, request-ID propagation, etc.)? See the [Middleware guide](docs/middleware.md).
```

So the surrounding context becomes:
```markdown
    ) as client:
        user = await client.get("/users/1", response_model=User)
```

Need a custom middleware (auth, tracing, request-ID propagation, etc.)? See the [Middleware guide](docs/middleware.md).

### Streaming responses
```

- [ ] **Step 2: Verify the link works locally**

The README is rendered on GitHub. A relative link `docs/middleware.md` from a repo-root README resolves to `<repo>/blob/main/docs/middleware.md` automatically. Visual-check by opening README.md in any markdown previewer and confirming the link clicks through.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs(readme): link to new Middleware guide (3-6)

One-sentence pointer in the existing 'With resilience middleware'
subsection. Surfaces the new guide for users skimming the README who
want to write their own middleware."
```

---

## Task 4: docs/index.md pointer

**Files:**
- Modify: `docs/index.md`

- [ ] **Step 1: Add a bullet to the existing "Where to go next" section**

The current section (around L107-L111) reads:
```markdown
## Where to go next

- **[Engineering Notes](https://github.com/modern-python/httpware/blob/main/planning/engineering.md)** — design invariants, the three protocol seams, exception contract, module layout, testing patterns, optional-extras pattern. Lives in the repo at `planning/engineering.md`.
- **[Contributing](dev/contributing.md)** — setup, conventions, workflow.
- **[Release notes](https://github.com/modern-python/httpware/releases)** — per-version changelogs.
```

Insert a new bullet as the FIRST bullet in that list (above Engineering Notes), since the Middleware guide is the most user-facing of the four entries:

```markdown
- **[Middleware guide](middleware.md)** — write your own middleware. Covers the Middleware Protocol, the phase decorators, and a worked Request-ID propagation example.
```

So the section becomes:
```markdown
## Where to go next

- **[Middleware guide](middleware.md)** — write your own middleware. Covers the Middleware Protocol, the phase decorators, and a worked Request-ID propagation example.
- **[Engineering Notes](https://github.com/modern-python/httpware/blob/main/planning/engineering.md)** — design invariants, the three protocol seams, exception contract, module layout, testing patterns, optional-extras pattern. Lives in the repo at `planning/engineering.md`.
- **[Contributing](dev/contributing.md)** — setup, conventions, workflow.
- **[Release notes](https://github.com/modern-python/httpware/releases)** — per-version changelogs.
```

- [ ] **Step 2: Verify mkdocs strict build still clean**

```bash
uv run --with mkdocs --with mkdocs-material mkdocs build --strict 2>&1 | tail -10
rm -rf site/
```
Expected: still clean (the `middleware.md` link resolves now that Task 2 added it to nav).

- [ ] **Step 3: Commit**

```bash
git add docs/index.md
git commit -m "docs(index): link to Middleware guide from Where-to-go-next (3-6)

Adds the guide as the first bullet — most user-facing of the four
entries in that section."
```

---

## Task 5: `planning/engineering.md` §8 — mark 3-6 SHIPPED

**Files:**
- Modify: `planning/engineering.md`

- [ ] **Step 1: Replace the Epic 3 Remaining line**

The current Epic 3 block in §8 (around L131-L134) reads:
```markdown
- **Epic 3 — Resilience:**
  - **Shipped in v0.4 slice 1:** `Retry` middleware + Finagle-style `RetryBudget` token bucket + `attempt_timeout=` parameter (folded-in 3-1). See [`planning/specs/2026-06-05-retry-and-retry-budget-design.md`](specs/2026-06-05-retry-and-retry-budget-design.md) and [`planning/plans/2026-06-05-retry-and-retry-budget-plan.md`](plans/2026-06-05-retry-and-retry-budget-plan.md).
  - **Shipped in v0.4 slice 2:** `Bulkhead` middleware (concurrency limiter via `asyncio.Semaphore` with bounded acquire wait). See [`planning/specs/2026-06-05-bulkhead-design.md`](specs/2026-06-05-bulkhead-design.md) and [`planning/plans/2026-06-05-bulkhead-plan.md`](plans/2026-06-05-bulkhead-plan.md).
  - **Remaining:** `3-6` extension-slot docs.
```

Replace the `- **Remaining:** ...` line with:
```markdown
  - **Shipped in v0.7:** `3-6` extension-slot docs — [`docs/middleware.md`](../docs/middleware.md). Covers the Middleware Protocol, phase decorators, a Request-ID worked example, and "when NOT to write a middleware." See [`planning/specs/2026-06-05-extension-slot-docs-design.md`](specs/2026-06-05-extension-slot-docs-design.md) and [`planning/plans/2026-06-05-extension-slot-docs-plan.md`](plans/2026-06-05-extension-slot-docs-plan.md).
  - **Epic 3 closed.**
```

- [ ] **Step 2: Commit**

```bash
git add planning/engineering.md
git commit -m "docs(engineering): mark Epic 3 closed (3-6 shipped in v0.7)

§8 now records the extension-slot docs as shipped in v0.7 and notes
Epic 3 closed. The remaining roadmap collapses to Epic 6 (ship v1.0)
plus Epic 5's already-shipped observability work."
```

---

## Task 6: Create `planning/releases/0.7.0.md`

**Files:**
- Create: `planning/releases/0.7.0.md`

- [ ] **Step 1: Write the release notes**

Create `planning/releases/0.7.0.md`:

```markdown
# httpware 0.7.0 — Middleware extension guide (docs-only)

**0.7.0 is a docs-only release. No API changes.** Code written against 0.6.0 continues to work unchanged.

This release ships the final piece of Epic 3 — a user-facing guide to writing custom middleware against `httpware`'s Middleware protocol. With it, Epic 3 (Resilience) closes.

## What's new

- **[`docs/middleware.md`](../../docs/middleware.md)** — a new top-level docs page covering:
  - The `Middleware` Protocol and `Next` type alias, both exported from `httpware.middleware`.
  - The three phase decorators (`@before_request`, `@after_response`, `@on_error`) as ergonomic shortcuts for the common cases.
  - A worked `RequestIdMiddleware` example — assign a per-call UUID, propagate via `X-Request-Id`, log it alongside the response status. Placed outside `Retry` so all attempts of one call share one ID, and correlates naturally with the 0.6.0 observability events' `url` attribute.
  - A "when NOT to write a middleware" section pointing redaction at `logging.Filter`, URL/header validation at `httpx2`, per-call behavior at `request.extensions=`, and HTTP-level tracing at `opentelemetry-instrumentation-httpx`.

Plus small touchups so the guide is discoverable: a nav entry in `mkdocs.yml`, a one-sentence pointer in the README, and a "Where to go next" bullet in `docs/index.md`.

## What's not in this release

- No source code changes. The `Middleware` protocol, `Next` type, and phase decorators all already existed (shipped pre-0.4 via Epic 2); this release documents them.
- No new built-in middleware (no CircuitBreaker, no RateLimiter, no metrics counter). The deliberate non-resilience worked-example choice keeps the guide focused on teaching the protocol rather than shipping a half-baked toy that gets cargo-culted.
- No mkdocs publish workflow / docs-site infra. That's Epic 6 story `6-2`; this release just makes the strict build green.

## Epic 3 closed

Epic 3 (Resilience) has shipped end-to-end:
- v0.4 slice 1 — `Retry` + `RetryBudget` + `attempt_timeout=`
- v0.4 slice 2 — `Bulkhead`
- v0.7 — extension-slot docs

Remaining roadmap is Epic 6 (ship v1.0): `6-2` docs site infrastructure, `6-3` benchmarks, `6-5` release flow (Trusted Publishers + Sigstore).

## References

- Spec: [`planning/specs/2026-06-05-extension-slot-docs-design.md`](../specs/2026-06-05-extension-slot-docs-design.md)
- Plan: [`planning/plans/2026-06-05-extension-slot-docs-plan.md`](../plans/2026-06-05-extension-slot-docs-plan.md)
- Roadmap: [`planning/engineering.md`](../engineering.md) §8
```

- [ ] **Step 2: Commit**

```bash
git add planning/releases/0.7.0.md
git commit -m "docs: 0.7.0 release notes — middleware guide + Epic 3 closed

Docs-only release. Calls out the new docs/middleware.md page, notes the
non-goals (no source changes, no new built-in middleware, no docs-site
infra), and records Epic 3 as closed end-to-end after v0.4 + v0.7."
```

---

## Task 7: Final verification + push

**Files:** none modified; verification only.

- [ ] **Step 1: Lint-ci (sanity)**

```bash
just lint-ci
```
Expected: clean. Lint runs against source code, not docs, so this is a pure no-op confirmation that we haven't accidentally touched a source file.

- [ ] **Step 2: Full test suite (sanity)**

```bash
just test
```
Expected: 251 passed, 100% coverage. Same no-op confirmation logic — no source touched.

- [ ] **Step 3: mkdocs strict build**

```bash
uv run --with mkdocs --with mkdocs-material mkdocs build --strict 2>&1 | tail -20
rm -rf site/
```
Expected: `Documentation built in <time>` with zero warnings about missing files, broken anchors, or unrecognized links. Strict mode treats warnings as errors.

- [ ] **Step 4: Manual cross-reference scan**

```bash
grep -nE '\]\(' docs/middleware.md
```

Each link should be one of:
- `index.md#with-resilience-middleware` (resolves — section exists in `docs/index.md`)
- `index.md#observability` (resolves — section exists in `docs/index.md`)

Repo paths like `planning/engineering.md` are inline references in prose (not markdown links) so they don't need to resolve as anchors.

- [ ] **Step 5: Architecture invariants (sanity)**

```bash
grep -rE 'httpx2\._' src/httpware/ || echo "PASS: no httpx2 private API"
grep -rE 'from __future__ import annotations' src/httpware/ || echo "PASS: no __future__ annotations"
grep -rE '\bprint\(' src/httpware/ || echo "PASS: no print()"
grep -rE 'logging\.(basicConfig|getLogger)\(\)' src/httpware/ || echo "PASS: no global logging"
grep -rE '# (type|mypy): ignore' src/httpware/ || echo "PASS: no type/mypy ignore"
```
Each should print PASS. (Docs-only PR — these are unchanged from main, just confirming we haven't drifted.)

- [ ] **Step 6: Push the branch**

```bash
git push -u origin feat/v0.7-middleware-docs
```

DO NOT open the PR yet — leave that to `finishing-a-development-branch`.

---

## Out of scope for this plan (per the spec)

These items are deliberately deferred or retired. Do NOT do them in this PR:

- **No source code changes.** Zero `src/` files modified. The protocol + decorators already exist and are public; this PR documents them.
- **No CircuitBreaker / RateLimiter / custom-resilience worked example.** The non-resilience Request-ID example is intentional.
- **No ResponseDecoder (Seam B) or optional-extras-pattern (Seam C) coverage.** Those stay in `engineering.md`.
- **No mkdocs publish / docs-site infrastructure.** Epic 6 story `6-2`.
- **No version bump in `pyproject.toml`.** Tag-driven; bump not required.
- **No CLAUDE.md changes.**
- **No new `# noqa` suppressions beyond `# noqa: A002` on the `next` parameter name** (matches `src/httpware/middleware/__init__.py` convention).

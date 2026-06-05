# Spec: Extension-slot docs (Epic 3 story 3-6)

**Date:** 2026-06-05
**Topic slug:** `extension-slot-docs`
**Status:** drafted, awaiting user review
**Target release:** 0.7.0 (docs-only minor)
**Epic 3 stories closed:** 3-6 (the last leftover). Closes Epic 3 entirely.

## Purpose

Document `httpware`'s primary extension point — the **Middleware protocol** — as a user-facing page so library consumers can write their own cross-cutting middleware (request-ID propagation, auth header injection, custom resilience policies, structured tracing, etc.) without reading the source.

This is the deferred-tutorial half of story 3-6. The docs-sync-0.4 pass (PR #25) shipped the freshness fixes and explicitly punted "_write your own middleware_" walkthrough to a future docs PR. This is that PR.

## Background — how 3-6 got here

- **Original framing (pre-pivot):** "Document the extension slot for custom resilience policies." A tutorial framed around hand-rolling CircuitBreaker / RateLimiter / custom backoff.
- **docs-sync-0.4 re-scope:** Folded the *freshness* half of 3-6 into a 0.3→0.4 docs catch-up PR; explicitly deferred the tutorial.
- **This spec:** Closes the tutorial half, scoped to **the Middleware seam only** (Seam A in `engineering.md §3`). ResponseDecoder (Seam B) and the optional-extras pattern (Seam C) stay contributor-facing in `engineering.md` — surfacing them in user docs over-promises an extension surface users shouldn't be touching.
- **Worked-example flavor:** non-resilience (Request-ID propagation) rather than CircuitBreaker. Demonstrates the protocol applies to anything cross-cutting, pairs naturally with the 0.6.0 observability events (correlate a `httpware.retry` record's `url` attribute with the X-Request-Id the middleware set), and avoids shipping a half-baked CircuitBreaker that would get cargo-culted into production.

## Deliverable

### New page: `docs/middleware.md`

Approximately 150 lines markdown, structured as:

1. **Intro (~5 lines).** What a middleware is in httpware; cross-cutting concerns it's the right tool for (auth, tracing, logging, custom resilience). Pointer to built-in `Retry`/`Bulkhead` for the common cases.

2. **The Middleware protocol (~25 lines).** The `Middleware` `Protocol` and `Next` type alias, both already exported from `httpware.middleware`:

   ```python
   from collections.abc import Awaitable, Callable
   from typing import Protocol, TypeAlias, runtime_checkable
   import httpx2

   Next: TypeAlias = Callable[[httpx2.Request], Awaitable[httpx2.Response]]

   @runtime_checkable
   class Middleware(Protocol):
       async def __call__(self, request: httpx2.Request, next: Next) -> httpx2.Response: ...
   ```

   Explain: chain composed at `AsyncClient.__init__`, frozen for the client's lifetime. First in the `middleware=[...]` list is outermost (so `[Bulkhead, Retry]` puts Bulkhead outside Retry — one slot covers all attempts). `await next(request)` invokes the next layer; returning without calling it short-circuits the chain (synthesize a `Response` directly).

3. **Phase decorators (~25 lines).** `@before_request`, `@after_response`, `@on_error` from `httpware.middleware` as ergonomic shortcuts for the common cases:

   - **Use these when:** you don't need state-keeping on `self`, and you don't need to wrap the full `await next(...)` call.
   - **Reach for the raw Protocol when:** you need instance state (e.g., a counter), you need to inspect both the request AND the response (e.g., timing), or you need to interleave behavior around the call (e.g., circuit-breaker state mutation on both success and failure paths).

   Show one minimal pair — a `@before_request` adding a header, and a `@on_error` translating an exception type — without dwelling.

4. **Worked example: Request-ID propagation (~50 lines).** Full class-based middleware demonstrating the raw `Middleware` protocol with state-keeping (a configurable header name) plus both phases (set request header before forwarding, log the ID after the response). Uses `logging.getLogger("myapp.request_id")` — explicitly a *consumer* logger, NOT a `httpware.*` logger, to reinforce that the `httpware.*` namespace is reserved for library-emitted events. The example:

   ```python
   import logging
   import uuid

   import httpx2
   from httpware import AsyncClient, Retry
   from httpware.middleware import Next

   _LOGGER = logging.getLogger("myapp.request_id")


   class RequestIdMiddleware:
       """Propagate a per-call X-Request-Id; log it on response.

       Place OUTSIDE Retry so all attempts of the same call share one ID
       (callable from the consumer's logs to httpware.retry's emitted events
       via the matching `url` attribute).
       """

       def __init__(self, *, header: str = "X-Request-Id") -> None:
           self._header = header

       async def __call__(self, request: httpx2.Request, next: Next) -> httpx2.Response:  # noqa: A002
           request_id = str(uuid.uuid4())
           request.headers[self._header] = request_id
           response = await next(request)
           _LOGGER.info("request complete", extra={"request_id": request_id, "status": response.status_code})
           return response


   async def main() -> None:
       async with AsyncClient(
           base_url="https://api.example.com",
           middleware=[RequestIdMiddleware(), Retry()],  # ID outside Retry
       ) as client:
           await client.get("/users/1")
   ```

   Brief paragraph after: "Correlate with the 0.6.0 observability events — a `httpware.retry` `retry.giving_up` record carries the same `url` your middleware logged the ID against."

5. **When NOT to write a middleware (~15 lines).** Tight callbacks to existing patterns:
   - **Redaction:** use a `logging.Filter` on the consumer side (per the 0.6.0 observability spec's no-redaction-in-httpware stance).
   - **URL / header validation:** `httpx2` owns it; don't reimplement.
   - **Per-call behavior with no cross-cutting state:** pass through `request.extensions=` or the call-site `extensions=` kwarg instead.
   - **Span creation for HTTP tracing:** install `opentelemetry-instrumentation-httpx` — don't write an OTel middleware in httpware (see `engineering.md §8` for why `5-4` was retired).

6. **Cross-references (~5 lines).**
   - `engineering.md §3 Seam A` — the formal protocol contract
   - `src/httpware/middleware/resilience/` — `Retry`, `Bulkhead`, `RetryBudget` as real-world examples reading the same protocol
   - `docs/index.md#with-resilience-middleware` — composition with built-ins

### Touchups

- **`mkdocs.yml`:** add `- Middleware: middleware.md` to the nav, between `Quick-Start` and `Development`.
- **`README.md`:** in the existing "With resilience middleware" subsection, append one sentence: "_Need a custom middleware (auth, tracing, request-ID propagation)? See [`docs/middleware.md`](docs/middleware.md)._"
- **`docs/index.md`:** in the "Where to go next" section, add one bullet: "**[Middleware guide](middleware.md)** — write your own middleware (Request-ID example included)."
- **`planning/engineering.md` §8:** replace the existing Epic 3 closing line ("**Remaining:** `3-6` extension-slot docs.") with: "**Epic 3 — Resilience: SHIPPED.** v0.4 shipped `Retry` + `RetryBudget` + `Bulkhead`; v0.7 ships `3-6` extension-slot docs (`docs/middleware.md`)."
- **`planning/releases/0.7.0.md`:** new file. Short doc-only release notes — calls out the new middleware guide, closes Epic 3, no API changes.

## Non-goals (explicit)

- **No code changes.** This is a docs-only PR. No middleware additions, no protocol extensions, no new public exports.
- **No CircuitBreaker / RateLimiter / custom-resilience example.** The user explicitly chose a non-resilience example to avoid shipping a half-baked toy that gets cargo-culted.
- **No ResponseDecoder (Seam B) or optional-extras (Seam C) coverage.** Those stay in `engineering.md` (contributor-facing).
- **No mkdocs publish / docs-site infra work.** That's Epic 6 story `6-2`; the site_url is still readthedocs.io and we don't try to make it actually publish here.
- **No version bump in `pyproject.toml`.** Tag-driven release (`uv version $GITHUB_REF_NAME` overwrites at build time).
- **No `# noqa`s in the example code beyond `# noqa: A002`** (matches the convention already in `src/httpware/middleware/__init__.py` for the `next` parameter name).
- **No CLAUDE.md changes.**

## Verification gates

- `uv run --with mkdocs --with mkdocs-material mkdocs build --strict 2>&1 | tail -10` → 0 warnings (matches the gate the 0.6.0 work used).
- All cross-reference links in the new page and the README/docs touchups resolve.
- The Request-ID example compiles under `ty` if extracted (verified locally during implementation; not committed as a test).
- Architecture-invariant grep suite still PASSes (no source files modified, but the grep should run anyway for hygiene).
- Full test suite still passes (no code changes, but `just test` should be a no-op confirmation).

## Release shape

- **Version:** 0.7.0 (semver minor — public docs surface grows but no API).
- **Branch:** `feat/v0.7-middleware-docs`.
- **PR:** docs-only, expected ~250 lines markdown net new.
- **Tag:** `0.7.0` after merge; GitHub Release reads from `planning/releases/0.7.0.md`.
- **Publish workflow:** unchanged — the tag-driven publish runs even for docs-only releases, but the only artifact difference is the package metadata's classifier set is unchanged.

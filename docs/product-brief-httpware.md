---
title: "Product Brief: httpware"
status: "complete"
created: "2026-05-11"
updated: "2026-05-12"
inputs:
  - "Conversation with maintainer (Artur Shiriev / krenix512@proton.me)"
  - "Source scan: /Users/kevinsmith/src/pypi/base-client"
  - "Source scan: github.com/community-of-python/circuit-breaker-box"
  - "GitHub API: encode/httpx, encode/httpx Discussion #3784, jawah/niquests, pydantic/httpx2"
  - "Survey of openai-python, anthropic-sdk-python, stripe-python, hvac"
  - "Survey of reqwest, ky, OkHttp, Polly, resilience4j, gobreaker, purgatory, pybreaker"
---

# Product Brief: httpware

## Executive Summary

`httpware` is a new Python async HTTP client framework for building resilient service clients. It supersedes `base-client` (community-of-python), which will be deprecated, and ships under the `modern-python` org.

The library exists because every Python team building backend service clients hits the same wall: the underlying HTTP client leaks its types through your public API, retries and circuit breakers are bolted on as separate libraries with poor composition, and the test story forces consumers to learn transport-level mocking. The dominant async HTTP client was released-stalled for 17 months under `encode/httpx`, then forked to `pydantic/httpx2` on 2026-05-11 with stewardship picked up by Pydantic Services — `httpware` ships on the stewardship-renewed `httpx2` line.

`httpware` solves the underlying design problems: the public API is **transport-agnostic** — the underlying HTTP client is an implementation detail behind a small `Transport` protocol, swappable from httpx2 to niquests (or anything else) without consumer changes. Resilience is a **composable middleware concern**: retries, timeouts, bulkheads, and a Finagle-style **retry budget** ship built-in; circuit breakers and other failure-policy primitives have a stable extension point and a reference design but are deliberately out of v1.0 (see Scope). Tests use a `RecordedTransport` and never see the underlying client.

Now is the right time because `base-client`'s current design (httpx types leaking through the public API, dependency on `httpx._client` private modules, a circuit-breaker library with verified critical bugs) is unsalvageable without breaking changes. The `httpx2` transition is a forcing function: rebuilding on the stewardship-renewed line is the moment to also fix the architectural debt and missing resilience primitives in one motion.

## The Problem

Three pain points motivate this work, in order of severity.

**1. The httpx → httpx2 transition.** `encode/httpx` 0.28.1 shipped 2024-12-06 — no release for 17+ months. The issue tracker was disabled. On 2026-02-27 the lead maintainer publicly stated they were stepping back from community engagement (Discussion #3784). On **2026-05-11** Pydantic Services forked the project as `pydantic/httpx2`, restored community channels, and released `v2.0.0b1` the same day. The strategic concern is now resolved — but every `base-client` consumer is still pinned to `encode/httpx`. Moving to the stewardship-renewed line is itself a breaking change for downstream services if we don't isolate the dependency. Rebuilding the wrapper is the moment to do it right.

**2. `base-client`'s public API leaks httpx everywhere.** Today, `BaseClient` exposes `httpx.AsyncClient` as a public dataclass field; method signatures take and return `httpx.Request` / `httpx.Response`; error classes hold `httpx.Response`; the implementation imports from `httpx._client` and `httpx._types` (private modules). Tests assert against 19 specific httpx exception types via `respx.mock(side_effect=...)`. **Every consumer is tightly coupled to httpx, including via httpx's private API.** Migrating to httpx2 — or anything else — is a breaking change for every downstream service that uses `base-client`.

**3. Resilience is bolted on poorly.** `base-client` depends on `circuit-breaker-box`, which a source-level read confirms has **five critical or high-severity bugs**: no half-open state at all (recovery thundering herd), first failure not counted in retries, Redis backend refreshes the TTL on every increment (the breaker never auto-recovers under sustained load), non-atomic in-memory increment, and an off-by-one in the availability check. It is not a faithful circuit-breaker implementation. Separately, no popular Python library currently ships a **retry budget** — the single most effective control against retry storms, well-understood at Finagle/Envoy scale and absent from Python entirely. The Python ecosystem has the right *parts* (`tenacity`, `purgatory`, `pybreaker`) but no canonical framework that composes them with a coherent ordering, observability, and async semantics.

## The Solution

`httpware` is a small, opinionated framework with six design pillars:

1. **Own the abstractions.** `httpware.Request`, `httpware.Response`, `httpware.Transport`, `httpware.Middleware` are first-class types defined by the library. The underlying HTTP client (`httpx2` by default) sits behind the `Transport` protocol. No consumer code ever imports `httpx2`.

2. **Single-call, typed-response API.** `await client.get("/users/1", response_model=User)` returns a typed `User`. No two-step prepare/send, no fluent builder. Matches the Stainless pattern that openai-python and anthropic-python proved at scale.

3. **First-class middleware, onion model.** Every request flows through `Observability → RetryBudget → Retry → [extension slot] → Bulkhead → Timeout → Transport`. Users add custom middleware (auth refresh, tracing, signing, or a third-party circuit breaker) on the same axis. Built-in primitives are themselves middleware — composable, replaceable, removable.

4. **Pluggable validation.** `response_model=` accepts any type — pydantic is the default validator, but a `ResponseDecoder` protocol lets users plug in `msgspec`, `attrs`, plain dataclasses, or anything else. The library does not hard-couple to one validation library, avoiding the same leakage problem we're solving for the transport.

5. **Retry budget as the flagship resilience feature.** The single thing that turns retry from a footgun into a safe default. Token-bucket admission control over the whole client's retry traffic (Finagle defaults: 20% retry ratio + 10/sec floor + 10s TTL). Caps retry storms before they happen; degrades gracefully when the budget is exhausted. Almost no Python library ships this — `httpware` makes it on by default.

6. **Tests speak the library's language, not the transport's.** A `RecordedTransport({(method, url): Response})` is the primary test path. Consumers never write respx routes and never assert against httpx2 exception types. Mocking is a 3-line fixture.

## What Makes This Different

The Python landscape has three rough cohorts:

- **Stainless-generated SDKs** (openai-python, anthropic-python): excellent typed responses, granular exception hierarchy, but deliberately no middleware system — retries are hand-rolled inside the request loop, circuit breakers are not supported, and the library exists only because it's generated from an OpenAPI spec. Not a framework for building your own service clients.
- **Raw httpx2 / niquests**: low-level transport. No resilience built in. Tests use transport-level mocking. Public API tied to the chosen client.
- **`base-client` and similar thin wrappers**: shims that re-expose the underlying client's types and bolt on one or two resilience libraries with poor composition.

`httpware` occupies the gap: a **framework** with the Stainless typed-response ergonomics, plus first-class middleware-based resilience (which Stainless deliberately omits), plus genuine transport-agnosticism. The retry budget is a category-leading feature. The honest moat is design quality and the combination — none of the pieces are individually novel, but the combination doesn't exist in Python today.

The fuller positioning: **`httpware` is to Python what Polly is to .NET and resilience4j is to the JVM** — a canonical resilience-first HTTP framework. Python has no equivalent category leader; the transport-agnostic abstraction is the proof point that lets `httpware` stand independent of any one underlying client's fate.

## Who This Serves

**Primary**: Backend Python teams in `modern-python` and partner orgs building async service-to-service clients (FastAPI services calling other internal or third-party APIs). Several teams already depend on `base-client`; they need a path forward.

**Secondary**: Teams building **LLM and AI-gateway clients**. AI service traffic is the highest-volume, highest-failure HTTP workload in Python in 2026: long streaming responses, aggressive rate-limits, retry storms when a provider degrades, multi-vendor failover. The middleware model is literally what teams hand-roll on top of openai/anthropic SDKs today — `httpware` makes it a one-line declaration.

**Tertiary**: The wider Python community building service clients on PyPI. `httpware` is open-source and credible as a default choice for new projects that today would reach for `httpx2 + tenacity + a-circuit-breaker-library + a custom wrapper`.

**Success for a user looks like**: defining a service client in under 50 lines that gets resilient retries, retry budgeting, observability, and typed responses for free; swapping the underlying HTTP client (httpx2 → niquests, when the time comes) with a single-line change; writing tests that don't know what an `httpx2.Request` is.

## Success Criteria

**v1.0 release criteria**

- All public API surface uses `httpware.*` types. `grep -r 'import httpx2' httpware/ examples/ tests/` returns zero hits outside the `httpware.transports.httpx2` module.
- Built-in middleware ships and is documented: Retry, RetryBudget, Bulkhead, Timeout, Observability (with OpenTelemetry instrumentation).
- Middleware extension point documented and validated by a reference circuit-breaker middleware (built atop `purgatory` or equivalent) shipped as an example or companion package, not as a v1.0 dependency.
- `RecordedTransport` covers the common test patterns from current `base-client` consumers (success, error status, exception, retry behavior).
- `ResponseDecoder` protocol shipped with pydantic and msgspec adapters.
- At least one consumer service inside `modern-python` is migrated from `base-client` to `httpware` and running in production.

**Adoption criteria (6 months post-1.0)**

- All known `base-client` consumers migrated; `base-client` archived.
- ≥3 external (non-`modern-python`) projects on PyPI depending on `httpware`.

## Scope

**In scope for v1.0**

- Async-only API (no sync facade).
- `Transport` protocol + default `Httpx2Transport`. (Niquests transport: nice-to-have, not blocking.)
- Single-call request API with `response_model=` typed responses.
- `ResponseDecoder` protocol — pluggable validator. Default pydantic adapter; msgspec adapter shipped. User can plug attrs, dataclasses, or anything else.
- Middleware system (onion model with phase-shortcut helpers) and a documented extension point in the resilience layer (the "extension slot" between Retry and Bulkhead) where third-party middleware (e.g. circuit breakers) cleanly compose.
- Built-in middleware: Retry (full-jitter exponential backoff, idempotency-aware), RetryBudget (Finagle defaults), Bulkhead (`asyncio.Semaphore`-based), Timeout, Observability hooks with first-class OpenTelemetry semantic-convention support.
- Exception hierarchy keyed by status (`NotFoundError`, `RateLimitedError`, etc.) with plain fields (`status: int`, `body: bytes`, `headers`, `json`). No transport-typed objects on exceptions.
- `RecordedTransport` for tests.
- `with_options(...)` returning a new client sharing the pool.
- Streaming via `async with client.stream(...) as resp`.
- Security defaults: TLS verification on, configurable secret-redaction hook on outgoing logs/spans, documented CVE disclosure channel.
- Python 3.11+ (drop 3.10 to use `TaskGroup`).

**Explicitly out of v1.0 (designed for, not implemented in v1.0)**

- **In-house circuit breaker.** The middleware extension slot is the contract — a circuit-breaker middleware can be plugged in without library changes. A reference implementation (likely wrapping `purgatory`) ships as an example or companion package. The library's design notes capture the intended state machine (3-state, sliding-window, slow-call, jittered half-open) so the future implementation has a target.
- **Sync API.** Async-only at v1.0. Sync support, if it comes, ships as a parallel class hierarchy (à la Stainless). Users with mixed sync/async codebases (Celery workers, scripts, migrations) keep using `requests` or httpx2 synchronously for now.
- **Niquests transport.** The `Transport` protocol guarantees it's a future-proof addition; shipping it is post-v1.0.
- **Distributed resilience-state coordination** beyond a single Redis backend. No gossip protocols.
- **OpenAPI-driven codegen.**
- **Backwards-compatibility shim for `base-client`.** Migration is documented but not automated.

## Technical Approach

A short engineering note (not the executive read):

The reference implementation is a **clean greenfield rewrite**, not a fork of `base-client`. Default `Transport` wraps `httpx2.AsyncClient` and adapts types at the seam. The default `ResponseDecoder` is a pydantic adapter that caches `TypeAdapter` instances per `response_model` and uses `validate_json(content)` rather than `validate_python(json())` — roughly 2× parse-and-validate throughput, and a fix for a documented performance footgun in current `base-client`. A msgspec adapter ships alongside for users who want msgspec's faster path. Default `Limits` and `Timeout` shipped by the library are sensible for service workloads (`Timeout(connect=5, read=30, write=30, pool=5)`, `Limits(max_connections=100, max_keepalive=20)`), not the `Timeout(1)` in current `base-client` examples.

## Vision (2-3 years)

`httpware` becomes the default choice in the `modern-python` ecosystem for any service that talks to another service over HTTP. It earns adoption outside the org because no other Python library combines its typed-response ergonomics, first-class resilience, and transport-agnosticism.

The transport-agnostic design isn't strategic insurance against any one client's fate (the httpx → httpx2 transition demonstrated that the ecosystem can self-correct), but it remains durable value: any consumer of `httpware` rides out future transport changes without code rewrites, and a future `NiquestsTransport` (or any other backend) drops into the same `Transport` slot.

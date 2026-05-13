---
stepsCompleted:
  - step-01-init
  - step-02-discovery
  - step-02b-vision
  - step-02c-executive-summary
  - step-03-success
  - step-04-journeys
  - step-05-domain-skipped
  - step-06-innovation
  - step-07-project-type
  - step-08-scoping
  - step-09-functional
  - step-10-nonfunctional
  - step-11-polish
  - step-12-complete
status: complete
releaseMode: phased
inputDocuments:
  - docs/product-brief-httpware.md
  - docs/product-brief-httpware-distillate.md
workflowType: prd
project_name: httpware
classification:
  projectType: developer_tool
  domain: general
  complexity: low
  projectContext: greenfield
---

# Product Requirements Document - httpware

**Author:** Artur Shiriev
**Date:** 2026-05-11
**Updated:** 2026-05-12 — reflects the `pydantic/httpx2` fork; transport switched from `encode/httpx` 0.28 to `pydantic/httpx2` 2.0.0b1.

## Executive Summary

`httpware` is a Python async HTTP client framework for building resilient service clients. It supersedes `community-of-python/base-client` (to be deprecated) and ships under `github.com/modern-python`.

The framework owns the abstraction layer above the underlying HTTP client (`httpx2` by default; niquests planned). Consumers never import the transport; swapping it is a constructor argument. Resilience primitives — retries, timeouts, bulkheads, and a Finagle-style retry budget — are composable middleware; circuit breakers have a stable extension point but are not implemented in v1.0. Tests use a `RecordedTransport` and assert against plain exception fields (`status`, `body`, `headers`, `json`), never against the underlying client's types.

**Target users:**
- *Primary:* Backend Python teams in `modern-python` and partner orgs building async service-to-service clients (FastAPI-era backends).
- *Secondary:* Teams building LLM and AI-gateway clients — high-volume, high-failure HTTP workloads where middleware-composed resilience is hand-rolled today.
- *Tertiary:* Wider Python community building service clients on PyPI.

**Problem solved:** Python has no canonical resilience-first HTTP framework. Existing wrappers (including `base-client`) leak transport types through their public APIs, making any transport migration — including the just-happened `encode/httpx` → `pydantic/httpx2` transition — a breaking change for every downstream consumer. Available resilience libraries are buggy or unmaintained (`circuit-breaker-box` has 5 verified critical bugs).

**Why now:** The `encode/httpx` → `pydantic/httpx2` fork (2026-05-11) is a forcing function. `base-client` cannot be salvaged in place (it imports from `httpx._client` and `httpx._types` private modules), and every consumer needs an httpx-to-httpx2 path anyway. Rebuilding the wrapper as a transport-agnostic framework is the moment to also close the resilience-framework gap that's been open in Python (analogous to Polly on .NET, resilience4j on JVM) since async HTTP became standard.

### What Makes This Special

**Core insight:** The Python async-HTTP problem isn't which client to pick. It's that no framework owns the layer *above* the client. Owning that layer turns transport choice into a reversible decision and resilience into composable primitives — both problems collapse into one architectural move.

**Differentiators:**
1. **Transport-agnostic public API.** `httpware.Request`, `httpware.Response`, `httpware.Transport`, `httpware.Middleware` are first-class types. The underlying client sits behind a small `Transport` protocol. No public symbol references `httpx2`.
2. **Onion middleware with phase shortcuts.** `Observability → RetryBudget → Retry → [extension slot] → Bulkhead → Timeout → Transport`. Built-in primitives and user middleware live on the same axis. Third-party circuit breakers plug into the extension slot without library changes.
3. **Retry budget by default.** Token-bucket admission control (Finagle defaults: 20% retry ratio, 10/sec floor, 10s TTL). The most effective single control against retry storms — absent from every popular Python HTTP library.
4. **Pluggable validation.** `response_model=` accepts any type via a `ResponseDecoder` protocol. Default pydantic adapter (cached `TypeAdapter`, `validate_json(content)`); msgspec adapter shipped. Same anti-leakage discipline applied to validation.
5. **`RecordedTransport` for tests.** Mocking is a 3-line fixture keyed on `(method, url) → Response`. No respx routes, no transport-level mocking, no httpx2-typed assertions.
6. **Stainless-pattern typed responses.** `await client.get("/users/1", response_model=User)` returns a typed `User`. `with_options(...)` returns a new client sharing the pool. Granular status-keyed exception hierarchy with plain fields.

**Positioning:** `httpware` is to Python what Polly is to .NET and resilience4j is to the JVM — a canonical resilience-first HTTP framework. Transport-agnosticism is the proof point that lets it stand independent of any underlying client's governance trajectory.

## Project Classification

| Field | Value |
|---|---|
| **Project Type** | `developer_tool` — pip-installable Python library/framework |
| **Domain** | `general` — Python developer infrastructure (no regulated-industry constraints) |
| **Domain Complexity** | `low` — implementation complexity is moderate-to-high (async, resilience, transport abstraction) but domain/compliance load is minimal |
| **Project Context** | `greenfield` — new library; supersedes `community-of-python/base-client` (to be deprecated) |
| **Org** | `github.com/modern-python` |

## Success Criteria

### User Success

`httpware` succeeds for its users (Python service-team developers) when:

- **Time-to-functional-client.** A new resilient service client (base URL + 3 endpoint methods + tests + typed responses + retries + retry budget) takes ≤50 LOC of consumer code, including imports.
- **Test ergonomics.** A unit test that mocks an HTTP call requires ≤3 lines of fixture setup via `RecordedTransport`. Zero references to `httpx2.*` or `respx.*` in consumer test code that is not specifically integration-testing the transport.
- **Transport reversibility.** Switching from `Httpx2Transport` to `NiquestsTransport` (once shipped) is a one-line constructor change and requires zero changes to consumer code — verified by migrating one example project.
- **Error handling.** Consumer code catches `httpware.NotFoundError`, `httpware.RateLimitedError`, etc. with plain fields (`e.status: int`, `e.body: bytes`, `e.headers`, `e.json`). Zero `except httpx2.*` clauses in any migrated codebase.
- **Discoverability.** A consumer can answer "how do I add request signing?" by reading the middleware authoring guide and writing one class in <30 LOC.
- **Aha moment.** When a developer migrating from `base-client` deletes the per-test `respx.route(...).mock(...)` boilerplate and replaces it with a 3-line `RecordedTransport`, AND when they delete the bolt-on tenacity decorators because retry policy is now a constructor argument.

### Business Success

For an OSS library shipping under `modern-python`:

- **3 months post-v1.0:** ≥1 production service inside `modern-python` (or partner org) migrated from `base-client` to `httpware` and stable for ≥30 days.
- **6 months post-v1.0:** All known `base-client` consumers migrated. `community-of-python/base-client` repo archived with a README pointer to `httpware`.
- **6 months post-v1.0:** ≥3 external PyPI projects (non-`modern-python`, non-`community-of-python`) declaring `httpware` as a dependency.
- **12 months post-v1.0:** Library cited in ≥2 external sources (blog post, conference talk, Awesome-Python list) as the recommended Python resilience-first HTTP framework.

### Technical Success

Hard, verifiable criteria:

- `grep -r 'import httpx2\|from httpx2' httpware/ tests/ examples/` returns matches only inside `httpware/transports/httpx2.py` (the transport adapter module).
- `grep -r 'httpx2\._' httpware/` returns zero matches (no httpx2 private-API usage anywhere — this is the bar `base-client` currently fails with `encode/httpx`).
- Property-based test suite (Hypothesis) for `RetryBudget` admission control passes ≥10,000 trials covering concurrent failure scenarios with no race-condition failures or invariant violations.
- Performance budget: per-request overhead measured as the wall-clock delta of `client.get(url, response_model=User)` vs raw `httpx2.AsyncClient().get(url)` + manual `pydantic.TypeAdapter(User).validate_json(resp.content)` is ≤15% on typical 5KB JSON payloads at 100 RPS sustained. Benchmark published with each release.
- ≥90% line coverage on `httpware/` core (transports excluded, since transport adapters are largely passthrough).
- All public types `py.typed`; `ty` (Astral) passes on `httpware/` and on a reference consumer.
- Python 3.11+ supported (3.11, 3.12, 3.13, 3.14 when available) on CI.

### Measurable Outcomes

Tracked publicly in the repo:

| Outcome | Metric | Target |
|---|---|---|
| Migration acceptance | `modern-python` services on `httpware` | 1 (3 mo), all known (6 mo) |
| External adoption | PyPI dependents (non-modern-python) | ≥3 (6 mo) |
| Performance honesty | Published benchmark vs raw httpx2+pydantic | Every release |
| Quality bar | Property-based test trials passing | ≥10,000 |
| API hygiene | httpx2 imports outside `transports/httpx2.py` | 0 |
| Test ergonomics | Lines of test fixture code in migrated consumers | ≤3 per test |

## Product Scope

### MVP — Minimum Viable Product

Everything required for a `modern-python` team to migrate one production service off `base-client`:

- **Async API.** `AsyncClient` with `get`/`post`/`put`/`patch`/`delete`/`head`/`options`/`request` methods. Async-only; no sync facade.
- **`Transport` protocol** + default **`Httpx2Transport`** wrapping `httpx2.AsyncClient` and adapting types at the seam. Sensible default `Timeout(connect=5, read=30, write=30, pool=5)` and `Limits(max_connections=100, max_keepalive_connections=20)`.
- **Single-call typed-response API.** `await client.get(url, response_model=T)` returns `T`. `response_model=None` returns a `Response` wrapper.
- **`ResponseDecoder` protocol** + pydantic adapter (cached `TypeAdapter` per model_type, `validate_json(content)`).
- **Middleware system.** Onion model with `Middleware`, `Next`, phase-shortcut helpers `@before_request`, `@after_response`, `@on_error`. Order: `Observability → RetryBudget → Retry → [extension slot] → Bulkhead → Timeout → Transport`. Extension slot is the documented contract for plug-in middleware (notably a future circuit breaker).
- **Built-in middleware (v1.0):** `Retry` (full-jitter exponential backoff, idempotent-method-only by default, Retry-After-aware), `RetryBudget` (Finagle defaults: 20% retry ratio, 10/sec floor, 10s TTL), `Bulkhead` (`asyncio.Semaphore` per key), `Timeout` (per-attempt), `Observability` (hooks + optional OpenTelemetry span integration).
- **Exception hierarchy** keyed by HTTP status with plain fields (`status`, `body`, `headers`, `json`, `request_method`, `request_url`). `TransportError`, `TimeoutError`, `BadRequestError`, `UnauthorizedError`, `ForbiddenError`, `NotFoundError`, `ConflictError`, `UnprocessableEntityError`, `RateLimitedError`, `InternalServerError`, `ServiceUnavailableError`.
- **`RecordedTransport`** test double accepting `{(method, url_pattern): Response | Exception}` and exposing `.calls` for assertions.
- **`with_options(...)`** returning a new client sharing the pool.
- **Streaming** via `async with client.stream(method, url, ...) as resp`, with `iter_bytes`, `iter_text`, `iter_lines`.
- **Auth abstraction** accepting `str | Callable[[], str | Awaitable[str]] | Middleware`.
- **Security defaults:** TLS verification on; configurable secret-redaction hook for log/span emission; CVE disclosure channel documented in `SECURITY.md`.
- **Docs:** README, migration guide from `base-client` (with side-by-side examples), middleware authoring guide, RecordedTransport cookbook.
- **Acceptance:** ≥1 production consumer in `modern-python` running on `httpware` for ≥30 days.

### Growth Features (Post-MVP)

Features that make `httpware` competitive beyond the migration use case:

- **`NiquestsTransport`** — second backend that proves the abstraction. HTTP/2 + HTTP/3 by default. Triggers the "transport reversibility" success metric.
- **Reference circuit-breaker middleware.** Companion package or example wrapping `purgatory`. Validates the extension slot is real and usable.
- **msgspec `ResponseDecoder` adapter** — faster validation path for high-throughput services.
- **OpenTelemetry semantic-convention auto-instrumentation** — spans named per `http.client.request.*` conventions; metric names per `http.client.request.duration`, etc.
- **`client.gather(...)`** — concurrency helper using `TaskGroup` with semaphore-aware queueing, sized against `Limits.max_connections`.
- **FastAPI / Litestar integration recipes** — context-managed dependency injection for shared clients, request-scoped middleware (correlation ID propagation).
- **Public benchmark suite** vs raw httpx2 + tenacity, published with each release as part of the repo (closing the "is this thing slow?" objection pre-emptively).
- **HTTP/2 toggle** for `Httpx2Transport` (default off; documented opt-in).
- **JSON Schema / OpenAPI response validation** as an alternate `ResponseDecoder` for users who don't want pydantic/msgspec.

### Vision (Future)

The dream version that comes from being the category leader:

- **LLM/AI-gateway preset.** A `LLMClient` subclass with token-accounting middleware, SSE/streaming parsers, vendor-failover middleware. Concrete answer to "I'm hand-rolling resilience on top of `openai-python`."
- **Sync API** as a parallel class hierarchy (Stainless pattern), if downstream demand justifies the maintenance double.
- **OpenAPI codegen target.** Generate typed `httpware`-based clients from a spec — each generated client is a distribution vector that brings the middleware ecosystem along.
- **In-house circuit breaker** (3-state, sliding-window, slow-call detection, jittered half-open) — only if the wrapping-`purgatory` path proves inadequate. Detailed reference design captured in the distillate.
- **Distributed resilience-state coordination** beyond a single Redis backend (gossip, multi-region failover).
- **Middleware marketplace / registry** — third-party middleware (auth providers, signing schemes for AWS SigV4/GCP/HMAC, tracing exporters) creating a network effect.

## User Journeys

### 1. Maria — Migrating a Service from `base-client` to `httpware` (Primary, success path)

**Opening scene.** Maria is a senior backend engineer at a `modern-python` partner team. Her FastAPI service depends on `base-client` to call three internal APIs. She has been deferring an upgrade because the last time she opened the codebase she counted 19 `except httpx.*` clauses in tests, three `httpx._client.USE_CLIENT_DEFAULT` references in production code, and a `circuit-breaker-box` configuration nobody on the team understands. The `lovelydinosaur` discussion thread crosses her feed and the migration becomes someone's task — hers.

**Rising action.** She reads the `httpware` README and the migration guide. The shape feels familiar (httpx-like method names) but the types are different — `httpware.AsyncClient` returns `httpware.Response`, not `httpx.Response`. She runs `grep -r 'httpx' .` on her consumer code and finds 47 hits. The migration guide gives her a per-symbol replacement table. She replaces `httpx.AsyncClient` construction with `httpware.AsyncClient(base_url=..., timeout=...)` (the default `Httpx2Transport` is constructed implicitly). She deletes the `circuit_breaker_box.Retrier` wrapper and the `tenacity` decorators — `httpware` ships retries and a retry budget by default. She rewrites her error handling: `except httpx.HTTPStatusError as e: if e.response.status_code == 404` becomes `except NotFoundError`. She thinks "wait, that's it?"

**Climax.** She runs the test suite. Most tests fail with `AttributeError: 'RecordedTransport' has no attribute 'mock'`. She replaces `respx.mock` + 5-line route setup with a single dict literal: `RecordedTransport({("GET", "/users/1"): Response(status=200, json={...})})`. Suddenly her test files shrink by 30%. The test that simulated a `httpx.ReadTimeout` becomes `RecordedTransport({(...): TimeoutError()})`. The 19 exception types collapse to 5.

**Resolution.** Her service runs. The retry-budget metrics show up in her Grafana dashboard automatically via OpenTelemetry. The migration took two afternoons. She archives the team's bookmark to circuit-breaker-box's repo. Her PR review comment from a teammate is "wait, where did all the test boilerplate go?"

**Capabilities this journey reveals:**
- Migration guide with per-symbol replacement table from `base-client` and from raw `httpx` (both `encode/httpx` and `pydantic/httpx2` paths)
- `httpware.NotFoundError`/`RateLimitedError`/etc. with plain fields
- Defaults that "just work" (retries on, retry budget on, sane Timeout/Limits)
- OpenTelemetry semantic-convention auto-instrumentation
- `RecordedTransport` accepting both response and exception side-effects

### 2. Dmitri — Greenfield Service Client (Primary, alternate goal)

**Opening scene.** Dmitri is starting a new internal billing service. It calls four upstream services. He skims the `httpware` README during onboarding.

**Rising action.** He writes a `BillingApiClient` subclass that holds an `httpware.AsyncClient` instance. Endpoint methods are 3-line `await self._client.get("/invoices/{id}", response_model=Invoice)`. He adds `default_headers={"X-Service": "billing"}` and `auth=lambda: get_token()`. Twenty minutes in, the client compiles, types check, and three endpoint methods are written.

**Climax.** He needs request signing (HMAC) for one upstream. He reads the middleware authoring guide. He writes a 12-line `SignRequestMiddleware` class implementing the `Middleware` protocol. He passes it to the constructor: `middleware=[SignRequestMiddleware(secret)]`. It works on the first run.

**Resolution.** The billing client is 47 lines of consumer code, has retries with full-jitter backoff, retry budget, OpenTelemetry tracing, typed responses, and signed requests. He never imported `httpx2`, `tenacity`, or `circuit-breaker-box`. He doesn't notice this; he just notices that he is done.

**Capabilities this journey reveals:**
- `AsyncClient` constructor with idiomatic kwargs (`default_headers`, `default_query`, `auth`, `middleware`, `timeout`, `base_url`)
- Composable `Middleware` protocol with single `(req, next) -> Response` signature
- `auth: str | Callable | Middleware` union type
- Middleware authoring guide with end-to-end signing example

### 3. Yulia — Production Outage Debug (Primary, edge case / failure recovery)

**Opening scene.** 2 a.m. PagerDuty. Yulia's service is throwing `5xx` for ~15% of requests to an upstream payments API. The on-call dashboard shows elevated `http.client.request.duration` p99 but the upstream's status page is green.

**Rising action.** Yulia opens the Grafana board (the one that `httpware` populates by default via OTel). She sees `circuit_breaker.rejections_total` is flat (good — no breaker tripped) but `retry_budget.tokens_remaining` is at 0. The retry budget is being exhausted, which means a large number of requests are hitting upstream failures and retries are being shed. She sees `http.client.request.duration` for the affected upstream — p99 of 4.2s, up from 600ms.

**Climax.** She runs `client.with_options(timeout=Timeout(connect=5, read=15, write=10, pool=5)).with_options(retries=0).post(...)` from a debug shell to bypass retries and isolate the upstream. She gets a clean `ServiceUnavailableError` with `e.body` showing the upstream's actual response: "rate-limit exceeded by region quota."

**Resolution.** She raises the upstream rate-limit ticket. The retry budget protected her service from spiraling into a retry storm during the incident. She updates the runbook to point at the `retry_budget.tokens_remaining` graph as the first thing to check during similar incidents.

**Capabilities this journey reveals:**
- OpenTelemetry semantic-convention instrumentation (per-request duration, per-host counters)
- `client.with_options(...)` as the ergonomic per-call override for debugging
- Observability hooks for `retry_budget.tokens_remaining`, `retry.attempts_total`, `bulkhead.queued`
- Plain-field exceptions (`e.body`, `e.headers`) usable in ad-hoc debug shells
- Documentation showing the on-call playbook for observability signals

### 4. Alex — LLM Gateway with Vendor Failover (Secondary user)

**Opening scene.** Alex maintains an internal LLM proxy service that fronts OpenAI, Anthropic, and an internal model. It uses `openai-python` and `anthropic-sdk-python` directly. The hand-rolled retry logic doesn't compose with the SDKs' built-in retries, and a recent OpenAI degradation took down the proxy for 12 minutes before the team manually flipped traffic to Anthropic.

**Rising action.** Alex reads the LLM/AI-gateway secondary-user section of the `httpware` docs. He decides to wrap the OpenAI and Anthropic SDKs at the HTTP layer using `httpware`. He configures two `AsyncClient` instances, each with `base_url` pointing at the respective vendor. He writes a `VendorFailoverMiddleware` that, on `ServiceUnavailableError` from one client, retries the request through a second client.

**Climax.** During a synthetic test, Alex kills the OpenAI route on his test stand. The middleware catches the connection error, calls the Anthropic client, and the response returns within 800ms (vs. the previous 12-minute manual cutover). The retry budget on the OpenAI side prevents thundering-herd retries during the outage.

**Resolution.** The LLM proxy is now resilient to single-vendor outages. The middleware is 60 LOC. Alex publishes it as `llm-failover-middleware` on PyPI — the first third-party `httpware` middleware in the ecosystem.

**Capabilities this journey reveals:**
- Streaming response support (LLM responses are SSE/streaming)
- Per-attempt timeouts long enough for LLM workloads (`read=600s` configurable)
- Middleware composition allowing cross-client patterns (failover across two `AsyncClient` instances)
- Public middleware-authoring contract stable enough to publish third-party middleware against
- `httpware` not being prescriptive about what "the" LLM client looks like — composition over inheritance

### 5. Sergey — Building Custom Tracing Middleware (Developer-author journey)

**Opening scene.** Sergey is the platform engineer who owns observability standards at his company. The default `httpware` OpenTelemetry middleware emits standard semantic-convention attributes, but his org needs custom attributes (tenant ID from a context var, deployment region from env).

**Rising action.** He reads the middleware authoring guide. He sees two paths: (a) write a full `Middleware` class, (b) use the `@before_request` and `@after_response` phase shortcuts. He picks (b) for simplicity. Two functions, eight lines total, decorated. He registers them on the client constructor.

**Climax.** First request fires. Custom attributes show up in his Jaeger trace alongside the default attributes — both compose cleanly. He notices the default OTel middleware ran first, his custom additions ran after. He likes that.

**Resolution.** He publishes the middleware as an internal package. Two other teams adopt it within a week.

**Capabilities this journey reveals:**
- `@before_request` and `@after_response` decorators as the ergonomic on-ramp before full `Middleware` classes
- Documented middleware execution order so additive instrumentation composes predictably
- Default OTel middleware is itself middleware (replaceable, not magic) — Sergey's custom middleware sees the same hooks
- Middleware authoring guide with both phase-shortcut and full-class examples

### Journey Requirements Summary

Capabilities revealed across the five journeys:

| Capability area | Journeys requiring it |
|---|---|
| Migration guide (per-symbol replacement, side-by-side examples) | 1 |
| `RecordedTransport` for tests (response + exception side-effects) | 1 |
| Sensible defaults (retries, retry budget, OTel, Timeout, Limits) | 1, 2 |
| Plain-field status-keyed exception hierarchy | 1, 3 |
| `AsyncClient` ergonomic constructor (`base_url`, `auth`, `middleware`, etc.) | 2, 4 |
| `Middleware` protocol + onion model | 2, 4, 5 |
| `@before_request` / `@after_response` phase shortcuts | 5 |
| Middleware authoring guide (phase shortcuts + full class) | 2, 5 |
| `auth: str \| Callable \| Middleware` union | 2 |
| OpenTelemetry semantic-convention auto-instrumentation | 1, 3, 5 |
| `client.with_options(...)` per-call override | 3 |
| Observability metrics: `retry_budget.tokens_remaining`, `retry.attempts_total`, `bulkhead.queued`, breaker rejections | 3 |
| Streaming response support (`async with client.stream(...)`) | 4 |
| Long-duration `read` timeout configurability | 4 |
| Public middleware contract stable for third-party publication | 4, 5 |
| Composable across multiple `AsyncClient` instances | 4 |
| Reasonable on-call documentation / runbook examples | 3 |

## Innovation & Novel Patterns

### Detected Innovation Areas

1. **Retry budget brought to Python.** The Finagle/Envoy retry-budget pattern (token-bucket admission control over the whole client's retry traffic) is well-understood at scale, but no popular Python HTTP library ships it. `httpware` is plausibly the first Python library to make a retry budget a default-on, configurable primitive. This isn't a new pattern — it's a documented best practice that's been absent from the language's ecosystem.

2. **Library-owned transport abstraction in async Python.** Stripe-python proved the pattern works for sync (its `HTTPClient` ABC switches between `RequestsClient`/`HTTPXClient`/`AIOHTTPClient`). `httpware` brings the same discipline to async — and applies it as a wrapper-framework, not a per-vendor SDK. Owning `Transport` as a first-class protocol that consumers depend on, rather than re-exposing httpx2, is uncommon in Python wrappers (the current `base-client` exemplifies the prevailing leaky pattern with `encode/httpx`).

3. **Documented "extension slot" in the middleware ordering.** `httpware` commits to a specific onion order with a named, contract-bound slot for plug-in middleware (where a circuit breaker will live). Most middleware systems leave order informal or document it loosely; a named slot is a small but real innovation in surface design. It makes the question "where does my middleware go?" answerable by reading docs, not by experimentation.

4. **Anti-leakage discipline applied beyond HTTP.** The same protocol-based pluggability applied to transport (`Transport` / `RecordedTransport`) is applied to validation (`ResponseDecoder` / pydantic adapter / msgspec adapter). One framework, two pluggable extension points, same design pattern. The novelty here is consistent execution, not the underlying idea.

### Market Context & Competitive Landscape

- **Polly (.NET)** and **resilience4j (JVM)** are the category leaders in their ecosystems. Python's analogous slot is empty — `tenacity` covers retry, `purgatory`/`pybreaker` cover breakers, but no library composes them into a coherent framework with consistent observability and async semantics.
- **Stainless-generated SDKs** (openai-python, anthropic-python) demonstrate that the typed-response + status-keyed-exception pattern works at scale. They deliberately omit middleware — that's the gap `httpware` fills for the framework use case (vs. the per-API SDK use case Stainless targets).
- **niquests** validates that the async HTTP transport landscape is mid-disruption. `httpware`'s abstraction means consumers don't pay a tax for being early or late on that disruption.
- **The `pydantic/httpx2` fork** (2026-05-11) resolves the encode/httpx maintenance gap with backed stewardship. `httpware` doesn't compete with httpx2 — it sits above it — so it's net-additive to whichever transport the consumer ends up on.

### Validation Approach

- **Migrate one production service first.** Hard-evidence test: a real consumer ships on `httpware` for ≥30 days. If migration takes >2 days for a team that already used `base-client`, the migration guide failed and the pattern needs work.
- **Property-based tests for the retry budget.** The hardest novel part of the design; concurrency invariants must hold under stress. ≥10,000 Hypothesis trials covering admission control under concurrent failure scenarios.
- **Public benchmark suite vs raw httpx2 + tenacity**, published with each release. Closes the "frameworks are slow" objection pre-emptively. Target: ≤15% per-request overhead on 5KB JSON payloads at 100 RPS.
- **External adoption signal.** ≥3 non-`modern-python` PyPI dependents within 6 months. This is the "did the combination resonate?" question being answered by the market, not by us.
- **Reference circuit-breaker middleware ships in growth phase.** Proves the extension slot is a real, usable contract — not aspirational.

### Risk Mitigation (innovation-specific)

Three risks tied directly to the innovative elements above; broader project-level risks (market, adoption, resourcing) are covered in *Project Scoping & Phased Development → Risk Mitigation Strategy*.

- **If retry budget defaults are wrong**, they're constructor-overridable from day one. No correctness risk — just a tuning question.
- **If transport abstraction cannot cleanly cover niquests semantic differences** (timeout interpretation, streaming cancellation), v1.0 stays httpx2-only and the gap is resolved via type-narrowing or adapter shims when niquests is added in the Growth phase. Consumer migration cost stays the same.
- **If property-based tests find concurrency bugs in the retry budget**, fix them before v1.0 — shipping broken resilience primitives is the exact failure mode that drove this project (the `circuit-breaker-box` precedent).

## Developer Tool Specific Requirements

### Project-Type Overview

`httpware` is a pip-installable Python library distributed via PyPI. It provides a public API surface (classes, protocols, decorators) consumed by application code at import time. It is not a CLI, has no GUI, requires no daemon, and does not generate code. Its install footprint is small (one wheel, pure-Python, ~1500-2000 LOC).

### Language Matrix

**Python versions supported (v1.0):**

| Version | Status | Notes |
|---|---|---|
| 3.11 | Supported | Floor — required for `asyncio.TaskGroup` and exception groups |
| 3.12 | Supported | |
| 3.13 | Supported | Free-threaded build tested as best-effort, not promised |
| 3.14 | Supported when GA | Added to CI on release |

**Python versions explicitly excluded:**

- **3.10 and earlier.** Required for `TaskGroup` and `except*` (PEP 654). 3.10 EOL is October 2026; cost of supporting it is too high.
- **PyPy.** Tested as best-effort; not promised. Pydantic v2 has degraded performance on PyPy.
- **GraalPy / IronPython / other implementations.** Not in scope.

**OS / platform support:** Pure Python wheels, no compiled extensions. Linux, macOS, Windows all supported equally. ARM and x86 supported equally.

**Async-only.** No sync facade in v1.0. The library requires `asyncio` (or `anyio` via httpx2's internals). `trio` compatibility is best-effort because httpx2 supports it; not directly tested.

### Installation Methods

**Primary install:**
```
pip install httpware
```

**Compatible package managers:** anything that reads `pyproject.toml`:
- `uv add httpware` / `uv pip install httpware`
- `poetry add httpware`
- `pdm add httpware`
- `pixi add --pypi httpware`
- `rye add httpware`

**Build backend:** `uv-build` (matching `base-client`'s recent migration). PEP 517/518 compliant.

**Distribution:** PyPI (primary), GitHub Releases (binary attestations). Releases are git-tagged and signed; provenance via PyPI Trusted Publishers / Sigstore attestation. SBOM published with each release.

**Extras (optional install groups):**

| Extra | Pulls in | Purpose |
|---|---|---|
| `httpware[msgspec]` | `msgspec` | Faster validator path (alternate `ResponseDecoder`) |
| `httpware[otel]` | `opentelemetry-api`, `opentelemetry-sdk` | OpenTelemetry instrumentation middleware |
| `httpware[niquests]` | `niquests` (post-v1.0) | `NiquestsTransport` backend |
| `httpware[all]` | everything above | Convenience |

Base install (no extras) ships with httpx2, pydantic, and standard library only.

### IDE Integration

- **`py.typed` marker** ships with the package — type checkers treat `httpware` as fully typed inline.
- **Full type coverage:** every public symbol carries explicit annotations. `ty` (Astral) passes on `httpware/` and on a reference consumer project.
- **Generic-aware:** `response_model: type[T] | None = None` keyword refines the return type to `T` when supplied, `Response` when omitted. Verified via `ty`-checked examples in the test suite.
- **Hover docs:** every public class and method carries a one-line docstring with usage example. Auto-extracted to API reference via mkdocstrings.
- **Type checker:** `ty` (Astral) exercised in CI; matches `modern-python/modern-di` and the org's house convention.
- **No IDE plugin required.** PyCharm, VS Code (Pylance), Helix, Neovim — all benefit equally from the inline types.

### API Surface

Top-level public exports from `httpware`:

| Symbol | Kind | Purpose |
|---|---|---|
| `AsyncClient` | class | The main client |
| `Request`, `Response` | dataclass | First-class request/response types |
| `Transport` | Protocol | Pluggable transport interface |
| `Httpx2Transport` | class | Default httpx2-backed transport |
| `RecordedTransport` | class | Test-only transport for mocking |
| `Middleware`, `Next` | Protocol | Onion middleware contract |
| `before_request`, `after_response`, `on_error` | decorator | Phase-shortcut helpers |
| `Retry`, `RetryBudget`, `Bulkhead`, `Timeout`, `Observability` | class | Built-in middleware |
| `ResponseDecoder` | Protocol | Pluggable validation interface |
| `PydanticDecoder`, `MsgspecDecoder` | class | Default decoders |
| `Limits`, `Timeout` (config types) | dataclass | Connection / timeout config |
| `ClientError`, `TransportError`, `TimeoutError`, `StatusError`, `BadRequestError`, `UnauthorizedError`, `ForbiddenError`, `NotFoundError`, `ConflictError`, `UnprocessableEntityError`, `RateLimitedError`, `InternalServerError`, `ServiceUnavailableError` | exception | Status-keyed hierarchy |

Approximate count: ~25 public symbols. Stability tier: all exports are public-stable from v1.0; private helpers live in `httpware._internal` (underscore-prefixed, not re-exported).

### Code Examples

**Quickstart (10 LOC):**

```python
from httpware import AsyncClient
from pydantic import BaseModel

class User(BaseModel):
    id: int
    name: str

async def main():
    async with AsyncClient(base_url="https://api.example.com") as client:
        user = await client.get("/users/1", response_model=User)
        print(user.name)
```

**Service-client subclass pattern:**

```python
from dataclasses import dataclass
from httpware import AsyncClient

@dataclass
class BillingClient:
    client: AsyncClient

    @classmethod
    def from_url(cls, base_url: str, *, token: str) -> "BillingClient":
        return cls(client=AsyncClient(base_url=base_url, auth=token))

    async def get_invoice(self, invoice_id: str) -> Invoice:
        return await self.client.get(f"/invoices/{invoice_id}", response_model=Invoice)
```

**Custom middleware (signing):**

```python
from httpware import Middleware, Next, Request, Response
import hmac, hashlib

class SignRequestMiddleware:
    def __init__(self, secret: bytes) -> None:
        self._secret = secret

    async def __call__(self, req: Request, next: Next) -> Response:
        sig = hmac.new(self._secret, req.body or b"", hashlib.sha256).hexdigest()
        return await next(req.with_header("X-Signature", sig))

client = AsyncClient(base_url="...", middleware=[SignRequestMiddleware(SECRET)])
```

**Test fixture (RecordedTransport):**

```python
import pytest
from httpware import AsyncClient, RecordedTransport, Response, NotFoundError

@pytest.fixture
def transport() -> RecordedTransport:
    return RecordedTransport({
        ("GET", "/users/1"): Response(status=200, json={"id": 1, "name": "ada"}),
        ("GET", "/users/2"): Response(status=404, json={"detail": "not found"}),
    })

async def test_user_ok(transport):
    client = AsyncClient(base_url="https://x", transport=transport)
    user = await client.get("/users/1", response_model=User)
    assert user.name == "ada"
    assert transport.calls[0].url.path == "/users/1"

async def test_user_missing(transport):
    client = AsyncClient(base_url="https://x", transport=transport)
    with pytest.raises(NotFoundError) as exc:
        await client.get("/users/2", response_model=User)
    assert exc.value.status == 404
```

**Streaming:**

```python
async with client.stream("GET", "/events") as resp:
    async for line in resp.iter_lines():
        process(line)
```

### Migration Guide (deliverable outline)

The migration guide is a v1.0 release blocker. Structure:

1. **Why migrate** — 200 words. Link to brief, focus on: the `encode/httpx` → `pydantic/httpx2` stewardship transition (which `base-client` consumers need to handle anyway), and on resilience correctness.
2. **What's changing** — at-a-glance table:
   - `httpx.AsyncClient` → `httpware.AsyncClient` (constructor kwargs largely compatible; httpware uses httpx2 under the hood)
   - `httpx.Request` / `httpx.Response` → `httpware.Request` / `httpware.Response`
   - `httpx.HTTPStatusError` → status-keyed exception (`NotFoundError` etc.)
   - `httpx.codes.is_*` → status-keyed exception branching
   - `httpx._client.USE_CLIENT_DEFAULT` → `httpware.Unset()` sentinel
   - `httpx.Timeout(1)` → `httpware.Timeout(connect=5, read=30, ...)`
   - `respx.mock` decorator → `RecordedTransport` fixture
   - `circuit_breaker_box.Retrier` → built-in `Retry` middleware
   - `tenacity.retry(...)` decorators → constructor `retries=N` or `Retry` middleware
3. **Step-by-step migration** — six concrete steps, each with a "before" and "after" code block:
   1. Replace `httpx.AsyncClient` construction
   2. Update method signatures returning `Response`
   3. Replace error handling (`except httpx.*` → `except StatusError` subclasses)
   4. Replace `respx` test fixtures with `RecordedTransport`
   5. Remove `circuit_breaker_box.Retrier` and `tenacity` decorators
   6. Verify OpenTelemetry/observability hookup
4. **Side-by-side reference appendix** — full before/after for one example service.
5. **Gotchas** — known semantic differences (e.g., exception fields are plain types, not `httpx.Response`; the underlying transport is now `httpx2`, not `httpx` — but this is invisible to consumer code through the `httpware.*` types).

### Implementation Considerations

- **Single-file core or split modules?** Split: `client.py`, `request.py`, `response.py`, `errors.py`, `middleware/__init__.py` (+ one file per built-in middleware), `transports/httpx2.py`, `transports/recorded.py`, `decoders/pydantic.py`, `decoders/msgspec.py`, `_internal/*`.
- **Concurrency model.** Single shared `AsyncClient` per event loop. Pool lifecycle bound to the client's async context manager. `from_url(...)` classmethod helper for one-line construction.
- **State immutability.** `Request`/`Response` are frozen dataclasses. `req.with_header(...)` returns a new instance. Prevents middleware action-at-a-distance bugs.
- **Cancellation.** `asyncio.CancelledError` propagates unchanged through middleware (it is *excluded* from retry/breaker failure classification).
- **Logging.** Library emits no `print` and no top-level logger configuration. Observability middleware emits structured logs via a configurable logger and OpenTelemetry spans/metrics — but only if the observability extra is installed. No log emission in the hot path of unconfigured installs.
- **Sensible failure mode for missing extras.** If a user passes `decoder=MsgspecDecoder()` without `httpware[msgspec]` installed, raise `ImportError` with a pointer to the install command. No silent fallbacks.

## Project Scoping & Phased Development

### MVP Strategy & Philosophy

**MVP approach: Problem-solving MVP.** The minimum useful version of `httpware` is whatever lets one `modern-python` team migrate one production service off `base-client` and ship it. Everything else — niquests, circuit breakers, msgspec adapter, OpenAPI codegen — is post-MVP value, not MVP value. We don't ship a "platform" or a "revenue MVP"; we ship a working framework for a single concrete migration target, then expand once it survives contact with production.

**Delivery mode: Phased.** Three phases: **MVP / Growth / Vision** — feature contents defined in the *Product Scope* section above. Phase boundaries are not changing in this step.

**Why phased over single-release:** The dependency between phases is real and ordered:
- Growth features (niquests transport, reference circuit breaker, msgspec, FastAPI integration recipes) all require a stable MVP abstraction as their foundation. Shipping them simultaneously would force premature surface decisions.
- Vision features (LLM preset, OpenAPI codegen, in-house circuit breaker) require Growth-phase external adoption signals to justify the implementation cost.
- Phasing also lets us ship v1.0 quickly with a small public surface, then expand the surface in 2.x releases with clear backward-compatibility commitments.

### Resource Requirements

- **Maintainer count (current):** 1-2 active, plus drive-by contributors. Explicit named-maintainer accounting and bus-factor target deferred per maintainer preference; to be revisited before v1.0 cut.
- **Build effort (MVP):** Estimated 2-3 calendar months of part-time engineering for a primary author with code-review support. Planning estimate: 1500-2000 LOC core + tests (acknowledged as possibly conservative; realistic ceiling 4000-6000 LOC including streaming edge cases, exception mapping, and property-based test infrastructure).
- **Dependencies:** httpx2 (>=2.0.0, <3.0; httpx2 v2.0.0 GA published to PyPI on 2026-05-12), pydantic v2, opentelemetry-api (optional), msgspec (optional), purgatory (referenced from companion CB package only, not MVP).
- **Infrastructure spend:** Zero beyond free-tier GitHub Actions CI, PyPI publishing, Read the Docs (or GitHub Pages) docs hosting.
- **Skills required:** Mid-senior Python async; familiarity with httpx/httpx2 internals; light resilience-engineering exposure (Finagle/Polly literacy helpful for retry budget). No specialized domain expertise needed.

### Phase Boundaries (recap)

See *Product Scope* section above for full feature lists. Summary:

| Phase | Goal | Feature highlights | Exit criteria |
|---|---|---|---|
| **MVP (v1.0)** | One service migrated, framework stable | Transport protocol, Httpx2Transport, single-call typed-response API, onion middleware, Retry + RetryBudget + Bulkhead + Timeout + Observability, status-keyed exceptions, RecordedTransport, streaming, migration guide | ≥1 production consumer in `modern-python` stable for 30 days |
| **Growth (v1.x → v2.x)** | Multi-transport proven, ecosystem seeded | NiquestsTransport, reference CB middleware (wraps purgatory), msgspec decoder, OTel auto-instrumentation, `client.gather`, FastAPI/Litestar recipes, public benchmark suite | All known `base-client` consumers migrated; ≥3 external PyPI dependents |
| **Vision (v3+)** | Category leader, codegen ecosystem | LLM-gateway preset, sync API hierarchy (if demand), OpenAPI codegen target, in-house CB (only if purgatory-wrap is inadequate), middleware registry, distributed resilience state | Cited externally as the recommended Python resilience-first HTTP framework |

### Risk Mitigation Strategy

Project-level risks beyond what the Innovation section covered:

**Technical risks**

- **Retry budget concurrency correctness.** Highest-novelty, highest-stakes piece. Mitigation: property-based test suite (Hypothesis) ≥10,000 trials covering concurrent failure scenarios; explicit invariants documented; retry budget is constructor-disabled (`retry_budget=None`) so users can opt out if a bug surfaces.
- **Transport semantic differences across backends.** Deferred risk — v1.0 is httpx2-only. NiquestsTransport in Growth phase validates the abstraction; if niquests's timeout/streaming semantics don't fit cleanly, we resolve via adapter shims without consumer-side breakage.
- **httpx2 private-API drift.** The current `base-client` imports from `httpx._client` and `httpx._types` (encode/httpx). `httpware`'s `Httpx2Transport` must avoid private-API usage entirely — verified by a CI check (`grep 'httpx2\._'` returns 0 inside `httpware/`). If httpx2 GA changes public APIs from the beta, we adapt one file (`transports/httpx2.py`); no consumer-visible change.

**Market risks**

- **External adoption may not materialize.** Mitigation: framed as upside, not a v1.0 gate. Primary success criterion is internal `modern-python` migration, which is within our control. External adoption signals (≥3 PyPI dependents) are Growth-phase, not MVP-phase.
- **The pydantic/httpx2 fork resolved the governance concern (2026-05-11) before v1.0 cut.** Reality check: this is the world we're in. Mitigation: the framework's value is multi-axis. Even with the strategic-risk argument now historical, the resilience composition, typed responses, RecordedTransport, and status-keyed exception hierarchy are standalone wins. The transport-agnostic layer becomes about good design hygiene rather than strategic insurance, but remains durable value (NiquestsTransport, future backends).
- **A vendor (Stainless, Pydantic AI, etc.) releases a competing framework.** Mitigation: low likelihood — Stainless's strategy is per-API SDKs not frameworks; Pydantic AI is LLM-specific. If a credible competitor emerges, we adapt positioning to lean into resilience and middleware composability (where competitors are weakest).

**Resource risks**

- **Bus-factor and maintainer attention.** Explicitly acknowledged. Mitigation strategy: (a) keep MVP core small (1500-4000 LOC) so the maintainable surface is finite; (b) keep extensions plug-in (Growth-phase features like circuit breaker, niquests, msgspec, codegen all live behind protocols and optional extras), so partial neglect doesn't break consumers; (c) sustainability section deferred per maintainer call but recognized as a real v1.0-cut decision point.
- **Maintainer attention shift mid-build.** If active development pauses post-MVP, consumers stay on a working httpx2-backed library indefinitely. No external dependencies force release cadence. Degradation is graceful — no daily releases needed for the library to keep working.
- **Funding.** None required. OSS project, no infrastructure costs beyond free-tier CI/docs hosting. Not a risk vector.

## Functional Requirements

### Client Construction & Lifecycle

- **FR1:** A consumer can construct an `AsyncClient` with optional `base_url`, default headers, default query parameters, timeout, limits, auth, transport, decoder, and middleware list.
- **FR2:** A consumer can construct an `AsyncClient` via `AsyncClient.from_url(base_url, ...)` for one-line default configuration.
- **FR3:** A consumer can use the client as an async context manager (`async with`), binding its lifecycle to a code block and closing the transport on exit.
- **FR4:** A consumer can derive a new client with overridden defaults via `client.with_options(**overrides)` that shares the underlying transport and connection pool.
- **FR5:** A consumer can pass authentication as a static string, a synchronous callable returning a string, an async callable returning a string, or a custom `Middleware` instance.
- **FR6:** A consumer can configure connection limits (`max_connections`, `max_keepalive_connections`, `keepalive_expiry`) and timeouts (split `connect`/`read`/`write`/`pool` or a single value) at client construction.

### Request & Response

- **FR7:** A consumer can issue GET, POST, PUT, PATCH, DELETE, HEAD, and OPTIONS requests via dedicated methods, plus arbitrary methods via `client.request(method, url, ...)`.
- **FR8:** A consumer can override per-request headers, query parameters, cookies, timeout, and provide body via `json=`, `data=` (form), `files=` (multipart), or `content=` (raw).
- **FR9:** A consumer receives an `httpware.Response` exposing `status: int`, `headers: Mapping`, `content: bytes`, `text: str`, `json()`, `url`, and `elapsed`, with no references to the underlying transport's types.
- **FR10:** A consumer can request a typed response by passing `response_model=T` to any request method, receiving a value of type `T` directly.
- **FR11:** A consumer can issue a streaming request via `async with client.stream(method, url, ...) as resp`, consuming the body through `iter_bytes(chunk_size)`, `iter_text(chunk_size)`, or `iter_lines()`.

### Transport Layer

- **FR12:** The framework defines a `Transport` Protocol that any HTTP-client backend must satisfy to be usable.
- **FR13:** A consumer can supply a custom `Transport` implementation at client construction.
- **FR14:** The framework ships a default `Httpx2Transport` adapting `httpx2.AsyncClient` to the `Transport` Protocol.
- **FR15:** The framework guarantees that swapping the `Transport` implementation requires no changes to consumer code that does not directly reference transport-specific types (i.e., conforming consumer code remains valid).
- **FR16:** The framework's public exports do not include the underlying HTTP client's types; `httpx2.*` is not re-exported.

### Middleware System

- **FR17:** A consumer can supply an ordered list of `Middleware` instances at client construction; each is invoked for every request in declared order (outer to inner).
- **FR18:** A consumer can implement a `Middleware` by providing an async callable matching `(req: Request, next: Next) -> Response`.
- **FR19:** A consumer can author middleware using `@before_request`, `@after_response`, and `@on_error` decorators on simple async functions.
- **FR20:** The framework documents a stable middleware execution order (`Observability → RetryBudget → Retry → [extension slot] → Bulkhead → Timeout → Transport`) and a named extension slot for plug-in middleware.
- **FR21:** A consumer can short-circuit the middleware chain by not calling `next` and returning a synthesized `Response` directly.
- **FR22:** `Request` objects are immutable; a consumer mutates a request via `req.with_header(...)`, `req.with_url(...)`, etc., each returning a new instance.

### Resilience

- **FR23:** The framework retries failed requests according to a configurable policy specifying max attempts, backoff curve, retryable status codes, and retryable exception types.
- **FR24:** The framework retries only idempotent methods (GET, HEAD, PUT, DELETE) by default; POST and PATCH require explicit opt-in.
- **FR25:** The framework applies full-jitter exponential backoff between retry attempts and honors a `Retry-After` response header when present.
- **FR26:** The framework enforces a retry budget (token-bucket admission control) capping total retries-per-second across the client; rejected retry attempts surface the original error without further retry.
- **FR27:** A consumer can configure or disable the retry budget at client construction.
- **FR28:** The framework enforces a per-host bulkhead (concurrency cap) when configured; requests exceeding the cap queue or fail-fast per configuration.
- **FR29:** The framework enforces a per-attempt timeout; timed-out attempts raise `TimeoutError` and are eligible for retry.
- **FR30:** A consumer can plug a circuit-breaker middleware (or any other resilience primitive) into the documented extension slot without library changes; a built-in circuit breaker is not provided in v1.0.

### Validation & Typed Responses

- **FR31:** The framework defines a `ResponseDecoder` Protocol that adapts raw response bytes to a typed model.
- **FR32:** The framework ships a default pydantic-based `ResponseDecoder` that caches `TypeAdapter` instances per model type and validates JSON in a single pass.
- **FR33:** The framework ships an alternate msgspec-based `ResponseDecoder` available via the `httpware[msgspec]` install extra.
- **FR34:** A consumer can supply a custom `ResponseDecoder` at client construction.
- **FR35:** A consumer can decode responses into pydantic models, dataclasses, TypedDict, `list[T]`, `dict[K, V]`, primitives, and any other type the chosen decoder supports.

### Error Handling

- **FR36:** The framework raises `httpware`-owned exceptions only; consumer code does not need to import the underlying transport's exception types.
- **FR37:** The framework provides a status-keyed exception hierarchy: `BadRequestError`, `UnauthorizedError`, `ForbiddenError`, `NotFoundError`, `ConflictError`, `UnprocessableEntityError`, `RateLimitedError`, `InternalServerError`, `ServiceUnavailableError`, plus base classes `ClientStatusError` (4xx), `ServerStatusError` (5xx), and `StatusError` (any non-2xx).
- **FR38:** The framework provides `TransportError` for connection/network failures and `TimeoutError` for client-side timeouts, both distinct from status errors.
- **FR39:** Every exception exposes plain-typed fields: `status: int`, `body: bytes`, `headers: Mapping[str, str]`, `json: Any | None`, `request_method: str`, `request_url: str`. No transport-typed objects are attached.
- **FR40:** The framework excludes `asyncio.CancelledError` from automatic retry and from resilience-middleware failure accounting; cancellation propagates unchanged through the middleware chain.

### Testing Support

- **FR41:** The framework ships a `RecordedTransport` test double accepting a mapping of `(method, url_pattern) → Response | Exception` and exposing received requests as `.calls`.
- **FR42:** A consumer can construct a client with `transport=RecordedTransport({...})` to drive tests without network access or external mocking libraries.
- **FR43:** `RecordedTransport` supports both response side-effects (returning a stub `Response`) and exception side-effects (raising a stub exception); recorded calls are inspectable for method, URL, headers, and body.

### Observability

- **FR44:** The framework emits lifecycle hooks for: request start, request complete, retry attempted, retry budget exhausted, per-attempt timeout, and exception raised — each accepting a user-supplied callable.
- **FR45:** The framework ships an OpenTelemetry instrumentation middleware (available via `httpware[otel]`) that produces spans and metrics conforming to OpenTelemetry HTTP-client semantic conventions.
- **FR46:** A consumer can inspect the runtime state of the retry budget (remaining tokens, in-use ratio) via a public API on the `RetryBudget` middleware for `/healthz`-style integration.
- **FR47:** The framework does not configure global logging or emit logs in its hot path unless observability middleware is explicitly installed.

## Non-Functional Requirements

### Performance

- **NFR1:** Per-request framework overhead — measured as the wall-clock delta of `client.get(url, response_model=User)` vs raw `httpx2.AsyncClient` + manual `pydantic.TypeAdapter(User).validate_json(...)` — is ≤15% on typical 5KB JSON payloads at 100 RPS sustained. Measured by the published benchmark suite on every release.
- **NFR2:** `TypeAdapter` instances are cached per `response_model`; the default pydantic decoder constructs zero `TypeAdapter` instances per request after warm-up.
- **NFR3:** The default `ResponseDecoder` uses `validate_json(response.content)` (single parse pass), not `validate_python(json.loads(content))` (two parse passes).
- **NFR4:** No synchronous I/O, no blocking calls (e.g., `requests`, `time.sleep`), and no GIL-heavy work on the framework hot path beyond what the chosen transport and decoder require.
- **NFR5:** Cold-start (first `import httpware` + first request) completes in ≤200ms on Python 3.11 on a developer-class machine (single-core baseline >2GHz).

### Security

- **NFR6:** TLS certificate verification is enabled by default. Disabling requires explicit `verify=False` per-client or per-request.
- **NFR7:** A configurable secret-redaction hook is invoked on every header and body fragment emitted to logs, OpenTelemetry spans, or `repr()` output. Default redacted-header allowlist includes `Authorization`, `Cookie`, `Set-Cookie`, `X-Api-Key`, `X-Auth-Token`, `Proxy-Authorization`.
- **NFR8:** No request or response body is emitted to logs or spans by default. Body capture is opt-in per middleware configuration.
- **NFR9:** Releases are published via PyPI Trusted Publishers with Sigstore attestation. A SBOM (CycloneDX or SPDX) is attached to each GitHub Release.
- **NFR10:** A `SECURITY.md` at the repo root documents the vulnerability disclosure channel and commits to a 90-day private-disclosure window before public disclosure.

### Concurrency & Throughput

- **NFR11:** A single `AsyncClient` instance supports concurrent requests up to its configured `max_connections` limit without framework-introduced lock contention beyond what the underlying transport requires.
- **NFR12:** `RetryBudget` token accounting is concurrency-safe: a Hypothesis property-based test suite of ≥10,000 concurrent-access trials passes without token-count drift, invariant violations, or race conditions.
- **NFR13:** Middleware execution is per-request and stateless by default. Any shared state across requests is the consumer's responsibility and must be explicit.
- **NFR14:** An `AsyncClient` instance is bound to its creating event loop; cross-loop sharing of a single client instance is not supported and is documented as undefined behavior.

### Reliability & Correctness

- **NFR15:** `asyncio.CancelledError` is never swallowed, transformed, or counted as a failure by any built-in middleware. It propagates through the entire middleware chain unchanged.
- **NFR16:** Streaming-response context managers guarantee the underlying connection is returned to the pool on consumer-raised exceptions (including `CancelledError`) and on normal exit.
- **NFR17:** All public types pass `ty` (Astral) type checking on Python 3.11+. A `py.typed` marker ships with the package.
- **NFR18:** No breaking changes to any public symbol within the v1.x release line. Deprecations carry a one-minor-version warning period (emitted via `DeprecationWarning`) before removal in v2.0.

### Integration

- **NFR19:** OpenTelemetry instrumentation conforms to the current OpenTelemetry HTTP-client semantic conventions (`http.request.method`, `url.full`, `http.response.status_code`, `http.client.request.duration`, etc.). Conformance is validated by a CI check that imports the OTel semconv schema and asserts emitted-attribute coverage.
- **NFR20:** Compatible with pydantic v2 (`>=2.0, <3.0`) and msgspec (`>=0.18`); a migration plan to pydantic v3 is documented when v3 ships, but compatibility is not pre-promised.
- **NFR21:** The library imports cleanly and operates correctly alongside FastAPI, Starlette, and Litestar (validated by a smoke-test CI job using each framework). Integration recipes ship as Growth-phase deliverables.
- **NFR22:** Project metadata follows PEP 621 (`pyproject.toml`); install and build succeed under `pip`, `uv`, `poetry`, and `pdm` using the `uv-build` PEP 517 backend.

### Maintainability & Quality

- **NFR23:** Line coverage on `httpware/` core modules (transports and decoders excluded, since both are largely adapter code) is ≥90%, enforced in CI.
- **NFR24:** Property-based tests (Hypothesis) cover concurrency-sensitive primitives: `RetryBudget`, `Bulkhead`, retry interleaving with timeouts, request immutability under middleware mutation. ≥10,000 trials per CI run.
- **NFR25:** CI runs on every push and pull request, exercising: `ruff` lint, `ty` type check on `httpware/` and on a reference consumer project, `pytest` with coverage, the property-based suite, and a smoke test against a real httpbin/httpbingo endpoint.

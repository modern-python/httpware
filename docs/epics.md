---
stepsCompleted:
  - step-01-validate-prerequisites
  - step-02-design-epics
  - step-03-create-stories
  - step-04-final-validation
status: complete
inputDocuments:
  - docs/prd.md
  - docs/architecture.md
  - docs/product-brief-httpware.md
  - docs/product-brief-httpware-distillate.md
project_name: httpware
updated: 2026-05-12
update_note: "Reflects the pydantic/httpx2 fork (2026-05-11); transport adapter, dependencies, and CI grep stories switched from encode/httpx 0.28 to pydantic/httpx2 2.0.0b1."
---

# httpware - Epic Breakdown

## Overview

This document provides the complete epic and story breakdown for `httpware`, decomposing the requirements from the PRD and Architecture into implementable stories. The library has no UI; no UX Design document applies.

## Requirements Inventory

### Functional Requirements

**Client Construction & Lifecycle**
- FR1: Consumer can construct `AsyncClient` with optional `base_url`, default headers, default query params, timeout, limits, auth, transport, decoder, and middleware list.
- FR2: Consumer can construct `AsyncClient` via `AsyncClient.from_url(base_url, ...)` for one-line default configuration.
- FR3: Consumer can use the client as an async context manager (`async with`), closing the transport on exit.
- FR4: Consumer can derive a new client with overridden defaults via `client.with_options(**overrides)` sharing transport/pool.
- FR5: Consumer can pass auth as static string, sync callable, async callable, or custom `Middleware`.
- FR6: Consumer can configure connection limits (max_connections, max_keepalive, expiry) and timeouts (split or single).

**Request & Response**
- FR7: Consumer can issue GET, POST, PUT, PATCH, DELETE, HEAD, OPTIONS via dedicated methods plus `client.request(method, url, ...)`.
- FR8: Consumer can override per-request headers, query, cookies, timeout; provide body via `json=`, `data=`, `files=`, or `content=`.
- FR9: Consumer receives `httpware.Response` exposing `status`, `headers`, `content`, `text`, `json()`, `url`, `elapsed` — no transport types.
- FR10: Consumer can request a typed response by passing `response_model=T`, receiving a value of type `T`.
- FR11: Consumer can stream via `async with client.stream(...) as resp` with `iter_bytes`, `iter_text`, `iter_lines`.

**Transport Layer**
- FR12: Framework defines a `Transport` Protocol any HTTP-client backend must satisfy.
- FR13: Consumer can supply a custom `Transport` at client construction.
- FR14: Framework ships default `Httpx2Transport` adapting `httpx2.AsyncClient`.
- FR15: Swapping `Transport` requires no consumer code changes beyond construction.
- FR16: Framework's public exports do not include underlying HTTP client's types; `httpx2.*` is not re-exported.

**Middleware System**
- FR17: Consumer can supply ordered list of `Middleware` instances at client construction.
- FR18: Consumer can implement `Middleware` via async callable matching `(req, next) -> Response`.
- FR19: Consumer can author middleware via `@before_request`, `@after_response`, `@on_error` decorators.
- FR20: Framework documents stable middleware execution order (`Observability → RetryBudget → Retry → [extension slot] → Bulkhead → Timeout → Transport`) with named extension slot.
- FR21: Consumer can short-circuit the middleware chain by not calling `next` and returning a synthesized `Response`.
- FR22: `Request` objects are immutable; mutation via `req.with_header(...)` etc. returns new instance.

**Resilience**
- FR23: Framework retries failed requests per configurable policy (attempts, backoff, retryable statuses, retryable exceptions).
- FR24: Framework retries only idempotent methods (GET/HEAD/PUT/DELETE) by default; POST/PATCH opt-in.
- FR25: Full-jitter exponential backoff between retries; honor `Retry-After` header.
- FR26: Framework enforces retry budget (token-bucket admission control) capping retries/sec; rejected retries surface original error.
- FR27: Consumer can configure or disable retry budget at construction.
- FR28: Framework enforces per-host bulkhead (concurrency cap) with queue or fail-fast.
- FR29: Framework enforces per-attempt timeout; timed-out attempts raise `TimeoutError` and are retry-eligible.
- FR30: Consumer can plug a circuit-breaker (or other resilience primitive) into the documented extension slot without library changes; no built-in CB in v1.0.

**Validation & Typed Responses**
- FR31: Framework defines a `ResponseDecoder` Protocol adapting raw response bytes to a typed model.
- FR32: Framework ships default pydantic-based `ResponseDecoder` with cached `TypeAdapter` and single-pass JSON validation.
- FR33: Framework ships msgspec-based `ResponseDecoder` via `httpware[msgspec]` extra.
- FR34: Consumer can supply custom `ResponseDecoder` at construction.
- FR35: Consumer can decode into pydantic models, dataclasses, TypedDict, `list[T]`, `dict[K,V]`, primitives.

**Error Handling**
- FR36: Framework raises `httpware`-owned exceptions only; no transport-specific exceptions surface to consumers.
- FR37: Framework provides status-keyed exception hierarchy: BadRequest, Unauthorized, Forbidden, NotFound, Conflict, UnprocessableEntity, RateLimited, InternalServerError, ServiceUnavailable; base classes ClientStatusError (4xx), ServerStatusError (5xx), StatusError.
- FR38: Framework provides `TransportError` for connection/network failures and `TimeoutError` for client-side timeouts.
- FR39: Every exception exposes plain-typed fields: `status: int`, `body: bytes`, `headers: Mapping`, `json: Any | None`, `request_method: str`, `request_url: str`.
- FR40: Framework excludes `asyncio.CancelledError` from automatic retry and resilience-middleware failure accounting.

**Testing Support**
- FR41: Framework ships `RecordedTransport` accepting `(method, url_pattern) → Response | Exception` mapping; exposes `.calls`.
- FR42: Consumer can construct client with `transport=RecordedTransport({...})` to drive tests without network.
- FR43: `RecordedTransport` supports both response and exception side-effects; calls inspectable for method, URL, headers, body.

**Observability**
- FR44: Framework emits lifecycle hooks: request start, request complete, retry attempted, retry budget exhausted, per-attempt timeout, exception raised.
- FR45: Framework ships OpenTelemetry instrumentation middleware via `httpware[otel]` extra, conforming to OTel HTTP-client semconv.
- FR46: Consumer can inspect retry-budget runtime state (tokens remaining, in-use ratio) for `/healthz` integration.
- FR47: Framework does not configure global logging or emit logs in hot path unless observability middleware is explicitly installed.

### NonFunctional Requirements

**Performance**
- NFR1: Per-request framework overhead ≤15% over raw `httpx2.AsyncClient` + manual pydantic at 100 RPS on 5KB JSON payloads. Benchmark published with each release.
- NFR2: `TypeAdapter` instances cached per `response_model`; zero per-request construction after warm-up.
- NFR3: Default `ResponseDecoder` uses `validate_json(content)`, single parse pass.
- NFR4: No synchronous I/O, blocking calls, or GIL-heavy work on framework hot path.
- NFR5: Cold-start (first import + first request) ≤200ms on Python 3.11 developer-class machine.

**Security**
- NFR6: TLS verification enabled by default; opt-out via explicit `verify=False`.
- NFR7: Configurable secret-redaction hook invoked on every header/body emission. Default redacted-header allowlist: Authorization, Cookie, Set-Cookie, X-Api-Key, X-Auth-Token, Proxy-Authorization.
- NFR8: No request/response body emitted to logs or spans by default.
- NFR9: Releases via PyPI Trusted Publishers + Sigstore attestation; SBOM attached to each GitHub Release.
- NFR10: SECURITY.md documents disclosure channel with 90-day private-disclosure window.

**Concurrency & Throughput**
- NFR11: Single `AsyncClient` supports concurrent requests up to `max_connections` without framework-introduced lock contention beyond transport's requirements.
- NFR12: `RetryBudget` token accounting concurrency-safe under ≥10,000 Hypothesis trials with no race conditions or invariant violations.
- NFR13: Middleware execution is per-request and stateless by default; shared state is consumer responsibility.
- NFR14: `AsyncClient` bound to creating event loop; cross-loop sharing is documented undefined behavior.

**Reliability & Correctness**
- NFR15: `asyncio.CancelledError` is never swallowed, transformed, or counted as failure by any built-in middleware.
- NFR16: Streaming-response context managers guarantee underlying connection returns to pool on any exception including `CancelledError`.
- NFR17: All public types pass `ty` (Astral) type checking on Python 3.11+; `py.typed` marker ships.
- NFR18: No breaking changes within v1.x; deprecations carry one-minor-version `DeprecationWarning` before removal.

**Integration**
- NFR19: OpenTelemetry instrumentation conforms to OTel HTTP-client semantic conventions; CI-validated.
- NFR20: Compatible with pydantic v2 (`>=2.0, <3.0`) and msgspec (`>=0.18`).
- NFR21: Imports cleanly alongside FastAPI, Starlette, Litestar; smoke-tested in CI.
- NFR22: PEP 621 `pyproject.toml`; install/build succeed under `pip`, `uv`, `poetry`, `pdm` using `uv_build` PEP 517 backend.

**Maintainability & Quality**
- NFR23: ≥90% line coverage on `httpware/` core modules (transports/decoders excluded), enforced in CI.
- NFR24: Property-based tests (Hypothesis) cover concurrency-sensitive primitives (RetryBudget, Bulkhead, retry interleaving, request immutability) with ≥10,000 trials per CI run.
- NFR25: CI runs on every push/PR: ruff lint, ty type check on `httpware/` and reference consumer, pytest with coverage, property suite, real-endpoint smoke test.

### Additional Requirements

From Architecture document — technical requirements that shape epic and story design:

**Project scaffold (Epic 1 Story 1 — starter template):**
- Initialize with `uv init --lib httpware`; build backend is `uv_build` (PEP 517)
- Copy org conventions from `modern-python/modern-di`: `Justfile`, `.github/workflows/`, `[tool.ruff]` config, `ty` lint dep, `[tool.pytest.ini_options]`, release flow
- Add: `py.typed` marker, `SECURITY.md`, `CONTRIBUTING.md`, `LICENSE` (MIT), `CHANGELOG.md`, `CLAUDE.md`, `context7.json`
- `pyproject.toml` declares: `httpx2>=2.0.0,<3.0`, `pydantic>=2.0,<3.0`; extras `[msgspec]`, `[otel]`, `[niquests]`
- Layout: `src/httpware/` with capability-aligned modules (`client.py`, `request.py`, `response.py`, `errors.py`, `config.py`, `middleware/`, `transports/`, `decoders/`, `_internal/`)
- Lint group: `ruff`, `ty`, `eof-fixer`, `typing-extensions`
- Dev group: `pytest`, `pytest-cov`, `pytest-asyncio`, `pytest-repeat`, `pytest-benchmark`, `hypothesis`

**Protocol seams (load-bearing — must implement to support all FRs):**
- Seam 1: `Middleware ↔ Transport` (chain bottom calls `transport.__call__`)
- Seam 2: `AsyncClient ↔ Middleware` (chain composed at construction)
- Seam 3: `AsyncClient ↔ ResponseDecoder` (called when `response_model` provided)
- Seam 4: `Httpx2Transport ↔ httpx2` (only module importing httpx2; exception mapping table)
- Seam 5: `httpware ↔ optional extras` (extras imported only inside their modules)

**Architectural decisions to apply across all stories (12 numbered decisions):**
1. Request/Response as `dataclasses.dataclass(frozen=True, slots=True)`
2. `Transport` protocol with async `__call__`, `stream` context manager, `aclose`
3. httpx2→httpware exception mapping table in `transports/httpx2.py` only
4. Recursive async-callable onion middleware with explicit `Next` type alias
5. RetryBudget = `asyncio.Lock` + monotonic-clock token bucket
6. Pure-Python retry (no `tenacity` dependency)
7. `asyncio.Semaphore`-based bulkhead with weakref-keyed per-host registry
8. `ResponseDecoder` protocol with cached `TypeAdapter` pydantic adapter
9. `AsyncClient` holds immutable `ClientConfig`; `with_options()` returns new client sharing transport
10. Separate `StreamResponse` type with `_release` callable; `@asynccontextmanager` ensures release
11. Two-layer observability: Layer 1 hooks always-on, Layer 2 OTel middleware extras-gated
12. `Redactor` class registered on client, invoked at every emission point

**Implementation patterns (10 categories) — must be enforced for all code in all stories:**
- Module/class/function/variable naming (Python conventions + project-specific)
- Project structure (src/ layout, tests/ at root, examples/ excluded from wheel)
- Type-hint style (no `from __future__ import annotations`, PEP 604/585, `# ty: ignore` not `# type: ignore`)
- Async naming (no `a` prefix except `aclose`)
- Exception construction (keyword-only, plain fields, no transport types)
- Logging (single `logging.getLogger("httpware")`, DEBUG only, no global config)
- Optional-extra imports (top-of-module try/except ImportError with install hint)
- Public API exports (`__all__` in `__init__.py`, API-snapshot CI test)
- Test conventions (`pytest-asyncio` auto mode, `RecordedTransport` only, property-based tests in `_props.py`)
- Docstring style (PEP 257; class/method required, missing-docstring `D1` ignored)

**Migration deliverable (release blocker for Epic that includes v1.0 cut):**
- Migration guide from `base-client` to `httpware` with per-symbol replacement table, before/after code blocks, side-by-side example, and known gotchas

### UX Design Requirements

Not applicable. `httpware` is a developer library with no user interface. No UX Design document exists for this project.

### FR Coverage Map

| FR | Epic | Note |
|---|---|---|
| FR1 | 1 | `AsyncClient(**kwargs)` |
| FR2 | 1 | `AsyncClient.from_url(...)` |
| FR3 | 1 | `async with AsyncClient(...) as c:` |
| FR4 | 1 | `client.with_options(**overrides)` |
| FR5 | 2 | auth coercion `str \| Callable \| Middleware` |
| FR6 | 1 | `Limits`, `Timeout` config |
| FR7 | 1 | HTTP methods + `request()` |
| FR8 | 1 | per-request overrides + body forms |
| FR9 | 1 | `Response` with plain fields |
| FR10 | 1 | `response_model=T` |
| FR11 | 4 | streaming |
| FR12 | 1 | `Transport` protocol |
| FR13 | 1 | custom `Transport` at construction |
| FR14 | 1 | `Httpx2Transport` default |
| FR15 | 1 | transport swap with zero consumer changes |
| FR16 | 1 (enforced by Story 6.4 CI gate) | no httpx2 in public exports |
| FR17 | 2 | middleware list at construction |
| FR18 | 2 | `Middleware` protocol with `(req, next)` |
| FR19 | 2 | phase-shortcut decorators |
| FR20 | 2 (extension slot doc in 3.6, observability ordering in 5.1) | chain ordering |
| FR21 | 2 | short-circuit middleware |
| FR22 | 2 | `Request` immutability helpers |
| FR23 | 3 | Retry policy |
| FR24 | 3 | idempotent-method default |
| FR25 | 3 | full-jitter + Retry-After |
| FR26 | 3 | RetryBudget token bucket |
| FR27 | 3 | configure/disable budget |
| FR28 | 3 | Bulkhead semaphore |
| FR29 | 3 | per-attempt Timeout |
| FR30 | 3 | extension-slot documentation |
| FR31 | 1 | `ResponseDecoder` protocol |
| FR32 | 1 | pydantic decoder |
| FR33 | 1 | msgspec decoder (extras-gated) |
| FR34 | 1 | custom decoder via constructor |
| FR35 | 1 | decode targets (pydantic, dataclasses, etc.) |
| FR36 | 1 | exception ownership |
| FR37 | 1 | status-keyed exception hierarchy |
| FR38 | 1 | `TransportError`, `TimeoutError` |
| FR39 | 1 | plain exception fields |
| FR40 | 1 (`CancelledError` discipline reinforced in every later epic) | `CancelledError` excluded |
| FR41 | 1 | `RecordedTransport` |
| FR42 | 1 | construct client with `RecordedTransport` |
| FR43 | 1 | call inspection / side-effects |
| FR44 | 5 | lifecycle hook callbacks |
| FR45 | 5 | OTel middleware |
| FR46 | 3 | RetryBudget state inspection |
| FR47 | 5 | no global logging |

## Epic List

### Epic 1: Make typed HTTP requests with sensible defaults
A developer installs `httpware`, writes `await client.get(url, response_model=User)`, gets a typed result, handles errors with status-keyed exceptions, and tests it via `RecordedTransport`. The library is useful as-is — independently shippable as a v0.1.0.
**FRs covered:** FR1, FR2, FR3, FR4, FR6, FR7, FR8, FR9, FR10, FR12, FR13, FR14, FR15, FR16, FR31, FR32, FR33, FR34, FR35, FR36, FR37, FR38, FR39, FR40, FR41, FR42, FR43

### Epic 2: Compose request-handling logic via middleware
A developer writes custom middleware (signing, correlation IDs, tracing) and composes it into their client. The framework's extensibility is real and ergonomic.
**FRs covered:** FR5, FR17, FR18, FR19, FR20, FR21, FR22

### Epic 3: Survive upstream failures with composable resilience
A developer's client survives 429s, retries idempotent methods, doesn't retry-storm via the budget, caps per-host concurrency, and times out per-attempt. Production-ready resilience without bolting on `tenacity` or a buggy circuit-breaker.
**FRs covered:** FR23, FR24, FR25, FR26, FR27, FR28, FR29, FR30, FR46

### Epic 4: Stream responses without buffering
A developer streams large downloads or SSE/LLM responses without loading them into memory; pool returns are guaranteed on any exception including `CancelledError`.
**FRs covered:** FR11

### Epic 5: Observe and instrument the client
A developer instruments their client with lifecycle hooks, integrates with OpenTelemetry exporters, and ships with sensible secret redaction. Operations team can observe retry storms, budget exhaustion, and breaker rejections from a real Grafana board.
**FRs covered:** FR44, FR45, FR47

### Epic 6: Ship v1.0
A `base-client` consumer reads the migration guide, swaps imports, and ships on `httpware` within a few hours. The library is publicly trustable — signed releases, SBOM, security disclosure channel, public benchmarks.
**FRs covered:** (none directly; ships the deliverables required by Success Criteria, NFR9, NFR10, NFR18, NFR23–25, and the migration-guide release blocker)

---

## Epic 1: Make typed HTTP requests with sensible defaults

A developer installs `httpware`, writes `await client.get(url, response_model=User)`, gets a typed result, handles errors with status-keyed exceptions, and tests it via `RecordedTransport`. Independently shippable as v0.1.0.

### Story 1.1: Project scaffold and tooling

As a `httpware` maintainer,
I want a fully-configured project skeleton with the org's conventions,
So that subsequent stories can implement library code without fighting tooling.

**Acceptance Criteria:**

**Given** a fresh checkout of a new GitHub repo at `modern-python/httpware`
**When** I run `uv init --lib httpware` followed by the org-convention port from `modern-python/modern-di`
**Then** the repo has `src/httpware/__init__.py`, `src/httpware/py.typed`, `pyproject.toml` declaring `httpx2>=2.0.0,<3.0` and `pydantic>=2.0,<3.0` as dependencies
**And** extras `[msgspec]`, `[otel]`, `[niquests]`, `[all]` are declared
**And** dev/lint dep groups match `modern-di` (pytest, pytest-cov, pytest-asyncio, pytest-repeat, pytest-benchmark, hypothesis; ruff, ty, eof-fixer, typing-extensions)
**And** `[tool.ruff]`, `[tool.pytest.ini_options]` match `modern-di` with `target-version = "py311"`
**And** root files exist: `Justfile`, `LICENSE` (MIT), `SECURITY.md`, `CONTRIBUTING.md`, `CHANGELOG.md`, `CLAUDE.md`, `context7.json`, `.gitignore`
**And** `.github/workflows/ci.yml` runs `ruff check`, `ty`, `pytest --cov` on Python 3.11–3.14
**And** `uv build` produces a wheel and `pip install dist/*.whl` succeeds in a clean venv

### Story 1.2: Core data types

As a library author,
I want immutable `Request`, `Response`, `Limits`, `Timeout`, and `ClientConfig` types,
So that every other module has stable primitives to build on.

**Acceptance Criteria:**

**Given** the scaffold from Story 1.1
**When** I implement `src/httpware/request.py`, `src/httpware/response.py`, `src/httpware/config.py`
**Then** `Request` is a `@dataclass(frozen=True, slots=True)` with fields `method: str`, `url: str`, `headers: Mapping[str, str]`, `params: Mapping[str, str]`, `cookies: Mapping[str, str]`, `body: bytes | None`, `extensions: Mapping[str, Any]`
**And** `Request` has methods `with_header(name, value) -> Request`, `with_url(url) -> Request`, `with_body(body) -> Request`, `with_query(params) -> Request`, each returning a new instance via `dataclasses.replace`
**And** `Response` is a `@dataclass(frozen=True, slots=True)` with fields `status: int`, `headers: Mapping[str, str]`, `content: bytes`, `url: str`, `elapsed: float`
**And** `Response.text` and `Response.json()` are computed accessors (not stored)
**And** `Limits`, `Timeout`, `ClientConfig` are frozen dataclasses with the defaults specified in the architecture (`Timeout(connect=5, read=30, write=30, pool=5)`, `Limits(max_connections=100, max_keepalive_connections=20, keepalive_expiry=5.0)`)
**And** `ty` passes; tests cover `with_*` immutability and that two `Request` instances with identical fields compare equal

### Story 1.3: Exception hierarchy with plain fields

As a consumer developer,
I want a status-keyed exception hierarchy with plain typed fields,
So that I can catch `NotFoundError` etc. without importing httpx2 and without inspecting transport types.

**Acceptance Criteria:**

**Given** `Request` and `Response` types from Story 1.2
**When** I implement `src/httpware/errors.py`
**Then** the module defines `ClientError`, `TransportError`, `TimeoutError`, `StatusError(ClientError)`, `ClientStatusError(StatusError)`, `ServerStatusError(StatusError)`, and the leaf classes `BadRequestError`, `UnauthorizedError`, `ForbiddenError`, `NotFoundError`, `ConflictError`, `UnprocessableEntityError`, `RateLimitedError`, `InternalServerError`, `ServiceUnavailableError`
**And** every status exception's `__init__` takes only keyword arguments: `status: int`, `body: bytes`, `headers: Mapping[str, str]`, `json: Any | None`, `request_method: str`, `request_url: str`
**And** a module-level dict `STATUS_TO_EXCEPTION: Mapping[int, type[StatusError]]` maps the canonical status codes to their leaf exceptions
**And** unknown 4xx falls back to `ClientStatusError`; unknown 5xx falls back to `ServerStatusError`
**And** `__repr__` format is `"<ExceptionClass status=NNN method=GET url=...>"` and never includes body or headers
**And** `__all__` lists every exception; `ty` passes

### Story 1.4: Transport protocol and Httpx2Transport adapter

As a library author,
I want a `Transport` protocol and a default `Httpx2Transport` implementation,
So that the entire library talks to one abstraction and httpx2 is confined to a single file.

**Acceptance Criteria:**

**Given** the data types and exception hierarchy from Stories 1.2 and 1.3
**When** I implement `src/httpware/transports/__init__.py` and `src/httpware/transports/httpx2.py`
**Then** `Transport` is a `@runtime_checkable Protocol` with three methods: `async def __call__(self, request: Request) -> Response`, `def stream(self, request: Request) -> AbstractAsyncContextManager[StreamResponse]` (signature only — implementation deferred to Epic 4 with `NotImplementedError`), `async def aclose(self) -> None`
**And** `Httpx2Transport` accepts a `httpx2.AsyncClient` (or constructs a default one from `Limits` / `Timeout`) and implements `__call__` by translating `Request` → `httpx2.Request`, awaiting `client.send`, and translating back to `Response`
**And** `Httpx2Transport.__call__` maps every `httpx2.HTTPError` subclass to a `httpware` exception per the architecture's mapping table, and never lets an `httpx2` exception escape
**And** `Httpx2Transport.__call__` raises one of `BadRequestError`/.../`ServiceUnavailableError`/`ClientStatusError`/`ServerStatusError` for any non-2xx response
**And** `grep -r 'import httpx2\|from httpx2' src/httpware/` returns matches only inside `transports/httpx2.py`
**And** tests cover: success path, each mapped exception class for representative httpx2 exceptions, status-code mapping for 200/400/401/403/404/409/422/429/500/503

### Story 1.5: ResponseDecoder protocol and pydantic adapter

As a consumer developer,
I want to decode response bodies into pydantic models in a single parse pass,
So that `response_model=User` returns a typed `User` with minimal overhead.

**Acceptance Criteria:**

**Given** the `Response` type from Story 1.2
**When** I implement `src/httpware/decoders/__init__.py` and `src/httpware/decoders/pydantic.py`
**Then** `ResponseDecoder` is a `@runtime_checkable Protocol` with method `def decode(self, content: bytes, model: type[T]) -> T`
**And** `PydanticDecoder.decode(content, model)` calls `_get_adapter(model).validate_json(content)` where `_get_adapter` is `@functools.lru_cache(maxsize=None)`-decorated and returns `pydantic.TypeAdapter(model)`
**And** unit tests verify: decoding into a pydantic `BaseModel`, into a `dataclass`, into `list[User]`, into `dict[str, User]`, into a primitive `int`
**And** a benchmark test confirms ≥2× faster than `pydantic.TypeAdapter(model).validate_python(json.loads(content))` on a 5KB JSON payload (NFR3)
**And** a test verifies the cache: 1000 calls to `decode(content, User)` construct exactly one `TypeAdapter` (NFR2)

### Story 1.6: msgspec decoder via extras

As a consumer developer with high-throughput needs,
I want to plug in a msgspec decoder via `pip install httpware[msgspec]`,
So that I get faster validation than pydantic with the same `response_model=` API.

**Acceptance Criteria:**

**Given** the `ResponseDecoder` protocol from Story 1.5
**When** I implement `src/httpware/decoders/msgspec.py`
**Then** the module imports `msgspec` at the top and on `ImportError` raises with message `"MsgspecDecoder requires the 'msgspec' extra. Install with: pip install httpware[msgspec]"`
**And** `MsgspecDecoder.decode(content, model)` calls `msgspec.json.decode(content, type=model)`
**And** `pyproject.toml`'s `[project.optional-dependencies]` declares `msgspec = ["msgspec>=0.18"]`
**And** importing `httpware` (without `httpware[msgspec]` installed) does not import `msgspec` (verified by an import-time test)
**And** unit tests cover decoding into `msgspec.Struct` and into pydantic models (msgspec also handles those)

### Story 1.7: AsyncClient with HTTP methods, response_model, with_options, lifecycle

As a consumer developer,
I want a single `AsyncClient` class that I can construct, use, and close — issuing HTTP requests with optional typed responses,
So that I have the v0.1.0 entry point of the library.

**Acceptance Criteria:**

**Given** Stories 1.2–1.6
**When** I implement `src/httpware/client.py`
**Then** `AsyncClient.__init__` accepts (keyword-only): `base_url: str | None`, `default_headers: Mapping[str, str] | None`, `default_query: Mapping[str, str] | None`, `timeout: Timeout | float | None`, `limits: Limits | None`, `transport: Transport | None`, `decoder: ResponseDecoder | None`, `middleware: list[Middleware] | None` (parameter present but ignored — wired in Epic 2)
**And** if `transport` is omitted, a default `Httpx2Transport` is constructed from `limits` and `timeout`
**And** if `decoder` is omitted, a `PydanticDecoder` is used
**And** `AsyncClient.from_url(base_url, **kwargs)` is a classmethod returning an `AsyncClient`
**And** the client implements `__aenter__` returning `self` and `__aexit__` calling `transport.aclose()`
**And** methods `get`, `post`, `put`, `patch`, `delete`, `head`, `options`, `request` all exist with overloads such that `response_model: type[T] | None = None` returns `T` when `T` is provided and `Response` when `None`; `ty` validates the overload against an example consumer
**And** every method accepts per-call overrides: `headers`, `params`, `cookies`, `timeout`, `json`, `data`, `files`, `content`
**And** `client.with_options(**overrides)` returns a new `AsyncClient` sharing the same `transport` instance
**And** integration tests issue a real GET to `httpbingo.org/json`, decode into a pydantic model, assert success
**And** unit tests verify `with_options` returns a different instance with the same transport reference

### Story 1.8: RecordedTransport for testing

As a consumer developer,
I want a built-in `RecordedTransport` test double,
So that I can write tests without `respx` and without mocking transport-level types.

**Acceptance Criteria:**

**Given** the `Transport` protocol from Story 1.4 and `Response` from Story 1.2
**When** I implement `src/httpware/transports/recorded.py`
**Then** `RecordedTransport(routes: Mapping[tuple[str, str], Response | Exception])` constructs the transport with a route table keyed by `(method, url_pattern)`
**And** `await transport(request)` looks up `(request.method, request.url)` in routes; on match, returns the `Response` or raises the `Exception`; on no match, raises `RuntimeError(f"No route for {request.method} {request.url}")`
**And** every received `Request` is appended to `transport.calls: list[Request]`
**And** url-pattern matching supports exact match (v0.1.0 scope; regex/glob deferred)
**And** unit tests verify: response side-effect, exception side-effect, `.calls[0].method` and `.calls[0].url` inspection, raise on missing route
**And** a documentation example shows a 3-line pytest fixture wiring `RecordedTransport` to `AsyncClient` and asserting on `.calls`

---

## Epic 2: Compose request-handling logic via middleware

A developer writes custom middleware (signing, correlation IDs, tracing) and composes it into their client.

### Story 2.1: Middleware protocol, Next type, and chain composition

As a library author,
I want a `Middleware` protocol with explicit `Next` semantics and a chain composer,
So that built-in and user middleware live on the same axis and compose correctly.

**Acceptance Criteria:**

**Given** the `Request`, `Response`, `Transport` types from Epic 1
**When** I implement `src/httpware/middleware/__init__.py` and `src/httpware/_internal/chain.py`
**Then** `Next` is exported as `type Next = Callable[[Request], Awaitable[Response]]` (PEP 695 if 3.12+, else `TypeAlias`)
**And** `Middleware` is a `@runtime_checkable Protocol` with `async def __call__(self, request: Request, next: Next) -> Response`
**And** `compose(middlewares: list[Middleware], transport: Transport) -> Next` returns a coroutine that, when called with a `Request`, invokes the outermost middleware, which receives a `Next` that calls the second middleware, …, with the bottom of the chain calling `transport.__call__`
**And** an empty middleware list composes to a `Next` that calls `transport.__call__` directly
**And** unit tests verify: ordering (outer-to-inner), short-circuit (a middleware that doesn't call `next` returns its synthesized `Response`), `CancelledError` propagation through every middleware (NFR15)

### Story 2.2: Phase-shortcut decorators

As a consumer developer,
I want `@before_request`, `@after_response`, `@on_error` decorators,
So that I can write simple lifecycle hooks without authoring a full `Middleware` class.

**Acceptance Criteria:**

**Given** the `Middleware` protocol from Story 2.1
**When** I implement decorator helpers in `src/httpware/middleware/__init__.py`
**Then** `@before_request` wraps `async def f(req: Request) -> Request` into a `Middleware` that applies `f` then calls `await next(req)`
**And** `@after_response` wraps `async def f(req: Request, resp: Response) -> Response` into a `Middleware` that calls `await next(req)` then applies `f`
**And** `@on_error` wraps `async def f(req: Request, exc: BaseException) -> Response | None` into a `Middleware` that catches `Exception` (NOT `BaseException`, so `CancelledError` propagates), calls `f`; if `f` returns a `Response`, return it; if `f` returns `None`, re-raise; never catches `CancelledError`
**And** unit tests verify each phase shortcut composes correctly with other middleware and respects `CancelledError`

### Story 2.3: Request immutability helpers

As a consumer developer,
I want ergonomic `with_*` mutators on `Request`,
So that middleware can rewrite requests immutably.

**Acceptance Criteria:**

**Given** the `Request` type from Story 1.2
**When** I extend `Request` with additional helpers
**Then** `with_header(name: str, value: str) -> Request` returns a new `Request` with the header added or replaced
**And** `with_headers(headers: Mapping[str, str]) -> Request` returns a new `Request` with the supplied headers merged in
**And** `with_url(url: str) -> Request`, `with_body(body: bytes | None) -> Request`, `with_query(params: Mapping[str, str]) -> Request` exist and behave consistently
**And** every `with_*` returns a new `Request`; the original is unchanged (verified by tests)
**And** the same helpers exist on `Response` where they make sense (`with_headers`, `with_status`)

### Story 2.4: Auth coercion as middleware

As a consumer developer,
I want to pass `auth=` as a string, callable, or full `Middleware`,
So that simple cases are one-liners and complex cases are still possible.

**Acceptance Criteria:**

**Given** the `Middleware` protocol from Story 2.1
**When** I implement auth normalization in `src/httpware/middleware/__init__.py` (or `_internal/auth.py`)
**Then** `_normalize_auth(value: str | Callable[[], str | Awaitable[str]] | Middleware | None) -> Middleware | None` returns a `Middleware`
**And** `_normalize_auth("token")` returns a middleware that adds `Authorization: Bearer token` header to every request
**And** `_normalize_auth(lambda: "token")` returns a middleware that calls the callable per request and adds the header
**And** `_normalize_auth(my_middleware)` returns `my_middleware` unchanged
**And** `_normalize_auth(None)` returns `None`
**And** unit tests verify each branch and that the bearer-scheme middleware is the second-to-innermost (just outside transport) when auto-added

### Story 2.5: Wire middleware into AsyncClient

As a consumer developer,
I want my supplied `middleware=[...]` list to actually run when I issue requests,
So that the framework's extensibility is real.

**Acceptance Criteria:**

**Given** Stories 2.1–2.4 and the `AsyncClient` from Story 1.7
**When** I update `AsyncClient.__init__` and the request-issuing methods
**Then** the constructor composes `middleware + ([_normalize_auth(auth)] if auth else [])` with `compose(...)` against the transport, storing the resulting `Next` callable on `self._dispatch`
**And** `client.get(url, ...)` builds a `Request` and awaits `self._dispatch(req)` instead of `self._transport(req)` directly
**And** an integration test passes `middleware=[trace_middleware, sign_middleware]` and verifies both ran in declared order
**And** `client.with_options(middleware=[...])` returns a new client with a recomposed chain (not sharing the cached `_dispatch` of the parent)

---

## Epic 3: Survive upstream failures with composable resilience

A developer's client survives 429s, retries idempotent methods, doesn't retry-storm via the budget, caps per-host concurrency, and times out per-attempt.

### Story 3.1: Timeout middleware (per-attempt)

As a consumer developer,
I want a per-attempt timeout that I can configure separately from total request time,
So that long retries don't compound into runaway operations.

**Acceptance Criteria:**

**Given** the `Middleware` protocol from Epic 2
**When** I implement `src/httpware/middleware/timeout.py`
**Then** `Timeout(seconds: float)` is a middleware that wraps `await next(req)` in `asyncio.timeout(seconds)`
**And** on timeout, raises `httpware.TimeoutError(...)` with `request_method`, `request_url` populated
**And** `CancelledError` from outer cancellation propagates without being caught (distinguish via `asyncio.timeout` semantics — outer cancel cancels the whole task; inner timeout fires `TimeoutError`)
**And** unit tests verify: timeout fires when downstream sleeps longer than the limit; outer `task.cancel()` propagates without conversion to `TimeoutError`

### Story 3.2: Retry middleware

As a consumer developer,
I want my client to retry transient failures with full-jitter exponential backoff,
So that intermittent upstream errors don't surface to my code.

**Acceptance Criteria:**

**Given** the `Middleware` protocol and exception hierarchy
**When** I implement `src/httpware/middleware/retry.py`
**Then** `Retry(max_attempts: int = 3, base_delay: float = 0.5, max_delay: float = 8.0, retryable_statuses: frozenset[int] = frozenset({429, 500, 502, 503, 504}), retryable_exceptions: tuple[type[BaseException], ...] = (TransportError, TimeoutError), idempotent_methods: frozenset[str] = frozenset({"GET", "HEAD", "PUT", "DELETE"}), respect_retry_after: bool = True)` is the constructor
**And** the middleware retries only on idempotent methods OR if the request has an explicit `extensions["idempotent"] = True` marker
**And** backoff delay = `random.uniform(0, base_delay * 2 ** (attempt - 1))`, capped at `max_delay`; if response carries `Retry-After` (seconds or HTTP-date) AND `respect_retry_after`, use that instead
**And** `CancelledError` short-circuits the retry loop (NFR15)
**And** unit tests cover: retry on 503, retry on `TransportError`, no retry on 4xx (except 429), no retry on POST without explicit marker, `Retry-After` honored, max-attempts respected, full-jitter distribution sampled

### Story 3.3: RetryBudget data structure

As a library author,
I want a concurrency-safe token-bucket data structure with monotonic-clock refill,
So that the retry budget primitive can be tested in isolation before being wrapped as middleware.

**Acceptance Criteria:**

**Given** stdlib `asyncio` and `time` only (no third-party concurrency libs)
**When** I implement `src/httpware/_internal/clock.py` (`monotonic()` wrapper) and `src/httpware/middleware/retry_budget.py`'s internal `_TokenBucket` class
**Then** `_TokenBucket(min_per_sec: float, ratio: float, ttl: float)` stores `tokens_remaining: float`, `last_refill_at: float`, an `asyncio.Lock`
**And** `await _TokenBucket.try_acquire(cost: float = 1.0) -> bool` refills based on monotonic-clock delta then attempts to deduct `cost`; returns True on success, False on insufficient tokens
**And** the lock is held only across the refill+deduct, never across an `await` to user code
**And** Hypothesis property tests (`test_middleware_retry_budget_props.py`) cover ≥10,000 trials with concurrent acquires from `asyncio.gather` and verify: tokens never go negative, refill rate honors `min_per_sec` floor and `ratio` cap, no double-spend
**And** the test runs in CI as part of the regular pytest suite (no special invocation)

### Story 3.4: RetryBudget middleware integration

As a consumer developer,
I want a retry budget wrapped into a middleware with state-inspection API,
So that I can cap retry traffic across my whole client and observe budget state from `/healthz`.

**Acceptance Criteria:**

**Given** the `_TokenBucket` from Story 3.3
**When** I implement `RetryBudget` middleware in `src/httpware/middleware/retry_budget.py`
**Then** `RetryBudget(min_per_sec: float = 10.0, ratio: float = 0.2, ttl: float = 10.0)` is the constructor (Finagle defaults)
**And** the middleware tracks "is this attempt a retry?" via `request.extensions["retry_attempt"]` (set by the `Retry` middleware before re-issuing); if it is a retry, it must acquire a token from the bucket before calling `next`; if acquisition fails, it raises the original exception or returns the original response (whichever it received from upstream)
**And** the middleware exposes public read-only properties `tokens_remaining: float`, `in_use_ratio: float` for `/healthz`-style integration (FR46)
**And** unit tests verify: budget exhaustion under sustained-failure load short-circuits subsequent retries; non-retry attempts are never gated; `tokens_remaining` reflects actual state under concurrent load

### Story 3.5: Bulkhead middleware

As a consumer developer,
I want per-host concurrency caps,
So that one slow upstream can't saturate my client's connection pool.

**Acceptance Criteria:**

**Given** the `Middleware` protocol
**When** I implement `src/httpware/middleware/bulkhead.py`
**Then** `Bulkhead(max_concurrent: int, key: Callable[[Request], str] = lambda r: urlparse(r.url).hostname or "", on_full: Literal["queue", "fail_fast"] = "queue")` is the constructor
**And** the middleware maintains a `weakref.WeakValueDictionary[str, asyncio.Semaphore]` of per-key semaphores, lazily created
**And** with `on_full="queue"`, requests await semaphore acquisition; with `on_full="fail_fast"`, requests over the cap raise `BulkheadFullError(TransportError)`
**And** `CancelledError` during semaphore acquisition releases the slot (verified by test)
**And** unit tests verify: concurrency cap is enforced; per-host isolation (one slow host doesn't block another); fail-fast raises `BulkheadFullError` immediately

### Story 3.6: Document the extension slot

As a third-party middleware author,
I want a documented contract for plugging a circuit-breaker (or any resilience primitive) into the middleware chain,
So that I can ship a reusable `httpware-circuit-breaker` package in v1.x without library changes.

**Acceptance Criteria:**

**Given** Epic 2's middleware system and Stories 3.1–3.5
**When** I update `src/httpware/middleware/__init__.py`'s docstring and `docs/concepts/middleware.md`
**Then** the documented chain ordering names the slot explicitly: `Observability → RetryBudget → Retry → [extension slot] → Bulkhead → Timeout → Transport`
**And** the docs explain when middleware should plug into the slot (per-attempt rejection / accounting; circuit-breaker semantics) vs. another position
**And** an example in `examples/circuit_breaker_with_purgatory.py` demonstrates wrapping `purgatory` as a middleware in the slot, showing it works without library changes (this example is post-MVP and may be a stub in v1.0; the docs section is the deliverable here)

---

## Epic 4: Stream responses without buffering

A developer streams large downloads or SSE/LLM responses without loading them into memory; pool returns are guaranteed on any exception.

### Story 4.1: StreamResponse type

As a consumer developer,
I want a `StreamResponse` distinct from `Response`,
So that I can't accidentally call `.content` on a streaming response and force a buffer.

**Acceptance Criteria:**

**Given** the `Response` type from Epic 1
**When** I extend `src/httpware/response.py`
**Then** `StreamResponse` is a `@dataclass(frozen=True, slots=True)` with fields `status: int`, `headers: Mapping[str, str]`, `url: str`, and private fields `_stream: AsyncIterator[bytes]`, `_release: Callable[[], Awaitable[None]]`
**And** `iter_bytes(chunk_size: int = 8192)` returns an async iterator yielding `bytes` chunks from `_stream`
**And** `iter_text(chunk_size: int = 8192, encoding: str | None = None)` decodes incrementally; encoding inferred from `Content-Type` header if not supplied
**And** `iter_lines()` yields decoded lines split on `\n`, handling chunk boundaries
**And** `StreamResponse` does NOT have `.content`, `.text`, or `.json()` attributes (compile-time hint via `__slots__`)
**And** unit tests with a stub `_stream` verify each iterator produces the expected output

### Story 4.2: Transport.stream implementation in Httpx2Transport

As a library author,
I want `Httpx2Transport.stream` to actually open a streaming response and yield it via the `StreamResponse` type,
So that the streaming path through Transport works end-to-end.

**Acceptance Criteria:**

**Given** the `Transport` protocol from Story 1.4 (which already declares `stream`) and `StreamResponse` from Story 4.1
**When** I implement `Httpx2Transport.stream` in `src/httpware/transports/httpx2.py`
**Then** `transport.stream(request)` is an `@asynccontextmanager` that calls `httpx2.AsyncClient.stream(...)`, wraps the resulting httpx2 response into a `StreamResponse` with `_stream = response.aiter_raw()` and `_release = response.aclose`
**And** the context manager calls `_release` in a `finally` block, including on `CancelledError` propagation (NFR16)
**And** httpx2 exception → httpware exception mapping is applied at this seam, same table as `__call__`
**And** `RecordedTransport.stream` is also implemented: yields a `StreamResponse` whose `_stream` iterates over a pre-supplied list of byte chunks
**And** integration tests verify: stream a 1MB response from `httpbingo.org/stream-bytes/1048576` without exceeding 100KB resident memory beyond baseline; stream is properly released when the consumer breaks out of the iteration early

### Story 4.3: AsyncClient.stream context manager

As a consumer developer,
I want `async with client.stream("GET", url) as resp:` semantics on the public client,
So that I can write SSE/LLM/large-download code idiomatically.

**Acceptance Criteria:**

**Given** Stories 4.1, 4.2 and the `AsyncClient` from Epic 1
**When** I add `AsyncClient.stream` to `src/httpware/client.py`
**Then** `client.stream(method: str, url: str, **kwargs) -> AbstractAsyncContextManager[StreamResponse]` builds a `Request` and delegates to `transport.stream(request)`, ensuring the middleware chain is also applied (chain composition for streaming is identical to non-streaming, but the `Next` returns a `StreamResponse` instead of `Response`)
**And** if a middleware in the chain doesn't support streaming (returns `Response` instead of `StreamResponse`), the framework raises a clear `TypeError` at construction time, not at request time
**And** on consumer-raised exceptions inside the `async with`, `_release` is still called
**And** integration test with `RecordedTransport`: stream a multi-chunk response, raise an exception mid-iteration, verify `_release` was called

---

## Epic 5: Observe and instrument the client

A developer instruments their client with lifecycle hooks, integrates with OpenTelemetry exporters, and ships with sensible secret redaction.

### Story 5.1: Layer 1 observability middleware (lifecycle hooks)

As a consumer developer,
I want to register lifecycle callbacks for request start/complete/retry/timeout/error events,
So that I can wire my own logging or metrics without depending on OpenTelemetry.

**Acceptance Criteria:**

**Given** the `Middleware` protocol
**When** I implement `src/httpware/middleware/observability.py`
**Then** `Observability(on_request_start: Callable[[Request], None] | None = None, on_request_complete: Callable[[Request, Response], None] | None = None, on_retry_attempt: Callable[[Request, int, float], None] | None = None, on_retry_budget_exhausted: Callable[[Request], None] | None = None, on_timeout: Callable[[Request, str], None] | None = None, on_exception: Callable[[Request, BaseException], None] | None = None)` is the constructor
**And** the middleware is the **outermost** in the default chain composition order (per Decision 11)
**And** every hook is awaitable-aware: if a hook returns a coroutine, it is awaited; otherwise it's called synchronously
**And** if a hook raises, the exception is caught and logged via `logging.getLogger("httpware").debug(...)`, never propagated (an instrumentation bug must not break the request flow)
**And** unit tests verify each hook fires at the right point, async and sync hook variants both work, and a hook exception doesn't break the request

### Story 5.2: Wire emission into resilience middlewares

As an `Observability` middleware,
I want `Retry`, `RetryBudget`, `Bulkhead`, and `Timeout` middlewares to publish their internal events to me,
So that my hooks fire at the right moments.

**Acceptance Criteria:**

**Given** Story 5.1 and the resilience middlewares from Epic 3
**When** I add an event-bus-style mechanism (single shared `EventEmitter` instance attached to `Observability`)
**Then** `Retry` calls `emitter.emit("retry_attempt", request, attempt, delay)` before each retry
**And** `RetryBudget` calls `emitter.emit("retry_budget_exhausted", request)` when token acquisition fails
**And** `Timeout` calls `emitter.emit("timeout", request, "read")` (or similar phase) on timeout firing
**And** `Bulkhead` calls `emitter.emit("bulkhead_full", request)` on `fail_fast` rejection
**And** `Observability` translates emitter events into the public hook callbacks (`on_retry_attempt` etc.)
**And** if no `Observability` middleware is in the chain, emitter calls are no-ops (zero overhead)
**And** unit tests verify each event flows through to the corresponding hook

### Story 5.3: Redactor class and integration

As a consumer developer,
I want secret-bearing headers redacted from every framework emission point by default,
So that `Authorization` tokens don't end up in my Grafana board or logs.

**Acceptance Criteria:**

**Given** the `Request`, `Response`, and exception types from Epic 1
**When** I implement `Redactor` in `src/httpware/config.py` and integrate it
**Then** `Redactor(headers: frozenset[str] = DEFAULT_REDACTED_HEADERS, redact_bodies: bool = True)` is the constructor
**And** `DEFAULT_REDACTED_HEADERS = frozenset({"authorization", "cookie", "set-cookie", "x-api-key", "x-auth-token", "proxy-authorization"})` (case-insensitive matching)
**And** `Redactor.redact_headers(headers)` returns a new mapping with redacted values replaced by `"<redacted>"`
**And** `Redactor.redact_body(body)` returns `b"<redacted>"` if `redact_bodies` is True, else returns body unchanged
**And** the default `Redactor` is on the default `ClientConfig`; users can override via `AsyncClient(redactor=...)`
**And** `Request.__repr__`, `Response.__repr__`, every exception's `__repr__` invoke the client's `Redactor` (passed via `extensions["redactor"]` or a context var) before emission
**And** unit tests verify: default headers are redacted; custom redactor with extra headers works; bodies redacted by default; `redact_bodies=False` preserves body

### Story 5.4: OpenTelemetry middleware

As a consumer developer with OpenTelemetry infrastructure,
I want a drop-in OTel middleware that emits semantic-convention-conformant spans and metrics,
So that my Grafana dashboards "just work" without me writing translation code.

**Acceptance Criteria:**

**Given** Stories 5.1, 5.2, 5.3 and `pip install httpware[otel]`
**When** I implement `src/httpware/middleware/_otel.py`
**Then** the module imports `opentelemetry.trace`, `opentelemetry.metrics` at the top with the standard `try/except ImportError` install-hint pattern
**And** `OpenTelemetryMiddleware(tracer_provider=None, meter_provider=None)` constructor accepts optional OTel providers (defaults to global)
**And** every request creates a span named `"HTTP {method}"` with attributes per OTel HTTP-client semconv: `http.request.method`, `url.full`, `server.address`, `server.port`, and on response: `http.response.status_code`
**And** sensitive header values are redacted via the client's `Redactor` before becoming span attributes
**And** the middleware emits the histograms `http.client.request.duration` and counters per the semconv
**And** a CI test imports the OTel semconv schema package and asserts the middleware's emitted attribute names are a subset of the schema's HTTP-client attributes (NFR19)
**And** integration tests verify spans are created and exported via an in-memory test exporter

### Story 5.5: Logging policy enforcement

As a library maintainer,
I want a CI gate that prevents anyone from accidentally adding `print()` or top-level logging configuration,
So that the no-global-logging guarantee (NFR47) is enforced rather than convention-only.

**Acceptance Criteria:**

**Given** the `httpware` source tree
**When** I add a CI grep step
**Then** `grep -rn 'print(' src/httpware/` returns zero matches (or only matches inside `# noqa`-annotated docstrings, of which there should be none)
**And** `grep -rn 'logging.basicConfig\|logging.getLogger()' src/httpware/` returns zero matches (`logging.getLogger("httpware")` and its sub-loggers are allowed; the bare `getLogger()` form is not)
**And** `pytest -W error::Warning` runs the test suite with warnings as errors and passes — the framework must not emit any warnings during unconfigured use
**And** the CI step fails the build on violation

---

## Epic 6: Ship v1.0

A `base-client` consumer reads the migration guide, swaps imports, and ships on `httpware` within a few hours. The library is publicly trustable.

### Story 6.1: Migration guide from base-client

As a `base-client` consumer,
I want a step-by-step migration guide with side-by-side examples,
So that I can move my service to `httpware` in a day, not a week.

**Acceptance Criteria:**

**Given** all prior epics complete and a working `httpware` v0.x
**When** I author `docs/migration-from-base-client.md`
**Then** the guide includes: a "Why migrate" section linking to the PRD and noting the `encode/httpx` → `pydantic/httpx2` transition that base-client consumers need to handle anyway; an at-a-glance per-symbol replacement table covering `httpx.AsyncClient`/`Request`/`Response`/`HTTPStatusError`/`codes.is_*`/`_client.USE_CLIENT_DEFAULT`/`Timeout`, plus `respx.mock`, `circuit_breaker_box.Retrier`, and `tenacity.retry`
**And** six step-by-step migration steps, each with a "before" and "after" code block: replace AsyncClient construction; update Response handling; replace error handling; replace respx with RecordedTransport; remove Retrier and tenacity decorators; verify OTel hookup
**And** a side-by-side reference appendix migrating one full example service from `base-client/examples/` to `httpware`
**And** a "Gotchas" section calling out: exception fields are plain types not `httpx.Response` (and not `httpx2.Response`); `auth=` union accepts string for static bearer tokens; `with_options` returns a new client (not mutates); the underlying transport changed from `encode/httpx` to `pydantic/httpx2` but this is invisible through the `httpware.*` types
**And** the migration guide is referenced from the `httpware` README as the recommended on-ramp

### Story 6.2: Documentation site (mkdocs)

As a potential adopter,
I want a hosted documentation site with quickstart, concepts, recipes, and API reference,
So that I can evaluate `httpware` and integrate it without reading the source.

**Acceptance Criteria:**

**Given** the source code of all prior epics
**When** I author the `docs/` tree and `mkdocs.yml`
**Then** the docs build with `mkdocs build` without warnings or broken links (CI-enforced)
**And** the structure matches the architecture's Documentation Organization section (`index.md`, `quickstart.md`, `migration-from-base-client.md`, `concepts/{middleware,transports,decoders,retries-and-budget,exceptions}.md`, `recipes/{custom-middleware,authentication,observability,testing}.md`, `api/` auto-generated via `mkdocstrings`)
**And** the site is hosted on Read the Docs (or GitHub Pages) and a build is triggered from `main` and tags
**And** the README links to the hosted docs URL
**And** every public symbol has at least a one-line docstring (verified by a CI test that imports `httpware` and asserts every name in `__all__` has a non-empty `__doc__`)

### Story 6.3: Public benchmark suite

As a potential adopter and as the maintainer,
I want a public benchmark comparing `httpware` to raw `httpx2 + tenacity`,
So that the "is this slow?" objection is closed pre-emptively and we catch perf regressions.

**Acceptance Criteria:**

**Given** all prior epics
**When** I implement `benchmarks/` and add a `just bench` recipe
**Then** the suite measures end-to-end request latency for: `httpware` with default config + `response_model=User`; raw `httpx2.AsyncClient.get(...)` + manual `pydantic.TypeAdapter(User).validate_json(...)` + `tenacity.retry`; baseline `httpx2.AsyncClient.get(...)` no validation no retry
**And** the workload is 1000 sequential requests against `httpbingo.org/json` returning a 5KB JSON response, plus a 100-RPS concurrent variant
**And** the benchmark output is a Markdown table appended to `benchmarks/RESULTS.md` with median, p95, p99 latency
**And** the CI job runs the benchmark on every release tag and posts the table as a comment on the release
**And** the per-request overhead delta is asserted to be ≤15% (NFR1); the build fails the release if exceeded

### Story 6.4: CI enforcement gates

As a library maintainer,
I want CI gates that enforce the architectural invariants automatically,
So that PRs that violate them never merge.

**Acceptance Criteria:**

**Given** the source tree and CI workflow from Story 1.1
**When** I extend `.github/workflows/ci.yml`
**Then** a step runs `! grep -rE 'import httpx2|from httpx2' src/httpware/ tests/ examples/ | grep -v 'src/httpware/transports/httpx2.py'` and fails the build if it finds matches outside `transports/httpx2.py`
**And** a step runs `! grep -rE 'httpx2\._' src/httpware/` and fails on any private-API usage (NFR4 / FR16)
**And** an `__all__`-snapshot test asserts that `set(httpware.__all__)` equals a frozenset literal in `tests/test_api_surface.py`; changes require updating both files (catches accidental public-API additions per NFR18)
**And** the OTel-conformance test from Story 5.4 runs in CI
**And** the no-print / no-basicConfig grep from Story 5.5 runs in CI
**And** the property-test job from Story 3.3 runs as part of the standard pytest invocation
**And** all gates run on every push and PR; build fails on any violation

### Story 6.5: Release flow with Trusted Publishers and Sigstore

As a security-conscious consumer of `httpware`,
I want releases signed via PyPI Trusted Publishers with Sigstore attestation and an attached SBOM,
So that I can verify the artifact's provenance.

**Acceptance Criteria:**

**Given** a PyPI account configured with Trusted Publishers for `modern-python/httpware`
**When** I push a tag matching `vX.Y.Z`
**Then** `.github/workflows/publish.yml` triggers, builds the wheel and sdist via `uv build`, generates an SBOM (CycloneDX format) via `cyclonedx-py` or equivalent, and uploads to PyPI via Trusted Publishers (no PyPI API token in repo secrets)
**And** Sigstore attestation is automatically attached to the upload
**And** the SBOM is also uploaded as a release asset on the GitHub Release
**And** the release notes are auto-extracted from `CHANGELOG.md` for the matching version
**And** `SECURITY.md` documents the disclosure channel (`security@...` or GitHub Security Advisories) with a 90-day private-disclosure commitment (NFR10)
**And** a manual smoke test verifies: install from PyPI in a clean venv after the release, verify the Sigstore attestation with `cosign verify-attestation`, import `httpware`, run the quickstart example

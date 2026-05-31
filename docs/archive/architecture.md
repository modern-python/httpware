---
stepsCompleted:
  - step-01-init
  - step-02-context
  - step-03-starter
  - step-04-decisions
  - step-05-patterns
  - step-06-structure
  - step-07-validation
  - step-08-complete
status: complete
completedAt: 2026-05-11
inputDocuments:
  - docs/prd.md
  - docs/product-brief-httpware.md
  - docs/product-brief-httpware-distillate.md
workflowType: architecture
project_name: httpware
user_name: Artur Shiriev
date: 2026-05-11
updated: 2026-05-12
update_note: "Reflects the pydantic/httpx2 fork (2026-05-11); transport, dependencies, CI greps switched from encode/httpx 0.28 to pydantic/httpx2 2.0.0b1."
---

# Architecture Decision Document

_This document builds collaboratively through step-by-step discovery. Sections are appended as we work through each architectural decision together._

## Project Context Analysis

### Requirements Overview

**Functional Requirements:**
47 FRs organized into 9 capability areas: Client Construction & Lifecycle (FR1–6), Request & Response (FR7–11), Transport Layer (FR12–16), Middleware System (FR17–22), Resilience (FR23–30), Validation & Typed Responses (FR31–35), Error Handling (FR36–40), Testing Support (FR41–43), Observability (FR44–47). Each FR is implementation-agnostic and testable.

Architectural implication: each capability area maps to a discrete internal module, with clearly defined protocols at the boundaries (`Transport`, `ResponseDecoder`, `Middleware`). The public API surface is ~25 symbols — narrow on purpose to support v1.x stability commitments (NFR18).

**Non-Functional Requirements driving architecture:**

| NFR | Architectural pressure |
|---|---|
| NFR1 (≤15% framework overhead) | Shallow middleware chain; minimal per-request allocations; default-on middlewares must be efficient |
| NFR2 (cached `TypeAdapter`) | Module-level cache keyed by `response_model` — explicit memoization layer |
| NFR3 (`validate_json` single pass) | Decoder receives raw `content: bytes`, not already-parsed `dict` |
| NFR4 (no blocking calls in hot path) | Static check or test on the framework's call-graph; pure async/await throughout |
| NFR12 (RetryBudget concurrency-safe under 10k Hypothesis trials) | Either single `asyncio.Lock` or lock-free token-bucket with monotonic timestamps; design choice is load-bearing |
| NFR14 (event-loop-bound client) | Client construction binds to the active loop; transport lazy-creation must be careful about loop affinity |
| NFR15 (CancelledError never swallowed) | Every middleware must re-raise `CancelledError` without transformation; built-in middlewares CI-tested for this |
| NFR16 (streaming pool return on any exception) | Streaming context manager must use `try/finally` and guarantee transport-pool release |
| NFR17 (`ty` type check; py.typed) | Generic-aware method overloads for `response_model: type[T] | None`; protocol types must be `@runtime_checkable` or carefully designed |
| NFR18 (no v1.x breaking changes) | Internal/private modules clearly demarcated (`httpware._internal`); deprecation infra in place |
| NFR19 (OTel semconv conformance) | Observability middleware emits structured attributes per OTel HTTP-client spec, CI-validated |

**Scale & Complexity:**

- Project complexity: **medium** — low domain/regulatory load, moderate concurrency-correctness load, novel for Python ecosystem
- Primary domain: **Python async library / framework** (no service, no UI, no persistence)
- Estimated architectural components: **~10 internal modules** organized by capability area
- Core LOC estimate: 1500-2000 baseline, 4000-6000 realistic ceiling
- Public API surface: ~25 symbols
- Distribution: PyPI; pure-Python wheel; build backend `uv-build`; install extras for msgspec, otel, niquests

### Technical Constraints & Dependencies

**Hard constraints (from PRD):**

- Python 3.11+ floor (`asyncio.TaskGroup`, `except*` syntax required)
- Async-only public API; no sync facade in v1.0
- Backend HTTP client is `httpx2 >=2.0.0, <3.0` for v1.0 (Pydantic Services stewardship line; same API as `encode/httpx` 0.28); **no httpx2 private-API usage** (`httpx2._client`, `httpx2._types`) enforced by CI grep
- `pydantic >=2.0, <3.0` for default decoder
- Pure-Python; no compiled extensions, no platform-specific wheels
- All public types `py.typed`; `ty` (Astral) passes in CI
- Default `Limits`: `max_connections=100, max_keepalive=20, keepalive_expiry=5.0`
- Default `Timeout`: `connect=5, read=30, write=30, pool=5` (split, not single-value)
- OpenTelemetry semantic-convention conformance (HTTP-client spec)

**Optional dependencies (install extras):**

- `httpware[msgspec]` → `msgspec >=0.18`
- `httpware[otel]` → `opentelemetry-api`, `opentelemetry-sdk`
- `httpware[niquests]` → `niquests` (post-v1.0, Growth phase)

**Backwards-compatibility commitment:** no breaking changes within v1.x; deprecation warnings emitted one minor version before removal.

### Cross-Cutting Concerns Identified

These concerns touch every internal module and must be designed for explicitly rather than added later:

1. **Type-safety with generics.** Every request method must carry the `response_model: type[T] | None` `TypeVar` through the call chain so that `response_model=User` yields a return type of `User`, and `response_model=None` yields a `Response` wrapper. Overload signatures or `TypeIs` machinery required.
2. **Async event-loop binding.** A client instance must operate correctly within its creating loop and produce documented undefined behavior outside it. Lifecycle: construction is loop-agnostic, first I/O binds the transport to the active loop.
3. **Cancellation correctness.** `asyncio.CancelledError` is propagated unchanged through every middleware in the framework; failure-classification logic in `Retry`, `RetryBudget`, and the future circuit-breaker plug-in explicitly excludes it. Tests verify each middleware does not swallow or transform it.
4. **Immutability.** `Request` and `Response` are frozen dataclasses. Mutation methods (`req.with_header(...)`, `req.with_url(...)`) return new instances. Prevents middleware action-at-a-distance bugs and is required for safe retry rebuild.
5. **Secret redaction.** A single configurable redaction hook is invoked everywhere headers or bodies leave the framework: logs, OTel spans, exception `repr()`, debug output. Default redacted-header allowlist applies; users can extend.
6. **Observability hooks.** Lifecycle events (request start/complete, retry attempted, budget exhausted, timeout, error) are emitted from canonical points in the middleware chain. Hook signatures are stable across the v1.x line.
7. **Packaging discipline.** Optional extras must not be imported at the top-level of the base install; lazy imports gated by `ImportError` with helpful messages.
8. **Testability as a first-class concern.** `RecordedTransport` is part of `httpware` (not a separate `httpware-testing` package); consumers can ship tests against `RecordedTransport` without dev-dependency overhead.

## Starter Template Evaluation

### Primary Technology Domain

Python async library (pip-installable, PyPI-distributed). No project-template tradition equivalent to web/mobile scaffolds; convention is to start from a minimal `pyproject.toml` and add infrastructure incrementally.

### Starter Options Considered

| Option | Pros | Cons | Verdict |
|---|---|---|---|
| `uv init --lib` | Minimal, uses `uv_build` (matches PRD), src layout, no template baggage | Lacks org conventions; manual port needed | **Selected** |
| Fork `modern-python/modern-di` | Inherits org conventions (Justfile, GHA workflow, ruff config, ty config, release flow) | Heavier; manual rename pass needed | Used as reference |
| `copier` template (org-owned) | Reusable across future `modern-python` libs | None exists today; not worth building now | Deferred |
| `cookiecutter-pypackage` | Mature | Pulls conventions that don't match `modern-python` house style | Rejected |

### Selected Starter: `uv init --lib httpware`

**Rationale:**

- `uv_build` is already committed in the PRD as the PEP 517 build backend
- `uv init --lib` produces the minimum-viable scaffold (src layout, `__init__.py`, py.typed marker, `pyproject.toml`) with no opinionated extras
- Org conventions are copied from `modern-python/modern-di`, keeping the repo shape consistent with the org's house style

**Initialization Command:**

```bash
uv init --lib httpware
cd httpware
# Copy org conventions from modern-python/modern-di:
#   Justfile, .github/workflows/, [tool.ruff] config, ty config, release flow
# Add: py.typed marker, SECURITY.md, CONTRIBUTING.md, LICENSE
```

**Architectural decisions provided by starter:**

- **Language & runtime:** Python 3.11+, async-only; no compiled extensions
- **Build backend:** `uv_build` (matching `base-client` and `modern-di`; PEP 517 compliant via `[build-system] requires = ["uv_build"]`)
- **Project layout:** `src/httpware/` (src layout — keeps test code from accidentally importing local source). Note: `modern-di` itself uses a flat layout (`modern_di/` at repo root with `[tool.uv.build-backend] module-name = "modern_di"`); `uv init --lib` defaults to src layout, which is the safer choice.
- **Type marker:** `py.typed` ships in the package
- **Package manager / lock file:** `uv` (lockfile `uv.lock` committed, matching base-client and modern-di)

**Decisions NOT provided by starter (to be made in subsequent steps):**

- Internal module layout (`client.py`, `request.py`, `response.py`, `errors.py`, `middleware/`, `transports/`, `decoders/`, `_internal/`)
- Default Limits / Timeout values (committed by PRD)
- Middleware interface shape
- Transport protocol surface
- Response decoder protocol surface
- Exception hierarchy

**Tooling to copy from `modern-python/modern-di` (org-convention reference):**

- `Justfile` with `install`, `test`, `lint`, `format`, `release` recipes
- `.github/workflows/` configuration (Python 3.11–3.14 matrix; ruff, ty, pytest)
- `[tool.ruff]` config — `select = ["ALL"]`, `line-length = 120`, `target-version = "py311"` (raised from modern-di's `py310`), `fix = true`, `unsafe-fixes = true`, ignore set: `D1`, `S101`, `TCH`, `FBT`, `D203`, `D213`, `COM812`, `ISC001`
- Type checker: **`ty`** (Astral) — matches `modern-di` and the org's house preference. NOT mypy/pyright.
- `[tool.pytest.ini_options]` — `asyncio_mode = "auto"`, `asyncio_default_fixture_loop_scope = "function"`, `--cov=.` enabled
- Dev dep group: `pytest`, `pytest-cov`, `pytest-asyncio`, `pytest-repeat`, `pytest-benchmark`
- Lint dep group: `ruff`, `ty`, `eof-fixer`, `typing-extensions`
- Release flow (tag-triggered PyPI publish via Trusted Publishers, Sigstore attestation per NFR9)

**Note:** Project initialization using this approach should be the first implementation story.

## Core Architectural Decisions

### Decision Priority Analysis

**Critical decisions (block implementation):**
1. Decision 1 (Request/Response data types) — every other module depends on these primitives
2. Decision 2 (Transport protocol shape) + Decision 3 (exception mapping at the httpx2 seam)
3. Decision 8 (ResponseDecoder protocol) — enables typed responses end-to-end
4. Decision 4 (Middleware execution model) — enables the resilience layer

**Important decisions (shape architecture significantly):**
- Decision 5 (RetryBudget data structure — load-bearing for NFR12)
- Decision 6 (Retry middleware: pure-Python, no tenacity dep)
- Decision 7 (Bulkhead via `asyncio.Semaphore` per host)
- Decision 9 (AsyncClient + `with_options` pool-sharing)
- Decision 10 (Streaming response model — separate `StreamResponse` type)
- Decision 11 (Observability two-layer architecture)
- Decision 12 (Redactor at every emission point)

**Deferred decisions (post-MVP):**
- NiquestsTransport implementation details (Growth phase — same `Transport` protocol)
- Circuit-breaker middleware (Growth phase — plugs into the named extension slot)
- Sync API parallel class hierarchy (deferred; possibly never)
- OpenAPI codegen integration (Vision phase)

### Data Architecture (library-internal types)

**Decision 1 — Request/Response data types:** `dataclasses.dataclass(frozen=True, slots=True)`.

- Immutable; mutation via `dataclasses.replace`-backed `with_*` methods returning new instances
- `slots=True` cuts per-instance memory and prevents attribute typos
- Avoids pulling `pydantic.BaseModel` into the hot path; `Request`/`Response` are pure stdlib
- `Response.content: bytes` is the primitive; `.json()` and `.text` are lazy properties
- `Limits` and `Timeout` config types are also frozen dataclasses

Trade-off: rejected `attrs` (extra dep, not justified) and `pydantic.BaseModel` for primitives (NFR1 overhead budget).

### Transport Protocol & Seam

**Decision 2 — Transport protocol shape:**

```python
@runtime_checkable
class Transport(Protocol):
    async def __call__(self, request: Request) -> Response: ...
    def stream(self, request: Request) -> AbstractAsyncContextManager[StreamResponse]: ...
    async def aclose(self) -> None: ...
```

- Async `__call__` for unary requests; explicit `stream` returning an async context manager (FR11, NFR16)
- `aclose()` invoked by the client's `__aexit__`
- `@runtime_checkable` enables isinstance checks; cost is acceptable for a protocol with few methods

**Decision 3 — Exception mapping at the seam.** The `httpx2 → httpware` mapping lives entirely inside `httpware/transports/httpx2.py`. No other module imports httpx2 exception types.

| httpx2 exception | httpware exception |
|---|---|
| `ConnectError`, `NetworkError`, `ProxyError`, `UnsupportedProtocol`, `ProtocolError`, `RemoteProtocolError`, `LocalProtocolError`, `DecodingError`, `TooManyRedirects`, `InvalidURL` | `TransportError` |
| `ConnectTimeout`, `ReadTimeout`, `WriteTimeout`, `PoolTimeout` | `TimeoutError` |
| HTTP 4xx response | `BadRequestError` / `UnauthorizedError` / ... / `RateLimitedError` (per status) |
| HTTP 5xx response | `InternalServerError` / `ServiceUnavailableError` / `ServerStatusError` (default) |

Status-to-exception mapping is a module-level dict keyed by `int`; unknown 4xx → `ClientStatusError`, unknown 5xx → `ServerStatusError`.

### Middleware Execution Model

**Decision 4 — Recursive async-callable onion with explicit `Next` type alias:**

```python
Next = Callable[[Request], Awaitable[Response]]

class Middleware(Protocol):
    async def __call__(self, request: Request, next: Next) -> Response: ...
```

- Composed at client construction by folding the middleware list into a single coroutine; the bottom of the chain calls `transport.__call__`
- Short-circuit supported (middleware may not call `next`, returning a synthesized `Response`) — FR21
- Phase-shortcut decorators (`@before_request`, `@after_response`, `@on_error`) wrap user functions into a `Middleware` adapter class
- Built-in middlewares (`Retry`, `RetryBudget`, `Bulkhead`, `Timeout`, `Observability`) ship as classes implementing this protocol

Trade-off: rejected iterator-based (ASGI-style) middleware as unnecessary complexity for the linear no-branching case; rejected functional composition because it can't model after-response or short-circuit cases cleanly.

### Resilience Implementation

**Decision 5 — RetryBudget data structure:** Token bucket with `asyncio.Lock` + monotonic clock.

- Lock held only during the read-modify-write of token count (microseconds; trivial vs network latency)
- Token refill driven by `time.monotonic()` deltas; no background task or timer
- State: `tokens_remaining: float`, `last_refill_at: float`, `ratio: float`, `min_per_sec: float`, `ttl: float`
- Property-based invariants verified via Hypothesis (NFR12, ≥10,000 trials): token count never negative, refill rate honors `min_per_sec` floor and `ratio` cap, concurrent acquires never double-spend
- Public state-inspection API: `budget.tokens_remaining`, `budget.in_use_ratio` (FR46)

Trade-off: lock-free CAS rejected (Python lacks the primitives; would need third-party atomics). `asyncio.Semaphore` rejected (doesn't model refill rate).

**Decision 6 — Retry middleware:** Pure-Python (no `tenacity` dependency for v1.0).

- `RetryPolicy(max_attempts, base_delay, max_delay, retryable_statuses, retryable_exceptions, idempotent_methods, respect_retry_after)`
- Default: max 3 attempts; full-jitter exponential backoff (`delay = random.uniform(0, base * 2 ** (attempt - 1))`, capped at `max_delay=8s`)
- `Retry-After` (seconds or HTTP-date) takes precedence over computed backoff
- Only retries idempotent methods (GET/HEAD/PUT/DELETE) by default; POST/PATCH require explicit opt-in (FR24)

Trade-off: `tenacity` rejected to avoid extra dependency and keep the retry logic transparent; ~100 LOC of loop code is the cost.

**Decision 7 — Bulkhead implementation:** `asyncio.Semaphore` keyed per-host.

- Semaphore registry stored in a `weakref.WeakValueDictionary` keyed by `key(request)` (default: `request.url.host`)
- Saturation behavior configurable: `queue` (default) or `fail_fast` (raises `BulkheadFullError(TransportError)`)
- Weakrefs allow transient hosts to garbage-collect

### Validation & Decoding

**Decision 8 — ResponseDecoder protocol:**

```python
class ResponseDecoder(Protocol):
    def decode(self, content: bytes, model: type[T]) -> T: ...
```

- Operates on raw `bytes` (NFR3 — single parse pass)
- Pydantic adapter (default): `TypeAdapter(model).validate_json(content)` with `@functools.lru_cache(maxsize=None)` on `TypeAdapter` construction keyed by `model` (NFR2)
- Msgspec adapter (`httpware[msgspec]`): `msgspec.json.decode(content, type=model)`
- Custom decoders supplied via constructor; missing-extra → `ImportError` with install hint

### Configuration & Lifecycle

**Decision 9 — AsyncClient internals and `with_options`:**

- `AsyncClient` holds a single immutable `ClientConfig` frozen dataclass + a `Transport` instance
- `with_options(**overrides)` returns a new `AsyncClient` sharing the same `transport` (and connection pool) with `dataclasses.replace`-updated `config`
- Transport reference-counted via private `_ref_count` on the transport; outermost `__aexit__` calls `transport.aclose()` only when count returns to its initial value
- Auth normalization at construction: `_normalize_auth(value)` returns a `Middleware` regardless of input shape (str → static-bearer middleware; callable → token-provider middleware; Middleware → identity). FR5 union internalized.
- `AsyncClient.from_url(base_url, **kwargs)` classmethod factory builds a sensibly-configured client (FR2)

### Streaming Response Model

**Decision 10 — Separate `StreamResponse` type:**

```python
@dataclass(frozen=True, slots=True)
class StreamResponse:
    status: int
    headers: Mapping[str, str]
    url: str
    _stream: AsyncIterator[bytes]                    # private
    _release: Callable[[], Awaitable[None]]          # private

    async def iter_bytes(self, chunk_size: int = 8192) -> AsyncIterator[bytes]: ...
    async def iter_text(self, chunk_size: int = 8192) -> AsyncIterator[str]: ...
    async def iter_lines(self) -> AsyncIterator[str]: ...
```

- `client.stream(...)` is `@asynccontextmanager` that always calls `_release` on exit, including on `CancelledError` (NFR15, NFR16)
- Separate type from `Response` — prevents accidental `.content` access on streaming responses (which would force a buffer read)

### Observability Architecture

**Decision 11 — Two-layer observability:**

- **Layer 1 (free, always-on):** Lifecycle event callbacks registered on the client. Hook signatures: `on_request_start(req)`, `on_request_complete(req, resp)`, `on_retry_attempt(req, attempt, delay)`, `on_retry_budget_exhausted(req)`, `on_timeout(req, phase)`, `on_exception(req, exc)`. Called by built-in middleware at canonical points. Zero non-stdlib deps.
- **Layer 2 (opt-in via `httpware[otel]`):** `OpenTelemetryMiddleware` translates Layer-1 events into OTel spans and metrics conforming to HTTP-client semantic conventions (NFR19). Imported only when extras installed.

No global logging configuration. Library uses `logging.getLogger("httpware")` only inside the optional observability middleware; emits nothing in unconfigured installs (NFR47).

### Secret Redaction

**Decision 12 — `Redactor` at every emission point:**

```python
@dataclass(frozen=True)
class Redactor:
    headers: frozenset[str] = frozenset({
        "authorization", "cookie", "set-cookie",
        "x-api-key", "x-auth-token", "proxy-authorization",
    })
    redact_bodies: bool = True

    def redact_headers(self, headers: Mapping[str, str]) -> Mapping[str, str]: ...
    def redact_body(self, body: bytes | None) -> bytes | None: ...
```

- All `__repr__` methods on `Request`/`Response`/exception types pass through the client's redactor (NFR7, NFR8)
- OTel middleware redacts before emitting span attributes
- Default is on; users override via `AsyncClient(redactor=Redactor(headers=frozenset({...})))`

### Decision Impact Analysis

**Implementation sequence (load-bearing order):**

1. `Request`, `Response`, `Limits`, `Timeout` data types (Decision 1)
2. `Transport` protocol (Decision 2) + exception hierarchy (Decision 3 — though only mapping table requires httpx2; exception classes themselves come first)
3. `Httpx2Transport` adapter implementing `Transport`
4. `ResponseDecoder` protocol + pydantic adapter (Decision 8)
5. `Middleware` protocol + `Next` type + composition logic (Decision 4)
6. `Retry`, `RetryBudget`, `Bulkhead`, `Timeout` middlewares (Decisions 5–7)
7. `AsyncClient` wiring (Decision 9)
8. `StreamResponse` + `client.stream()` (Decision 10)
9. Observability hooks layer (Decision 11, Layer 1)
10. `Redactor` integration across emission points (Decision 12)
11. OTel middleware in `transports/_otel.py` (Decision 11, Layer 2) — extras-gated
12. `RecordedTransport` test double

**Cross-component dependencies:**

- Middlewares depend on `Request`/`Response`/exception types but not on `Transport`
- `AsyncClient` depends on `Transport` + `Middleware` + `ResponseDecoder` + `Redactor`
- `OpenTelemetryMiddleware` depends on Layer-1 hooks AND `opentelemetry-api` (extras)
- `MsgspecDecoder` depends on `msgspec` (extras)
- Nothing in the core library imports `httpx2` outside `transports/httpx2.py`

## Implementation Patterns & Consistency Rules

### Pattern Categories Defined

**Critical conflict points for a Python library:**

1. Naming (modules, classes, functions, private symbols)
2. Structure (where tests live; where private code lives; how subpackages are organized)
3. Type-hint style (future annotations, generics, protocol vs ABC)
4. Async naming (a-prefix or no)
5. Exception construction format
6. Logging conventions (logger name, level discipline)
7. Optional-extra import pattern
8. Public API export discipline (`__all__` location)
9. Test file conventions (naming, layout, fixture scope)
10. Docstring style

### Naming Patterns

**Modules** — `snake_case`. Match `modern-di` style: `client.py`, `request.py`, `response.py`, `errors.py`, `transports/httpx2.py`, `decoders/pydantic.py`, `_internal/lock_pool.py`. No `httpware_client.py` (redundant prefix); no `Client.py` (PascalCase forbidden for module names).

**Classes** — `PascalCase`. Examples: `AsyncClient`, `Request`, `Response`, `StreamResponse`, `RecordedTransport`, `Httpx2Transport`, `RetryBudget`, `PydanticDecoder`, `BadRequestError`. No `HTTPClient` (acronym capitalization avoided — `Http` is two letters by Python convention; matches httpx/httpx2 style: `httpx2.AsyncClient` not `HTTPClient`).

**Functions and methods** — `snake_case`. Examples: `with_options`, `from_url`, `iter_bytes`, `iter_lines`, `aclose`, `normalize_auth`. Verbs preferred over nouns for actions.

**Variables** — `snake_case`. Constants `UPPER_SNAKE_CASE`. Type variables `T`, `M`, single-letter PascalCase.

**Private symbols** — `_leading_underscore` for module-private symbols (functions/classes not in `__all__`). `_internal/` subpackage for cross-module private code that needs to be importable across modules but is not part of the public API. Double-underscore name-mangling NOT used.

**Test naming** — `test_<unit>.py` mirroring the module under test: `test_client.py`, `test_middleware_retry.py`, `test_transports_httpx2.py`. Test functions `test_<behavior>` (`test_get_returns_typed_response`, `test_retry_honors_retry_after`). Fixture names `<noun>` (`fake_transport`, `client`, `recorded`).

### Structure Patterns

**Layout — src/-style:**

```
src/httpware/
    __init__.py          # public re-exports + __all__
    client.py            # AsyncClient
    request.py           # Request + with_*
    response.py          # Response, StreamResponse
    errors.py            # exception hierarchy
    config.py            # Limits, Timeout, ClientConfig, Redactor
    middleware/
        __init__.py      # Middleware, Next, before_request, after_response, on_error
        retry.py         # Retry
        retry_budget.py  # RetryBudget
        bulkhead.py      # Bulkhead
        timeout.py       # Timeout (middleware)
        observability.py # lifecycle hooks (Layer 1)
        _otel.py         # OpenTelemetryMiddleware (Layer 2, extras-gated)
    transports/
        __init__.py      # Transport protocol
        httpx2.py        # Httpx2Transport + exception mapping
        recorded.py      # RecordedTransport
        niquests.py      # (Growth phase)
    decoders/
        __init__.py      # ResponseDecoder protocol
        pydantic.py      # PydanticDecoder + TypeAdapter cache
        msgspec.py       # MsgspecDecoder (extras-gated)
    _internal/
        chain.py         # middleware composition
        clock.py         # monotonic-time helpers used by RetryBudget
        types.py         # internal type aliases not part of public API
    py.typed             # zero-byte marker file

tests/
    test_client.py
    test_request.py
    test_middleware_retry.py
    test_middleware_retry_budget.py     # property-based tests live here
    test_transports_httpx2.py
    test_transports_recorded.py
    test_decoders_pydantic.py
    test_errors.py
    test_streaming.py
    test_observability.py
    conftest.py

examples/
    quickstart.py
    service_client.py
    custom_middleware.py
    streaming.py
```

**Rules:**

- Tests live in top-level `tests/`, NOT co-located. `pyproject.toml`'s `[tool.pytest.ini_options] pythonpath = ["src"]` finds the package.
- `examples/` is shipped in the repo but excluded from the wheel.
- No `utils.py` catch-all; helpers go in `_internal/` named for what they help with.
- No `lib/`, `common/`, `core/` dumping grounds.

### Type-Hint Style

- **No `from __future__ import annotations`.** Python 3.11+ floor means PEP 604 union syntax (`A | B`) is native; no need for future-annotations stringification. Matches `modern-di`.
- **PEP 604 union syntax** preferred over `typing.Union`: `int | None` not `Optional[int]`.
- **`list[T]`, `dict[K, V]`, `tuple[T, ...]`** (PEP 585 generics) instead of `typing.List`, etc.
- **Type aliases** declared with `type X = ...` (PEP 695) where supported; fallback to `X: TypeAlias = ...` only if needed for `ty` compatibility.
- **Generics** via `class Foo[T]:` (PEP 695) syntax (Python 3.12+) where possible; for 3.11 compat use explicit `TypeVar` with `class Foo(Generic[T]):`. Confirm `ty`'s preference here at first implementation; if `ty` prefers PEP 695, raise floor to 3.12.
- **Protocols** declared with `Protocol`, `@runtime_checkable` only when isinstance checks are actually needed (`Transport`, `Middleware`, `ResponseDecoder`).
- **Suppression comments** are `# ty: ignore[<rule>]` (per user global pref), NOT `# type: ignore` or `# mypy: ignore`.
- **Imports** at module top level. NO TYPE_CHECKING guards unless avoiding a runtime circular import.

### Async Naming

- **No `a` prefix on async methods** unless the symbol already exists with a sync counterpart. Match httpx2's convention (same as httpx): `client.get(...)` not `client.aget(...)`. `aclose()` is the sole exception — used to disambiguate from any potential future sync `close()` and to match httpx2's pattern.
- **Context managers:** `__aenter__` / `__aexit__` always implemented as a pair. `@asynccontextmanager` for inline factories.
- **Async generators:** `async def iter_*` returning `AsyncIterator[T]`.

### Exception Construction

**All `httpware` exceptions are constructed with keyword arguments only**, no positional:

```python
raise NotFoundError(
    status=404,
    body=resp.content,
    headers=resp.headers,
    json=resp.json() if resp.is_json else None,
    request_method=req.method,
    request_url=str(req.url),
)
```

**Mandatory fields on every status exception:** `status: int`, `body: bytes`, `headers: Mapping[str, str]`, `json: Any | None`, `request_method: str`, `request_url: str`.

**`__repr__` format:** `"<ExceptionClass status=NNN method=GET url=...>"` — never includes body or headers in the default repr (NFR8). The `Redactor` is invoked on demand if a user inspects `e.headers` / `e.body`.

**No bare `Exception` raises.** Every internal raise is one of the public exception types or a private `_internal` subclass.

### Logging Conventions

- **One library logger:** `logging.getLogger("httpware")`. Submodule loggers acquired as `logging.getLogger(f"httpware.{__name__.split('.')[-1]}")` — used inside transports and observability middleware only.
- **No log emission in the hot path of unconfigured installs** (NFR47). Logging is invoked only inside the optional observability middleware.
- **Level discipline:** DEBUG only. The library never emits INFO/WARNING/ERROR. The observability middleware may, but only if the user opts in by installing `httpware[otel]` and configuring a handler.
- **No `print()` anywhere.** Lint-enforced.
- **Structured logging via OTel attributes** — when the OTel middleware logs, it does so via span events with structured attributes per HTTP-client semconv (NFR19), not as free-form strings.

### Optional-Extra Import Pattern

Inside any module that uses an optional dependency:

```python
# decoders/msgspec.py
try:
    import msgspec
except ImportError as e:
    raise ImportError(
        "MsgspecDecoder requires the 'msgspec' extra. "
        "Install with: pip install httpware[msgspec]"
    ) from e
```

**Rules:**

- Optional deps are imported at the **top of the optional module**, not lazily inside functions
- Top-level `httpware/__init__.py` never imports optional modules; users explicitly import `httpware.decoders.msgspec` or `httpware.middleware._otel`
- `try/except ImportError` raises a helpful message with the install command
- No `if importlib.util.find_spec(...)` runtime checks in the hot path

### Public API Export Discipline

- **Single source of truth:** `httpware/__init__.py` defines `__all__` listing every public symbol.
- **Re-export via explicit imports:** `from httpware.client import AsyncClient`, not `from httpware.client import *`.
- **Private modules use `_` prefix** and are NOT importable as `httpware._internal.foo` per documentation; downstream consumers who import private modules accept that they may break.
- **API surface tests:** a CI test asserts that `set(httpware.__all__) == EXPECTED_SET` to catch accidental additions or removals. Changes to the set require a changelog entry.

### Docstring Style

- **Module docstring:** one short line describing the module's purpose. Optional second paragraph for detail.
- **Class docstring:** one short line; followed by usage example only if non-obvious.
- **Public method docstring:** required. PEP 257 short-summary style. Args/Returns sections only when types alone are insufficient (rare — type hints carry most of the load).
- **Private function/method docstring:** optional; missing-docstring rule (`D1`) is ignored per ruff config.
- **No `# noqa`** comments without a rule code. No `# type: ignore` (use `# ty: ignore[rule]` per user global pref).

### Test Conventions

- **`pytest-asyncio` mode:** `asyncio_mode = "auto"` — async test functions don't need `@pytest.mark.asyncio`.
- **Fixture scope:** `function` by default (per `modern-di`'s `asyncio_default_fixture_loop_scope = "function"`).
- **Property-based tests** (Hypothesis) live in `test_<unit>_props.py` (e.g., `test_middleware_retry_budget_props.py`) — separates fast unit tests from slow property tests.
- **Test fixtures** are defined in `conftest.py` if shared across files; otherwise inline.
- **No `unittest.TestCase`** subclasses; pytest function-style tests only.
- **Mocking:** `RecordedTransport` for network mocking. `unittest.mock.MagicMock` allowed for internal collaborators. No `respx` in `httpware`'s own tests (eat your own dogfood — though respx is acceptable in cross-compatibility tests).

### Enforcement Guidelines

**All AI agents MUST:**

- Import via absolute paths only inside `httpware/`; relative imports only within the same subpackage (`from .pydantic import PydanticDecoder` inside `decoders/`)
- Place all new public symbols in `httpware/__init__.py`'s `__all__` AND add a changelog entry
- Add a property-based test for any new concurrency-touching code (retry-budget extensions, new resilience middleware)
- Run `ruff format`, `ruff check`, `ty`, `pytest` locally before pushing
- Reject `from __future__ import annotations`; reject `# type: ignore`; reject `print()`
- Map every new transport-specific exception to a public `httpware` exception in the transport adapter — never propagate

**Pattern enforcement (CI):**

- `ruff check` with the modern-di ignore set (D1, S101, TCH, FBT, D203, D213, COM812, ISC001)
- `ty` (Astral) on `src/httpware/` and on `examples/`
- `pytest --cov=httpware` with ≥90% threshold (NFR23)
- API-surface snapshot test (catches accidental public-symbol drift)
- `grep -r 'import httpx2\|from httpx2' src/httpware/` returns matches only inside `transports/httpx2.py` (Success Criteria → Technical Success)
- `grep -r 'httpx2\._' src/httpware/` returns zero matches

### Pattern Examples

**Good — exception construction with keyword args:**

```python
status_to_exc = {404: NotFoundError, 429: RateLimitedError, ...}
exc_class = status_to_exc.get(resp.status_code, ClientStatusError if resp.status_code < 500 else ServerStatusError)
raise exc_class(
    status=resp.status_code,
    body=await resp.aread(),
    headers=dict(resp.headers),
    json=_try_json(resp),
    request_method=req.method,
    request_url=str(req.url),
)
```

**Anti-pattern — positional construction, leaking transport types:**

```python
# WRONG: positional args, leaks httpx2.Response
raise NotFoundError(resp)
```

**Good — middleware with explicit `Next`:**

```python
class TracingMiddleware:
    async def __call__(self, req: Request, next: Next) -> Response:
        with tracer.start_as_current_span(f"{req.method} {req.url.path}"):
            return await next(req)
```

**Anti-pattern — middleware that swallows `CancelledError`:**

```python
# WRONG: swallows CancelledError; breaks NFR15
async def __call__(self, req: Request, next: Next) -> Response:
    try:
        return await next(req)
    except Exception:  # bare-Exception catches CancelledError on 3.11+
        return Response(status=599, ...)
```

The correct pattern uses `except StatusError` or a specific exception class, never bare `Exception`.

## Project Structure & Boundaries

### Complete Project Directory Structure

See *Implementation Patterns → Structure Patterns* above for the full `src/httpware/` tree. Summarized:

```
src/httpware/
├── __init__.py                    # public exports + __all__
├── client.py                      # AsyncClient
├── request.py                     # Request + with_*
├── response.py                    # Response, StreamResponse
├── errors.py                      # status-keyed exception hierarchy
├── config.py                      # Limits, Timeout, ClientConfig, Redactor
├── middleware/
│   ├── __init__.py                # Middleware, Next, decorators
│   ├── retry.py
│   ├── retry_budget.py
│   ├── bulkhead.py
│   ├── timeout.py
│   ├── observability.py           # Layer 1 (lifecycle hooks)
│   └── _otel.py                   # Layer 2 (extras-gated)
├── transports/
│   ├── __init__.py                # Transport protocol
│   ├── httpx2.py                  # Httpx2Transport + exception mapping
│   ├── recorded.py                # RecordedTransport
│   └── niquests.py                # Growth phase
├── decoders/
│   ├── __init__.py                # ResponseDecoder protocol
│   ├── pydantic.py                # cached TypeAdapter
│   └── msgspec.py                 # extras-gated
├── _internal/
│   ├── chain.py                   # middleware composition
│   ├── clock.py                   # monotonic-time helpers
│   └── types.py                   # internal type aliases
└── py.typed
tests/                             # tests at repo root, not co-located
examples/                          # excluded from wheel
docs/                              # mkdocs source
```

**Repo-root configuration:**

```
httpware/
├── README.md
├── LICENSE                        # MIT
├── SECURITY.md                    # CVE disclosure channel, 90-day window
├── CONTRIBUTING.md
├── CHANGELOG.md                   # Keep a Changelog format
├── pyproject.toml                 # [project], [build-system], [tool.ruff], [tool.pytest.ini_options]
├── uv.lock                        # committed
├── Justfile                       # install/test/lint/format/release recipes
├── mkdocs.yml                     # docs config
├── context7.json                  # context7 docs index (matches modern-di)
├── CLAUDE.md                      # AI-agent guidance for downstream consumers / contributors
├── .github/
│   ├── workflows/
│   │   ├── ci.yml                 # ruff, ty, pytest on push/PR
│   │   ├── publish.yml            # tag-triggered PyPI publish (Trusted Publishers)
│   │   └── property-tests.yml     # nightly Hypothesis run with high trial count
│   └── ISSUE_TEMPLATE/
├── .gitignore
└── .readthedocs.yaml              # if hosting on RTD; otherwise GitHub Pages
```

### Architectural Boundaries

There are no service boundaries in `httpware` (it's a library, not a service). The relevant boundaries are between **internal protocol seams** — each is a point where one module talks to another only through a documented protocol, and the protocol is the only thing that can change without ripple effects.

**Seam 1 — `Middleware ↔ Transport`** (innermost boundary):

- Definition: the bottom of the middleware chain calls `transport.__call__(request) -> response`. Nothing else in the framework touches the transport.
- Crosses: `_internal/chain.py` composes the chain; `client.py` provides the transport.
- Stability: Transport protocol is part of the v1.x public-API contract (NFR18). Adding a new transport (e.g. NiquestsTransport) must not require chain changes.

**Seam 2 — `AsyncClient ↔ Middleware`**:

- Definition: client construction folds the middleware list into a single coroutine via `_internal/chain.compose(middlewares, transport) -> Next`. Calling `client.get(...)` invokes that coroutine with a fresh `Request`.
- Crosses: `client.py` builds the chain; `middleware/__init__.py` provides primitives.
- Stability: `Middleware` and `Next` types are part of the v1.x public contract. Adding a new built-in middleware does not change the protocol.

**Seam 3 — `AsyncClient ↔ ResponseDecoder`**:

- Definition: after the transport returns a `Response`, the client invokes `decoder.decode(response.content, response_model)` if `response_model` is provided.
- Crosses: `client.py` calls the decoder; `decoders/*` provides implementations.
- Stability: `ResponseDecoder` protocol is part of the v1.x public contract.

**Seam 4 — `Httpx2Transport ↔ httpx2`** (external dependency boundary):

- Definition: the only module that imports `httpx2` is `transports/httpx2.py`. It adapts `httpx2.AsyncClient` and `httpx2.Request`/`httpx2.Response`/`httpx2.Timeout`/`httpx2.Limits` to httpware's types, and maps every httpx2 exception to a httpware exception.
- Crosses: nothing else in `httpware/` imports httpx2.
- Enforcement: CI grep test (Technical Success in PRD).
- Stability: this is where httpx2-version-specific code lives. An httpx2 GA release (or eventual 3.0) touches one file.

**Seam 5 — `httpware ↔ optional extras`** (external dependency boundary):

- Definition: optional modules (`decoders/msgspec.py`, `middleware/_otel.py`, future `transports/niquests.py`) are the only places that import their respective extras. Base install does not import any of them.
- Enforcement: import-time test that imports `httpware` with no extras installed and verifies it doesn't fail.

### Requirements to Structure Mapping

Mapping the 47 FRs to their primary implementation module(s):

| FR group | Capability area | Primary module(s) |
|---|---|---|
| FR1–FR6 | Client Construction & Lifecycle | `client.py`, `config.py` |
| FR7–FR11 | Request & Response | `client.py`, `request.py`, `response.py` |
| FR12–FR16 | Transport Layer | `transports/__init__.py` (protocol), `transports/httpx2.py` (default impl wrapping `pydantic/httpx2`) |
| FR17–FR22 | Middleware System | `middleware/__init__.py` (protocol + decorators), `_internal/chain.py` (composition) |
| FR23–FR25 | Retry | `middleware/retry.py` |
| FR26–FR27 | RetryBudget | `middleware/retry_budget.py` |
| FR28 | Bulkhead | `middleware/bulkhead.py` |
| FR29 | Timeout (per-attempt) | `middleware/timeout.py` |
| FR30 | Circuit-breaker extension slot | (no implementation in v1.0; documented in `middleware/__init__.py` chain ordering) |
| FR31–FR35 | Validation & Typed Responses | `decoders/__init__.py` (protocol), `decoders/pydantic.py` (default), `decoders/msgspec.py` (extras), `client.py` (response_model wiring) |
| FR36–FR40 | Error Handling | `errors.py` (hierarchy), `transports/httpx2.py` (mapping at seam) |
| FR41–FR43 | Testing Support | `transports/recorded.py` |
| FR44 | Lifecycle hooks | `middleware/observability.py` (Layer 1) |
| FR45 | OpenTelemetry instrumentation | `middleware/_otel.py` (Layer 2, extras-gated) |
| FR46 | RetryBudget state inspection | `middleware/retry_budget.py` (public `tokens_remaining`, `in_use_ratio`) |
| FR47 | No global logging | enforced via convention + CI grep for `logging.basicConfig` |

**Cross-cutting concerns to modules:**

| Concern | Where implemented |
|---|---|
| Type-safety with generics | `client.py` (method overloads for `response_model: type[T] \| None`) |
| Event-loop binding | `transports/httpx2.py` (lazy `httpx2.AsyncClient` creation on first `__call__`) |
| Cancellation correctness | every `middleware/*.py` (CI test verifies `CancelledError` propagation) |
| Immutability | `request.py`, `response.py` (frozen dataclasses + `with_*` methods) |
| Secret redaction | `config.py` (`Redactor` class) + every emission point (`__repr__`, OTel, logs) |
| Observability hooks | `middleware/observability.py` (Layer 1 emission) |
| Packaging discipline | top-level `__init__.py` only imports from non-extras modules |
| Testability | `transports/recorded.py` (`RecordedTransport`) |

### Integration Points

**Internal communication (within the library):**

- Request flow: `AsyncClient.get(url, ...)` → builds `Request` → invokes composed middleware chain → bottom calls `Transport.__call__(request)` → returns `Response` → if `response_model` is set, calls `ResponseDecoder.decode(response.content, model)` → returns to user.
- Configuration flow: `AsyncClient(**kwargs)` → builds `ClientConfig` → builds default `Httpx2Transport` if not supplied → composes middlewares with chain ending at transport.
- Lifecycle: `async with AsyncClient(...) as client:` → `__aenter__` increments `transport._ref_count` → `__aexit__` decrements; if zero, calls `transport.aclose()`.

**External integrations (what users plug in):**

- Custom `Transport` (FR13) — any class satisfying the `Transport` protocol can replace `Httpx2Transport`. Plug-in point: `AsyncClient(transport=...)`.
- Custom `Middleware` (FR17) — any callable matching `(req, next) -> response`. Plug-in point: `AsyncClient(middleware=[...])`.
- Custom `ResponseDecoder` (FR34) — any class with a `decode(content, model)` method. Plug-in point: `AsyncClient(decoder=...)`.
- Observability backends — register Layer 1 hooks at client construction OR install `httpware[otel]` for Layer 2 integration with OTel exporters.
- Circuit-breaker plug-in (FR30) — third-party middleware plugs into the documented extension slot in the chain ordering. Reference implementation (post-MVP) wraps `purgatory`.

**Data flow diagram:**

```
User code
  │
  │  await client.get("/users/1", response_model=User)
  ▼
AsyncClient.request()
  │  builds Request (frozen dataclass)
  ▼
[Observability outer wrap]
  │  emits on_request_start
  ▼
[RetryBudget]
  │  acquires token (or shortcuts to TransportError if exhausted)
  ▼
[Retry]
  │  loop start; emits on_retry_attempt if attempt > 1
  ▼
[Extension slot — circuit breaker plugs in here when shipped]
  │
  ▼
[Bulkhead]
  │  acquires per-host semaphore
  ▼
[Timeout]
  │  starts per-attempt deadline
  ▼
Transport.__call__(request)
  │  Httpx2Transport → httpx2.AsyncClient → network
  │  exception mapping at the seam
  ▼
Response (frozen dataclass)
  │  propagates back up the chain
  ▼
[Retry decides: retry-able? loop again. Else return.]
  ▼
[Observability emits on_request_complete]
  ▼
AsyncClient.request() returns Response
  │  if response_model is set: decoder.decode(response.content, model)
  ▼
User code receives typed T
```

### File Organization Patterns

**Configuration files** — all live at the repo root (`pyproject.toml`, `Justfile`, `mkdocs.yml`, `.gitignore`, `LICENSE`, `SECURITY.md`, `CONTRIBUTING.md`, `CHANGELOG.md`, `CLAUDE.md`, `context7.json`, `.readthedocs.yaml`, `uv.lock`). No nested `config/` directory.

**Source code** — under `src/httpware/`. Capability-aligned modules. Tests in `tests/`, not co-located. Examples in `examples/` (repo only, not in wheel — controlled via `[tool.uv.build-backend] module-name = "httpware"`).

**Test organization** — flat under `tests/`, one file per `httpware/` module. Property-based tests in `_props.py` suffix files. `conftest.py` for shared fixtures.

**Docs organization** — under `docs/`:

```
docs/
├── index.md                       # README content for the docs site
├── quickstart.md
├── migration-from-base-client.md  # release blocker
├── concepts/
│   ├── middleware.md
│   ├── transports.md
│   ├── decoders.md
│   ├── retries-and-budget.md
│   └── exceptions.md
├── recipes/
│   ├── custom-middleware.md
│   ├── authentication.md
│   ├── observability.md
│   └── testing.md
└── api/                           # auto-generated via mkdocstrings
```

### Development Workflow Integration

**Development server structure** — n/a (library, no server). Local development is `uv sync && pytest`.

**Build process** — `uv build` produces wheel + sdist. `uv-build` PEP 517 backend; no setup.py, no build script. CI artifacts uploaded to GitHub Releases on tag.

**Deployment structure** — release flow (matching `modern-di`):

1. Update `CHANGELOG.md` for the release notes
2. Bump version in `pyproject.toml`
3. Tag with `vX.Y.Z`
4. GitHub Actions `publish.yml` triggers on tag, builds, uploads to PyPI via Trusted Publishers, attaches Sigstore attestation (NFR9)
5. Read the Docs build (if hosting there) triggers from main + tags

## Architecture Validation Results

### Coherence Validation ✅

**Decision Compatibility:**

All 12 core architectural decisions reinforce rather than contradict each other.

- Decision 1 (frozen dataclasses) supports Decision 4 (immutable middleware request) and Decision 6 (safe retry rebuild) without conflict
- Decision 2 (Transport protocol) is the foundation for Decisions 3 (exception mapping seam), 9 (lifecycle), and 10 (streaming)
- Decision 4 (onion middleware) is the substrate on which Decisions 5, 6, 7, 11, 12 all live
- Decision 8 (ResponseDecoder protocol) mirrors Decision 2 (Transport protocol) — same anti-leakage pattern applied to validation
- Decision 11 (two-layer observability) sits cleanly on Decision 4's middleware substrate; Layer 1 is just a built-in middleware

No contradictions found across the 12 decisions or 47 FRs.

**Pattern Consistency:**

The patterns codify the implementation conventions for the decisions:

- Async naming, module naming, and exception construction patterns are consistent with the data-type and transport decisions
- The CI grep enforcement (`httpx2` imports outside `transports/httpx2.py`) directly verifies Seam 4 from the structure section
- Test conventions (no `respx`, `RecordedTransport` only) match Decision 1 (own the abstractions)
- Logger naming (`logging.getLogger("httpware")`) matches the no-global-logging policy (NFR47, Decision 11)

**Structure Alignment:**

The 10-module layout supports the architecture:

- One module per protocol seam (`transports/`, `middleware/`, `decoders/`)
- `_internal/` houses cross-module helpers (chain composition, clock, types) without exposing them
- Tests mirror modules 1:1; property-based tests are isolated by file naming convention
- Optional extras live in dedicated modules (`middleware/_otel.py`, `decoders/msgspec.py`, future `transports/niquests.py`) — never imported from the top-level

### Requirements Coverage Validation ✅

**Functional Requirements coverage:** All 47 FRs map to specific modules (see *Requirements to Structure Mapping* in step 6). Capability-area-to-module is 1-to-1 or 1-to-few; no FR is orphaned and no FR is implemented across more than 2 modules.

**Non-Functional Requirements coverage:** All 25 NFRs are addressable by the documented architecture. Spot-check:

| NFR | Architectural support |
|---|---|
| NFR1 (≤15% overhead) | Frozen dataclasses, cached TypeAdapter, no `from __future__ import annotations`, shallow chain composition |
| NFR2 (cached TypeAdapter) | `decoders/pydantic.py` module-level `@functools.lru_cache` |
| NFR3 (validate_json single pass) | `ResponseDecoder.decode(content: bytes, model)` signature |
| NFR4 (no blocking calls) | Async-only throughout; CI grep for `requests`, `time.sleep` |
| NFR12 (RetryBudget concurrency) | Decision 5: `asyncio.Lock` + monotonic clock; property-based tests |
| NFR14 (event-loop binding) | Decision 9: lazy transport creation on first I/O |
| NFR15 (CancelledError) | Decision 4 pattern + per-middleware test |
| NFR16 (streaming pool return) | Decision 10: `StreamResponse._release` always called via `@asynccontextmanager` `finally` |
| NFR17 (`ty` type check) | Patterns: full annotations, PEP 604/585, `py.typed` marker |
| NFR18 (v1.x stability) | Patterns: `__all__` snapshot test, `_internal/` for private code |
| NFR19 (OTel semconv) | Decision 11: Layer 2 `_otel.py` middleware; CI conformance check |

No NFR lacks architectural support.

### Implementation Readiness Validation ✅

**Decision completeness:** All 12 decisions specify enough to begin implementation. Each includes the data structure, the public interface shape, and the trade-off considered.

**Structure completeness:** Full directory tree specified to the file level. Module responsibilities explicit. Test file naming and location explicit. Configuration files at the repo root enumerated.

**Pattern completeness:** Naming, structure, type hints, async, exceptions, logging, extras, exports, tests, docstrings — all 10 conflict categories addressed with concrete rules and pattern/anti-pattern examples.

### Gap Analysis Results

Honest list of gaps. None are blocking implementation; all are resolvable in early stories.

**Critical gaps:** None.

**Important gaps (resolve in early implementation):**

1. **PEP 695 generic syntax vs older `Generic[T]`** — patterns prefer PEP 695 (`class Foo[T]:`, `type X = ...`) but PRD floor is Python 3.11; PEP 695 needs 3.12+. Decision: use older `Generic[T]` / `TypeVar` syntax on 3.11; revisit when raising the floor (3.10 EOL is Oct 2026; 3.11 EOL is Oct 2027). Document this in the implementation story for module skeletons.
2. **`@runtime_checkable` cost analysis** — applied to `Transport`, `Middleware`, `ResponseDecoder`. Need to verify no measurable per-request overhead from `isinstance` checks in the hot path. Mitigation: only do `isinstance` checks at client construction, not per-request.
3. **Auth string-coercion middleware shape** — `auth=str` is normalized to a static-bearer middleware, but the exact wire format (`Authorization: Bearer <token>` vs another scheme) needs spec. Defer to implementation: probably `Bearer` as default, with `AuthMiddleware(scheme=...)` for non-bearer schemes.
4. **Property-based test scenarios** — count target (≥10,000 trials) is set; specific Hypothesis strategies for RetryBudget invariants need authoring. Spec lives in the test-implementation story.
5. **OTel attribute emission list** — semantic-convention conformance is committed (NFR19, NFR45), but the exact attribute set per span/metric isn't enumerated here. Defer to the OTel middleware implementation story; reference will be opentelemetry-specification HTTP-client-semconv at the time of implementation.

**Nice-to-have gaps (deferrable indefinitely):**

6. **Module-content-hash test** — patterns mention a "public-symbol drift" test via `__all__` snapshot. The exact comparison mechanism (frozenset equality vs string snapshot) is an implementation detail.
7. **Pydantic v3 migration plan** — NFR20 commits to documenting a migration plan when v3 ships. Pydantic v3 timeline unknown; plan can be written reactively.
8. **`httpware[all]` meta-extra** — mentioned in PRD but not load-bearing; can be added in pyproject.toml at any time.
9. **Documentation content** — `docs/` structure specified; actual prose content is a v1.0 release-blocker but architecturally trivial.
10. **Sustainability / maintainer governance** — explicitly deferred by maintainer in PRD. Worth re-raising before v1.0 cut, not architecturally blocking.

### Validation Issues Addressed

None of the gaps above block proceeding to implementation. Items 1–5 are sequenced into early implementation stories; items 6–10 are tracked but not gating.

### Architecture Completeness Checklist

**Requirements Analysis**

- [x] Project context thoroughly analyzed
- [x] Scale and complexity assessed
- [x] Technical constraints identified
- [x] Cross-cutting concerns mapped

**Architectural Decisions**

- [x] Critical decisions documented with versions (12 decisions, all with rationale and trade-offs)
- [x] Technology stack fully specified (Python 3.11+, httpx2 2.0.0+, pydantic v2, msgspec, OTel, uv_build, ruff, ty)
- [x] Integration patterns defined (5 seams)
- [x] Performance considerations addressed (NFR1–NFR5 mapped to decisions)

**Implementation Patterns**

- [x] Naming conventions established
- [x] Structure patterns defined
- [x] Communication patterns specified (middleware onion + hooks)
- [x] Process patterns documented (exception construction, logging, extras-import, test conventions)

**Project Structure**

- [x] Complete directory structure defined (file-level)
- [x] Component boundaries established (5 seams)
- [x] Integration points mapped (FR-to-module table + data-flow diagram)
- [x] Requirements to structure mapping complete (all 47 FRs mapped)

### Architecture Readiness Assessment

**Overall Status:** READY FOR IMPLEMENTATION

All 16 checklist items confirmed. No Critical Gaps. 5 Important Gaps documented and queued for early-implementation resolution.

**Confidence Level:** high

The architecture is concrete enough that an AI agent (or a small team of humans) can begin implementation without further architectural decisions. The Important Gaps are well-bounded: each has a documented mitigation or a clear stage at which to resolve it.

**Key Strengths:**

- **Five protocol seams** make every load-bearing extension point first-class and documented. Future changes (NiquestsTransport, third-party circuit breaker, OpenAPI codegen) drop into known slots.
- **No httpx2 leakage** — enforced by CI grep, designed at every level (no public type references httpx2; mapping happens at one file).
- **Resilience composition order is named** — the "extension slot" is a documented contract, not a convention. Third-party middleware authors have a reliable target.
- **Test ergonomics built-in** — `RecordedTransport` is a first-class API, not a separate package. Consumer tests have a clear, low-overhead pattern.
- **Conventions match the org** — copying from `modern-di` keeps every `modern-python` library readable to a single set of muscle-memory conventions (ruff config, `ty`, `uv_build`, layout).

**Areas for Future Enhancement:**

- Reference circuit-breaker middleware (Growth phase; wraps `purgatory`)
- NiquestsTransport (Growth phase; second backend proves the abstraction)
- LLM-gateway preset (Vision phase; concrete answer for AI-service consumers)
- Sustainability / governance section in PRD (deferred per maintainer; revisit before v1.0 cut)
- Property-based test strategies for RetryBudget (early implementation story)
- Migration to PEP 695 generics when Python 3.11 floor is raised

### Implementation Handoff

**AI Agent Guidelines:**

- Follow all 12 architectural decisions exactly as documented
- Apply the 10 implementation-pattern categories consistently across every module
- Respect the 5 protocol seams — never import across them except through the documented protocol
- Refer to this document for all architectural questions; if a question isn't answered here, surface it as a documentation gap rather than improvising
- Run `ruff check`, `ty`, `pytest` before pushing every change
- Add a property-based test for any code touching concurrency primitives
- Map every transport-specific exception to a public `httpware` exception at the transport seam

**First Implementation Priority:**

```bash
uv init --lib httpware
cd httpware
# Copy org conventions from modern-python/modern-di:
#   Justfile, .github/workflows/, [tool.ruff], ty config, [tool.pytest.ini_options]
# Add: py.typed marker, SECURITY.md, CONTRIBUTING.md, LICENSE (MIT), CHANGELOG.md, CLAUDE.md
# Configure pyproject.toml with:
#   - deps: httpx2>=2.0.0,<3.0, pydantic>=2.0,<3.0
#   - extras: msgspec, otel, niquests (placeholder)
#   - [tool.uv.build-backend] module-name = "httpware"
```

The first implementation story is the project scaffold itself. Subsequent stories implement in the load-bearing order documented in Decision 13 (Decision Impact Analysis).

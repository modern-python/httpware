# `httpware` engineering notes

This doc is the single distilled reference for `httpware` design rationale, protocol seams, and remaining roadmap. It complements [`../CLAUDE.md`](../CLAUDE.md): `CLAUDE.md` holds AI-enforced invariants and operational commands; this file holds the reasoning and the structural map. Historical planning artifacts live in [`archive/`](./archive/) and are cited only for original rationale.

## 1. Project intent

`httpware` is a Python async HTTP client framework for building resilient service clients. It supersedes `community-of-python/base-client` and ships under the `modern-python` org. The framework owns the abstraction layer above the underlying HTTP client (`httpx2` by default); consumers never import the transport directly.

## 2. Architectural invariants (CI-enforced)

These are non-negotiable. CI rejects PRs that violate them. The "why" exists so future contributors can judge edge cases instead of blindly following the rule.

- **No `httpx2` leakage outside `src/httpware/transports/httpx2.py`.** *Why:* the whole point of the framework is to own the abstraction above the underlying client. Any consumer that imports `httpx2` directly defeats the abstraction and pins us to the current transport choice.
- **No `httpx2` private API.** *Why:* private symbols can change between patch releases. We accept the public-API surface as the contract.
- **No `from __future__ import annotations`.** *Why:* Python 3.11+ floor. PEP 604/585 syntax is native; the future-import would only add noise and inconsistency.
- **No `print()`.** *Why:* ruff-enforced. Libraries log; they do not print to stdout. Stray prints leak into consumer applications.
- **No global logging config.** *Why:* `logging.basicConfig()` from a library mutates the consumer's logging tree. We only acquire `logging.getLogger("httpware")` or namespaced child loggers and let consumers configure handlers.
- **Type suppressions use `# ty: ignore[<rule>]`.** *Why:* this project uses `ty`, not `mypy`. `# type: ignore` is silently accepted by `ty` but ambiguous; `# ty: ignore[<rule>]` is checked and rule-specific.

## 3. The five protocol seams

A protocol seam is a documented internal boundary. AI agents and contributors must respect it — never cross a seam except through its protocol.

### Seam 1: `Middleware ↔ Transport`

- **Where:** `src/httpware/middleware/` (chain) ↔ `src/httpware/transports/` (any `Transport` implementation).
- **Contract:** the chain bottom calls `transport.__call__(request) -> Response`.
- **Rule:** middleware never instantiates a transport; the `AsyncClient` injects it at construction.

### Seam 2: `AsyncClient ↔ Middleware`

- **Where:** `src/httpware/client.py` ↔ `src/httpware/middleware/`.
- **Contract:** the middleware chain is composed at `AsyncClient.__init__` and frozen for the client's lifetime.
- **Rule:** mutating the chain after construction is not supported. Per-request middleware is expressed via the `Request` extensions field, not by rebuilding the chain.

### Seam 3: `AsyncClient ↔ ResponseDecoder`

- **Where:** `src/httpware/client.py` ↔ `src/httpware/decoders/`.
- **Contract:** the decoder is invoked when the caller passes `response_model=`. The protocol is `decode(content: bytes, model: type[T]) -> T`.
- **Rule:** the decoder must operate on raw bytes in a single parse pass. Two-pass decoding (`json.loads` then `validate_python`) is rejected: a single bytes-in / typed-object-out pass avoids the redundant intermediate `dict` allocation and parses faster. The Pydantic adapter implements this as `TypeAdapter(model).validate_json(content)`, with the `TypeAdapter` itself memoized via `@functools.lru_cache(maxsize=1024)` on a module-level `_get_adapter(model)` factory (the adapter is the expensive part to build). The msgspec adapter implements it as `msgspec.json.decode(content, type=model)`.

### Seam 4: `Httpx2Transport ↔ httpx2`

- **Where:** `src/httpware/transports/httpx2.py` is the only file that may import `httpx2`.
- **Contract:** `httpx2` exceptions are mapped to `httpware` exceptions at this seam.
- **Rule:** CI grep checks enforce zero `httpx2` imports outside this file and zero `httpx2._` private references anywhere.

### Seam 5: `httpware ↔ optional extras`

- **Where:** `pyproject.toml` extras (`[project.optional-dependencies]`) ↔ the adapter modules that import them.
- **Contract:** each optional dependency is imported only inside its own dedicated module (e.g., `pydantic` in `decoders/pydantic.py`; `msgspec` in `decoders/msgspec.py` when 1-6 lands; `opentelemetry` in `middleware/observability/otel.py` when 5-4 lands).
- **Rule:** never import an extra at package top-level. The package must import cleanly when the extra is not installed.

## 4. Exception contract

All `httpware` HTTP exceptions are constructed with **keyword arguments only**. The mandatory fields on every `StatusError` (and its 4xx/5xx subclasses) are:

| Field | Type | Source |
| --- | --- | --- |
| `status` | `int` | response status code |
| `body` | `bytes` | full response body |
| `headers` | `Mapping[str, str]` | lowercased response headers (v0 contract) |
| `json` | `Any \| None` | parsed JSON if `application/json` content-type; else `None` |
| `request_method` | `str` | uppercased request method |
| `request_url` | `str` | request URL, may include userinfo (Redactor sanitizes — Story 5.3) |

The mapping table from `httpx2` errors to `httpware` errors lives at Seam 4 (`src/httpware/transports/httpx2.py`). Status-keyed exceptions are looked up via the `STATUS_TO_EXCEPTION` table in `src/httpware/errors.py`.

Constructing any of these exceptions positionally is a programming error caught by `ty`. The keyword-only signature is enforced via `__init__` definitions, not docstrings.

## 5. Module layout

Current tree (post-story-1.5):

```text
src/httpware/
├── __init__.py                       # public exports + __all__
├── py.typed
├── config.py                         # Limits, Timeout, ClientConfig
├── request.py                        # Request + with_* helpers
├── response.py                       # Response (StreamResponse pending in Epic 4)
├── errors.py                         # status-keyed exception hierarchy
├── decoders/
│   ├── __init__.py                   # ResponseDecoder protocol (Seam 3)
│   └── pydantic.py                   # PydanticDecoder adapter
└── transports/
    ├── __init__.py                   # Transport protocol
    └── httpx2.py                     # Httpx2Transport adapter (Seam 4)
```

Planned modules (filled in as the roadmap lands):

```text
src/httpware/
├── client.py                         # AsyncClient (Story 1.7)
├── decoders/msgspec.py               # MsgspecDecoder via extra (Story 1.6)
├── transports/recorded.py            # RecordedTransport for testing (Story 1.8)
├── middleware/                       # protocols + built-in middleware (Epic 2)
│   ├── __init__.py                   # Middleware protocol, Next type
│   ├── chain.py                      # chain composition
│   ├── auth.py                       # auth coercion (Story 2.4)
│   ├── timeout.py                    # per-attempt timeout (Story 3.1)
│   ├── retry.py                      # retry + RetryBudget (Stories 3.2–3.4)
│   ├── bulkhead.py                   # concurrency limit (Story 3.5)
│   └── observability/                # Layer 1 emission + OTEL (Epic 5)
└── _internal/                        # private cross-module helpers
```

## 6. Testing patterns

- **`pytest-asyncio` auto mode.** Async test functions do not require `@pytest.mark.asyncio`. The setting lives in `pyproject.toml` under `[tool.pytest.ini_options]`.
- **`RecordedTransport` for transport mocking, not `respx`.** Once Story 1.8 lands, transport-level tests instantiate `RecordedTransport` (shipped with the library) instead of patching `httpx2` calls. This keeps tests aligned with the public seam and avoids `respx`'s private-API risk.
- **Hypothesis property-based tests** for concurrency-sensitive code: `RetryBudget`, `Bulkhead`, retry interleaving. Files are named `test_*_props.py` so they are easy to grep and treat separately in CI.
- **Performance tests are opt-in.** The `perf` pytest marker is registered in `pyproject.toml`; the default `addopts` line includes `-m 'not perf'`. Run benchmarks explicitly with `pytest -m perf`.
- **Coverage is 100% line coverage.** The five merged stories ship at 100% line coverage. New code is expected to maintain this.

## 7. Optional-extras pattern

`httpware` core has a small dependency set. Capabilities that pull in heavyweight dependencies (`pydantic`, `msgspec`, `opentelemetry`) live behind extras declared in `pyproject.toml`:

```toml
[project.optional-dependencies]
pydantic = ["pydantic>=2"]
msgspec = ["msgspec>=0.18"]
otel = ["opentelemetry-api>=1.20", "opentelemetry-sdk>=1.20"]
```

Each extra's code lives in a single dedicated module (e.g., `decoders/pydantic.py`, `decoders/msgspec.py`, `middleware/observability/otel.py`). The `import` of the extra happens **inside** that module — never at package top level. This way, `import httpware` works cleanly without the extras installed, and the seam stays observable: grep for `import pydantic` should return exactly one file.

Caller-facing pattern: consumers select the implementation by passing it explicitly, e.g., `AsyncClient(decoder=PydanticDecoder())`. There is no auto-detection or implicit registry.

## 8. Remaining roadmap

Twenty-seven stories remain. Topic slugs in `docs/superpowers/specs/` and `docs/superpowers/plans/` use kebab-case descriptions, not the story IDs — these IDs are kept here only as a stable mapping to the archived epic specs (`archive/epics.md`).

### Epic 1 — Make typed HTTP requests with sensible defaults

- **1-6** `msgspec` decoder via extras — second `ResponseDecoder` adapter, opt-in.
- **1-7** `AsyncClient` with HTTP methods, `response_model`, `with_options`, lifecycle — the main public surface.
- **1-8** `RecordedTransport` for testing — ships with the library; replaces `respx` for transport-level tests.

### Epic 2 — Compose request-handling logic via middleware

- **2-1** `Middleware` protocol, `Next` type, chain composition.
- **2-2** Phase shortcut decorators (`@before_request`, `@after_response`, `@on_error`).
- **2-3** `Request` immutability helpers (`with_headers`, `with_cookie`, `with_extension`, etc.).
- **2-4** Auth coercion as middleware.
- **2-5** Wire middleware into `AsyncClient`.

### Epic 3 — Survive upstream failures with composable resilience

- **3-1** Per-attempt timeout middleware.
- **3-2** Retry middleware.
- **3-3** `RetryBudget` data structure.
- **3-4** `RetryBudget` middleware integration.
- **3-5** `Bulkhead` middleware.
- **3-6** Document the extension slot for custom resilience policies.

### Epic 4 — Stream responses without buffering

- **4-1** `StreamResponse` type.
- **4-2** Transport stream implementation in `Httpx2Transport`.
- **4-3** `AsyncClient.stream` context manager.

### Epic 5 — Observe and instrument the client

- **5-1** Layer 1 observability — middleware lifecycle hooks.
- **5-2** Wire emission into resilience middlewares.
- **5-3** `Redactor` class and integration (closes deferred work on URL/header/userinfo sanitization).
- **5-4** OpenTelemetry middleware via the `otel` extra.
- **5-5** Logging policy enforcement (CI grep on `logging.basicConfig`, `logging.getLogger()` without a name).

### Epic 6 — Ship v1.0

- **6-1** Migration guide from `base-client`.
- **6-2** Documentation site (`mkdocs`).
- **6-3** Public benchmark suite.
- **6-4** CI enforcement gates (codify the invariants in Section 2 as CI jobs).
- **6-5** Release flow with Trusted Publishers + Sigstore.

When work starts on a roadmap item, it gets a superpowers spec at `docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md` and a plan at `docs/superpowers/plans/YYYY-MM-DD-<topic>-plan.md`. The bmad-era 40KB story specs in `archive/stories/` cover 1-1 through 1-5 and are retired going forward.

## 9. Deferred work

Review-surfaced items that are real but not actionable now live in [`./deferred-work.md`](./deferred-work.md). Each entry cites the originating story and the file/line, and explains why the fix is deferred (cross-story dependency, scope, performance/security tradeoff, etc.). When a deferred item becomes actionable, it migrates into the spec for the story that resolves it.

# `httpware` engineering notes

This doc is the single distilled reference for `httpware` design rationale, protocol seams, and remaining roadmap. It complements `CLAUDE.md` (at the repo root): `CLAUDE.md` holds AI-enforced invariants and operational commands; this file holds the reasoning and the structural map.

## 1. Project intent

`httpware` is a thin opinionated wrapper around `httpx2`. It re-exports `httpx2.Request` and `httpx2.Response` as the public request/response surface and adds three things on top: typed response decoding (via a `ResponseDecoder` protocol; pydantic and msgspec are both opt-in extras as of 0.3.0), a middleware chain composed at client construction, and a status-keyed exception tree raised automatically on 4xx and 5xx. `AsyncClient(decoder=None)` defaults to constructing a `PydanticDecoder` and so requires the `pydantic` extra; callers can supply an explicit `decoder=` argument to escape the default. As of 0.4.0, the package ships a small resilience suite under `httpware.middleware.resilience` — a `Retry` middleware with a Finagle-style `RetryBudget`, plus a `Bulkhead` concurrency limiter — composed via the standard middleware chain. As of 0.5.0, `AsyncClient.stream()` provides a context-manager API for chunked response bodies; it bypasses the middleware chain by design (see planning/archive/specs/2026-06-05-streaming-design.md). As of 0.6.0, `Retry` and `Bulkhead` emit operational events via stdlib `logging` records (`httpware.retry` / `httpware.bulkhead` loggers) and — when `opentelemetry-api` is installed — OpenTelemetry span events on the active span. As of 0.7.0, the first-cut user-docs surface is live at <https://httpware.readthedocs.io/> (Middleware, Resilience, Errors, Testing guides) and Epic 3 is closed.

The next release renames the async middleware surface to use the `Async*`/`async_*` prefix (aligning with httpx2's convention) and removes the seldom-used `attempt_timeout=` kwarg from `AsyncRetry` — see `planning/specs/2026-06-07-sync-client-design.md` for the rationale.

The same release also adds a sync `Client` with full feature parity (typed decoding, middleware chain, `Retry`/`Bulkhead`, `stream()`). `RetryBudget` is now thread-safe (one class, both worlds). Sync `Bulkhead` uses `threading.Semaphore` and cannot share an instance with `AsyncBulkhead`. See `planning/specs/2026-06-07-sync-client-design.md`.

The 0.1.0 release attempted to own a full abstraction over the underlying HTTP client. v0.2 walks that back: `httpx2` is part of the public surface.

## 2. Architectural invariants (CI-enforced)

These are non-negotiable. CI rejects PRs that violate them. The "why" exists so future contributors can judge edge cases instead of blindly following the rule.

- **No `httpx2._` private API.** *Why:* private symbols can change between patch releases. We accept the public-API surface as the contract.
- **No `from __future__ import annotations`.** *Why:* Python 3.11+ floor. PEP 604/585 syntax is native; the future-import would only add noise and inconsistency.
- **No `print()`.** *Why:* ruff-enforced. Libraries log; they do not print to stdout. Stray prints leak into consumer applications.
- **No global logging config.** *Why:* `logging.basicConfig()` from a library mutates the consumer's logging tree. We only acquire `logging.getLogger("httpware")` or namespaced child loggers and let consumers configure handlers.
- **Type suppressions use `# ty: ignore[<rule>]`.** *Why:* this project uses `ty`, not `mypy`. `# type: ignore` is silently accepted by `ty` but ambiguous; `# ty: ignore[<rule>]` is checked and rule-specific.

The 0.1.0 "no `httpx2` leakage outside `transports/httpx2.py`" invariant is **retired in v0.2**. Exposing `httpx2.Request`/`httpx2.Response` is the design.

## 3. The three protocol seams

A protocol seam is a documented internal boundary. AI agents and contributors must respect it — never cross a seam except through its protocol.

The 0.1.0 seams numbered 1 (Middleware↔Transport) and 4 (Transport↔httpx2) have collapsed into the `AsyncClient` terminal — there is no transport abstraction in v0.2.

### Seam A: `Client`/`AsyncClient` ↔ `Middleware`/`AsyncMiddleware`

- **Where:** `src/httpware/client.py` ↔ `src/httpware/middleware/`.
- **Contract:** the middleware chain is composed once at client construction and frozen for the client's lifetime. Both worlds follow the same contract; the only difference is the per-world type: `AsyncClient` composes `AsyncMiddleware` via `compose_async` (the continuation type is `AsyncNext`), and `Client` composes `Middleware` via `compose` (the continuation type is `Next`). Both `compose` and `compose_async` live in `src/httpware/middleware/chain.py`. The chain bottom (the "terminal") is internal: it calls `self._httpx2_client.send(request)`, maps `httpx2` errors to `httpware` errors, and raises a `StatusError` subclass on 4xx/5xx. Same lifecycle rules in both worlds.
- **Rule:** mutating the chain after construction is not supported. Per-request behavior goes through `httpx2.Request.extensions` or through `extensions=` kwargs at call sites.

### Seam B: `Client`/`AsyncClient` ↔ `ResponseDecoder`

- **Where:** `src/httpware/client.py` ↔ `src/httpware/decoders/`.
- **Contract:** the decoder is invoked when the caller passes `response_model=`. The protocol is `decode(content: bytes, model: type[T]) -> T`. Any exception raised by `decode` is wrapped by `Client.send` / `AsyncClient.send` into `httpware.DecodeError` (a `ClientError` subclass carrying `response`, `model`, `original`). Decoder implementers do not need to raise `DecodeError` directly.
- **Rule:** the decoder must operate on raw bytes in a single parse pass. Two-pass decoding (`json.loads` then `validate_python`) is rejected: a single bytes-in / typed-object-out pass avoids the redundant intermediate `dict` allocation and parses faster. The Pydantic adapter implements this as `TypeAdapter(model).validate_json(content)`, with the `TypeAdapter` itself memoized via `@functools.lru_cache(maxsize=1024)` on a module-level `_get_adapter(model)` factory (the adapter is the expensive part to build). The msgspec adapter implements it as `msgspec.json.decode(content, type=model)`.

### Seam C: `httpware ↔ optional extras`

- **Where:** `pyproject.toml` extras (`[project.optional-dependencies]`) ↔ the adapter modules that import them.
- **Contract:** each optional dependency is imported only inside its own dedicated module (e.g., `pydantic` in `decoders/pydantic.py`; `msgspec` in `decoders/msgspec.py`). Future extras (e.g., OpenTelemetry under Epic 5) follow the same pattern, with the extra declared in `pyproject.toml` at the same time the code that uses it lands — not earlier.
- **Rule:** never import an extra at package top-level. The package must import cleanly when the extra is not installed.
- **Verification:** `tests/test_optional_extras_isolation.py` runs a fresh-subprocess `import httpware` and asserts that neither pydantic nor msgspec ends up in `sys.modules`. New extras must add the same isolation test.

## 4. Exception contract

`StatusError` and all its 4xx/5xx subclasses are constructed with a **single positional `response: httpx2.Response`**. Subclasses do not override `__init__`. All fields are available via `exc.response.*` (status code, headers, content, request, etc.).

```python
raise NotFoundError(response)          # correct
exc.response.status_code               # 404
exc.response.request.url               # URL of the failed request
```

`__repr__` and the `str()` summary strip `user:pass@` userinfo from `response.request.url` to avoid leaking credentials in tracebacks. Query-string secrets are not stripped here.

The error-mapping table (what `httpx2` exception maps to which `httpware` exception) lives at the `AsyncClient` terminal in `src/httpware/client.py`. Status-keyed exceptions are looked up via the `STATUS_TO_EXCEPTION` table in `src/httpware/errors.py`. Unknown 4xx falls back to `ClientStatusError`; unknown 5xx falls back to `ServerStatusError`.

`TimeoutError` inherits from both `httpware.ClientError` and `builtins.TimeoutError` so `except builtins.TimeoutError` (the form `asyncio.wait_for` uses) also catches httpware-raised timeouts.

`DecodeError` covers the case where `response_model=` is set, the HTTP call itself succeeded, but the active `ResponseDecoder` raised. The wrap happens at the seam in `Client.send` / `AsyncClient.send` — `except Exception` translates any decoder-side failure into `DecodeError(response=..., model=..., original=...)` with `raise ... from exc` chaining. The `original` attribute exposes the underlying library exception (e.g., `pydantic.ValidationError`, `msgspec.ValidationError`); `__cause__` carries the same reference.

## 5. Module layout

Current tree:

```text
src/httpware/
├── __init__.py            # public exports (both worlds at top level)
├── py.typed
├── client.py              # Client (sync) + AsyncClient (async)
├── errors.py              # status-keyed exception tree (shared)
├── middleware/
│   ├── __init__.py        # Middleware + AsyncMiddleware, Next + AsyncNext, decorators
│   ├── chain.py           # compose + compose_async
│   └── resilience/
│       ├── __init__.py    # re-exports both worlds + RetryBudget
│       ├── bulkhead.py    # Bulkhead + AsyncBulkhead
│       ├── budget.py      # RetryBudget (thread-safe; shared)
│       ├── retry.py       # Retry + AsyncRetry
│       └── _backoff.py    # full-jitter helper (shared)
├── decoders/              # shared (ResponseDecoder + adapters)
└── _internal/
    ├── exception_mapping.py  # map_httpx2_exception (shared)
    ├── import_checker.py     # is_*_installed flags
    ├── observability.py      # _emit_event
    └── status.py             # _raise_on_status_error, _is_streaming_body_*, STREAMING_BODY_MARKER
```

**Deleted relative to 0.1.0:** `request.py`, `response.py`, `config.py`, `transports/` (Transport protocol + Httpx2Transport), `_internal/auth.py`, `_internal/chain.py`. The `RecordedTransport` testing helper is gone; tests inject `httpx2.MockTransport` via `httpx2_client=` instead.

## 6. Testing patterns

- **`pytest-asyncio` auto mode.** Async test functions do not require `@pytest.mark.asyncio`. The setting lives in `pyproject.toml` under `[tool.pytest.ini_options]`.
- **`httpx2.MockTransport` for transport mocking, not `respx`.** Tests construct `httpx2.AsyncClient(transport=httpx2.MockTransport(handler))` and pass it as `httpx2_client=` to `AsyncClient`. `MockTransport` is the public test seam in `httpx`; `respx` patches private internals and breaks across `httpx` major versions. (The 0.1-era `RecordedTransport` testing helper was removed in the v0.2 pivot.) See [`docs/testing.md`](../docs/testing.md) for the user-facing version of this pattern.
- **Hypothesis property-based tests** for concurrency-sensitive code: `RetryBudget`, `Bulkhead`, retry interleaving. Files are named `test_*_props.py` so they are easy to grep and treat separately in CI.
- **Performance tests are opt-in.** The `perf` pytest marker is registered in `pyproject.toml`; the default `addopts` line includes `-m 'not perf'`. Run benchmarks explicitly with `pytest -m perf`.
- **Coverage is 100% line coverage.** The five merged stories ship at 100% line coverage. New code is expected to maintain this.

## 7. Optional-extras pattern

`httpware` core has a small dependency set. Capabilities that pull in heavyweight dependencies (`pydantic`, `msgspec`) live behind extras declared in `pyproject.toml`:

```toml
[project.optional-dependencies]
pydantic = ["pydantic>=2"]
msgspec = ["msgspec>=0.18"]
```

Each extra's code lives in a single dedicated module (`decoders/pydantic.py`, `decoders/msgspec.py`). The `import` of the extra happens **inside** that module behind an `is_<extra>_installed` guard from `_internal/import_checker.py` — never at package top level. This way, `import httpware` works cleanly without the extras installed, and the seam stays observable: `grep -rnE 'from pydantic|import pydantic' src/httpware/ | grep -v import_checker` returns exactly one indented line (the guarded import in `decoders/pydantic.py`), and the same is true for `msgspec`.

New extras are added at the same time as the code that uses them — never preemptively. (An `otel` extra existed pre-0.4 but was removed once we noticed it was advertising functionality that didn't exist. 0.6.0 reintroduces it paired with the code that uses it — `Retry` and `Bulkhead` add events to the active OpenTelemetry span via `trace.get_current_span().add_event(...)`.)

Caller-facing pattern: consumers select the implementation by passing it explicitly, e.g., `AsyncClient(decoder=PydanticDecoder())`. There is no auto-detection or implicit registry.

## 8. Remaining roadmap

Post-pivot, the roadmap has three categories. Topic slugs in `planning/specs/` and `planning/plans/` use kebab-case descriptions.

### Deleted by the v0.2 pivot

`1-8` `RecordedTransport`, `2-3` Request immutability helpers, `2-4` auth coercion middleware, `4-1` `StreamResponse` type, `4-2` transport stream implementation, `5-3` `Redactor` middleware.

### Rewritten by the v0.2 pivot

`1-7` `AsyncClient` (the heart of v0.2 — shipped in the pivot PR), `2-5` wire middleware into `AsyncClient` (trivially part of `1-7`), `6-1` migration guide (extended with httpware 0.1→0.2 notes), `6-4` CI invariant gates (drop the "no `httpx2` leakage" rule).

### Shipped (all epics closed)

- **Epic 3 — Resilience: SHIPPED.**
  - **v0.4 slice 1:** `Retry` middleware + Finagle-style `RetryBudget` token bucket + `attempt_timeout=` parameter (folded-in 3-1). See [`planning/archive/specs/2026-06-05-retry-and-retry-budget-design.md`](archive/specs/2026-06-05-retry-and-retry-budget-design.md) and [`planning/archive/plans/2026-06-05-retry-and-retry-budget-plan.md`](archive/plans/2026-06-05-retry-and-retry-budget-plan.md).
  - **v0.4 slice 2:** `Bulkhead` middleware (concurrency limiter via `asyncio.Semaphore` with bounded acquire wait). See [`planning/archive/specs/2026-06-05-bulkhead-design.md`](archive/specs/2026-06-05-bulkhead-design.md) and [`planning/archive/plans/2026-06-05-bulkhead-plan.md`](archive/plans/2026-06-05-bulkhead-plan.md).
  - **v0.7:** `3-6` extension-slot docs — [`docs/middleware.md`](../docs/middleware.md). Covers the Middleware Protocol, phase decorators, a Request-ID worked example, and "when NOT to write a middleware." See [`planning/archive/specs/2026-06-05-extension-slot-docs-design.md`](archive/specs/2026-06-05-extension-slot-docs-design.md) and [`planning/archive/plans/2026-06-05-extension-slot-docs-plan.md`](archive/plans/2026-06-05-extension-slot-docs-plan.md).
  - **v0.7 also bundles** the rest of the first-cut user-docs surface — [`docs/resilience.md`](../docs/resilience.md) (Retry/RetryBudget/Bulkhead reference), [`docs/errors.md`](../docs/errors.md) (exception tree + catching strategies), [`docs/testing.md`](../docs/testing.md) (mock-transport injection pattern) — plus an "OpenTelemetry wiring" section appended to `docs/middleware.md`. See [`planning/archive/specs/2026-06-05-v0.7-docs-expansion-design.md`](archive/specs/2026-06-05-v0.7-docs-expansion-design.md) and [`planning/archive/plans/2026-06-05-v0.7-docs-expansion-plan.md`](archive/plans/2026-06-05-v0.7-docs-expansion-plan.md).
- **Epic 4 — Streaming: SHIPPED in v0.5.** `AsyncClient.stream()` context manager + Retry refuses streamed-body requests. See [`planning/archive/specs/2026-06-05-streaming-design.md`](archive/specs/2026-06-05-streaming-design.md) and [`planning/archive/plans/2026-06-05-streaming-plan.md`](archive/plans/2026-06-05-streaming-plan.md).
- **Epic 5 — Observability: SHIPPED in v0.6** — re-scoped from the original 4-story plan. `Retry` and `Bulkhead` emit operational events via stdlib `logging` + opt-in OpenTelemetry span events. Stories `5-1` (Layer 1 middleware hooks) and `5-4` (standalone OTel middleware) RETIRED — `opentelemetry-instrumentation-httpx` already covers transport-level tracing; a separate httpware middleware would duplicate it. See [`planning/archive/specs/2026-06-05-observability-design.md`](archive/specs/2026-06-05-observability-design.md) and [`planning/archive/plans/2026-06-05-observability-plan.md`](archive/plans/2026-06-05-observability-plan.md).
- **Epic 6 — Ship v1.0: SHIPPED.** `6-2` docs site live at <https://httpware.readthedocs.io/> (mkdocs-material, hand-written content only, auto-publishing from `main`). Stories `6-3` (benchmarks) and `6-5` (Trusted Publishers + Sigstore release flow) RETIRED — neither carries enough value to maintain. Tag-driven release via the existing `publish.yml` workflow stays as-is.
- **Carry-forward decoder:** `1-6` msgspec decoder via extras — second `ResponseDecoder` adapter, already implemented; verified surviving in the pivot.
- **Middleware protocol:** `2-1` and `2-2` already implemented in the pivot (protocol, chain, phase decorators).

All planned epics are closed as of v0.7.0. The next semver bump is a judgment call (cut v1.0 from the current main; or keep iterating at 0.x and let the API settle further before promising stability).

When work starts on a roadmap item, it gets a spec at `planning/specs/YYYY-MM-DD-<topic>-design.md` and a plan at `planning/plans/YYYY-MM-DD-<topic>-plan.md`.

## 9. Deferred work

Review-surfaced items that are real but not actionable now live in `planning/deferred-work.md` at the repository root. Each entry cites the originating story and the file/line, and explains why the fix is deferred (cross-story dependency, scope, performance/security tradeoff, etc.). When a deferred item becomes actionable, it migrates into the spec for the story that resolves it.

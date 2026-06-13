# Middleware

A protocol seam is a documented internal boundary. AI agents and contributors must respect it — never cross a seam except through its protocol.

## Seam A: `Client`/`AsyncClient` ↔ `Middleware`/`AsyncMiddleware`

- **Where:** `src/httpware/client.py` ↔ `src/httpware/middleware/`.
- **Contract:** the middleware chain is composed once at client construction and frozen for the client's lifetime. Both worlds follow the same contract; the only difference is the per-world type: `AsyncClient` composes `AsyncMiddleware` via `compose_async` (the continuation type is `AsyncNext`), and `Client` composes `Middleware` via `compose` (the continuation type is `Next`). Both `compose` and `compose_async` live in `src/httpware/middleware/chain.py`. The chain bottom (the "terminal") is internal: it calls `self._httpx2_client.send(request)`, maps `httpx2` errors to `httpware` errors, and raises a `StatusError` subclass on 4xx/5xx. Same lifecycle rules in both worlds.
- **Rule:** mutating the chain after construction is not supported. Per-request behavior goes through `httpx2.Request.extensions` or through `extensions=` kwargs at call sites.

Phase decorators (declared alongside `Middleware`/`AsyncMiddleware`, `Next`/`AsyncNext` in `src/httpware/middleware/__init__.py`) let a middleware target a specific phase of the request lifecycle.

## Why there is no standalone OpenTelemetry middleware

`httpware` deliberately does not ship a separate OTel tracing middleware layer. `opentelemetry-instrumentation-httpx` already covers transport-level tracing; a separate httpware middleware would duplicate it. Observability that `httpware` does add lives where it has information httpx2 lacks — the `Retry` and `Bulkhead` span events on the active span (see Resilience).

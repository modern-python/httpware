# Changelog

All notable changes to `httpware` will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Initial project scaffold: `src/httpware/` package, `py.typed` marker, `pyproject.toml` with `uv_build` backend.
- Org conventions ported from `modern-python/modern-di`: `Justfile`, `.github/workflows/ci.yml`, `[tool.ruff]` config, `[tool.pytest.ini_options]`, dev and lint dep groups.
- Declared dependencies: `httpx2>=2.0.0,<3.0`, `pydantic>=2.0,<3.0`.
- Declared install extras: `[msgspec]`, `[otel]`, `[niquests]`, `[all]`.
- `SECURITY.md` with 90-day private-disclosure window.
- `CONTRIBUTING.md` with development workflow.
- `CLAUDE.md` with AI-agent guidance.
- Core data types: `Request`, `Response`, `Limits`, `Timeout`, `ClientConfig` — frozen+slotted dataclasses with `with_*` immutability helpers on `Request` and computed `text`/`json()` accessors on `Response` (Story 1.2).
- Status-keyed exception hierarchy with plain typed fields: `ClientError`, `TransportError`, `TimeoutError`, `StatusError`, `ClientStatusError`/`ServerStatusError` bases, 9 leaf classes (`BadRequestError` … `ServiceUnavailableError`), `STATUS_TO_EXCEPTION` lookup dict (Story 1.3). `StatusError` is picklable and deep-copyable via custom `__reduce__`; `__repr__` and the summary message strip `user:pass@` userinfo from the request URL; `headers` is stored as a read-only `MappingProxyType` so caller mutations after `raise` do not bleed into the exception. `TimeoutError` multi-inherits from `builtins.TimeoutError` (revisits architecture Decision 3) so `except builtins.TimeoutError` (the form `asyncio.wait_for` raises) also catches httpware-raised timeouts.
- `Transport` protocol (`@runtime_checkable`) and default `Httpx2Transport` adapter; `StreamResponse` placeholder for Story 4.1 protocol typing; the wire `method` is uppercased at the seam and `httpx2` exceptions (`TimeoutException`, `HTTPError`, `InvalidURL`, `CookieConflict`, and the closed-client `RuntimeError`) are mapped to `httpware.TimeoutError` / `httpware.TransportError` (with the original exception's message preserved on the mapped instance) so no `httpx2` exception escapes the library; lazy `httpx2.AsyncClient` construction is guarded by an `asyncio.Lock` so concurrent first-calls share one client; `httpx2` is confined to `src/httpware/transports/httpx2.py` (Story 1.4).
- `ResponseDecoder` protocol (`@runtime_checkable`) and default `PydanticDecoder` adapter — single-parse-pass JSON decoding via `pydantic.TypeAdapter.validate_json(bytes)`; a module-level `@functools.lru_cache(maxsize=None)` factory (`_get_adapter`) memoizes one `TypeAdapter` per `response_model` across the process so warm-path requests pay zero adapter-construction cost; `pydantic.ValidationError` surfaces unchanged to the caller (Story 1.5).
- `Middleware` protocol (`@runtime_checkable`) and `Next` callable type alias (`Callable[[Request], Awaitable[Response]]`); private `compose(middlewares, transport)` chain composer at `httpware._internal.chain` using a recursive closure fold with `transport.__call__` as the bottom of the chain. No exception handling inside `compose`, so `asyncio.CancelledError` and user-raised exceptions propagate untouched (Story 2.1).
- Phase-shortcut decorators `@before_request`, `@after_response`, `@on_error` for lifecycle hooks without authoring a full `Middleware` class. `@on_error` catches `Exception` only (so `asyncio.CancelledError` propagates); its handler may return a `Response` to recover or `None` to re-raise (Story 2.2).
- Request and Response immutability helper expansion: `Request.with_headers`, `with_cookie`, `with_cookies`, `with_extension`, `with_extensions`; `Response.with_headers`, `with_status`. Plural helpers merge mappings (incoming keys override existing); singular helpers add or replace a single entry. No validation, no header-key normalization — matches the existing `with_header` semantics from Story 1.2 (Story 2.3).

[Unreleased]: https://github.com/modern-python/httpware/commits/main

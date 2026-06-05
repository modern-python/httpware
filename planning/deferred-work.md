# Deferred Work

Items raised in reviews that are real but not actionable now.

## Open

### Retry + streaming bodies (Epic 4 interaction)

- **`Retry` re-invokes `next(request)` with the same `httpx2.Request` on each attempt.** Safe for in-memory bytes/JSON bodies; unsafe for streaming/async-iterable bodies (consumed iterator can't replay). When Epic 4 ships `AsyncClient.stream` (`4-3`), Retry needs to refuse to retry streamed-body requests (or document that callers supply a body factory). Spec: `planning/specs/2026-06-05-retry-and-retry-budget-design.md` §"Open questions".

### Decoder-side

- **`_get_adapter` `lru_cache` is module-global, not per-decoder instance** — keyed by `model` only; two `PydanticDecoder()` instances with different configurations (none today) would share adapters, and the cache survives across tests unless explicitly cleared. Revisit if/when a configurable `PydanticDecoder(mode=..., strict=...)` lands. (`src/httpware/decoders/pydantic.py:12-14`)

## Closed by the 0.3.0 release (2026-06-04)

PR #21 (`feat/v0.3-pydantic-optional`) shipped 0.3.0 with pydantic moved to `[project.optional-dependencies]`, guarded the same way `msgspec` is, and fail-fast at `AsyncClient.__init__` when the extra is missing. Spec/plan archived under `planning/archive/`.

- **`pydantic` import not guarded the way `msgspec` is** — closed. `decoders/pydantic.py` now guards via `import_checker.is_pydantic_installed`; `PydanticDecoder.__init__` raises `ImportError` with the install hint; `AsyncClient(decoder=None)` fail-fast in `_default_pydantic_decoder()`.
- **Empty/malformed payload tests** — closed. `tests/test_decoders_pydantic.py::test_malformed_payload_raises_validation_error` is a 7-case parametrized test pinning current pydantic-core behavior for `b""`, `b"null"`, `b"{}"`, malformed JSON, and invalid UTF-8.

## Closed by the v0.2 thin-wrapper pivot (2026-06-03)

The pivot retired Request/Response/Httpx2Transport/RecordedTransport. The following deferred items are no longer applicable because their host code has been removed or because the responsibility shifted to `httpx2`:

- `extensions=dict(request.extensions)` opaque forwarding (host module removed).
- Unbounded error body size on `StatusError.body` (the `body` field no longer exists; callers reach into `exc.response.content` themselves).
- `httpx2.StreamError` family escape from the transport's `except httpx2.HTTPError` (mapping logic relocated to AsyncClient's terminal; revisit with Epic 4 streaming work).
- Header CRLF / log-injection at the transport seam (host module removed; httpx2 validates).
- Userinfo on `StatusError.request_url` raw field (the field no longer exists; `__repr__` and summary still sanitize).
- Concurrent `aclose()` ↔ `__call__` races on `Httpx2Transport` (host class removed; lifecycle is `httpx2`'s concern).
- URL CRLF / log-injection (httpx2 owns URL validation).
- `request.method` validation beyond uppercasing (host module removed; `httpx2` owns).
- Case-insensitive header type / multi-valued header collapse (host module removed; `httpx2.Headers` already provides case-insensitive multi-valued access).
- Multi-valued query params (host module removed; `httpx2` owns).
- Streaming / async-iterable request bodies (Epic 4 lands on `httpx2.Request` directly).
- `@final` to prevent subclassing of `Request`/`Response`/`ClientConfig` (host classes removed).

# Deferred Work

Items raised in reviews that are real but not actionable now.

## Open

### Decoder-side

- **`_get_adapter` `lru_cache` is module-global, not per-decoder instance** — keyed by `model` only; two `PydanticDecoder()` instances with different configurations (none today) would share adapters, and the cache survives across tests unless explicitly cleared. Revisit if/when a configurable `PydanticDecoder(mode=..., strict=...)` lands. (`src/httpware/decoders/pydantic.py:12-14`)
- **Empty/malformed payload tests** — `b""`, `b"null"`, `b"{}"`, invalid UTF-8: current pydantic-core behavior is correct but unpinned; a future pydantic upgrade could change error types undetected. (`tests/test_decoders_pydantic.py`)

### Tooling

- **Unpinned `ruff`/`ty` with `select=["ALL"]`** — any new ruff release adds rules and can break CI overnight. Pin major versions or pin specific rules when a regression occurs. (`pyproject.toml` `[dependency-groups] lint`, `[tool.ruff.lint] select`)
- **No `[test]` extra; CI installs all extras** — `just install` runs `uv sync --all-extras --group lint`, so every CI run pulls msgspec/otel/niquests even though most tests don't need them. Declare a `test` extra (or move test-only deps into a dedicated dependency-group) and switch CI to the narrower install. (`pyproject.toml` `[project.optional-dependencies]`, `Justfile:install`)
- **`pydantic` import not guarded the way `msgspec` is** — `decoders/pydantic.py` imports `pydantic` at module top; `decoders/msgspec.py` guards via `is_msgspec_installed`. Either drop the optional-extras framing for pydantic (it is already a required dependency) or guard pydantic the same way. (`src/httpware/decoders/pydantic.py:5`, `pyproject.toml` `[project] dependencies`)

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

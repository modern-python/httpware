# Deferred Work

Items raised in reviews that are real but not actionable now.

## Deferred from: retrospective review of stories 1-1 through 1-5 (2026-05-31)

- **`_get_adapter` `lru_cache` is module-global, not per-decoder instance** — keyed by `model` only; two `PydanticDecoder()` instances with different configurations (none today) would share adapters, and the cache survives across tests unless explicitly cleared. Revisit if/when a configurable `PydanticDecoder(mode=..., strict=...)` lands. (`src/httpware/decoders/pydantic.py:12-14`)
- **`extensions=dict(request.extensions)` forwards opaque payloads to httpx2 verbatim** — `httpx2` interprets specific keys (e.g. `timeout`, `sni_hostname`); a typo or unknown key silently bypasses our timeout/limits config. The seam now has a real user: `AsyncClient._build_request` writes `extensions["timeout"]` (`src/httpware/client.py:140-142`). Epic 3 timeout middleware will own the extensions contract; introducing an allowlist now risks blocking legitimate forward-compat uses. (`src/httpware/transports/httpx2.py:121`)

## Deferred from: code review of story-1-5 (2026-05-14)

- **Empty/malformed payload tests** — `b""`, `b"null"`, `b"{}"`, invalid UTF-8: current pydantic-core behavior is correct but unpinned; a future pydantic upgrade could change error types undetected. (`tests/test_decoders_pydantic.py`)

## Deferred from: code review of story-1-4 (2026-05-14)

- **Unbounded error body size** — `StatusError.body` holds the full `resp.content` with no cap; large 5xx pages stay pinned in memory through exception lifetimes (Sentry payloads, logs, retained tracebacks). Revisit with retry/observability middleware. (`src/httpware/transports/httpx2.py:151`)
- **`httpx2.StreamError` family escape** — `StreamError` and its children (`StreamConsumed`, `StreamClosed`, `ResponseNotRead`, `RequestNotRead`) are `RuntimeError` subclasses, not `HTTPError`; not caught by the seam's `except httpx2.HTTPError`. Unreachable via the default httpx2 config (no redirects, no retries) but exploitable through user-supplied clients with retry layers. Revisit when retry middleware or streaming (Story 4.1) lands. (`src/httpware/transports/httpx2.py:127-128`)
- **Header CRLF / log-injection** — extends the existing URL CRLF deferral. `dict(request.headers)` forwards values verbatim including embedded `\r\n`; full sanitization lands with the `Redactor` middleware (Story 5.3). (`src/httpware/transports/httpx2.py:117`)
- **Userinfo on `StatusError.request_url` raw field** — `__repr__` and the exception summary strip `user:pass@`, but the field itself retains credentials, leaking through structured-logging serializers. Defense-in-depth strip is the Redactor's job (Story 5.3) per `errors.py` docstring. (`src/httpware/transports/httpx2.py:155`)
- **Concurrent `aclose()` ↔ `__call__` races** — no synchronization between in-flight `client.send` and a parallel `aclose`. `Httpx2Transport._closed` guards `_get_client`, but a `send` that already obtained the client races a concurrent `aclose`. Best case raises `RuntimeError` (caught and re-raised as `TransportError`); worst case completes on a partly-disposed pool. Broader concurrency/lifecycle design; defer to retry or dedicated lifecycle work. (`src/httpware/transports/httpx2.py:87-181`)

## Deferred from: code review of story-1-4 (2026-05-13)

- **URL CRLF / log-injection** — relying on httpx2's `InvalidURL` validation; explicit `Redactor`-level sanitization deferred to Story 5.3.
- **`request.method` validation beyond uppercasing** — httpx2 surfaces `LocalProtocolError` for malformed methods; no further mitigation in `transports/httpx2.py`.
- **Case-insensitive header type + multi-valued header collapse** — `Mapping[str, str]` with lowercase ASCII keys is the v0 contract. Two limitations bundled: (a) case-insensitive lookup unavailable; (b) `dict(resp.headers)` collapses duplicate-key headers like `Set-Cookie`, `Via`, `Link` to the last value only. Revisit together when header-handling middleware demands either capability — the contract widens to `Mapping[str, Sequence[str]]` (or similar) at that point.

## Deferred from: code review of story-1-2 (2026-05-13)

- **Multi-valued query params** — `Mapping[str, str]` cannot express `?tag=a&tag=b`. Type widening needed. (`src/httpware/request.py:16`)
- **Streaming / async-iterable request bodies** — `body: bytes | None` only. Revisit in streaming work (Story 4.1). (`src/httpware/request.py:18`)
- **`@final` to prevent subclassing** — frozen+slots subclassing is fragile. No current subclasser; defer until needed. (`src/httpware/request.py`, `response.py`, `config.py`)

## Deferred from: code review of story-1-1 (2026-05-13)

- **Unpinned `ruff`/`ty` with `select=["ALL"]`** — any new ruff release adds rules and can break CI overnight. Pin major versions or pin specific rules when a regression occurs. (`pyproject.toml` `[dependency-groups] lint`, `[tool.ruff.lint] select`)
- **No `[test]` extra; CI installs all extras** — `just install` runs `uv sync --all-extras --group lint`, so every CI run pulls msgspec/otel/niquests even though most tests don't need them. Declare a `test` extra (or move test-only deps into a dedicated dependency-group) and switch CI to the narrower install. Mild YAGNI today; revisit when extras grow heavier. (`pyproject.toml` `[project.optional-dependencies]`, `Justfile:install`)

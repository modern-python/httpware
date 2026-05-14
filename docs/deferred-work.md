# Deferred Work

Items raised in reviews that are real but not actionable now.

## Deferred from: code review of story-1-4 (2026-05-14)

- **Unbounded error body size** — `StatusError.body` holds the full `resp.content` with no cap; large 5xx pages stay pinned in memory through exception lifetimes (Sentry payloads, logs, retained tracebacks). Revisit with retry/observability middleware. (`src/httpware/transports/httpx2.py:117-124`)
- **`httpx2.StreamError` family escape** — `StreamError` and its children (`StreamConsumed`, `StreamClosed`, `ResponseNotRead`, `RequestNotRead`) are `RuntimeError` subclasses, not `HTTPError`; not caught by the seam's `except httpx2.HTTPError`. Unreachable via the default httpx2 config (no redirects, no retries) but exploitable through user-supplied clients with retry layers. Revisit when retry middleware lands. (`src/httpware/transports/httpx2.py:103-108`)
- **Header CRLF / log-injection** — extends the existing URL CRLF deferral. `dict(request.headers)` forwards values verbatim including embedded `\r\n`; full sanitization lands with the `Redactor` middleware (Story 5.3). (`src/httpware/transports/httpx2.py:94`)
- **Userinfo on `StatusError.request_url` raw field** — `__repr__` and the exception summary strip `user:pass@`, but the field itself retains credentials, leaking through structured-logging serializers. Defense-in-depth strip is the Redactor's job (Story 5.3) per `errors.py` docstring. (`src/httpware/transports/httpx2.py:123`)
- **Concurrent `aclose()` ↔ `__call__` races** — no synchronization between in-flight `client.send` and a parallel `aclose`. Best case raises `RuntimeError`; worst case completes on a partly-disposed pool. Broader concurrency / lifecycle design; defer to Story 1.7 or retry stories. (`src/httpware/transports/httpx2.py:87-145`)

## Deferred from: code review of story-1-4 (2026-05-13)

- **URL CRLF / log-injection** — relying on httpx2's `InvalidURL` validation; explicit `Redactor`-level sanitization deferred to Story 5.3.
- **`request.method` validation beyond uppercasing** — httpx2 surfaces `LocalProtocolError` for malformed methods; no further mitigation in `transports/httpx2.py`.
- **Case-insensitive header type + multi-valued header collapse** — `Mapping[str, str]` with lowercase ASCII keys is the v0 contract. Two limitations bundled: (a) case-insensitive lookup unavailable; (b) `dict(resp.headers)` collapses duplicate-key headers like `Set-Cookie`, `Via`, `Link` to the last value only. Revisit together when real header-handling middleware (Story 2.3 era) demands either capability — the contract widens to `Mapping[str, Sequence[str]]` (or similar) at that point.

## Deferred from: code review of story-1-3 (2026-05-13)

Resolved by Story 1.4: method uppercased at seam; httpx2 returns lowercased headers (v0 contract); CRLF mitigation via `httpx2.InvalidURL`.

## Deferred from: code review of story-1-2 (2026-05-13)

- **Charset parser robustness** — quoted whitespace, mismatched quotes, multi-`charset=` directives, substring false-positives (e.g. `boundary` containing `charset=`). (`src/httpware/response.py:21-26`)
- **Header name/value validation** — `with_header` accepts CR/LF (injection), `None`, empty string. Lands with header-handling story (2.3 or later). (`src/httpware/request.py:21-23`)
- **URL validation** — `with_url("")` accepts empty; `base_url` has no trailing-slash normalization. (`src/httpware/request.py:25-27`, `src/httpware/config.py:27-33`)
- **`with_query(None)` handling** — currently accepted and breaks downstream iteration. (`src/httpware/request.py:33-35`)
- **`Timeout` / `Limits` negative-value validation** — no `__post_init__` guard; nonsensical values silently accepted. (`src/httpware/config.py:10-22`)
- **Multi-valued query params** — `Mapping[str, str]` cannot express `?tag=a&tag=b`. Type widening needed. (`src/httpware/request.py:8`)
- **Streaming / async-iterable request bodies** — `body: bytes | None` only. Revisit in transport stories. (`src/httpware/request.py:11`)
- **`with_headers` / `with_cookie` / `with_extension` merge helpers** — only `with_header` (single) and `with_query` (replace) exist. Story 2.3 will fill this in. (`src/httpware/request.py:20-35`)
- **`Response.json()` honor declared charset** — `json.loads(bytes)` auto-detects only UTF-8/16/32. Real APIs vary. (`src/httpware/response.py:44-45`)
- **`@final` to prevent subclassing** — frozen+slots subclassing is fragile. No current subclasser; defer until needed. (`src/httpware/request.py`, `response.py`, `config.py`)

## Deferred from: code review of story-1-1 (2026-05-13)

- **Codecov upload fails on fork PRs** — fork PRs cannot access `CODECOV_TOKEN`; matches modern-di pattern, accepted tradeoff. (`.github/workflows/ci.yml:46-52`)
- **`just publish` lacks env-var validation** — recipe assumes `GITHUB_REF_NAME` and `PYPI_TOKEN` are set; running locally could corrupt the version. Add `test -n "$GITHUB_REF_NAME"` guard before release work. (`Justfile:25-29`)
- **`uv_build>=0.11,<0.12` narrow window** — single-minor band will expire as soon as uv_build 0.12 ships; bump when that happens. (`pyproject.toml:54`)
- **Python 3.14 wheel availability risk** — `httpx2` / `pydantic` / `uv_build` may not have 3.14 wheels yet, breaking the matrix entry. Watch CI red on 3.14. (`.github/workflows/ci.yml:30-33`)
- **Unpinned `ruff`/`ty` with `select=["ALL"]`** — any new ruff release adds rules and can break CI overnight. Pin major versions or pin specific rules when a regression occurs. (`pyproject.toml:70-72, 84-85`)
- **No `[test]` extra; CI uses `--all-extras`** — future heavy extras will be installed in every CI run. Declare a `test` extra and switch CI to `--extra test`. (`pyproject.toml:35-47`)

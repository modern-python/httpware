---
status: draft
date: 2026-06-14
slug: security-hardening
spec: security-hardening
pr: null
---

# security-hardening — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps
> use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redact URL secrets across logs/telemetry/errors and add an opt-in
Content-Length-gated bound on the `stream()` error-body pre-read, closing the
2026-06-14 deep-audit security cluster.

**Spec:** [`design.md`](./design.md)

**Branch:** `feat/security-hardening` (already created)

**Commit strategy:** Per-task commits, TDD (failing test → implement → green →
commit).

**Conventions reminder:** Python 3.11+, no `from __future__ import
annotations`, no `print()`, no `httpx2._` private API, type suppressions are
`# ty: ignore[...]`. Run tests with coverage disabled during TDD via
`uv run pytest <path> -o addopts="" -q`; the full gate is `just test` (100%
line coverage) + `just lint`.

---

### Task 1: `redact_url` sanitizer module

**Files:**
- Create: `src/httpware/_internal/redaction.py`
- Create: `tests/test_redaction.py`

Owns all URL sanitation: strip `user:pass@` userinfo and mask the values of
known-sensitive query parameters.

- [ ] **Step 1: Write the failing tests** in `tests/test_redaction.py`:

```python
"""Unit tests for the URL redaction helper."""

import pytest

from httpware._internal.redaction import redact_url


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        # no-op cases (common-path guard: bytes unchanged)
        ("https://example.test/path", "https://example.test/path"),
        ("https://example.test/path?page=2&limit=10", "https://example.test/path?page=2&limit=10"),
        ("not-a-url", "not-a-url"),
        ("https://example.test", "https://example.test"),
        # userinfo stripped
        ("https://user:pass@example.test/p", "https://example.test/p"),
        ("https://user:pass@example.test:8443/p", "https://example.test:8443/p"),
        ("https://user:pass@[2001:db8::1]:8443/p", "https://[2001:db8::1]:8443/p"),
        # sensitive query value masked, key + other params preserved
        ("https://example.test/p?api_key=abc123", "https://example.test/p?api_key=REDACTED"),
        ("https://example.test/p?page=2&access_token=xyz", "https://example.test/p?page=2&access_token=REDACTED"),
        # case-insensitive key match
        ("https://example.test/p?API_KEY=abc", "https://example.test/p?API_KEY=REDACTED"),
        # userinfo AND query both handled
        ("https://u:p@example.test/p?token=t", "https://example.test/p?token=REDACTED"),
    ],
)
def test_redact_url(url: str, expected: str) -> None:
    assert redact_url(url) == expected


def test_redact_url_masks_repeated_sensitive_keys() -> None:
    result = redact_url("https://example.test/p?token=a&token=b&page=1")
    assert "token=a" not in result
    assert "token=b" not in result
    assert result.count("token=REDACTED") == 2  # noqa: PLR2004 — two token params above
    assert "page=1" in result


def test_redact_url_masks_blank_sensitive_value() -> None:
    assert redact_url("https://example.test/p?secret=") == "https://example.test/p?secret=REDACTED"
```

- [ ] **Step 2: Run to verify failure**

  Run: `uv run pytest tests/test_redaction.py -o addopts="" -q`
  Expected: FAIL — `ModuleNotFoundError: No module named 'httpware._internal.redaction'`.

- [ ] **Step 3: Implement** `src/httpware/_internal/redaction.py`:

```python
"""URL sanitation for logs, telemetry, and error messages.

Strips ``user:pass@`` userinfo and masks the values of known-sensitive query
parameters so secrets embedded in URLs do not leak into observability output.
Shared by ``errors.py`` (StatusError messages) and the resilience middleware
(event attributes).
"""

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


SENSITIVE_QUERY_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "access_token",
        "refresh_token",
        "token",
        "secret",
        "client_secret",
        "password",
        "passwd",
        "pwd",
        "auth",
        "authorization",
        "sig",
        "signature",
        "key",
        "private_key",
        "session",
        "sessionid",
        "x-api-key",
    }
)

_REDACTED = "REDACTED"


def _strip_userinfo(url: str) -> str:
    if "@" not in url or "://" not in url:
        return url
    parts = urlsplit(url)
    if parts.username is None and parts.password is None:
        return url
    hostname = parts.hostname or ""
    if ":" in hostname:  # IPv6 literal — re-wrap in brackets
        hostname = f"[{hostname}]"
    netloc = hostname
    if parts.port is not None:
        netloc = f"{netloc}:{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def _mask_query(url: str) -> str:
    parts = urlsplit(url)
    if not parts.query:
        return url
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    if not any(key.lower() in SENSITIVE_QUERY_KEYS for key, _ in pairs):
        return url  # common-path guard: nothing sensitive, leave bytes untouched
    masked = [(key, _REDACTED if key.lower() in SENSITIVE_QUERY_KEYS else value) for key, value in pairs]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(masked), parts.fragment))


def redact_url(url: str) -> str:
    """Return ``url`` safe for logs/telemetry/errors.

    Userinfo is stripped and the values of known-sensitive query parameters are
    replaced with ``REDACTED`` (keys preserved). URLs with no sensitive query
    key are returned byte-identical to the userinfo-stripped input.
    """
    return _mask_query(_strip_userinfo(url))
```

- [ ] **Step 4: Run to verify pass**

  Run: `uv run pytest tests/test_redaction.py -o addopts="" -q`
  Expected: PASS (all parametrized cases + the two extra tests).

- [ ] **Step 5: Commit**

  ```bash
  git add src/httpware/_internal/redaction.py tests/test_redaction.py
  git commit -m "feat(redaction): URL sanitizer (strip userinfo + mask sensitive query keys)

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 2: Route `StatusError` messages through `redact_url`

**Files:**
- Modify: `src/httpware/errors.py`
- Modify: `tests/test_errors.py`

Replace the userinfo-only `_strip_userinfo` in `errors.py` with `redact_url`,
and delete the now-duplicated local helper.

- [ ] **Step 1: Write the failing test** — append to `tests/test_errors.py`:

```python
def test_status_error_message_masks_query_secret() -> None:
    request = httpx2.Request("GET", "https://example.test/p?api_key=topsecret&page=2")
    response = httpx2.Response(404, request=request)
    exc = NotFoundError(response)
    assert "topsecret" not in str(exc)
    assert "api_key=REDACTED" in str(exc)
    assert "page=2" in str(exc)
    assert "topsecret" not in repr(exc)
```

  (Confirm `httpx2` and `NotFoundError` are already imported at the top of
  `tests/test_errors.py`; add `from httpware.errors import NotFoundError` /
  `import httpx2` only if missing.)

- [ ] **Step 2: Run to verify failure**

  Run: `uv run pytest tests/test_errors.py -k masks_query_secret -o addopts="" -q`
  Expected: FAIL — `assert 'api_key=REDACTED' in '404 GET https://example.test/p?api_key=topsecret&page=2'`.

- [ ] **Step 3: Implement** in `src/httpware/errors.py`:

  3a. Replace the module docstring lines about stripping (currently):

```python
"""Status-keyed exception hierarchy.

Auto-raise rule lives at AsyncClient's internal terminal (see client.py).
Unknown 4xx falls back to ClientStatusError; unknown 5xx to ServerStatusError.
The fallback assumes 400 <= status < 600.

__repr__ and the summary message strip user:pass@ userinfo from
response.request.url to avoid leaking credentials in tracebacks.
Query-string secrets are NOT stripped here.
"""
```

  with:

```python
"""Status-keyed exception hierarchy.

Auto-raise rule lives at AsyncClient's internal terminal (see client.py).
Unknown 4xx falls back to ClientStatusError; unknown 5xx to ServerStatusError.
The fallback assumes 400 <= status < 600.

__repr__ and the summary message run response.request.url through
_internal.redaction.redact_url, which strips user:pass@ userinfo and masks the
values of known-sensitive query parameters. NOTE: the full request headers
(Authorization, Cookie, ...) remain reachable via exc.response.request — handler
authors must redact those before logging.
"""
```

  3b. Replace the `urllib.parse` import line:

```python
from urllib.parse import urlsplit, urlunsplit
```

  with:

```python
from httpware._internal.redaction import redact_url
```

  (Place it with the other `httpware`/third-party imports per isort ordering;
  `ruff --fix` will reorder if needed.)

  3c. Delete the entire `_strip_userinfo` function (the `def _strip_userinfo(url: str) -> str:` block).

  3d. In `_summary` and `__repr__`, change both occurrences of:

```python
        url = _strip_userinfo(str(self.response.request.url))
```

  to:

```python
        url = redact_url(str(self.response.request.url))
```

- [ ] **Step 4: Run to verify pass**

  Run: `uv run pytest tests/test_errors.py -o addopts="" -q`
  Expected: PASS (new test plus all existing `StatusError` tests — existing
  userinfo-stripping assertions still hold because `redact_url` strips userinfo).

- [ ] **Step 5: Commit**

  ```bash
  git add src/httpware/errors.py tests/test_errors.py
  git commit -m "fix(errors): mask query secrets in StatusError messages via redact_url

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 3: Route all middleware event URLs through a shared helper

**Files:**
- Modify: `src/httpware/_internal/observability.py`
- Modify: `src/httpware/middleware/resilience/retry.py` (6 sites)
- Modify: `src/httpware/middleware/resilience/bulkhead.py` (2 sites)
- Modify: `src/httpware/middleware/resilience/circuit_breaker.py` (1 site)
- Modify: `src/httpware/middleware/resilience/timeout.py` (1 site)
- Modify: `tests/test_retry.py` (async leakage test)
- Modify: `tests/test_retry_sync.py` (sync parity)

Add one `_observed_url(request)` helper and route every emit site through it,
so a future emit site can't silently reintroduce the leak.

- [ ] **Step 1: Write the failing test** — append to `tests/test_retry.py`
  (mirror the existing `caplog` event tests; the event attribute is reachable
  as `record.url`):

```python
async def test_retry_event_url_attribute_masks_query_secret(caplog: pytest.LogCaptureFixture) -> None:
    """Resilience event `url` attributes must not leak query-string secrets."""
    sleeper = _SleepRecorder()
    handler = _ResponseSequence([HTTPStatus.SERVICE_UNAVAILABLE] * 3)
    client = _client(handler, retry=AsyncRetry(_sleep=sleeper, max_attempts=3, base_delay=0.001, max_delay=0.002))

    with caplog.at_level(logging.WARNING, logger="httpware.retry"), pytest.raises(ServiceUnavailableError):
        await client.get("https://example.test/x?api_key=topsecret")

    giving_up = [r for r in caplog.records if r.name == "httpware.retry" and r.message.startswith("retry gave up")]
    assert len(giving_up) == 1
    assert "topsecret" not in giving_up[0].url  # ty: ignore[unresolved-attribute]
    assert "api_key=REDACTED" in giving_up[0].url  # ty: ignore[unresolved-attribute]
```

  (Use the same `_client`, `_SleepRecorder`, `_ResponseSequence` helpers the
  surrounding tests use; do not invent new fixtures.)

- [ ] **Step 2: Run to verify failure**

  Run: `uv run pytest tests/test_retry.py -k event_url_attribute_masks -o addopts="" -q`
  Expected: FAIL — `assert 'topsecret' not in 'https://example.test/x?api_key=topsecret'`.

- [ ] **Step 3a: Add the helper** to `src/httpware/_internal/observability.py`.
  Add the import near the top (with the existing imports):

```python
import httpx2

from httpware._internal.redaction import redact_url
```

  and add this function (below `_emit_event`):

```python
def _observed_url(request: httpx2.Request) -> str:
    """Return the request URL safe for emission (userinfo + sensitive query masked)."""
    return redact_url(str(request.url))
```

- [ ] **Step 3b: Route every emit site.** In each of `retry.py`, `bulkhead.py`,
  `circuit_breaker.py`, `timeout.py`:

  - Extend the existing import `from httpware._internal.observability import _emit_event` to:

```python
from httpware._internal.observability import _emit_event, _observed_url
```

  - Replace every attributes-dict line `"url": str(request.url),` with
    `"url": _observed_url(request),`. Sites: `retry.py` lines ~136, 155, 171,
    274, 293, 309; `bulkhead.py` ~117, 173; `circuit_breaker.py` ~193;
    `timeout.py` ~72. Grep to confirm none remain:
    `grep -rn 'str(request.url)' src/httpware/middleware/` must return zero
    lines after this step.

- [ ] **Step 4a: Add the sync parity test** — append to `tests/test_retry_sync.py`
  (sync analogue, using that file's sync helpers and a `with pytest.raises(...)`
  around a sync call; no `await`):

```python
def test_retry_event_url_attribute_masks_query_secret_sync(caplog: pytest.LogCaptureFixture) -> None:
    """Sync resilience event `url` attributes must not leak query-string secrets."""
    sleeper = _SleepRecorder()
    handler = _ResponseSequence([HTTPStatus.SERVICE_UNAVAILABLE] * 3)
    client = _client(handler, retry=Retry(_sleep=sleeper, max_attempts=3, base_delay=0.001, max_delay=0.002))

    with caplog.at_level(logging.WARNING, logger="httpware.retry"), pytest.raises(ServiceUnavailableError):
        client.get("https://example.test/x?api_key=topsecret")

    giving_up = [r for r in caplog.records if r.name == "httpware.retry" and r.message.startswith("retry gave up")]
    assert len(giving_up) == 1
    assert "topsecret" not in giving_up[0].url  # ty: ignore[unresolved-attribute]
    assert "api_key=REDACTED" in giving_up[0].url  # ty: ignore[unresolved-attribute]
```

  (Match the exact constructor/helper names used elsewhere in
  `tests/test_retry_sync.py` — e.g. `Retry`, the sync `_client`,
  `_SleepRecorder`, `_ResponseSequence`. Adjust names if that file's helpers
  differ.)

- [ ] **Step 4b: Run to verify pass**

  Run: `uv run pytest tests/test_retry.py tests/test_retry_sync.py -k masks_query_secret -o addopts="" -q`
  Expected: PASS (async + sync).

- [ ] **Step 5: Commit**

  ```bash
  git add src/httpware/_internal/observability.py src/httpware/middleware/resilience/ tests/test_retry.py tests/test_retry_sync.py
  git commit -m "fix(observability): mask query secrets in resilience event URLs

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 4: `ResponseTooLargeError` exception

**Files:**
- Modify: `src/httpware/errors.py`
- Modify: `src/httpware/__init__.py`
- Modify: `tests/test_errors.py`
- Modify: `tests/test_public_api.py`

New `ClientError` subclass (non-`StatusError`, so it defines `__init__` +
`__reduce__`, per the convention in CLAUDE.md).

- [ ] **Step 1: Write the failing tests** — append to `tests/test_errors.py`:

```python
def test_response_too_large_error_fields_and_message() -> None:
    exc = ResponseTooLargeError(status_code=500, limit=1024, content_length=2048)
    assert exc.status_code == 500  # noqa: PLR2004 — literal mirrors construction above
    assert exc.limit == 1024  # noqa: PLR2004 — literal mirrors construction above
    assert exc.content_length == 2048  # noqa: PLR2004 — literal mirrors construction above
    assert "1024" in str(exc)
    assert "2048" in str(exc)


def test_response_too_large_error_pickle_round_trip() -> None:
    exc = ResponseTooLargeError(status_code=503, limit=10, content_length=None)
    restored = pickle.loads(pickle.dumps(exc))  # noqa: S301 — round-tripping our own exception
    assert isinstance(restored, ResponseTooLargeError)
    assert restored.status_code == 503  # noqa: PLR2004 — literal mirrors construction above
    assert restored.limit == 10  # noqa: PLR2004 — literal mirrors construction above
    assert restored.content_length is None
```

  Add `ResponseTooLargeError` to the `from httpware.errors import (...)` /
  `from httpware import ...` block at the top of `tests/test_errors.py`, and
  ensure `import pickle` is present at module top (the existing `__reduce__`
  round-trip tests almost certainly import it already; add it if not — do
  **not** import inside the function, ruff `PLC0415` forbids it).

- [ ] **Step 2: Run to verify failure**

  Run: `uv run pytest tests/test_errors.py -k response_too_large -o addopts="" -q`
  Expected: FAIL — `ImportError: cannot import name 'ResponseTooLargeError'`.

- [ ] **Step 3a: Implement** in `src/httpware/errors.py` — add after the
  `MissingDecoderError` class (end of file):

```python
def _reconstruct_response_too_large(
    cls: "type[ResponseTooLargeError]",
    status_code: int,
    limit: int,
    content_length: int | None,
) -> "ResponseTooLargeError":
    return cls(status_code=status_code, limit=limit, content_length=content_length)


class ResponseTooLargeError(ClientError):
    """Raised when an error response body exceeds the client's max_error_body_bytes cap.

    Fires from stream() on a 4xx/5xx whose declared Content-Length exceeds the
    configured cap, BEFORE the body is read — so the oversized body is never
    buffered. Only raised when max_error_body_bytes is set (opt-in).
    """

    status_code: int
    limit: int
    content_length: int | None

    def __init__(self, *, status_code: int, limit: int, content_length: int | None) -> None:
        self.status_code = status_code
        self.limit = limit
        self.content_length = content_length
        super().__init__(
            f"error response body too large: status={status_code} "
            f"content_length={content_length} exceeds max_error_body_bytes={limit}"
        )

    def __reduce__(self) -> tuple[Any, ...]:
        return (
            _reconstruct_response_too_large,
            (type(self), self.status_code, self.limit, self.content_length),
        )
```

- [ ] **Step 3b: Export** in `src/httpware/__init__.py`: add
  `ResponseTooLargeError` to the `from httpware.errors import (...)` block
  (alphabetically, after `RateLimitedError`) and add `"ResponseTooLargeError",`
  to `__all__` (alphabetically, after `"ResponseDecoder",`).

- [ ] **Step 3c: Update the public-API test.** In `tests/test_public_api.py`,
  add `"ResponseTooLargeError"` to whatever expected-symbol collection the test
  asserts against (read the file; match its existing structure exactly).

- [ ] **Step 4: Run to verify pass**

  Run: `uv run pytest tests/test_errors.py tests/test_public_api.py -o addopts="" -q`
  Expected: PASS.

- [ ] **Step 5: Commit**

  ```bash
  git add src/httpware/errors.py src/httpware/__init__.py tests/test_errors.py tests/test_public_api.py
  git commit -m "feat(errors): add ResponseTooLargeError (opt-in error-body cap)

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 5: Opt-in `max_error_body_bytes` + bounded `stream()` pre-read

**Files:**
- Modify: `src/httpware/client.py` (both constructors, both `stream()`, new helper)
- Modify: `tests/test_client_stream.py` (async)
- Modify: `tests/test_client_stream_sync.py` (sync)

- [ ] **Step 1: Write the failing tests.**

  1a. Async — append to `tests/test_client_stream.py` (use that file's existing
  `httpx2.MockTransport` construction style; the helper names below mirror the
  conftest/fixture pattern — adjust to match the file):

```python
async def test_stream_raises_response_too_large_when_over_cap() -> None:
    body = b"x" * 200

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(500, content=body)

    client = AsyncClient(httpx2_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)), max_error_body_bytes=10)
    with pytest.raises(ResponseTooLargeError) as caught:
        async with client.stream("GET", "https://example.test/x"):
            pass
    assert caught.value.limit == 10  # noqa: PLR2004 — mirrors max_error_body_bytes above
    assert caught.value.content_length == 200  # noqa: PLR2004 — len(body) above
    await client.aclose()


async def test_stream_reads_error_body_when_under_cap() -> None:
    body = b"nope"

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(404, content=body)

    client = AsyncClient(httpx2_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)), max_error_body_bytes=1000)
    with pytest.raises(NotFoundError) as caught:
        async with client.stream("GET", "https://example.test/x"):
            pass
    assert caught.value.response.content == body
    await client.aclose()


async def test_stream_unbounded_by_default_reads_large_error_body() -> None:
    body = b"x" * 200

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(500, content=body)

    client = AsyncClient(httpx2_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)))
    with pytest.raises(InternalServerError) as caught:
        async with client.stream("GET", "https://example.test/x"):
            pass
    assert caught.value.response.content == body
    await client.aclose()
```

  Ensure `ResponseTooLargeError`, `NotFoundError`, `InternalServerError`, and
  `AsyncClient` are imported at the top of the test file (add any missing).

  1b. Sync — append the sync analogues to `tests/test_client_stream_sync.py`
  (use `Client`, `httpx2.Client`, `with client.stream(...)`, `client.close()`,
  no `await`): `test_stream_raises_response_too_large_when_over_cap_sync`,
  `test_stream_reads_error_body_when_under_cap_sync`,
  `test_stream_unbounded_by_default_reads_large_error_body_sync`.

  1c. `_parse_content_length` unit tests — append to
  `tests/test_client_stream.py`:

```python
@pytest.mark.parametrize(
    ("raw", "expected"),
    [(None, None), ("123", 123), ("abc", None), ("-5", None), ("0", 0)],
)
def test_parse_content_length(raw: str | None, expected: int | None) -> None:
    assert _parse_content_length(raw) == expected
```

  Add `from httpware.client import _parse_content_length` to the **top** imports
  of `tests/test_client_stream.py` (module level — ruff `PLC0415` forbids a
  function-body import).

- [ ] **Step 2: Run to verify failure**

  Run: `uv run pytest tests/test_client_stream.py tests/test_client_stream_sync.py -k "too_large or under_cap or unbounded or parse_content_length" -o addopts="" -q`
  Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'max_error_body_bytes'` (and `ImportError` for `_parse_content_length`).

- [ ] **Step 3a: Add the helper** to `src/httpware/client.py` (module level,
  near `_build_default_decoders`):

```python
def _parse_content_length(raw: str | None) -> int | None:
    """Return a non-negative int Content-Length, or None for missing/garbage. Never raises."""
    if raw is None:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value >= 0 else None
```

- [ ] **Step 3b: Import the exception.** Change client.py's errors import:

```python
from httpware.errors import DecodeError, MissingDecoderError, TransportError
```

  to:

```python
from httpware.errors import DecodeError, MissingDecoderError, ResponseTooLargeError, TransportError
```

- [ ] **Step 3c: AsyncClient constructor.** Add the class annotation under the
  other `_`-prefixed annotations in `class AsyncClient` (after `_dispatch: AsyncNext`):

```python
    _max_error_body_bytes: int | None
```

  Add the parameter to `AsyncClient.__init__` (keyword-only, after
  `middleware: Sequence[AsyncMiddleware] = (),`):

```python
        max_error_body_bytes: int | None = None,
```

  And store it (after `self._dispatch = compose_async(...)`):

```python
        self._max_error_body_bytes = max_error_body_bytes
```

- [ ] **Step 3d: Client constructor.** Mirror 3c in `class Client`: add
  `_max_error_body_bytes: int | None` annotation (after `_dispatch: Next`), add
  the `max_error_body_bytes: int | None = None,` param after
  `middleware: Sequence[Middleware] = (),`, and add
  `self._max_error_body_bytes = max_error_body_bytes` after
  `self._dispatch = compose(...)`.

- [ ] **Step 3e: Bound the async stream pre-read.** Replace (around line 786):

```python
        async with _httpx2_exception_mapper(), self._httpx2_client.stream(method, url, **kwargs) as response:
            if HTTPStatus.BAD_REQUEST <= response.status_code < 600:  # noqa: PLR2004 — 600 is the synthetic upper bound for 5xx
                await response.aread()  # pre-read body so exc.response.content works
                _raise_on_status_error(response)
            yield response
```

  with:

```python
        async with _httpx2_exception_mapper(), self._httpx2_client.stream(method, url, **kwargs) as response:
            if HTTPStatus.BAD_REQUEST <= response.status_code < 600:  # noqa: PLR2004 — 600 is the synthetic upper bound for 5xx
                if self._max_error_body_bytes is not None:
                    content_length = _parse_content_length(response.headers.get("content-length"))
                    if content_length is not None and content_length > self._max_error_body_bytes:
                        raise ResponseTooLargeError(
                            status_code=response.status_code,
                            limit=self._max_error_body_bytes,
                            content_length=content_length,
                        )
                await response.aread()  # pre-read body so exc.response.content works
                _raise_on_status_error(response)
            yield response
```

- [ ] **Step 3f: Bound the sync stream pre-read.** Replace (around line 1548)
  the sync equivalent the same way, using `response.read()` (no `await`):

```python
        with _httpx2_exception_mapper_sync(), self._httpx2_client.stream(method, url, **kwargs) as response:
            if HTTPStatus.BAD_REQUEST <= response.status_code < 600:  # noqa: PLR2004 — 600 is the synthetic upper bound for 5xx
                if self._max_error_body_bytes is not None:
                    content_length = _parse_content_length(response.headers.get("content-length"))
                    if content_length is not None and content_length > self._max_error_body_bytes:
                        raise ResponseTooLargeError(
                            status_code=response.status_code,
                            limit=self._max_error_body_bytes,
                            content_length=content_length,
                        )
                response.read()  # pre-read body so exc.response.content works
                _raise_on_status_error(response)
            yield response
```

- [ ] **Step 4: Run to verify pass**

  Run: `uv run pytest tests/test_client_stream.py tests/test_client_stream_sync.py -o addopts="" -q`
  Expected: PASS.

- [ ] **Step 5: Commit**

  ```bash
  git add src/httpware/client.py tests/test_client_stream.py tests/test_client_stream_sync.py
  git commit -m "feat(client): opt-in max_error_body_bytes bounds the stream() error pre-read

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 6: Documentation — architecture + deferred item

**Files:**
- Modify: `architecture/client.md`
- Modify: `architecture/errors.md`
- Modify: `planning/deferred.md`

Docs only; no code. (Read each file first and match its prose style.)

- [ ] **Step 1: `architecture/client.md`** — add two short subsections:

  - **Proxy environment (`trust_env`):** "httpware wraps an
    `httpx2.Client`/`httpx2.AsyncClient`, which default to `trust_env=True`:
    `HTTP_PROXY`/`HTTPS_PROXY`/`NO_PROXY` and `.netrc` are honored by default.
    To opt out, pass an explicit client:
    `Client(httpx2_client=httpx2.Client(trust_env=False))`."
  - **Bounded error bodies:** document `max_error_body_bytes` (default `None`,
    opt-in), that it raises `ResponseTooLargeError` from `stream()` when a
    4xx/5xx **declares** a `Content-Length` over the cap before reading, and the
    residual: a chunked error body with no declared length is still read,
    because a hard mid-read cap would require httpx2's private `_content`.

- [ ] **Step 2: `architecture/errors.md`** — add a callout: `StatusError` holds
  the raw `httpx2.Response`, so secrets in **request headers**
  (`Authorization`, `Cookie`, `Proxy-Authorization`) remain reachable via
  `exc.response.request.headers`; httpware masks URL userinfo and known-sensitive
  query values in messages/`repr`, but does not strip headers — handler authors
  must redact before logging or serializing a caught error. Mention
  `ResponseTooLargeError` in the error list/tree if the file enumerates the
  hierarchy.

- [ ] **Step 3: `planning/deferred.md`** — add an entry: "Non-streaming hard
  response-body cap — for non-streaming `send()`, httpx2 buffers the whole body
  before the decode seam, so a true cap needs a streaming-with-capped-accumulator
  rework of the Seam-A terminal. Revisit trigger: the Seam-A terminal is next
  reworked, or a concrete large-response abuse is reported. Source: 2026-06-14
  deep audit (Medium)." Match the file's existing entry format.

- [ ] **Step 4: Commit**

  ```bash
  git add architecture/client.md architecture/errors.md planning/deferred.md
  git commit -m "docs: trust_env + bounded-error-body + header-reachability callouts

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 7: Full verification

**Files:** none (gate only).

- [ ] **Step 1: Lint**

  Run: `just lint`
  Expected: eof-fixer + ruff format + ruff check + ty all clean. (If ruff
  reordered imports in `errors.py`/`observability.py`/`client.py`, that's
  expected; re-stage and amend the relevant task commit or add a fixup commit.)

- [ ] **Step 2: Full suite + coverage**

  Run: `just test`
  Expected: all tests pass, **coverage 100%**. If `redaction.py` or the new
  error class shows a missing line, add the covering assertion (do NOT add
  `# pragma: no cover`).

- [ ] **Step 3: Grep guards**

  Run:
  ```bash
  grep -rn 'str(request.url)' src/httpware/middleware/ ; echo "[expect none]"
  grep -rn 'httpx2\._' src/httpware/ ; echo "[expect none]"
  ```
  Expected: both empty.

- [ ] **Step 4: Final report** — summarize bucket of findings closed (3 leakage
  Lows folded + the streaming Medium bounded + trust_env Nit documented), and
  that the non-streaming hard cap was deferred.

---

## Notes for the executor

- **TDD discipline:** every code task starts with a failing test and the exact
  failure message is given — confirm you see it before implementing.
- **Sync/async parity:** Tasks 3 and 5 touch both surfaces; never land one
  without its sibling test.
- **No `# pragma: no cover`** — `just test` enforces 100% line coverage; the
  plan's tests are designed to reach every new line (`_parse_content_length`
  branches via its direct unit test; the redaction common-path guard via the
  no-op parametrized cases).
- **Helper-name reality check:** the test snippets assume helper names
  (`_client`, `_SleepRecorder`, `_ResponseSequence`, `_SleepRecorder`) from the
  existing test files. Open each target test file first and match its actual
  fixtures; adjust the snippet names if they differ, keeping the assertions.

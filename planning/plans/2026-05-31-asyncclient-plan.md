# AsyncClient Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship Story 1-7: a `AsyncClient` class at `src/httpware/client.py` with 8 HTTP method shortcuts, typed `response_model` overloads, lifecycle management, and `with_options` returning lifecycle-view clients.

**Architecture:** Single new module `src/httpware/client.py` (~350 lines, heavy with type signatures). Extends the existing `ClientConfig` with `decoder` and `middleware` fields. Composes the middleware chain at construction via `compose()` (Story 2-1) and stores the resulting `Next` callable. HTTP methods are 2-line shims that call a shared `_send` helper. Lifecycle uses a private `_owns_transport` flag to distinguish the original client (closes the transport on `__aexit__`) from `with_options` views (no-op on close).

**Tech Stack:** Python 3.11 floor. Existing deps only (`pydantic`, `httpx2` via transport, stdlib `json`). `typing.overload` for response_model typing.

**Branch:** `story/1-7-asyncclient` (already created; spec commit `bebb1dd` is on it).

**Spec:** `docs/superpowers/specs/2026-05-31-asyncclient-design.md`.

---

## File Structure

**New files:**
- `src/httpware/client.py` — `AsyncClient` class with construction, HTTP methods, lifecycle, `with_options`.
- `tests/test_client_construction.py` — defaults, `from_url`, timeout normalization, param validation.
- `tests/test_client_methods.py` — 8 HTTP methods build correct Requests; default merging; URL resolution; body params.
- `tests/test_client_response_model.py` — decoder invocation by `response_model`.
- `tests/test_client_typing.py` — `ty`-checked file verifying overload return types.
- `tests/test_client_lifecycle.py` — `__aenter__`/`__aexit__`, view no-op, double-close.
- `tests/test_client_middleware_wiring.py` — middleware execution + re-composition via `with_options`.

**Modified files:**
- `src/httpware/config.py` — extend `ClientConfig` with `decoder` and `middleware` fields.
- `src/httpware/__init__.py` — export `AsyncClient`, add to `__all__`.
- `CHANGELOG.md` — Story 1.7 bullet.

**Files NOT touched:** `request.py`, `response.py`, `errors.py`, `decoders/*`, `middleware/*`, `_internal/*`, `transports/*`.

---

## Task 1: Extend `ClientConfig` with `decoder` and `middleware` fields

Backwards-compatible addition. Existing `tests/test_config.py` keeps passing because both new fields have defaults.

**Files:**
- Modify: `src/httpware/config.py`
- Modify: `tests/test_config.py` (append two assertions to the existing defaults test)

- [ ] **Step 1: Add the failing assertions**

Edit `tests/test_config.py`. Find `test_client_config_defaults` and append two assertions:

```python
def test_client_config_defaults() -> None:
    cfg = ClientConfig()
    assert cfg.base_url is None
    assert cfg.default_headers == {}
    assert cfg.default_query == {}
    assert cfg.timeout == Timeout()
    assert cfg.limits == Limits()
    # NEW for Story 1.7:
    from httpware.decoders.pydantic import PydanticDecoder  # noqa: PLC0415 — local to keep import ordering tidy
    assert isinstance(cfg.decoder, PydanticDecoder)
    assert cfg.middleware == ()
```

(Note: the `# noqa: PLC0415` here is a temporary stand-in if ruff flags the in-function import; if not flagged, drop the noqa. The preferred fix is to add `from httpware.decoders.pydantic import PydanticDecoder` to the top-level imports — do that instead and remove the in-function import.)

Re-run: `uv run pytest tests/test_config.py::test_client_config_defaults -v`
Expected: `AttributeError: 'ClientConfig' object has no attribute 'decoder'`.

- [ ] **Step 2: Extend `ClientConfig`**

Edit `src/httpware/config.py`. Current state:

```python
"""Immutable configuration value types: Limits, Timeout, ClientConfig."""

from collections.abc import Mapping
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class Timeout:
    """Per-phase request timeout configuration (seconds)."""

    connect: float = 5.0
    read: float = 30.0
    write: float = 30.0
    pool: float = 5.0


@dataclass(frozen=True, slots=True)
class Limits:
    """Connection-pool limits."""

    max_connections: int = 100
    max_keepalive_connections: int = 20
    keepalive_expiry: float = 5.0


@dataclass(frozen=True, slots=True)
class ClientConfig:
    """Immutable client configuration bag."""

    base_url: str | None = None
    default_headers: Mapping[str, str] = field(default_factory=dict)
    default_query: Mapping[str, str] = field(default_factory=dict)
    timeout: Timeout = field(default_factory=Timeout)
    limits: Limits = field(default_factory=Limits)
```

Add two imports and two fields. Final file:

```python
"""Immutable configuration value types: Limits, Timeout, ClientConfig."""

from collections.abc import Mapping
from dataclasses import dataclass, field

from httpware.decoders import ResponseDecoder
from httpware.decoders.pydantic import PydanticDecoder
from httpware.middleware import Middleware


@dataclass(frozen=True, slots=True)
class Timeout:
    """Per-phase request timeout configuration (seconds)."""

    connect: float = 5.0
    read: float = 30.0
    write: float = 30.0
    pool: float = 5.0


@dataclass(frozen=True, slots=True)
class Limits:
    """Connection-pool limits."""

    max_connections: int = 100
    max_keepalive_connections: int = 20
    keepalive_expiry: float = 5.0


@dataclass(frozen=True, slots=True)
class ClientConfig:
    """Immutable client configuration bag."""

    base_url: str | None = None
    default_headers: Mapping[str, str] = field(default_factory=dict)
    default_query: Mapping[str, str] = field(default_factory=dict)
    timeout: Timeout = field(default_factory=Timeout)
    limits: Limits = field(default_factory=Limits)
    decoder: ResponseDecoder = field(default_factory=PydanticDecoder)
    middleware: tuple[Middleware, ...] = ()
```

Now update the test file to move the `PydanticDecoder` import to the top:

```python
"""Unit tests for httpware.config types."""

from dataclasses import FrozenInstanceError

import pytest

from httpware import ClientConfig, Limits, Timeout
from httpware.decoders.pydantic import PydanticDecoder
```

And drop the in-function import + noqa from `test_client_config_defaults`:

```python
def test_client_config_defaults() -> None:
    cfg = ClientConfig()
    assert cfg.base_url is None
    assert cfg.default_headers == {}
    assert cfg.default_query == {}
    assert cfg.timeout == Timeout()
    assert cfg.limits == Limits()
    assert isinstance(cfg.decoder, PydanticDecoder)
    assert cfg.middleware == ()
```

- [ ] **Step 3: Run all config tests to verify they pass**

Run: `uv run pytest tests/test_config.py -v`
Expected: all pass (existing 6 tests + the extended defaults test).

- [ ] **Step 4: Lint and ty**

Run: `uv run ruff check src/httpware/config.py tests/test_config.py`
Run: `uv run ty check src/httpware/config.py`
Expected: both clean.

- [ ] **Step 5: Commit**

```bash
git add src/httpware/config.py tests/test_config.py
git commit -m "$(cat <<'EOF'
feat(story-1.7): extend ClientConfig with decoder and middleware fields

Adds two new fields to ClientConfig:
- decoder: ResponseDecoder (default: PydanticDecoder())
- middleware: tuple[Middleware, ...] (default: ())

Both fields have defaults so existing construction paths are unchanged.
The PydanticDecoder default factory introduces a constructor-time
dependency from config.py on decoders/pydantic.py — acceptable since
pydantic is a hard dep.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `AsyncClient` construction and defaults

Build the smallest `AsyncClient` that satisfies construction defaults and `from_url`. No HTTP methods yet — those land in Task 3.

**Files:**
- Create: `src/httpware/client.py`
- Create: `tests/test_client_construction.py`

- [ ] **Step 1: Add the failing tests**

Create `tests/test_client_construction.py`:

```python
"""Unit tests for httpware.client.AsyncClient construction."""

import pytest

from httpware import AsyncClient, Limits, Timeout
from httpware.decoders.pydantic import PydanticDecoder
from httpware.middleware import Middleware
from httpware.request import Request
from httpware.response import Response
from httpware.transports.httpx2 import Httpx2Transport


class _FakeTransport:
    """Minimal Transport for construction tests; never actually called."""

    async def __call__(self, request: Request) -> Response:  # pragma: no cover - not used
        raise NotImplementedError

    def stream(  # pragma: no cover - not used
        self, request: Request
    ):
        raise NotImplementedError

    async def aclose(self) -> None:  # pragma: no cover - not used
        return None


def test_init_defaults_provide_transport_and_decoder() -> None:
    client = AsyncClient()
    assert isinstance(client._transport, Httpx2Transport)
    assert isinstance(client._config.decoder, PydanticDecoder)
    assert client._config.middleware == ()


def test_init_accepts_explicit_transport() -> None:
    transport = _FakeTransport()
    client = AsyncClient(transport=transport)
    assert client._transport is transport


def test_init_accepts_explicit_decoder() -> None:
    decoder = PydanticDecoder()
    client = AsyncClient(decoder=decoder)
    assert client._config.decoder is decoder


def test_init_accepts_middleware_sequence() -> None:
    class _M:
        async def __call__(self, request: Request, next):  # noqa: A002
            return await next(request)

    middleware: list[Middleware] = [_M()]
    client = AsyncClient(middleware=middleware)
    assert client._config.middleware == tuple(middleware)


def test_init_normalizes_float_timeout() -> None:
    client = AsyncClient(timeout=2.5)
    assert client._config.timeout == Timeout(connect=2.5, read=2.5, write=2.5, pool=2.5)


def test_init_keeps_timeout_instance() -> None:
    t = Timeout(connect=1.0, read=60.0, write=10.0, pool=2.0)
    client = AsyncClient(timeout=t)
    assert client._config.timeout is t


def test_init_normalizes_none_timeout() -> None:
    client = AsyncClient(timeout=None)
    assert client._config.timeout == Timeout()


def test_init_default_limits() -> None:
    client = AsyncClient()
    assert client._config.limits == Limits()


def test_from_url_classmethod_sets_base_url() -> None:
    client = AsyncClient.from_url("https://api.example.com/v1")
    assert client._config.base_url == "https://api.example.com/v1"


def test_init_owns_transport_by_default() -> None:
    client = AsyncClient()
    assert client._owns_transport is True


def test_construction_does_not_create_httpx2_client() -> None:
    """Construction is side-effect-free; the httpx2.AsyncClient is lazily created on first request."""
    client = AsyncClient()
    # Httpx2Transport stores `_client` lazily; until first call, _client is None.
    assert client._transport._client is None  # type: ignore[attr-defined]
```

The last test reaches into private state (`_client`) on `Httpx2Transport`. Use the `# ty: ignore[unresolved-attribute]` style if `ty` complains; the comment above matches the existing test patterns elsewhere.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_client_construction.py -v`
Expected: `ImportError: cannot import name 'AsyncClient' from 'httpware'`.

- [ ] **Step 3: Implement the minimal `AsyncClient`**

Create `src/httpware/client.py`:

```python
"""AsyncClient — the v0.1.0 public surface of httpware."""

import dataclasses
import json as _json
from collections.abc import Mapping, Sequence
from typing import Any, TypeVar, overload

from httpware._internal.chain import compose
from httpware.config import ClientConfig, Limits, Timeout
from httpware.decoders import ResponseDecoder
from httpware.decoders.pydantic import PydanticDecoder
from httpware.middleware import Middleware, Next
from httpware.request import Request
from httpware.response import Response
from httpware.transports import Transport
from httpware.transports.httpx2 import Httpx2Transport


T = TypeVar("T")

_UNSET: Any = object()


def _normalize_timeout(value: Timeout | float | None) -> Timeout:
    if value is None:
        return Timeout()
    if isinstance(value, Timeout):
        return value
    return Timeout(connect=value, read=value, write=value, pool=value)


def _build_body(
    json_value: Any | None, content: bytes | None
) -> tuple[bytes | None, str | None]:
    if json_value is not None and content is not None:
        raise TypeError("pass either `json` or `content`, not both")
    if json_value is not None:
        return _json.dumps(json_value).encode("utf-8"), "application/json"
    return content, None


class AsyncClient:
    """Async HTTP client with typed response decoding and middleware composition."""

    _config: ClientConfig
    _transport: Transport
    _dispatch: Next
    _owns_transport: bool

    def __init__(
        self,
        *,
        base_url: str | None = None,
        default_headers: Mapping[str, str] | None = None,
        default_query: Mapping[str, str] | None = None,
        timeout: Timeout | float | None = None,
        limits: Limits | None = None,
        transport: Transport | None = None,
        decoder: ResponseDecoder | None = None,
        middleware: Sequence[Middleware] | None = None,
    ) -> None:
        normalized_timeout = _normalize_timeout(timeout)
        resolved_limits = limits or Limits()
        resolved_transport: Transport = transport or Httpx2Transport(
            limits=resolved_limits, timeout=normalized_timeout
        )
        resolved_decoder = decoder or PydanticDecoder()
        resolved_middleware = tuple(middleware) if middleware is not None else ()

        self._config = ClientConfig(
            base_url=base_url,
            default_headers=dict(default_headers or {}),
            default_query=dict(default_query or {}),
            timeout=normalized_timeout,
            limits=resolved_limits,
            decoder=resolved_decoder,
            middleware=resolved_middleware,
        )
        self._transport = resolved_transport
        self._dispatch = compose(resolved_middleware, resolved_transport)
        self._owns_transport = True

    @classmethod
    def from_url(cls, base_url: str, **kwargs: Any) -> "AsyncClient":
        """Construct an AsyncClient with a base URL prefix."""
        return cls(base_url=base_url, **kwargs)
```

- [ ] **Step 4: Add `AsyncClient` to the package root exports**

Edit `src/httpware/__init__.py`. Find the existing `from httpware.transports.httpx2 import Httpx2Transport` line (or insert in alphabetic position). Add the import:

```python
from httpware.client import AsyncClient
```

In `__all__`, add `"AsyncClient"` to the list. The list is sorted by `RUF022` (ASCII order); the correct position is at the very start (`"A"` < `"S"` in ASCII, so before `"STATUS_TO_EXCEPTION"`). If unsure, add the entry anywhere and run `uv run ruff check --fix src/httpware/__init__.py` to let ruff sort it.

- [ ] **Step 5: Run construction tests**

Run: `uv run pytest tests/test_client_construction.py -v`
Expected: 11 passed.

- [ ] **Step 6: Lint and ty**

Run: `uv run ruff check src/httpware/client.py src/httpware/__init__.py tests/test_client_construction.py`
Run: `uv run ty check src/httpware/client.py src/httpware/__init__.py`
Expected: both clean.

- [ ] **Step 7: Commit**

```bash
git add src/httpware/client.py src/httpware/__init__.py tests/test_client_construction.py
git commit -m "$(cat <<'EOF'
feat(story-1.7): AsyncClient construction + from_url + defaults

Adds src/httpware/client.py with the AsyncClient skeleton:
- keyword-only __init__ resolving defaults for transport (Httpx2Transport),
  decoder (PydanticDecoder), middleware (()), timeout (Timeout()), and
  limits (Limits())
- _normalize_timeout helper for float→Timeout coercion
- _build_body helper for the upcoming HTTP method shortcuts
- _UNSET sentinel for the upcoming with_options method
- from_url classmethod factory
- middleware chain composed via compose() at construction; result stored
  in self._dispatch
- _owns_transport flag set to True (views from with_options will set False)

No HTTP methods yet (Task 3). Construction is side-effect-free —
Httpx2Transport's lazy init means no httpx2.AsyncClient() is created
until the first request.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: HTTP method shortcuts + URL resolution + request building

The biggest task. Implement `_resolve_url`, `_build_request`, `_send`, and all 8 HTTP methods with their `@overload` declarations. Test via a `_RecordingTransport` that captures the produced `Request`.

**Files:**
- Modify: `src/httpware/client.py` (append helpers + 8 methods)
- Create: `tests/test_client_methods.py`

- [ ] **Step 1: Add the first failing test (GET happy path)**

Create `tests/test_client_methods.py`:

```python
"""Unit tests for AsyncClient HTTP method shortcuts."""

from contextlib import AbstractAsyncContextManager
from typing import Any

import pytest

from httpware import AsyncClient
from httpware.request import Request
from httpware.response import Response, StreamResponse


class _RecordingTransport:
    """Captures the last-seen Request and returns a canned Response."""

    def __init__(self) -> None:
        self.last_request: Request | None = None
        self.canned = Response(
            status=200,
            headers={"x-from": "transport"},
            content=b"body",
            url="https://example.test/",
            elapsed=0.0,
        )

    async def __call__(self, request: Request) -> Response:
        self.last_request = request
        return self.canned

    def stream(  # pragma: no cover - not exercised
        self, request: Request
    ) -> AbstractAsyncContextManager[StreamResponse]:
        raise NotImplementedError

    async def aclose(self) -> None:  # pragma: no cover - not exercised
        return None


async def test_get_builds_request_with_method_and_url() -> None:
    transport = _RecordingTransport()
    client = AsyncClient(transport=transport)

    await client.get("https://api.example.com/users")

    assert transport.last_request is not None
    assert transport.last_request.method == "GET"
    assert transport.last_request.url == "https://api.example.com/users"
    assert transport.last_request.body is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_client_methods.py::test_get_builds_request_with_method_and_url -v`
Expected: `AttributeError: 'AsyncClient' object has no attribute 'get'`.

- [ ] **Step 3: Implement `_resolve_url`, `_build_request`, `_send`, and `get`**

Append to `src/httpware/client.py` (inside the `AsyncClient` class):

```python
    def _resolve_url(self, path: str) -> str:
        if path.startswith(("http://", "https://")):
            return path
        base = self._config.base_url
        if base is None:
            return path
        return f"{base.rstrip('/')}/{path.lstrip('/')}"

    def _build_request(
        self,
        method: str,
        path: str,
        *,
        headers: Mapping[str, str] | None,
        params: Mapping[str, str] | None,
        cookies: Mapping[str, str] | None,
        timeout: Timeout | float | None,
        body: bytes | None,
        content_type: str | None,
    ) -> Request:
        merged_headers: dict[str, str] = {**self._config.default_headers, **(headers or {})}
        if content_type is not None and "content-type" not in {k.lower() for k in merged_headers}:
            merged_headers["content-type"] = content_type
        merged_params: dict[str, str] = {**self._config.default_query, **(params or {})}
        extensions: dict[str, Any] = {}
        if timeout is not None:
            extensions["timeout"] = _normalize_timeout(timeout)
        return Request(
            method=method,
            url=self._resolve_url(path),
            headers=merged_headers,
            params=merged_params,
            cookies=dict(cookies or {}),
            body=body,
            extensions=extensions,
        )

    async def _send(
        self,
        method: str,
        path: str,
        *,
        headers: Mapping[str, str] | None,
        params: Mapping[str, str] | None,
        cookies: Mapping[str, str] | None,
        timeout: Timeout | float | None,
        body: bytes | None,
        content_type: str | None,
        response_model: type[T] | None,
    ) -> Response | T:
        request = self._build_request(
            method,
            path,
            headers=headers,
            params=params,
            cookies=cookies,
            timeout=timeout,
            body=body,
            content_type=content_type,
        )
        response = await self._dispatch(request)
        if response_model is None:
            return response
        return self._config.decoder.decode(response.content, response_model)

    @overload
    async def get(
        self,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, str] | None = None,
        cookies: Mapping[str, str] | None = None,
        timeout: Timeout | float | None = None,
        response_model: None = None,
    ) -> Response: ...

    @overload
    async def get(
        self,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, str] | None = None,
        cookies: Mapping[str, str] | None = None,
        timeout: Timeout | float | None = None,
        response_model: type[T],
    ) -> T: ...

    async def get(
        self,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, str] | None = None,
        cookies: Mapping[str, str] | None = None,
        timeout: Timeout | float | None = None,
        response_model: type[T] | None = None,
    ) -> Response | T:
        return await self._send(
            "GET",
            path,
            headers=headers,
            params=params,
            cookies=cookies,
            timeout=timeout,
            body=None,
            content_type=None,
            response_model=response_model,
        )
```

- [ ] **Step 4: Run the GET test to verify it passes**

Run: `uv run pytest tests/test_client_methods.py::test_get_builds_request_with_method_and_url -v`
Expected: PASS.

- [ ] **Step 5: Add tests for URL resolution and default merging**

Append to `tests/test_client_methods.py`:

```python
async def test_relative_path_joins_with_base_url() -> None:
    transport = _RecordingTransport()
    client = AsyncClient(base_url="https://api.example.com/v1", transport=transport)
    await client.get("/users")
    assert transport.last_request is not None
    assert transport.last_request.url == "https://api.example.com/v1/users"


async def test_relative_path_without_leading_slash_joins_same_way() -> None:
    transport = _RecordingTransport()
    client = AsyncClient(base_url="https://api.example.com/v1", transport=transport)
    await client.get("users")
    assert transport.last_request is not None
    assert transport.last_request.url == "https://api.example.com/v1/users"


async def test_absolute_url_bypasses_base_url() -> None:
    transport = _RecordingTransport()
    client = AsyncClient(base_url="https://api.example.com/v1", transport=transport)
    await client.get("https://other.com/foo")
    assert transport.last_request is not None
    assert transport.last_request.url == "https://other.com/foo"


async def test_default_headers_merged_with_per_call_headers() -> None:
    transport = _RecordingTransport()
    client = AsyncClient(
        default_headers={"x-keep": "1", "x-override": "default"},
        transport=transport,
    )
    await client.get("/", headers={"x-override": "per-call", "x-add": "2"})
    assert transport.last_request is not None
    assert transport.last_request.headers == {
        "x-keep": "1",
        "x-override": "per-call",
        "x-add": "2",
    }


async def test_default_query_merged_with_per_call_params() -> None:
    transport = _RecordingTransport()
    client = AsyncClient(default_query={"k": "default"}, transport=transport)
    await client.get("/", params={"k": "per-call", "extra": "1"})
    assert transport.last_request is not None
    assert transport.last_request.params == {"k": "per-call", "extra": "1"}
```

Run: `uv run pytest tests/test_client_methods.py -v`
Expected: all 6 tests pass.

- [ ] **Step 6: Add tests for `post` body params**

Append:

```python
async def test_post_with_json_serializes_and_sets_content_type() -> None:
    transport = _RecordingTransport()
    client = AsyncClient(transport=transport)
    await client.post("/users", json={"name": "alice"})
    assert transport.last_request is not None
    assert transport.last_request.method == "POST"
    assert transport.last_request.body == b'{"name": "alice"}'
    assert transport.last_request.headers["content-type"] == "application/json"


async def test_post_with_content_preserves_bytes_unchanged() -> None:
    transport = _RecordingTransport()
    client = AsyncClient(transport=transport)
    await client.post("/users", content=b"raw bytes")
    assert transport.last_request is not None
    assert transport.last_request.body == b"raw bytes"
    assert "content-type" not in transport.last_request.headers


async def test_post_json_and_content_raises_typeerror() -> None:
    transport = _RecordingTransport()
    client = AsyncClient(transport=transport)
    with pytest.raises(TypeError, match="`json` or `content`"):
        await client.post("/users", json={"a": 1}, content=b"raw")


async def test_post_per_call_content_type_skips_auto_injection() -> None:
    transport = _RecordingTransport()
    client = AsyncClient(transport=transport)
    await client.post(
        "/users",
        json={"a": 1},
        headers={"Content-Type": "application/vnd.custom+json"},
    )
    assert transport.last_request is not None
    # The user-supplied Content-Type wins; the auto-injection is skipped because the case-insensitive
    # check finds an existing entry.
    assert transport.last_request.headers["Content-Type"] == "application/vnd.custom+json"
```

Run: `uv run pytest tests/test_client_methods.py -v`
Expected: still some fail — `post` not implemented yet.

- [ ] **Step 7: Implement `post`**

Append to `src/httpware/client.py` (inside the `AsyncClient` class):

```python
    @overload
    async def post(
        self,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, str] | None = None,
        cookies: Mapping[str, str] | None = None,
        timeout: Timeout | float | None = None,
        json: Any | None = None,
        content: bytes | None = None,
        response_model: None = None,
    ) -> Response: ...

    @overload
    async def post(
        self,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, str] | None = None,
        cookies: Mapping[str, str] | None = None,
        timeout: Timeout | float | None = None,
        json: Any | None = None,
        content: bytes | None = None,
        response_model: type[T],
    ) -> T: ...

    async def post(
        self,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, str] | None = None,
        cookies: Mapping[str, str] | None = None,
        timeout: Timeout | float | None = None,
        json: Any | None = None,
        content: bytes | None = None,
        response_model: type[T] | None = None,
    ) -> Response | T:
        body, content_type = _build_body(json, content)
        return await self._send(
            "POST",
            path,
            headers=headers,
            params=params,
            cookies=cookies,
            timeout=timeout,
            body=body,
            content_type=content_type,
            response_model=response_model,
        )
```

Run: `uv run pytest tests/test_client_methods.py -v`
Expected: 10 passed.

- [ ] **Step 8: Implement the remaining 6 methods**

Append to `src/httpware/client.py`:

```python
    @overload
    async def put(
        self,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, str] | None = None,
        cookies: Mapping[str, str] | None = None,
        timeout: Timeout | float | None = None,
        json: Any | None = None,
        content: bytes | None = None,
        response_model: None = None,
    ) -> Response: ...

    @overload
    async def put(
        self,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, str] | None = None,
        cookies: Mapping[str, str] | None = None,
        timeout: Timeout | float | None = None,
        json: Any | None = None,
        content: bytes | None = None,
        response_model: type[T],
    ) -> T: ...

    async def put(
        self,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, str] | None = None,
        cookies: Mapping[str, str] | None = None,
        timeout: Timeout | float | None = None,
        json: Any | None = None,
        content: bytes | None = None,
        response_model: type[T] | None = None,
    ) -> Response | T:
        body, content_type = _build_body(json, content)
        return await self._send(
            "PUT",
            path,
            headers=headers,
            params=params,
            cookies=cookies,
            timeout=timeout,
            body=body,
            content_type=content_type,
            response_model=response_model,
        )

    @overload
    async def patch(
        self,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, str] | None = None,
        cookies: Mapping[str, str] | None = None,
        timeout: Timeout | float | None = None,
        json: Any | None = None,
        content: bytes | None = None,
        response_model: None = None,
    ) -> Response: ...

    @overload
    async def patch(
        self,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, str] | None = None,
        cookies: Mapping[str, str] | None = None,
        timeout: Timeout | float | None = None,
        json: Any | None = None,
        content: bytes | None = None,
        response_model: type[T],
    ) -> T: ...

    async def patch(
        self,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, str] | None = None,
        cookies: Mapping[str, str] | None = None,
        timeout: Timeout | float | None = None,
        json: Any | None = None,
        content: bytes | None = None,
        response_model: type[T] | None = None,
    ) -> Response | T:
        body, content_type = _build_body(json, content)
        return await self._send(
            "PATCH",
            path,
            headers=headers,
            params=params,
            cookies=cookies,
            timeout=timeout,
            body=body,
            content_type=content_type,
            response_model=response_model,
        )

    @overload
    async def delete(
        self,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, str] | None = None,
        cookies: Mapping[str, str] | None = None,
        timeout: Timeout | float | None = None,
        response_model: None = None,
    ) -> Response: ...

    @overload
    async def delete(
        self,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, str] | None = None,
        cookies: Mapping[str, str] | None = None,
        timeout: Timeout | float | None = None,
        response_model: type[T],
    ) -> T: ...

    async def delete(
        self,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, str] | None = None,
        cookies: Mapping[str, str] | None = None,
        timeout: Timeout | float | None = None,
        response_model: type[T] | None = None,
    ) -> Response | T:
        return await self._send(
            "DELETE",
            path,
            headers=headers,
            params=params,
            cookies=cookies,
            timeout=timeout,
            body=None,
            content_type=None,
            response_model=response_model,
        )

    @overload
    async def head(
        self,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, str] | None = None,
        cookies: Mapping[str, str] | None = None,
        timeout: Timeout | float | None = None,
        response_model: None = None,
    ) -> Response: ...

    @overload
    async def head(
        self,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, str] | None = None,
        cookies: Mapping[str, str] | None = None,
        timeout: Timeout | float | None = None,
        response_model: type[T],
    ) -> T: ...

    async def head(
        self,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, str] | None = None,
        cookies: Mapping[str, str] | None = None,
        timeout: Timeout | float | None = None,
        response_model: type[T] | None = None,
    ) -> Response | T:
        return await self._send(
            "HEAD",
            path,
            headers=headers,
            params=params,
            cookies=cookies,
            timeout=timeout,
            body=None,
            content_type=None,
            response_model=response_model,
        )

    @overload
    async def options(
        self,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, str] | None = None,
        cookies: Mapping[str, str] | None = None,
        timeout: Timeout | float | None = None,
        response_model: None = None,
    ) -> Response: ...

    @overload
    async def options(
        self,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, str] | None = None,
        cookies: Mapping[str, str] | None = None,
        timeout: Timeout | float | None = None,
        response_model: type[T],
    ) -> T: ...

    async def options(
        self,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, str] | None = None,
        cookies: Mapping[str, str] | None = None,
        timeout: Timeout | float | None = None,
        response_model: type[T] | None = None,
    ) -> Response | T:
        return await self._send(
            "OPTIONS",
            path,
            headers=headers,
            params=params,
            cookies=cookies,
            timeout=timeout,
            body=None,
            content_type=None,
            response_model=response_model,
        )

    @overload
    async def request(
        self,
        method: str,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, str] | None = None,
        cookies: Mapping[str, str] | None = None,
        timeout: Timeout | float | None = None,
        json: Any | None = None,
        content: bytes | None = None,
        response_model: None = None,
    ) -> Response: ...

    @overload
    async def request(
        self,
        method: str,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, str] | None = None,
        cookies: Mapping[str, str] | None = None,
        timeout: Timeout | float | None = None,
        json: Any | None = None,
        content: bytes | None = None,
        response_model: type[T],
    ) -> T: ...

    async def request(
        self,
        method: str,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, str] | None = None,
        cookies: Mapping[str, str] | None = None,
        timeout: Timeout | float | None = None,
        json: Any | None = None,
        content: bytes | None = None,
        response_model: type[T] | None = None,
    ) -> Response | T:
        body, content_type = _build_body(json, content)
        return await self._send(
            method,
            path,
            headers=headers,
            params=params,
            cookies=cookies,
            timeout=timeout,
            body=body,
            content_type=content_type,
            response_model=response_model,
        )
```

- [ ] **Step 9: Add tests for the remaining methods (one per method, verifying the wire method string)**

Append to `tests/test_client_methods.py`:

```python
@pytest.mark.parametrize(
    ("client_method_name", "expected_wire_method"),
    [
        ("get", "GET"),
        ("post", "POST"),
        ("put", "PUT"),
        ("patch", "PATCH"),
        ("delete", "DELETE"),
        ("head", "HEAD"),
        ("options", "OPTIONS"),
    ],
)
async def test_each_method_emits_correct_wire_method(
    client_method_name: str, expected_wire_method: str
) -> None:
    transport = _RecordingTransport()
    client = AsyncClient(transport=transport)
    method = getattr(client, client_method_name)
    await method("/foo")
    assert transport.last_request is not None
    assert transport.last_request.method == expected_wire_method


async def test_request_method_uses_first_positional_method_arg() -> None:
    transport = _RecordingTransport()
    client = AsyncClient(transport=transport)
    await client.request("CUSTOM", "/foo")
    assert transport.last_request is not None
    assert transport.last_request.method == "CUSTOM"
```

Run: `uv run pytest tests/test_client_methods.py -v`
Expected: 18 passed (10 + 7 parametrized + 1 `request`).

- [ ] **Step 10: Lint and ty**

Run: `uv run ruff check src/httpware/client.py tests/test_client_methods.py`
Run: `uv run ty check src/httpware/client.py`
Expected: both clean.

If `ty` flags any overload as ambiguous, the most common fix is to ensure each overload's `response_model` parameter has a distinct annotation (`None` literal vs `type[T]`). The pattern used here matches httpx's own stubs.

- [ ] **Step 11: Commit**

```bash
git add src/httpware/client.py tests/test_client_methods.py
git commit -m "$(cat <<'EOF'
feat(story-1.7): HTTP method shortcuts on AsyncClient (8 methods)

Adds the eight public HTTP method shortcuts plus the helpers they share:
- _resolve_url for httpx-style base_url prefix join
- _build_request for default+per-call header/param merging
- _send for the dispatch + optional decode wiring
- 8 methods × 2 @overload declarations each (None vs type[T] for the
  response_model parameter) — total 16 overload stubs
- get/head/options/delete take no body params; post/put/patch add json
  and content (mutually exclusive — TypeError if both)
- request takes a leading positional method parameter

18 tests cover: URL resolution (relative, absolute, no base_url), default
merging (headers, params), body resolution (json→serialized,
content→passthrough, both→TypeError), per-call Content-Type override,
and one parametrized test per method confirming the wire-method string.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: `response_model` decoding

Verify the decoder is invoked when `response_model` is provided and bypassed when it's `None`.

**Files:**
- Create: `tests/test_client_response_model.py`

- [ ] **Step 1: Add the tests**

Create `tests/test_client_response_model.py`:

```python
"""Unit tests for AsyncClient response_model integration with ResponseDecoder."""

from contextlib import AbstractAsyncContextManager
from typing import Any, TypeVar

from pydantic import BaseModel

from httpware import AsyncClient
from httpware.request import Request
from httpware.response import Response, StreamResponse


T = TypeVar("T")


class _RecordingTransport:
    def __init__(self, content: bytes) -> None:
        self._content = content

    async def __call__(self, request: Request) -> Response:
        return Response(
            status=200,
            headers={},
            content=self._content,
            url=request.url,
            elapsed=0.0,
        )

    def stream(  # pragma: no cover
        self, request: Request
    ) -> AbstractAsyncContextManager[StreamResponse]:
        raise NotImplementedError

    async def aclose(self) -> None:  # pragma: no cover
        return None


class _Item(BaseModel):
    name: str
    qty: int


async def test_response_model_none_returns_raw_response() -> None:
    transport = _RecordingTransport(content=b'{"name":"x","qty":1}')
    client = AsyncClient(transport=transport)
    result = await client.get("/foo")
    assert isinstance(result, Response)
    assert result.content == b'{"name":"x","qty":1}'


async def test_response_model_invokes_decoder() -> None:
    transport = _RecordingTransport(content=b'{"name":"x","qty":1}')
    client = AsyncClient(transport=transport)
    result = await client.get("/foo", response_model=_Item)
    assert isinstance(result, _Item)
    assert result == _Item(name="x", qty=1)


async def test_response_model_uses_supplied_decoder() -> None:
    transport = _RecordingTransport(content=b'{"name":"x","qty":1}')
    seen: list[tuple[bytes, type[Any]]] = []

    class _SpyDecoder:
        def decode(self, content: bytes, model: type[T]) -> T:
            seen.append((content, model))
            return model(name="spy", qty=999)  # type: ignore[call-arg]

    client = AsyncClient(transport=transport, decoder=_SpyDecoder())
    result = await client.get("/foo", response_model=_Item)
    assert seen == [(b'{"name":"x","qty":1}', _Item)]
    assert isinstance(result, _Item)
    assert result.name == "spy"
```

- [ ] **Step 2: Run tests**

Run: `uv run pytest tests/test_client_response_model.py -v`
Expected: 3 passed. (The plumbing was already implemented in Task 3's `_send` helper; these tests just verify the contract.)

- [ ] **Step 3: Lint**

Run: `uv run ruff check tests/test_client_response_model.py`
Expected: clean.

If ruff flags the `# type: ignore[call-arg]` on `model(name=..., qty=...)`, replace with `# ty: ignore[unknown-argument]` per the project's convention.

- [ ] **Step 4: Commit**

```bash
git add tests/test_client_response_model.py
git commit -m "$(cat <<'EOF'
test(story-1.7): response_model decoder invocation contract

Three tests verify the decoder wiring established in Task 3:
- response_model=None returns the raw Response (no decoder call)
- response_model=Foo invokes the configured decoder and returns Foo
- a user-supplied decoder= overrides the default PydanticDecoder

No production code changes; the plumbing was implemented as part of the
HTTP method shortcuts.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Typed overload validation via `ty`

Add a `ty`-checked file that fails compilation if the overload return types are wrong.

**Files:**
- Create: `tests/test_client_typing.py`

- [ ] **Step 1: Create the typed test file**

Create `tests/test_client_typing.py`:

```python
"""Type-checked verification that AsyncClient.{get,post,...} overloads narrow correctly.

This file is checked by `ty` as part of `just lint-ci`. If the @overload
declarations are wrong, the typed assignments below fail to type-check.

The runtime test below just ensures the module imports cleanly so coverage
notices the file.
"""

from pydantic import BaseModel

from httpware import AsyncClient, Response


class _Item(BaseModel):
    name: str


async def _check_overload_types(client: AsyncClient) -> None:
    # No response_model → Response
    resp: Response = await client.get("/foo")
    assert resp is not None

    # response_model=type[T] → T
    item: _Item = await client.get("/foo", response_model=_Item)
    assert item is not None

    # POST: same pattern
    resp_post: Response = await client.post("/foo", json={"a": 1})
    item_post: _Item = await client.post("/foo", json={"a": 1}, response_model=_Item)
    assert resp_post is not None
    assert item_post is not None

    # request(method, path, ...) shape
    resp_req: Response = await client.request("PURGE", "/foo")
    item_req: _Item = await client.request("PURGE", "/foo", response_model=_Item)
    assert resp_req is not None
    assert item_req is not None


def test_typing_module_imports_cleanly() -> None:
    """Runtime stub so coverage notices this file is reachable; ty does the real work."""
    assert AsyncClient is not None
```

- [ ] **Step 2: Run the typing module via ty**

Run: `uv run ty check tests/test_client_typing.py`
Expected: clean. If any assignment fails type-check, the corresponding overload is wrong.

- [ ] **Step 3: Run the runtime test**

Run: `uv run pytest tests/test_client_typing.py -v`
Expected: 1 passed.

- [ ] **Step 4: Lint**

Run: `uv run ruff check tests/test_client_typing.py`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add tests/test_client_typing.py
git commit -m "$(cat <<'EOF'
test(story-1.7): ty-validated overload type narrowing for HTTP methods

Adds tests/test_client_typing.py with typed assignments that exercise
each overload variant on get, post, and request. Wrong @overload
declarations would cause ty to reject the assignments. Runs as part of
`just lint-ci`'s ty check pass.

Includes a one-line runtime test so coverage sees the file is reachable.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Lifecycle (`__aenter__` and `__aexit__`)

Add the async context manager support plus tests.

**Files:**
- Modify: `src/httpware/client.py` (append two methods)
- Create: `tests/test_client_lifecycle.py`

- [ ] **Step 1: Add the failing tests**

Create `tests/test_client_lifecycle.py`:

```python
"""Unit tests for AsyncClient lifecycle (__aenter__, __aexit__)."""

from contextlib import AbstractAsyncContextManager

from httpware import AsyncClient
from httpware.request import Request
from httpware.response import Response, StreamResponse


class _TrackingTransport:
    """Counts aclose() invocations."""

    def __init__(self) -> None:
        self.aclose_calls = 0

    async def __call__(self, request: Request) -> Response:  # pragma: no cover - not used
        raise NotImplementedError

    def stream(  # pragma: no cover - not used
        self, request: Request
    ) -> AbstractAsyncContextManager[StreamResponse]:
        raise NotImplementedError

    async def aclose(self) -> None:
        self.aclose_calls += 1


async def test_aenter_returns_self() -> None:
    transport = _TrackingTransport()
    client = AsyncClient(transport=transport)
    async with client as entered:
        assert entered is client


async def test_async_with_calls_aclose_on_exit() -> None:
    transport = _TrackingTransport()
    client = AsyncClient(transport=transport)
    async with client:
        pass
    assert transport.aclose_calls == 1


async def test_double_close_is_safe() -> None:
    transport = _TrackingTransport()
    client = AsyncClient(transport=transport)
    async with client:
        pass
    async with client:
        pass
    assert transport.aclose_calls == 2  # noqa: PLR2004


async def test_view_async_with_does_not_close_transport() -> None:
    transport = _TrackingTransport()
    client = AsyncClient(transport=transport)
    view = client.with_options(timeout=10)
    async with view:
        pass
    assert transport.aclose_calls == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_client_lifecycle.py -v`
Expected: `AttributeError: 'AsyncClient' object has no attribute '__aenter__'` (or `with_options` for the last one).

- [ ] **Step 3: Implement `__aenter__` and `__aexit__`**

Append to `src/httpware/client.py` (inside the `AsyncClient` class):

```python
    async def __aenter__(self) -> "AsyncClient":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object | None,
    ) -> None:
        if self._owns_transport:
            await self._transport.aclose()
```

- [ ] **Step 4: Run the first three tests (the `with_options` test stays failing)**

Run: `uv run pytest tests/test_client_lifecycle.py -k "not view" -v`
Expected: 3 passed (`test_aenter_returns_self`, `test_async_with_calls_aclose_on_exit`, `test_double_close_is_safe`).

The `view` test stays red until Task 7.

- [ ] **Step 5: Lint and ty**

Run: `uv run ruff check src/httpware/client.py tests/test_client_lifecycle.py`
Run: `uv run ty check src/httpware/client.py`
Expected: both clean.

- [ ] **Step 6: Commit**

```bash
git add src/httpware/client.py tests/test_client_lifecycle.py
git commit -m "$(cat <<'EOF'
feat(story-1.7): async context manager lifecycle for AsyncClient

Adds __aenter__ (returns self) and __aexit__ (calls transport.aclose()
if self._owns_transport). Three tests pass: aenter returns self, the
context manager closes the transport on exit, and double-close is safe
(Httpx2Transport.aclose is idempotent).

The view test (test_view_async_with_does_not_close_transport) stays
failing until Task 7 implements with_options.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: `with_options` and views

Implement `with_options` and the `_from_view` helper that constructs a view (non-owning) client.

**Files:**
- Modify: `src/httpware/client.py` (append two methods)
- Create: `tests/test_client_middleware_wiring.py`

- [ ] **Step 1: Add the failing middleware-wiring tests**

Create `tests/test_client_middleware_wiring.py`:

```python
"""Unit tests for AsyncClient middleware wiring through compose() and with_options."""

from contextlib import AbstractAsyncContextManager

from httpware import AsyncClient
from httpware.middleware import Middleware, Next
from httpware.request import Request
from httpware.response import Response, StreamResponse


class _RecordingTransport:
    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self, request: Request) -> Response:
        self.calls += 1
        return Response(
            status=200,
            headers={},
            content=b"",
            url=request.url,
            elapsed=0.0,
        )

    def stream(  # pragma: no cover
        self, request: Request
    ) -> AbstractAsyncContextManager[StreamResponse]:
        raise NotImplementedError

    async def aclose(self) -> None:  # pragma: no cover
        return None


def _make_recording_middleware(label: str, log: list[str]) -> Middleware:
    class _M:
        async def __call__(self, request: Request, next: Next) -> Response:  # noqa: A002
            log.append(label)
            return await next(request)

    return _M()


async def test_middleware_runs_per_request() -> None:
    transport = _RecordingTransport()
    log: list[str] = []
    client = AsyncClient(
        transport=transport,
        middleware=[_make_recording_middleware("A", log)],
    )
    await client.get("/foo")
    assert log == ["A"]
    assert transport.calls == 1


async def test_with_options_recomposes_middleware() -> None:
    transport = _RecordingTransport()
    parent_log: list[str] = []
    view_log: list[str] = []
    client = AsyncClient(
        transport=transport,
        middleware=[_make_recording_middleware("parent", parent_log)],
    )
    view = client.with_options(
        middleware=[_make_recording_middleware("view", view_log)],
    )
    await view.get("/foo")
    assert view_log == ["view"]
    assert parent_log == []  # parent's middleware does NOT run for view calls


async def test_with_options_inherits_middleware_when_unset() -> None:
    transport = _RecordingTransport()
    log: list[str] = []
    client = AsyncClient(
        transport=transport,
        middleware=[_make_recording_middleware("inherited", log)],
    )
    view = client.with_options(timeout=10)
    await view.get("/foo")
    assert log == ["inherited"]


async def test_view_shares_transport_with_parent() -> None:
    transport = _RecordingTransport()
    client = AsyncClient(transport=transport)
    view = client.with_options(timeout=10)
    assert view._transport is client._transport


async def test_view_does_not_own_transport() -> None:
    client = AsyncClient()
    view = client.with_options(timeout=10)
    assert view._owns_transport is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_client_middleware_wiring.py -v`
Expected: middleware-only test passes (Task 3 already wired `compose()`); `with_options` tests fail with `AttributeError`.

- [ ] **Step 3: Implement `with_options` and `_from_view`**

Append to `src/httpware/client.py` (inside the `AsyncClient` class):

```python
    def with_options(
        self,
        *,
        base_url: str | None = _UNSET,
        default_headers: Mapping[str, str] | None = _UNSET,
        default_query: Mapping[str, str] | None = _UNSET,
        timeout: Timeout | float | None = _UNSET,
        decoder: ResponseDecoder | None = _UNSET,
        middleware: Sequence[Middleware] | None = _UNSET,
    ) -> "AsyncClient":
        """Return a new AsyncClient sharing the same transport with overridden config.

        The returned client is a "view": it does NOT own the transport lifecycle.
        Closing it via `async with` is a no-op. The original client should be the
        one inside the outermost `async with` block.

        `limits` and `transport` are NOT overridable here — both bind to the
        transport, which is shared. Construct a fresh AsyncClient for those.
        """
        changes: dict[str, Any] = {}
        if base_url is not _UNSET:
            changes["base_url"] = base_url
        if default_headers is not _UNSET:
            changes["default_headers"] = dict(default_headers or {})
        if default_query is not _UNSET:
            changes["default_query"] = dict(default_query or {})
        if timeout is not _UNSET:
            changes["timeout"] = _normalize_timeout(timeout)
        if decoder is not _UNSET:
            changes["decoder"] = decoder or PydanticDecoder()
        if middleware is not _UNSET:
            changes["middleware"] = tuple(middleware) if middleware is not None else ()

        new_config = dataclasses.replace(self._config, **changes)
        return AsyncClient._from_view(new_config, self._transport)

    @classmethod
    def _from_view(cls, config: ClientConfig, transport: Transport) -> "AsyncClient":
        """Construct a view sharing an existing transport. Bypasses __init__."""
        client = cls.__new__(cls)
        client._config = config
        client._transport = transport
        client._dispatch = compose(config.middleware, transport)
        client._owns_transport = False
        return client
```

- [ ] **Step 4: Run all middleware-wiring and lifecycle tests**

Run: `uv run pytest tests/test_client_middleware_wiring.py tests/test_client_lifecycle.py -v`
Expected: 5 middleware-wiring tests + 4 lifecycle tests = 9 passed.

- [ ] **Step 5: Lint and ty**

Run: `uv run ruff check src/httpware/client.py tests/test_client_middleware_wiring.py`
Run: `uv run ty check src/httpware/client.py`
Expected: both clean.

- [ ] **Step 6: Commit**

```bash
git add src/httpware/client.py tests/test_client_middleware_wiring.py
git commit -m "$(cat <<'EOF'
feat(story-1.7): with_options + view-client lifecycle for AsyncClient

Adds with_options(...) returning a new AsyncClient sharing the same
transport with selected config overrides. Uses an _UNSET sentinel so
None is a valid override value distinct from "not specified".

Adds _from_view classmethod that bypasses __init__ to construct a view
client (sets _owns_transport=False so __aexit__ is a no-op). The view's
middleware chain is re-composed against the shared transport.

with_options allowlist: base_url, default_headers, default_query, timeout,
decoder, middleware. limits and transport are intentionally NOT overridable
(both bind to the transport, which is shared).

Five new wiring tests cover: middleware execution per request, view re-
composes with new middleware, view inherits parent middleware when unset,
view shares the transport reference, view _owns_transport is False. The
previously-failing lifecycle test (view __aexit__ no-op) now passes.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: CHANGELOG bullet

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Append the bullet**

Edit `CHANGELOG.md`. The `## [Unreleased]` / `### Added` section currently ends with the Story 1.6 bullet. Append a new bullet immediately after it (still before the `[Unreleased]: ...` reference link at the bottom):

```markdown
- `AsyncClient` — the v0.1.0 public surface. Construct with keyword-only `base_url`, `default_headers`, `default_query`, `timeout` (accepts `Timeout` instance, float seconds, or `None`), `limits`, `transport` (defaults to `Httpx2Transport`), `decoder` (defaults to `PydanticDecoder`), and `middleware` (`Sequence[Middleware]`, composed via `httpware._internal.chain.compose` at construction). Eight HTTP method shortcuts (`get`, `post`, `put`, `patch`, `delete`, `head`, `options`, `request`) with `@overload`-based `response_model` typing — passing `response_model=type[T]` returns `T`, otherwise `Response`. Per-call overrides for `headers`, `params`, `cookies`, `timeout`; body params `json` (auto-encoded with `Content-Type: application/json`) and `content` (raw bytes; mutually exclusive). `base_url` joins with the path using an httpx-style prefix; absolute URLs (`http(s)://`) bypass. `from_url(base_url, **kwargs)` classmethod factory. Async context-manager lifecycle: the original client owns the transport and closes it on `__aexit__`; views returned by `with_options(**overrides)` share the transport and are no-ops on close. `with_options` accepts a keyword allowlist (`base_url`, `default_headers`, `default_query`, `timeout`, `decoder`, `middleware`); `limits` and `transport` are not overridable. Out of scope and deferred: `auth=` (Story 2.4), `data=`/`files=` body params, transport reference-counting, streaming (Epic 4), observability (Epic 5) (Story 1.7).
```

- [ ] **Step 2: Commit**

```bash
git add CHANGELOG.md
git commit -m "$(cat <<'EOF'
docs(story-1.7): CHANGELOG entry for AsyncClient

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Verify, push, PR, merge

End-to-end sanity check, push, open PR, wait for CI, merge.

- [ ] **Step 1: Run the full test suite with coverage**

Run: `just test`
Expected: ~246 passed (208 baseline post-1.6 + ~38 new), 1 deselected (perf), 100% line coverage including `src/httpware/client.py` and the extended `ClientConfig`.

If coverage is below 100% on `client.py`, identify the uncovered branch. Common culprits: an overload body (which should not be executed — `@overload` stubs are excluded by coverage's standard pragmas), the `_UNSET` defaults inside `with_options` (covered by the `inherits when unset` test), or `_from_view` (covered by the view-shares-transport test).

- [ ] **Step 2: Run full lint and type checks**

Run: `just lint-ci`
Expected: `eof-fixer`, `ruff format --check`, `ruff check --no-fix`, `ty check` all clean.

- [ ] **Step 3: Confirm the working tree is clean**

Run: `git status --short`
Expected: only the untracked plan file `docs/superpowers/plans/2026-05-31-asyncclient-plan.md`.

- [ ] **Step 4: Review the branch diff**

Run: `git log --oneline main..HEAD`
Expected: nine or ten commits — spec, Task 1, Task 2, Task 3, Task 4, Task 5, Task 6, Task 7, Task 8.

Run: `git diff --stat main..HEAD`
Expected: changes to `CHANGELOG.md`, `src/httpware/__init__.py`, `src/httpware/config.py`, `src/httpware/client.py` (new), `tests/test_config.py`, plus six new test files under `tests/test_client_*.py`, plus the spec and plan docs.

- [ ] **Step 5: Stage and commit the plan file**

```bash
git add docs/superpowers/plans/2026-05-31-asyncclient-plan.md
git commit -m "docs(story-1.7): implementation plan for AsyncClient

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 6: Push the branch**

Run: `git push -u origin story/1-7-asyncclient`
Expected: push succeeds; GitHub prints a "Create a pull request for ..." URL.

- [ ] **Step 7: Open the PR**

```bash
gh pr create --title "feat(story-1.7): AsyncClient — the v0.1.0 public surface" --body "$(cat <<'EOF'
## Summary

- Adds `src/httpware/client.py` with `AsyncClient`, the central public class. Eight HTTP method shortcuts (`get`, `post`, `put`, `patch`, `delete`, `head`, `options`, `request`) with typed `response_model` overloads validated by `ty`. Body params: `json` (auto-encoded) and `content` (raw bytes); mutually exclusive. Per-call overrides: `headers`, `params`, `cookies`, `timeout`.
- httpx-style prefix join for `base_url` + path; absolute URLs bypass.
- Middleware composition via `compose()` at construction (Story 2-1). The composed chain is stored as `self._dispatch`.
- Lifecycle: original AsyncClient owns the transport and closes it on `__aexit__`. Views from `with_options(...)` share the transport and are no-ops on close. Simpler than the archived Decision-9 ref-counting model; ref-counting can be added later without breaking the public API.
- `from_url(base_url, **kwargs)` classmethod factory.
- `ClientConfig` extended with `decoder` and `middleware` fields (backwards-compatible — both have defaults).
- ~38 new tests across six test files; 100% line coverage on `client.py`.

**Out of scope and deferred:** `auth=` (Story 2-4), `data=`/`files=` body params, transport reference-counting, streaming (Epic 4), observability (Epic 5).

Spec + plan: `docs/superpowers/specs/2026-05-31-asyncclient-design.md`, `docs/superpowers/plans/2026-05-31-asyncclient-plan.md`.

## Test plan

- [x] `just test` — ~246 passed, 1 deselected, 100% line coverage on the new and extended source files.
- [x] `just lint-ci` clean (`eof-fixer`, `ruff format --check`, `ruff check --no-fix`, `ty check`).
- [x] `tests/test_no_httpx2_leakage.py` still passes — no `httpx2` import in `client.py`.
- [x] `tests/test_optional_extras_isolation.py` still passes.
- [x] `tests/test_client_typing.py` — `ty` validates the typed overload narrowing across `get`, `post`, and `request`.
- [ ] CI green on all matrix entries (3.11/3.12/3.13/3.14 + lint).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 8: Wait for CI**

Run: `gh pr checks <PR_NUMBER>`
Expected: all five jobs green (`lint`, `pytest (3.11)`, `pytest (3.12)`, `pytest (3.13)`, `pytest (3.14)`).

If `pytest (3.14)` fails on `codecov/codecov-action@v4.0.1` with EPIPE (transient pattern seen on this repo), re-run with `gh run rerun <RUN_ID> --failed`.

- [ ] **Step 9: Merge**

Once CI is green:

Run: `gh pr merge <PR_NUMBER> --merge --delete-branch`
Run: `git checkout main && git pull --ff-only && git log --oneline -3`

Story 1-7 is complete. Story 1-8 (`RecordedTransport` for testing) closes out Epic 1.

---

## Definition of done

- `src/httpware/config.py` extends `ClientConfig` with `decoder` (default `PydanticDecoder()`) and `middleware` (default `()`) fields.
- `src/httpware/client.py` exists with `AsyncClient`, `_normalize_timeout`, `_build_body`, `_UNSET`, and `_from_view`.
- `src/httpware/__init__.py` exports `AsyncClient` at the package root and adds it to `__all__` in alphabetic position.
- All six test files exist with the test list from the spec; ~38 tests; all pass.
- `tests/test_client_typing.py` includes the `ty`-checked overload-validation file with at least one runtime test.
- `just test` shows the expected increment and 100% line coverage on `client.py` and the new `ClientConfig` fields.
- `just lint-ci` clean.
- `tests/test_no_httpx2_leakage.py` still passes — no `httpx2` import in `client.py`.
- `tests/test_optional_extras_isolation.py` still passes.
- CHANGELOG bullet under `[Unreleased]` / `### Added` describes the public surface plus the out-of-scope items.
- Story 1-7 lands as a single PR off `main` via the branch `story/1-7-asyncclient`.

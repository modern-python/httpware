---
status: shipped
date: 2026-06-01
slug: auth-coercion
spec: auth-coercion
pr: 16
---

# Auth coercion as middleware Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship Story 2-4: add an `auth=` parameter to `AsyncClient.__init__` and `with_options` that coerces `str | Callable[[], str | Awaitable[str]] | Middleware | None` into a `Middleware` (or `None`), with auto-injection at the inner-most user-controllable position in the chain.

**Architecture:** New private module `src/httpware/_internal/auth.py` (~70 lines) holds the coercion logic and bearer-middleware factories built atop `@before_request` (Story 2-2). `AsyncClient` tracks the user-supplied middleware list and the raw auth value separately so `with_options(...)` can recompose without losing either. `AuthValue` is the only new public name.

**Tech Stack:** Python 3.11 floor. `inspect.signature` for the callable-vs-Middleware dispatch. `inspect.isawaitable` for sync-vs-async token providers. No new dependencies.

**Branch:** `story/2-4-auth-coercion` (already created; spec commit `5906d22` is on it).

**Spec:** `planning/specs/2026-06-01-auth-coercion-design.md`.

---

## File Structure

**New files:**
- `src/httpware/_internal/auth.py` — `AuthValue` alias, `_normalize_auth`, `_bearer`, `_bearer_from_provider`, `_has_authorization`.
- `tests/test_internal_auth.py` — 10 unit tests for `_normalize_auth` in isolation.

**Modified files:**
- `src/httpware/client.py` — `__init__` gains `auth: AuthValue = None`; new private attrs `_user_middleware` and `_auth`; auth middleware appended at the END of the composed list. `with_options` accepts `auth=` and recomposes. `_from_view` accepts `user_middleware=` and `auth=` kwargs.
- `src/httpware/__init__.py` — re-export `AuthValue`; add to `__all__`.
- `tests/test_client_construction.py` — 3 tests for the new param.
- `tests/test_client_methods.py` — 3 tests for end-to-end Authorization header injection.
- `tests/test_client_middleware_wiring.py` — 3 tests for composition ordering and `with_options(auth=...)`.

**Files NOT touched:**
- `pyproject.toml`, `Justfile`, `.github/workflows/`.
- `src/httpware/middleware/__init__.py` (`@before_request`, `Middleware`, `Next` are reused, not modified).
- `src/httpware/config.py` (`ClientConfig.middleware` already holds `tuple[Middleware, ...]`).
- `src/httpware/transports/*`, `src/httpware/decoders/*`, `src/httpware/errors.py`, `src/httpware/request.py`, `src/httpware/response.py`.

---

## Task 1: `_internal/auth.py` module with 10 unit tests

TDD cycle for the core coercion logic. Start with one happy-path test, implement the whole module, then add the remaining 9 tests.

**Files:**
- Create: `src/httpware/_internal/auth.py`
- Create: `tests/test_internal_auth.py`

- [ ] **Step 1: Add the first failing test (None returns None)**

Create `tests/test_internal_auth.py`:

```python
"""Unit tests for httpware._internal.auth._normalize_auth."""

import pytest

from httpware._internal.auth import _normalize_auth
from httpware.middleware import Middleware, Next
from httpware.request import Request
from httpware.response import Response


def _make_request(headers: dict[str, str] | None = None) -> Request:
    return Request(method="GET", url="/foo", headers=headers or {})


def _ok_response() -> Response:
    return Response(status=200, headers={}, content=b"", url="/foo", elapsed=0.0)


async def _identity_next(request: Request) -> Response:
    return _ok_response()


def test_none_returns_none() -> None:
    assert _normalize_auth(None) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_internal_auth.py::test_none_returns_none -v`
Expected: `ModuleNotFoundError: No module named 'httpware._internal.auth'`.

- [ ] **Step 3: Implement `src/httpware/_internal/auth.py`**

Create `src/httpware/_internal/auth.py`:

```python
"""Normalize the `auth=` value of AsyncClient into a Middleware (or None)."""

import inspect
from collections.abc import Awaitable, Callable
from typing import TypeAlias

from httpware.middleware import Middleware, before_request
from httpware.request import Request


AuthValue: TypeAlias = (
    str
    | Callable[[], str | Awaitable[str]]
    | Middleware
    | None
)


def _normalize_auth(value: AuthValue) -> Middleware | None:
    """Coerce an `auth=` value into a Middleware.

    - `None` → returns `None` (no auth middleware injected).
    - `str` → returns a middleware that sets `Authorization: Bearer <str>`
      on every request (skipping if Authorization is already present).
    - `Callable[[], str | Awaitable[str]]` (zero-arg) → returns a middleware
      that calls the provider per request (awaiting if it returns an
      awaitable) and sets `Authorization: Bearer <result>` (skip-if-present).
    - `Middleware` (two-arg `__call__(request, next)`) → returned unchanged.
    - Any other callable shape → raises `TypeError` naming `auth=`.
    """
    if value is None:
        return None
    if isinstance(value, str):
        return _bearer(value)
    if not callable(value):
        msg = (
            "`auth=` must be a string, zero-arg callable, Middleware, or None; "
            f"got {type(value).__name__}"
        )
        raise TypeError(msg)
    n_params = len(inspect.signature(value).parameters)
    if n_params == 0:
        return _bearer_from_provider(value)
    if n_params == 2:
        return value
    msg = (
        "`auth=` callable must take 0 args (token provider) or 2 args "
        f"(Middleware); got {n_params}"
    )
    raise TypeError(msg)


def _bearer(token: str) -> Middleware:
    """Middleware that sets `Authorization: Bearer <token>` (skip-if-present)."""

    @before_request
    async def _add_static_bearer(request: Request) -> Request:
        if _has_authorization(request):
            return request
        return request.with_header("Authorization", f"Bearer {token}")

    return _add_static_bearer


def _bearer_from_provider(
    provider: Callable[[], str | Awaitable[str]],
) -> Middleware:
    """Middleware that calls `provider()` per request and sets the header."""

    @before_request
    async def _add_dynamic_bearer(request: Request) -> Request:
        if _has_authorization(request):
            return request
        token = provider()
        if inspect.isawaitable(token):
            token = await token
        return request.with_header("Authorization", f"Bearer {token}")

    return _add_dynamic_bearer


def _has_authorization(request: Request) -> bool:
    """Case-insensitive check for an existing Authorization header."""
    return any(k.lower() == "authorization" for k in request.headers)
```

No `__all__` (project convention).

- [ ] **Step 4: Run the first test to verify it passes**

Run: `uv run pytest tests/test_internal_auth.py::test_none_returns_none -v`
Expected: PASS.

- [ ] **Step 5: Add the string-bearer happy-path tests**

Append to `tests/test_internal_auth.py`:

```python
async def test_string_returns_bearer_middleware() -> None:
    mw = _normalize_auth("token")
    assert mw is not None

    seen: list[Request] = []

    async def _capture_next(request: Request) -> Response:
        seen.append(request)
        return _ok_response()

    await mw(_make_request(), _capture_next)

    assert seen[0].headers["Authorization"] == "Bearer token"


async def test_string_bearer_skips_if_authorization_already_present() -> None:
    mw = _normalize_auth("ignored")
    assert mw is not None

    seen: list[Request] = []

    async def _capture_next(request: Request) -> Response:
        seen.append(request)
        return _ok_response()

    await mw(_make_request(headers={"Authorization": "Basic xyz"}), _capture_next)

    assert seen[0].headers["Authorization"] == "Basic xyz"
```

Run: `uv run pytest tests/test_internal_auth.py -v`
Expected: 3 passed.

- [ ] **Step 6: Add the callable-provider tests**

Append:

```python
async def test_sync_callable_returns_token_provider_middleware() -> None:
    mw = _normalize_auth(lambda: "sync-tok")
    assert mw is not None

    seen: list[Request] = []

    async def _capture_next(request: Request) -> Response:
        seen.append(request)
        return _ok_response()

    await mw(_make_request(), _capture_next)

    assert seen[0].headers["Authorization"] == "Bearer sync-tok"


async def test_async_callable_returns_token_provider_middleware() -> None:
    async def _provider() -> str:
        return "async-tok"

    mw = _normalize_auth(_provider)
    assert mw is not None

    seen: list[Request] = []

    async def _capture_next(request: Request) -> Response:
        seen.append(request)
        return _ok_response()

    await mw(_make_request(), _capture_next)

    assert seen[0].headers["Authorization"] == "Bearer async-tok"


async def test_callable_token_provider_skips_if_authorization_already_present() -> None:
    calls = 0

    def _provider() -> str:
        nonlocal calls
        calls += 1
        return "should-not-set"

    mw = _normalize_auth(_provider)
    assert mw is not None

    seen: list[Request] = []

    async def _capture_next(request: Request) -> Response:
        seen.append(request)
        return _ok_response()

    await mw(_make_request(headers={"authorization": "Basic existing"}), _capture_next)

    assert seen[0].headers["authorization"] == "Basic existing"
    assert calls == 0  # skip-fired; provider not invoked


async def test_callable_token_provider_calls_provider_per_request() -> None:
    calls = 0

    def _provider() -> str:
        nonlocal calls
        calls += 1
        return f"tok-{calls}"

    mw = _normalize_auth(_provider)
    assert mw is not None

    async def _ok_next(request: Request) -> Response:
        return _ok_response()

    await mw(_make_request(), _ok_next)
    await mw(_make_request(), _ok_next)
    await mw(_make_request(), _ok_next)

    assert calls == 3  # noqa: PLR2004
```

Run: `uv run pytest tests/test_internal_auth.py -v`
Expected: 7 passed.

- [ ] **Step 7: Add the Middleware-passthrough test**

Append:

```python
async def test_middleware_returned_unchanged() -> None:
    class _PassthroughMw:
        async def __call__(self, request: Request, next: Next) -> Response:  # noqa: A002
            return await next(request)

    mw = _PassthroughMw()
    assert _normalize_auth(mw) is mw
```

Run: `uv run pytest tests/test_internal_auth.py -v`
Expected: 8 passed.

- [ ] **Step 8: Add the TypeError tests**

Append:

```python
def test_one_arg_callable_raises_typeerror() -> None:
    with pytest.raises(TypeError, match=r"`auth=`.*0 args.*2 args.*1"):
        _normalize_auth(lambda x: "tok")  # noqa: ARG005 — intentional 1-arg callable


def test_non_callable_non_string_non_middleware_raises_typeerror() -> None:
    with pytest.raises(TypeError, match=r"`auth=`.*string.*Middleware.*int"):
        _normalize_auth(42)  # ty: ignore[invalid-argument-type]
```

Run: `uv run pytest tests/test_internal_auth.py -v`
Expected: 10 passed.

- [ ] **Step 9: Verify 100% coverage on the new module**

Run: `uv run pytest tests/test_internal_auth.py --cov=src/httpware/_internal/auth --cov-report=term-missing`
Expected: 100% coverage on `_internal/auth.py`.

- [ ] **Step 10: Lint and ty**

Run: `uv run ruff check src/httpware/_internal/auth.py tests/test_internal_auth.py`
Run: `uv run ty check src/httpware/_internal/auth.py`
Expected: both clean.

- [ ] **Step 11: Commit**

```bash
git add src/httpware/_internal/auth.py tests/test_internal_auth.py
git commit -m "$(cat <<'EOF'
feat(story-2.4): _internal/auth.py with _normalize_auth coercion

Adds src/httpware/_internal/auth.py with:
- AuthValue: TypeAlias = str | Callable[[], str | Awaitable[str]] | Middleware | None
- _normalize_auth(value): coerces into Middleware | None via signature-arity
  dispatch (0 → token provider, 2 → Middleware passthrough, else TypeError)
- _bearer(token): static bearer middleware via @before_request
- _bearer_from_provider(provider): dynamic bearer middleware via @before_request
  with sync/async detection via inspect.isawaitable
- _has_authorization(request): case-insensitive skip-check

Ten tests cover: None passthrough, string→bearer happy path and
skip-if-present, sync and async callable providers, callable skip-if-present,
provider called per request (no caching), Middleware identity passthrough,
1-arg callable raises TypeError, non-callable raises TypeError.

No __all__ (project convention). 100% line coverage on the new module.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: AsyncClient `__init__` integration

Add `auth: AuthValue = None` to the constructor. Track `_user_middleware` and `_auth` separately. Compose user middleware + auth middleware at the END before `compose()`.

**Files:**
- Modify: `src/httpware/client.py` (extend imports + `__init__` body)
- Modify: `tests/test_client_construction.py` (append 3 tests)

- [ ] **Step 1: Add the failing tests**

Append to `tests/test_client_construction.py`. The existing imports already include `AsyncClient`, `Limits`, `Timeout`, `RecordedTransport`; add `Middleware` if not present and add the auth-related imports:

```python
from httpware._internal.auth import _normalize_auth


def test_init_no_auth_means_no_auth_middleware() -> None:
    transport = RecordedTransport()
    client = AsyncClient(transport=transport)
    assert client._config.middleware == ()
    assert client._auth is None
    assert client._user_middleware == ()


def test_init_with_string_auth_appends_bearer_middleware() -> None:
    transport = RecordedTransport()
    client = AsyncClient(transport=transport, auth="tok")
    assert len(client._config.middleware) == 1
    assert isinstance(client._config.middleware[0], Middleware)
    assert client._auth == "tok"
    assert client._user_middleware == ()


def test_init_with_user_middleware_plus_auth() -> None:
    class _M:
        async def __call__(self, request, next):  # noqa: A002, ANN001
            return await next(request)

    m1 = _M()
    m2 = _M()
    transport = RecordedTransport()
    client = AsyncClient(transport=transport, middleware=[m1, m2], auth="tok")
    assert len(client._config.middleware) == 3
    assert client._config.middleware[0] is m1
    assert client._config.middleware[1] is m2
    # The third entry is the auth middleware; identity-test that user_middleware excludes it.
    assert client._user_middleware == (m1, m2)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_client_construction.py -k "auth" -v`
Expected: `TypeError: AsyncClient() got an unexpected keyword argument 'auth'`.

- [ ] **Step 3: Extend imports in `src/httpware/client.py`**

At the top of `src/httpware/client.py`, find the existing import block. Add:

```python
from httpware._internal.auth import AuthValue, _normalize_auth
```

(Place in alphabetic order among the `httpware._internal.*` imports; ruff will reorder if needed.)

- [ ] **Step 4: Add `auth=` to `__init__` and amend the body**

Modify `AsyncClient.__init__`. Add the parameter at the end of the keyword-only list:

```python
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
    auth: AuthValue = None,
) -> None:
```

Replace the body (the current body resolves middleware then composes; we now interpose the auth coercion and append). The full replaced body:

```python
    normalized_timeout = _normalize_timeout(timeout)
    resolved_limits = limits or Limits()
    resolved_transport: Transport = transport or Httpx2Transport(
        limits=resolved_limits, timeout=normalized_timeout
    )
    resolved_decoder = decoder or PydanticDecoder()
    resolved_user_middleware: tuple[Middleware, ...] = (
        tuple(middleware) if middleware is not None else ()
    )
    resolved_auth_middleware = _normalize_auth(auth)
    composed_middleware: tuple[Middleware, ...] = (
        resolved_user_middleware
        if resolved_auth_middleware is None
        else (*resolved_user_middleware, resolved_auth_middleware)
    )

    self._config = ClientConfig(
        base_url=base_url,
        default_headers=dict(default_headers or {}),
        default_query=dict(default_query or {}),
        timeout=normalized_timeout,
        limits=resolved_limits,
        decoder=resolved_decoder,
        middleware=composed_middleware,
    )
    self._transport = resolved_transport
    self._dispatch = compose(composed_middleware, resolved_transport)
    self._owns_transport = True
    self._user_middleware = resolved_user_middleware
    self._auth = auth
```

- [ ] **Step 5: Run construction tests**

Run: `uv run pytest tests/test_client_construction.py -v`
Expected: existing 11 tests + 3 new = 14 passed.

- [ ] **Step 6: Lint and ty**

Run: `uv run ruff check src/httpware/client.py tests/test_client_construction.py`
Run: `uv run ty check src/httpware/client.py`
Expected: both clean.

- [ ] **Step 7: Commit**

```bash
git add src/httpware/client.py tests/test_client_construction.py
git commit -m "$(cat <<'EOF'
feat(story-2.4): AsyncClient.__init__ accepts auth= and tracks _user_middleware/_auth

Adds the `auth: AuthValue = None` keyword param. Coerces via
_normalize_auth and appends the resulting middleware (if any) at the END
of the user-supplied middleware list — so it runs just before the
transport.

Introduces two new private attrs on AsyncClient:
- _user_middleware: the user's tuple, EXCLUDING the auth middleware
- _auth: the raw AuthValue (so with_options can recompose)

ClientConfig.middleware continues to hold the COMPOSED list (what
actually runs), keeping the existing wiring contract.

Three new construction tests verify: no auth → empty composed; string
auth → 1-element composed; user middleware + auth → 3-element composed
with user entries at positions 0,1 and auth at position 2.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: End-to-end Authorization header tests

Three tests in `tests/test_client_methods.py` confirming the auth middleware fires through the full AsyncClient → transport path. No production code changes expected.

**Files:**
- Modify: `tests/test_client_methods.py` (append 3 tests)

- [ ] **Step 1: Add the tests**

Append to `tests/test_client_methods.py`. The existing imports already include `AsyncClient`, `RecordedTransport`, `Request`, `Response`. Add `pytest` if not present (it is).

```python
async def test_string_auth_sends_authorization_header() -> None:
    transport = RecordedTransport(
        default=Response(status=200, headers={}, content=b"", url="/", elapsed=0.0)
    )
    client = AsyncClient(transport=transport, auth="tok")

    await client.get("/foo")

    assert transport.last_request is not None
    assert transport.last_request.headers["Authorization"] == "Bearer tok"


async def test_per_call_authorization_header_wins_over_auth_param() -> None:
    transport = RecordedTransport(
        default=Response(status=200, headers={}, content=b"", url="/", elapsed=0.0)
    )
    client = AsyncClient(transport=transport, auth="default-tok")

    await client.get("/foo", headers={"Authorization": "Bearer override"})

    assert transport.last_request is not None
    assert transport.last_request.headers["Authorization"] == "Bearer override"


async def test_callable_auth_calls_provider_per_request() -> None:
    transport = RecordedTransport(
        default=Response(status=200, headers={}, content=b"", url="/", elapsed=0.0)
    )
    calls = 0

    def _provider() -> str:
        nonlocal calls
        calls += 1
        return f"tok-{calls}"

    client = AsyncClient(transport=transport, auth=_provider)

    await client.get("/a")
    await client.get("/b")

    assert calls == 2  # noqa: PLR2004
```

- [ ] **Step 2: Run tests**

Run: `uv run pytest tests/test_client_methods.py -k "auth" -v`
Expected: 3 passed.

- [ ] **Step 3: Lint**

Run: `uv run ruff check tests/test_client_methods.py`
Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add tests/test_client_methods.py
git commit -m "$(cat <<'EOF'
test(story-2.4): end-to-end Authorization header injection via auth=

Three tests confirm the auth middleware fires through the full
AsyncClient → transport path:
- string auth attaches Authorization: Bearer <token> on the transport's
  observed request
- per-call headers={"Authorization": ...} wins over the auth= param
  (skip-if-present rule)
- callable auth invokes the provider once per AsyncClient.get(...) call

No production code changes; Task 2 wired the integration.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: `with_options(auth=...)` + `_from_view` updates

Add `auth` to the `with_options` keyword allowlist; recompose user middleware + auth into the new `ClientConfig.middleware`. Update `_from_view` to accept `user_middleware=` and `auth=` keyword params.

**Files:**
- Modify: `src/httpware/client.py` (extend `with_options` + `_from_view`)
- Modify: `tests/test_client_middleware_wiring.py` (append 3 tests)

- [ ] **Step 1: Add the failing tests**

Append to `tests/test_client_middleware_wiring.py`. The existing imports already include `AsyncClient`, `RecordedTransport`, `Request`, `Response`, `Middleware`, `Next`.

```python
async def test_auth_runs_inside_user_middleware() -> None:
    transport = RecordedTransport(
        default=Response(status=200, headers={}, content=b"", url="/", elapsed=0.0)
    )

    user_seen_headers: list[Mapping[str, str]] = []  # type: ignore[name-defined]

    class _UserOuter:
        async def __call__(self, request: Request, next: Next) -> Response:  # noqa: A002
            user_seen_headers.append(dict(request.headers))
            return await next(request)

    client = AsyncClient(transport=transport, middleware=[_UserOuter()], auth="tok")
    await client.get("/foo")

    # User middleware saw the request BEFORE auth header was applied.
    assert "Authorization" not in user_seen_headers[0]
    # Transport saw the request WITH the auth header.
    assert transport.last_request is not None
    assert transport.last_request.headers["Authorization"] == "Bearer tok"


async def test_with_options_auth_replaces_auth_middleware() -> None:
    transport = RecordedTransport(
        default=Response(status=200, headers={}, content=b"", url="/", elapsed=0.0)
    )
    client = AsyncClient(transport=transport, auth="parent")
    view = client.with_options(auth="view")

    await view.get("/foo")
    assert transport.last_request is not None
    assert transport.last_request.headers["Authorization"] == "Bearer view"

    await client.get("/foo")
    assert transport.last_request is not None
    assert transport.last_request.headers["Authorization"] == "Bearer parent"


async def test_with_options_middleware_keeps_existing_auth() -> None:
    transport = RecordedTransport(
        default=Response(status=200, headers={}, content=b"", url="/", elapsed=0.0)
    )

    class _M:
        async def __call__(self, request: Request, next: Next) -> Response:  # noqa: A002
            return await next(request)

    m1 = _M()
    m2 = _M()
    client = AsyncClient(transport=transport, auth="tok", middleware=[m1])
    view = client.with_options(middleware=[m2])

    await view.get("/foo")
    assert transport.last_request is not None
    assert transport.last_request.headers["Authorization"] == "Bearer tok"
```

The first test references `Mapping` — add to imports if not already present at the top of the file:

```python
from collections.abc import Mapping
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_client_middleware_wiring.py -k "auth or with_options" -v`
Expected: the `auth_runs_inside_user_middleware` test passes (uses Task 2's `__init__`); the two `with_options` tests fail with `TypeError: with_options() got an unexpected keyword argument 'auth'`.

- [ ] **Step 3: Update `with_options` in `src/httpware/client.py`**

Find the `with_options` method (currently at ~line 576). Add `auth: AuthValue | object = _UNSET` to the keyword-only list and amend the body. Full replaced method:

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
    auth: AuthValue | object = _UNSET,
) -> "AsyncClient":
    """Return a new AsyncClient sharing the same transport with overridden config.

    The returned client is a "view": it does NOT own the transport lifecycle.
    Closing it via `async with` is a no-op. The original client should be the
    one inside the outermost `async with` block.

    `limits` and `transport` are NOT overridable here — both bind to the
    transport, which is shared. Construct a fresh AsyncClient for those.
    """
    changes: dict[str, typing.Any] = {}
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

    new_user_middleware = self._user_middleware
    if middleware is not _UNSET:
        new_user_middleware = tuple(middleware) if middleware is not None else ()

    new_auth = self._auth
    if auth is not _UNSET:
        new_auth = auth

    new_auth_middleware = _normalize_auth(new_auth)
    new_composed: tuple[Middleware, ...] = (
        new_user_middleware
        if new_auth_middleware is None
        else (*new_user_middleware, new_auth_middleware)
    )
    changes["middleware"] = new_composed

    new_config = dataclasses.replace(self._config, **changes)
    return AsyncClient._from_view(
        new_config,
        self._transport,
        user_middleware=new_user_middleware,
        auth=new_auth,
    )
```

- [ ] **Step 4: Update `_from_view` in `src/httpware/client.py`**

Find `_from_view` (immediately below `with_options`). Replace it with:

```python
@classmethod
def _from_view(
    cls,
    config: ClientConfig,
    transport: Transport,
    *,
    user_middleware: tuple[Middleware, ...],
    auth: AuthValue,
) -> "AsyncClient":
    """Construct a view sharing an existing transport. Bypasses __init__."""
    client = cls.__new__(cls)
    client._config = config
    client._transport = transport
    client._dispatch = compose(config.middleware, transport)
    client._owns_transport = False
    client._user_middleware = user_middleware
    client._auth = auth
    return client
```

- [ ] **Step 5: Run middleware-wiring tests**

Run: `uv run pytest tests/test_client_middleware_wiring.py -v`
Expected: all tests pass (previously 13 + 3 new = 16 passed; verify the count matches what the file actually contained before; the absolute number doesn't matter — both new tests pass and no old test breaks).

- [ ] **Step 6: Run all existing tests to confirm no regression**

Run: `just test`
Expected: 273 (baseline post-1.8) + 10 (Task 1) + 3 (Task 2) + 3 (Task 3) + 3 (Task 4) = 292 passed at this point, 1 deselected. (Task 5 adds one more reexport test for a final total of 293.)

- [ ] **Step 7: Lint and ty**

Run: `uv run ruff check src/httpware/client.py tests/test_client_middleware_wiring.py`
Run: `uv run ty check src/httpware/client.py`
Expected: both clean.

- [ ] **Step 8: Commit**

```bash
git add src/httpware/client.py tests/test_client_middleware_wiring.py
git commit -m "$(cat <<'EOF'
feat(story-2.4): with_options(auth=) + _from_view tracks user_middleware/auth

with_options now accepts `auth: AuthValue | object = _UNSET`. View
construction recomposes the chain from the new (or inherited) user
middleware + auth value: `with_options(middleware=...)` preserves auth;
`with_options(auth=...)` preserves user middleware; both can change
together; neither change loses the auth/middleware that wasn't passed.

_from_view gains `user_middleware=` and `auth=` keyword params so the
view client inherits the raw inputs (not just the composed result) and
its own with_options call works correctly.

Three new wiring tests cover: auth runs INSIDE user middleware (user
sees request before auth header; transport sees it after); with_options
replaces auth in the view while preserving the parent; with_options
replacing middleware preserves auth.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Public exports + reexport test

Re-export `AuthValue` at the package root and add to `__all__`.

**Files:**
- Modify: `src/httpware/__init__.py`
- Modify: `tests/test_internal_auth.py` (append reexport test)

- [ ] **Step 1: Add the failing reexport test**

Append to `tests/test_internal_auth.py`:

```python
def test_auth_value_reexported_at_package_root() -> None:
    """`from httpware import AuthValue` works."""
    import httpware
    from httpware._internal.auth import AuthValue as InternalAuthValue

    assert httpware.AuthValue is InternalAuthValue
    assert "AuthValue" in httpware.__all__
```

Move the `import httpware` to the top of the file (project preference: no in-function imports). Add at the top alongside the other imports.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_internal_auth.py::test_auth_value_reexported_at_package_root -v`
Expected: `AttributeError: module 'httpware' has no attribute 'AuthValue'`.

- [ ] **Step 3: Update `src/httpware/__init__.py`**

Find the existing `from httpware._internal.chain import compose` line (or wherever `_internal.*` imports live). Add:

```python
from httpware._internal.auth import AuthValue
```

In `__all__`, add `"AuthValue"`. The list is sorted by ruff's `RUF022` (ASCII order); `"AuthValue"` sits between `"AsyncClient"` and `"BadRequestError"`. If unsure, add anywhere and run `uv run ruff check --fix src/httpware/__init__.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_internal_auth.py -v`
Expected: 11 passed (10 + 1 reexport).

- [ ] **Step 5: Lint and ty**

Run: `uv run ruff check src/httpware/__init__.py tests/test_internal_auth.py`
Run: `uv run ty check src/httpware/__init__.py`
Expected: both clean.

- [ ] **Step 6: Commit**

```bash
git add src/httpware/__init__.py tests/test_internal_auth.py
git commit -m "$(cat <<'EOF'
feat(story-2.4): re-export AuthValue at httpware package root

Adds AuthValue to httpware/__init__.py imports and __all__ so consumers
can `from httpware import AuthValue` to type-annotate their config (e.g.,
a settings class that holds an auth value).

The bearer helpers and _normalize_auth remain internal at
httpware._internal.auth and are NOT exported.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Verify, push, PR, merge

- [ ] **Step 1: Run the full test suite**

Run: `just test`
Expected: 293 passed, 1 deselected (perf), 100% line coverage including the new `_internal/auth.py`.

- [ ] **Step 2: Run lint and type checks**

Run: `just lint-ci`
Expected: `eof-fixer`, `ruff format --check`, `ruff check --no-fix`, `ty check` all clean.

- [ ] **Step 3: Confirm the working tree**

Run: `git status --short`
Expected: only the untracked plan file `planning/plans/2026-06-01-auth-coercion-plan.md`.

Run: `git log --oneline main..HEAD`
Expected: six commits — spec, Task 1, Task 2, Task 3, Task 4, Task 5.

- [ ] **Step 4: Stage and commit the plan**

```bash
git add planning/plans/2026-06-01-auth-coercion-plan.md
git commit -m "docs(story-2.4): implementation plan for auth coercion

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 5: Push the branch**

Run: `git push -u origin story/2-4-auth-coercion`
Expected: push succeeds.

- [ ] **Step 6: Open the PR**

```bash
gh pr create --title "feat(story-2.4): auth coercion as middleware" --body "$(cat <<'EOF'
## Summary

- Adds an \`auth=\` parameter to \`AsyncClient.__init__\` and \`with_options\` accepting \`str | Callable[[], str | Awaitable[str]] | Middleware | None\`. \`AuthValue\` type alias re-exported at the package root.
- Coercion lives in \`src/httpware/_internal/auth.py\`. Dispatch via \`inspect.signature\` arity: 0 → token provider, 2 → Middleware passthrough, else \`TypeError\`. Bearer helpers built atop \`@before_request\` (free \`<before_request(...)>\` repr; token never leaks).
- Skip-if-present rule: auth middleware leaves an existing \`Authorization\` header untouched (user middleware / per-call header wins). Provider not invoked when skip fires.
- Auth middleware appended at the END of the user-supplied list — runs just before the transport. User middleware sees Request WITHOUT auth header on the way down; sees Response on the way up.
- \`with_options(auth=...)\` supported; AsyncClient tracks \`_user_middleware\` and \`_auth\` separately so \`with_options(middleware=...)\` preserves the existing auth, and vice versa.
- 20 new tests (10 in \`test_internal_auth.py\` + 3 construction + 3 methods + 3 wiring); 100% line coverage on the new source.

**This closes Epic 2.**

Out of scope: OAuth2 / refresh tokens, mTLS, signature schemes (HMAC, AWS Sigv4), per-call \`auth=\` override on HTTP methods.

Spec + plan: \`planning/specs/2026-06-01-auth-coercion-design.md\`, \`planning/plans/2026-06-01-auth-coercion-plan.md\`.

## Test plan

- [x] \`just test\` — 293 passed, 1 deselected, 100% line coverage on the new module.
- [x] \`just lint-ci\` clean.
- [x] \`tests/test_no_httpx2_leakage.py\` still passes.
- [x] \`tests/test_optional_extras_isolation.py\` still passes.
- [ ] CI green on all matrix entries (3.11/3.12/3.13/3.14 + lint).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 7: Wait for CI**

Run: `gh pr checks <PR_NUMBER>`.
Expected: all five jobs green.

If `pytest (3.14)` fails on the `codecov/codecov-action@v4.0.1` step with EPIPE (the transient pattern this repo has hit before), re-run with `gh run rerun <RUN_ID> --failed`.

- [ ] **Step 8: Merge**

Once CI is green:

Run: `gh pr merge <PR_NUMBER> --merge --delete-branch`
Run: `git checkout main && git pull --ff-only && git log --oneline -3`

Story 2-4 is complete. **Epic 2 is complete.** The next normal-flow roadmap item is Epic 3 (resilience: retry, RetryBudget, bulkhead).

---

## Definition of done

- `src/httpware/_internal/auth.py` exists with `AuthValue`, `_normalize_auth`, `_bearer`, `_bearer_from_provider`, `_has_authorization`. No `__all__`.
- `src/httpware/client.py` `__init__` accepts `auth: AuthValue = None`; private attrs `_user_middleware` and `_auth` set. Auth middleware appended at the end of the composed list.
- `src/httpware/client.py` `with_options` accepts `auth=` and recomposes; `_from_view` accepts `user_middleware=` and `auth=` kwargs.
- `src/httpware/__init__.py` re-exports `AuthValue` and adds it to `__all__`.
- 20 new tests pass; existing 273 tests still pass.
- `just test` shows 293 passed, 1 deselected, 100% line coverage on the new source.
- `just lint-ci` clean.
- `tests/test_no_httpx2_leakage.py` and `tests/test_optional_extras_isolation.py` still pass.
- Story 2-4 lands as a single PR off `main` via the branch `story/2-4-auth-coercion`. After this merge, Epic 2 is fully complete.

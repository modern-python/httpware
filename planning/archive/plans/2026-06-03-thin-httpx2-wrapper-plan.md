# Thin httpx2 wrapper (v0.2 pivot) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Re-cut `httpware` as a thin opinionated wrapper around `httpx2`. Drop the `Transport` protocol, custom `Request`/`Response`/`Limits`/`Timeout`/`ClientConfig` value types, `RecordedTransport`, auth coercion, and `with_options`. Keep typed decoders, middleware chain, and the status-keyed exception tree. Ship as `0.2.0`.

**Architecture:** `AsyncClient` owns (or wraps) an `httpx2.AsyncClient`. Per-method calls delegate `build_request` to httpx2, run the request through a middleware chain composed at `__init__`, hit an internal terminal that calls `httpx2.AsyncClient.send`, maps `httpx2` exceptions to `httpware` exceptions, and raises a `StatusError` subclass on 4xx/5xx. Decoders run after the chain if `response_model=` is set. Three protocol seams remain: `AsyncClient ↔ Middleware`, `AsyncClient ↔ ResponseDecoder`, `httpware ↔ optional extras`.

**Tech Stack:** Python 3.11+, `httpx2`, `pydantic` (default decoder), `msgspec` (opt-in via extras), `ty` (type checker), `ruff` (linter), `pytest` + `pytest-asyncio` (auto mode), `hypothesis` (property tests), `uv` (package manager), `just` (task runner).

**Spec:** `planning/specs/2026-06-03-thin-httpx2-wrapper-design.md`

**Scope check:** Single structural PR per spec section 13. Epic 3 (resilience), Epic 4 (streaming), Epic 5 (observability) are explicitly out of scope and land later as ordinary stories.

---

## File map

**Surviving with edits:**

- `src/httpware/__init__.py` — exports rewritten.
- `src/httpware/decoders/__init__.py` — unchanged (protocol stays).
- `src/httpware/decoders/pydantic.py` — unchanged.
- `src/httpware/decoders/msgspec.py` — unchanged.
- `src/httpware/_internal/import_checker.py` — unchanged.
- `tests/test_decoders_pydantic.py` — unchanged.
- `tests/test_decoders_msgspec.py` — unchanged.
- `tests/test_decoders_pydantic_bench.py` — unchanged (perf marker).
- `tests/test_optional_extras_isolation.py` — unchanged.
- `tests/conftest.py` — unchanged.
- `CLAUDE.md` — rewrite invariants + module layout sections.
- `docs/dev/engineering.md` — rewrite sections 2, 3, 5, 8.
- `planning/deferred-work.md` — sweep items obsoleted by pivot.
- `pyproject.toml` — bump version, drop the `httpx2 leakage` ruff/ty notes if present.

**New files:**

- `src/httpware/client.py` (full rewrite — delete & re-create).
- `src/httpware/errors.py` (full rewrite — delete & re-create).
- `src/httpware/middleware/__init__.py` (full rewrite — delete & re-create).
- `src/httpware/middleware/chain.py` (new file, holds `compose`).
- `tests/test_errors.py` (full rewrite — delete & re-create).
- `tests/test_middleware.py` (full rewrite — delete & re-create).
- `tests/test_client_construction.py` (full rewrite — delete & re-create).
- `tests/test_client_lifecycle.py` (full rewrite — delete & re-create).
- `tests/test_client_methods.py` (full rewrite — delete & re-create).
- `tests/test_client_middleware_wiring.py` (full rewrite — delete & re-create).
- `tests/test_client_response_model.py` (full rewrite — delete & re-create).
- `tests/test_client_typing.py` (full rewrite — delete & re-create).
- `tests/test_public_api.py` (full rewrite — delete & re-create).
- `tests/test_error_mapping_terminal.py` (new — terminal-level error translation).

**Deleted:**

- `src/httpware/request.py`
- `src/httpware/response.py`
- `src/httpware/config.py`
- `src/httpware/transports/` (entire directory)
- `src/httpware/_internal/auth.py`
- `src/httpware/_internal/chain.py`
- `tests/test_request.py`
- `tests/test_response.py`
- `tests/test_config.py`
- `tests/test_transports_httpx2.py`
- `tests/test_transports_recorded.py`
- `tests/test_internal_auth.py`
- `tests/test_no_httpx2_leakage.py`

---

## Task 1: Pre-flight

**Files:**
- Inspect: working tree, current branch, baseline test status.

- [ ] **Step 1: Verify clean working tree on a fresh branch**

Run:
```bash
git status
git switch -c feat/v0.2-thin-httpx2-wrapper
```
Expected: working tree is clean; new branch created off `main`.

- [ ] **Step 2: Capture the baseline pass/fail count**

Run:
```bash
just install
just test 2>&1 | tail -20
```
Expected: full suite passes (100% coverage on the existing modules). Record the totals (e.g. "147 passed").

This is the "before" snapshot; we will track regressions against it.

- [ ] **Step 3: Confirm `httpx2.MockTransport` exists in the installed version**

Run:
```bash
uv run python -c "import httpx2; print(httpx2.MockTransport)"
```
Expected: `<class 'httpx2.MockTransport'>` (no AttributeError). If absent, stop and tell the user — the pivot needs MockTransport for the testing pattern.

- [ ] **Step 4: Commit a marker tag for rollback**

Run:
```bash
git tag pre-v0.2-pivot
```
Expected: tag created at the current `HEAD` (no commit yet on the feature branch).

---

## Task 2: Tear-down (one explicit deletion commit)

**Files:**
- Delete: `src/httpware/request.py`, `src/httpware/response.py`, `src/httpware/config.py`, `src/httpware/transports/`, `src/httpware/_internal/auth.py`, `src/httpware/_internal/chain.py`.
- Delete: `tests/test_request.py`, `tests/test_response.py`, `tests/test_config.py`, `tests/test_transports_httpx2.py`, `tests/test_transports_recorded.py`, `tests/test_internal_auth.py`, `tests/test_no_httpx2_leakage.py`.
- Stub: `src/httpware/__init__.py`, `src/httpware/client.py`, `src/httpware/errors.py`, `src/httpware/middleware/__init__.py`.
- Delete: `tests/test_errors.py`, `tests/test_middleware.py`, `tests/test_client_*.py`, `tests/test_public_api.py`.

- [ ] **Step 1: Remove the deleted files**

Run:
```bash
git rm src/httpware/request.py
git rm src/httpware/response.py
git rm src/httpware/config.py
git rm -r src/httpware/transports
git rm src/httpware/_internal/auth.py
git rm src/httpware/_internal/chain.py
git rm tests/test_request.py tests/test_response.py tests/test_config.py
git rm tests/test_transports_httpx2.py tests/test_transports_recorded.py
git rm tests/test_internal_auth.py tests/test_no_httpx2_leakage.py
git rm tests/test_errors.py tests/test_middleware.py
git rm tests/test_client_construction.py tests/test_client_lifecycle.py
git rm tests/test_client_methods.py tests/test_client_middleware_wiring.py
git rm tests/test_client_response_model.py tests/test_client_typing.py
git rm tests/test_public_api.py
```

- [ ] **Step 2: Stub the surviving package files to a minimal compilable state**

Replace `src/httpware/__init__.py` with:
```python
"""httpware — thin async HTTP client wrapper over httpx2."""
```

Replace `src/httpware/client.py` with:
```python
"""AsyncClient — implemented in later tasks of the v0.2 pivot."""
```

Replace `src/httpware/errors.py` with:
```python
"""Exception hierarchy — implemented in later tasks of the v0.2 pivot."""
```

Replace `src/httpware/middleware/__init__.py` with:
```python
"""Middleware protocol — implemented in later tasks of the v0.2 pivot."""
```

- [ ] **Step 3: Confirm decoders + extras-isolation tests still pass**

Run:
```bash
just test tests/test_decoders_pydantic.py tests/test_decoders_msgspec.py tests/test_optional_extras_isolation.py 2>&1 | tail -10
```
Expected: all three files pass. (These are the only tests that survive the tear-down.)

- [ ] **Step 4: Commit the tear-down**

Run:
```bash
git add -A
git commit -m "refactor(v0.2): tear down 0.1 surfaces ahead of thin-wrapper rewrite

Remove Request/Response/Config value types, Transport protocol,
Httpx2Transport, RecordedTransport, auth coercion, and the no-leakage
CI invariant. Decoders survive. New AsyncClient/errors/middleware land
in subsequent commits."
```

---

## Task 3: Errors — failing tests

**Files:**
- Create: `tests/test_errors.py`

- [ ] **Step 1: Write the failing test file**

Create `tests/test_errors.py`:
```python
"""Tests for the status-keyed exception tree in httpware.errors."""

import builtins
import pickle

import httpx2
import pytest

from httpware.errors import (
    STATUS_TO_EXCEPTION,
    BadRequestError,
    ClientError,
    ClientStatusError,
    ConflictError,
    ForbiddenError,
    InternalServerError,
    NotFoundError,
    RateLimitedError,
    ServerStatusError,
    ServiceUnavailableError,
    StatusError,
    TimeoutError,  # noqa: A004
    TransportError,
    UnauthorizedError,
    UnprocessableEntityError,
)


def _make_response(status: int, *, url: str = "https://example.test/x", method: str = "GET") -> httpx2.Response:
    request = httpx2.Request(method, url)
    return httpx2.Response(status, request=request)


def test_inheritance_tree() -> None:
    assert issubclass(StatusError, ClientError)
    assert issubclass(TransportError, ClientError)
    assert issubclass(TimeoutError, ClientError)
    assert issubclass(TimeoutError, builtins.TimeoutError)
    assert issubclass(ClientStatusError, StatusError)
    assert issubclass(ServerStatusError, StatusError)
    for exc in (
        BadRequestError,
        UnauthorizedError,
        ForbiddenError,
        NotFoundError,
        ConflictError,
        UnprocessableEntityError,
        RateLimitedError,
    ):
        assert issubclass(exc, ClientStatusError), exc
    for exc in (InternalServerError, ServiceUnavailableError):
        assert issubclass(exc, ServerStatusError), exc


def test_status_to_exception_table() -> None:
    assert STATUS_TO_EXCEPTION == {
        400: BadRequestError,
        401: UnauthorizedError,
        403: ForbiddenError,
        404: NotFoundError,
        409: ConflictError,
        422: UnprocessableEntityError,
        429: RateLimitedError,
        500: InternalServerError,
        503: ServiceUnavailableError,
    }


def test_status_error_stores_response() -> None:
    response = _make_response(404)
    exc = NotFoundError(response)
    assert exc.response is response


def test_status_error_summary_message_includes_status_method_url() -> None:
    exc = NotFoundError(_make_response(404, url="https://example.test/missing", method="GET"))
    assert str(exc) == "404 GET https://example.test/missing"


def test_status_error_strips_userinfo_in_summary_message() -> None:
    exc = NotFoundError(_make_response(404, url="https://user:pass@example.test/x"))
    assert "user" not in str(exc)
    assert "pass" not in str(exc)
    assert str(exc) == "404 GET https://example.test/x"


def test_status_error_repr_strips_userinfo() -> None:
    exc = NotFoundError(_make_response(404, url="https://user:pass@example.test/x"))
    r = repr(exc)
    assert "user" not in r
    assert "pass" not in r
    assert "NotFoundError" in r
    assert "status=404" in r


def test_status_error_pickleable() -> None:
    exc = NotFoundError(_make_response(404, url="https://example.test/x"))
    restored = pickle.loads(pickle.dumps(exc))
    assert isinstance(restored, NotFoundError)
    assert restored.response.status_code == 404
    assert str(restored.response.request.url) == "https://example.test/x"


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (400, BadRequestError),
        (401, UnauthorizedError),
        (404, NotFoundError),
        (429, RateLimitedError),
        (500, InternalServerError),
        (503, ServiceUnavailableError),
    ],
)
def test_per_status_subclasses_construct(status: int, expected: type[StatusError]) -> None:
    response = _make_response(status)
    exc = expected(response)
    assert isinstance(exc, expected)
    assert exc.response.status_code == status


def test_timeout_error_is_builtin_timeout_error() -> None:
    exc = TimeoutError("timed out")
    assert isinstance(exc, builtins.TimeoutError)
    assert isinstance(exc, ClientError)


def test_transport_error_is_client_error() -> None:
    exc = TransportError("connection refused")
    assert isinstance(exc, ClientError)
```

- [ ] **Step 2: Run the failing test**

Run:
```bash
just test tests/test_errors.py 2>&1 | tail -15
```
Expected: collection error (`ImportError`) — the symbols don't exist yet in `errors.py`.

---

## Task 4: Errors — implementation

**Files:**
- Modify: `src/httpware/errors.py`

- [ ] **Step 1: Replace the stub with the full exception module**

Replace `src/httpware/errors.py` with:
```python
"""Status-keyed exception hierarchy.

Auto-raise rule lives at AsyncClient's internal terminal (see client.py).
Unknown 4xx falls back to ClientStatusError; unknown 5xx to ServerStatusError.
The fallback assumes 400 <= status < 600.

__repr__ and the summary message strip user:pass@ userinfo from
response.request.url to avoid leaking credentials in tracebacks.
Query-string secrets are NOT stripped here.
"""

import builtins
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx2


def _strip_userinfo(url: str) -> str:
    if "@" not in url or "://" not in url:
        return url
    parts = urlsplit(url)
    if parts.username is None and parts.password is None:
        return url
    netloc = parts.hostname or ""
    if parts.port is not None:
        netloc = f"{netloc}:{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


class ClientError(Exception):
    """Root of the httpware exception tree."""


class TransportError(ClientError):
    """Connection / network / protocol failure raised before a response was received."""


class TimeoutError(ClientError, builtins.TimeoutError):  # noqa: A001
    """Client-side timeout (connect / read / write / pool).

    Inherits from both ``httpware.ClientError`` and ``builtins.TimeoutError`` so
    ``except builtins.TimeoutError`` / ``except OSError`` (the form
    ``asyncio.wait_for`` uses) also catches httpware-raised timeouts.
    Deliberate shadowing of the builtin; do not rename.
    """


def _reconstruct_status_error(cls: "type[StatusError]", response: httpx2.Response) -> "StatusError":
    return cls(response)


class StatusError(ClientError):
    """Base for HTTP-status-keyed errors.

    Holds the raw httpx2.Response. Subclasses do not override __init__.
    """

    response: httpx2.Response

    def __init__(self, response: httpx2.Response) -> None:
        self.response = response
        super().__init__(self._summary())

    def _summary(self) -> str:
        method = self.response.request.method
        url = _strip_userinfo(str(self.response.request.url))
        return f"{self.response.status_code} {method} {url}"

    def __repr__(self) -> str:
        cls_name = type(self).__name__
        method = self.response.request.method
        url = _strip_userinfo(str(self.response.request.url))
        return f"<{cls_name} status={self.response.status_code} method={method} url={url}>"

    def __reduce__(self) -> tuple[Any, ...]:
        return (_reconstruct_status_error, (type(self), self.response))


class ClientStatusError(StatusError):
    """Base for 4xx HTTP status errors."""


class ServerStatusError(StatusError):
    """Base for 5xx HTTP status errors."""


class BadRequestError(ClientStatusError):
    """HTTP 400."""


class UnauthorizedError(ClientStatusError):
    """HTTP 401."""


class ForbiddenError(ClientStatusError):
    """HTTP 403."""


class NotFoundError(ClientStatusError):
    """HTTP 404."""


class ConflictError(ClientStatusError):
    """HTTP 409."""


class UnprocessableEntityError(ClientStatusError):
    """HTTP 422."""


class RateLimitedError(ClientStatusError):
    """HTTP 429."""


class InternalServerError(ServerStatusError):
    """HTTP 500."""


class ServiceUnavailableError(ServerStatusError):
    """HTTP 503."""


STATUS_TO_EXCEPTION: Mapping[int, type[StatusError]] = {
    400: BadRequestError,
    401: UnauthorizedError,
    403: ForbiddenError,
    404: NotFoundError,
    409: ConflictError,
    422: UnprocessableEntityError,
    429: RateLimitedError,
    500: InternalServerError,
    503: ServiceUnavailableError,
}
```

- [ ] **Step 2: Run the test suite for errors**

Run:
```bash
just test tests/test_errors.py 2>&1 | tail -10
```
Expected: all tests pass.

- [ ] **Step 3: Lint**

Run:
```bash
just lint 2>&1 | tail -10
```
Expected: zero issues. Fix any that surface (typically `D205` or similar — adjust docstrings inline).

- [ ] **Step 4: Commit**

Run:
```bash
git add src/httpware/errors.py tests/test_errors.py
git commit -m "feat(errors): status-keyed exception tree holding httpx2.Response"
```

---

## Task 5: Middleware — failing tests

**Files:**
- Create: `tests/test_middleware.py`

- [ ] **Step 1: Write the failing test file**

Create `tests/test_middleware.py`:
```python
"""Tests for the Middleware protocol, Next type, chain composition, and decorators."""

import httpx2
import pytest

from httpware.middleware import (
    Middleware,
    Next,
    after_response,
    before_request,
    on_error,
)
from httpware.middleware.chain import compose


def _make_request(url: str = "https://example.test/x") -> httpx2.Request:
    return httpx2.Request("GET", url)


def _make_response(status: int = 200, *, request: httpx2.Request | None = None) -> httpx2.Response:
    if request is None:
        request = _make_request()
    return httpx2.Response(status, request=request)


async def test_middleware_protocol_is_runtime_checkable() -> None:
    class _OkMiddleware:
        async def __call__(self, request: httpx2.Request, next: Next) -> httpx2.Response:  # noqa: A002
            return await next(request)

    assert isinstance(_OkMiddleware(), Middleware)


async def test_empty_chain_calls_terminal_directly() -> None:
    seen: list[httpx2.Request] = []

    async def terminal(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return _make_response(200, request=request)

    dispatch = compose((), terminal)
    request = _make_request()
    response = await dispatch(request)
    assert response.status_code == 200
    assert seen == [request]


async def test_chain_runs_middleware_in_order() -> None:
    order: list[str] = []

    class _M:
        def __init__(self, label: str) -> None:
            self.label = label

        async def __call__(self, request: httpx2.Request, next: Next) -> httpx2.Response:  # noqa: A002
            order.append(f"{self.label}.before")
            response = await next(request)
            order.append(f"{self.label}.after")
            return response

    async def terminal(request: httpx2.Request) -> httpx2.Response:
        order.append("terminal")
        return _make_response(200, request=request)

    dispatch = compose((_M("a"), _M("b")), terminal)
    await dispatch(_make_request())
    assert order == ["a.before", "b.before", "terminal", "b.after", "a.after"]


async def test_before_request_decorator_transforms_request() -> None:
    @before_request
    async def add_header(request: httpx2.Request) -> httpx2.Request:
        return httpx2.Request(
            request.method, request.url, headers={**request.headers, "X-Custom": "1"}
        )

    captured: list[httpx2.Request] = []

    async def terminal(request: httpx2.Request) -> httpx2.Response:
        captured.append(request)
        return _make_response(200, request=request)

    dispatch = compose((add_header,), terminal)
    await dispatch(_make_request())
    assert captured[0].headers["x-custom"] == "1"


async def test_after_response_decorator_transforms_response() -> None:
    @after_response
    async def upgrade_status(request: httpx2.Request, response: httpx2.Response) -> httpx2.Response:
        return httpx2.Response(299, request=request, headers=response.headers, content=response.content)

    async def terminal(request: httpx2.Request) -> httpx2.Response:
        return _make_response(200, request=request)

    dispatch = compose((upgrade_status,), terminal)
    response = await dispatch(_make_request())
    assert response.status_code == 299


async def test_on_error_decorator_can_translate_exception() -> None:
    @on_error
    async def swallow(request: httpx2.Request, exc: Exception) -> httpx2.Response | None:
        if isinstance(exc, RuntimeError) and str(exc) == "boom":
            return _make_response(503, request=request)
        return None

    async def terminal(request: httpx2.Request) -> httpx2.Response:
        msg = "boom"
        raise RuntimeError(msg)

    dispatch = compose((swallow,), terminal)
    response = await dispatch(_make_request())
    assert response.status_code == 503


async def test_on_error_returns_none_reraises() -> None:
    @on_error
    async def passthrough(
        request: httpx2.Request,  # noqa: ARG001
        exc: Exception,  # noqa: ARG001
    ) -> httpx2.Response | None:
        return None

    async def terminal(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        msg = "boom"
        raise RuntimeError(msg)

    dispatch = compose((passthrough,), terminal)
    with pytest.raises(RuntimeError, match="boom"):
        await dispatch(_make_request())


async def test_on_error_lets_cancelled_propagate() -> None:
    import asyncio

    @on_error
    async def swallow_all(
        request: httpx2.Request,  # noqa: ARG001
        exc: Exception,  # noqa: ARG001
    ) -> httpx2.Response | None:
        msg = "should not catch CancelledError"
        raise AssertionError(msg)

    async def terminal(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        raise asyncio.CancelledError

    dispatch = compose((swallow_all,), terminal)
    with pytest.raises(asyncio.CancelledError):
        await dispatch(_make_request())
```

- [ ] **Step 2: Run the failing tests**

Run:
```bash
just test tests/test_middleware.py 2>&1 | tail -15
```
Expected: `ImportError` or collection failure — `Middleware`, `Next`, `compose`, decorators don't exist yet.

---

## Task 6: Middleware — implementation

**Files:**
- Modify: `src/httpware/middleware/__init__.py`
- Create: `src/httpware/middleware/chain.py`

- [ ] **Step 1: Implement the protocol and decorators**

Replace `src/httpware/middleware/__init__.py` with:
```python
"""Middleware protocol, Next type, and phase-shortcut decorators.

Middleware operates directly on httpx2.Request / httpx2.Response — there is
no httpware-owned request type. The chain is composed at AsyncClient.__init__
(see client.py) and frozen for the client's lifetime.
"""

from collections.abc import Awaitable, Callable
from typing import Protocol, TypeAlias, runtime_checkable

import httpx2

from httpware.middleware.chain import compose


Next: TypeAlias = Callable[[httpx2.Request], Awaitable[httpx2.Response]]


@runtime_checkable
class Middleware(Protocol):
    """Structural protocol every middleware satisfies."""

    async def __call__(self, request: httpx2.Request, next: Next) -> httpx2.Response:  # noqa: A002
        """Process `request`; call `next(request)` to forward, or synthesize a Response."""
        ...


def before_request(f: Callable[[httpx2.Request], Awaitable[httpx2.Request]]) -> Middleware:
    """Wrap an async request transform into a Middleware."""

    class _BeforeRequestMiddleware:
        async def __call__(self, request: httpx2.Request, next: Next) -> httpx2.Response:  # noqa: A002
            return await next(await f(request))

        def __repr__(self) -> str:
            return f"<before_request({f.__qualname__})>"  # ty: ignore[unresolved-attribute]

    return _BeforeRequestMiddleware()


def after_response(
    f: Callable[[httpx2.Request, httpx2.Response], Awaitable[httpx2.Response]],
) -> Middleware:
    """Wrap an async response transform into a Middleware."""

    class _AfterResponseMiddleware:
        async def __call__(self, request: httpx2.Request, next: Next) -> httpx2.Response:  # noqa: A002
            response = await next(request)
            return await f(request, response)

        def __repr__(self) -> str:
            return f"<after_response({f.__qualname__})>"  # ty: ignore[unresolved-attribute]

    return _AfterResponseMiddleware()


def on_error(
    f: Callable[[httpx2.Request, Exception], Awaitable[httpx2.Response | None]],
) -> Middleware:
    """Wrap an async error handler into a Middleware.

    Catches Exception (not BaseException), so asyncio.CancelledError propagates.
    Handler returning None re-raises; returning a Response replaces the failure.
    """

    class _OnErrorMiddleware:
        async def __call__(self, request: httpx2.Request, next: Next) -> httpx2.Response:  # noqa: A002
            try:
                return await next(request)
            except Exception as exc:
                result = await f(request, exc)
                if result is None:
                    raise
                return result

        def __repr__(self) -> str:
            return f"<on_error({f.__qualname__})>"  # ty: ignore[unresolved-attribute]

    return _OnErrorMiddleware()
```

- [ ] **Step 2: Implement chain composition**

Create `src/httpware/middleware/chain.py`:
```python
"""Chain composition for the middleware stack."""

from collections.abc import Awaitable, Callable, Sequence
from typing import TYPE_CHECKING, TypeAlias

import httpx2


if TYPE_CHECKING:
    from httpware.middleware import Middleware


_Next: TypeAlias = Callable[[httpx2.Request], Awaitable[httpx2.Response]]


def compose(middleware: "Sequence[Middleware]", terminal: _Next) -> _Next:
    """Fold `middleware` into a single callable around `terminal`.

    The first middleware in the sequence is the outermost wrapper.
    """
    dispatch: _Next = terminal
    for layer in reversed(middleware):
        dispatch = _wrap(layer, dispatch)
    return dispatch


def _wrap(layer: "Middleware", inner: _Next) -> _Next:
    async def call(request: httpx2.Request) -> httpx2.Response:
        return await layer(request, inner)

    return call
```

- [ ] **Step 3: Run middleware tests**

Run:
```bash
just test tests/test_middleware.py 2>&1 | tail -10
```
Expected: all tests pass.

- [ ] **Step 4: Lint**

Run:
```bash
just lint 2>&1 | tail -10
```
Expected: zero issues. The `if TYPE_CHECKING:` in `chain.py` avoids a circular import (`chain.py` is imported by `middleware/__init__.py`); keep it.

- [ ] **Step 5: Commit**

Run:
```bash
git add src/httpware/middleware tests/test_middleware.py
git commit -m "feat(middleware): protocol and chain retyped on httpx2.Request/Response"
```

---

## Task 7: AsyncClient — failing tests for construction & ownership

**Files:**
- Create: `tests/test_client_construction.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_client_construction.py`:
```python
"""Tests for AsyncClient construction and ownership semantics."""

import httpx2
import pytest

from httpware import AsyncClient


def test_construction_with_no_args_works() -> None:
    client = AsyncClient()
    assert isinstance(client, AsyncClient)


def test_construction_with_forwarded_kwargs() -> None:
    client = AsyncClient(
        base_url="https://example.test",
        headers={"x-shared": "1"},
        params={"trace": "yes"},
        timeout=10.0,
    )
    assert isinstance(client, AsyncClient)


def test_construction_with_caller_owned_httpx2_client() -> None:
    transport = httpx2.MockTransport(lambda req: httpx2.Response(200, request=req))
    caller = httpx2.AsyncClient(transport=transport)
    client = AsyncClient(httpx2_client=caller)
    assert isinstance(client, AsyncClient)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"base_url": "https://example.test"},
        {"headers": {"x": "1"}},
        {"params": {"x": "1"}},
        {"cookies": {"x": "1"}},
        {"timeout": 5.0},
        {"limits": httpx2.Limits(max_connections=10)},
        {"auth": httpx2.BasicAuth("u", "p")},
    ],
)
def test_caller_owned_client_with_forwarded_kwargs_is_typeerror(kwargs: dict) -> None:
    transport = httpx2.MockTransport(lambda req: httpx2.Response(200, request=req))
    caller = httpx2.AsyncClient(transport=transport)
    with pytest.raises(TypeError, match="httpx2_client"):
        AsyncClient(httpx2_client=caller, **kwargs)


def test_default_decoder_is_pydantic_decoder() -> None:
    from httpware.decoders.pydantic import PydanticDecoder

    client = AsyncClient()
    assert isinstance(client._decoder, PydanticDecoder)  # noqa: SLF001


def test_explicit_decoder_is_honored() -> None:
    class _Stub:
        def decode(self, content: bytes, model: type) -> object:  # noqa: ARG002
            return None

    client = AsyncClient(decoder=_Stub())
    assert isinstance(client._decoder, _Stub)  # noqa: SLF001


def test_explicit_middleware_is_honored() -> None:
    captured: list[str] = []

    class _Tag:
        async def __call__(self, request, next):  # noqa: A002, ANN001
            captured.append("tag")
            return await next(request)

    client = AsyncClient(middleware=(_Tag(),))
    assert client._user_middleware == (client._user_middleware[0],)  # noqa: SLF001
    assert len(client._user_middleware) == 1  # noqa: SLF001
```

- [ ] **Step 2: Run the failing tests**

Run:
```bash
just test tests/test_client_construction.py 2>&1 | tail -15
```
Expected: `ImportError` — `AsyncClient` doesn't exist yet.

---

## Task 8: AsyncClient — construction implementation

**Files:**
- Modify: `src/httpware/client.py`

- [ ] **Step 1: Implement `AsyncClient.__init__` and the terminal/chain wiring**

Replace `src/httpware/client.py` with:
```python
"""AsyncClient — the thin httpx2 wrapper."""

import typing
from collections.abc import Sequence

import httpx2

from httpware.decoders import ResponseDecoder
from httpware.decoders.pydantic import PydanticDecoder
from httpware.errors import (
    STATUS_TO_EXCEPTION,
    ClientStatusError,
    ServerStatusError,
    TimeoutError,  # noqa: A004
    TransportError,
)
from httpware.middleware import Middleware, Next
from httpware.middleware.chain import compose


T = typing.TypeVar("T")


_FORWARDED_KWARG_NAMES = ("base_url", "headers", "params", "cookies", "timeout", "limits", "auth")
_HTTPX2_CLIENT_CONFLICT_MESSAGE = (
    "AsyncClient(httpx2_client=...) cannot be combined with any of "
    f"{_FORWARDED_KWARG_NAMES}; configure the httpx2.AsyncClient you pass instead."
)


class AsyncClient:
    """Async HTTP client: thin wrapper around httpx2 with typed decoding and middleware."""

    _httpx2_client: httpx2.AsyncClient
    _owns_client: bool
    _decoder: ResponseDecoder
    _user_middleware: tuple[Middleware, ...]
    _dispatch: Next

    def __init__(  # noqa: PLR0913
        self,
        *,
        base_url: str = "",
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
        cookies: dict[str, str] | None = None,
        timeout: httpx2.Timeout | float | None = None,
        limits: httpx2.Limits | None = None,
        auth: httpx2.Auth | None = None,
        httpx2_client: httpx2.AsyncClient | None = None,
        decoder: ResponseDecoder | None = None,
        middleware: Sequence[Middleware] = (),
    ) -> None:
        if httpx2_client is not None:
            forwarded = {
                "base_url": base_url,
                "headers": headers,
                "params": params,
                "cookies": cookies,
                "timeout": timeout,
                "limits": limits,
                "auth": auth,
            }
            if any(value not in (None, "") for value in forwarded.values()):
                raise TypeError(_HTTPX2_CLIENT_CONFLICT_MESSAGE)
            self._httpx2_client = httpx2_client
            self._owns_client = False
        else:
            kwargs: dict[str, typing.Any] = {}
            if base_url:
                kwargs["base_url"] = base_url
            if headers is not None:
                kwargs["headers"] = headers
            if params is not None:
                kwargs["params"] = params
            if cookies is not None:
                kwargs["cookies"] = cookies
            if timeout is not None:
                kwargs["timeout"] = timeout
            if limits is not None:
                kwargs["limits"] = limits
            if auth is not None:
                kwargs["auth"] = auth
            self._httpx2_client = httpx2.AsyncClient(**kwargs)
            self._owns_client = True

        self._decoder = decoder if decoder is not None else PydanticDecoder()
        self._user_middleware = tuple(middleware)
        self._dispatch = compose(self._user_middleware, self._terminal)

    async def _terminal(self, request: httpx2.Request) -> httpx2.Response:
        try:
            response = await self._httpx2_client.send(request)
        except httpx2.TimeoutException as exc:
            raise TimeoutError(str(exc)) from exc
        except (httpx2.InvalidURL, httpx2.CookieConflict) as exc:
            raise TransportError(str(exc)) from exc
        except httpx2.HTTPError as exc:
            raise TransportError(str(exc)) from exc
        except RuntimeError as exc:
            if "closed" in str(exc):
                raise TransportError(str(exc)) from exc
            raise
        status = response.status_code
        if 400 <= status < 600:  # noqa: PLR2004
            exc_class = STATUS_TO_EXCEPTION.get(
                status,
                ClientStatusError if status < 500 else ServerStatusError,  # noqa: PLR2004
            )
            raise exc_class(response)
        return response
```

- [ ] **Step 2: Wire AsyncClient into the public package**

Replace `src/httpware/__init__.py` with:
```python
"""httpware — thin async HTTP client wrapper over httpx2."""

from httpware.client import AsyncClient
from httpware.decoders import ResponseDecoder
from httpware.decoders.pydantic import PydanticDecoder
from httpware.errors import (
    STATUS_TO_EXCEPTION,
    BadRequestError,
    ClientError,
    ClientStatusError,
    ConflictError,
    ForbiddenError,
    InternalServerError,
    NotFoundError,
    RateLimitedError,
    ServerStatusError,
    ServiceUnavailableError,
    StatusError,
    TimeoutError,  # noqa: A004
    TransportError,
    UnauthorizedError,
    UnprocessableEntityError,
)
from httpware.middleware import Middleware, Next, after_response, before_request, on_error


__all__ = [
    "STATUS_TO_EXCEPTION",
    "AsyncClient",
    "BadRequestError",
    "ClientError",
    "ClientStatusError",
    "ConflictError",
    "ForbiddenError",
    "InternalServerError",
    "Middleware",
    "Next",
    "NotFoundError",
    "PydanticDecoder",
    "RateLimitedError",
    "ResponseDecoder",
    "ServerStatusError",
    "ServiceUnavailableError",
    "StatusError",
    "TimeoutError",
    "TransportError",
    "UnauthorizedError",
    "UnprocessableEntityError",
    "after_response",
    "before_request",
    "on_error",
]
```

- [ ] **Step 3: Run the construction tests**

Run:
```bash
just test tests/test_client_construction.py 2>&1 | tail -10
```
Expected: all tests pass.

- [ ] **Step 4: Lint**

Run:
```bash
just lint 2>&1 | tail -10
```
Expected: zero issues.

- [ ] **Step 5: Commit**

Run:
```bash
git add src/httpware/client.py src/httpware/__init__.py tests/test_client_construction.py
git commit -m "feat(client): AsyncClient construction and ownership semantics"
```

---

## Task 9: AsyncClient — failing tests for `send()` and the terminal error path

**Files:**
- Create: `tests/test_error_mapping_terminal.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_error_mapping_terminal.py`:
```python
"""Tests for the AsyncClient internal terminal's exception mapping."""

import httpx2
import pytest

from httpware import (
    AsyncClient,
    BadRequestError,
    InternalServerError,
    NotFoundError,
    RateLimitedError,
    ServerStatusError,
    TimeoutError,  # noqa: A004
    TransportError,
)


def _client_with_handler(handler) -> AsyncClient:  # noqa: ANN001
    transport = httpx2.MockTransport(handler)
    return AsyncClient(httpx2_client=httpx2.AsyncClient(transport=transport))


async def test_terminal_returns_response_on_2xx() -> None:
    client = _client_with_handler(lambda req: httpx2.Response(200, json={"ok": True}, request=req))
    response = await client.send(httpx2.Request("GET", "https://example.test/x"))
    assert response.status_code == 200
    assert response.json() == {"ok": True}


@pytest.mark.parametrize(
    ("status", "exc_type"),
    [
        (400, BadRequestError),
        (404, NotFoundError),
        (429, RateLimitedError),
        (500, InternalServerError),
    ],
)
async def test_known_status_codes_raise_typed_subclass(status: int, exc_type: type) -> None:
    client = _client_with_handler(lambda req: httpx2.Response(status, request=req))
    with pytest.raises(exc_type) as info:
        await client.send(httpx2.Request("GET", "https://example.test/x"))
    assert info.value.response.status_code == status


async def test_unknown_4xx_falls_back_to_client_status_error() -> None:
    from httpware import ClientStatusError

    client = _client_with_handler(lambda req: httpx2.Response(418, request=req))
    with pytest.raises(ClientStatusError) as info:
        await client.send(httpx2.Request("GET", "https://example.test/x"))
    assert info.value.response.status_code == 418
    assert type(info.value) is ClientStatusError


async def test_unknown_5xx_falls_back_to_server_status_error() -> None:
    client = _client_with_handler(lambda req: httpx2.Response(599, request=req))
    with pytest.raises(ServerStatusError) as info:
        await client.send(httpx2.Request("GET", "https://example.test/x"))
    assert info.value.response.status_code == 599
    assert type(info.value) is ServerStatusError


async def test_3xx_does_not_raise() -> None:
    client = _client_with_handler(lambda req: httpx2.Response(301, request=req, headers={"location": "/y"}))
    response = await client.send(httpx2.Request("GET", "https://example.test/x"))
    assert response.status_code == 301


async def test_httpx2_timeout_maps_to_httpware_timeout() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        msg = "read timeout"
        raise httpx2.ReadTimeout(msg)

    client = _client_with_handler(handler)
    with pytest.raises(TimeoutError, match="read timeout"):
        await client.send(httpx2.Request("GET", "https://example.test/x"))


async def test_httpx2_connect_error_maps_to_transport_error() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        msg = "connect refused"
        raise httpx2.ConnectError(msg)

    client = _client_with_handler(handler)
    with pytest.raises(TransportError, match="connect refused"):
        await client.send(httpx2.Request("GET", "https://example.test/x"))


async def test_send_on_closed_client_raises_transport_error() -> None:
    transport = httpx2.MockTransport(lambda req: httpx2.Response(200, request=req))
    underlying = httpx2.AsyncClient(transport=transport)
    client = AsyncClient(httpx2_client=underlying)
    await underlying.aclose()
    with pytest.raises(TransportError):
        await client.send(httpx2.Request("GET", "https://example.test/x"))
```

- [ ] **Step 2: Run the failing tests**

Run:
```bash
just test tests/test_error_mapping_terminal.py 2>&1 | tail -15
```
Expected: failures — `AsyncClient.send` doesn't exist yet.

---

## Task 10: AsyncClient — `send()` implementation

**Files:**
- Modify: `src/httpware/client.py`

- [ ] **Step 1: Add `send()` and `build_request()` to the existing `AsyncClient`**

Append the following methods to the `AsyncClient` class in `src/httpware/client.py` (insert immediately after `_terminal`):

```python
    @typing.overload
    async def send(self, request: httpx2.Request, *, response_model: None = None) -> httpx2.Response: ...

    @typing.overload
    async def send(self, request: httpx2.Request, *, response_model: type[T]) -> T: ...

    async def send(
        self,
        request: httpx2.Request,
        *,
        response_model: type[T] | None = None,
    ) -> httpx2.Response | T:
        """Send `request` through the middleware chain. Decode if `response_model` is set."""
        response = await self._dispatch(request)
        if response_model is None:
            return response
        return self._decoder.decode(response.content, response_model)

    def build_request(self, method: str, url: str, **kwargs: typing.Any) -> httpx2.Request:
        """Delegate request construction to the wrapped httpx2.AsyncClient."""
        return self._httpx2_client.build_request(method, url, **kwargs)
```

- [ ] **Step 2: Run the terminal-error-mapping tests**

Run:
```bash
just test tests/test_error_mapping_terminal.py 2>&1 | tail -10
```
Expected: all tests pass.

- [ ] **Step 3: Lint**

Run:
```bash
just lint 2>&1 | tail -10
```
Expected: zero issues. If `ty` complains about the `**kwargs: typing.Any` shape, adjust the kwargs annotation as ruff/ty advise — `httpx2.AsyncClient.build_request` is the upstream type oracle.

- [ ] **Step 4: Commit**

Run:
```bash
git add src/httpware/client.py tests/test_error_mapping_terminal.py
git commit -m "feat(client): send() + build_request(), terminal error mapping"
```

---

## Task 11: Per-method surface — failing tests

**Files:**
- Create: `tests/test_client_methods.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_client_methods.py`:
```python
"""Tests for the per-method API surface of AsyncClient."""

import httpx2
import pytest

from httpware import AsyncClient, NotFoundError


def _echo_handler(request: httpx2.Request) -> httpx2.Response:
    return httpx2.Response(
        200,
        request=request,
        json={
            "method": request.method,
            "url": str(request.url),
            "headers": dict(request.headers),
            "content": request.content.decode() if request.content else "",
        },
    )


def _client_with_handler(handler, **kwargs) -> AsyncClient:  # noqa: ANN001, ANN003
    transport = httpx2.MockTransport(handler)
    return AsyncClient(httpx2_client=httpx2.AsyncClient(transport=transport, **kwargs))


async def test_get_returns_httpx2_response() -> None:
    client = _client_with_handler(_echo_handler)
    response = await client.get("https://example.test/x")
    assert isinstance(response, httpx2.Response)
    assert response.json()["method"] == "GET"


@pytest.mark.parametrize(
    "method_name",
    ["get", "post", "put", "patch", "delete", "head", "options"],
)
async def test_each_per_method_helper_exists_and_uses_correct_verb(method_name: str) -> None:
    client = _client_with_handler(_echo_handler)
    method = getattr(client, method_name)
    response = await method("https://example.test/x")
    assert response.json()["method"] == method_name.upper()


async def test_post_json_body_serialized() -> None:
    client = _client_with_handler(_echo_handler)
    response = await client.post("https://example.test/x", json={"k": "v"})
    payload = response.json()
    assert "application/json" in payload["headers"]["content-type"]
    assert payload["content"] == '{"k": "v"}'


async def test_get_with_params_forwards_query() -> None:
    captured: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured.append(request)
        return httpx2.Response(200, request=request)

    client = _client_with_handler(handler)
    await client.get("https://example.test/x", params={"a": "1"})
    assert "a=1" in str(captured[0].url)


async def test_get_with_headers_merges() -> None:
    captured: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured.append(request)
        return httpx2.Response(200, request=request)

    client = _client_with_handler(handler)
    await client.get("https://example.test/x", headers={"x-trace": "abc"})
    assert captured[0].headers["x-trace"] == "abc"


async def test_get_raises_typed_status_error_on_404() -> None:
    client = _client_with_handler(lambda req: httpx2.Response(404, request=req))
    with pytest.raises(NotFoundError):
        await client.get("https://example.test/missing")


async def test_request_method_takes_arbitrary_verb() -> None:
    client = _client_with_handler(_echo_handler)
    response = await client.request("PROPFIND", "https://example.test/x")
    assert response.json()["method"] == "PROPFIND"


async def test_base_url_is_applied() -> None:
    captured: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured.append(request)
        return httpx2.Response(200, request=request)

    transport = httpx2.MockTransport(handler)
    underlying = httpx2.AsyncClient(transport=transport, base_url="https://example.test")
    client = AsyncClient(httpx2_client=underlying)
    await client.get("/relative")
    assert str(captured[0].url) == "https://example.test/relative"
```

- [ ] **Step 2: Run the failing tests**

Run:
```bash
just test tests/test_client_methods.py 2>&1 | tail -15
```
Expected: failures — per-method helpers don't exist yet.

---

## Task 12: Per-method surface — implementation

**Files:**
- Modify: `src/httpware/client.py`

- [ ] **Step 1: Add per-method helpers**

Append the following block to the `AsyncClient` class in `src/httpware/client.py`, immediately after `build_request`. Each method has two overloads + the runtime body. To keep this task tractable, the methods share a private helper:

```python
    async def _request_with_body(
        self,
        method: str,
        url: str,
        *,
        params: typing.Any | None = None,
        headers: typing.Any | None = None,
        cookies: typing.Any | None = None,
        timeout: typing.Any = httpx2.USE_CLIENT_DEFAULT,
        extensions: typing.Any | None = None,
        json: typing.Any | None = None,
        content: typing.Any | None = None,
        data: typing.Any | None = None,
        files: typing.Any | None = None,
        response_model: type[T] | None = None,
    ) -> httpx2.Response | T:
        kwargs: dict[str, typing.Any] = {}
        if params is not None:
            kwargs["params"] = params
        if headers is not None:
            kwargs["headers"] = headers
        if cookies is not None:
            kwargs["cookies"] = cookies
        if timeout is not httpx2.USE_CLIENT_DEFAULT:
            kwargs["timeout"] = timeout
        if extensions is not None:
            kwargs["extensions"] = extensions
        if json is not None:
            kwargs["json"] = json
        if content is not None:
            kwargs["content"] = content
        if data is not None:
            kwargs["data"] = data
        if files is not None:
            kwargs["files"] = files
        request = self._httpx2_client.build_request(method, url, **kwargs)
        return await self.send(request, response_model=response_model)
```

Then add the eight per-method helpers. Pattern (full code shown for `get`, `post`; identical shape for `put`, `patch`, `delete`, `head`, `options`):

```python
    @typing.overload
    async def get(
        self,
        url: str,
        *,
        params: typing.Any | None = None,
        headers: typing.Any | None = None,
        cookies: typing.Any | None = None,
        timeout: typing.Any = httpx2.USE_CLIENT_DEFAULT,
        extensions: typing.Any | None = None,
        response_model: None = None,
    ) -> httpx2.Response: ...

    @typing.overload
    async def get(
        self,
        url: str,
        *,
        params: typing.Any | None = None,
        headers: typing.Any | None = None,
        cookies: typing.Any | None = None,
        timeout: typing.Any = httpx2.USE_CLIENT_DEFAULT,
        extensions: typing.Any | None = None,
        response_model: type[T],
    ) -> T: ...

    async def get(
        self,
        url: str,
        *,
        params: typing.Any | None = None,
        headers: typing.Any | None = None,
        cookies: typing.Any | None = None,
        timeout: typing.Any = httpx2.USE_CLIENT_DEFAULT,
        extensions: typing.Any | None = None,
        response_model: type[T] | None = None,
    ) -> httpx2.Response | T:
        """Send a GET request."""
        return await self._request_with_body(
            "GET",
            url,
            params=params,
            headers=headers,
            cookies=cookies,
            timeout=timeout,
            extensions=extensions,
            response_model=response_model,
        )

    @typing.overload
    async def post(
        self,
        url: str,
        *,
        params: typing.Any | None = None,
        headers: typing.Any | None = None,
        cookies: typing.Any | None = None,
        timeout: typing.Any = httpx2.USE_CLIENT_DEFAULT,
        extensions: typing.Any | None = None,
        json: typing.Any | None = None,
        content: typing.Any | None = None,
        data: typing.Any | None = None,
        files: typing.Any | None = None,
        response_model: None = None,
    ) -> httpx2.Response: ...

    @typing.overload
    async def post(
        self,
        url: str,
        *,
        params: typing.Any | None = None,
        headers: typing.Any | None = None,
        cookies: typing.Any | None = None,
        timeout: typing.Any = httpx2.USE_CLIENT_DEFAULT,
        extensions: typing.Any | None = None,
        json: typing.Any | None = None,
        content: typing.Any | None = None,
        data: typing.Any | None = None,
        files: typing.Any | None = None,
        response_model: type[T],
    ) -> T: ...

    async def post(
        self,
        url: str,
        *,
        params: typing.Any | None = None,
        headers: typing.Any | None = None,
        cookies: typing.Any | None = None,
        timeout: typing.Any = httpx2.USE_CLIENT_DEFAULT,
        extensions: typing.Any | None = None,
        json: typing.Any | None = None,
        content: typing.Any | None = None,
        data: typing.Any | None = None,
        files: typing.Any | None = None,
        response_model: type[T] | None = None,
    ) -> httpx2.Response | T:
        """Send a POST request."""
        return await self._request_with_body(
            "POST",
            url,
            params=params,
            headers=headers,
            cookies=cookies,
            timeout=timeout,
            extensions=extensions,
            json=json,
            content=content,
            data=data,
            files=files,
            response_model=response_model,
        )
```

Repeat the `post` shape for `put` (`"PUT"`), `patch` (`"PATCH"`), and `delete` (`"DELETE"`). For `head`, `options`, copy the `get` shape (no body kwargs).

Add `request` (arbitrary verb) using the post-shape with an explicit `method` first parameter:

```python
    @typing.overload
    async def request(
        self,
        method: str,
        url: str,
        *,
        params: typing.Any | None = None,
        headers: typing.Any | None = None,
        cookies: typing.Any | None = None,
        timeout: typing.Any = httpx2.USE_CLIENT_DEFAULT,
        extensions: typing.Any | None = None,
        json: typing.Any | None = None,
        content: typing.Any | None = None,
        data: typing.Any | None = None,
        files: typing.Any | None = None,
        response_model: None = None,
    ) -> httpx2.Response: ...

    @typing.overload
    async def request(
        self,
        method: str,
        url: str,
        *,
        params: typing.Any | None = None,
        headers: typing.Any | None = None,
        cookies: typing.Any | None = None,
        timeout: typing.Any = httpx2.USE_CLIENT_DEFAULT,
        extensions: typing.Any | None = None,
        json: typing.Any | None = None,
        content: typing.Any | None = None,
        data: typing.Any | None = None,
        files: typing.Any | None = None,
        response_model: type[T],
    ) -> T: ...

    async def request(
        self,
        method: str,
        url: str,
        *,
        params: typing.Any | None = None,
        headers: typing.Any | None = None,
        cookies: typing.Any | None = None,
        timeout: typing.Any = httpx2.USE_CLIENT_DEFAULT,
        extensions: typing.Any | None = None,
        json: typing.Any | None = None,
        content: typing.Any | None = None,
        data: typing.Any | None = None,
        files: typing.Any | None = None,
        response_model: type[T] | None = None,
    ) -> httpx2.Response | T:
        """Send a request with an arbitrary HTTP method."""
        return await self._request_with_body(
            method,
            url,
            params=params,
            headers=headers,
            cookies=cookies,
            timeout=timeout,
            extensions=extensions,
            json=json,
            content=content,
            data=data,
            files=files,
            response_model=response_model,
        )
```

- [ ] **Step 2: Run per-method tests**

Run:
```bash
just test tests/test_client_methods.py 2>&1 | tail -10
```
Expected: all pass.

- [ ] **Step 3: Lint**

Run:
```bash
just lint 2>&1 | tail -10
```
Expected: zero issues. `pylint.max-args = 10` is already set in `pyproject.toml`. The per-file `ASYNC109` ignore for `src/httpware/client.py` is already declared.

- [ ] **Step 4: Commit**

Run:
```bash
git add src/httpware/client.py tests/test_client_methods.py
git commit -m "feat(client): per-method API surface (get/post/put/patch/delete/head/options/request)"
```

---

## Task 13: Response-model decoding — failing tests

**Files:**
- Create: `tests/test_client_response_model.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_client_response_model.py`:
```python
"""Tests for response_model decoding integration."""

import httpx2
import pydantic
import pytest

from httpware import AsyncClient


class _User(pydantic.BaseModel):
    id: int
    name: str


def _client_with_payload(payload: bytes, content_type: str = "application/json") -> AsyncClient:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, content=payload, headers={"content-type": content_type}, request=request)

    transport = httpx2.MockTransport(handler)
    return AsyncClient(httpx2_client=httpx2.AsyncClient(transport=transport))


async def test_get_with_response_model_returns_typed_object() -> None:
    client = _client_with_payload(b'{"id": 1, "name": "ada"}')
    user = await client.get("https://example.test/u", response_model=_User)
    assert isinstance(user, _User)
    assert user == _User(id=1, name="ada")


async def test_post_with_response_model_returns_typed_object() -> None:
    client = _client_with_payload(b'{"id": 2, "name": "bob"}')
    user = await client.post("https://example.test/u", json={"name": "bob"}, response_model=_User)
    assert isinstance(user, _User)


async def test_send_with_response_model_returns_typed_object() -> None:
    client = _client_with_payload(b'{"id": 3, "name": "cat"}')
    request = client.build_request("GET", "https://example.test/u")
    user = await client.send(request, response_model=_User)
    assert isinstance(user, _User)


async def test_decoder_validation_error_propagates_unwrapped() -> None:
    client = _client_with_payload(b'{"id": "not-an-int", "name": "x"}')
    with pytest.raises(pydantic.ValidationError):
        await client.get("https://example.test/u", response_model=_User)


async def test_status_error_raised_before_decoder_runs() -> None:
    from httpware import NotFoundError

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(404, content=b'{"id": 1, "name": "x"}', request=request)

    transport = httpx2.MockTransport(handler)
    client = AsyncClient(httpx2_client=httpx2.AsyncClient(transport=transport))
    with pytest.raises(NotFoundError):
        await client.get("https://example.test/u", response_model=_User)
```

- [ ] **Step 2: Run the tests**

Run:
```bash
just test tests/test_client_response_model.py 2>&1 | tail -10
```
Expected: all tests pass — the decoder path was wired in Task 10, the per-method path in Task 12.

- [ ] **Step 3: Commit**

Run:
```bash
git add tests/test_client_response_model.py
git commit -m "test(client): response_model decoding across get/post/send paths"
```

---

## Task 14: Middleware wiring — tests

**Files:**
- Create: `tests/test_client_middleware_wiring.py`

- [ ] **Step 1: Write the tests**

Create `tests/test_client_middleware_wiring.py`:
```python
"""Tests for AsyncClient ↔ middleware chain integration."""

import httpx2

from httpware import AsyncClient, after_response, before_request, on_error


async def test_before_request_runs() -> None:
    @before_request
    async def add_header(request: httpx2.Request) -> httpx2.Request:
        return httpx2.Request(
            request.method,
            request.url,
            headers={**request.headers, "x-injected": "1"},
        )

    captured: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured.append(request)
        return httpx2.Response(200, request=request)

    transport = httpx2.MockTransport(handler)
    client = AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=transport),
        middleware=(add_header,),
    )
    await client.get("https://example.test/x")
    assert captured[0].headers["x-injected"] == "1"


async def test_after_response_runs() -> None:
    @after_response
    async def tag_status(request: httpx2.Request, response: httpx2.Response) -> httpx2.Response:
        return httpx2.Response(
            299, request=request, headers=response.headers, content=response.content
        )

    transport = httpx2.MockTransport(lambda req: httpx2.Response(200, request=req))
    client = AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=transport),
        middleware=(tag_status,),
    )
    response = await client.get("https://example.test/x")
    assert response.status_code == 299


async def test_on_error_catches_status_error() -> None:
    @on_error
    async def convert_404(request: httpx2.Request, exc: Exception) -> httpx2.Response | None:
        from httpware import NotFoundError

        if isinstance(exc, NotFoundError):
            return httpx2.Response(200, request=request, content=b"recovered")
        return None

    transport = httpx2.MockTransport(lambda req: httpx2.Response(404, request=req))
    client = AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=transport),
        middleware=(convert_404,),
    )
    response = await client.get("https://example.test/x")
    assert response.status_code == 200
    assert response.content == b"recovered"


async def test_middleware_runs_outer_to_inner_then_inner_to_outer() -> None:
    order: list[str] = []

    class _Tag:
        def __init__(self, name: str) -> None:
            self.name = name

        async def __call__(self, request, next):  # noqa: A002, ANN001
            order.append(f"{self.name}.in")
            response = await next(request)
            order.append(f"{self.name}.out")
            return response

    transport = httpx2.MockTransport(lambda req: httpx2.Response(200, request=req))
    client = AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=transport),
        middleware=(_Tag("a"), _Tag("b")),
    )
    await client.get("https://example.test/x")
    assert order == ["a.in", "b.in", "b.out", "a.out"]
```

- [ ] **Step 2: Run the tests**

Run:
```bash
just test tests/test_client_middleware_wiring.py 2>&1 | tail -10
```
Expected: all tests pass.

- [ ] **Step 3: Commit**

Run:
```bash
git add tests/test_client_middleware_wiring.py
git commit -m "test(client): middleware chain runs around the terminal"
```

---

## Task 15: Lifecycle — tests and `__aenter__`/`__aexit__`

**Files:**
- Create: `tests/test_client_lifecycle.py`
- Modify: `src/httpware/client.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_client_lifecycle.py`:
```python
"""Tests for AsyncClient.__aenter__/__aexit__ lifecycle and ownership."""

import httpx2

from httpware import AsyncClient


async def test_aexit_closes_owned_httpx2_client() -> None:
    client = AsyncClient()
    async with client:
        pass
    assert client._httpx2_client.is_closed  # noqa: SLF001


async def test_aexit_does_not_close_borrowed_httpx2_client() -> None:
    transport = httpx2.MockTransport(lambda req: httpx2.Response(200, request=req))
    underlying = httpx2.AsyncClient(transport=transport)
    client = AsyncClient(httpx2_client=underlying)
    async with client:
        pass
    assert not underlying.is_closed
    await underlying.aclose()


async def test_aexit_is_idempotent_for_owned_client() -> None:
    client = AsyncClient()
    async with client:
        pass
    # Second use should not raise — the boolean prevents a double-close on httpx2 internals.
    await client.__aexit__(None, None, None)
```

- [ ] **Step 2: Run them to confirm failure**

Run:
```bash
just test tests/test_client_lifecycle.py 2>&1 | tail -10
```
Expected: failures — `__aenter__`/`__aexit__` don't exist yet.

- [ ] **Step 3: Add lifecycle methods to AsyncClient**

Append these two methods to the `AsyncClient` class in `src/httpware/client.py`:

```python
    async def __aenter__(self) -> typing.Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object,
    ) -> None:
        if self._owns_client and not self._httpx2_client.is_closed:
            await self._httpx2_client.aclose()
```

- [ ] **Step 4: Run lifecycle tests**

Run:
```bash
just test tests/test_client_lifecycle.py 2>&1 | tail -10
```
Expected: all tests pass.

- [ ] **Step 5: Commit**

Run:
```bash
git add src/httpware/client.py tests/test_client_lifecycle.py
git commit -m "feat(client): __aenter__/__aexit__ honors owned vs. borrowed httpx2 client"
```

---

## Task 16: Typing overloads — tests

**Files:**
- Create: `tests/test_client_typing.py`

- [ ] **Step 1: Write the typing tests**

Create `tests/test_client_typing.py`:
```python
"""Static-typing tests for AsyncClient overloads.

These assert overload selection at runtime via isinstance checks. ty/mypy
catches the static-typing variant during `just lint`.
"""

import httpx2
import pydantic

from httpware import AsyncClient


class _User(pydantic.BaseModel):
    id: int
    name: str


async def test_get_without_response_model_returns_response() -> None:
    transport = httpx2.MockTransport(lambda req: httpx2.Response(200, request=req, json={"id": 1, "name": "a"}))
    client = AsyncClient(httpx2_client=httpx2.AsyncClient(transport=transport))
    result = await client.get("https://example.test/x")
    assert isinstance(result, httpx2.Response)


async def test_get_with_response_model_returns_typed() -> None:
    transport = httpx2.MockTransport(lambda req: httpx2.Response(200, request=req, json={"id": 1, "name": "a"}))
    client = AsyncClient(httpx2_client=httpx2.AsyncClient(transport=transport))
    result = await client.get("https://example.test/x", response_model=_User)
    assert isinstance(result, _User)


async def test_send_without_response_model_returns_response() -> None:
    transport = httpx2.MockTransport(lambda req: httpx2.Response(200, request=req, json={"id": 1, "name": "a"}))
    client = AsyncClient(httpx2_client=httpx2.AsyncClient(transport=transport))
    result = await client.send(httpx2.Request("GET", "https://example.test/x"))
    assert isinstance(result, httpx2.Response)


async def test_send_with_response_model_returns_typed() -> None:
    transport = httpx2.MockTransport(lambda req: httpx2.Response(200, request=req, json={"id": 1, "name": "a"}))
    client = AsyncClient(httpx2_client=httpx2.AsyncClient(transport=transport))
    result = await client.send(httpx2.Request("GET", "https://example.test/x"), response_model=_User)
    assert isinstance(result, _User)
```

- [ ] **Step 2: Run them and lint**

Run:
```bash
just test tests/test_client_typing.py
just lint
```
Expected: tests pass; `ty check` reports zero issues.

- [ ] **Step 3: Commit**

Run:
```bash
git add tests/test_client_typing.py
git commit -m "test(client): overload selection of response_model for get/send"
```

---

## Task 17: Public-API surface test

**Files:**
- Create: `tests/test_public_api.py`

- [ ] **Step 1: Write the public-API test**

Create `tests/test_public_api.py`:
```python
"""Public API surface — what `from httpware import ...` exposes."""

import httpware


def test_all_exports_resolve() -> None:
    for symbol in httpware.__all__:
        assert hasattr(httpware, symbol), f"{symbol} declared in __all__ but missing"


def test_no_removed_symbols_leaked() -> None:
    removed = {
        "Request",
        "Response",
        "StreamResponse",
        "Timeout",
        "Limits",
        "ClientConfig",
        "Transport",
        "Httpx2Transport",
        "RecordedTransport",
        "AuthValue",
    }
    leaked = removed & set(dir(httpware))
    assert not leaked, f"removed 0.1 symbols still exposed: {leaked}"


def test_expected_exports() -> None:
    expected = {
        "AsyncClient",
        "Middleware",
        "Next",
        "ResponseDecoder",
        "PydanticDecoder",
        "ClientError",
        "TransportError",
        "TimeoutError",
        "StatusError",
        "ClientStatusError",
        "ServerStatusError",
        "BadRequestError",
        "UnauthorizedError",
        "ForbiddenError",
        "NotFoundError",
        "ConflictError",
        "UnprocessableEntityError",
        "RateLimitedError",
        "InternalServerError",
        "ServiceUnavailableError",
        "STATUS_TO_EXCEPTION",
        "before_request",
        "after_response",
        "on_error",
    }
    missing = expected - set(httpware.__all__)
    assert not missing, f"expected exports missing from __all__: {missing}"
```

- [ ] **Step 2: Run it**

Run:
```bash
just test tests/test_public_api.py
```
Expected: all tests pass. If `test_no_removed_symbols_leaked` fails, an export survived the tear-down; trace and remove from `__init__.py`.

- [ ] **Step 3: Commit**

Run:
```bash
git add tests/test_public_api.py
git commit -m "test(public-api): assert v0.2 surface + no leaked 0.1 names"
```

---

## Task 18: Full test suite + coverage gate

**Files:**
- All tests.

- [ ] **Step 1: Run the full suite with coverage**

Run:
```bash
just test 2>&1 | tail -30
```
Expected: every test passes; line coverage at 100% on `src/httpware/`. Note the new total count.

- [ ] **Step 2: Lint, format, type-check**

Run:
```bash
just lint 2>&1 | tail -15
```
Expected: zero issues across all linters.

- [ ] **Step 3: Run `import httpware` in a clean subprocess and confirm no `msgspec` leak**

Run:
```bash
just test tests/test_optional_extras_isolation.py 2>&1 | tail -5
```
Expected: pass.

- [ ] **Step 4: If coverage gaps appear, add a tiny targeted test for each uncovered branch**

This is a per-line-coverage spot fix. Most gaps will be in the `_terminal` error branches; add a parametrized test in `tests/test_error_mapping_terminal.py` for whichever specific `httpx2` exception subclass is uncovered.

- [ ] **Step 5: Commit (only if step 4 produced changes)**

Run:
```bash
git add tests/
git commit -m "test(coverage): close remaining branch gaps in terminal error mapping"
```

---

## Task 19: Rewrite `CLAUDE.md`

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update the architecture-invariants section**

Open `CLAUDE.md`. In the "Architecture invariants (CI-enforced)" section, **delete** the two bullets:

- `- **No httpx2 leakage**: ...`
- `- **No httpx2 private API**: ...`

Replace with a single bullet:

```markdown
- **No `httpx2` private API**: `grep -rE 'httpx2\._' src/httpware/` must return zero matches. Public symbols only.
```

In the "Module layout" section, **replace** the diagram with:

```text
src/httpware/
├── __init__.py                    # public exports + __all__
├── client.py                      # AsyncClient (thin wrapper over httpx2.AsyncClient)
├── errors.py                      # status-keyed exception hierarchy holding httpx2.Response
├── middleware/                    # protocol, Next type, chain composition, phase decorators
├── decoders/                      # ResponseDecoder protocol + Pydantic/msgspec adapters
├── _internal/                     # private cross-module helpers
└── py.typed
```

In the "Protocol seams" section, **replace** the five-seam list with three:

```markdown
Three documented internal boundaries. AI agents must respect them — never cross a seam except through its documented protocol.

1. **`AsyncClient ↔ Middleware`** — middleware chain composed at `AsyncClient.__init__`, frozen for the client's lifetime. Internal terminal calls `httpx2.AsyncClient.send`, maps exceptions, raises `StatusError` on 4xx/5xx.
2. **`AsyncClient ↔ ResponseDecoder`** — called when `response_model` is provided. Signature: `decode(content: bytes, model: type[T]) -> T`.
3. **`httpware ↔ optional extras`** — each opt-in dependency imported only inside its dedicated module.
```

- [ ] **Step 2: Update project-overview text**

In the "Project Overview" section, **replace** "The framework owns the abstraction layer above the underlying HTTP client (`httpx2` by default); consumers never import the transport." with "The framework is a thin opinionated wrapper around `httpx2`: it re-exports `httpx2.Request`/`httpx2.Response`, adds a middleware chain, typed response decoding, and a status-keyed exception tree raised automatically on 4xx/5xx."

- [ ] **Step 3: Confirm the file lints**

Run:
```bash
just lint 2>&1 | tail -5
```
Expected: zero issues (CLAUDE.md is markdown; ruff doesn't touch it, but `eof-fixer` does — confirm the trailing newline).

- [ ] **Step 4: Commit**

Run:
```bash
git add CLAUDE.md
git commit -m "docs(claude): retire no-leakage invariant; collapse seams to three"
```

---

## Task 20: Rewrite `docs/dev/engineering.md`

**Files:**
- Modify: `docs/dev/engineering.md`

- [ ] **Step 1: Rewrite Section 1 (Project intent)**

Replace section 1 with:

```markdown
## 1. Project intent

`httpware` is a thin opinionated wrapper around `httpx2`. It re-exports `httpx2.Request` and `httpx2.Response` as the public request/response surface and adds three things on top: typed response decoding (via a `ResponseDecoder` protocol; Pydantic ships as the default, msgspec as an opt-in extra), a middleware chain composed at client construction, and a status-keyed exception tree raised automatically on 4xx and 5xx.

The 0.1.0 release attempted to own a full abstraction over the underlying HTTP client. v0.2 walks that back: `httpx2` is part of the public surface.
```

- [ ] **Step 2: Rewrite Section 2 (Architectural invariants)**

Replace section 2 with:

```markdown
## 2. Architectural invariants (CI-enforced)

These are non-negotiable. CI rejects PRs that violate them.

- **No `httpx2._` private API.** *Why:* private symbols can change between patch releases. We accept the public-API surface as the contract.
- **No `from __future__ import annotations`.** *Why:* Python 3.11+ floor; PEP 604/585 syntax is native.
- **No `print()`.** *Why:* ruff-enforced. Libraries log; they do not print.
- **No global logging config.** *Why:* `logging.basicConfig()` from a library mutates the consumer's logging tree. We only acquire `logging.getLogger("httpware")` or namespaced child loggers.
- **Type suppressions use `# ty: ignore[<rule>]`.** *Why:* this project uses `ty`, not `mypy`. `# type: ignore` is silently accepted; `# ty: ignore[<rule>]` is checked and rule-specific.

The 0.1.0 "no `httpx2` leakage outside `transports/httpx2.py`" invariant is **retired in v0.2**. Exposing `httpx2.Request`/`httpx2.Response` is the design.
```

- [ ] **Step 3: Rewrite Section 3 (The five protocol seams) → three seams**

Replace section 3 wholesale with the three-seam content from the spec (sections 4.A, 4.B, 4.C).

- [ ] **Step 4: Rewrite Section 5 (Module layout)**

Replace the layout diagram and "Planned modules" subsection with the layout from spec section 5 (single tree, no "planned modules" — they all land or get deleted in this pivot).

- [ ] **Step 5: Rewrite Section 8 (Remaining roadmap)**

Replace section 8's story list with the updated roadmap from spec section 12 (the four-category breakdown: deleted, rewritten, surviving, plus the explicit story IDs).

- [ ] **Step 6: Confirm formatting and commit**

Run:
```bash
just lint 2>&1 | tail -5
git add docs/dev/engineering.md
git commit -m "docs(engineering): rewrite sections 1, 2, 3, 5, 8 for the v0.2 pivot"
```

---

## Task 21: Sweep `planning/deferred-work.md`

**Files:**
- Modify: `planning/deferred-work.md`

- [ ] **Step 1: Identify and close obsoleted entries**

Replace the contents of `planning/deferred-work.md` with:

```markdown
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
```

- [ ] **Step 2: Lint and commit**

Run:
```bash
just lint 2>&1 | tail -5
git add planning/deferred-work.md
git commit -m "docs(deferred): close items obsoleted by the v0.2 thin-wrapper pivot"
```

---

## Task 22: Version bump and release notes

**Files:**
- Modify: `pyproject.toml`
- Create: `planning/specs/2026-06-03-release-notes-0.2.0.md` (draft of the GitHub Release body)

- [ ] **Step 1: Bump the version**

In `pyproject.toml`, change:

```toml
version = "0"
```

to:

```toml
version = "0.2.0"
```

- [ ] **Step 2: Draft release notes**

Create `planning/specs/2026-06-03-release-notes-0.2.0.md`:

```markdown
# httpware 0.2.0 — thin httpx2 wrapper

**0.2.0 is a breaking rewrite.** The framework is now a thin opinionated wrapper around `httpx2`: it re-exports `httpx2.Request`/`httpx2.Response`, adds a middleware chain, typed response decoding, and a status-keyed exception tree raised automatically on 4xx/5xx.

## Breaking changes from 0.1.0

- **Removed value types.** `httpware.Request`, `httpware.Response`, `httpware.StreamResponse`, `httpware.Limits`, `httpware.Timeout`, and `httpware.ClientConfig` are gone. Use `httpx2.Request`, `httpx2.Response`, `httpx2.Limits`, `httpx2.Timeout` directly.
- **Removed transport abstraction.** `httpware.Transport`, `httpware.Httpx2Transport`, and `httpware.RecordedTransport` are gone. Tests should inject `httpx2.MockTransport` via the new `httpx2_client=` kwarg.
- **Removed auth coercion.** Pass `httpx2.Auth` (e.g., `httpx2.BasicAuth`) directly to the client.
- **`with_options` removed.** Construct a separate `AsyncClient` wrapping a shared `httpx2.AsyncClient` instead.
- **`StatusError` simplified.** Subclasses no longer accept `status` / `body` / `headers` / `json` / `request_method` / `request_url` kwargs. Construct with a single `response: httpx2.Response` argument and read fields from `exc.response.*`.
- **CI invariant retired.** The "no `httpx2` imports outside `transports/httpx2.py`" rule is gone. `httpx2` is part of the public surface.

## What still works

- `AsyncClient.get/post/put/patch/delete/head/options/request` with `response_model=...` for typed decoding.
- `PydanticDecoder` (default) and `MsgspecDecoder` (opt-in via `pip install httpware[msgspec]`).
- Middleware protocol with `@before_request`, `@after_response`, `@on_error` decorators.
- Status-keyed exception tree (`NotFoundError`, `RateLimitedError`, etc.) raised automatically on 4xx/5xx.

## Migration

```python
# Before (0.1.0)
import httpware

async with httpware.AsyncClient(base_url="https://api.example.com", auth="my-token") as client:
    user = await client.get("/users/1", response_model=User)
```

```python
# After (0.2.0)
import httpx2
import httpware

async with httpware.AsyncClient(
    base_url="https://api.example.com",
    headers={"Authorization": "Bearer my-token"},
) as client:
    user = await client.get("/users/1", response_model=User)
```

## What's next

Epic 3 (resilience middleware — retry, timeout, bulkhead) and Epic 5 (observability) ship in subsequent minor releases. See `docs/dev/engineering.md` section 8 for the post-pivot roadmap.
```

- [ ] **Step 3: Confirm `just lint-ci` and `just test` still pass**

Run:
```bash
just lint-ci 2>&1 | tail -5
just test 2>&1 | tail -10
```
Expected: clean.

- [ ] **Step 4: Commit**

Run:
```bash
git add pyproject.toml planning/specs/2026-06-03-release-notes-0.2.0.md
git commit -m "chore(release): bump version to 0.2.0 and draft release notes"
```

---

## Task 23: Final integration sweep

**Files:**
- All.

- [ ] **Step 1: Re-read the diff against `main`**

Run:
```bash
git diff main --stat
```
Expected: roughly matches the file-map at the top of this plan — deletions in `transports/`, `_internal/auth.py`, `request.py`, `response.py`, `config.py`, the corresponding tests; rewrites in `client.py`, `errors.py`, `middleware/`, `__init__.py`, the corresponding tests; updates to `CLAUDE.md`, `docs/dev/engineering.md`, `planning/deferred-work.md`, `pyproject.toml`; new release-notes file.

- [ ] **Step 2: Run the perf-marked tests opt-in to confirm no regressions**

Run:
```bash
uv run --no-sync pytest -m perf 2>&1 | tail -10
```
Expected: pass (or skip cleanly).

- [ ] **Step 3: Confirm `import httpware` works in a fresh interpreter**

Run:
```bash
uv run python -c "import httpware; print(sorted(httpware.__all__))"
```
Expected: the v0.2 export list prints, no ImportError, no warnings.

- [ ] **Step 4: Push branch and open PR (manual step)**

Run:
```bash
git push -u origin feat/v0.2-thin-httpx2-wrapper
gh pr create --title "v0.2: thin httpx2 wrapper rewrite" --body "$(cat <<'EOF'
## Summary
- Single structural PR for the v0.2 thin-wrapper pivot per `planning/specs/2026-06-03-thin-httpx2-wrapper-design.md`.
- Removes `Request`/`Response`/`Transport`/`RecordedTransport`/auth coercion/`with_options`.
- Re-exports `httpx2.Request`/`httpx2.Response`; adds `httpx2_client=` injection point.
- Middleware retyped on `httpx2.Request`/`httpx2.Response`; chain composition moved to `middleware/chain.py`.
- `StatusError` subclasses now hold a single `response: httpx2.Response`.
- Five protocol seams collapse to three.
- Closes 12 deferred-work items obsoleted by the pivot.
- Bumps version to `0.2.0`; release notes draft included.

## Test plan
- [ ] `just test` is green at 100% coverage.
- [ ] `just lint-ci` is green.
- [ ] Optional-extras isolation test still passes (`import httpware` doesn't pull `msgspec`).
- [ ] Public-API test asserts no 0.1 names leak.
- [ ] Migration example in release notes verified by inspection.
EOF
)"
```
This is the final manual step. The agent should NOT push or open the PR without explicit user instruction.

---

## Self-review notes (writer to writer)

- **Spec coverage:** Each spec section maps to at least one task. Section 1 → Task 19 + 20 (docs); 3 (invariants) → Task 19 + 20; 4 (seams) → Tasks 5-10 + 19 + 20; 5 (layout) → Task 2 + 19 + 20; 6 (public API) → Tasks 7-16; 7 (middleware) → Tasks 5-6 + 14; 8 (errors) → Tasks 3-4; 9 (data flow) → Tasks 9-14; 10 (error mapping table) → Task 9-10; 11 (testing pattern) → every test task; 12 (roadmap) → Task 20 + 21; 13 (cutover plan) → entire plan; 14 (open questions) → none currently.
- **Placeholder scan:** none of the forbidden phrases ("TBD", "TODO", "implement later", "fill in details", "appropriate error handling") appear in any step.
- **Type consistency:** `AsyncClient._terminal`, `AsyncClient.send`, `AsyncClient.build_request`, `AsyncClient._request_with_body`, `AsyncClient._dispatch`, `AsyncClient._user_middleware`, `AsyncClient._decoder`, `AsyncClient._httpx2_client`, `AsyncClient._owns_client` are all referenced consistently across tasks. `Next` is a `TypeAlias` defined in `middleware/__init__.py`; `_Next` is the private alias in `chain.py` (matching, but not re-exported, to avoid the circular import at `chain.py` import time).
- **Coverage gate:** Task 18 step 4 calls out the spot-fix pattern if line coverage drops below 100%.
- **Decoder default:** the spec footnote about `pydantic` being not-truly-opt-in is reflected in the "Open" section of `deferred-work.md` (Task 21).

# RecordedTransport Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship Story 1-8: a built-in `RecordedTransport` test double at `src/httpware/transports/recorded.py`, then consolidate the five in-tree stubs (`_FakeTransport`, `_OkTransport`, `_FailingTransport`, two `_RecordingTransport` variants, `_TrackingTransport`) by replacing them with `RecordedTransport`. Closes Epic 1.

**Architecture:** Single new module (~50 lines) implementing the `Transport` protocol with a route table, observed-request list, and `aclose_calls` counter. Routes keyed by `(method.upper(), url)` → `Response | BaseException`. Configurable `default` for the no-match case. After the class lands, six existing test files swap their file-local stubs for `RecordedTransport` construction in a single mechanical commit.

**Tech Stack:** Python 3.11 floor; stdlib only (`collections.abc.Mapping`, `contextlib.AbstractAsyncContextManager`). No new dependencies.

**Branch:** `story/1-8-recordedtransport` (already created; spec commit `60d2e0c` is on it).

**Spec:** `docs/superpowers/specs/2026-05-31-recordedtransport-design.md`.

---

## File Structure

**New files:**
- `src/httpware/transports/recorded.py` — `RecordedTransport` class.
- `tests/test_transports_recorded.py` — 15 behavioral tests for the new class.

**Modified files:**
- `src/httpware/__init__.py` — export `RecordedTransport`, add to `__all__`.
- `CHANGELOG.md` — Story 1.8 bullet.
- `tests/test_middleware.py` — replace `_OkTransport` and `_FailingTransport` with `RecordedTransport`.
- `tests/test_client_construction.py` — replace `_FakeTransport` with `RecordedTransport()`.
- `tests/test_client_methods.py` — replace local `_RecordingTransport` with `RecordedTransport`.
- `tests/test_client_response_model.py` — replace local `_RecordingTransport` with `RecordedTransport`.
- `tests/test_client_lifecycle.py` — replace `_TrackingTransport` with `RecordedTransport`.
- `tests/test_client_middleware_wiring.py` — replace local `_RecordingTransport` with `RecordedTransport`.

**Files NOT touched:**
- `pyproject.toml`, `Justfile`, CI workflows.
- `src/httpware/transports/__init__.py` (the `Transport` Protocol stays as-is).
- `src/httpware/transports/httpx2.py`.

---

## Task 1: `RecordedTransport` module with core route-matching tests

TDD cycle for the core behavior: route matching, default handling, exception propagation. Implementation lands once tests are in place.

**Files:**
- Create: `src/httpware/transports/recorded.py`
- Create: `tests/test_transports_recorded.py`

- [ ] **Step 1: Add the first failing test (route match returns response)**

Create `tests/test_transports_recorded.py`:

```python
"""Unit tests for httpware.transports.recorded.RecordedTransport."""

import pytest

from httpware.request import Request
from httpware.response import Response
from httpware.transports import Transport
from httpware.transports.recorded import RecordedTransport


def _response(content: bytes = b"ok") -> Response:
    return Response(status=200, headers={}, content=content, url="/", elapsed=0.0)


def _request(method: str = "GET", url: str = "/foo") -> Request:
    return Request(method=method, url=url)


async def test_route_match_returns_response() -> None:
    canned = _response(b"matched")
    transport = RecordedTransport(routes={("GET", "/foo"): canned})

    result = await transport(_request())

    assert result is canned
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_transports_recorded.py::test_route_match_returns_response -v`
Expected: `ModuleNotFoundError: No module named 'httpware.transports.recorded'`.

- [ ] **Step 3: Implement `RecordedTransport`**

Create `src/httpware/transports/recorded.py`:

```python
"""RecordedTransport — built-in Transport test double."""

from collections.abc import Mapping
from contextlib import AbstractAsyncContextManager

from httpware.request import Request
from httpware.response import Response, StreamResponse


class RecordedTransport:
    """Built-in Transport test double.

    Construct with a route table mapping (method, url) → Response | BaseException.
    `await transport(request)` looks up `(request.method.upper(), request.url)`; on
    match returns the Response or raises the Exception. On no-match, uses the
    `default` (Response, BaseException, or RuntimeError("No route for METHOD URL")
    when None).

    Every call appends the Request to `transport.requests`. Tests can assert on
    `transport.last_request`, iterate `transport.requests`, or count
    `transport.aclose_calls` for lifecycle assertions.

    Routes fire indefinitely — the same (method, url) yields the same canned
    Response on every match. To express "different replies on repeat calls",
    swap the route between calls via `add_route(...)` or construct a new
    transport per call.

    `stream()` raises NotImplementedError; streaming lands in Epic 4 (Story 4-1).
    """

    def __init__(
        self,
        routes: Mapping[tuple[str, str], Response | BaseException] | None = None,
        *,
        default: Response | BaseException | None = None,
    ) -> None:
        self._routes: dict[tuple[str, str], Response | BaseException] = (
            {(m.upper(), u): v for (m, u), v in routes.items()}
            if routes is not None
            else {}
        )
        self._default = default
        self.requests: list[Request] = []
        self.aclose_calls = 0

    @property
    def last_request(self) -> Request | None:
        """The most recently observed Request, or None if no calls have been made."""
        return self.requests[-1] if self.requests else None

    def add_route(
        self,
        method: str,
        url: str,
        response_or_exception: Response | BaseException,
    ) -> None:
        """Add or replace a route entry."""
        self._routes[(method.upper(), url)] = response_or_exception

    async def __call__(self, request: Request) -> Response:
        self.requests.append(request)
        key = (request.method.upper(), request.url)
        result: Response | BaseException | None
        result = self._routes[key] if key in self._routes else self._default
        if isinstance(result, BaseException):
            raise result
        if result is None:
            msg = f"No route for {request.method} {request.url}"
            raise RuntimeError(msg)
        return result

    def stream(
        self,
        request: Request,
    ) -> AbstractAsyncContextManager[StreamResponse]:
        """Streaming not implemented in v0 — landing in Epic 4 (Story 4-1)."""
        msg = "RecordedTransport.stream() is not implemented; streaming lands in Epic 4"
        raise NotImplementedError(msg)

    async def aclose(self) -> None:
        self.aclose_calls += 1
```

No `__all__` (project convention).

- [ ] **Step 4: Run the first test to verify it passes**

Run: `uv run pytest tests/test_transports_recorded.py::test_route_match_returns_response -v`
Expected: PASS.

- [ ] **Step 5: Add the remaining 4 core tests (exception routes, defaults)**

Append to `tests/test_transports_recorded.py`:

```python
async def test_route_match_raises_exception() -> None:
    class _BoomError(Exception):
        pass

    transport = RecordedTransport(routes={("GET", "/fail"): _BoomError("boom")})

    with pytest.raises(_BoomError, match="boom"):
        await transport(_request(url="/fail"))


async def test_no_match_with_no_default_raises_runtime_error() -> None:
    transport = RecordedTransport()

    with pytest.raises(RuntimeError, match=r"No route for GET /missing"):
        await transport(_request(url="/missing"))


async def test_no_match_with_response_default_returns_default() -> None:
    fallback = _response(b"fallback")
    transport = RecordedTransport(default=fallback)

    result = await transport(_request(url="/anything"))

    assert result is fallback


async def test_no_match_with_exception_default_raises_default() -> None:
    transport = RecordedTransport(default=RuntimeError("default boom"))

    with pytest.raises(RuntimeError, match="default boom"):
        await transport(_request(url="/anything"))
```

- [ ] **Step 6: Run tests to verify all 5 pass**

Run: `uv run pytest tests/test_transports_recorded.py -v`
Expected: 5 passed.

- [ ] **Step 7: Lint and ty**

Run: `uv run ruff check src/httpware/transports/recorded.py tests/test_transports_recorded.py`
Run: `uv run ty check src/httpware/transports/recorded.py`
Expected: both clean.

- [ ] **Step 8: Commit**

```bash
git add src/httpware/transports/recorded.py tests/test_transports_recorded.py
git commit -m "$(cat <<'EOF'
feat(story-1.8): RecordedTransport test double with core route matching

Adds src/httpware/transports/recorded.py with RecordedTransport:
- routes: Mapping[(method, url), Response | BaseException] with method
  uppercased on insert
- default: Response | BaseException | None — None raises RuntimeError per
  archive AC; otherwise the default is returned or raised
- requests: list[Request] populated on every __call__
- last_request property reading requests[-1]
- aclose_calls counter
- add_route(method, url, response_or_exception) for incremental setup
- stream() raises NotImplementedError (lands in Epic 4)

Five tests cover: route match returns Response, route raises Exception,
no-match raises RuntimeError, default Response returned on no-match,
default Exception raised on no-match.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Method normalization, observability, lifecycle, stream, protocol satisfaction tests

Ten more tests covering case normalization, request recording, `aclose`, `stream`, protocol satisfaction, `add_route`, and multi-call semantics. No production code changes expected.

**Files:**
- Modify: `tests/test_transports_recorded.py` (append 10 tests)

- [ ] **Step 1: Add the method-normalization tests**

Append to `tests/test_transports_recorded.py`:

```python
async def test_method_normalized_to_uppercase_in_routes() -> None:
    canned = _response()
    transport = RecordedTransport(routes={("get", "/foo"): canned})

    result = await transport(_request(method="GET"))

    assert result is canned


async def test_method_normalized_to_uppercase_on_request() -> None:
    canned = _response()
    transport = RecordedTransport(routes={("GET", "/foo"): canned})

    result = await transport(_request(method="get"))

    assert result is canned
```

- [ ] **Step 2: Add the requests-recording tests**

Append:

```python
async def test_requests_list_records_every_call() -> None:
    transport = RecordedTransport(default=_response())

    req1 = _request(url="/a")
    req2 = _request(url="/b")
    req3 = _request(url="/c")
    await transport(req1)
    await transport(req2)
    await transport(req3)

    assert transport.requests == [req1, req2, req3]


async def test_last_request_returns_most_recent() -> None:
    transport = RecordedTransport(default=_response())

    assert transport.last_request is None

    req1 = _request(url="/a")
    await transport(req1)
    assert transport.last_request is req1

    req2 = _request(url="/b")
    await transport(req2)
    assert transport.last_request is req2
```

- [ ] **Step 3: Add the aclose tests**

Append:

```python
async def test_aclose_increments_counter() -> None:
    transport = RecordedTransport()

    assert transport.aclose_calls == 0

    await transport.aclose()
    await transport.aclose()
    await transport.aclose()

    assert transport.aclose_calls == 3  # noqa: PLR2004


async def test_aclose_is_idempotent_and_doesnt_block_calls() -> None:
    transport = RecordedTransport(default=_response())

    await transport.aclose()
    result = await transport(_request())

    assert result is not None
    assert transport.aclose_calls == 1
```

- [ ] **Step 4: Add the stream and protocol-satisfaction tests**

Append:

```python
def test_stream_raises_not_implemented_error() -> None:
    transport = RecordedTransport()

    with pytest.raises(NotImplementedError, match="streaming lands in Epic 4"):
        transport.stream(_request())


def test_satisfies_transport_protocol() -> None:
    assert isinstance(RecordedTransport(), Transport)
```

- [ ] **Step 5: Add the add_route and multi-call tests**

Append:

```python
async def test_add_route_appends_or_replaces_entry() -> None:
    transport = RecordedTransport()

    original = _response(b"first")
    transport.add_route("GET", "/foo", original)
    assert (await transport(_request())) is original

    replacement = _response(b"second")
    transport.add_route("GET", "/foo", replacement)
    assert (await transport(_request())) is replacement


async def test_routes_fire_indefinitely_on_repeat_calls() -> None:
    canned = _response(b"canned")
    transport = RecordedTransport(routes={("GET", "/foo"): canned})

    r1 = await transport(_request())
    r2 = await transport(_request())
    r3 = await transport(_request())

    assert r1 is canned
    assert r2 is canned
    assert r3 is canned
```

- [ ] **Step 6: Run all 15 tests**

Run: `uv run pytest tests/test_transports_recorded.py -v`
Expected: 15 passed.

- [ ] **Step 7: Lint**

Run: `uv run ruff check tests/test_transports_recorded.py`
Expected: clean.

- [ ] **Step 8: Verify 100% coverage on the new module**

Run: `uv run pytest tests/test_transports_recorded.py --cov=src/httpware/transports/recorded --cov-report=term-missing`
Expected: 100% coverage on `recorded.py`.

If any line is missed, identify which test should exercise it. The whole class body (~50 lines) is covered by the test suite as-written.

- [ ] **Step 9: Commit**

```bash
git add tests/test_transports_recorded.py
git commit -m "$(cat <<'EOF'
test(story-1.8): method norm, observability, lifecycle, protocol — full suite

Ten additional tests bring RecordedTransport to 15 total:
- method normalization in both directions (route key vs request)
- requests list captures every call in order; last_request property
- aclose counter; idempotent close that doesn't block subsequent calls
- stream() raises NotImplementedError pointing to Epic 4
- isinstance(RecordedTransport(), Transport) — protocol satisfaction
- add_route adds and replaces entries
- routes fire indefinitely on repeat matching calls

100% line coverage on src/httpware/transports/recorded.py.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Public exports and CHANGELOG

Wire `RecordedTransport` into the package root and add the Story 1.8 bullet.

**Files:**
- Modify: `src/httpware/__init__.py`
- Modify: `CHANGELOG.md`
- Modify: `tests/test_transports_recorded.py` (add a re-export test)

- [ ] **Step 1: Add the failing re-export test**

Append to `tests/test_transports_recorded.py`:

```python
def test_recorded_transport_reexported_at_package_root() -> None:
    """`from httpware import RecordedTransport` works in addition to the subpackage path."""
    import httpware

    assert httpware.RecordedTransport is RecordedTransport
    assert "RecordedTransport" in httpware.__all__
```

Move the `import httpware` to the top of the file alongside the other imports (memory: in-function imports are a code smell). If the test file doesn't yet import `httpware`, add it at the top.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_transports_recorded.py::test_recorded_transport_reexported_at_package_root -v`
Expected: `AttributeError: module 'httpware' has no attribute 'RecordedTransport'`.

- [ ] **Step 3: Update `src/httpware/__init__.py`**

Edit `src/httpware/__init__.py`. Find the existing `from httpware.transports.httpx2 import Httpx2Transport` line and add the import for `RecordedTransport` immediately after (or wherever ruff prefers alphabetically):

```python
from httpware.transports.recorded import RecordedTransport
```

In `__all__`, add `"RecordedTransport"` to the list. Ruff `RUF022` will sort. The correct ASCII-order position is between `"RateLimitedError"` and `"Request"`. If unsure, add anywhere and run `uv run ruff check --fix src/httpware/__init__.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_transports_recorded.py::test_recorded_transport_reexported_at_package_root -v`
Expected: PASS.

- [ ] **Step 5: Append CHANGELOG bullet**

Edit `CHANGELOG.md`. The `## [Unreleased]` / `### Added` section currently ends with the Story 1.7 bullet about `AsyncClient`. Append a new bullet immediately after it (before the `[Unreleased]: ...` reference link at the bottom):

```markdown
- `RecordedTransport` built-in `Transport` test double at `httpware.transports.recorded` (also re-exported as `httpware.RecordedTransport`). Construct with `routes: Mapping[(method, url), Response | BaseException]` and a configurable `default` for the no-match case (`None` → `RuntimeError("No route for METHOD URL")` per archive AC; `Response` → returned; `BaseException` → raised). Method names are uppercased on insert and lookup. Routes fire indefinitely on repeat matches. Exposes `transport.requests: list[Request]`, `transport.last_request` (property), and `transport.aclose_calls: int` for assertion patterns. `add_route(method, url, response_or_exception)` allows incremental setup. `stream()` raises `NotImplementedError` — streaming lands in Epic 4 (Story 4-1). Replaces the five in-tree test stubs (`_FakeTransport`, `_OkTransport`, `_FailingTransport`, two `_RecordingTransport` variants, `_TrackingTransport`) accumulated through Stories 2-1 and 1-7 (Story 1.8).
```

- [ ] **Step 6: Lint and ty**

Run: `uv run ruff check src/httpware/__init__.py tests/test_transports_recorded.py`
Run: `uv run ty check src/httpware/__init__.py`
Expected: both clean.

- [ ] **Step 7: Commit**

```bash
git add src/httpware/__init__.py tests/test_transports_recorded.py CHANGELOG.md
git commit -m "$(cat <<'EOF'
feat(story-1.8): re-export RecordedTransport at httpware package root

Adds RecordedTransport to httpware/__init__.py imports and __all__ so
consumers can `from httpware import RecordedTransport` in addition to
the subpackage path. CHANGELOG records the Story 1.8 surface and notes
the in-tree stub consolidation (Task 4).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Replace the five in-tree test stubs with `RecordedTransport`

Mechanical refactor across six test files. Each stub class drops out; `RecordedTransport(...)` construction takes its place. The replacements are bundled into one commit (per the spec's "stub-replacement commit must not regress any existing test").

**Files:**
- Modify: `tests/test_middleware.py` (drop `_OkTransport`, `_FailingTransport`)
- Modify: `tests/test_client_construction.py` (drop `_FakeTransport`)
- Modify: `tests/test_client_methods.py` (drop local `_RecordingTransport`)
- Modify: `tests/test_client_response_model.py` (drop local `_RecordingTransport`)
- Modify: `tests/test_client_lifecycle.py` (drop `_TrackingTransport`)
- Modify: `tests/test_client_middleware_wiring.py` (drop local `_RecordingTransport`; tests use `len(transport.requests)` instead of `.calls`)

For each file, the workflow is the same:

1. Add the import: `from httpware import RecordedTransport`.
2. Delete the stub class definition (and any unused `from contextlib import AbstractAsyncContextManager` or `from httpware.response import StreamResponse` imports left behind).
3. Replace each stub construction with `RecordedTransport(...)`.
4. Adapt any access to fields the stub had but `RecordedTransport` exposes differently (e.g., `.calls` → `len(transport.requests)`).
5. Run that file's tests.
6. Once all six files pass, commit.

The detailed per-file replacement strategy follows.

### 4.1 `tests/test_client_construction.py`

The `_FakeTransport` is constructed in `test_init_accepts_explicit_transport` and stored on the client; it's never called.

- [ ] **Step 1: Delete the `_FakeTransport` class definition**

Find this block at the top of `tests/test_client_construction.py`:

```python
class _FakeTransport:
    """Minimal Transport for construction tests; never actually called."""

    async def __call__(self, request: Request) -> Response:  # pragma: no cover - not used
        raise NotImplementedError

    def stream(  # pragma: no cover - not used
        self, request: Request
    ) -> AbstractAsyncContextManager[StreamResponse]:
        raise NotImplementedError

    async def aclose(self) -> None:  # pragma: no cover - not used
        return None
```

Delete it.

- [ ] **Step 2: Replace `_FakeTransport()` usage**

In `test_init_accepts_explicit_transport`, change `transport = _FakeTransport()` to:

```python
transport = RecordedTransport()
```

- [ ] **Step 3: Add the import**

At the top of the file's imports (alphabetically):

```python
from httpware import AsyncClient, Limits, RecordedTransport, Timeout
```

(Modify the existing `from httpware import AsyncClient, Limits, Timeout` line to include `RecordedTransport`.)

- [ ] **Step 4: Drop unused imports**

If `Response`, `StreamResponse`, `AbstractAsyncContextManager` were imported only for `_FakeTransport`, drop them. Verify by inspecting other tests in the file.

- [ ] **Step 5: Run this file's tests**

Run: `uv run pytest tests/test_client_construction.py -v`
Expected: all pass (same count as before).

### 4.2 `tests/test_client_lifecycle.py`

The `_TrackingTransport` exposes `aclose_calls`; `RecordedTransport` has the same attribute name.

- [ ] **Step 1: Delete the `_TrackingTransport` class definition**

Find and delete:

```python
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
```

- [ ] **Step 2: Replace `_TrackingTransport()` with `RecordedTransport()`**

In each test, change `transport = _TrackingTransport()` to:

```python
transport = RecordedTransport()
```

The tests already access `transport.aclose_calls`; that attribute is present on `RecordedTransport`.

- [ ] **Step 3: Add the import**

```python
from httpware import AsyncClient, RecordedTransport
```

- [ ] **Step 4: Drop unused imports**

Remove `Request`, `Response`, `StreamResponse`, `AbstractAsyncContextManager` if they were imported only for the stub.

- [ ] **Step 5: Run this file's tests**

Run: `uv run pytest tests/test_client_lifecycle.py -v`
Expected: all pass.

### 4.3 `tests/test_client_methods.py`

The `_RecordingTransport` here has `last_request` and a canned 200 response. `RecordedTransport(default=...)` provides both.

- [ ] **Step 1: Delete the local `_RecordingTransport` class**

Find and delete:

```python
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
```

- [ ] **Step 2: Replace constructions**

For each `transport = _RecordingTransport()`, replace with:

```python
transport = RecordedTransport(
    default=Response(
        status=200,
        headers={"x-from": "transport"},
        content=b"body",
        url="https://example.test/",
        elapsed=0.0,
    )
)
```

Tests already access `transport.last_request`; the property is present on `RecordedTransport`.

- [ ] **Step 3: Add the import**

```python
from httpware import AsyncClient, RecordedTransport
```

- [ ] **Step 4: Drop unused imports**

Remove `StreamResponse`, `AbstractAsyncContextManager` if no longer needed.

- [ ] **Step 5: Run this file's tests**

Run: `uv run pytest tests/test_client_methods.py -v`
Expected: all pass.

### 4.4 `tests/test_client_response_model.py`

The `_RecordingTransport` here takes a `content` argument and returns a canned 200 with that content.

- [ ] **Step 1: Delete the local `_RecordingTransport` class**

Find and delete the class definition at the top of the file.

- [ ] **Step 2: Replace constructions**

For each `transport = _RecordingTransport(content=b'...')`, replace with:

```python
transport = RecordedTransport(
    default=Response(
        status=200,
        headers={},
        content=b'...',
        url="/",
        elapsed=0.0,
    )
)
```

(Use the same content bytes the test was originally constructing.)

- [ ] **Step 3: Add the import**

```python
from httpware import AsyncClient, RecordedTransport, Response
```

- [ ] **Step 4: Drop unused imports**

Remove `StreamResponse`, `AbstractAsyncContextManager`, and the `Request` import if no longer used.

- [ ] **Step 5: Run this file's tests**

Run: `uv run pytest tests/test_client_response_model.py -v`
Expected: 3 passed.

### 4.5 `tests/test_client_middleware_wiring.py`

The `_RecordingTransport` here counts `.calls`. Replace with `RecordedTransport(default=...)`; tests that used `transport.calls == N` switch to `len(transport.requests) == N`.

- [ ] **Step 1: Delete the local `_RecordingTransport` class**

Find and delete the class.

- [ ] **Step 2: Replace constructions**

For each `transport = _RecordingTransport()`, replace with:

```python
transport = RecordedTransport(
    default=Response(
        status=200,
        headers={},
        content=b"",
        url="/",
        elapsed=0.0,
    )
)
```

Note: the original stub returned a Response with `url=request.url`. `RecordedTransport(default=Response(url="/"))` returns a fixed URL. Most tests don't read `response.url`; if any do, adjust them to read `transport.last_request.url` instead.

- [ ] **Step 3: Switch `transport.calls` to `len(transport.requests)`**

Search for `transport.calls` in the file. Each occurrence:

```python
# Before:
assert transport.calls == 1

# After:
assert len(transport.requests) == 1
```

- [ ] **Step 4: Add the import**

```python
from httpware import AsyncClient, RecordedTransport, Response
```

- [ ] **Step 5: Drop unused imports**

Remove `StreamResponse`, `AbstractAsyncContextManager`, `Request` if unused.

- [ ] **Step 6: Run this file's tests**

Run: `uv run pytest tests/test_client_middleware_wiring.py -v`
Expected: all pass.

### 4.6 `tests/test_middleware.py`

The file has TWO stubs: `_OkTransport` (returns fixed 200) and `_FailingTransport` (raises chosen exception). Replace both.

- [ ] **Step 1: Delete `_OkTransport` and `_FailingTransport`**

Find and delete:

```python
class _OkTransport:
    """Minimal Transport: returns a fixed Response, no streaming, no aclose work."""

    async def __call__(self, request: Request) -> Response:
        return Response(
            status=200,
            headers={"x-from": "transport"},
            content=b"transport",
            url=request.url,
            elapsed=0.0,
        )

    def stream(  # pragma: no cover - not exercised in 2-1
        ...
    ) -> AbstractAsyncContextManager[StreamResponse]:
        raise NotImplementedError

    async def aclose(self) -> None:  # pragma: no cover - not exercised in 2-1
        return None
```

And `_FailingTransport`:

```python
class _FailingTransport:
    """Transport whose __call__ raises a chosen exception."""

    def __init__(self, exc: BaseException) -> None:
        self._exc = exc

    async def __call__(self, request: Request) -> Response:  # noqa: ARG002
        raise self._exc

    def stream(  # pragma: no cover - not exercised in 2-2
        self, request: Request
    ) -> AbstractAsyncContextManager[StreamResponse]:
        raise NotImplementedError

    async def aclose(self) -> None:  # pragma: no cover - not exercised in 2-2
        return None
```

- [ ] **Step 2: Replace `_OkTransport()` constructions**

Each `_OkTransport()` becomes:

```python
RecordedTransport(
    default=Response(
        status=200,
        headers={"x-from": "transport"},
        content=b"transport",
        url="/",
        elapsed=0.0,
    )
)
```

Note: the original stub returned `url=request.url`. If any test reads `response.url` from the dispatched response and expects it to match the request URL, switch the assertion to read `transport.last_request.url`. Most tests in `test_middleware.py` check headers / status / content rather than url.

- [ ] **Step 3: Replace `_FailingTransport(exc)` constructions**

Each `_FailingTransport(some_error)` becomes:

```python
RecordedTransport(default=some_error)
```

- [ ] **Step 4: Add the import**

```python
from httpware import RecordedTransport
```

(plus the existing `Middleware`, `Next`, etc. imports.)

- [ ] **Step 5: Drop unused imports**

Remove `StreamResponse` and `AbstractAsyncContextManager` if no longer needed after the stub removal.

- [ ] **Step 6: Run this file's tests**

Run: `uv run pytest tests/test_middleware.py -v`
Expected: all 24 tests pass.

### 4.7 Final commit for Task 4

- [ ] **Step 1: Run the full test suite**

Run: `just test`
Expected: same count as the post-Task-3 baseline plus the 16 RecordedTransport tests (15 + 1 reexport), now ~272 passed, 1 deselected. 100% coverage maintained.

- [ ] **Step 2: Lint**

Run: `just lint-ci`
Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add tests/test_middleware.py tests/test_client_construction.py tests/test_client_methods.py tests/test_client_response_model.py tests/test_client_lifecycle.py tests/test_client_middleware_wiring.py
git commit -m "$(cat <<'EOF'
test(story-1.8): consolidate five in-tree transport stubs into RecordedTransport

Replaces the file-local _FakeTransport (test_client_construction.py),
_OkTransport and _FailingTransport (test_middleware.py), two distinct
_RecordingTransport variants (test_client_methods.py,
test_client_response_model.py, test_client_middleware_wiring.py), and
_TrackingTransport (test_client_lifecycle.py) with one shared
RecordedTransport class.

Each replacement is mechanical:
- _FakeTransport() → RecordedTransport()
- _OkTransport() → RecordedTransport(default=Response(...))
- _FailingTransport(exc) → RecordedTransport(default=exc)
- _RecordingTransport (last_request flavor) → RecordedTransport(default=Response(...))
- _RecordingTransport (calls counter) → RecordedTransport(default=Response(...))
  with .calls → len(transport.requests)
- _TrackingTransport → RecordedTransport()  (aclose_calls attribute preserved)

No test behavior changes. Total test count unchanged from this commit's
edits; only the new 16 RecordedTransport tests from Tasks 1-3 increase the
overall count.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Verify, push, PR, merge

End-to-end sanity check, push, open PR, wait for CI, merge.

- [ ] **Step 1: Run the full test suite with coverage**

Run: `just test`
Expected: ~272 passed (256 baseline post-1.7 + 15 RecordedTransport behavioral tests + 1 reexport test), 1 deselected (perf), 100% line coverage including `src/httpware/transports/recorded.py`.

- [ ] **Step 2: Run full lint and type checks**

Run: `just lint-ci`
Expected: `eof-fixer`, `ruff format --check`, `ruff check --no-fix`, `ty check` all clean.

- [ ] **Step 3: Confirm the working tree is clean**

Run: `git status --short`
Expected: only the untracked plan file `docs/superpowers/plans/2026-05-31-recordedtransport-plan.md`.

- [ ] **Step 4: Review the branch diff**

Run: `git log --oneline main..HEAD`
Expected: five commits — spec, Task 1, Task 2, Task 3, Task 4.

Run: `git diff --stat main..HEAD`
Expected: new files `src/httpware/transports/recorded.py`, `tests/test_transports_recorded.py`, the spec, the plan; modifications to `CHANGELOG.md`, `src/httpware/__init__.py`, and the six test files; no source files outside this scope.

- [ ] **Step 5: Stage and commit the plan file**

```bash
git add docs/superpowers/plans/2026-05-31-recordedtransport-plan.md
git commit -m "docs(story-1.8): implementation plan for RecordedTransport

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 6: Push the branch**

Run: `git push -u origin story/1-8-recordedtransport`
Expected: push succeeds; GitHub prints a "Create a pull request for ..." URL.

- [ ] **Step 7: Open the PR**

```bash
gh pr create --title "feat(story-1.8): RecordedTransport — built-in Transport test double" --body "$(cat <<'EOF'
## Summary

- Adds `src/httpware/transports/recorded.py` with `RecordedTransport`, a built-in `Transport` test double. Route table maps `(method, url)` to `Response | BaseException`; configurable `default` for the no-match case (`None` → `RuntimeError` per archive AC; `Response` → returned; `BaseException` → raised). Method names are uppercased on insert and lookup. Routes fire indefinitely on repeat matches.
- Exposes `transport.requests: list[Request]`, `transport.last_request` (property), and `transport.aclose_calls: int` for assertion patterns. `add_route(method, url, response_or_exception)` for incremental setup. `stream()` raises `NotImplementedError` — streaming lands in Epic 4 (Story 4-1).
- Re-exported as `httpware.RecordedTransport`.
- **Consolidation:** the five in-tree test stubs accumulated through Stories 1-7 and 2-1 (`_FakeTransport`, `_OkTransport`, `_FailingTransport`, two `_RecordingTransport` variants, `_TrackingTransport`) are replaced with one canonical class. Mechanical refactor; no test behavior changes.
- 16 new tests (15 behavioral + 1 reexport) in `tests/test_transports_recorded.py`; 100% line coverage on the new module.

This closes Epic 1.

Out of scope (subsequent stories): URL pattern matching / globs, cassette files loaded from JSON, streaming responses (Epic 4).

Spec + plan: `docs/superpowers/specs/2026-05-31-recordedtransport-design.md`, `docs/superpowers/plans/2026-05-31-recordedtransport-plan.md`.

## Test plan

- [x] `just test` — ~272 passed, 1 deselected, 100% line coverage on the new module.
- [x] `just lint-ci` clean.
- [x] `tests/test_no_httpx2_leakage.py` still passes.
- [x] `tests/test_optional_extras_isolation.py` still passes.
- [x] All six existing test files (`test_middleware.py`, `test_client_construction.py`, `test_client_methods.py`, `test_client_response_model.py`, `test_client_lifecycle.py`, `test_client_middleware_wiring.py`) pass after the stub-replacement commit.
- [ ] CI green on all matrix entries (3.11/3.12/3.13/3.14 + lint).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 8: Wait for CI**

Run: `gh pr checks <PR_NUMBER>`
Expected: all five jobs green.

If `pytest (3.14)` fails on the `codecov/codecov-action@v4.0.1` step with EPIPE (transient pattern observed earlier on this repo), re-run with `gh run rerun <RUN_ID> --failed`.

- [ ] **Step 9: Merge**

Once CI is green:

Run: `gh pr merge <PR_NUMBER> --merge --delete-branch`
Run: `git checkout main && git pull --ff-only && git log --oneline -3`

Story 1-8 is complete. **Epic 1 is complete.** Story 2-4 (auth coercion as middleware) becomes the next normal-flow item in Epic 2.

---

## Definition of done

- `src/httpware/transports/recorded.py` exists with the `RecordedTransport` class. No `__all__`.
- `tests/test_transports_recorded.py` contains 16 tests (15 behavioral + 1 reexport); all pass; 100% line coverage on `recorded.py`.
- `src/httpware/__init__.py` exports `RecordedTransport` at the package root and adds it to `__all__`.
- All five existing in-tree stub classes (`_FakeTransport`, `_OkTransport`, `_FailingTransport`, the two `_RecordingTransport` variants, `_TrackingTransport`) are removed from their respective test files; those tests now use `RecordedTransport(...)` construction. Total test count unchanged from before the stub-replacement commit (only Tasks 1-3 add new tests).
- `just test` shows ~272 passed, 1 deselected, 100% line coverage.
- `just lint-ci` clean.
- `tests/test_no_httpx2_leakage.py` and `tests/test_optional_extras_isolation.py` still pass.
- CHANGELOG bullet under `[Unreleased]` / `### Added` describes the public surface plus the stub-consolidation outcome.
- Story 1-8 lands as a single PR off `main` via the branch `story/1-8-recordedtransport`. Epic 1 is complete after this merge.

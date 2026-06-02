# RecordedTransport (design)

- **Date:** 2026-05-31
- **Status:** approved, ready for plan
- **Scope:** Story 1-8 (eighth and final story of Epic 1). Ships a built-in `Transport` test double at `src/httpware/transports/recorded.py` plus follow-up commits that replace the five existing in-tree test stubs (`_OkTransport`, `_FailingTransport`, `_FakeTransport`, two distinct `_RecordingTransport` variants, `_TrackingTransport`) with this new class. Out of scope: URL pattern matching / globs, cassette files loaded from JSON, streaming (Epic 4).
- **Roadmap pointer:** `docs/dev/engineering.md` §8 "Epic 1 — Make typed HTTP requests with sensible defaults".

## Why

Stories 1-1 through 1-7 each accumulated their own in-tree transport stubs — five distinct file-local classes that all reimplement the `Transport` protocol shape. They drift apart: some have `last_request`, some count `aclose_calls`, some count `calls`, one raises chosen exceptions. A single shared `RecordedTransport` consolidates the patterns and lets future stories (Epic 2 middleware tests, Epic 3 resilience tests, Epic 5 observability tests) reach for one well-documented test double instead of writing yet another stub.

The archived epic AC describes a minimal version (route table + raise on no-match). This spec is pragmatic: routes + observed-requests recording + close tracking, so the class can actually replace the existing stubs.

## Decisions

| Decision | Choice |
| --- | --- |
| Scope | Pragmatic — routes, observed requests, close tracking. |
| Module location | `src/httpware/transports/recorded.py`. |
| Public exports | Re-exported at package root: `from httpware import RecordedTransport`. |
| Route table type | `Mapping[tuple[str, str], Response \| BaseException]`. Method is uppercased on insert and lookup. URL match is byte-exact. |
| `BaseException` vs `Exception` | `BaseException` — covers `asyncio.CancelledError`, `SystemExit`, etc. Test code legitimately wants to express any of these. |
| No-match behavior | Configurable `default: Response \| BaseException \| None = None`. `None` → raises `RuntimeError(f"No route for {method} {url}")` per archive AC. `Response` → returned. `BaseException` → raised. |
| Multi-call semantics | Routes fire indefinitely. Same `(method, url)` yields the same canned response on every call. Tests asserting different replies on repeat calls swap the route via `add_route(...)` between calls. |
| Observed-request recording | `requests: list[Request]` populated on every `__call__`, in order. `last_request: Request \| None` is a property reading `requests[-1] if requests else None`. |
| `aclose()` tracking | `aclose_calls: int` counter; idempotent (multiple closes are allowed). |
| `aclose()` lockout | None. Calls after `aclose()` continue to work — matches test-double conventions; production transports may differ. |
| `stream()` method | Raises `NotImplementedError` with message pointing to Epic 4 / Story 4-1. |
| `add_route(method, url, response_or_exception)` | Public method for incremental route setup; lets tests build routes after construction. |
| `__all__` | Not added on `recorded.py` (project convention — only `__init__.py` files get `__all__`). Re-export in `httpware/__init__.py` adds to its `__all__`. |
| In-tree stub replacement | Five test files updated to use `RecordedTransport` instead of file-local stubs. Lands as a follow-up commit on this branch, bundled in the same PR. |

## File structure

**New files:**
- `src/httpware/transports/recorded.py` — `RecordedTransport` class (~50 lines).
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
- `pyproject.toml`.
- `src/httpware/transports/__init__.py` (`Transport` Protocol stays as-is).
- `src/httpware/transports/httpx2.py`.

## Public surface

```python
from collections.abc import Mapping
from contextlib import AbstractAsyncContextManager

from httpware.request import Request
from httpware.response import Response, StreamResponse


class RecordedTransport:
    def __init__(
        self,
        routes: Mapping[tuple[str, str], Response | BaseException] | None = None,
        *,
        default: Response | BaseException | None = None,
    ) -> None: ...

    requests: list[Request]      # appended on every __call__
    aclose_calls: int            # incremented on every aclose

    @property
    def last_request(self) -> Request | None: ...

    def add_route(
        self,
        method: str,
        url: str,
        response_or_exception: Response | BaseException,
    ) -> None: ...

    async def __call__(self, request: Request) -> Response: ...
    def stream(self, request: Request) -> AbstractAsyncContextManager[StreamResponse]: ...
    async def aclose(self) -> None: ...
```

Usage examples documented in the class docstring:

```python
# Simple canned response for a single endpoint.
transport = RecordedTransport(routes={
    ("GET", "/users"): Response(status=200, headers={}, content=b"[]", url="/users", elapsed=0.0),
})

# Same canned response for every request — useful for AsyncClient construction tests.
transport = RecordedTransport(default=Response(status=200, headers={}, content=b"", url="", elapsed=0.0))

# Raise on no-match (archive AC default).
transport = RecordedTransport()  # RuntimeError("No route for ...")

# Raise a specific exception on a route.
transport = RecordedTransport(routes={
    ("GET", "/error"): RuntimeError("upstream down"),
})

# Inspect observed requests after the test.
client = AsyncClient(transport=transport)
await client.get("/users")
assert transport.last_request is not None
assert transport.last_request.method == "GET"
```

## Implementation

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

Notes:
- Method uppercased on both insert (constructor + `add_route`) and lookup. Tests using `"get"` or `"GET"` in route keys behave the same.
- The constructor's dict comprehension preserves the original mapping unchanged (no surprises if the caller's `routes` is a `dict`).
- The `result: Response | BaseException | None = ...` line uses a single-pass conditional to avoid two dict accesses; the explicit `key in self._routes` keeps the type-system simple compared to `dict.get(key, self._default)` (which would force a wider union).
- `BaseException` is preferred over `Exception` so test code can express `asyncio.CancelledError`, `SystemExit`, `KeyboardInterrupt` if needed for cancellation/shutdown tests.
- No `__all__` in `recorded.py` (project convention).

## In-tree stub replacement

After landing `RecordedTransport`, replace each of the five existing in-tree stubs in a single bundled commit on this branch:

| Test file | Current stub | Replacement |
| --- | --- | --- |
| `tests/test_middleware.py` | `_OkTransport`, `_FailingTransport` | `RecordedTransport(default=Response(status=200, ...))` and `RecordedTransport(default=SomeError())`. |
| `tests/test_client_construction.py` | `_FakeTransport` | `RecordedTransport()`. |
| `tests/test_client_methods.py` | `_RecordingTransport` | `RecordedTransport(default=Response(...))`; tests already read `transport.last_request`. |
| `tests/test_client_response_model.py` | `_RecordingTransport` | `RecordedTransport(default=Response(status=200, content=..., ...))`. |
| `tests/test_client_lifecycle.py` | `_TrackingTransport` | `RecordedTransport()`; tests read `transport.aclose_calls`. |
| `tests/test_client_middleware_wiring.py` | `_RecordingTransport` (counts `calls`) | `RecordedTransport(default=Response(...))`; tests use `len(transport.requests)` instead of `.calls`. |

The replacements are mechanical. Each ~5–15 line stub class drops out, replaced by one-line construction. Test bodies that read `last_request` / `aclose_calls` keep working unchanged.

This consolidation is the structural payoff of the story: one canonical test double instead of five drifting variants.

## Testing

`tests/test_transports_recorded.py` — 15 tests:

| Test | Verifies |
| --- | --- |
| `test_route_match_returns_response` | Matching `(method, url)` returns canned Response. |
| `test_route_match_raises_exception` | Route configured with `BaseException` raises it. |
| `test_no_match_with_no_default_raises_runtime_error` | Archive default: `RuntimeError("No route for METHOD URL")`. |
| `test_no_match_with_response_default_returns_default` | `default=Response(...)` returned on no-match. |
| `test_no_match_with_exception_default_raises_default` | `default=SomeError()` raised on no-match. |
| `test_method_normalized_to_uppercase_in_routes` | Constructor `routes={("get", "/foo"): r}` matches `Request(method="GET", ...)`. |
| `test_method_normalized_to_uppercase_on_request` | `Request(method="get")` matches a route keyed `("GET", "/foo")`. |
| `test_requests_list_records_every_call` | `transport.requests` grows by one per call, in order. |
| `test_last_request_returns_most_recent` | `last_request` is `requests[-1]`; `None` initially. |
| `test_aclose_increments_counter` | Each `await aclose()` bumps the counter. |
| `test_aclose_is_idempotent_and_doesnt_block_calls` | After `aclose()`, the next `__call__` still works. |
| `test_stream_raises_not_implemented_error` | `transport.stream(request)` raises `NotImplementedError`. |
| `test_satisfies_transport_protocol` | `isinstance(RecordedTransport(), Transport)` is True. |
| `test_add_route_appends_or_replaces_entry` | `add_route(method, url, resp)` works for new entries and replacements. |
| `test_routes_fire_indefinitely_on_repeat_calls` | Three calls with the same `(method, url)` return the same canned Response three times. |

Coverage expectation: 100% line coverage on `src/httpware/transports/recorded.py`.

The stub-replacement commit must not regress any existing test. After the replacements, `just test` should still pass at the same count (now mostly 256 from Story 1-7 — the in-tree stub replacements don't add or remove tests).

## Constraints and invariants

- **No `httpx2` import.** `tests/test_no_httpx2_leakage.py` continues to pass.
- **No `from __future__ import annotations`.**
- **No `print()`, no `logging.basicConfig`.**
- **No `# type: ignore`.** `# ty: ignore[<rule>]` not expected.
- **No `__all__` in `recorded.py`** (project convention).
- **`# pragma: no cover` on `stream()`** is acceptable if coverage flags the raise — but the test `test_stream_raises_not_implemented_error` should exercise it, so likely not needed.

## Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| `_routes` is a public-ish attribute reached by tests; future changes break callers. | Documented as private (`_routes` underscore prefix). Tests use `add_route(...)`. The internal storage shape can change without breaking the public API. |
| `BaseException` route values surprise users who expected `Exception` — they pass a `CancelledError` and it leaks past `except Exception:`. | This is the intended behavior. Documented in the docstring: "BaseException covers all exception types, including asyncio.CancelledError. Test code that wants cancellation propagation should use this." |
| Replacing five in-tree stubs in one commit creates a large diff that hides regressions. | Run `just test` after each file's replacement and only commit when green. The commit message lists each file. |
| `RecordedTransport(default=Response(...))` returns the same Response for every request, so tests asserting "GET /users returned this response" can pass even if the client sent the wrong request. | This is the trade-off for the convenience default. Tests that need stricter matching configure routes explicitly. Documented in the docstring. |

## Definition of done

- `src/httpware/transports/recorded.py` exists with `RecordedTransport` class. No `__all__`.
- `tests/test_transports_recorded.py` contains 15 tests; all pass; 100% line coverage on the new module.
- `src/httpware/__init__.py` exports `RecordedTransport` at the package root.
- All five existing in-tree stub classes are removed and their tests updated to use `RecordedTransport`. The total test count is unchanged or strictly greater (no test removed except the stub class definitions themselves).
- `just test` shows the expected count, 1 deselected (perf), 100% line coverage including the new module.
- `just lint-ci` clean.
- `tests/test_no_httpx2_leakage.py` still passes.
- `tests/test_optional_extras_isolation.py` still passes.
- CHANGELOG bullet under `[Unreleased]` / `### Added` describes the public surface plus the stub-consolidation outcome.
- Story 1-8 lands as a single PR off `main` via the branch `story/1-8-recordedtransport`. Epic 1 is complete after this merge.

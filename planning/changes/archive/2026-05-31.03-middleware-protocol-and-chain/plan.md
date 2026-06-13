---
status: shipped
date: 2026-05-31
slug: middleware-protocol-and-chain
spec: middleware-protocol-and-chain
pr: 8
---

# Middleware protocol and chain composition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship Story 2-1: a `Middleware` runtime-checkable Protocol, a `Next` type alias, and a private `compose()` chain composer at `_internal/chain.py`. No decorators, no built-in middleware, no AsyncClient wiring (those are Stories 2-2 through 2-5).

**Architecture:** Three new module files plus one test file. `Middleware` and `Next` live at `src/httpware/middleware/__init__.py` and re-export at the package root. `compose(middlewares, transport) -> Next` lives at `src/httpware/_internal/chain.py` and uses a recursive closure fold with `transport.__call__` as the bottom of the chain. No exception handling anywhere in compose — `CancelledError` and all other exceptions propagate untouched.

**Tech Stack:** Python 3.11 floor. `typing.Protocol`, `typing.TypeAlias`, `typing.runtime_checkable`. No new dependencies, no new extras, no pyproject.toml changes.

**Branch:** `story/2-1-middleware-protocol-and-chain` (already created; the spec commit is on it).

**Spec:** `planning/specs/2026-05-31-middleware-protocol-and-chain-design.md`.

---

## File Structure

**New files:**
- `src/httpware/middleware/__init__.py` — `Middleware` Protocol + `Next` type alias. ~25 lines.
- `src/httpware/_internal/__init__.py` — empty package marker. 1 line (module docstring).
- `src/httpware/_internal/chain.py` — `compose()` + private `_wrap()`. ~30 lines.
- `tests/test_middleware.py` — 11 tests, ~150 lines.

**Modified files:**
- `src/httpware/__init__.py` — add `Middleware` and `Next` to imports and `__all__`.
- `CHANGELOG.md` — add an `[Unreleased]` bullet for Story 2.1.

**Files untouched (deliberate):**
- `src/httpware/request.py`, `response.py`, `errors.py`, `config.py`, `transports/`, `decoders/` — Story 2-1 is purely additive.
- `pyproject.toml`, `Justfile`, `.github/workflows/` — no tooling changes.
- `tests/test_no_httpx2_leakage.py` — must continue to pass without modification.

---

## Task 1: `Middleware` Protocol and `Next` type alias

Define the public protocol surface. TDD cycle: write a structural-check test, then the protocol module.

**Files:**
- Create: `src/httpware/middleware/__init__.py`
- Create: `tests/test_middleware.py` (test file itself, populated incrementally; this task seeds it)

- [ ] **Step 1: Write the failing test**

Create `tests/test_middleware.py`:

```python
"""Tests for the Middleware protocol and chain composition."""

from typing import get_type_hints

from httpware.middleware import Middleware, Next
from httpware.request import Request
from httpware.response import Response


class _SignalMiddleware:
    """Minimal valid Middleware implementation used by tests."""

    async def __call__(self, request: Request, next: Next) -> Response:
        return await next(request)


def test_runtime_checkable_isinstance_works() -> None:
    """A class implementing `__call__` with the right signature satisfies the Protocol."""

    assert isinstance(_SignalMiddleware(), Middleware)

    def plain_callable(_req: Request) -> Response:  # wrong signature: 1 arg, sync
        raise NotImplementedError

    assert not isinstance(plain_callable, Middleware)


def test_next_type_alias_is_a_callable_protocol() -> None:
    """`Next` is `Callable[[Request], Awaitable[Response]]` — verified by inspecting the alias target."""

    hints = get_type_hints(_SignalMiddleware.__call__)
    assert hints["next"] is Next
    # `Next` is a TypeAlias to Callable[[Request], Awaitable[Response]]; identity check above
    # is sufficient because the alias is publicly exported as a value.
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_middleware.py -v`

Expected: `ModuleNotFoundError: No module named 'httpware.middleware'`.

- [ ] **Step 3: Create the middleware module**

Create `src/httpware/middleware/__init__.py`:

```python
"""Middleware protocol — the AsyncClient ↔ Middleware seam (Seam 2)."""

from collections.abc import Awaitable, Callable
from typing import Protocol, TypeAlias, runtime_checkable

from httpware.request import Request
from httpware.response import Response


Next: TypeAlias = Callable[[Request], Awaitable[Response]]


@runtime_checkable
class Middleware(Protocol):
    """Structural protocol every middleware satisfies.

    A middleware receives the incoming `Request` and a `Next` callable. It may
    inspect/transform the request, await `next(request)` to forward to the rest
    of the chain (eventually the transport), inspect/transform the returned
    `Response`, short-circuit by returning a `Response` without calling `next`,
    or raise.
    """

    async def __call__(self, request: Request, next: Next) -> Response:  # noqa: A002
        """Process `request`; call `next(request)` to forward, or synthesize a Response."""
        ...


__all__ = ["Middleware", "Next"]
```

The `# noqa: A002` suppresses the ruff "argument shadows a Python builtin" check on the `next` parameter name. The shadowing is intentional and standard for this pattern (matches ASGI conventions). Structural typing matches by position and type, not parameter name, so implementers may rename it (and almost certainly should) when writing concrete middleware.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_middleware.py -v`

Expected: 2 passed.

- [ ] **Step 5: Lint and ty**

Run: `uv run ruff check src/httpware/middleware/ tests/test_middleware.py`
Expected: All checks passed.

Run: `uv run ty check src/httpware/middleware/`
Expected: All checks passed.

- [ ] **Step 6: Commit**

```bash
git add src/httpware/middleware/__init__.py tests/test_middleware.py
git commit -m "$(cat <<'EOF'
feat(story-2.1): Middleware protocol and Next type alias

Adds src/httpware/middleware/__init__.py defining:
- Next: TypeAlias = Callable[[Request], Awaitable[Response]]
- Middleware: @runtime_checkable Protocol with async __call__(request, next)

Matches Transport and ResponseDecoder shape. The `next` parameter
shadows the Python builtin (standard for this pattern); structural
typing matches by position, so concrete middleware may rename it.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `compose()` skeleton — empty list and single middleware

Build the smallest `compose` that satisfies the empty-list and single-middleware cases.

**Files:**
- Create: `src/httpware/_internal/__init__.py`
- Create: `src/httpware/_internal/chain.py`
- Modify: `tests/test_middleware.py` (append tests)

- [ ] **Step 1: Add the failing tests**

Append to `tests/test_middleware.py`:

```python
import pytest

from httpware._internal.chain import compose


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

    def stream(self, request: Request):  # pragma: no cover - not exercised in 2-1
        raise NotImplementedError

    async def aclose(self) -> None:  # pragma: no cover - not exercised in 2-1
        return None


def _make_request(method: str = "GET", url: str = "https://example.test/") -> Request:
    return Request(method=method, url=url)


async def test_empty_list_composes_to_transport_call() -> None:
    """compose([], transport) yields a callable that behaves like transport(req)."""

    transport = _OkTransport()
    dispatch = compose([], transport)

    request = _make_request()
    response = await dispatch(request)

    assert response.status == 200
    assert response.content == b"transport"
    assert response.headers["x-from"] == "transport"


async def test_single_middleware_wraps_transport() -> None:
    """One middleware sees the request, calls next, returns the transport's response unchanged."""

    seen: list[Request] = []

    class Tap:
        async def __call__(self, request: Request, next: Next) -> Response:  # noqa: A002
            seen.append(request)
            return await next(request)

    transport = _OkTransport()
    request = _make_request()

    response = await compose([Tap()], transport)(request)

    assert seen == [request]
    assert response.content == b"transport"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_middleware.py -v`
Expected: 2 prior pass; the 2 new tests fail with `ModuleNotFoundError: No module named 'httpware._internal'`.

- [ ] **Step 3: Create the `_internal` package**

Create `src/httpware/_internal/__init__.py`:

```python
"""Private cross-module helpers (not part of the public API)."""
```

- [ ] **Step 4: Create the chain module with compose()**

Create `src/httpware/_internal/chain.py`:

```python
"""Middleware chain composition — wires a middleware list against a Transport.

Private helper. AsyncClient calls `compose` at construction time and stores the
returned `Next` callable; per-request dispatch awaits that callable.
"""

from collections.abc import Sequence

from httpware.middleware import Middleware, Next
from httpware.request import Request
from httpware.response import Response
from httpware.transports import Transport


def compose(middlewares: Sequence[Middleware], transport: Transport) -> Next:
    """Fold `middlewares` into a single `Next` callable terminating at `transport`.

    The outermost middleware in the input sequence is the first to receive the
    request; its `next` argument forwards to the next middleware, and so on,
    until the innermost middleware's `next` calls `transport.__call__`. An
    empty sequence returns `transport.__call__` directly.

    The returned callable is reusable across many requests; it captures
    references to `middlewares` and `transport` by closure.
    """
    chain: Next = transport.__call__
    for middleware in reversed(middlewares):
        chain = _wrap(middleware, chain)
    return chain


def _wrap(middleware: Middleware, next_call: Next) -> Next:
    async def _call(request: Request) -> Response:
        return await middleware(request, next_call)

    return _call


__all__ = ["compose"]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_middleware.py -v`
Expected: 4 passed.

- [ ] **Step 6: Lint and ty**

Run: `uv run ruff check src/httpware/_internal/ tests/test_middleware.py`
Expected: All checks passed.

Run: `uv run ty check src/httpware/_internal/`
Expected: All checks passed.

If `ty` flags `chain: Next = transport.__call__` (e.g., complaining about assigning a bound method to a `Callable` alias), fall back to wrapping the bottom:

```python
async def _terminal(request: Request) -> Response:
    return await transport(request)

chain: Next = _terminal
```

…and add a code comment explaining why. The behavioral test still passes; only the identity of the empty-list result changes. (No identity assertion is made by any test, so no test edit needed.)

- [ ] **Step 7: Commit**

```bash
git add src/httpware/_internal/__init__.py src/httpware/_internal/chain.py tests/test_middleware.py
git commit -m "$(cat <<'EOF'
feat(story-2.1): compose() chain composer with empty and single-middleware cases

Adds src/httpware/_internal/chain.compose(middlewares, transport) -> Next
using a recursive closure fold. Bottom of chain is transport.__call__
(bound method, no wrapper). Empty sequence returns transport.__call__
directly. Tests verify both cases against a minimal _OkTransport fixture.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Chain ordering and request/response transformations

Verify that the existing `compose()` implementation handles the onion ordering and intermediate transformations correctly. No new production code is expected; if a test reveals a gap, fix it locally.

**Files:**
- Modify: `tests/test_middleware.py` (append tests)

- [ ] **Step 1: Add the failing/passing tests**

Append to `tests/test_middleware.py`:

```python
async def test_chain_runs_outer_to_inner() -> None:
    """Three middlewares form an onion: outer→inner→transport→inner→outer."""

    log: list[str] = []

    def labeled(name: str):
        class Labeled:
            async def __call__(self, request: Request, next: Next) -> Response:  # noqa: A002
                log.append(f"{name}:before")
                response = await next(request)
                log.append(f"{name}:after")
                return response

        return Labeled()

    dispatch = compose([labeled("A"), labeled("B"), labeled("C")], _OkTransport())
    await dispatch(_make_request())

    assert log == [
        "A:before",
        "B:before",
        "C:before",
        "C:after",
        "B:after",
        "A:after",
    ]


async def test_middleware_can_transform_request_before_forwarding() -> None:
    """An outer middleware mutates the request via with_header; the inner sees the mutation."""

    seen: list[Request] = []

    class Stamp:
        async def __call__(self, request: Request, next: Next) -> Response:  # noqa: A002
            stamped = request.with_header("x-trace", "abc123")
            return await next(stamped)

    class Inspect:
        async def __call__(self, request: Request, next: Next) -> Response:  # noqa: A002
            seen.append(request)
            return await next(request)

    await compose([Stamp(), Inspect()], _OkTransport())(_make_request())

    assert seen[0].headers["x-trace"] == "abc123"


async def test_middleware_can_transform_response_before_returning() -> None:
    """An outer middleware awaits next, then returns a modified Response; caller sees it."""

    class AddHeader:
        async def __call__(self, request: Request, next: Next) -> Response:  # noqa: A002
            response = await next(request)
            return Response(
                status=response.status,
                headers={**response.headers, "x-trace": "abc123"},
                content=response.content,
                url=response.url,
                elapsed=response.elapsed,
            )

    response = await compose([AddHeader()], _OkTransport())(_make_request())

    assert response.headers["x-trace"] == "abc123"
    assert response.headers["x-from"] == "transport"  # original still present
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `uv run pytest tests/test_middleware.py -v`
Expected: 7 passed.

If `test_chain_runs_outer_to_inner` fails with the wrong order, the loop direction in `compose` is wrong — verify the `reversed()` is present and the bottom of the chain is the transport (not the first middleware).

- [ ] **Step 3: Lint**

Run: `uv run ruff check tests/test_middleware.py`
Expected: All checks passed.

- [ ] **Step 4: Commit**

```bash
git add tests/test_middleware.py
git commit -m "$(cat <<'EOF'
test(story-2.1): chain ordering, request/response transformation

Adds three tests verifying the onion-execution order (outer→inner→
transport→inner→outer), request mutation via with_header propagates to
the inner middleware, and outer middleware can return a modified
Response after awaiting next. No production code changes; the existing
compose() implementation handles all three cases.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Short-circuit, exception propagation, and cancellation

The remaining behavioral tests: middleware that doesn't call `next`, exceptions in middleware and transport, and `CancelledError` propagation. None should require production-code changes.

**Files:**
- Modify: `tests/test_middleware.py` (append tests)

- [ ] **Step 1: Add the failing/passing tests**

Append to `tests/test_middleware.py`:

```python
import asyncio


async def test_short_circuit_returns_synthesized_response() -> None:
    """A middleware that does NOT call next returns a synthesized Response; transport never runs."""

    transport_calls = 0

    class CountingTransport(_OkTransport):
        async def __call__(self, request: Request) -> Response:
            nonlocal transport_calls
            transport_calls += 1
            return await super().__call__(request)

    class ShortCircuit:
        async def __call__(self, request: Request, next: Next) -> Response:  # noqa: A002
            return Response(
                status=418,
                headers={},
                content=b"teapot",
                url=request.url,
                elapsed=0.0,
            )

    class NeverReached:
        async def __call__(self, request: Request, next: Next) -> Response:  # noqa: A002
            raise AssertionError("inner middleware should not be invoked")

    response = await compose([ShortCircuit(), NeverReached()], CountingTransport())(_make_request())

    assert response.status == 418
    assert response.content == b"teapot"
    assert transport_calls == 0


async def test_exception_in_middleware_propagates() -> None:
    """A custom exception raised inside a middleware bubbles through the chain unchanged."""

    class CustomError(Exception):
        pass

    class Boom:
        async def __call__(self, request: Request, next: Next) -> Response:  # noqa: A002
            raise CustomError("boom")

    with pytest.raises(CustomError, match="boom"):
        await compose([Boom()], _OkTransport())(_make_request())


async def test_exception_in_transport_propagates_through_chain() -> None:
    """An exception raised by the transport passes through every middleware unmodified."""

    class TransportFail:
        async def __call__(self, request: Request) -> Response:
            raise RuntimeError("transport failed")

        def stream(self, request: Request):  # pragma: no cover - not exercised
            raise NotImplementedError

        async def aclose(self) -> None:  # pragma: no cover - not exercised
            return None

    class Passthrough:
        async def __call__(self, request: Request, next: Next) -> Response:  # noqa: A002
            return await next(request)

    with pytest.raises(RuntimeError, match="transport failed"):
        await compose([Passthrough(), Passthrough()], TransportFail())(_make_request())


async def test_cancelled_error_propagates_through_chain() -> None:
    """asyncio.CancelledError raised mid-chain propagates to the caller (NFR15)."""

    class Cancel:
        async def __call__(self, request: Request, next: Next) -> Response:  # noqa: A002
            raise asyncio.CancelledError

    class Passthrough:
        async def __call__(self, request: Request, next: Next) -> Response:  # noqa: A002
            return await next(request)

    with pytest.raises(asyncio.CancelledError):
        await compose([Passthrough(), Cancel()], _OkTransport())(_make_request())


async def test_compose_returned_callable_is_reusable() -> None:
    """The Next returned by compose can be awaited sequentially across multiple requests."""

    count = 0

    class Counter:
        async def __call__(self, request: Request, next: Next) -> Response:  # noqa: A002
            nonlocal count
            count += 1
            return await next(request)

    dispatch = compose([Counter()], _OkTransport())

    for _ in range(3):
        response = await dispatch(_make_request())
        assert response.status == 200

    assert count == 3
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `uv run pytest tests/test_middleware.py -v`
Expected: 12 passed.

(The plan defines 12 tests so far: 2 from Task 1 + 2 from Task 2 + 3 from Task 3 + 5 from Task 4. Task 5 adds one more re-export test for a final total of 13. The spec's table lists 11 — the two extras the plan adds are `test_next_type_alias_is_a_callable_protocol` and `test_middleware_and_next_are_reexported_at_package_root`.)

- [ ] **Step 3: Lint**

Run: `uv run ruff check tests/test_middleware.py`
Expected: All checks passed.

- [ ] **Step 4: Verify no `httpx2` leakage was introduced**

Run: `uv run pytest tests/test_no_httpx2_leakage.py -v`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add tests/test_middleware.py
git commit -m "$(cat <<'EOF'
test(story-2.1): short-circuit, exception propagation, cancellation, reusability

Adds five tests covering the remaining acceptance criteria:
- short-circuit middleware bypasses inner layers and the transport
- exceptions raised inside middleware bubble through unchanged
- exceptions raised by the transport pass through middleware unchanged
- asyncio.CancelledError propagates (NFR15)
- the Next returned by compose can be reused across sequential requests

No production code changes; compose's no-try/except design carries
the cancellation guarantee.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Public exports and CHANGELOG

Wire `Middleware` and `Next` into the package root and add a CHANGELOG bullet.

**Files:**
- Modify: `src/httpware/__init__.py`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Add the failing import test**

Append to `tests/test_middleware.py`:

```python
def test_middleware_and_next_are_reexported_at_package_root() -> None:
    """`from httpware import Middleware, Next` works in addition to the subpackage path."""

    import httpware

    assert httpware.Middleware is Middleware
    assert httpware.Next is Next
    assert "Middleware" in httpware.__all__
    assert "Next" in httpware.__all__
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_middleware.py::test_middleware_and_next_are_reexported_at_package_root -v`
Expected: `AttributeError: module 'httpware' has no attribute 'Middleware'`.

- [ ] **Step 3: Add the imports to `src/httpware/__init__.py`**

Edit `src/httpware/__init__.py`. After the existing `from httpware.errors import (...)` block (or in alphabetic position among the imports), add:

```python
from httpware.middleware import Middleware, Next
```

In the `__all__` list, insert `"Middleware"` and `"Next"` in alphabetic position. The list is alphabetically sorted; place `"Middleware"` between `"Limits"` and `"NotFoundError"`, and `"Next"` between `"NotFoundError"` and `"PydanticDecoder"`. The final `__all__` (relative additions) should look like:

```python
__all__ = [
    "STATUS_TO_EXCEPTION",
    "BadRequestError",
    "ClientConfig",
    "ClientError",
    "ClientStatusError",
    "ConflictError",
    "ForbiddenError",
    "Httpx2Transport",
    "InternalServerError",
    "Limits",
    "Middleware",   # NEW
    "Next",         # NEW
    "NotFoundError",
    "PydanticDecoder",
    "RateLimitedError",
    "Request",
    "Response",
    "ResponseDecoder",
    "ServerStatusError",
    "ServiceUnavailableError",
    "StatusError",
    "StreamResponse",
    "Timeout",
    "TimeoutError",
    "Transport",
    "TransportError",
    "UnauthorizedError",
    "UnprocessableEntityError",
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_middleware.py -v`
Expected: 13 passed.

- [ ] **Step 5: Update CHANGELOG**

Edit `CHANGELOG.md`. In the `## [Unreleased]` → `### Added` section, append a new bullet at the end of the list (after the Story 1.5 bullet):

```markdown
- `Middleware` protocol (`@runtime_checkable`) and `Next` callable type alias (`Callable[[Request], Awaitable[Response]]`); private `compose(middlewares, transport)` chain composer at `httpware._internal.chain` using a recursive closure fold with `transport.__call__` as the bottom of the chain. No exception handling inside `compose`, so `asyncio.CancelledError` and user-raised exceptions propagate untouched (Story 2.1).
```

- [ ] **Step 6: Lint and ty**

Run: `uv run ruff check src/httpware/__init__.py tests/test_middleware.py`
Expected: All checks passed.

Run: `uv run ty check src/httpware/__init__.py`
Expected: All checks passed.

- [ ] **Step 7: Commit**

```bash
git add src/httpware/__init__.py tests/test_middleware.py CHANGELOG.md
git commit -m "$(cat <<'EOF'
feat(story-2.1): re-export Middleware and Next at httpware package root

Adds Middleware and Next to httpware/__init__.py imports and __all__
so consumers can `from httpware import Middleware, Next` in addition
to the subpackage path. Matches the existing Request/Response/Transport
re-export pattern. CHANGELOG records the Story 2.1 surface.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Full verification, push, and PR

End-to-end sanity check on the branch, push, open PR, wait for CI.

- [ ] **Step 1: Run the full test suite with coverage**

Run: `just test`
Expected: 170 passed (157 baseline + 13 new), 1 deselected (perf bench), 100% line coverage including the new modules.

If coverage is below 100% on `middleware/__init__.py`, `_internal/__init__.py`, or `_internal/chain.py`, identify the uncovered line. The Protocol method body (`...`) typically reports as uncovered — add `# pragma: no cover` on the `...` line if so.

- [ ] **Step 2: Run full lint and type checks**

Run: `just lint-ci`
Expected: `ruff format --check`, `ruff check --no-fix`, `ty check` all clean.

- [ ] **Step 3: Confirm the working tree is clean**

Run: `git status --short`
Expected: empty output (nothing to commit, no untracked files).

- [ ] **Step 4: Review the branch diff**

Run: `git log --oneline main..HEAD`
Expected: five or six commits — the spec commit (`docs(story-2.1): design...`), Task 1, Task 2, Task 3, Task 4, Task 5.

Run: `git diff --stat main..HEAD`
Expected: changes to `CHANGELOG.md`, `planning/specs/2026-05-31-middleware-protocol-and-chain-design.md`, `planning/plans/2026-05-31-middleware-protocol-and-chain-plan.md`, `src/httpware/__init__.py`, two new files under `src/httpware/_internal/`, one new file under `src/httpware/middleware/`, and `tests/test_middleware.py`. No source files outside this scope should be touched.

- [ ] **Step 5: Stage and commit the plan file**

The plan file at `planning/plans/2026-05-31-middleware-protocol-and-chain-plan.md` is still untracked (it was created during the writing-plans step but not yet committed). Stage and commit it on this branch so the merge captures the plan alongside the spec.

Run:
```bash
git add planning/plans/2026-05-31-middleware-protocol-and-chain-plan.md
git commit -m "docs(story-2.1): implementation plan for Middleware protocol and chain

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 6: Push the branch**

Run: `git push -u origin story/2-1-middleware-protocol-and-chain`
Expected: push succeeds; GitHub prints a "Create a pull request for ..." URL.

- [ ] **Step 7: Open the PR**

Run:
```bash
gh pr create --title "feat(story-2.1): Middleware protocol, Next type, and chain composition" --body "$(cat <<'EOF'
## Summary

- Adds the `AsyncClient ↔ Middleware` seam (Seam 2): `Middleware` runtime-checkable Protocol with `async def __call__(self, request: Request, next: Next) -> Response`, and `Next = Callable[[Request], Awaitable[Response]]` exported at both `httpware.middleware.*` and `httpware.*`.
- Adds the private `compose(middlewares, transport) -> Next` at `httpware._internal.chain`. Recursive closure fold; `transport.__call__` is the bottom of the chain; empty list returns `transport.__call__` directly. No `try`/`except` in `compose` or `_wrap` — `asyncio.CancelledError` and user-raised exceptions propagate untouched (NFR15).
- 13 tests cover ordering (outer→inner onion), short-circuit, request and response transformation, exception propagation through middleware and transport, cancellation, runtime_checkable `isinstance`, package-root re-export, and reusability of the composed `Next`.

Out of scope (subsequent stories): phase decorators (2-2), Request immutability helpers beyond what already exists (2-3), auth coercion (2-4), AsyncClient wiring (2-5), streaming chain (4-3).

Spec + plan: `planning/specs/2026-05-31-middleware-protocol-and-chain-design.md`, `planning/plans/2026-05-31-middleware-protocol-and-chain-plan.md`.

## Test plan

- [x] `just test` — 170 passed, 1 deselected (perf), 100% line coverage including the new modules.
- [x] `just lint-ci` — `ruff format --check`, `ruff check --no-fix`, `ty check` all clean.
- [x] `tests/test_no_httpx2_leakage.py` passes — no `httpx2` import added.
- [x] `from httpware import Middleware, Next` and `from httpware.middleware import Middleware, Next` both resolve.
- [ ] CI green on all matrix entries.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 8: Wait for CI**

Run: `gh pr checks` (the PR number is printed by `gh pr create`).
Expected: all five jobs (`lint`, `pytest (3.11)`, `pytest (3.12)`, `pytest (3.13)`, `pytest (3.14)`) green.

If any check fails, identify which: CI's `lint` runs the same checks as `just lint-ci` and `pytest (3.x)` runs the same suite as `just test`. Fix locally on this branch, push the fix, wait again.

- [ ] **Step 9: Merge**

Once CI is green:

Run: `gh pr merge --merge --delete-branch`
Expected: PR merged, branch deleted locally and on remote.

Run: `git checkout main && git pull --ff-only && git log --oneline -3`
Expected: the cutover merge commit at HEAD, followed by the most recent Story 2.1 commit.

Story 2-1 is complete. Story 2-2 (phase decorators) is the next normal-flow item.

---

## Definition of done

- `src/httpware/middleware/__init__.py` exists and exports `Middleware` (runtime-checkable Protocol) and `Next` (TypeAlias).
- `src/httpware/_internal/__init__.py` exists as an empty package marker.
- `src/httpware/_internal/chain.py` exists and exports `compose(middlewares, transport) -> Next`.
- `src/httpware/__init__.py` re-exports `Middleware` and `Next` at the package root and adds them to `__all__` in alphabetic position.
- `tests/test_middleware.py` contains 13 tests; all pass.
- `just test` shows 170 passed, 1 deselected, 100% line coverage including the new modules.
- `just lint-ci` clean (`ruff format --check`, `ruff check --no-fix`, `ty check`).
- `tests/test_no_httpx2_leakage.py` still passes.
- `CHANGELOG.md` has a Story 2.1 bullet under `[Unreleased]` → `### Added`.
- Both the spec and the plan are committed on `story/2-1-middleware-protocol-and-chain` and land via a single PR.

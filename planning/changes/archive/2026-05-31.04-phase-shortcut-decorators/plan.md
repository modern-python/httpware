---
status: shipped
date: 2026-05-31
slug: phase-shortcut-decorators
spec: phase-shortcut-decorators
pr: 9
---

# Phase-shortcut decorators Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship Story 2-2: three sync decorator factories `before_request`, `after_response`, `on_error` in `src/httpware/middleware/__init__.py` that wrap async user functions into `Middleware`-conforming instances.

**Architecture:** Append three factory functions to the existing `middleware/__init__.py`. Each factory defines a private class inside its body, instantiates it, returns the instance. `f` is captured by closure; instance `__repr__` formats as `<phase_name(f.__qualname__)>`. `@on_error` adds the only `try`/`except Exception` in the codebase's middleware seam — `CancelledError` flows past untouched.

**Tech Stack:** Python 3.11 floor. No new dependencies, no pyproject.toml changes.

**Branch:** `story/2-2-phase-shortcut-decorators` (already created; spec commit `6cfc9fa` is on it).

**Spec:** `planning/specs/2026-05-31-phase-shortcut-decorators-design.md`.

---

## File Structure

**Modified files:**
- `src/httpware/middleware/__init__.py` — append three factory functions (~65 lines added; file grows from 30 to ~95 lines). Update `__all__`.
- `src/httpware/__init__.py` — import and re-export `before_request`, `after_response`, `on_error`. Update `__all__`.
- `docs/dev/engineering.md` — fix line 145 stale decorator names.
- `CHANGELOG.md` — append Story 2.2 bullet under `[Unreleased]` / `### Added`.
- `tests/test_middleware.py` — append 10 new tests (file grows from 14 → 24 tests).

**Files untouched:** Every other source file. Story 2-2 is purely additive on top of Story 2-1.

---

## Task 1: `@before_request` decorator

TDD cycle: write the behavioral test for request transformation, then implement the smallest factory that satisfies it.

**Files:**
- Modify: `src/httpware/middleware/__init__.py` (append factory)
- Modify: `tests/test_middleware.py` (append test)

- [ ] **Step 1: Add the failing test**

Append to `tests/test_middleware.py`. The existing imports already include `Request`, `Response`, `Middleware`, `Next`, `compose`, `_OkTransport`, `_make_request`. You will need to import `before_request`:

```python
from httpware.middleware import before_request


async def test_before_request_transforms_request() -> None:
    """@before_request wraps an async request transform; downstream sees the mutation."""

    @before_request
    async def stamp(request: Request) -> Request:
        return request.with_header("x-trace", "abc123")

    seen: list[Request] = []

    class Inspect:
        async def __call__(self, request: Request, next: Next) -> Response:  # noqa: A002
            seen.append(request)
            return await next(request)

    await compose([stamp, Inspect()], _OkTransport())(_make_request())

    assert seen[0].headers["x-trace"] == "abc123"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_middleware.py::test_before_request_transforms_request -v`
Expected: `ImportError: cannot import name 'before_request' from 'httpware.middleware'`.

- [ ] **Step 3: Implement `before_request`**

Append to `src/httpware/middleware/__init__.py` (after the `Middleware` class, before `__all__`):

```python
def before_request(f: Callable[[Request], Awaitable[Request]]) -> Middleware:
    """Wrap an async request transform into a Middleware.

    The decorated function receives the incoming Request and returns a
    (possibly modified) Request, which is then forwarded down the chain.
    """

    class _BeforeRequestMiddleware:
        async def __call__(self, request: Request, next: Next) -> Response:  # noqa: A002
            return await next(await f(request))

        def __repr__(self) -> str:
            return f"<before_request({f.__qualname__})>"

    return _BeforeRequestMiddleware()
```

Update `__all__` at the bottom of the file from `["Middleware", "Next"]` to `["Middleware", "Next", "before_request"]`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_middleware.py::test_before_request_transforms_request -v`
Expected: PASS.

- [ ] **Step 5: Run the full test_middleware.py to confirm no regressions**

Run: `uv run pytest tests/test_middleware.py -v`
Expected: 15 passed (14 prior + 1 new).

- [ ] **Step 6: Lint and ty**

Run: `uv run ruff check src/httpware/middleware/__init__.py tests/test_middleware.py`
Expected: All checks passed.

Run: `uv run ty check src/httpware/middleware/__init__.py`
Expected: All checks passed.

If ruff/`ty` flags the inner class for any reason, the standard mitigation is to mark suppressions with `# ty: ignore[<rule>]` or `# noqa: <RULE>` on the trigger line — but none expected. The structural Protocol match should work because the class has an `async __call__(self, request, next) -> Response` matching `Middleware`.

- [ ] **Step 7: Commit**

```bash
git add src/httpware/middleware/__init__.py tests/test_middleware.py
git commit -m "$(cat <<'EOF'
feat(story-2.2): @before_request decorator factory

Wraps an async f(Request) -> Request into a Middleware that applies f
then forwards the (possibly transformed) request down the chain via
await next(...). Returns a private _BeforeRequestMiddleware instance
with a __repr__ that surfaces the original function name.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `@after_response` decorator

TDD cycle for the response-transform variant. Mirrors Task 1's shape.

**Files:**
- Modify: `src/httpware/middleware/__init__.py` (append factory)
- Modify: `tests/test_middleware.py` (append test)

- [ ] **Step 1: Add the failing test**

Append to `tests/test_middleware.py`. Add `after_response` to the existing `from httpware.middleware import before_request` line so it reads `from httpware.middleware import after_response, before_request`:

```python
async def test_after_response_transforms_response() -> None:
    """@after_response wraps an async response transform; caller sees the modification."""

    @after_response
    async def add_header(request: Request, response: Response) -> Response:
        return Response(
            status=response.status,
            headers={**response.headers, "x-trace": "abc123"},
            content=response.content,
            url=response.url,
            elapsed=response.elapsed,
        )

    response = await compose([add_header], _OkTransport())(_make_request())

    assert response.headers["x-trace"] == "abc123"
    assert response.headers["x-from"] == "transport"  # original still present
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_middleware.py::test_after_response_transforms_response -v`
Expected: `ImportError: cannot import name 'after_response' from 'httpware.middleware'`.

- [ ] **Step 3: Implement `after_response`**

Append to `src/httpware/middleware/__init__.py` after the `before_request` factory:

```python
def after_response(f: Callable[[Request, Response], Awaitable[Response]]) -> Middleware:
    """Wrap an async response transform into a Middleware.

    The decorated function receives the original Request and the Response
    returned by the chain, and returns a (possibly modified) Response.
    """

    class _AfterResponseMiddleware:
        async def __call__(self, request: Request, next: Next) -> Response:  # noqa: A002
            response = await next(request)
            return await f(request, response)

        def __repr__(self) -> str:
            return f"<after_response({f.__qualname__})>"

    return _AfterResponseMiddleware()
```

Update `__all__` from `["Middleware", "Next", "before_request"]` to `["Middleware", "Next", "after_response", "before_request"]`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_middleware.py::test_after_response_transforms_response -v`
Expected: PASS.

- [ ] **Step 5: Run the full test_middleware.py**

Run: `uv run pytest tests/test_middleware.py -v`
Expected: 16 passed (15 prior + 1 new).

- [ ] **Step 6: Lint and ty**

Run: `uv run ruff check src/httpware/middleware/__init__.py tests/test_middleware.py`
Run: `uv run ty check src/httpware/middleware/__init__.py`
Expected: both clean.

- [ ] **Step 7: Commit**

```bash
git add src/httpware/middleware/__init__.py tests/test_middleware.py
git commit -m "$(cat <<'EOF'
feat(story-2.2): @after_response decorator factory

Wraps an async f(Request, Response) -> Response into a Middleware that
awaits next(...) then applies f to the result. Returns a private
_AfterResponseMiddleware instance with the standard __repr__.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `@on_error` decorator

The substantive decorator — adds the one `try`/`except Exception` in the seam. Four behavioral tests pin the contract: returning a Response swallows the exception, returning None re-raises, CancelledError flows past, and the handler receives the original exception instance.

**Files:**
- Modify: `src/httpware/middleware/__init__.py` (append factory)
- Modify: `tests/test_middleware.py` (append fixture + 4 tests)

- [ ] **Step 1: Add the failing tests**

Append to `tests/test_middleware.py`. Add `on_error` to the existing import: `from httpware.middleware import after_response, before_request, on_error`. Then append:

```python
class _FailingTransport:
    """Transport whose __call__ raises a chosen exception."""

    def __init__(self, exc: BaseException) -> None:
        self._exc = exc

    async def __call__(self, request: Request) -> Response:
        raise self._exc

    def stream(self, request: Request):  # pragma: no cover - not exercised in 2-2
        raise NotImplementedError

    async def aclose(self) -> None:  # pragma: no cover - not exercised in 2-2
        return None


async def test_on_error_returns_response_swallows_exception() -> None:
    """When the handler returns a Response, the caller gets it; no exception escapes."""

    @on_error
    async def recover(request: Request, exc: Exception) -> Response | None:
        return Response(
            status=503,
            headers={"x-recovered": "true"},
            content=b"recovered",
            url=request.url,
            elapsed=0.0,
        )

    transport = _FailingTransport(RuntimeError("boom"))
    response = await compose([recover], transport)(_make_request())

    assert response.status == 503
    assert response.headers["x-recovered"] == "true"
    assert response.content == b"recovered"


async def test_on_error_returns_none_reraises() -> None:
    """When the handler returns None, the original exception is re-raised with traceback intact."""

    @on_error
    async def pass_through(request: Request, exc: Exception) -> Response | None:
        return None

    transport = _FailingTransport(RuntimeError("boom"))

    with pytest.raises(RuntimeError, match="boom"):
        await compose([pass_through], transport)(_make_request())


async def test_on_error_does_not_catch_cancelled_error() -> None:
    """asyncio.CancelledError is not Exception; the handler must not be invoked."""

    invocations: list[Exception] = []

    @on_error
    async def should_not_run(request: Request, exc: Exception) -> Response | None:
        invocations.append(exc)
        return None

    class Cancel:
        async def __call__(self, request: Request, next: Next) -> Response:  # noqa: A002
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await compose([should_not_run, Cancel()], _OkTransport())(_make_request())

    assert invocations == []


async def test_on_error_handler_receives_correct_exception_instance() -> None:
    """The handler's `exc` parameter is the same instance the transport raised."""

    raised = RuntimeError("specific instance")
    seen: list[Exception] = []

    @on_error
    async def capture(request: Request, exc: Exception) -> Response | None:
        seen.append(exc)
        return None

    with pytest.raises(RuntimeError):
        await compose([capture], _FailingTransport(raised))(_make_request())

    assert seen == [raised]
    assert seen[0] is raised
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_middleware.py -k "on_error" -v`
Expected: 4 errors with `ImportError: cannot import name 'on_error' from 'httpware.middleware'`.

- [ ] **Step 3: Implement `on_error`**

Append to `src/httpware/middleware/__init__.py` after the `after_response` factory:

```python
def on_error(f: Callable[[Request, Exception], Awaitable[Response | None]]) -> Middleware:
    """Wrap an async error handler into a Middleware.

    Catches Exception (not BaseException, so asyncio.CancelledError
    propagates). If the handler returns a Response, that Response is
    returned to the caller. If the handler returns None, the original
    exception is re-raised.
    """

    class _OnErrorMiddleware:
        async def __call__(self, request: Request, next: Next) -> Response:  # noqa: A002
            try:
                return await next(request)
            except Exception as exc:
                result = await f(request, exc)
                if result is None:
                    raise
                return result

        def __repr__(self) -> str:
            return f"<on_error({f.__qualname__})>"

    return _OnErrorMiddleware()
```

Update `__all__` from `["Middleware", "Next", "after_response", "before_request"]` to `["Middleware", "Next", "after_response", "before_request", "on_error"]`.

- [ ] **Step 4: Run on_error tests to verify they pass**

Run: `uv run pytest tests/test_middleware.py -k "on_error" -v`
Expected: 4 passed.

- [ ] **Step 5: Run the full test_middleware.py**

Run: `uv run pytest tests/test_middleware.py -v`
Expected: 20 passed (16 prior + 4 new).

- [ ] **Step 6: Lint and ty**

Run: `uv run ruff check src/httpware/middleware/__init__.py tests/test_middleware.py`
Run: `uv run ty check src/httpware/middleware/__init__.py`
Expected: both clean.

If ruff flags BLE001 ("bare blind except") on the `except Exception as exc:` line, suppress with `# noqa: BLE001` and add a one-line code comment: `# We catch Exception deliberately; CancelledError is BaseException and propagates.` `BLE001` targets `except Exception` specifically.

- [ ] **Step 7: Commit**

```bash
git add src/httpware/middleware/__init__.py tests/test_middleware.py
git commit -m "$(cat <<'EOF'
feat(story-2.2): @on_error decorator factory

Wraps an async f(Request, Exception) -> Response | None into a
Middleware. Catches Exception (not BaseException, so CancelledError
propagates). If the handler returns a Response, that becomes the
caller's response; if it returns None, the original exception is
re-raised with traceback intact via bare `raise`.

Four tests pin the contract: recovery via Response, re-raise via None,
CancelledError flows past untouched, handler receives the original
exception instance.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Cross-decorator behavior tests

Verify the three decorators interoperate: each satisfies the `Middleware` Protocol, mixes correctly in a `compose()` chain alongside class-based middleware, and renders a useful `repr()`. No new production code is expected.

**Files:**
- Modify: `tests/test_middleware.py` (append 3 tests)

- [ ] **Step 1: Add the tests**

Append to `tests/test_middleware.py`:

```python
def test_decorators_satisfy_middleware_protocol() -> None:
    """Each decorator returns an object that isinstance() recognizes as Middleware."""

    @before_request
    async def br(request: Request) -> Request:
        return request

    @after_response
    async def ar(request: Request, response: Response) -> Response:
        return response

    @on_error
    async def oe(request: Request, exc: Exception) -> Response | None:
        return None

    assert isinstance(br, Middleware)
    assert isinstance(ar, Middleware)
    assert isinstance(oe, Middleware)


async def test_decorated_middlewares_compose_in_chain() -> None:
    """Phase decorators interoperate with class-based middleware in one compose() call."""

    @before_request
    async def stamp(request: Request) -> Request:
        return request.with_header("x-stamp", "1")

    @after_response
    async def tag(request: Request, response: Response) -> Response:
        return Response(
            status=response.status,
            headers={**response.headers, "x-tag": "1"},
            content=response.content,
            url=response.url,
            elapsed=response.elapsed,
        )

    seen_headers: list[str] = []

    class Inspect:
        async def __call__(self, request: Request, next: Next) -> Response:  # noqa: A002
            seen_headers.append(request.headers.get("x-stamp", ""))
            return await next(request)

    response = await compose([stamp, Inspect(), tag], _OkTransport())(_make_request())

    assert seen_headers == ["1"]  # stamp ran before Inspect
    assert response.headers["x-tag"] == "1"  # tag ran after the chain


def test_repr_shows_original_function_name() -> None:
    """repr() includes the phase name and the original user function's qualname."""

    @before_request
    async def my_stamp(request: Request) -> Request:
        return request

    text = repr(my_stamp)
    assert "before_request" in text
    assert "my_stamp" in text
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `uv run pytest tests/test_middleware.py -v`
Expected: 23 passed (20 prior + 3 new).

- [ ] **Step 3: Lint**

Run: `uv run ruff check tests/test_middleware.py`
Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add tests/test_middleware.py
git commit -m "$(cat <<'EOF'
test(story-2.2): cross-decorator behavior (Protocol, chain, repr)

Three tests verify the three decorators interoperate:
- isinstance() recognizes each as Middleware
- a mixed chain of @before_request + class middleware + @after_response
  applies each phase in the correct position
- repr() surfaces the phase name and the original user function's
  qualname for debug-friendly chain inspection

No production code changes.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Public exports, engineering.md fix, CHANGELOG

Wire the three decorators into the package root, fix the stale naming in `engineering.md`, and record the change in `CHANGELOG.md`. One re-export test.

**Files:**
- Modify: `src/httpware/__init__.py`
- Modify: `docs/dev/engineering.md`
- Modify: `CHANGELOG.md`
- Modify: `tests/test_middleware.py` (append 1 re-export test)

- [ ] **Step 1: Add the failing re-export test**

Append to `tests/test_middleware.py`:

```python
def test_decorators_reexported_at_package_root() -> None:
    """`from httpware import before_request, after_response, on_error` works."""

    import httpware  # noqa: PLC0415

    assert httpware.before_request is before_request
    assert httpware.after_response is after_response
    assert httpware.on_error is on_error
    assert "before_request" in httpware.__all__
    assert "after_response" in httpware.__all__
    assert "on_error" in httpware.__all__
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_middleware.py::test_decorators_reexported_at_package_root -v`
Expected: `AttributeError: module 'httpware' has no attribute 'before_request'`.

- [ ] **Step 3: Update `src/httpware/__init__.py`**

Find the existing line `from httpware.middleware import Middleware, Next` and replace it with:

```python
from httpware.middleware import Middleware, Next, after_response, before_request, on_error
```

In `__all__`, the existing list ends with `"UnprocessableEntityError"`. Append the three lowercase names after it (lowercase sorts after uppercase in ASCII):

```python
__all__ = [
    # ... existing entries unchanged ...
    "UnprocessableEntityError",
    "after_response",
    "before_request",
    "on_error",
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_middleware.py::test_decorators_reexported_at_package_root -v`
Expected: PASS.

- [ ] **Step 5: Fix the engineering.md roadmap line**

Edit `docs/dev/engineering.md` line 145. The current text reads:

```
- **2-2** Phase shortcut decorators (`@on_request`, `@on_response`, `@on_error`).
```

Replace with:

```
- **2-2** Phase shortcut decorators (`@before_request`, `@after_response`, `@on_error`).
```

- [ ] **Step 6: Append a CHANGELOG bullet**

Edit `CHANGELOG.md`. The `## [Unreleased]` / `### Added` section ends with the Story 2.1 bullet about the `Middleware` protocol and `compose`. Append a new bullet immediately after it (before the `[Unreleased]: ...` reference link line at the bottom of the file):

```markdown
- Phase-shortcut decorators `@before_request`, `@after_response`, `@on_error` for lifecycle hooks without authoring a full `Middleware` class. `@on_error` catches `Exception` only (so `asyncio.CancelledError` propagates); its handler may return a `Response` to recover or `None` to re-raise (Story 2.2).
```

- [ ] **Step 7: Lint and ty**

Run: `uv run ruff check src/httpware/__init__.py tests/test_middleware.py`
Expected: All checks passed.

Run: `uv run ty check src/httpware/__init__.py`
Expected: All checks passed.

- [ ] **Step 8: Commit**

```bash
git add src/httpware/__init__.py docs/dev/engineering.md CHANGELOG.md tests/test_middleware.py
git commit -m "$(cat <<'EOF'
feat(story-2.2): re-export decorators; fix engineering.md naming; CHANGELOG

Adds before_request, after_response, on_error to httpware/__init__.py
imports and __all__ so consumers can `from httpware import …` in
addition to the subpackage path.

Fixes docs/dev/engineering.md §8 line 145 to reflect the canonical
@before_request / @after_response / @on_error names (it had stale
@on_request / @on_response from the distillation).

CHANGELOG records the Story 2.2 surface.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Verify, push, PR, merge

End-to-end sanity check, push the branch, open the PR, wait for CI, merge.

- [ ] **Step 1: Run the full test suite with coverage**

Run: `just test`
Expected: 184 passed (174 baseline post-2-1 + 10 new), 1 deselected (perf bench), 100% line coverage including the new decorator factories.

The Protocol method body `...` line is excluded from coverage automatically; if the new inner-class `__call__` bodies report uncovered lines, the tests are insufficient — back up and add cases. None should be uncovered: each test exercises every decorator's full body.

- [ ] **Step 2: Run full lint and type checks**

Run: `just lint-ci`
Expected: `eof-fixer`, `ruff format --check`, `ruff check --no-fix`, `ty check` all clean.

- [ ] **Step 3: Confirm the working tree is clean**

Run: `git status --short`
Expected: empty output (every change committed).

- [ ] **Step 4: Review the branch diff**

Run: `git log --oneline main..HEAD`
Expected: six or seven commits — spec (`docs(story-2.2): design...`), Task 1, Task 2, Task 3, Task 4, Task 5.

Run: `git diff --stat main..HEAD`
Expected: changes to `CHANGELOG.md`, `docs/dev/engineering.md`, `planning/specs/2026-05-31-phase-shortcut-decorators-design.md`, `planning/plans/2026-05-31-phase-shortcut-decorators-plan.md`, `src/httpware/__init__.py`, `src/httpware/middleware/__init__.py`, `tests/test_middleware.py`. No other source files touched.

- [ ] **Step 5: Stage and commit the plan file**

The plan file at `planning/plans/2026-05-31-phase-shortcut-decorators-plan.md` is still untracked. Stage and commit it on this branch so the merge captures the plan alongside the spec.

```bash
git add planning/plans/2026-05-31-phase-shortcut-decorators-plan.md
git commit -m "docs(story-2.2): implementation plan for phase-shortcut decorators

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 6: Push the branch**

Run: `git push -u origin story/2-2-phase-shortcut-decorators`
Expected: push succeeds; GitHub prints a "Create a pull request for ..." URL.

- [ ] **Step 7: Open the PR**

```bash
gh pr create --title "feat(story-2.2): phase-shortcut decorators @before_request, @after_response, @on_error" --body "$(cat <<'EOF'
## Summary

- Adds three phase-shortcut decorators in `src/httpware/middleware/__init__.py` for writing lifecycle hooks without authoring a full `Middleware` class:
  - `@before_request` wraps `async f(Request) -> Request` and forwards the transformed request to the chain.
  - `@after_response` wraps `async f(Request, Response) -> Response` and applies `f` to the response.
  - `@on_error` wraps `async f(Request, Exception) -> Response | None`, catches `Exception` only (`CancelledError` propagates), returns the handler's `Response` or re-raises if the handler returns `None`.
- Each decorator returns a private class instance with `f` captured via closure and a `__repr__` of the form `<before_request(f.__qualname__)>` for clean chain inspection.
- All three exported at both `httpware.middleware.*` and `httpware.*`.
- 10 new tests in `tests/test_middleware.py` (24 total): request and response transformations, on_error swallow/re-raise paths, `CancelledError` non-capture, exception identity, Protocol satisfaction, mixed-chain composition, `repr()` content, package-root re-export.

Bundled-in doc fix: `docs/dev/engineering.md` §8 line 145 had stale `@on_request`/`@on_response` names from the distillation — corrected to the canonical `@before_request`/`@after_response`.

Out of scope (subsequent stories): `Request.with_*` helper expansion (2-3), auth coercion (2-4), AsyncClient wiring (2-5).

Spec + plan: `planning/specs/2026-05-31-phase-shortcut-decorators-design.md`, `planning/plans/2026-05-31-phase-shortcut-decorators-plan.md`.

## Test plan

- [x] `just test` — 184 passed, 1 deselected, 100% line coverage including the new factories.
- [x] `just lint-ci` clean.
- [x] `tests/test_no_httpx2_leakage.py` still passes.
- [x] `from httpware import before_request, after_response, on_error` and the subpackage path both resolve.
- [ ] CI green on all matrix entries (3.11/3.12/3.13/3.14 + lint).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 8: Wait for CI**

Run: `gh pr checks <PR_NUMBER>` (the number is printed by `gh pr create`).
Expected: all five jobs green (`lint`, `pytest (3.11)`, `pytest (3.12)`, `pytest (3.13)`, `pytest (3.14)`).

Codecov uploads on `pytest (3.14)` have shown a transient EPIPE failure in this repo. If 3.14 fails on the `Run codecov/codecov-action@v4.0.1` step (not on pytest itself), re-run with `gh run rerun <RUN_ID> --failed` and re-check.

If a pytest step fails on a specific Python version, identify the test and version locally with `uv run --python 3.X pytest …` and address; pure-Python `Protocol` / `TypeAlias` / `Callable` shape is stable across 3.11–3.14, so failures more likely indicate test fragility than version differences.

- [ ] **Step 9: Merge**

Once CI is green:

Run: `gh pr merge <PR_NUMBER> --merge --delete-branch`
Expected: PR merged, branch deleted locally and on remote.

Run: `git checkout main && git pull --ff-only && git log --oneline -3`
Expected: the cutover merge commit at HEAD; the Story 2.2 history visible below.

Story 2-2 is complete. Story 2-3 (`Request` immutability helper expansion) is the next normal-flow item.

---

## Definition of done

- `src/httpware/middleware/__init__.py` exports `before_request`, `after_response`, `on_error` in addition to `Middleware` and `Next`.
- `src/httpware/__init__.py` re-exports the three new names and adds them to `__all__` in alphabetic position (after `"UnprocessableEntityError"`).
- `docs/dev/engineering.md` §8 line 145 reads `@before_request`, `@after_response`, `@on_error` — the stale `@on_request`/`@on_response` is gone.
- `CHANGELOG.md` has a Story 2.2 bullet under `[Unreleased]` / `### Added`.
- `tests/test_middleware.py` contains 24 tests (14 carried forward from Story 2-1 + 10 new); all pass.
- `just test` shows 184 passed, 1 deselected, 100% line coverage.
- `just lint-ci` clean.
- `tests/test_no_httpx2_leakage.py` still passes.
- Both the spec and the plan are committed on `story/2-2-phase-shortcut-decorators` and land via a single PR.

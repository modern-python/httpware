# Sync `Client` + httpx2-aligned `Async*` rename — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a sync `Client` to `httpware` with full parity to `AsyncClient` (typed decoding, middleware, `Retry`/`Bulkhead`, `stream()`), and rename the existing async middleware surface to use the `Async*`/`async_*` prefix to match `httpx2`'s naming convention. Drop `Retry(attempt_timeout=...)` in both worlds.

**Architecture:** Two PRs, one release. **PR 1** (branch `feat/async-prefix-rename`) is a pure mechanical rename: `Middleware → AsyncMiddleware`, `Next → AsyncNext`, `Retry → AsyncRetry`, `Bulkhead → AsyncBulkhead`, `before_request → async_before_request`, etc., plus removal of `attempt_timeout=` from `AsyncRetry`. Zero new functionality. **PR 2** (branch `feat/sync-client`, branched after PR 1 merges) extracts shared helpers into `_internal/`, adds a `threading.Lock` to `RetryBudget`, then lands the sync `Client` + sync middleware/decorators + sync `Retry`/`Bulkhead` + sync `stream()`. Both classes per concept live in the same file (sync + async siblings — pair-per-file, mirrors httpx). After PR 2 merges, cut **one** release (`0.8.0` or `1.0.0`, decided at release time).

**Tech Stack:** Python 3.11+ (`contextlib.contextmanager`, `threading.Lock`, `threading.Semaphore`, `time.sleep`), `httpx2`, `pytest` / `pytest-asyncio` (auto mode), `uv`, `just`, `ruff`, `ty`.

**Source spec:** [`planning/specs/2026-06-07-sync-client-design.md`](../specs/2026-06-07-sync-client-design.md). Read it before starting — the *why* for each decision lives there.

**Commit cadence:** one commit per task. Use the existing `type(scope): subject` format (e.g., `refactor(middleware):`, `feat(client):`, `docs(plan):`).

---

## File structure

### PR 1 — async-prefix rename (branch `feat/async-prefix-rename`)

**Modified:**
- `src/httpware/__init__.py` — public exports renamed
- `src/httpware/client.py` — internal imports updated (`Middleware → AsyncMiddleware`, `Next → AsyncNext`); no behavior change
- `src/httpware/middleware/__init__.py` — `Middleware → AsyncMiddleware`, `Next → AsyncNext`; decorators `before_request/after_response/on_error → async_before_request/async_after_response/async_on_error`
- `src/httpware/middleware/chain.py` — `compose → compose_async`, internal types renamed
- `src/httpware/middleware/resilience/__init__.py` — `Retry → AsyncRetry`, `Bulkhead → AsyncBulkhead`
- `src/httpware/middleware/resilience/retry.py` — `Retry → AsyncRetry`; drop `attempt_timeout=` parameter and related code; drop `builtins.TimeoutError` re-wrap branch (only the asyncio.timeout source raised it)
- `src/httpware/middleware/resilience/bulkhead.py` — `Bulkhead → AsyncBulkhead`
- `tests/*.py` — every `from httpware import …` / `from httpware.middleware… import …` referring to renamed symbols is updated
- `docs/middleware.md` — every code snippet updated
- `docs/resilience.md` — same; `attempt_timeout=` paragraph removed and replaced with httpx2-timeout pointer
- `docs/errors.md` — verify imports
- `docs/testing.md` — examples renamed
- `docs/index.md` — quickstart imports renamed
- `README.md` — quickstart imports renamed
- `planning/engineering.md` — §1 mentions the rename; §3 Seam A re-labelled

**New:** none.

### PR 2 — sync addition (branch `feat/sync-client`)

**Modified:**
- `src/httpware/__init__.py` — adds `Client`, sync `Middleware`/`Next`/`Retry`/`Bulkhead`, sync decorators
- `src/httpware/client.py` — adds `Client` class; existing `AsyncClient` switches to importing helpers from `_internal/`; the inline `_httpx2_exception_mapper`, `_raise_on_status_error`, `_is_streaming_body`, `STREAMING_BODY_MARKER` move out
- `src/httpware/middleware/__init__.py` — adds sync `Middleware` protocol, `Next` type, `before_request`/`after_response`/`on_error` (sync decorators)
- `src/httpware/middleware/chain.py` — adds sync `compose`
- `src/httpware/middleware/resilience/__init__.py` — re-exports sync `Retry` + `Bulkhead`
- `src/httpware/middleware/resilience/retry.py` — adds sync `Retry`; extracts shared `DEFAULT_*` constants if not already module-level (they are)
- `src/httpware/middleware/resilience/bulkhead.py` — adds sync `Bulkhead` using `threading.Semaphore`
- `src/httpware/middleware/resilience/budget.py` — adds `threading.Lock` to `RetryBudget`
- `docs/middleware.md` — sibling sync section
- `docs/resilience.md` — sibling sync sections; bulkhead per-world note
- `docs/errors.md` — note that the exception tree is shared
- `docs/testing.md` — sync example using `httpx2.Client(transport=httpx2.MockTransport(...))`
- `docs/index.md` — quickstart shows both worlds
- `README.md` — same
- `planning/engineering.md` — §1 mentions sync; §3 Seam A entry mentions both worlds; §5 module layout updated

**New:**
- `src/httpware/_internal/exception_mapping.py` — `map_httpx2_exception` pure function
- `src/httpware/_internal/status.py` — `_raise_on_status_error`, `_is_streaming_body_async`, `_is_streaming_body_sync`, `STREAMING_BODY_MARKER`
- `tests/test_client_sync.py` — mirror of `test_client_methods.py`/`test_client_construction.py`/`test_client_lifecycle.py` adapted to `Client`
- `tests/test_retry_sync.py` — mirror of `test_retry.py` for sync `Retry`
- `tests/test_bulkhead_sync.py` — mirror of `test_bulkhead.py` for sync `Bulkhead`
- `tests/test_middleware_sync.py` — mirror of `test_middleware.py` for sync `Middleware`/`compose`/decorators
- `tests/test_client_stream_sync.py` — mirror of `test_client_stream.py`
- `tests/test_retry_budget_threadsafety.py` — concurrent deposit/withdraw stress test
- `tests/test_threading_with_shared_budget.py` — one Client + one AsyncClient sharing one RetryBudget
- `planning/releases/0.8.0.md` (or `1.0.0.md`) — release notes covering both PRs

---

# PART A — PR 1: async-prefix rename (branch `feat/async-prefix-rename`)

## Task A1: Branch + rename `Middleware`/`Next` + phase decorators in `middleware/__init__.py`

**Files:**
- Modify: `src/httpware/middleware/__init__.py`

- [ ] **Step 1: Create the branch**

```bash
git checkout main && git pull && git checkout -b feat/async-prefix-rename
```
Expected: switched to a new branch.

- [ ] **Step 2: Rename `Next` → `AsyncNext`, `Middleware` → `AsyncMiddleware`, decorators**

Replace the contents of `src/httpware/middleware/__init__.py` with:

```python
"""AsyncMiddleware protocol, AsyncNext type, and phase-shortcut decorators.

Middleware operates directly on httpx2.Request / httpx2.Response — there is
no httpware-owned request type. The chain is composed at AsyncClient.__init__
(see client.py) and frozen for the client's lifetime.
"""

from collections.abc import Awaitable, Callable
from typing import Protocol, TypeAlias, runtime_checkable

import httpx2


AsyncNext: TypeAlias = Callable[[httpx2.Request], Awaitable[httpx2.Response]]


@runtime_checkable
class AsyncMiddleware(Protocol):
    """Structural protocol every async middleware satisfies."""

    async def __call__(self, request: httpx2.Request, next: AsyncNext) -> httpx2.Response:  # noqa: A002
        """Process `request`; call `next(request)` to forward, or synthesize a Response."""
        ...


def async_before_request(f: Callable[[httpx2.Request], Awaitable[httpx2.Request]]) -> AsyncMiddleware:
    """Wrap an async request transform into an AsyncMiddleware."""

    class _BeforeRequestMiddleware:
        async def __call__(self, request: httpx2.Request, next: AsyncNext) -> httpx2.Response:  # noqa: A002
            return await next(await f(request))

        def __repr__(self) -> str:
            return f"<async_before_request({f.__qualname__})>"  # ty: ignore[unresolved-attribute]

    return _BeforeRequestMiddleware()


def async_after_response(
    f: Callable[[httpx2.Request, httpx2.Response], Awaitable[httpx2.Response]],
) -> AsyncMiddleware:
    """Wrap an async response transform into an AsyncMiddleware."""

    class _AfterResponseMiddleware:
        async def __call__(self, request: httpx2.Request, next: AsyncNext) -> httpx2.Response:  # noqa: A002
            response = await next(request)
            return await f(request, response)

        def __repr__(self) -> str:
            return f"<async_after_response({f.__qualname__})>"  # ty: ignore[unresolved-attribute]

    return _AfterResponseMiddleware()


def async_on_error(
    f: Callable[[httpx2.Request, Exception], Awaitable[httpx2.Response | None]],
) -> AsyncMiddleware:
    """Wrap an async error handler into an AsyncMiddleware.

    Catches Exception (not BaseException), so asyncio.CancelledError propagates.
    Handler returning None re-raises; returning a Response replaces the failure.
    """

    class _OnErrorMiddleware:
        async def __call__(self, request: httpx2.Request, next: AsyncNext) -> httpx2.Response:  # noqa: A002
            try:
                return await next(request)
            except Exception as exc:
                result = await f(request, exc)
                if result is None:
                    raise
                return result

        def __repr__(self) -> str:
            return f"<async_on_error({f.__qualname__})>"  # ty: ignore[unresolved-attribute]

    return _OnErrorMiddleware()
```

- [ ] **Step 3: Verify file parses**

```bash
uv run python -c "from httpware.middleware import AsyncMiddleware, AsyncNext, async_before_request, async_after_response, async_on_error; print('ok')"
```
Expected: `ok` (the import works in isolation even though dependent modules still reference old names — they will be updated in subsequent tasks).

- [ ] **Step 4: Do NOT run the suite yet**

Tests will fail until Tasks A2–A8 land. Commit at the end of Task A1 isolated rename; the suite goes red until the rename cascade is complete and we re-green it in Task A9. This is acceptable — PR 1 is a single coherent rename.

- [ ] **Step 5: Commit**

```bash
git add src/httpware/middleware/__init__.py
git commit -m "refactor(middleware): rename Middleware/Next/decorators with Async/async_ prefix

Aligns with httpx2's naming convention (sync default, Async* prefix on
the async sibling). Sync versions will land in PR 2.

Part of feat/async-prefix-rename. Suite is intentionally red until the
cascade completes; greens up in the same PR."
```

---

## Task A2: Rename `compose` → `compose_async` in `middleware/chain.py`

**Files:**
- Modify: `src/httpware/middleware/chain.py`

- [ ] **Step 1: Replace `chain.py` contents**

```python
"""Chain composition for the middleware stack."""

import typing
from collections.abc import Awaitable, Callable, Sequence

import httpx2


if typing.TYPE_CHECKING:
    from httpware.middleware import AsyncMiddleware


_AsyncNext: typing.TypeAlias = Callable[[httpx2.Request], Awaitable[httpx2.Response]]


def compose_async(middleware: "Sequence[AsyncMiddleware]", terminal: _AsyncNext) -> _AsyncNext:
    """Fold `middleware` into a single callable around `terminal`.

    The first middleware in the sequence is the outermost wrapper.
    """
    dispatch: _AsyncNext = terminal
    for layer in reversed(middleware):
        dispatch = _wrap(layer, dispatch)
    return dispatch


def _wrap(layer: "AsyncMiddleware", inner: _AsyncNext) -> _AsyncNext:
    async def call(request: httpx2.Request) -> httpx2.Response:
        return await layer(request, inner)

    return call
```

- [ ] **Step 2: Commit**

```bash
git add src/httpware/middleware/chain.py
git commit -m "refactor(middleware/chain): rename compose to compose_async"
```

---

## Task A3: Rename `Retry → AsyncRetry`, drop `attempt_timeout`

**Files:**
- Modify: `src/httpware/middleware/resilience/retry.py`

- [ ] **Step 1: Update imports + class rename + drop attempt_timeout**

Apply these edits in `retry.py`:

(a) Imports section (top of file): change

```python
from httpware.middleware import Next
```

to

```python
from httpware.middleware import AsyncNext
```

Also remove the now-unused `import builtins` (the `builtins.TimeoutError` branch is being removed).

(b) Class definition: rename `class Retry:` to `class AsyncRetry:`. Update the docstring to mention "async retry middleware."

(c) `__init__`: remove the `attempt_timeout: float | None = None` parameter, the `self.attempt_timeout = attempt_timeout` assignment, and any line storing it. The remaining params stay as-is.

(d) `__call__` signature: change `next: Next` to `next: AsyncNext`. The `noqa` comment list shrinks (no more attempt_timeout). Replace with:

```python
async def __call__(self, request: httpx2.Request, next: AsyncNext) -> httpx2.Response:  # noqa: A002, C901, PLR0912 — complexity budget: 3 error clauses + idempotency gate + streaming-body refusal + budget gate + Retry-After branch + backoff
```

(e) `__call__` body: remove the `attempt_timeout` block. The `try:` body that currently reads:

```python
try:
    if self.attempt_timeout is not None:
        async with asyncio.timeout(self.attempt_timeout):
            return await next(request)
    else:
        return await next(request)
except StatusError as exc:
    ...
```

becomes simply:

```python
try:
    return await next(request)
except StatusError as exc:
    ...
```

(f) Remove the entire `except builtins.TimeoutError as exc:` branch (lines ~129–137 in current code). With `asyncio.timeout` gone, no `builtins.TimeoutError` source remains; that branch is unreachable and must be removed. The next-down logic continues at `# ---- retryable failure path`.

(g) Remove the `import asyncio` if no longer used. (Confirm: with `attempt_timeout` gone, `asyncio.timeout` no longer appears. `asyncio.sleep` is *still* the default for `_sleep`, so the import stays.) Re-check after edit; keep `import asyncio` if it's referenced.

- [ ] **Step 2: Commit**

```bash
git add src/httpware/middleware/resilience/retry.py
git commit -m "refactor(retry): rename Retry -> AsyncRetry, drop attempt_timeout

attempt_timeout used asyncio.timeout to bound the whole attempt. It has
no clean sync equivalent and the I/O slice is already covered by
httpx2's per-phase Timeout. Removed from both worlds; users who need
whole-attempt structured cancellation can compose a custom timeout
middleware.

Also drops the now-dead except builtins.TimeoutError branch (the only
source was asyncio.timeout) and the builtins import."
```

---

## Task A4: Rename `Bulkhead → AsyncBulkhead`

**Files:**
- Modify: `src/httpware/middleware/resilience/bulkhead.py`

- [ ] **Step 1: Apply rename**

In `bulkhead.py`:

(a) Change the `from httpware.middleware import Next` import to `from httpware.middleware import AsyncNext`.
(b) Rename `class Bulkhead:` to `class AsyncBulkhead:` and update the docstring to say "async concurrency limiter."
(c) `__call__` signature: change `next: Next` to `next: AsyncNext`.

No other changes.

- [ ] **Step 2: Commit**

```bash
git add src/httpware/middleware/resilience/bulkhead.py
git commit -m "refactor(bulkhead): rename Bulkhead -> AsyncBulkhead"
```

---

## Task A5: Update `resilience/__init__.py` re-exports

**Files:**
- Modify: `src/httpware/middleware/resilience/__init__.py`

- [ ] **Step 1: Replace file contents**

```python
"""Resilience primitives: AsyncBulkhead, AsyncRetry middleware, and RetryBudget token bucket."""

from httpware.middleware.resilience.budget import RetryBudget
from httpware.middleware.resilience.bulkhead import AsyncBulkhead
from httpware.middleware.resilience.retry import AsyncRetry


__all__ = ["AsyncBulkhead", "AsyncRetry", "RetryBudget"]
```

- [ ] **Step 2: Commit**

```bash
git add src/httpware/middleware/resilience/__init__.py
git commit -m "refactor(resilience): update __init__ for Async-prefixed exports"
```

---

## Task A6: Update `client.py` imports

**Files:**
- Modify: `src/httpware/client.py`

- [ ] **Step 1: Update middleware imports**

In `client.py`, change the import block:

```python
from httpware.middleware import Middleware, Next
from httpware.middleware.chain import compose
```

to:

```python
from httpware.middleware import AsyncMiddleware, AsyncNext
from httpware.middleware.chain import compose_async
```

- [ ] **Step 2: Update class annotations and method signatures**

In `client.py`, do an exact replace (case-sensitive, whole-word where the form fits):

- `_user_middleware: tuple[Middleware, ...]` → `_user_middleware: tuple[AsyncMiddleware, ...]`
- `_dispatch: Next` → `_dispatch: AsyncNext`
- Parameter `middleware: Sequence[Middleware] = ()` → `middleware: Sequence[AsyncMiddleware] = ()`
- `self._dispatch = compose(self._user_middleware, self._terminal)` → `self._dispatch = compose_async(self._user_middleware, self._terminal)`

- [ ] **Step 3: Commit**

```bash
git add src/httpware/client.py
git commit -m "refactor(client): use AsyncMiddleware/AsyncNext/compose_async"
```

---

## Task A7: Update top-level `__init__.py` public exports

**Files:**
- Modify: `src/httpware/__init__.py`

- [ ] **Step 1: Replace file contents**

```python
"""httpware — thin async HTTP client wrapper over httpx2."""

from httpware.client import AsyncClient
from httpware.decoders import ResponseDecoder
from httpware.errors import (
    STATUS_TO_EXCEPTION,
    BadRequestError,
    BulkheadFullError,
    ClientError,
    ClientStatusError,
    ConflictError,
    ForbiddenError,
    InternalServerError,
    NetworkError,
    NotFoundError,
    RateLimitedError,
    RetryBudgetExhaustedError,
    ServerStatusError,
    ServiceUnavailableError,
    StatusError,
    TimeoutError,  # noqa: A004
    TransportError,
    UnauthorizedError,
    UnprocessableEntityError,
)
from httpware.middleware import (
    AsyncMiddleware,
    AsyncNext,
    async_after_response,
    async_before_request,
    async_on_error,
)
from httpware.middleware.resilience import AsyncBulkhead, AsyncRetry, RetryBudget


__all__ = [
    "STATUS_TO_EXCEPTION",
    "AsyncBulkhead",
    "AsyncClient",
    "AsyncMiddleware",
    "AsyncNext",
    "AsyncRetry",
    "BadRequestError",
    "BulkheadFullError",
    "ClientError",
    "ClientStatusError",
    "ConflictError",
    "ForbiddenError",
    "InternalServerError",
    "NetworkError",
    "NotFoundError",
    "RateLimitedError",
    "ResponseDecoder",
    "RetryBudget",
    "RetryBudgetExhaustedError",
    "ServerStatusError",
    "ServiceUnavailableError",
    "StatusError",
    "TimeoutError",
    "TransportError",
    "UnauthorizedError",
    "UnprocessableEntityError",
    "async_after_response",
    "async_before_request",
    "async_on_error",
]
```

- [ ] **Step 2: Commit**

```bash
git add src/httpware/__init__.py
git commit -m "refactor(public-api): export AsyncMiddleware/AsyncRetry/AsyncBulkhead + async_* decorators"
```

---

## Task A8: Update `tests/` to use the new names

**Files:**
- Modify: every test file currently importing the renamed symbols

- [ ] **Step 1: Survey the affected test files**

```bash
grep -lE 'from httpware import .*\b(Middleware|Next|Retry|Bulkhead|before_request|after_response|on_error)\b|from httpware\.middleware import|from httpware\.middleware\.chain import compose|from httpware\.middleware\.resilience' tests/
```

Expected list (verify it matches):
- `tests/test_bulkhead.py`
- `tests/test_bulkhead_props.py`
- `tests/test_client_middleware_wiring.py`
- `tests/test_client_stream.py`
- `tests/test_middleware.py`
- `tests/test_observability.py`
- `tests/test_public_api.py`
- `tests/test_retry.py`
- `tests/test_retry_props.py`

(There may be others; trust the grep output.)

- [ ] **Step 2: Apply the rename across tests**

For each file in the survey list, apply these substitutions (use Edit with `replace_all=True` per occurrence; do not batch-sed because some tests reference the literal token names in `pytest.raises(match=...)` strings):

In every import statement (only):
- `from httpware import Middleware` → `from httpware import AsyncMiddleware`
- `from httpware import …, Middleware, …` → `…, AsyncMiddleware, …`
- `from httpware import Next` → `from httpware import AsyncNext`
- `from httpware.middleware import Middleware, Next` → `from httpware.middleware import AsyncMiddleware, AsyncNext`
- `from httpware.middleware import (Middleware, Next, after_response, before_request, on_error,)` → `from httpware.middleware import (AsyncMiddleware, AsyncNext, async_after_response, async_before_request, async_on_error,)`
- `from httpware.middleware.chain import compose` → `from httpware.middleware.chain import compose_async`
- `from httpware.middleware.resilience.bulkhead import Bulkhead` → `from httpware.middleware.resilience.bulkhead import AsyncBulkhead`
- `from httpware.middleware.resilience.retry import (..., Retry)` → `from httpware.middleware.resilience.retry import (..., AsyncRetry)`

In test bodies — every occurrence of:
- `Middleware` as a class reference → `AsyncMiddleware`
- `Next` as a type reference → `AsyncNext`
- `Retry(` as a constructor call → `AsyncRetry(`
- `Bulkhead(` as a constructor call → `AsyncBulkhead(`
- `compose(` as a function call → `compose_async(`
- `@before_request` → `@async_before_request`
- `@after_response` → `@async_after_response`
- `@on_error` → `@async_on_error`

For each file, after editing, eyeball the diff for any string-matches inside `pytest.raises(match=...)` or test-name strings that should NOT have been changed (e.g., a docstring saying "Tests for the Middleware protocol" should become "Tests for the AsyncMiddleware protocol", which is correct).

- [ ] **Step 3: Drop attempt_timeout tests**

In `tests/test_retry.py`, find every test that exercises `attempt_timeout=` (search: `attempt_timeout`). Remove those tests entirely (delete the function bodies). Expected: 2–4 tests touching this. If a test mixes `attempt_timeout` with other assertions, split it: keep the non-timeout assertions in a renamed test, remove the timeout-specific assertions.

If `tests/test_retry.py` imports `asyncio.TimeoutError` solely for the attempt_timeout tests, drop that import too.

- [ ] **Step 4: Update `tests/test_public_api.py`**

This file tests the public surface. Replace `Middleware`/`Retry`/`Bulkhead`/`Next`/decorator names in its assertions with their renamed counterparts. The structure (asserting `__all__` shape or symbol presence) is unchanged.

- [ ] **Step 5: Run the suite**

```bash
just test
```
Expected: ALL PASS (the rename is mechanical; behaviors unchanged). If any test fails for a reason other than a stale import or stale name, stop and investigate — that's a real signal.

- [ ] **Step 6: Run lint**

```bash
just lint
```
Expected: clean. If `ruff` flags any rename leftover, fix inline and re-run.

- [ ] **Step 7: Commit**

```bash
git add tests/
git commit -m "test: update suite for Async*-prefixed names; drop attempt_timeout tests"
```

---

## Task A9: Update `docs/` for the rename

**Files:**
- Modify: `docs/middleware.md`, `docs/resilience.md`, `docs/errors.md`, `docs/testing.md`, `docs/index.md`, `README.md`

- [ ] **Step 1: Update `docs/middleware.md`**

Read the file. Apply the same substitutions as Task A8 step 2 to every code block and prose mention:
- `Middleware` (class) → `AsyncMiddleware`
- `Next` (type) → `AsyncNext`
- `@before_request` / `@after_response` / `@on_error` → `@async_before_request` / `@async_after_response` / `@async_on_error`
- `from httpware import Middleware, Next, ...` → `from httpware import AsyncMiddleware, AsyncNext, ...`

Prose context: any line saying "the Middleware protocol" should become "the AsyncMiddleware protocol." Section headings get the same treatment.

- [ ] **Step 2: Update `docs/resilience.md`**

Same rename for `Retry → AsyncRetry`, `Bulkhead → AsyncBulkhead`, etc. **Also remove the `attempt_timeout` documentation:**

Find the `attempt_timeout` row in the parameter tables and the surrounding prose discussing it. Delete the row + the discussion paragraph. Insert a short replacement paragraph (1–2 sentences) at the end of the "AsyncRetry parameters" section:

```markdown
For a whole-attempt wall-clock bound, use `httpx2.Timeout` on the client or
pass `timeout=` per request. `httpware` does not own a structured-cancellation
timeout knob.
```

- [ ] **Step 3: Update `docs/errors.md`, `docs/testing.md`, `docs/index.md`, `README.md`**

Same import/symbol rename per file. The `errors.md` content is mostly about the exception tree, which is unchanged — the only edits should be code snippets importing renamed middleware. `testing.md`'s `MockTransport` example uses `AsyncClient` (already correctly named) — verify the imports of `Middleware`/etc. are updated. `index.md` and `README.md` quickstarts get the same treatment.

- [ ] **Step 4: Verify mkdocs build**

```bash
uv run mkdocs build --strict 2>&1 | tail -20
```
Expected: build OK, no broken cross-references. If mkdocs is not in the project's lint group, install it: `uv run --with mkdocs-material mkdocs build --strict`.

- [ ] **Step 5: Commit**

```bash
git add docs/ README.md
git commit -m "docs: update for Async*/async_* rename + drop attempt_timeout"
```

---

## Task A10: Update `planning/engineering.md`

**Files:**
- Modify: `planning/engineering.md`

- [ ] **Step 1: Update §1 (project intent)**

Find the v0.7.0 sentence ("As of 0.7.0, the first-cut user-docs surface is live..."). Append a new sentence:

```markdown
The next release renames the async middleware surface to use the `Async*`/`async_*` prefix (aligning with httpx2's convention) and removes the seldom-used `attempt_timeout=` kwarg from `AsyncRetry` — see `planning/specs/2026-06-07-sync-client-design.md` for the rationale.
```

- [ ] **Step 2: Update §3 Seam A**

Change the heading "### Seam A: `AsyncClient ↔ Middleware`" to "### Seam A: `AsyncClient ↔ AsyncMiddleware`" and update the prose to refer to `AsyncMiddleware`/`AsyncNext`/`compose_async` everywhere. The contract is unchanged.

- [ ] **Step 3: Commit**

```bash
git add planning/engineering.md
git commit -m "docs(engineering): note Async*/async_* rename + attempt_timeout removal"
```

---

## Task A11: Open PR 1

- [ ] **Step 1: Push branch**

```bash
git push -u origin feat/async-prefix-rename
```

- [ ] **Step 2: Open the PR**

```bash
gh pr create --title "refactor: rename async middleware surface with Async*/async_* prefix; drop attempt_timeout" --body "$(cat <<'EOF'
## Summary
- Renames `Middleware → AsyncMiddleware`, `Next → AsyncNext`, `Retry → AsyncRetry`, `Bulkhead → AsyncBulkhead`, `before_request/after_response/on_error → async_before_request/...`, `compose → compose_async` to align with httpx2's naming convention (sync default, `Async*` prefix on the async sibling).
- Removes `AsyncRetry(attempt_timeout=...)`. Whole-attempt wall-clock bounds were the only feature that depended on `asyncio.timeout` and have no clean sync equivalent. Users wanting whole-attempt bounds can compose a custom timeout middleware; per-phase I/O bounds remain available via `httpx2.Timeout`.
- Pure mechanical rename. Zero behavior change.

Part 1 of 2. Part 2 (sync `Client` + sync middleware) lands separately and the combined work cuts one release.

Source spec: `planning/specs/2026-06-07-sync-client-design.md`.

## Breaking changes
- All async middleware classes/types renamed (`Async*`/`async_*` prefix).
- `AsyncRetry(attempt_timeout=...)` removed.

## Test plan
- [x] `just lint` clean
- [x] `just test` all green (coverage maintained at 100%)
- [ ] reviewer eyeball: confirm no doc/snippet references the old names
EOF
)"
```

- [ ] **Step 3: After PR 1 merges to `main`**

Wait for review + merge. PR 2 branches from `main` only after PR 1 is in.

---

# PART B — PR 2: sync `Client` + helpers + threading lock (branch `feat/sync-client`)

Wait for PR 1 to merge before starting Part B.

## Task B1: Branch from updated `main`

- [ ] **Step 1: Create the branch**

```bash
git checkout main && git pull && git checkout -b feat/sync-client
```
Expected: switched to `feat/sync-client` with PR 1's rename already in.

---

## Task B2: Add `threading.Lock` to `RetryBudget`

**Files:**
- Modify: `src/httpware/middleware/resilience/budget.py`
- Modify: `tests/test_budget.py` — existing tests are already deterministic via `_now` injection; lock is invisible. Just confirm they still pass.
- New: `tests/test_retry_budget_threadsafety.py`

- [ ] **Step 1: Update `budget.py`**

Replace the file with:

```python
"""Finagle-style token-bucket retry budget.

See planning/specs/2026-06-05-retry-and-retry-budget-design.md for the contract.

Thread-safe and asyncio-safe: all mutations go through a threading.Lock.
A single RetryBudget instance is safe to share across threads, across
coroutines on one event loop, and across (sync Client, AsyncClient) pairs
in the same process.
"""

import threading
import time
from collections import deque
from collections.abc import Callable


class RetryBudget:
    """Token-bucket budget bounding retry rate to prevent retry storms.

    Each request deposits a token; each retry attempts to withdraw one.
    Available retries are bounded by `percent_can_retry` of recent deposits,
    plus a `min_retries_per_sec * ttl` floor.
    """

    def __init__(
        self,
        *,
        ttl: float = 10.0,
        min_retries_per_sec: float = 10.0,
        percent_can_retry: float = 0.2,
        _now: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl = ttl
        self._min_retries_per_sec = min_retries_per_sec
        self._percent_can_retry = percent_can_retry
        self._now = _now
        self._lock = threading.Lock()
        self._deposits: deque[float] = deque()
        self._withdrawn: deque[float] = deque()

    def _purge(self, now: float) -> None:
        # Caller must hold self._lock.
        # Strict `< cutoff` keeps entries at exactly `now - ttl`: window is [now - ttl, now].
        cutoff = now - self._ttl
        while self._deposits and self._deposits[0] < cutoff:
            self._deposits.popleft()
        while self._withdrawn and self._withdrawn[0] < cutoff:
            self._withdrawn.popleft()

    def deposit(self) -> None:
        """Record a request (success or failure attempt). Adds one token."""
        now = self._now()
        with self._lock:
            self._purge(now)
            self._deposits.append(now)

    def try_withdraw(self) -> bool:
        """Atomically attempt to spend one retry token.

        Returns True if a retry is permitted, False if the budget is exhausted.
        Never blocks.
        """
        now = self._now()
        with self._lock:
            self._purge(now)
            floor = int(self._min_retries_per_sec * self._ttl)
            ceiling = int(len(self._deposits) * self._percent_can_retry) + floor
            if len(self._withdrawn) >= ceiling:
                return False
            self._withdrawn.append(now)
            return True
```

- [ ] **Step 2: Run existing budget tests**

```bash
uv run pytest tests/test_budget.py tests/test_budget_props.py -v
```
Expected: all PASS (lock is invisible to single-threaded tests).

- [ ] **Step 3: Write new thread-safety test**

Create `tests/test_retry_budget_threadsafety.py`:

```python
"""Thread-safety test for RetryBudget.

Sync Client may share a RetryBudget across a ThreadPoolExecutor. Concurrent
deposit() / try_withdraw() calls must not corrupt the internal deques. We
spawn many threads doing many ops and assert no exception, sane counters.
"""

import threading

from httpware.middleware.resilience.budget import RetryBudget


_N_THREADS = 16
_N_OPS_PER_THREAD = 1000


def test_concurrent_deposit_withdraw_does_not_corrupt() -> None:
    budget = RetryBudget(ttl=60.0, min_retries_per_sec=1000.0, percent_can_retry=0.5)
    errors: list[BaseException] = []
    barrier = threading.Barrier(_N_THREADS)

    def worker() -> None:
        try:
            barrier.wait()
            for _ in range(_N_OPS_PER_THREAD):
                budget.deposit()
                budget.try_withdraw()
        except BaseException as exc:  # noqa: BLE001 — collect any failure for the assert
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(_N_THREADS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    # Each thread did _N_OPS_PER_THREAD deposits; budget must have accepted them all
    # (and possibly some withdrawals — we don't assert withdrawn count; the ceiling
    # formula doesn't guarantee how many succeed).
    assert len(budget._deposits) <= _N_THREADS * _N_OPS_PER_THREAD  # noqa: SLF001 — internal state check
    assert len(budget._deposits) > 0  # noqa: SLF001


def test_concurrent_only_deposit_count_matches() -> None:
    budget = RetryBudget(ttl=60.0)
    barrier = threading.Barrier(_N_THREADS)

    def worker() -> None:
        barrier.wait()
        for _ in range(_N_OPS_PER_THREAD):
            budget.deposit()

    threads = [threading.Thread(target=worker) for _ in range(_N_THREADS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # With no withdraws and no TTL expiry (60s window, sub-second test), every
    # deposit lands in the deque. Exact equality proves no deposits were lost
    # to a race.
    assert len(budget._deposits) == _N_THREADS * _N_OPS_PER_THREAD  # noqa: SLF001
```

- [ ] **Step 4: Run the new test**

```bash
uv run pytest tests/test_retry_budget_threadsafety.py -v
```
Expected: both tests PASS. If `test_concurrent_only_deposit_count_matches` fails (count mismatch), the lock is missing somewhere — re-inspect `budget.py`.

- [ ] **Step 5: Commit**

```bash
git add src/httpware/middleware/resilience/budget.py tests/test_retry_budget_threadsafety.py
git commit -m "feat(budget): make RetryBudget thread-safe via threading.Lock

Sync Client (landing in this PR) may share a Retry/RetryBudget across
a ThreadPoolExecutor. The token-bucket deques would race without a lock.
Uncontended lock cost in CPython is ~50-100ns per op — negligible vs
HTTP latency. Existing async paths are unaffected; lock is taken
unconditionally for one type, one mental model, no flag at the call
site."
```

---

## Task B3: Extract shared helper — `_internal/exception_mapping.py`

**Files:**
- New: `src/httpware/_internal/exception_mapping.py`

- [ ] **Step 1: Create the new module**

```python
"""httpx2 → httpware exception mapping.

Pure function used by both Client._terminal and AsyncClient._terminal,
and by both stream() methods. Clause ordering: TimeoutException →
InvalidURL/CookieConflict → NetworkError → HTTPError (subclass before
parent so the right type wins).
"""

import httpx2

from httpware.errors import NetworkError, TimeoutError, TransportError  # noqa: A004


def map_httpx2_exception(exc: BaseException) -> NetworkError | TimeoutError | TransportError:
    """Map an httpx2 exception to its httpware equivalent.

    Order is significant: more-specific httpx2 types must match before more
    general ones. We return the mapped exception; the caller does `raise ... from exc`.
    """
    if isinstance(exc, httpx2.TimeoutException):
        return TimeoutError(str(exc))
    if isinstance(exc, (httpx2.InvalidURL, httpx2.CookieConflict)):
        return TransportError(str(exc))
    if isinstance(exc, httpx2.NetworkError):
        return NetworkError(str(exc))
    if isinstance(exc, httpx2.HTTPError):
        return TransportError(str(exc))
    return TransportError(str(exc))  # pragma: no cover — defensive default; httpx2.HTTPError is the root
```

Note: `TimeoutError` here is `httpware.errors.TimeoutError` (which inherits from both `httpware.ClientError` and `builtins.TimeoutError`) — the shadowing is intentional and matches the existing `client.py` import style.

- [ ] **Step 2: Quick smoke check**

```bash
uv run python -c "
from httpware._internal.exception_mapping import map_httpx2_exception
import httpx2
exc = httpx2.ConnectError('boom')
mapped = map_httpx2_exception(exc)
print(type(mapped).__name__, str(mapped))
"
```
Expected: `NetworkError boom`.

- [ ] **Step 3: Commit**

```bash
git add src/httpware/_internal/exception_mapping.py
git commit -m "refactor(internal): extract map_httpx2_exception to _internal/exception_mapping.py

Shared by AsyncClient (and the upcoming Client). Pure function; the
existing _httpx2_exception_mapper context manager in client.py will
delegate to this in Task B5."
```

---

## Task B4: Extract shared helpers — `_internal/status.py`

**Files:**
- New: `src/httpware/_internal/status.py`

- [ ] **Step 1: Create the new module**

```python
"""Status-code dispatch + streaming-body detection.

Shared by Client and AsyncClient. The STREAMING_BODY_MARKER is the public
extensions key both Retry and AsyncRetry read; renaming it is breaking.
"""

import typing
from http import HTTPStatus

import httpx2

from httpware.errors import STATUS_TO_EXCEPTION, ClientStatusError, ServerStatusError


STREAMING_BODY_MARKER = "httpware.streaming_body"
"""Set on ``httpx2.Request.extensions`` when content/data/files is a non-replayable
iterable (async-iterable for AsyncClient, sync iterator/generator for Client).
Retry / AsyncRetry read this marker to refuse retrying a streamed-body request
(the consumed iterator cannot replay across attempts)."""


def _raise_on_status_error(response: httpx2.Response) -> None:
    """Raise the appropriate StatusError subclass for a 4xx/5xx response. No-op for 2xx/3xx."""
    status = response.status_code
    if HTTPStatus.BAD_REQUEST <= status < 600:  # noqa: PLR2004 — 600 is the synthetic upper bound for 5xx
        exc_class = STATUS_TO_EXCEPTION.get(
            status,
            ClientStatusError if status < HTTPStatus.INTERNAL_SERVER_ERROR else ServerStatusError,
        )
        raise exc_class(response)


def _is_streaming_body_async(value: typing.Any) -> bool:
    """Return True if value is an async-iterable that cannot be safely replayed for retry."""
    if value is None:
        return False
    if isinstance(value, (bytes, bytearray, memoryview, str, dict)):
        return False
    return hasattr(value, "__aiter__")


def _is_streaming_body_sync(value: typing.Any) -> bool:
    """Return True if value is a sync iterable body that cannot be safely replayed for retry."""
    if value is None:
        return False
    if isinstance(value, (bytes, bytearray, memoryview, str, dict, list, tuple)):
        return False
    return hasattr(value, "__iter__")
```

- [ ] **Step 2: Smoke check**

```bash
uv run python -c "
from httpware._internal.status import (
    STREAMING_BODY_MARKER, _raise_on_status_error,
    _is_streaming_body_async, _is_streaming_body_sync,
)
print(STREAMING_BODY_MARKER)
print(_is_streaming_body_sync(b'bytes'), _is_streaming_body_sync([1, 2]), _is_streaming_body_sync(iter([1, 2])))
"
```
Expected: `httpware.streaming_body`, `False False True`.

- [ ] **Step 3: Commit**

```bash
git add src/httpware/_internal/status.py
git commit -m "refactor(internal): extract status raise + streaming-body predicates to _internal/status.py

Both worlds share the status-code dispatch (already pure sync) and the
STREAMING_BODY_MARKER. Predicates split: _is_streaming_body_async checks
__aiter__; _is_streaming_body_sync checks __iter__ with list/tuple in the
safe-list (common in sync code, never streaming)."
```

---

## Task B5: Refactor `client.py` to use the new helpers

**Files:**
- Modify: `src/httpware/client.py`
- Modify: `src/httpware/middleware/resilience/retry.py` (import path for `STREAMING_BODY_MARKER`)
- Modify: `tests/test_retry.py` (import path for `_is_streaming_body`)

- [ ] **Step 1: Update `client.py` imports**

Add to the existing imports:

```python
from httpware._internal.exception_mapping import map_httpx2_exception
from httpware._internal.status import (
    STREAMING_BODY_MARKER,
    _is_streaming_body_async,
    _raise_on_status_error,
)
```

Remove the now-duplicate definitions from `client.py`:
- The `_httpx2_exception_mapper` `asynccontextmanager` body — replace its dispatch with a single `raise map_httpx2_exception(exc) from exc` per the cm pattern (see step 2).
- `_raise_on_status_error` — delete from `client.py` (imported from `_internal/status.py`).
- `_is_streaming_body` — delete from `client.py`; the rename below also drops it from the public path.
- `STREAMING_BODY_MARKER` — delete the constant; imported from `_internal/status.py`.

- [ ] **Step 2: Update `_httpx2_exception_mapper` body**

Replace the `try/except` chain inside `_httpx2_exception_mapper` with:

```python
@contextlib.asynccontextmanager
async def _httpx2_exception_mapper() -> AsyncIterator[None]:
    """Map httpx2 exceptions to httpware exceptions. Shared by AsyncClient._terminal and stream()."""
    try:
        yield
    except httpx2.HTTPError as exc:
        raise map_httpx2_exception(exc) from exc
    except (httpx2.InvalidURL, httpx2.CookieConflict) as exc:
        raise map_httpx2_exception(exc) from exc
```

Note: `(InvalidURL, CookieConflict)` are caught separately because they are NOT `HTTPError` subclasses in httpx2. The `map_httpx2_exception` dispatch handles both — these `except` branches just route them to the same function.

- [ ] **Step 3: Update `_request_with_body` streaming-body check**

In `_request_with_body`, replace the `_is_streaming_body(...)` calls with `_is_streaming_body_async(...)` (the function is named for its world).

- [ ] **Step 4: Update `retry.py` import**

In `src/httpware/middleware/resilience/retry.py`, change:

```python
from httpware.client import STREAMING_BODY_MARKER
```

to:

```python
from httpware._internal.status import STREAMING_BODY_MARKER
```

This unbinds `retry.py` from `client.py` (cleaner — retry shouldn't depend on the client module for a marker constant).

- [ ] **Step 5: Update `tests/test_retry.py` import**

In `tests/test_retry.py`, change:

```python
from httpware.client import _is_streaming_body
```

to:

```python
from httpware._internal.status import _is_streaming_body_async as _is_streaming_body
```

(The alias keeps the in-test name short; the only test usage is `assert _is_streaming_body(value) is True/False`.)

- [ ] **Step 6: Run the suite**

```bash
just test
```
Expected: ALL PASS. The refactor is byte-for-byte behavior-equivalent.

- [ ] **Step 7: Run lint**

```bash
just lint
```
Expected: clean.

- [ ] **Step 8: Commit**

```bash
git add src/httpware/client.py src/httpware/middleware/resilience/retry.py tests/test_retry.py
git commit -m "refactor(client): use _internal/exception_mapping + _internal/status helpers

Pulls map_httpx2_exception, _raise_on_status_error, _is_streaming_body_*,
and STREAMING_BODY_MARKER out of client.py into _internal/. Behavior
unchanged; sets up Client (sync) to share the same dispatch."
```

---

## Task B6: Add sync `Middleware` protocol + `Next` type + sync decorators

**Files:**
- Modify: `src/httpware/middleware/__init__.py`

- [ ] **Step 1: Add sync surface**

Append to `src/httpware/middleware/__init__.py`:

```python


Next: TypeAlias = Callable[[httpx2.Request], httpx2.Response]


@runtime_checkable
class Middleware(Protocol):
    """Structural protocol every sync middleware satisfies."""

    def __call__(self, request: httpx2.Request, next: Next) -> httpx2.Response:  # noqa: A002
        """Process `request`; call `next(request)` to forward, or synthesize a Response."""
        ...


def before_request(f: Callable[[httpx2.Request], httpx2.Request]) -> Middleware:
    """Wrap a sync request transform into a Middleware."""

    class _BeforeRequestMiddleware:
        def __call__(self, request: httpx2.Request, next: Next) -> httpx2.Response:  # noqa: A002
            return next(f(request))

        def __repr__(self) -> str:
            return f"<before_request({f.__qualname__})>"  # ty: ignore[unresolved-attribute]

    return _BeforeRequestMiddleware()


def after_response(
    f: Callable[[httpx2.Request, httpx2.Response], httpx2.Response],
) -> Middleware:
    """Wrap a sync response transform into a Middleware."""

    class _AfterResponseMiddleware:
        def __call__(self, request: httpx2.Request, next: Next) -> httpx2.Response:  # noqa: A002
            response = next(request)
            return f(request, response)

        def __repr__(self) -> str:
            return f"<after_response({f.__qualname__})>"  # ty: ignore[unresolved-attribute]

    return _AfterResponseMiddleware()


def on_error(
    f: Callable[[httpx2.Request, Exception], httpx2.Response | None],
) -> Middleware:
    """Wrap a sync error handler into a Middleware.

    Catches Exception (not BaseException), so KeyboardInterrupt / SystemExit propagate.
    Handler returning None re-raises; returning a Response replaces the failure.
    """

    class _OnErrorMiddleware:
        def __call__(self, request: httpx2.Request, next: Next) -> httpx2.Response:  # noqa: A002
            try:
                return next(request)
            except Exception as exc:
                result = f(request, exc)
                if result is None:
                    raise
                return result

        def __repr__(self) -> str:
            return f"<on_error({f.__qualname__})>"  # ty: ignore[unresolved-attribute]

    return _OnErrorMiddleware()
```

- [ ] **Step 2: Smoke check**

```bash
uv run python -c "from httpware.middleware import Middleware, Next, before_request, after_response, on_error; print('ok')"
```
Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
git add src/httpware/middleware/__init__.py
git commit -m "feat(middleware): add sync Middleware protocol + Next + sync decorators"
```

---

## Task B7: Add sync `compose` to `middleware/chain.py`

**Files:**
- Modify: `src/httpware/middleware/chain.py`

- [ ] **Step 1: Append sync `compose`**

Add to `src/httpware/middleware/chain.py` (alongside the existing `compose_async`):

```python


if typing.TYPE_CHECKING:
    from httpware.middleware import Middleware


_Next: typing.TypeAlias = Callable[[httpx2.Request], httpx2.Response]


def compose(middleware: "Sequence[Middleware]", terminal: _Next) -> _Next:
    """Fold sync `middleware` into a single callable around sync `terminal`.

    The first middleware in the sequence is the outermost wrapper.
    """
    dispatch: _Next = terminal
    for layer in reversed(middleware):
        dispatch = _wrap_sync(layer, dispatch)
    return dispatch


def _wrap_sync(layer: "Middleware", inner: _Next) -> _Next:
    def call(request: httpx2.Request) -> httpx2.Response:
        return layer(request, inner)

    return call
```

The existing `compose_async` and `_wrap` are untouched. The two `TYPE_CHECKING` blocks coexist (Python merges the same conditional cleanly).

- [ ] **Step 2: Commit**

```bash
git add src/httpware/middleware/chain.py
git commit -m "feat(middleware/chain): add sync compose alongside compose_async"
```

---

## Task B8: Write `test_middleware_sync.py`

**Files:**
- New: `tests/test_middleware_sync.py`

- [ ] **Step 1: Write the file**

```python
"""Tests for the sync Middleware protocol, Next type, chain composition, and decorators."""

from http import HTTPStatus

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


def _make_response(status: int = HTTPStatus.OK, *, request: httpx2.Request | None = None) -> httpx2.Response:
    if request is None:  # pragma: no cover
        request = _make_request()
    return httpx2.Response(status, request=request)


def test_middleware_protocol_is_runtime_checkable() -> None:
    class _OkMiddleware:
        def __call__(self, request: httpx2.Request, next: Next) -> httpx2.Response:  # noqa: A002  # pragma: no cover
            return next(request)

    assert isinstance(_OkMiddleware(), Middleware)


def test_empty_chain_calls_terminal_directly() -> None:
    seen: list[httpx2.Request] = []

    def terminal(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return _make_response(200, request=request)

    dispatch = compose((), terminal)
    request = _make_request()
    response = dispatch(request)
    assert response.status_code == HTTPStatus.OK
    assert seen == [request]


def test_chain_runs_middleware_in_order() -> None:
    order: list[str] = []

    class _M:
        def __init__(self, label: str) -> None:
            self.label = label

        def __call__(self, request: httpx2.Request, next: Next) -> httpx2.Response:  # noqa: A002
            order.append(f"{self.label}.before")
            response = next(request)
            order.append(f"{self.label}.after")
            return response

    def terminal(request: httpx2.Request) -> httpx2.Response:
        order.append("terminal")
        return _make_response(200, request=request)

    dispatch = compose((_M("a"), _M("b")), terminal)
    dispatch(_make_request())
    assert order == ["a.before", "b.before", "terminal", "b.after", "a.after"]


def test_before_request_decorator_transforms_request() -> None:
    @before_request
    def add_header(request: httpx2.Request) -> httpx2.Request:
        return httpx2.Request(request.method, request.url, headers={**request.headers, "X-Custom": "1"})

    captured: list[httpx2.Request] = []

    def terminal(request: httpx2.Request) -> httpx2.Response:
        captured.append(request)
        return _make_response(200, request=request)

    dispatch = compose((add_header,), terminal)
    dispatch(_make_request())
    assert captured[0].headers["x-custom"] == "1"


def test_after_response_decorator_transforms_response() -> None:
    @after_response
    def upgrade_status(request: httpx2.Request, response: httpx2.Response) -> httpx2.Response:
        return httpx2.Response(HTTPStatus.IM_USED, request=request, headers=response.headers, content=response.content)

    def terminal(request: httpx2.Request) -> httpx2.Response:
        return _make_response(HTTPStatus.OK, request=request)

    dispatch = compose((upgrade_status,), terminal)
    response = dispatch(_make_request())
    assert response.status_code == HTTPStatus.IM_USED


def test_on_error_decorator_can_translate_exception() -> None:
    @on_error
    def swallow(request: httpx2.Request, exc: Exception) -> httpx2.Response | None:
        if isinstance(exc, RuntimeError) and str(exc) == "boom":
            return _make_response(HTTPStatus.SERVICE_UNAVAILABLE, request=request)
        return None  # pragma: no cover

    def terminal(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        msg = "boom"
        raise RuntimeError(msg)

    dispatch = compose((swallow,), terminal)
    response = dispatch(_make_request())
    assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE


def test_on_error_returns_none_reraises() -> None:
    @on_error
    def passthrough(
        request: httpx2.Request,  # noqa: ARG001
        exc: Exception,  # noqa: ARG001
    ) -> httpx2.Response | None:
        return None

    def terminal(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        msg = "boom"
        raise RuntimeError(msg)

    dispatch = compose((passthrough,), terminal)
    with pytest.raises(RuntimeError, match="boom"):
        dispatch(_make_request())


def test_before_request_repr() -> None:
    @before_request
    def my_transform(request: httpx2.Request) -> httpx2.Request:
        return request  # pragma: no cover

    assert "before_request" in repr(my_transform)
    assert "my_transform" in repr(my_transform)


def test_after_response_repr() -> None:
    @after_response
    def my_transform(request: httpx2.Request, response: httpx2.Response) -> httpx2.Response:  # noqa: ARG001
        return response  # pragma: no cover

    assert "after_response" in repr(my_transform)
    assert "my_transform" in repr(my_transform)


def test_on_error_repr() -> None:
    @on_error
    def my_handler(request: httpx2.Request, exc: Exception) -> httpx2.Response | None:  # noqa: ARG001
        return None  # pragma: no cover

    assert "on_error" in repr(my_handler)
    assert "my_handler" in repr(my_handler)
```

- [ ] **Step 2: Run**

```bash
uv run pytest tests/test_middleware_sync.py -v
```
Expected: all PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_middleware_sync.py
git commit -m "test(middleware): cover sync Middleware/Next/compose/decorators"
```

---

## Task B9: Add sync `Retry` to `retry.py`

**Files:**
- Modify: `src/httpware/middleware/resilience/retry.py`

- [ ] **Step 1: Add the sync class**

Append to `src/httpware/middleware/resilience/retry.py` (after `class AsyncRetry:`):

```python


import time  # near the top of the file alongside the other stdlib imports


from httpware.middleware import Next  # near other from-imports


class Retry:
    """Sync retry middleware. Mirror of AsyncRetry; uses time.sleep instead of asyncio.sleep."""

    def __init__(  # noqa: PLR0913 — retry policy has many orthogonal knobs; a dataclass would be worse
        self,
        *,
        max_attempts: int = 3,
        base_delay: float = 0.1,
        max_delay: float = 5.0,
        retry_status_codes: frozenset[int] = DEFAULT_RETRY_STATUS_CODES,
        retry_methods: frozenset[str] = DEFAULT_IDEMPOTENT_METHODS,
        respect_retry_after: bool = True,
        budget: RetryBudget | None = None,
        _sleep: typing.Callable[[float], None] = time.sleep,
    ) -> None:
        if max_attempts < 1:
            raise ValueError(_MAX_ATTEMPTS_INVALID)
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.retry_status_codes = retry_status_codes
        self.retry_methods = retry_methods
        self.respect_retry_after = respect_retry_after
        self.budget = budget if budget is not None else RetryBudget()
        self._sleep = _sleep

    def __call__(self, request: httpx2.Request, next: Next) -> httpx2.Response:  # noqa: A002, C901, PLR0912 — same complexity rationale as AsyncRetry
        """Process a request through the sync retry loop. See AsyncRetry for full contract."""
        method_eligible = request.method.upper() in self.retry_methods
        last_exc: BaseException | None = None
        last_response: httpx2.Response | None = None

        for attempt in range(self.max_attempts):
            is_last = attempt + 1 >= self.max_attempts
            self.budget.deposit()
            try:
                return next(request)
            except StatusError as exc:
                retryable_status = exc.response.status_code in self.retry_status_codes
                if not method_eligible or not retryable_status:
                    if retryable_status and request.extensions.get(STREAMING_BODY_MARKER):
                        exc.add_note(_STREAMING_BODY_REFUSAL_NOTE)
                    raise
                last_exc = exc
                last_response = exc.response
            except (NetworkError, TimeoutError) as exc:
                if not method_eligible:
                    if request.extensions.get(STREAMING_BODY_MARKER):
                        exc.add_note(_STREAMING_BODY_REFUSAL_NOTE)
                    raise
                last_exc = exc
                last_response = None

            # ---- retryable failure path
            if request.extensions.get(STREAMING_BODY_MARKER):
                if last_exc is None:  # pragma: no cover — invariant from except branch
                    msg = "Retry: streaming-body refusal reached with no last_exc"
                    raise AssertionError(msg)
                last_exc.add_note(_STREAMING_BODY_REFUSAL_NOTE)
                _emit_event(
                    _LOGGER,
                    "retry.streaming_refused",
                    level=logging.WARNING,
                    message="retry refused — request body is a stream that cannot replay",
                    attributes={
                        "method": request.method,
                        "url": str(request.url),
                        "last_exception_type": type(last_exc).__qualname__,
                    },
                )
                raise last_exc

            if is_last:
                if last_exc is None:  # pragma: no cover — structural invariant from except branch
                    msg = "Retry: last_exc unset on final attempt — unreachable"
                    raise AssertionError(msg)
                last_exc.add_note(f"httpware: gave up after {attempt + 1} attempts")
                _emit_event(
                    _LOGGER,
                    "retry.giving_up",
                    level=logging.WARNING,
                    message=f"retry gave up after {attempt + 1} attempts",
                    attributes={
                        "attempts": attempt + 1,
                        "method": request.method,
                        "url": str(request.url),
                        "last_status": last_response.status_code if last_response is not None else None,
                        "last_exception_type": type(last_exc).__qualname__,
                    },
                )
                raise last_exc

            if not self.budget.try_withdraw():
                _emit_event(
                    _LOGGER,
                    "retry.budget_refused",
                    level=logging.WARNING,
                    message=f"retry budget refused after {attempt + 1} attempts",
                    attributes={
                        "attempts": attempt + 1,
                        "method": request.method,
                        "url": str(request.url),
                        "last_status": last_response.status_code if last_response is not None else None,
                    },
                )
                raise RetryBudgetExhaustedError(
                    last_response=last_response,
                    last_exception=last_exc,
                    attempts=attempt + 1,
                ) from last_exc

            retry_after: float | None = None
            if self.respect_retry_after and last_response is not None:
                header = last_response.headers.get("Retry-After")
                if header is not None:
                    retry_after = _parse_retry_after(header)

            if retry_after is not None:
                delay = min(retry_after, self.max_delay)
            else:
                delay = full_jitter_delay(
                    attempt,
                    base_delay=self.base_delay,
                    max_delay=self.max_delay,
                )
            self._sleep(delay)

        msg = "unreachable"  # pragma: no cover
        raise AssertionError(msg)  # pragma: no cover
```

Notes for the implementer:
- `time` is imported at module top. If you prefer, use `from time import sleep` and reference `sleep` directly — but the existing `_sleep` injection idiom (used by the AsyncRetry tests) keeps a clean test seam.
- `typing` is already imported (existing `AsyncRetry` uses it indirectly via `Callable`/`Awaitable`). If not, add `import typing` to the imports.

- [ ] **Step 2: Smoke check**

```bash
uv run python -c "from httpware.middleware.resilience.retry import Retry, AsyncRetry; print('ok')"
```
Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
git add src/httpware/middleware/resilience/retry.py
git commit -m "feat(retry): add sync Retry alongside AsyncRetry

Same algorithm: budget deposit per attempt, status/network/timeout
gates, idempotent-method check, streaming-body refusal, Retry-After,
full-jitter backoff, budget refusal, PEP-678 add_note on giving up.
Uses time.sleep for the delay; no attempt_timeout (removed from both
worlds in PR 1). Shares the same observability emitters (httpware.retry
logger, retry.streaming_refused / retry.giving_up / retry.budget_refused
events)."
```

---

## Task B10: Add sync `Bulkhead` to `bulkhead.py`

**Files:**
- Modify: `src/httpware/middleware/resilience/bulkhead.py`

- [ ] **Step 1: Update imports**

Add `import threading` to the imports. Add `from httpware.middleware import Next` (next to the existing `from httpware.middleware import AsyncNext`).

- [ ] **Step 2: Add the sync class**

Append:

```python


class Bulkhead:
    """Sync concurrency limiter backed by threading.Semaphore.

    Bulkhead is the sharable unit — pass the same instance to multiple
    Client(middleware=[shared]) calls to enforce a joint cap across clients.

    Bulkhead is per-world: a single instance cannot be shared between a Client
    and an AsyncClient (the underlying semaphore primitives differ). To cap
    a sync+async mixed workload, use a Bulkhead and an AsyncBulkhead with
    matching max_concurrent.
    """

    def __init__(
        self,
        *,
        max_concurrent: int,
        acquire_timeout: float | None = 1.0,
    ) -> None:
        if max_concurrent < 1:
            raise ValueError(_MAX_CONCURRENT_INVALID)
        if acquire_timeout is not None and acquire_timeout < 0:
            raise ValueError(_ACQUIRE_TIMEOUT_INVALID)
        self._max_concurrent = max_concurrent
        self._acquire_timeout = acquire_timeout
        self._sem = threading.Semaphore(max_concurrent)

    def __call__(self, request: httpx2.Request, next: Next) -> httpx2.Response:  # noqa: A002
        """Acquire a slot (bounded by acquire_timeout), invoke next, release."""
        # threading.Semaphore.acquire(timeout=None) blocks until acquired;
        # acquire(timeout=0) returns immediately (True if a slot was available,
        # False otherwise). Both match AsyncBulkhead's contract.
        acquired = self._sem.acquire(timeout=self._acquire_timeout)
        if not acquired:
            _emit_event(
                _LOGGER,
                "bulkhead.rejected",
                level=logging.WARNING,
                message="bulkhead rejected request — acquire_timeout exceeded",
                attributes={
                    "max_concurrent": self._max_concurrent,
                    "acquire_timeout": self._acquire_timeout,
                    "method": request.method,
                    "url": str(request.url),
                },
            )
            raise BulkheadFullError(
                max_concurrent=self._max_concurrent,
                acquire_timeout=self._acquire_timeout,
            )

        try:
            return next(request)
        finally:
            self._sem.release()
```

- [ ] **Step 3: Smoke check**

```bash
uv run python -c "from httpware.middleware.resilience.bulkhead import Bulkhead, AsyncBulkhead; print('ok')"
```
Expected: `ok`.

- [ ] **Step 4: Commit**

```bash
git add src/httpware/middleware/resilience/bulkhead.py
git commit -m "feat(bulkhead): add sync Bulkhead with threading.Semaphore"
```

---

## Task B11: Update `resilience/__init__.py` re-exports

**Files:**
- Modify: `src/httpware/middleware/resilience/__init__.py`

- [ ] **Step 1: Replace file contents**

```python
"""Resilience primitives: Bulkhead/AsyncBulkhead, Retry/AsyncRetry, RetryBudget."""

from httpware.middleware.resilience.budget import RetryBudget
from httpware.middleware.resilience.bulkhead import AsyncBulkhead, Bulkhead
from httpware.middleware.resilience.retry import AsyncRetry, Retry


__all__ = ["AsyncBulkhead", "AsyncRetry", "Bulkhead", "Retry", "RetryBudget"]
```

- [ ] **Step 2: Commit**

```bash
git add src/httpware/middleware/resilience/__init__.py
git commit -m "feat(resilience): re-export sync Retry and Bulkhead"
```

---

## Task B12: Write `test_retry_sync.py`

**Files:**
- New: `tests/test_retry_sync.py`

- [ ] **Step 1: Write the file**

Adapt the existing `tests/test_retry.py` to sync (mostly an `async def` → `def` and `await` removal pass). Create:

```python
"""Tests for the sync Retry middleware.

Mirror of test_retry.py. Mocks the transport via httpx2.MockTransport;
injects a recording `_sleep` callable so the suite runs instantly.
"""

import logging
from collections.abc import Callable
from http import HTTPStatus

import httpx2
import pytest

from httpware import Client, NotFoundError, ServiceUnavailableError
from httpware.errors import NetworkError, RetryBudgetExhaustedError
from httpware.errors import TimeoutError as HttpwareTimeoutError
from httpware._internal.status import STREAMING_BODY_MARKER, _is_streaming_body_sync
from httpware.middleware.resilience.budget import RetryBudget
from httpware.middleware.resilience.retry import (
    DEFAULT_IDEMPOTENT_METHODS,
    DEFAULT_RETRY_STATUS_CODES,
    Retry,
)


class _SleepRecorder:
    def __init__(self) -> None:
        self.calls: list[float] = []

    def __call__(self, delay: float) -> None:
        self.calls.append(delay)


class _ResponseSequence:
    def __init__(self, statuses: list[int]) -> None:
        self._statuses = list(statuses)
        self.calls: int = 0

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.calls += 1
        status = self._statuses.pop(0) if self._statuses else HTTPStatus.OK
        return httpx2.Response(status, request=request)


def _client(handler: Callable[[httpx2.Request], httpx2.Response], *, retry: Retry) -> Client:
    transport = httpx2.MockTransport(handler)
    return Client(
        httpx2_client=httpx2.Client(transport=transport),
        middleware=[retry],
    )


def test_default_retry_status_codes_match_spec() -> None:
    # Module-level constant is shared with AsyncRetry; this test mirrors test_retry.py.
    assert frozenset({408, 429, 502, 503, 504}) == DEFAULT_RETRY_STATUS_CODES


def test_default_idempotent_methods_match_spec() -> None:
    assert frozenset({"GET", "HEAD", "OPTIONS", "PUT", "DELETE"}) == DEFAULT_IDEMPOTENT_METHODS


def test_succeeds_first_try_no_sleep() -> None:
    sleeper = _SleepRecorder()
    handler = _ResponseSequence([HTTPStatus.OK])
    client = _client(handler, retry=Retry(_sleep=sleeper))
    response = client.get("https://example.test/x")
    assert response.status_code == HTTPStatus.OK
    assert handler.calls == 1
    assert sleeper.calls == []


def test_retries_503_then_succeeds() -> None:
    sleeper = _SleepRecorder()
    handler = _ResponseSequence([HTTPStatus.SERVICE_UNAVAILABLE, HTTPStatus.OK])
    client = _client(handler, retry=Retry(_sleep=sleeper, base_delay=0.01, max_delay=0.02))
    response = client.get("https://example.test/x")
    assert response.status_code == HTTPStatus.OK
    assert handler.calls == 2  # noqa: PLR2004
    assert len(sleeper.calls) == 1
    assert 0.0 <= sleeper.calls[0] <= 0.02  # noqa: PLR2004


def test_gives_up_after_max_attempts_and_reraises_status_error() -> None:
    sleeper = _SleepRecorder()
    handler = _ResponseSequence([HTTPStatus.SERVICE_UNAVAILABLE] * 3)
    client = _client(handler, retry=Retry(_sleep=sleeper, base_delay=0.01, max_delay=0.02, max_attempts=3))
    with pytest.raises(ServiceUnavailableError) as info:
        client.get("https://example.test/x")
    assert handler.calls == 3  # noqa: PLR2004
    assert len(sleeper.calls) == 2  # noqa: PLR2004
    notes = getattr(info.value, "__notes__", [])
    assert any("gave up after 3 attempts" in note for note in notes)


def test_does_not_retry_non_retryable_status() -> None:
    sleeper = _SleepRecorder()
    handler = _ResponseSequence([HTTPStatus.NOT_FOUND])
    client = _client(handler, retry=Retry(_sleep=sleeper))
    with pytest.raises(NotFoundError):
        client.get("https://example.test/missing")
    assert handler.calls == 1
    assert sleeper.calls == []


def test_does_not_retry_non_idempotent_method() -> None:
    sleeper = _SleepRecorder()
    handler = _ResponseSequence([HTTPStatus.SERVICE_UNAVAILABLE])
    client = _client(handler, retry=Retry(_sleep=sleeper))
    with pytest.raises(ServiceUnavailableError):
        client.post("https://example.test/x")  # POST is not idempotent by default
    assert handler.calls == 1


def test_max_attempts_zero_rejected() -> None:
    with pytest.raises(ValueError, match="max_attempts must be >= 1"):
        Retry(max_attempts=0)


def test_streamed_body_request_is_refused() -> None:
    sleeper = _SleepRecorder()
    handler = _ResponseSequence([HTTPStatus.SERVICE_UNAVAILABLE])
    client = _client(handler, retry=Retry(_sleep=sleeper))

    # Manually craft a request with the streaming-body marker set.
    request = httpx2.Request("GET", "https://example.test/x")
    request.extensions[STREAMING_BODY_MARKER] = True

    with pytest.raises(ServiceUnavailableError) as info:
        client.send(request)

    notes = getattr(info.value, "__notes__", [])
    assert any("stream that cannot replay" in note for note in notes)
    assert sleeper.calls == []  # no retry attempted; no backoff


def test_client_post_with_sync_generator_content_marks_extensions() -> None:
    """Posting with a sync generator body sets the streaming marker on request.extensions."""
    seen_extensions: list[dict[str, object]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen_extensions.append(dict(request.extensions))
        return httpx2.Response(HTTPStatus.OK, request=request)

    def streamed_body():
        yield b"chunk1"
        yield b"chunk2"

    transport = httpx2.MockTransport(handler)
    client = Client(httpx2_client=httpx2.Client(transport=transport))
    client.post("https://example.test/upload", content=streamed_body())

    assert len(seen_extensions) == 1
    assert seen_extensions[0].get(STREAMING_BODY_MARKER) is True


def test_client_post_with_list_content_does_not_mark_extensions() -> None:
    """A list body is replayable; should NOT be marked as streaming."""
    seen_extensions: list[dict[str, object]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen_extensions.append(dict(request.extensions))
        return httpx2.Response(HTTPStatus.OK, request=request)

    transport = httpx2.MockTransport(handler)
    client = Client(httpx2_client=httpx2.Client(transport=transport))
    client.post("https://example.test/upload", content=[b"chunk1", b"chunk2"])

    assert len(seen_extensions) == 1
    assert STREAMING_BODY_MARKER not in seen_extensions[0]


def test_budget_exhausted_raises_with_payload() -> None:
    sleeper = _SleepRecorder()
    # Tiny budget: 0 floor, 0 retries.
    budget = RetryBudget(ttl=10.0, min_retries_per_sec=0.0, percent_can_retry=0.0)
    handler = _ResponseSequence([HTTPStatus.SERVICE_UNAVAILABLE, HTTPStatus.OK])
    client = _client(handler, retry=Retry(_sleep=sleeper, budget=budget, max_attempts=3))
    with pytest.raises(RetryBudgetExhaustedError) as info:
        client.get("https://example.test/x")
    assert info.value.attempts == 1
    assert info.value.last_response is not None
    assert info.value.last_response.status_code == HTTPStatus.SERVICE_UNAVAILABLE


def test_retry_after_seconds_honored() -> None:
    sleeper = _SleepRecorder()

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            HTTPStatus.TOO_MANY_REQUESTS,
            request=request,
            headers={"Retry-After": "1"},
        )

    client = _client(handler, retry=Retry(_sleep=sleeper, base_delay=0.01, max_delay=0.5, max_attempts=2))
    with pytest.raises(StatusError := __import__("httpware.errors").errors.StatusError):
        client.get("https://example.test/x")
    # Retry-After=1 clamped to max_delay=0.5
    assert sleeper.calls == [0.5]


def test_emits_giving_up_log_event(caplog: pytest.LogCaptureFixture) -> None:
    sleeper = _SleepRecorder()
    handler = _ResponseSequence([HTTPStatus.SERVICE_UNAVAILABLE] * 2)
    client = _client(handler, retry=Retry(_sleep=sleeper, base_delay=0.01, max_attempts=2))
    with caplog.at_level(logging.WARNING, logger="httpware.retry"):
        with pytest.raises(ServiceUnavailableError):
            client.get("https://example.test/x")
    assert any("retry gave up" in r.getMessage() for r in caplog.records)


def test_is_streaming_body_sync_predicates() -> None:
    assert _is_streaming_body_sync(None) is False
    assert _is_streaming_body_sync(b"bytes") is False
    assert _is_streaming_body_sync("str") is False
    assert _is_streaming_body_sync({"k": "v"}) is False
    assert _is_streaming_body_sync([1, 2]) is False
    assert _is_streaming_body_sync((1, 2)) is False
    assert _is_streaming_body_sync(iter([1, 2])) is True
    assert _is_streaming_body_sync((x for x in range(3))) is True  # generator
```

The implementer may need to add more tests to maintain 100% coverage of the sync `Retry` body (e.g., a network-error retry test, a streaming-marker emit-event coverage test). Use coverage output to identify gaps.

- [ ] **Step 2: Run**

```bash
uv run pytest tests/test_retry_sync.py -v
```

The test for `Client` will fail with ImportError until Task B14 — that's expected. **Skip this run for now**; come back after Task B14 (`Client` class lands) to run the full sync retry suite.

- [ ] **Step 3: Commit**

```bash
git add tests/test_retry_sync.py
git commit -m "test(retry-sync): cover sync Retry behavior"
```

---

## Task B13: Write `test_bulkhead_sync.py`

**Files:**
- New: `tests/test_bulkhead_sync.py`

- [ ] **Step 1: Write the file**

```python
"""Tests for the sync Bulkhead middleware.

Mirror of test_bulkhead.py for sync semantics. Uses threading for the
concurrency-cap proofs.
"""

import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from http import HTTPStatus

import httpx2
import pytest

from httpware import Client
from httpware.errors import BulkheadFullError
from httpware.middleware.resilience.bulkhead import Bulkhead


_MAX_CONCURRENT_1 = 1
_MAX_CONCURRENT_2 = 2
_ACQUIRE_TIMEOUT_FAST = 0.01
_ACQUIRE_TIMEOUT_SHORT = 0.05
_ACQUIRE_TIMEOUT_LONG = 0.5


class _SlowHandler:
    """Mock handler that blocks for `delay` seconds before returning 200 OK."""

    def __init__(self, delay: float) -> None:
        self.delay = delay
        self.lock = threading.Lock()
        self.in_flight = 0
        self.max_in_flight = 0
        self.calls = 0

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        with self.lock:
            self.calls += 1
            self.in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            time.sleep(self.delay)
            return httpx2.Response(HTTPStatus.OK, request=request)
        finally:
            with self.lock:
                self.in_flight -= 1


def _client(
    handler: Callable[[httpx2.Request], httpx2.Response],
    *,
    bulkhead: Bulkhead,
) -> Client:
    transport = httpx2.MockTransport(handler)
    return Client(
        httpx2_client=httpx2.Client(transport=transport),
        middleware=[bulkhead],
    )


def test_max_concurrent_zero_rejected() -> None:
    with pytest.raises(ValueError, match="max_concurrent must be >= 1"):
        Bulkhead(max_concurrent=0)


def test_max_concurrent_negative_rejected() -> None:
    with pytest.raises(ValueError, match="max_concurrent must be >= 1"):
        Bulkhead(max_concurrent=-1)


def test_negative_acquire_timeout_rejected() -> None:
    with pytest.raises(ValueError, match="acquire_timeout must be >= 0"):
        Bulkhead(max_concurrent=_MAX_CONCURRENT_1, acquire_timeout=-0.1)


def test_acquire_timeout_zero_accepted() -> None:
    bulkhead = Bulkhead(max_concurrent=_MAX_CONCURRENT_1, acquire_timeout=0)
    assert bulkhead._acquire_timeout == 0  # noqa: SLF001


def test_acquire_timeout_none_accepted() -> None:
    bulkhead = Bulkhead(max_concurrent=_MAX_CONCURRENT_1, acquire_timeout=None)
    assert bulkhead._acquire_timeout is None  # noqa: SLF001


def test_succeeds_when_slot_available() -> None:
    handler = _SlowHandler(delay=0.0)
    client = _client(handler, bulkhead=Bulkhead(max_concurrent=_MAX_CONCURRENT_2))
    response = client.get("https://example.test/x")
    assert response.status_code == HTTPStatus.OK
    assert handler.calls == 1


def test_serializes_at_capacity() -> None:
    """With max_concurrent=1 and 3 concurrent threads, in-flight count never exceeds 1."""
    handler = _SlowHandler(delay=0.02)
    client = _client(
        handler,
        bulkhead=Bulkhead(max_concurrent=_MAX_CONCURRENT_1, acquire_timeout=None),
    )
    with ThreadPoolExecutor(max_workers=3) as ex:
        futures = [ex.submit(client.get, f"https://example.test/{i}") for i in "abc"]
        for f in futures:
            f.result()
    assert handler.calls == 3  # noqa: PLR2004
    assert handler.max_in_flight == 1


def test_acquire_timeout_rejects_when_no_slot_available() -> None:
    handler = _SlowHandler(delay=0.1)
    client = _client(
        handler,
        bulkhead=Bulkhead(max_concurrent=_MAX_CONCURRENT_1, acquire_timeout=_ACQUIRE_TIMEOUT_FAST),
    )

    holder = threading.Thread(target=client.get, args=("https://example.test/hold",))
    holder.start()
    # Give the holder time to acquire the only slot
    time.sleep(0.01)
    try:
        with pytest.raises(BulkheadFullError) as info:
            client.get("https://example.test/blocked")
        assert info.value.max_concurrent == _MAX_CONCURRENT_1
        assert info.value.acquire_timeout == _ACQUIRE_TIMEOUT_FAST
    finally:
        holder.join()


def test_releases_slot_on_exception() -> None:
    """A handler that raises must still cause the slot to be released."""
    calls = []

    def boom(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        calls.append(1)
        msg = "kaboom"
        raise RuntimeError(msg)

    transport = httpx2.MockTransport(boom)
    bulkhead = Bulkhead(max_concurrent=_MAX_CONCURRENT_1, acquire_timeout=_ACQUIRE_TIMEOUT_SHORT)
    client = Client(httpx2_client=httpx2.Client(transport=transport), middleware=[bulkhead])

    with pytest.raises(RuntimeError, match="kaboom"):
        client.get("https://example.test/x")
    # Second call must succeed (slot was released) — handler still raises, but bulkhead doesn't reject
    with pytest.raises(RuntimeError, match="kaboom"):
        client.get("https://example.test/y")
    assert len(calls) == 2  # noqa: PLR2004 — both attempts reached the handler


def test_emits_rejected_event(caplog: pytest.LogCaptureFixture) -> None:
    import logging
    handler = _SlowHandler(delay=0.1)
    client = _client(
        handler,
        bulkhead=Bulkhead(max_concurrent=_MAX_CONCURRENT_1, acquire_timeout=_ACQUIRE_TIMEOUT_FAST),
    )
    holder = threading.Thread(target=client.get, args=("https://example.test/hold",))
    holder.start()
    time.sleep(0.01)
    try:
        with caplog.at_level(logging.WARNING, logger="httpware.bulkhead"):
            with pytest.raises(BulkheadFullError):
                client.get("https://example.test/blocked")
        assert any("bulkhead rejected" in r.getMessage() for r in caplog.records)
    finally:
        holder.join()
```

- [ ] **Step 2: Commit (run after Client lands)**

```bash
git add tests/test_bulkhead_sync.py
git commit -m "test(bulkhead-sync): cover sync Bulkhead behavior"
```

The tests will fail with ImportError on `from httpware import Client` until Task B14 lands. Run them after B14.

---

## Task B14: Add sync `Client` class to `client.py` (constructor + terminal + lifecycle)

**Files:**
- Modify: `src/httpware/client.py`

This is the largest task. Add the `Client` class alongside `AsyncClient`. Split the work: constructor + terminal + lifecycle first (this task); HTTP methods next task (B15); `stream()` after that (B16).

- [ ] **Step 1: Add imports**

In `client.py`, add to the top:

```python
from httpware.middleware import Middleware, Next  # sync siblings of AsyncMiddleware/AsyncNext
from httpware.middleware.chain import compose  # sync sibling of compose_async
from httpware._internal.status import _is_streaming_body_sync
```

- [ ] **Step 2: Add `_httpx2_exception_mapper_sync` helper**

Add a sync sibling of the async context manager (before `class AsyncClient:`):

```python
@contextlib.contextmanager
def _httpx2_exception_mapper_sync() -> typing.Iterator[None]:
    """Map httpx2 exceptions to httpware exceptions. Sync sibling of _httpx2_exception_mapper."""
    try:
        yield
    except httpx2.HTTPError as exc:
        raise map_httpx2_exception(exc) from exc
    except (httpx2.InvalidURL, httpx2.CookieConflict) as exc:
        raise map_httpx2_exception(exc) from exc
```

Add `Iterator` to `from collections.abc import AsyncIterator, Iterator, Sequence` (extend the existing import).

- [ ] **Step 3: Add `Client` class body**

Append this class after `AsyncClient` (end of file):

```python
class Client:
    """Sync HTTP client: thin wrapper around httpx2 with typed decoding and middleware."""

    _httpx2_client: httpx2.Client
    _owns_client: bool
    _decoder: ResponseDecoder
    _user_middleware: tuple[Middleware, ...]
    _dispatch: Next

    def __init__(  # noqa: PLR0913 — wide constructor is the cost of a single-call API
        self,
        *,
        base_url: str = "",
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
        cookies: dict[str, str] | None = None,
        timeout: httpx2.Timeout | float | None = None,
        limits: httpx2.Limits | None = None,
        auth: httpx2.Auth | None = None,
        httpx2_client: httpx2.Client | None = None,
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
            self._httpx2_client = httpx2.Client(**kwargs)
            self._owns_client = True

        self._decoder = decoder if decoder is not None else _default_pydantic_decoder()
        self._user_middleware = tuple(middleware)
        self._dispatch = compose(self._user_middleware, self._terminal)

    def _terminal(self, request: httpx2.Request) -> httpx2.Response:
        try:
            with _httpx2_exception_mapper_sync():
                response = self._httpx2_client.send(request)
        except RuntimeError as exc:
            if "closed" in str(exc):
                raise TransportError(str(exc)) from exc
            raise
        _raise_on_status_error(response)
        return response

    def __enter__(self) -> typing.Self:
        """Enter the sync context manager; return self."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object,
    ) -> None:
        """Exit the sync context manager; close the underlying client only if owned."""
        if self._owns_client and not self._httpx2_client.is_closed:
            self._httpx2_client.close()

    def close(self) -> None:
        """Close the underlying httpx2 client if we own it.

        Idempotent — safe to call after ``__exit__`` or another ``close()`` call.
        Use this when the client is not managed by ``with`` (e.g., wired into a
        DI container's lifecycle). Mirrors AsyncClient.aclose().
        """
        if self._owns_client and not self._httpx2_client.is_closed:
            self._httpx2_client.close()
```

Note: HTTP method bodies (`get`/`post`/etc) come in Task B15.

- [ ] **Step 4: Smoke check the class imports**

```bash
uv run python -c "
from httpware.client import Client, AsyncClient
c = Client()
c.close()
print('ok')
"
```
Expected: `ok`. (Constructing a no-arg `Client` requires the `pydantic` extra installed, which it is in the dev environment.)

- [ ] **Step 5: Commit**

```bash
git add src/httpware/client.py
git commit -m "feat(client): add sync Client (constructor + terminal + lifecycle)

HTTP methods land in the next commit; stream() after."
```

---

## Task B15: Add HTTP methods + `request`/`send`/`build_request` to `Client`

**Files:**
- Modify: `src/httpware/client.py`

- [ ] **Step 1: Add `send`, `build_request`, `_request_with_body`, and per-method API**

Add to the `Client` class body (after `close()`):

```python
    @typing.overload
    def send(self, request: httpx2.Request, *, response_model: None = None) -> httpx2.Response: ...

    @typing.overload
    def send(self, request: httpx2.Request, *, response_model: type[T]) -> T: ...

    def send(
        self,
        request: httpx2.Request,
        *,
        response_model: type[T] | None = None,
    ) -> httpx2.Response | T:
        """Send `request` through the middleware chain. Decode if `response_model` is set."""
        response = self._dispatch(request)
        if response_model is None:
            return response
        return self._decoder.decode(response.content, response_model)

    def build_request(self, method: str, url: str, **kwargs: typing.Any) -> httpx2.Request:
        """Delegate request construction to the wrapped httpx2.Client."""
        return self._httpx2_client.build_request(method, url, **kwargs)

    def _request_with_body(  # noqa: PLR0913, C901 — mirrors httpx2 per-method signatures; kwargs-forwarding complexity is structural
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
        if _is_streaming_body_sync(content) or _is_streaming_body_sync(data) or _is_streaming_body_sync(files):
            request.extensions[STREAMING_BODY_MARKER] = True
        return self.send(request, response_model=response_model)
```

- [ ] **Step 2: Add per-method helpers (get, post, put, patch, delete, head, options, request)**

For each of these methods, mirror the existing `AsyncClient` definition (overload + body) but drop the `async`/`await` keywords. The implementer copies the existing async method bodies from `client.py` (the `get`/`post`/`put`/`patch`/`delete`/`head`/`options`/`request` methods on `AsyncClient`) and produces sync versions. Example for `get`:

```python
    @typing.overload
    def get(
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
    def get(
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

    def get(  # noqa: PLR0913 — mirrors httpx2 per-method signatures
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
        return self._request_with_body(
            "GET",
            url,
            params=params,
            headers=headers,
            cookies=cookies,
            timeout=timeout,
            extensions=extensions,
            response_model=response_model,
        )
```

Apply the same transformation to `post`, `put`, `patch`, `delete`, `head`, `options`, and `request` from `AsyncClient`. The body-bearing methods (`post`, `put`, `patch`, `delete`, `request`) include `json`, `content`, `data`, `files` kwargs; the bodyless ones (`get`, `head`, `options`) do not. **Mirror the existing async signatures exactly** — same kwargs, same overload structure.

- [ ] **Step 3: Verify with a small script**

```bash
uv run python -c "
import httpx2
from httpware import Client
transport = httpx2.MockTransport(lambda req: httpx2.Response(200, request=req, json={'ok': True}))
with Client(httpx2_client=httpx2.Client(transport=transport)) as client:
    r = client.get('https://example.test/x')
    print(r.status_code, r.json())
"
```
Expected: `200 {'ok': True}`.

- [ ] **Step 4: Commit**

```bash
git add src/httpware/client.py
git commit -m "feat(client): add sync Client HTTP methods (get/post/put/patch/delete/head/options/request/send)"
```

---

## Task B16: Add `Client.stream()`

**Files:**
- Modify: `src/httpware/client.py`

- [ ] **Step 1: Append `stream()` method to `Client`**

```python
    @contextlib.contextmanager
    def stream(  # noqa: PLR0913, C901 — mirrors httpx2 per-method signatures; kwargs-forwarding complexity is structural
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
    ) -> Iterator[httpx2.Response]:
        """Stream an HTTP response. Bypasses the middleware chain.

        Yields an httpx2.Response; consume the body via response.iter_bytes(),
        response.iter_text(), response.iter_lines(), or response.iter_raw().
        The body is NOT pre-read for 2xx/3xx (streaming preserved); the response
        is closed when the context exits.

        Bypasses the middleware chain (no Retry, no Bulkhead, no user-installed
        middleware) — matches AsyncClient.stream() behavior.

        Auto-raises StatusError subclasses on 4xx/5xx. On error the response
        body is pre-read so exc.response.content is accessible.

        Maps httpx2 exceptions raised during the request OR body consumption to
        httpware exceptions via _httpx2_exception_mapper_sync.
        """
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

        with _httpx2_exception_mapper_sync(), self._httpx2_client.stream(method, url, **kwargs) as response:
            if HTTPStatus.BAD_REQUEST <= response.status_code < 600:  # noqa: PLR2004 — 600 is the synthetic upper bound for 5xx
                response.read()  # pre-read body so exc.response.content works
                _raise_on_status_error(response)
            yield response
```

- [ ] **Step 2: Commit**

```bash
git add src/httpware/client.py
git commit -m "feat(client): add Client.stream() context manager"
```

---

## Task B17: Update top-level `__init__.py` for sync exports

**Files:**
- Modify: `src/httpware/__init__.py`

- [ ] **Step 1: Replace file contents**

```python
"""httpware — thin async + sync HTTP client wrapper over httpx2."""

from httpware.client import AsyncClient, Client
from httpware.decoders import ResponseDecoder
from httpware.errors import (
    STATUS_TO_EXCEPTION,
    BadRequestError,
    BulkheadFullError,
    ClientError,
    ClientStatusError,
    ConflictError,
    ForbiddenError,
    InternalServerError,
    NetworkError,
    NotFoundError,
    RateLimitedError,
    RetryBudgetExhaustedError,
    ServerStatusError,
    ServiceUnavailableError,
    StatusError,
    TimeoutError,  # noqa: A004
    TransportError,
    UnauthorizedError,
    UnprocessableEntityError,
)
from httpware.middleware import (
    AsyncMiddleware,
    AsyncNext,
    Middleware,
    Next,
    after_response,
    async_after_response,
    async_before_request,
    async_on_error,
    before_request,
    on_error,
)
from httpware.middleware.resilience import AsyncBulkhead, AsyncRetry, Bulkhead, Retry, RetryBudget


__all__ = [
    "STATUS_TO_EXCEPTION",
    "AsyncBulkhead",
    "AsyncClient",
    "AsyncMiddleware",
    "AsyncNext",
    "AsyncRetry",
    "BadRequestError",
    "Bulkhead",
    "BulkheadFullError",
    "Client",
    "ClientError",
    "ClientStatusError",
    "ConflictError",
    "ForbiddenError",
    "InternalServerError",
    "Middleware",
    "NetworkError",
    "Next",
    "NotFoundError",
    "RateLimitedError",
    "ResponseDecoder",
    "Retry",
    "RetryBudget",
    "RetryBudgetExhaustedError",
    "ServerStatusError",
    "ServiceUnavailableError",
    "StatusError",
    "TimeoutError",
    "TransportError",
    "UnauthorizedError",
    "UnprocessableEntityError",
    "after_response",
    "async_after_response",
    "async_before_request",
    "async_on_error",
    "before_request",
    "on_error",
]
```

- [ ] **Step 2: Commit**

```bash
git add src/httpware/__init__.py
git commit -m "feat(public-api): export Client, sync Middleware/Retry/Bulkhead/Next + decorators"
```

---

## Task B18: Write `test_client_sync.py`

**Files:**
- New: `tests/test_client_sync.py`

- [ ] **Step 1: Write the test file**

Mirror `tests/test_client_construction.py`, `tests/test_client_lifecycle.py`, and `tests/test_client_methods.py` into one consolidated sync file (or three separate files — the implementer's call; one file is cleaner since the sync surface is smaller). Use this consolidated form:

```python
"""Tests for the sync Client — construction, methods, lifecycle, error mapping."""

from http import HTTPStatus

import httpx2
import pytest

from httpware import Client, NotFoundError
from httpware.decoders.pydantic import PydanticDecoder


# ---------- Construction ----------


def test_construction_with_no_args_works() -> None:
    client = Client()
    assert isinstance(client, Client)
    client.close()


def test_construction_with_forwarded_kwargs() -> None:
    client = Client(
        base_url="https://example.test",
        headers={"x-shared": "1"},
        params={"trace": "yes"},
        timeout=10.0,
    )
    assert isinstance(client, Client)
    client.close()


def test_construction_with_caller_owned_httpx2_client() -> None:
    transport = httpx2.MockTransport(lambda req: httpx2.Response(200, request=req))
    caller = httpx2.Client(transport=transport)
    client = Client(httpx2_client=caller)
    assert isinstance(client, Client)
    caller.close()


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
    caller = httpx2.Client(transport=transport)
    with pytest.raises(TypeError, match="httpx2_client"):
        Client(httpx2_client=caller, **kwargs)
    caller.close()


def test_default_decoder_is_pydantic_decoder() -> None:
    client = Client()
    assert isinstance(client._decoder, PydanticDecoder)  # noqa: SLF001
    client.close()


def test_explicit_decoder_is_honored() -> None:
    class _Stub:
        def decode(self, content: bytes, model: type) -> object:  # noqa: ARG002  # pragma: no cover
            return None

    client = Client(decoder=_Stub())
    assert isinstance(client._decoder, _Stub)  # noqa: SLF001
    client.close()


# ---------- Methods ----------


def _echo_handler(request: httpx2.Request) -> httpx2.Response:
    return httpx2.Response(
        HTTPStatus.OK,
        request=request,
        json={
            "method": request.method,
            "url": str(request.url),
            "headers": dict(request.headers),
            "content": request.content.decode() if request.content else "",
        },
    )


def _client_with_handler(handler, **kwargs) -> Client:  # noqa: ANN001, ANN003
    transport = httpx2.MockTransport(handler)
    return Client(httpx2_client=httpx2.Client(transport=transport, **kwargs))


def test_get_returns_httpx2_response() -> None:
    client = _client_with_handler(_echo_handler)
    response = client.get("https://example.test/x")
    assert isinstance(response, httpx2.Response)
    assert response.json()["method"] == "GET"


@pytest.mark.parametrize(
    "method_name",
    ["get", "post", "put", "patch", "delete", "head", "options"],
)
def test_each_per_method_helper_uses_correct_verb(method_name: str) -> None:
    client = _client_with_handler(_echo_handler)
    method = getattr(client, method_name)
    response = method("https://example.test/x")
    assert response.json()["method"] == method_name.upper()


def test_post_json_body_serialized() -> None:
    client = _client_with_handler(_echo_handler)
    response = client.post("https://example.test/x", json={"k": "v"})
    payload = response.json()
    assert "application/json" in payload["headers"]["content-type"]
    assert payload["content"] == '{"k":"v"}'


def test_get_raises_typed_status_error_on_404() -> None:
    client = _client_with_handler(lambda req: httpx2.Response(HTTPStatus.NOT_FOUND, request=req))
    with pytest.raises(NotFoundError):
        client.get("https://example.test/missing")


def test_request_method_takes_arbitrary_verb() -> None:
    client = _client_with_handler(_echo_handler)
    response = client.request("PROPFIND", "https://example.test/x")
    assert response.json()["method"] == "PROPFIND"


def test_runtime_error_without_closed_reraises() -> None:
    def boom(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        msg = "unexpected internal failure"
        raise RuntimeError(msg)

    client = _client_with_handler(boom)
    with pytest.raises(RuntimeError, match="unexpected internal failure"):
        client.get("https://example.test/x")


# ---------- Lifecycle ----------


def test_exit_closes_owned_httpx2_client() -> None:
    client = Client()
    with client:
        pass
    assert client._httpx2_client.is_closed  # noqa: SLF001


def test_exit_does_not_close_borrowed_httpx2_client() -> None:
    transport = httpx2.MockTransport(lambda req: httpx2.Response(HTTPStatus.OK, request=req))
    underlying = httpx2.Client(transport=transport)
    client = Client(httpx2_client=underlying)
    with client:
        pass
    assert not underlying.is_closed
    underlying.close()


def test_exit_is_idempotent_for_owned_client() -> None:
    client = Client()
    with client:
        pass
    # Second use should not raise
    client.__exit__(None, None, None)


def test_close_is_idempotent_for_owned_client() -> None:
    client = Client()
    client.close()
    client.close()
    assert client._httpx2_client.is_closed  # noqa: SLF001
```

- [ ] **Step 2: Run**

```bash
uv run pytest tests/test_client_sync.py -v
```
Expected: all PASS.

- [ ] **Step 3: Run the deferred-runs from Tasks B12 and B13**

```bash
uv run pytest tests/test_retry_sync.py tests/test_bulkhead_sync.py -v
```
Expected: all PASS (now that `Client` exists).

- [ ] **Step 4: Commit**

```bash
git add tests/test_client_sync.py
git commit -m "test(client-sync): cover sync Client construction, methods, lifecycle"
```

---

## Task B19: Write `test_client_stream_sync.py`

**Files:**
- New: `tests/test_client_stream_sync.py`

- [ ] **Step 1: Write the test file**

Mirror `tests/test_client_stream.py` to sync. Adapt the async iterator (`async for chunk in response.aiter_bytes()`) to sync (`for chunk in response.iter_bytes()`). Keep the test names parallel to the async file so pairs are easy to find.

```python
"""Tests for Client.stream() — sync sibling of test_client_stream.py."""

import typing
from http import HTTPStatus

import httpx2
import pytest

from httpware import (
    Client,
    ClientStatusError,
    NetworkError,
    NotFoundError,
    ServerStatusError,
    ServiceUnavailableError,
    TransportError,
)
from httpware.middleware import Middleware, Next


_UNKNOWN_4XX = 418
_UNKNOWN_5XX = 599
_REDIRECT_3XX = 301
_NOT_FOUND = 404
_SERVICE_UNAVAILABLE = 503


def _client(handler: typing.Callable[[httpx2.Request], httpx2.Response]) -> Client:
    transport = httpx2.MockTransport(handler)
    return Client(httpx2_client=httpx2.Client(transport=transport))


def test_streams_response_body_successfully() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(HTTPStatus.OK, request=request, content=b"chunk1chunk2chunk3")

    client = _client(handler)
    with client.stream("GET", "https://example.test/x") as response:
        assert response.status_code == HTTPStatus.OK
        chunks = list(response.iter_bytes())
    assert b"".join(chunks) == b"chunk1chunk2chunk3"


def test_auto_raises_on_4xx_with_body_preread() -> None:
    body = b'{"error": "not found"}'

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(_NOT_FOUND, request=request, content=body)

    client = _client(handler)
    with pytest.raises(NotFoundError) as info:
        with client.stream("GET", "https://example.test/missing"):
            pytest.fail("should have raised before reaching block body")  # pragma: no cover
    assert info.value.response.status_code == _NOT_FOUND
    assert info.value.response.content == body


def test_auto_raises_on_5xx_with_body_preread() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(_SERVICE_UNAVAILABLE, request=request, content=b"degraded")

    client = _client(handler)
    with pytest.raises(ServiceUnavailableError) as info:
        with client.stream("GET", "https://example.test/x"):
            pytest.fail("unreachable")  # pragma: no cover
    assert info.value.response.content == b"degraded"


def test_auto_raises_unknown_4xx_falls_back_to_client_status_error() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(_UNKNOWN_4XX, request=request)

    client = _client(handler)
    with pytest.raises(ClientStatusError):
        with client.stream("GET", "https://example.test/x"):
            pytest.fail("unreachable")  # pragma: no cover


def test_auto_raises_unknown_5xx_falls_back_to_server_status_error() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(_UNKNOWN_5XX, request=request)

    client = _client(handler)
    with pytest.raises(ServerStatusError):
        with client.stream("GET", "https://example.test/x"):
            pytest.fail("unreachable")  # pragma: no cover


def test_3xx_does_not_raise() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(_REDIRECT_3XX, request=request, headers={"location": "/x"})

    client = _client(handler)
    with client.stream("GET", "https://example.test/x") as response:
        assert response.status_code == _REDIRECT_3XX


def test_network_error_during_request_maps_to_network_error() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        raise httpx2.ConnectError("boom")

    client = _client(handler)
    with pytest.raises(NetworkError):
        with client.stream("GET", "https://example.test/x"):
            pytest.fail("unreachable")  # pragma: no cover


def test_bypasses_middleware_chain() -> None:
    """Middleware in the chain must NOT see stream() requests (matches AsyncClient.stream)."""
    seen: list[str] = []

    class _Counter:
        def __call__(self, request: httpx2.Request, next: Next) -> httpx2.Response:  # noqa: A002
            seen.append("middleware")
            return next(request)

    transport = httpx2.MockTransport(lambda req: httpx2.Response(200, request=req, content=b"x"))
    client = Client(
        httpx2_client=httpx2.Client(transport=transport),
        middleware=[_Counter()],
    )
    with client.stream("GET", "https://example.test/x") as response:
        list(response.iter_bytes())
    assert seen == []
```

- [ ] **Step 2: Run**

```bash
uv run pytest tests/test_client_stream_sync.py -v
```
Expected: all PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_client_stream_sync.py
git commit -m "test(client-stream-sync): cover Client.stream() behavior"
```

---

## Task B20: Write `test_threading_with_shared_budget.py`

**Files:**
- New: `tests/test_threading_with_shared_budget.py`

- [ ] **Step 1: Write the test file**

```python
"""Demonstrates that a single RetryBudget can be shared across a sync Client and an AsyncClient
in the same process without races (proven by the lock added in Task B2)."""

import asyncio
import threading
from http import HTTPStatus

import httpx2

from httpware import AsyncClient, AsyncRetry, Client, Retry
from httpware.middleware.resilience.budget import RetryBudget


_N_SYNC_THREADS = 4
_N_OPS_PER_THREAD = 50
_N_ASYNC_TASKS = 20


def test_shared_budget_across_sync_threads_and_async_loop() -> None:
    budget = RetryBudget(ttl=60.0, min_retries_per_sec=1000.0, percent_can_retry=0.5)

    def sync_handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(HTTPStatus.SERVICE_UNAVAILABLE, request=request)

    async def async_handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(HTTPStatus.SERVICE_UNAVAILABLE, request=request)

    # Sync side: ThreadPoolExecutor of Client.get() calls
    sync_transport = httpx2.MockTransport(sync_handler)
    sync_client = Client(
        httpx2_client=httpx2.Client(transport=sync_transport),
        middleware=[Retry(budget=budget, max_attempts=2, base_delay=0.0001, max_delay=0.001)],
    )

    def sync_worker() -> None:
        for _ in range(_N_OPS_PER_THREAD):
            try:
                sync_client.get("https://example.test/x")
            except Exception:  # noqa: BLE001 — we expect failures; just keep deposits/withdraws flowing
                pass

    threads = [threading.Thread(target=sync_worker) for _ in range(_N_SYNC_THREADS)]
    for t in threads:
        t.start()

    # Async side: an event loop driving AsyncClient
    async def async_main() -> None:
        async_transport = httpx2.MockTransport(async_handler)
        async_client = AsyncClient(
            httpx2_client=httpx2.AsyncClient(transport=async_transport),
            middleware=[AsyncRetry(budget=budget, max_attempts=2, base_delay=0.0001, max_delay=0.001, _sleep=asyncio.sleep)],
        )
        async with async_client:
            await asyncio.gather(*[_safe_get(async_client) for _ in range(_N_ASYNC_TASKS)])

    async def _safe_get(c: AsyncClient) -> None:
        try:
            await c.get("https://example.test/x")
        except Exception:  # noqa: BLE001
            pass

    asyncio.run(async_main())

    for t in threads:
        t.join()

    # The lock kept the budget's internal deques consistent — no IndexError, no corruption.
    # No specific count assertion: the test passes if it completes without an exception
    # from the budget itself. Add a smoke check that the budget recorded SOME activity:
    assert len(budget._deposits) > 0  # noqa: SLF001

    sync_client.close()
```

- [ ] **Step 2: Run**

```bash
uv run pytest tests/test_threading_with_shared_budget.py -v
```
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_threading_with_shared_budget.py
git commit -m "test: demonstrate shared RetryBudget across sync Client + AsyncClient"
```

---

## Task B21: Run the full suite + lint + coverage

**Files:** none (verification only)

- [ ] **Step 1: Run linters**

```bash
just lint
```
Expected: clean. Fix any leftover issues (likely unused imports from the refactor).

- [ ] **Step 2: Run full suite**

```bash
just test
```
Expected: ALL PASS with 100% line coverage maintained. Check the coverage report for any gaps in the new sync code; if any sync branch is uncovered, add a targeted test in the relevant `test_*_sync.py` file before continuing.

- [ ] **Step 3: Run the optional-extras isolation tests in subprocess**

```bash
uv run pytest tests/test_optional_extras_isolation.py -v
```
Expected: all PASS. `import httpware` must still NOT pull pydantic/msgspec/opentelemetry into `sys.modules` (the sync addition introduces no new transitive imports).

- [ ] **Step 4: Commit any small fixups**

If `just lint` made auto-fix changes to test files (formatting), stage them:

```bash
git add -u tests/ src/
git commit -m "style: ruff auto-fixes after sync addition"
```

(If nothing to commit, skip.)

---

## Task B22: Update docs for the sync surface

**Files:**
- Modify: `docs/middleware.md`, `docs/resilience.md`, `docs/errors.md`, `docs/testing.md`, `docs/index.md`, `README.md`

- [ ] **Step 1: Update `docs/middleware.md`**

Add a sibling "Sync middleware" section at the end of the existing middleware reference. Contents:

```markdown
## Sync middleware

The same protocol shape, sync flavor.

```python
from httpware import Middleware, Next, before_request, after_response, on_error
from httpware.middleware.chain import compose
```

A sync `Middleware` is a structural protocol — any callable with the right
signature satisfies it:

```python
class LoggingMiddleware:
    def __call__(self, request: httpx2.Request, next: Next) -> httpx2.Response:
        print(f"→ {request.method} {request.url}")
        response = next(request)
        print(f"← {response.status_code}")
        return response
```

Phase decorators (`@before_request`, `@after_response`, `@on_error`) have the
same semantics as their `@async_*` siblings, but wrap sync functions:

```python
@before_request
def add_request_id(request: httpx2.Request) -> httpx2.Request:
    return httpx2.Request(
        request.method,
        request.url,
        headers={**request.headers, "X-Request-ID": uuid.uuid4().hex},
        content=request.content,
    )

client = Client(middleware=[add_request_id])
```

Sync and async middleware classes do not interop: a `Middleware` cannot be
passed to `AsyncClient(middleware=...)` and vice versa. Pick the flavor
matching your client.
```

(The `_internal` reference in the existing async section needs no change.)

- [ ] **Step 2: Update `docs/resilience.md`**

Add a sibling section "Sync Retry and Bulkhead" with parameter tables identical to the async ones, minus `attempt_timeout`. Include a Bulkhead per-world warning:

```markdown
> **Per-world Bulkhead.** A `Bulkhead` (sync) and an `AsyncBulkhead` are separate
> primitives backed by `threading.Semaphore` and `asyncio.Semaphore` respectively.
> A single Bulkhead instance cannot enforce a joint cap across sync + async
> clients in the same process. If you need that, create both with the same
> `max_concurrent`; the OS will not coordinate the two but the policy intent
> is documented.
```

- [ ] **Step 3: Update `docs/errors.md`**

Add a one-paragraph note: "The status-keyed exception tree is shared between `Client` and `AsyncClient`. Catching `NotFoundError` in sync code uses the same import as catching it in async code (`from httpware import NotFoundError`)."

- [ ] **Step 4: Update `docs/testing.md`**

Add a sync example using `httpx2.Client` + `httpx2.MockTransport`:

```python
from http import HTTPStatus
import httpx2
from httpware import Client


def test_get_returns_typed_response() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(HTTPStatus.OK, request=request, json={"ok": True})

    with Client(httpx2_client=httpx2.Client(transport=httpx2.MockTransport(handler))) as client:
        response = client.get("https://example.test/x")

    assert response.status_code == HTTPStatus.OK
    assert response.json() == {"ok": True}
```

- [ ] **Step 5: Update `docs/index.md` and `README.md` quickstart**

Show both worlds side-by-side. For example, append to the quickstart:

```markdown
**Async usage:**

```python
import asyncio
from httpware import AsyncClient

async def main() -> None:
    async with AsyncClient(base_url="https://example.test") as client:
        response = await client.get("/users/42")
        print(response.json())

asyncio.run(main())
```

**Sync usage:**

```python
from httpware import Client

with Client(base_url="https://example.test") as client:
    response = client.get("/users/42")
    print(response.json())
```
```

- [ ] **Step 6: Verify mkdocs build**

```bash
uv run --with mkdocs-material mkdocs build --strict 2>&1 | tail -20
```
Expected: clean build.

- [ ] **Step 7: Commit**

```bash
git add docs/ README.md
git commit -m "docs: add sync Client + sync middleware/Retry/Bulkhead sections"
```

---

## Task B23: Update `planning/engineering.md`

**Files:**
- Modify: `planning/engineering.md`

- [ ] **Step 1: §1 (project intent) update**

After the existing v0.7.0 sentence (and the rename-sentence added by PR 1 Task A10), append:

```markdown
The same release also adds a sync `Client` with full feature parity (typed decoding, middleware chain, `Retry`/`Bulkhead`, `stream()`). `RetryBudget` is now thread-safe (one class, both worlds). Sync `Bulkhead` uses `threading.Semaphore` and cannot share an instance with `AsyncBulkhead`. See `planning/specs/2026-06-07-sync-client-design.md`.
```

- [ ] **Step 2: §3 Seam A update**

Re-label "Seam A: AsyncClient ↔ AsyncMiddleware" to "Seam A: Client/AsyncClient ↔ Middleware/AsyncMiddleware" and update the prose to mention that both clients freeze the chain at construction.

- [ ] **Step 3: §5 module layout update**

Replace the module-layout tree to reflect the new files:

```text
src/httpware/
├── __init__.py            # public exports (both worlds at top level)
├── py.typed
├── client.py              # Client (sync) + AsyncClient (async)
├── errors.py              # status-keyed exception tree (shared)
├── middleware/
│   ├── __init__.py        # Middleware + AsyncMiddleware, Next + AsyncNext, decorators
│   ├── chain.py           # compose + compose_async
│   └── resilience/
│       ├── __init__.py    # re-exports both worlds + RetryBudget
│       ├── bulkhead.py    # Bulkhead + AsyncBulkhead
│       ├── budget.py      # RetryBudget (thread-safe; shared)
│       ├── retry.py       # Retry + AsyncRetry
│       └── _backoff.py    # full-jitter helper (shared)
├── decoders/              # shared (ResponseDecoder + adapters)
└── _internal/
    ├── exception_mapping.py  # map_httpx2_exception (shared)
    ├── import_checker.py     # is_*_installed flags
    ├── observability.py      # _emit_event
    └── status.py             # _raise_on_status_error, _is_streaming_body_*, STREAMING_BODY_MARKER
```

- [ ] **Step 4: Commit**

```bash
git add planning/engineering.md
git commit -m "docs(engineering): document sync Client + new layout + shared helpers"
```

---

## Task B24: Write release notes

**Files:**
- New: `planning/releases/0.8.0.md` (filename TBD at release time — could be `1.0.0.md`)

- [ ] **Step 1: Draft release notes**

Use this template (placeholder version `0.8.0` — rename to `1.0.0.md` if cutting a stable release):

```markdown
# httpware 0.8.0 — Sync Client + httpx2-aligned naming

**Breaking release.** Renames the async middleware surface to use the `Async*`/`async_*` prefix (matching httpx2's convention), drops `Retry(attempt_timeout=...)`, and adds a fully-featured sync `Client`.

If you have existing async code, migration is one mechanical pass through your imports — see "Breaking changes" below.

## What's new

- **Sync `Client`.** Full parity with `AsyncClient`: typed response decoding, middleware chain, `Retry` + `Bulkhead`, `stream()` context manager, lifecycle (`with` + `close()`), and `httpx2.Client` injection. Designed for CLI tools, scripts, Django sync views, Jupyter, and threaded service workers.
- **Sync `Middleware` + `Next` + decorators.** `from httpware import Middleware, Next, before_request, after_response, on_error`. Same protocol shape as async; bodies are sync.
- **Sync `Retry` and `Bulkhead`.** Same resilience semantics as their async siblings, with `time.sleep` and `threading.Semaphore`. Sync `Retry` shares `RetryBudget` with async — one instance is safe across both worlds.
- **`RetryBudget` is now thread-safe** via an internal `threading.Lock`. Async users see no behavioral difference; the overhead is invisible (~50–100 ns per op).
- **Shared helpers in `_internal/`.** `map_httpx2_exception`, `_raise_on_status_error`, the streaming-body marker, and the body predicates moved to `_internal/exception_mapping.py` and `_internal/status.py`. No public-API change other than the exports listed below.

## Breaking changes

### Renames

| Old name | New name |
|---|---|
| `httpware.Middleware` | `httpware.AsyncMiddleware` |
| `httpware.Next` | `httpware.AsyncNext` |
| `httpware.Retry` | `httpware.AsyncRetry` |
| `httpware.Bulkhead` | `httpware.AsyncBulkhead` |
| `httpware.before_request` | `httpware.async_before_request` |
| `httpware.after_response` | `httpware.async_after_response` |
| `httpware.on_error` | `httpware.async_on_error` |
| `httpware.middleware.chain.compose` | `httpware.middleware.chain.compose_async` |

### Removals

- `Retry(attempt_timeout=...)` / `AsyncRetry(attempt_timeout=...)` is **removed**. It used `asyncio.timeout` to bound the whole attempt as a structured cancellation; this had no clean sync equivalent and is mostly covered by `httpx2.Timeout` (per-phase I/O bounds) for typical use cases. Users who genuinely need whole-attempt wall-clock bounds can compose their own timeout middleware.

### New names that previously meant something else

The unprefixed `Middleware`, `Next`, `Retry`, `Bulkhead`, `before_request`, `after_response`, `on_error` now refer to **sync** types. Code that imports them and expects async behavior will break at type-check time (or at the first `await` site).

## Migration

A one-pass sed/regex covers most of the work:

```bash
# in your project root:
git ls-files '*.py' | xargs sed -i.bak \
  -e 's/from httpware import \(.*\)\bMiddleware\b/from httpware import \1AsyncMiddleware/g' \
  -e 's/from httpware import \(.*\)\bNext\b/from httpware import \1AsyncNext/g' \
  -e 's/from httpware import \(.*\)\bRetry\b/from httpware import \1AsyncRetry/g' \
  -e 's/from httpware import \(.*\)\bBulkhead\b/from httpware import \1AsyncBulkhead/g' \
  -e 's/from httpware import \(.*\)\bbefore_request\b/from httpware import \1async_before_request/g' \
  -e 's/from httpware import \(.*\)\bafter_response\b/from httpware import \1async_after_response/g' \
  -e 's/from httpware import \(.*\)\bon_error\b/from httpware import \1async_on_error/g'
```

Then update the symbol references in the file bodies (your type checker will guide you). If you were using `Retry(attempt_timeout=...)`, remove the kwarg and rely on `httpx2.Timeout` or write a minimal timeout middleware.

## References

- Design spec: [`planning/specs/2026-06-07-sync-client-design.md`](../specs/2026-06-07-sync-client-design.md)
- Implementation plan: [`planning/plans/2026-06-07-sync-client-plan.md`](../plans/2026-06-07-sync-client-plan.md)
- Engineering notes: [`planning/engineering.md`](../engineering.md) §3 Seam A, §5 module layout
- Source spec parent (httpx convention): [`planning/archive/specs/2026-06-03-thin-httpx2-wrapper-design.md`](../archive/specs/2026-06-03-thin-httpx2-wrapper-design.md)
```

- [ ] **Step 2: Commit**

```bash
git add planning/releases/0.8.0.md
git commit -m "docs(release): draft 0.8.0 notes (sync Client + Async* rename)"
```

---

## Task B25: Open PR 2

- [ ] **Step 1: Push branch**

```bash
git push -u origin feat/sync-client
```

- [ ] **Step 2: Open the PR**

```bash
gh pr create --title "feat: sync Client + sync Middleware/Retry/Bulkhead + RetryBudget thread-safety" --body "$(cat <<'EOF'
## Summary
- Adds a fully-featured sync `Client` matching `AsyncClient` (typed decoding, middleware, `Retry`, `Bulkhead`, `stream()`, lifecycle, `httpx2.Client` injection).
- Adds sync `Middleware`, `Next`, `before_request`/`after_response`/`on_error` decorators, sync `compose`.
- Adds sync `Retry` (uses `time.sleep`) and sync `Bulkhead` (uses `threading.Semaphore`).
- Makes `RetryBudget` thread-safe via an internal `threading.Lock`. Same class for both worlds; one instance is safe to share across (sync_client, async_client) pairs and across threads.
- Extracts shared helpers (`map_httpx2_exception`, `_raise_on_status_error`, streaming-body predicates, `STREAMING_BODY_MARKER`) to `_internal/exception_mapping.py` and `_internal/status.py`.

Part 2 of 2. Part 1 (rename) already merged. After this PR merges, cut one combined release.

Source spec: `planning/specs/2026-06-07-sync-client-design.md`. Plan: `planning/plans/2026-06-07-sync-client-plan.md`.

## Test plan
- [x] `just lint` clean
- [x] `just test` all green (coverage maintained at 100%)
- [x] sync test suite mirrors async — `test_client_sync.py`, `test_retry_sync.py`, `test_bulkhead_sync.py`, `test_middleware_sync.py`, `test_client_stream_sync.py`
- [x] `test_retry_budget_threadsafety.py` proves the lock keeps the deques consistent under contention
- [x] `test_threading_with_shared_budget.py` proves a single RetryBudget works under mixed sync-threads + async-loop pressure
- [x] `test_optional_extras_isolation.py` still green (no new transitive imports)

## Release notes
Draft at `planning/releases/0.8.0.md`. Decide `0.8.0` vs `1.0.0` at release-tagging time.
EOF
)"
```

- [ ] **Step 3: Wait for review + merge**

Once PR 2 merges, cut the release. The tag and the version-bump (`0.8.0` or `1.0.0`) happen in the existing release workflow per project conventions.

---

## Self-review checklist (for the plan author)

After completing all tasks, verify:

- [ ] Every spec section has at least one task implementing it
- [ ] Every breaking change in the spec is reflected in either Part A or Part B and called out in the release notes (Task B24)
- [ ] No `attempt_timeout` references survive anywhere in `src/`, `tests/`, or `docs/`
- [ ] `100% line coverage` maintained
- [ ] `just lint` clean
- [ ] `import httpware` does not transitively import pydantic/msgspec/opentelemetry (Task B21 step 3)
- [ ] Both PRs merged before cutting the single release

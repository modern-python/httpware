# Small-Fixes Mop-Up Implementation Plan (0.8.5)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land 5 commits on branch `fix/small-mop-up` that close 4 small unrelated audit findings, draft 0.8.5 release notes, and open a PR.

**Architecture:** Four independent surgical fixes — chain.py hoists imports out of `TYPE_CHECKING`, pydantic.py hoists the `TypeAdapter` import unconditionally and updates the module docstring, docs/middleware.md swaps `print()` for `logging`, tests/test_public_api.py tightens `expected == set(__all__)`. Each fix is TDD where applicable (#1 + #4 add focused tests). Order is mechanical — no inter-fix dependencies.

**Tech Stack:** Python 3.11+, `typing.get_type_hints`, `pydantic.TypeAdapter`, `logging`, pytest. No new dependencies. No public API change.

---

## Spec reference

`planning/specs/2026-06-08-small-fixes-mop-up-design.md`. Decisions locked there: 4 commits + 1 release-notes commit; chain.py drops the TYPE_CHECKING block and unquotes string annotations; pydantic.py hoists `from pydantic import TypeAdapter` unconditionally and rewrites the module docstring; LoggingMiddleware example mirrors the RequestIdMiddleware logging pattern; the public-API test uses set equality so bogus `__all__` entries are caught.

## File structure

```
src/httpware/middleware/chain.py            # Task 1 — hoist imports + unquote
src/httpware/decoders/pydantic.py           # Task 2 — unconditional TypeAdapter + docstring
docs/middleware.md                          # Task 3 — print() → logging
tests/test_public_api.py                    # Task 4 — symmetric __all__ assertion
tests/test_middleware.py                    # Task 1 — get_type_hints test
planning/releases/0.8.5.md                  # Task 5 — release notes
```

No new source files. No file deletions. Branch is already created (`fix/small-mop-up`); spec already committed at `e84e8aa` or similar (the most recent commit on the branch).

---

## Task 1: chain.py — hoist Middleware / AsyncMiddleware out of TYPE_CHECKING

**Files:**
- Modify: `src/httpware/middleware/chain.py`
- Modify: `tests/test_middleware.py` (new test)

Closes audit Low finding (`chain.py:9-10`).

- [ ] **Step 1: Confirm there is no circular import**

```bash
grep -n 'chain' src/httpware/middleware/__init__.py
```

Expected: zero matches (or matches that are NOT imports of `chain.py`). The fix only works if `middleware/__init__.py` does not import from `chain.py` at module-load time — confirmed by the audit, verify again here. If a match exists and is a real import, STOP and report BLOCKED.

- [ ] **Step 2: Write the failing test (async)**

Append to `tests/test_middleware.py`:

```python
def test_compose_async_get_type_hints_resolves_without_nameerror() -> None:
    """typing.get_type_hints(compose_async) must resolve to real classes, not raise NameError.

    Pre-0.8.5: AsyncMiddleware was imported only under `if typing.TYPE_CHECKING`,
    so get_type_hints raised NameError at runtime.
    """
    import typing

    from httpware.middleware.chain import compose_async

    hints = typing.get_type_hints(compose_async)
    assert "middleware" in hints


def test_compose_get_type_hints_resolves_without_nameerror() -> None:
    """Sync mirror — sync `compose` get_type_hints must also resolve."""
    import typing

    from httpware.middleware.chain import compose

    hints = typing.get_type_hints(compose)
    assert "middleware" in hints
```

Note: per the user's `user_dislikes_plc0415_noqa_in_tests` memory, top-level imports are preferred. But these tests are 2-line one-shots that call `get_type_hints` exactly once. If `typing` and `compose_async`/`compose` aren't already imported at the top, hoist them. Check the existing imports in `tests/test_middleware.py` and adjust:

```bash
head -25 tests/test_middleware.py
```

Move any needed imports to the top of the file if they aren't already there, and drop them from inside the test bodies. Final state should have NO in-function imports.

- [ ] **Step 3: Run the tests — confirm BOTH fail**

```bash
uv run pytest tests/test_middleware.py::test_compose_async_get_type_hints_resolves_without_nameerror tests/test_middleware.py::test_compose_get_type_hints_resolves_without_nameerror --no-cov -q
```

Expected: BOTH FAIL with `NameError: name 'AsyncMiddleware' is not defined` (and `Middleware` for the sync one).

- [ ] **Step 4: Fix chain.py — drop TYPE_CHECKING block and unquote annotations**

Edit `src/httpware/middleware/chain.py`. Use the Edit tool.

old_string:
```python
"""Chain composition for the middleware stack."""

import typing
from collections.abc import Awaitable, Callable, Sequence

import httpx2


if typing.TYPE_CHECKING:
    from httpware.middleware import AsyncMiddleware, Middleware


_AsyncNext: typing.TypeAlias = Callable[[httpx2.Request], Awaitable[httpx2.Response]]
_Next: typing.TypeAlias = Callable[[httpx2.Request], httpx2.Response]


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

new_string:
```python
"""Chain composition for the middleware stack."""

import typing
from collections.abc import Awaitable, Callable, Sequence

import httpx2

from httpware.middleware import AsyncMiddleware, Middleware


_AsyncNext: typing.TypeAlias = Callable[[httpx2.Request], Awaitable[httpx2.Response]]
_Next: typing.TypeAlias = Callable[[httpx2.Request], httpx2.Response]


def compose_async(middleware: Sequence[AsyncMiddleware], terminal: _AsyncNext) -> _AsyncNext:
    """Fold `middleware` into a single callable around `terminal`.

    The first middleware in the sequence is the outermost wrapper.
    """
    dispatch: _AsyncNext = terminal
    for layer in reversed(middleware):
        dispatch = _wrap(layer, dispatch)
    return dispatch


def _wrap(layer: AsyncMiddleware, inner: _AsyncNext) -> _AsyncNext:
    async def call(request: httpx2.Request) -> httpx2.Response:
        return await layer(request, inner)

    return call


def compose(middleware: Sequence[Middleware], terminal: _Next) -> _Next:
    """Fold sync `middleware` into a single callable around sync `terminal`.

    The first middleware in the sequence is the outermost wrapper.
    """
    dispatch: _Next = terminal
    for layer in reversed(middleware):
        dispatch = _wrap_sync(layer, dispatch)
    return dispatch


def _wrap_sync(layer: Middleware, inner: _Next) -> _Next:
    def call(request: httpx2.Request) -> httpx2.Response:
        return layer(request, inner)

    return call
```

- [ ] **Step 5: Run the tests — confirm BOTH pass**

```bash
uv run pytest tests/test_middleware.py::test_compose_async_get_type_hints_resolves_without_nameerror tests/test_middleware.py::test_compose_get_type_hints_resolves_without_nameerror --no-cov -q
```

Expected: BOTH PASS.

- [ ] **Step 6: Run the full middleware test suites + retry/bulkhead/client (which exercise compose indirectly)**

```bash
uv run pytest tests/test_middleware.py tests/test_middleware_sync.py tests/test_client_middleware_wiring.py tests/test_client_methods.py tests/test_client_sync.py tests/test_retry.py tests/test_retry_sync.py tests/test_bulkhead.py tests/test_bulkhead_sync.py -x --no-cov -q
```

Expected: all pass.

- [ ] **Step 7: Run the isolation test (confirms no new transitive import surprises)**

```bash
uv run pytest tests/test_optional_extras_isolation.py -x --no-cov -q
```

Expected: all pass. (The new module-top import only touches `httpware.middleware`, which `import httpware` already loads; no new modules enter `sys.modules`.)

- [ ] **Step 8: Lint**

```bash
just lint-ci
```

Expected: green.

- [ ] **Step 9: Commit**

```bash
git add src/httpware/middleware/chain.py tests/test_middleware.py
git commit -m "$(cat <<'EOF'
fix(chain): hoist Middleware/AsyncMiddleware imports out of TYPE_CHECKING

compose_async and compose used string annotations referencing
AsyncMiddleware / Middleware imported only under `if typing.TYPE_CHECKING:`.
Calling typing.get_type_hints(compose_async) at runtime raised
`NameError: name 'AsyncMiddleware' is not defined`. The TYPE_CHECKING
guard also violates the project's typing-import-style memory rule.

Drop the guard, import the protocols unconditionally at module top, and
unquote the string annotations. httpware.middleware.__init__ does not
import chain.py back, so no circular import.

Tests pin typing.get_type_hints(compose_async) and typing.get_type_hints(
compose) resolve without NameError.

Closes audit Low finding (chain.py:9-10) from
planning/audit/2026-06-07-deep-audit.md.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: pydantic.py — unconditional `TypeAdapter` import + docstring update

**Files:**
- Modify: `src/httpware/decoders/pydantic.py`

Closes audit Low finding (`pydantic.py:15-16, 27, 43`).

- [ ] **Step 1: Verify the existing pydantic-missing tests still rely on runtime patching, not module-load behavior**

```bash
grep -nE 'is_pydantic_installed|from httpware.decoders.pydantic' tests/test_optional_extras_pydantic_missing.py
```

Expected: imports of `PydanticDecoder` happen at module-load time (unguarded); the flag-patching happens inside test bodies via `unittest.mock.patch`. This confirms that hoisting `from pydantic import TypeAdapter` unconditionally doesn't break those tests (the module is already loaded with pydantic available when the patches kick in).

If the test file structure is different from this expectation, STOP and report BLOCKED.

- [ ] **Step 2: Edit pydantic.py — drop the conditional, update docstring**

Use the Edit tool.

old_string:
```python
"""PydanticDecoder — module-level cached TypeAdapter adapter for ResponseDecoder.

Requires the `pydantic` extra: `pip install httpware[pydantic]`. Importing this
module without the extra works (the `pydantic` import is guarded by a
`find_spec` check), but instantiating the decoder raises `ImportError` with the
install hint.
"""

import functools
from typing import TypeVar

from httpware._internal import import_checker


if import_checker.is_pydantic_installed:
    from pydantic import TypeAdapter
```

new_string:
```python
"""PydanticDecoder — module-level cached TypeAdapter adapter for ResponseDecoder.

Requires the `pydantic` extra: `pip install httpware[pydantic]`. The optional-extras
gate is enforced upstream — `client.py:_default_pydantic_decoder()` raises
ImportError when pydantic is absent, so this module is never imported in that
path. Tests simulating "pydantic not installed" patch
`import_checker.is_pydantic_installed=False` at runtime, after this module is
already loaded; `PydanticDecoder.__init__` then raises ImportError with the
install hint.
"""

import functools
from typing import TypeVar

from pydantic import TypeAdapter

from httpware._internal import import_checker
```

- [ ] **Step 3: Run the pydantic-decoder + isolation + extras tests**

```bash
uv run pytest tests/test_decoders_pydantic.py tests/test_optional_extras_pydantic_missing.py tests/test_optional_extras_isolation.py tests/test_client_response_model.py tests/test_client_send_with_response.py tests/test_client_send_with_response_sync.py -x --no-cov -q
```

Expected: all pass. Critical: `test_pydantic_decoder_init_raises_when_pydantic_missing` still raises ImportError under the patched flag (because `PydanticDecoder.__init__` checks the flag and raises, regardless of whether `TypeAdapter` is conditionally bound or not).

Also critical: `test_importing_httpware_does_not_import_pydantic` still passes (the existing import graph doesn't pull `httpware.decoders.pydantic` into `sys.modules` at `import httpware` time).

- [ ] **Step 4: Run the full suite**

```bash
uv run pytest -x --no-cov -q
```

Expected: all pass.

- [ ] **Step 5: Lint**

```bash
just lint-ci
```

Expected: green. The unconditional `from pydantic import TypeAdapter` may need a comment to satisfy any future strict-imports rule, but as of 0.8.4 there is no such rule.

- [ ] **Step 6: Commit**

```bash
git add src/httpware/decoders/pydantic.py
git commit -m "$(cat <<'EOF'
fix(pydantic): unconditional TypeAdapter import — eliminate NameError window

_get_adapter and the TypeError fallback inside PydanticDecoder.decode both
referenced TypeAdapter as a bare name. The name was bound only under
`if import_checker.is_pydantic_installed:`. If a test reloaded the module
with the flag patched to False, TypeAdapter was undefined and subsequent
calls raised NameError instead of the documented ImportError.

Hoist `from pydantic import TypeAdapter` unconditionally. The module is
gated upstream by client.py:_default_pydantic_decoder(), which raises
ImportError before this module is loaded when pydantic is absent — there
is no real-world path that loads pydantic.py without pydantic available.

Update the module docstring to reflect the new contract.

Closes audit Low finding (pydantic.py:15-16, 27, 43) from
planning/audit/2026-06-07-deep-audit.md.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: docs/middleware.md — LoggingMiddleware uses `logging`, not `print()`

**Files:**
- Modify: `docs/middleware.md`

Closes audit Nit finding (`docs/middleware.md:156-161`).

- [ ] **Step 1: Confirm current state**

```bash
sed -n '150,170p' docs/middleware.md
```

Expected: the LoggingMiddleware example uses `print(f"-> {request.method} {request.url}")` and `print(f"<- {response.status_code}")`.

- [ ] **Step 2: Replace the LoggingMiddleware example**

Edit `docs/middleware.md`. Use the Edit tool.

old_string:
```python
import httpx2

from httpware import Client
from httpware.middleware import Next


class LoggingMiddleware:
    def __call__(self, request: httpx2.Request, next: Next) -> httpx2.Response:  # noqa: A002
        print(f"-> {request.method} {request.url}")
        response = next(request)
        print(f"<- {response.status_code}")
        return response


with Client(base_url="https://api.example.com", middleware=[LoggingMiddleware()]) as client:
    client.get("/users/1")
```

new_string:
```python
import logging

import httpx2

from httpware import Client
from httpware.middleware import Next


_LOGGER = logging.getLogger("myapp.logging_middleware")


class LoggingMiddleware:
    def __call__(self, request: httpx2.Request, next: Next) -> httpx2.Response:  # noqa: A002
        _LOGGER.info("-> %s %s", request.method, request.url)
        response = next(request)
        _LOGGER.info("<- %s", response.status_code)
        return response


with Client(base_url="https://api.example.com", middleware=[LoggingMiddleware()]) as client:
    client.get("/users/1")
```

- [ ] **Step 3: Verify no `print(` remains in that section**

```bash
sed -n '150,180p' docs/middleware.md | grep -c 'print('
```

Expected: `0`.

- [ ] **Step 4: Lint**

```bash
just lint-ci
```

Expected: green. (No code change; only markdown.)

- [ ] **Step 5: Commit**

```bash
git add docs/middleware.md
git commit -m "$(cat <<'EOF'
docs(middleware): LoggingMiddleware uses logging, not print()

The example previously used `print(...)` to demonstrate a middleware that
records inbound/outbound traffic. CLAUDE.md lists "No print()" as a
non-negotiable architecture invariant, so the doc example would fail CI
in a user's own project if they followed the project's conventions.

Rewrite with a module-level `_LOGGER = logging.getLogger("myapp.logging_middleware")`
and `_LOGGER.info(...)` calls, matching the existing RequestIdMiddleware
example's style further down the same file.

Closes audit Nit finding (docs/middleware.md:156-161) from
planning/audit/2026-06-07-deep-audit.md.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: tests/test_public_api.py — symmetric `__all__` assertion

**Files:**
- Modify: `tests/test_public_api.py`

Closes audit Nit finding (`test_public_api.py:69-71`).

- [ ] **Step 1: Verify the current test catches missing-from-__all__ but not bogus-in-__all__**

(Optional manual exploration — read `tests/test_public_api.py:29-71` to confirm the existing assertion is `missing = expected - set(httpware.__all__); assert not missing, ...`.)

- [ ] **Step 2: Replace the assertion with symmetric set equality**

Edit `tests/test_public_api.py`. Use the Edit tool.

old_string:
```python
    missing = expected - set(httpware.__all__)
    assert not missing, f"expected exports missing from __all__: {missing}"
```

new_string:
```python
    actual = set(httpware.__all__)
    assert expected == actual, (
        f"__all__ mismatch:\n"
        f"  missing from __all__: {expected - actual}\n"
        f"  unexpected in __all__: {actual - expected}"
    )
```

- [ ] **Step 3: Run the test — confirm it PASSES**

```bash
uv run pytest tests/test_public_api.py -x --no-cov -q
```

Expected: PASS. (Production `__all__` currently matches `expected` exactly — verified by the existing assertion that catches missing, plus the no-removed-symbols test, plus the all-resolve test. The new symmetric form just adds coverage for the bogus-in-__all__ direction.)

- [ ] **Step 4: Manual verification of the new failure mode (DO NOT COMMIT this temp change)**

In `src/httpware/__init__.py`, temporarily add a bogus symbol to `__all__` (e.g., `"_FakeNewExport"`). Run the test:

```bash
uv run pytest tests/test_public_api.py::test_expected_exports -x --no-cov
```

Expected: FAIL with `unexpected in __all__: {'_FakeNewExport'}`. Revert the change. (This is a sanity check, not a regression test that lands — the project doesn't ship intentionally-broken state as a guard.)

- [ ] **Step 5: Lint**

```bash
just lint-ci
```

Expected: green.

- [ ] **Step 6: Commit**

```bash
git add tests/test_public_api.py
git commit -m "$(cat <<'EOF'
test(public-api): symmetric assertion against __all__

test_expected_exports used `missing = expected - set(__all__)` so it
caught symbols missing from __all__ but not the reverse — symbols added
to __all__ that aren't in the expected set slipped through (the companion
test_all_exports_resolve catches symbols in __all__ that don't exist at
all; the gap was real symbols accidentally added to __all__).

Switch to `assert expected == set(__all__)` with a multi-line message
that names both directions, so future test failures pinpoint which side
drifted.

Closes audit Nit finding (test_public_api.py:69-71) from
planning/audit/2026-06-07-deep-audit.md.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Draft 0.8.5 release notes + open PR

**Files:**
- Create: `planning/releases/0.8.5.md`

- [ ] **Step 1: Skim the 0.8.4 release notes for shape**

```bash
cat planning/releases/0.8.4.md
```

(0.8.5 is similarly small — defensive fixes + docs + test, no user-visible behavior change on the happy path.)

- [ ] **Step 2: Write `planning/releases/0.8.5.md`**

Create with this exact content:

```markdown
# httpware 0.8.5 — small fixes mop-up

**Patch release. Four small unrelated fixes. No API change, no user-visible behavior change on the happy path.** Closes 4 of the remaining audit findings — two Low (chain.py + pydantic.py), two Nit (LoggingMiddleware docs + public-API test).

## What changed

- **`typing.get_type_hints(compose_async)` and `typing.get_type_hints(compose)` now resolve cleanly.** The `AsyncMiddleware` / `Middleware` imports moved out of the `if typing.TYPE_CHECKING:` guard in `httpware/middleware/chain.py`; runtime introspection of the chain-composition signatures works. No behavior change for users not calling `get_type_hints`.

- **`PydanticDecoder` no longer has a NameError window on test-reload.** `httpware/decoders/pydantic.py` now imports `pydantic.TypeAdapter` unconditionally at module top. The optional-extras gate is enforced upstream by `client.py:_default_pydantic_decoder()`, so loading this module without pydantic was already not a real-world path. The previous conditional import left `TypeAdapter` undefined when the install flag was patched off, raising `NameError` instead of the documented `ImportError` if anyone reloaded the module under the flag patch.

- **`LoggingMiddleware` example in `docs/middleware.md` uses `logging`, not `print()`.** CLAUDE.md lists "No `print()`" as a non-negotiable invariant; copying the example into a user's project would have failed their own ruff check. The new snippet mirrors the `RequestIdMiddleware` style further down the same file.

- **Public-API test catches bogus `__all__` entries.** `test_expected_exports` previously checked only `expected - set(__all__)`; now it asserts set equality so a symbol added to `__all__` without a peer update to the expected set is also caught.

## Upgrade

```bash
uv add httpware==0.8.5
# or
pip install -U 'httpware==0.8.5'
```

No import changes. No API changes. The only behavior change is that `from httpware.decoders.pydantic import PydanticDecoder` now fails with a real `ImportError` at import time when pydantic isn't installed (instead of succeeding-then-failing-at-construct). The audit finding documented that the previous behavior was unreachable in practice — the upstream fail-fast at `_default_pydantic_decoder()` is the real safety net.
```

- [ ] **Step 3: Lint**

```bash
just lint-ci
```

Expected: green. eof-fixer may add a trailing newline; that's fine.

- [ ] **Step 4: Commit**

```bash
git add planning/releases/0.8.5.md
git commit -m "$(cat <<'EOF'
docs(release): draft 0.8.5 notes — small-fixes mop-up

Four small unrelated fixes in one patch. chain.py get_type_hints
resolves; pydantic.py NameError window eliminated; LoggingMiddleware
docs example uses logging; public-API test catches bogus __all__ entries.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 5: Push the branch + open the PR**

```bash
git push -u origin fix/small-mop-up
```

```bash
gh pr create --base main --head fix/small-mop-up --title "fix(small-fixes): close 4 audit findings (0.8.5)" --body "$(cat <<'EOF'
## Summary

Closes 4 of the remaining audit findings — two Lows in production code, two Nits in docs/tests. See [\`planning/specs/2026-06-08-small-fixes-mop-up-design.md\`](planning/specs/2026-06-08-small-fixes-mop-up-design.md) for the design and [\`planning/releases/0.8.5.md\`](planning/releases/0.8.5.md) for the user-facing release notes.

## What changes

- **\`chain.py\` TYPE_CHECKING block dropped.** \`typing.get_type_hints(compose_async)\` and \`typing.get_type_hints(compose)\` now resolve cleanly.
- **\`pydantic.py\` TypeAdapter import is unconditional.** Eliminates the NameError window on module-reload with the install flag patched off.
- **\`LoggingMiddleware\` docs example uses \`logging\` instead of \`print()\`.** Matches CLAUDE.md's "no print()" invariant.
- **Public-API test asserts set equality against \`__all__\`.** Catches bogus entries the old subtraction missed.

## Audit findings closed

| # | Severity | File:line | Closed by |
|---|---|---|---|
| 1 | Low | \`middleware/chain.py:9-10\` | hoist Middleware/AsyncMiddleware imports |
| 2 | Low | \`decoders/pydantic.py:15-16, 27, 43\` | unconditional TypeAdapter import |
| 3 | Nit | \`docs/middleware.md:156-161\` | logging-based example |
| 4 | Nit | \`tests/test_public_api.py:69-71\` | symmetric \`expected == set(__all__)\` |

## Test plan

- [x] Two new tests pin \`typing.get_type_hints\` resolution for both \`compose_async\` and \`compose\`.
- [x] Existing pydantic-missing tests continue to pass (the flag-patch path doesn't depend on TypeAdapter being conditionally bound).
- [x] Existing optional-extras isolation tests continue to pass — \`import httpware\` does not load pydantic.
- [x] Full suite + lint green after each commit.

## Release

Tag \`0.8.5\` from the merge SHA after this PR lands.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Capture the PR URL.

- [ ] **Step 6: Final verification**

```bash
git log --oneline -8
gh pr view --json url,state,title
```

Expected: 5 fix/docs commits on top of the spec; PR open against main.

## Reporting

Return DONE with the PR URL.

---

## Self-review notes

- **Spec coverage:** Spec finding #1 → T1; finding #2 → T2; finding #3 → T3; finding #4 → T4; release notes + PR → T5. All four findings covered, plus the release/PR step.
- **Placeholder scan:** All before/after strings are verbatim. Test bodies complete. Commit messages filled in. No "TBD" / "similar to".
- **Type/name consistency:** `_LOGGER` lowercase is used in the LoggingMiddleware example; the existing `RequestIdMiddleware` further down the file uses the same lowercase convention (verified during spec design). The `actual` variable in Task 4's symmetric assertion is reused in the error message.
- **TDD ordering:** T1 has a clean red→green sequence with two tests. T2 is a contract-narrowing change verified by existing tests (no new test needed — see spec §Tests). T3 is docs-only. T4 is a test-quality change; manual verification step confirms the new symmetric failure mode is real.
- **Order dependency:** None. T1-T4 are independent; T5 depends on T1-T4 all landing. The branch sequences them in order for diff readability.

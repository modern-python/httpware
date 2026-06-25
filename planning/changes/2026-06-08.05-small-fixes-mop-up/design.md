---
summary: Shipped 0.8.5 — 4 small audit findings
---

# Spec: Small-fixes mop-up (0.8.5)

**Date:** 2026-06-08
**Topic slug:** `small-fixes-mop-up`
**Branch:** `fix/small-mop-up`
**Target release:** `0.8.5` — patch (4 unrelated small fixes, no API change)
**Status:** drafted, awaiting user review

## Purpose

Close 4 small audit findings in one PR — two Lows in production code (chain.py TYPE_CHECKING violation, pydantic.py NameError window), one user-facing docs Nit (LoggingMiddleware print() example), and one public-API test Nit (asymmetric `__all__` assertion). Each is independently small; bundling avoids release churn.

| # | Severity | File | Headline |
|---|---|---|---|
| 1 | Low | `src/httpware/middleware/chain.py:9-10` | `if typing.TYPE_CHECKING:` block prevents `typing.get_type_hints()`; violates project memory |
| 2 | Low | `src/httpware/decoders/pydantic.py:15-16, 27, 43` | `TypeAdapter` is conditionally bound — `NameError` window if module is reloaded with `is_pydantic_installed=False` |
| 3 | Nit | `docs/middleware.md:156-161` | `LoggingMiddleware` example uses `print()` — contradicts CLAUDE.md "no print()" invariant |
| 4 | Nit | `tests/test_public_api.py:69-71` | `expected - __all__` is one-directional; bogus entries in `__all__` are not caught |

## Non-goals

- No new public API. No new exception types.
- No changes to `Middleware` / `AsyncMiddleware` Protocol definitions.
- No restructuring of the optional-extras seam beyond the targeted pydantic.py change.
- No rewrite of the `RequestIdMiddleware` example next door (only `LoggingMiddleware` is in scope).
- No changes to msgspec.py — the audit flagged pydantic specifically.

## Architecture

### Four commits, one PR

Order is mechanical (small standalone fixes — no dependencies between them):

1. `fix(chain): hoist Middleware/AsyncMiddleware imports out of TYPE_CHECKING guard` — finding #1
2. `fix(pydantic): unconditional TypeAdapter import — eliminate NameError window` — finding #2
3. `docs(middleware): rewrite LoggingMiddleware example with logging, not print()` — finding #3
4. `test(public-api): symmetric assertion against __all__` — finding #4
5. `docs(release): draft 0.8.5 notes`

(4 fix commits + 1 release-notes commit = 5 total.)

## Per-finding change list

### Finding #1 — chain.py TYPE_CHECKING block

The current code:

```python
import typing
from collections.abc import Awaitable, Callable, Sequence

import httpx2


if typing.TYPE_CHECKING:
    from httpware.middleware import AsyncMiddleware, Middleware


_AsyncNext: typing.TypeAlias = Callable[[httpx2.Request], Awaitable[httpx2.Response]]
_Next: typing.TypeAlias = Callable[[httpx2.Request], httpx2.Response]


def compose_async(middleware: "Sequence[AsyncMiddleware]", terminal: _AsyncNext) -> _AsyncNext:
    ...


def compose(middleware: "Sequence[Middleware]", terminal: _Next) -> _Next:
    ...
```

The two function signatures use string annotations referencing `AsyncMiddleware` / `Middleware`, which are only imported when `typing.TYPE_CHECKING`. `typing.get_type_hints(compose_async)` at runtime raises `NameError: name 'AsyncMiddleware' is not defined`.

Audit verified: `httpware.middleware.__init__` does not import `chain.py` back. So hoisting the imports to module top is safe.

**Fix:** drop the `if typing.TYPE_CHECKING:` guard; import the protocols unconditionally; drop the string-annotation quotes from the parameter types.

```python
import typing
from collections.abc import Awaitable, Callable, Sequence

import httpx2

from httpware.middleware import AsyncMiddleware, Middleware


_AsyncNext: typing.TypeAlias = Callable[[httpx2.Request], Awaitable[httpx2.Response]]
_Next: typing.TypeAlias = Callable[[httpx2.Request], httpx2.Response]


def compose_async(middleware: Sequence[AsyncMiddleware], terminal: _AsyncNext) -> _AsyncNext:
    ...


def _wrap(layer: AsyncMiddleware, inner: _AsyncNext) -> _AsyncNext:
    ...


def compose(middleware: Sequence[Middleware], terminal: _Next) -> _Next:
    ...


def _wrap_sync(layer: Middleware, inner: _Next) -> _Next:
    ...
```

(String annotations on `_wrap` and `_wrap_sync` also unquoted.)

### Finding #2 — pydantic.py NameError window

The current code conditionally imports `TypeAdapter`:

```python
if import_checker.is_pydantic_installed:
    from pydantic import TypeAdapter
```

Then references `TypeAdapter` at runtime in `_get_adapter` and `PydanticDecoder.decode`'s `TypeError` fallback. When the flag is False (only reachable by test-reload), `TypeAdapter` is undefined, and subsequent calls raise `NameError` instead of the documented `ImportError`.

**Fix (audit's Option 1):** hoist the `from pydantic import TypeAdapter` unconditionally. The module is gated upstream by `client.py:_default_pydantic_decoder()`'s fail-fast check (`PydanticDecoder.__init__` raises `ImportError` when the flag is False) — there is no real-world path that loads this module without pydantic installed.

```python
"""PydanticDecoder — module-level cached TypeAdapter adapter for ResponseDecoder.

Requires the `pydantic` extra: `pip install httpware[pydantic]`. The optional-extras
gate is enforced upstream — `client.py:_default_pydantic_decoder()` raises ImportError
before this module is imported when pydantic is absent. Tests simulating "pydantic
not installed" patch `import_checker.is_pydantic_installed=False` at runtime, which
makes `PydanticDecoder.__init__` raise ImportError; the module itself is still loaded.
"""

import functools
from typing import TypeVar

from pydantic import TypeAdapter

from httpware._internal import import_checker
```

The module docstring updates to describe the new contract; the `if import_checker.is_pydantic_installed:` guard around the import is removed.

This change does NOT affect the existing pydantic-missing tests (which patch the flag at runtime — the module is already loaded by then). The isolation test (`test_importing_httpware_does_not_import_pydantic`) is also unaffected: `import httpware` does not transitively import `httpware.decoders.pydantic` (verified by the test passing today and the import graph staying the same after this change).

### Finding #3 — LoggingMiddleware print()

The current `docs/middleware.md` snippet:

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

**Fix:** replace the two `print()` calls with a module-level logger and `info()` calls. Mirror the style of the existing `RequestIdMiddleware` example in the same file (which already uses `logging.getLogger(...)` pattern).

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

### Finding #4 — test_expected_exports symmetric assertion

The current test (`tests/test_public_api.py:69-71`):

```python
missing = expected - set(httpware.__all__)
assert not missing, f"expected exports missing from __all__: {missing}"
```

Catches symbols in `expected` not in `__all__`, but not the reverse — a symbol added to `__all__` that ISN'T in `expected` slips through. (The companion `test_all_exports_resolve` catches symbols in `__all__` that don't actually exist; the gap is real symbols accidentally added to `__all__`.)

**Fix:** symmetric assertion. The cleanest is to drop the directional subtraction and assert set equality:

```python
actual = set(httpware.__all__)
assert expected == actual, (
    f"__all__ mismatch:\n"
    f"  missing from __all__: {expected - actual}\n"
    f"  unexpected in __all__: {actual - expected}"
)
```

The error message names both directions so future test failures pinpoint which side drifted.

## Tests

For findings #1 + #4, add focused tests:

### Test for finding #1 (chain.py TYPE_CHECKING fix)

Add to `tests/test_middleware.py` (or `tests/test_middleware_sync.py`, whichever fits — the test exercises `compose_async`/`compose`):

```python
def test_compose_async_get_type_hints_resolves_without_nameerror() -> None:
    """typing.get_type_hints(compose_async) must resolve to real classes, not raise NameError.

    Pre-0.8.5: AsyncMiddleware was imported only under `if typing.TYPE_CHECKING`,
    so get_type_hints raised NameError at runtime.
    """
    import typing

    from httpware.middleware.chain import compose_async

    hints = typing.get_type_hints(compose_async)
    # The 'middleware' parameter's hint should mention AsyncMiddleware (Sequence[AsyncMiddleware]).
    assert "middleware" in hints


def test_compose_get_type_hints_resolves_without_nameerror() -> None:
    """Sync mirror of the above for the sync `compose`."""
    import typing

    from httpware.middleware.chain import compose

    hints = typing.get_type_hints(compose)
    assert "middleware" in hints
```

### Test for finding #4 (symmetric assertion)

The rewritten `test_expected_exports` IS the test — no additional test needed. To verify the symmetric assertion catches the new failure mode, the implementer should manually inject a fake symbol into `__all__` locally, run the test, confirm it fails with the "unexpected in __all__" message, then revert.

### No new test for finding #2 (pydantic NameError window)

The NameError window was only reachable by module-reload — a scenario that doesn't occur in production and the existing tests don't exercise. After Fix #2, `TypeAdapter` is always bound at module-load (since pydantic is required for the module to load). A test that "reloads the module with the flag patched" would only verify the new module-import contract, which is already implicitly tested by every test that imports `pydantic.py`.

### No new test for finding #3 (LoggingMiddleware print)

It's a docs example. The change is verified by reading the docs file and confirming no `print()` calls remain in the snippet.

## Verification

After each commit:

```bash
just lint-ci
uv run pytest -x --no-cov -q
```

Full suite + lint green after every commit.

## Release notes

`planning/releases/0.8.5.md` — short patch, no behavioral change visible to users on the happy path. The pydantic.py change is a contract narrowing (the docstring "importing without the extra works" was untrue in the test-reload edge case; now the contract matches reality). The chain.py change is observable only via `typing.get_type_hints` — useful for users introspecting middleware signatures.

## Acceptance criteria

1. Four fix commits + one release-notes commit on branch `fix/small-mop-up`.
2. `just lint-ci` and `uv run pytest` green after every commit.
3. PR opened against `main` with title `fix(small-fixes): close 4 audit findings (0.8.5)`.
4. After merge, tag `0.8.5` from the merge SHA; GitHub Release published from `planning/releases/0.8.5.md`.
5. Memory `release_0_8_5_shipped` added.

## Open questions

None. All four fixes are precisely specified and the audit's recommended directions hold.

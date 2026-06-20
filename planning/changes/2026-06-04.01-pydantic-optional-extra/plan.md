---
status: shipped
date: 2026-06-04
slug: pydantic-optional-extra
spec: pydantic-optional-extra
pr: 21
---

# Pydantic-as-optional-extra (0.3.0) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move `pydantic` from a hard dependency to an opt-in extra (matching how `msgspec` already works), drop the top-level `httpware.PydanticDecoder` re-export, fail fast at `AsyncClient.__init__` when the default decoder cannot be constructed, add malformed-payload tests for `PydanticDecoder`, and bring `README.md` and `planning/engineering.md` up to date for the 0.3.0 release.

**Architecture:** Mirror the `msgspec` pattern exactly. `_internal/import_checker.py` exposes `is_pydantic_installed`. `decoders/pydantic.py` guards the `from pydantic import TypeAdapter` import behind that flag and raises `ImportError` from `PydanticDecoder.__init__` when the extra is missing. `client.py` removes the unconditional top-level `PydanticDecoder` import and uses a lazy module-level helper that fails fast at `AsyncClient.__init__` when `decoder=None` and pydantic is unavailable. `httpware/__init__.py` no longer re-exports `PydanticDecoder`.

**Tech Stack:** Python 3.11+, `httpx2`, `pydantic` (now optional), `pytest`/`pytest-asyncio`/`hypothesis`, `uv`, `just`, `ruff`, `ty`.

**Target branch:** `feat/v0.3-pydantic-optional`.

**Source spec:** [`planning/specs/2026-06-04-pydantic-optional-extra-design.md`](../specs/2026-06-04-pydantic-optional-extra-design.md). Read it before starting — the *why* for each decision lives there.

---

## File structure

**Modified files:**
- `pyproject.toml` — move `pydantic` to `[project.optional-dependencies]`, bump version to `0.3.0`, update `all` extra.
- `src/httpware/_internal/import_checker.py` — add `is_pydantic_installed`.
- `src/httpware/decoders/pydantic.py` — guard the pydantic import; raise `ImportError` in `__init__`; drop the submodule-level `__all__`.
- `src/httpware/client.py` — remove top-level `PydanticDecoder` import; add `_default_pydantic_decoder` helper that fails fast at `__init__`.
- `src/httpware/__init__.py` — drop the `PydanticDecoder` re-export from imports and `__all__`.
- `tests/test_optional_extras_isolation.py` — add a pydantic-isolation subprocess test.
- `tests/test_decoders_pydantic.py` — update `PydanticDecoder` import path; add 7 parametrized malformed-payload tests.
- `tests/test_public_api.py` — move `"PydanticDecoder"` from the `expected` set to the `removed` set.
- `README.md` — full freshness pass.
- `planning/engineering.md` — §1, §3 Seam C, §7 updates.

**New files:**
- `tests/test_optional_extras_pydantic_missing.py` — fail-fast tests gated by patched `is_pydantic_installed`.
- `planning/releases/0.3.0.md` — release notes.

**Branch setup:** the worktree skill (`superpowers:using-git-worktrees`) may have already created a worktree on `feat/v0.3-pydantic-optional`. If not, before Task 1 run `git checkout -b feat/v0.3-pydantic-optional` from `main`. The plan assumes commits go to that branch.

---

## Task 1: Add `is_pydantic_installed` to `import_checker`

**Files:**
- Modify: `src/httpware/_internal/import_checker.py`

- [ ] **Step 1: Read the current file**

Run: `cat src/httpware/_internal/import_checker.py`
Expected current contents:

```python
"""Detect optional extras without importing them. Used by adapter modules to gate hard imports."""

from importlib.util import find_spec


is_msgspec_installed = find_spec("msgspec") is not None
```

- [ ] **Step 2: Add the new constant**

Replace the file with:

```python
"""Detect optional extras without importing them. Used by adapter modules to gate hard imports."""

from importlib.util import find_spec


is_msgspec_installed = find_spec("msgspec") is not None
is_pydantic_installed = find_spec("pydantic") is not None
```

- [ ] **Step 3: Lint check**

Run: `uv run ruff check src/httpware/_internal/import_checker.py && uv run ty check src/httpware/_internal/import_checker.py`
Expected: clean exit (`All checks passed!` or no output).

- [ ] **Step 4: Stage the change (hold the commit)**

```bash
git add src/httpware/_internal/import_checker.py
```

(Commits are batched per the spec's §Execution order; this change joins Task 4's commit.)

---

## Task 2: Failing test — `PydanticDecoder.__init__` raises `ImportError` when pydantic missing

**Files:**
- Create: `tests/test_optional_extras_pydantic_missing.py`

- [ ] **Step 1: Create the new test file**

```python
"""Fail-fast tests for the pydantic optional-extra (0.3.0).

Pydantic IS installed in the CI test environment via `--all-extras`. To
simulate the "extra not installed" case, patch
`httpware._internal.import_checker.is_pydantic_installed = False` for the
duration of the test.
"""

from unittest.mock import patch

import pytest

from httpware import AsyncClient
from httpware.decoders.pydantic import PydanticDecoder


def test_pydantic_decoder_init_raises_when_pydantic_missing() -> None:
    with patch("httpware._internal.import_checker.is_pydantic_installed", False):
        with pytest.raises(ImportError, match=r"httpware\[pydantic\]"):
            PydanticDecoder()


def test_async_client_default_decoder_raises_when_pydantic_missing() -> None:
    with patch("httpware._internal.import_checker.is_pydantic_installed", False):
        with pytest.raises(ImportError, match=r"httpware\[pydantic\]"):
            AsyncClient()


def test_async_client_accepts_explicit_decoder_without_pydantic() -> None:
    """An explicit decoder= escapes the fail-fast even when pydantic is 'missing'."""

    class _FakeDecoder:
        def decode(self, content: bytes, model: type) -> object:
            return model()

    with patch("httpware._internal.import_checker.is_pydantic_installed", False):
        client = AsyncClient(decoder=_FakeDecoder())
        assert client is not None
```

- [ ] **Step 2: Run the test, verify the first two fail**

Run: `uv run pytest tests/test_optional_extras_pydantic_missing.py -v`
Expected:
- `test_pydantic_decoder_init_raises_when_pydantic_missing` — **FAIL** (`PydanticDecoder()` currently does not check `is_pydantic_installed`).
- `test_async_client_default_decoder_raises_when_pydantic_missing` — **FAIL** (`AsyncClient.__init__` currently does not check either).
- `test_async_client_accepts_explicit_decoder_without_pydantic` — **PASS** (no fail-fast yet, so explicit decoder definitely works).

Tasks 3 and 5 make the failing tests pass.

- [ ] **Step 3: Stage the test file**

```bash
git add tests/test_optional_extras_pydantic_missing.py
```

---

## Task 3: Guard `decoders/pydantic.py` + `PydanticDecoder.__init__` raises

**Files:**
- Modify: `src/httpware/decoders/pydantic.py`

- [ ] **Step 1: Read the current file**

Run: `cat src/httpware/decoders/pydantic.py`
Expected current contents (29 lines including the `__all__`):

```python
"""PydanticDecoder — module-level cached TypeAdapter adapter for ResponseDecoder."""

import functools
from typing import TypeVar

from pydantic import TypeAdapter


T = TypeVar("T")


@functools.lru_cache(maxsize=1024)
def _get_adapter(model: type[T]) -> TypeAdapter[T]:
    return TypeAdapter(model)


class PydanticDecoder:
    """Decode raw response bytes into `model` via a cached `pydantic.TypeAdapter`."""

    def decode(self, content: bytes, model: type[T]) -> T:
        """Validate `content` as JSON against `model` in a single parse pass."""
        try:
            adapter = _get_adapter(model)
        except TypeError:
            adapter = TypeAdapter(model)
        return adapter.validate_json(content)


__all__ = ["PydanticDecoder"]
```

- [ ] **Step 2: Replace with the guarded version**

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


MISSING_DEPENDENCY_MESSAGE = (
    "PydanticDecoder requires the 'pydantic' extra. Install with: pip install httpware[pydantic]"
)

T = TypeVar("T")


@functools.lru_cache(maxsize=1024)
def _get_adapter(model: type[T]) -> "TypeAdapter[T]":
    return TypeAdapter(model)


class PydanticDecoder:
    """Decode raw response bytes into `model` via a cached `pydantic.TypeAdapter`."""

    def __init__(self) -> None:
        if not import_checker.is_pydantic_installed:
            raise ImportError(MISSING_DEPENDENCY_MESSAGE)

    def decode(self, content: bytes, model: type[T]) -> T:
        """Validate `content` as JSON against `model` in a single parse pass."""
        try:
            adapter = _get_adapter(model)
        except TypeError:
            adapter = TypeAdapter(model)
        return adapter.validate_json(content)
```

Notes on the changes (read these — they prevent surprise):
- `from pydantic import TypeAdapter` is now inside `if import_checker.is_pydantic_installed:`. The module imports cleanly even without pydantic.
- `_get_adapter`'s return-type annotation became the **string** `"TypeAdapter[T]"`. Without the string, the annotation evaluates at function-definition time and would raise `NameError` when pydantic is absent. The string defers evaluation to anyone explicitly calling `typing.get_type_hints()`, which never happens in our hot paths.
- `_get_adapter`'s body still references `TypeAdapter` directly — that's fine because the body only runs when `_get_adapter()` is called, which only happens after `PydanticDecoder.__init__` succeeds, which only succeeds with pydantic installed.
- `MISSING_DEPENDENCY_MESSAGE` is a module-level UPPER_CASE constant (matches the existing pattern in `decoders/msgspec.py`).
- The submodule-level `__all__ = ["PydanticDecoder"]` is **removed** — submodules don't need `__all__`; that lives only in `httpware/__init__.py`.

- [ ] **Step 3: Run the failing test, verify it now passes**

Run: `uv run pytest tests/test_optional_extras_pydantic_missing.py::test_pydantic_decoder_init_raises_when_pydantic_missing -v`
Expected: **PASS**.

- [ ] **Step 4: Run the full pydantic-decoder test file, verify no regression**

Run: `uv run pytest tests/test_decoders_pydantic.py -v`
Expected: all existing tests still pass (pydantic IS installed in the test env, so the guard is true, the `from pydantic import TypeAdapter` runs, and behavior is unchanged for the happy path).

- [ ] **Step 5: Lint**

Run: `uv run ruff check src/httpware/decoders/pydantic.py && uv run ty check src/httpware/decoders/pydantic.py`
Expected: clean.

- [ ] **Step 6: Stage**

```bash
git add src/httpware/decoders/pydantic.py
```

---

## Task 4: Commit Task 1 + Task 2 + Task 3 together

The spec groups `is_pydantic_installed` + the `decoders/pydantic.py` guard + its tests into one logical change.

- [ ] **Step 1: Verify staged contents**

Run: `git diff --cached --stat`
Expected: three files changed — `src/httpware/_internal/import_checker.py`, `src/httpware/decoders/pydantic.py`, `tests/test_optional_extras_pydantic_missing.py`.

- [ ] **Step 2: Commit**

```bash
git commit -m "$(cat <<'EOF'
feat(extras): guard pydantic import + fail-fast in PydanticDecoder.__init__

Adds is_pydantic_installed to _internal/import_checker.py; guards the
pydantic import in decoders/pydantic.py the same way msgspec is guarded;
PydanticDecoder.__init__ raises ImportError with the install hint when
the extra is missing. New tests in tests/test_optional_extras_pydantic_missing.py
cover both the PydanticDecoder fail-fast and the explicit-decoder escape
hatch. Drops the submodule-level __all__ in decoders/pydantic.py.

Part of the 0.3.0 pydantic-optional-extra work
(planning/specs/2026-06-04-pydantic-optional-extra-design.md).
EOF
)"
```

---

## Task 5: Lazy default decoder + fail-fast in `client.py`

**Files:**
- Modify: `src/httpware/client.py`

- [ ] **Step 1: Re-read the relevant lines**

Run: `sed -n '1,20p;85,92p' src/httpware/client.py`
Expected: imports at lines 1–19 include `from httpware.decoders.pydantic import PydanticDecoder` on line 10; line 88 reads `self._decoder = decoder if decoder is not None else PydanticDecoder()`.

- [ ] **Step 2: Remove the top-level `PydanticDecoder` import**

Edit `src/httpware/client.py`: delete line 10 (`from httpware.decoders.pydantic import PydanticDecoder`).

- [ ] **Step 3: Add the `import_checker` import**

Add `from httpware._internal import import_checker` to the imports block (after the other `httpware.*` imports, before the blank line preceding the module-level definitions).

- [ ] **Step 4: Add the `_default_pydantic_decoder` helper and the message constant**

After the existing module-level constants (`_FORWARDED_KWARG_NAMES`, `_HTTPX2_CLIENT_CONFLICT_MESSAGE`) and before `class AsyncClient`, insert:

```python
_DEFAULT_DECODER_MISSING_MESSAGE = (
    "AsyncClient(decoder=None) defaults to PydanticDecoder, which requires the "
    "'pydantic' extra. Either install it (`pip install httpware[pydantic]`) or "
    "pass an explicit decoder=..."
)


def _default_pydantic_decoder() -> ResponseDecoder:
    if not import_checker.is_pydantic_installed:
        raise ImportError(_DEFAULT_DECODER_MISSING_MESSAGE)
    from httpware.decoders.pydantic import PydanticDecoder  # noqa: PLC0415 — lazy by design

    return PydanticDecoder()
```

The `# noqa: PLC0415` justification is real (lazy default is the design); per the user's memory on lint suppression, per-line `# noqa` with a justification is preferred over project-wide ignore or hoisting.

- [ ] **Step 5: Update `__init__` line 88**

Replace:

```python
self._decoder = decoder if decoder is not None else PydanticDecoder()
```

With:

```python
self._decoder = decoder if decoder is not None else _default_pydantic_decoder()
```

- [ ] **Step 6: Run the failing fail-fast test, verify it now passes**

Run: `uv run pytest tests/test_optional_extras_pydantic_missing.py -v`
Expected: all 3 tests pass.

- [ ] **Step 7: Run the full client test suite**

Run: `uv run pytest tests/test_client_construction.py tests/test_client_lifecycle.py tests/test_client_methods.py tests/test_client_middleware_wiring.py tests/test_client_response_model.py tests/test_client_typing.py tests/test_error_mapping_terminal.py -v`
Expected: all pass. `test_client_construction.py:53` (`isinstance(client._decoder, PydanticDecoder)`) still passes because pydantic IS installed and the lazy import succeeds.

- [ ] **Step 8: Lint**

Run: `uv run ruff check src/httpware/client.py && uv run ty check src/httpware/client.py`
Expected: clean.

- [ ] **Step 9: Stage and commit**

```bash
git add src/httpware/client.py
git commit -m "$(cat <<'EOF'
feat(client): lazy default decoder with fail-fast at __init__

Removes the unconditional top-level PydanticDecoder import. Adds
_default_pydantic_decoder() that checks is_pydantic_installed up front
and raises ImportError immediately when AsyncClient(decoder=None) is
constructed without the pydantic extra. Explicit decoder= arguments
bypass the check.

Part of the 0.3.0 pydantic-optional-extra work
(planning/specs/2026-06-04-pydantic-optional-extra-design.md).
EOF
)"
```

---

## Task 6: Failing pydantic-isolation subprocess test

**Files:**
- Modify: `tests/test_optional_extras_isolation.py`

- [ ] **Step 1: Append the new test**

Add to the end of the file:

```python
def test_importing_httpware_does_not_import_pydantic() -> None:
    """Fresh subprocess: pydantic must NOT appear in sys.modules after `import httpware`.

    pydantic IS installed in the test environment (via `--all-extras`), so this
    test runs in a subprocess with a clean interpreter to verify that nothing
    in the httpware import chain pulls pydantic in.
    """
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import httpware; import sys; sys.exit(0 if 'pydantic' not in sys.modules else 1)",
        ],
        check=False,
        capture_output=True,
    )
    assert result.returncode == 0, (
        f"pydantic was loaded transitively by `import httpware`; "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
```

- [ ] **Step 2: Run the test, verify it fails**

Run: `uv run pytest tests/test_optional_extras_isolation.py::test_importing_httpware_does_not_import_pydantic -v`
Expected: **FAIL**. After Task 5, `client.py` no longer imports `PydanticDecoder` directly, but `httpware/__init__.py:5` still does. So `import httpware` still loads pydantic transitively. Task 7 makes this pass.

- [ ] **Step 3: Stage the test (hold the commit; pairs with Task 7)**

```bash
git add tests/test_optional_extras_isolation.py
```

---

## Task 7: Drop `PydanticDecoder` from the top-level public API + tests

**Files:**
- Modify: `src/httpware/__init__.py`
- Modify: `tests/test_public_api.py`
- Modify: `tests/test_decoders_pydantic.py`

- [ ] **Step 1: Update `httpware/__init__.py`**

Delete line 5 (`from httpware.decoders.pydantic import PydanticDecoder`).
Delete the `"PydanticDecoder",` entry in `__all__` (currently line 39).

After edits, the imports look like:

```python
"""httpware — thin async HTTP client wrapper over httpx2."""

from httpware.client import AsyncClient
from httpware.decoders import ResponseDecoder
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
```

And `__all__` is the same list minus `"PydanticDecoder"`.

- [ ] **Step 2: Update `tests/test_public_api.py`**

Move `"PydanticDecoder"` from the `expected` set in `test_expected_exports` to the `removed` set in `test_no_removed_symbols_leaked`. After edits:

```python
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
        "PydanticDecoder",
    }
    leaked = removed & set(dir(httpware))
    assert not leaked, f"removed 0.1 symbols still exposed: {leaked}"


def test_expected_exports() -> None:
    expected = {
        "AsyncClient",
        "Middleware",
        "Next",
        "ResponseDecoder",
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

- [ ] **Step 3: Update `tests/test_decoders_pydantic.py` import path**

Replace line 11:

```python
from httpware import PydanticDecoder, ResponseDecoder
```

With:

```python
from httpware import ResponseDecoder
from httpware.decoders.pydantic import PydanticDecoder
```

All 16 test bodies in the file already use `PydanticDecoder` as a bare name — no further changes needed.

- [ ] **Step 4: Run the isolation test, verify it now passes**

Run: `uv run pytest tests/test_optional_extras_isolation.py -v`
Expected: both `test_importing_httpware_does_not_import_msgspec` and `test_importing_httpware_does_not_import_pydantic` pass.

- [ ] **Step 5: Run `test_public_api.py`**

Run: `uv run pytest tests/test_public_api.py -v`
Expected: all 3 tests pass.

- [ ] **Step 6: Run `test_decoders_pydantic.py`**

Run: `uv run pytest tests/test_decoders_pydantic.py -v`
Expected: all 16 existing tests pass with the new import path.

- [ ] **Step 7: Run the entire test suite to catch any other consumer of the top-level export**

Run: `uv run pytest -v`
Expected: every test passes. If anything fails with `ImportError: cannot import name 'PydanticDecoder' from 'httpware'`, fix the consumer to use the submodule path.

- [ ] **Step 8: Lint**

Run: `uv run ruff check . && uv run ty check`
Expected: clean.

- [ ] **Step 9: Stage and commit**

```bash
git add src/httpware/__init__.py tests/test_public_api.py tests/test_decoders_pydantic.py tests/test_optional_extras_isolation.py
git commit -m "$(cat <<'EOF'
feat(api): drop top-level PydanticDecoder re-export

PydanticDecoder is no longer re-exported from httpware/__init__.py.
Consumers import it from httpware.decoders.pydantic instead, mirroring
how MsgspecDecoder is already accessed. test_public_api.py moves the
symbol from expected to removed; tests/test_decoders_pydantic.py uses
the submodule import path; a new subprocess test in
tests/test_optional_extras_isolation.py guards against pydantic being
re-introduced as a transitive load.

Breaking change for callers using `from httpware import PydanticDecoder`.

Part of the 0.3.0 pydantic-optional-extra work
(planning/specs/2026-06-04-pydantic-optional-extra-design.md).
EOF
)"
```

---

## Task 8: Malformed-payload tests for `PydanticDecoder`

**Files:**
- Modify: `tests/test_decoders_pydantic.py`

- [ ] **Step 1: Append parametrized test cases to the end of the file**

```python
@pytest.mark.parametrize(
    ("payload", "model"),
    [
        (b"", int),
        (b"", User),
        (b"null", int),
        (b"null", User),
        (b"{}", User),
        (b"{not-json}", User),
        (b"\xff\xfe\x00\x00", User),
    ],
)
def test_malformed_payload_raises_validation_error(payload: bytes, model: type) -> None:
    """Pin current pydantic-core behavior for malformed payloads.

    A future pydantic upgrade that changes which error type surfaces will fail
    this test, surfacing the change for explicit acceptance or workaround.
    """
    with pytest.raises(pydantic.ValidationError):
        PydanticDecoder().decode(payload, model)
```

The `User` model is already defined at the top of the file (`class User(pydantic.BaseModel): id: int; name: str`). No other changes needed.

- [ ] **Step 2: Run the new tests, verify they pass**

Run: `uv run pytest tests/test_decoders_pydantic.py::test_malformed_payload_raises_validation_error -v`
Expected: 7 parametrized cases, all **PASS**. The tests pin current pydantic-core behavior; they do not change the implementation.

- [ ] **Step 3: Run the full pydantic-decoder test file to ensure no regression**

Run: `uv run pytest tests/test_decoders_pydantic.py -v`
Expected: 16 original + 7 new = 23 tests, all pass.

- [ ] **Step 4: Lint**

Run: `uv run ruff check tests/test_decoders_pydantic.py`
Expected: clean.

- [ ] **Step 5: Stage and commit**

```bash
git add tests/test_decoders_pydantic.py
git commit -m "$(cat <<'EOF'
test: pin pydantic-core behavior for malformed payloads

Parametrized tests for empty bytes, null literal, empty object,
malformed JSON, and invalid UTF-8 against both a primitive int and a
BaseModel subclass. Pins current pydantic.ValidationError surface so a
future pydantic upgrade that changes the error type fails visibly
instead of silently changing semantics.

Closes the "empty/malformed payload tests" item from
planning/deferred-work.md. Part of the 0.3.0 pydantic-optional-extra
work.
EOF
)"
```

---

## Task 9: Move `pydantic` to `[project.optional-dependencies]` + version bump

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Read the current `[project]` and `[project.optional-dependencies]` sections**

Run: `sed -n '1,50p' pyproject.toml`
Expected: `version = "0.2.0"`, `dependencies = ["httpx2>=2.0.0,<3.0", "pydantic>=2.0,<3.0"]`, `[project.optional-dependencies]` has `msgspec`, `otel`, `all = ["httpware[msgspec,otel]"]`.

- [ ] **Step 2: Update `dependencies`**

Remove `"pydantic>=2.0,<3.0"` from the `dependencies` list. The remaining list is just `["httpx2>=2.0.0,<3.0"]`.

- [ ] **Step 3: Add `pydantic` extra**

Inside `[project.optional-dependencies]`, add `pydantic = ["pydantic>=2.0,<3.0"]` as the first entry (alphabetical pairing is not enforced; this just keeps related extras grouped logically).

- [ ] **Step 4: Update the `all` extra**

Change `all = ["httpware[msgspec,otel]"]` to `all = ["httpware[pydantic,msgspec,otel]"]`.

- [ ] **Step 5: Bump the version**

Change `version = "0.2.0"` to `version = "0.3.0"`.

- [ ] **Step 6: Refresh the lockfile and reinstall**

Run: `just install`
Expected: `uv lock --upgrade && uv sync --all-extras --frozen --group lint` completes without error. `uv.lock` should now list `pydantic` as an extra-gated dependency.

- [ ] **Step 7: Re-run the full test suite under the new install**

Run: `just test`
Expected: every test passes. The isolation subprocess test (`test_importing_httpware_does_not_import_pydantic`) is the load-bearing one here — if it fails, something still imports pydantic at the package root.

- [ ] **Step 8: Lint (full project)**

Run: `just lint-ci`
Expected: clean.

- [ ] **Step 9: Stage and commit**

```bash
git add pyproject.toml uv.lock
git commit -m "$(cat <<'EOF'
feat(extras): move pydantic to optional-dependencies + bump to 0.3.0

pydantic moves from [project] dependencies to
[project.optional-dependencies]. Install httpware[pydantic] to keep
the default-decoder UX; the all extra now bundles pydantic, msgspec,
and otel.

Breaking change. See planning/releases/0.3.0.md for the full migration
story. Part of the 0.3.0 pydantic-optional-extra work.
EOF
)"
```

---

## Task 10: `README.md` freshness pass

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Read the current README**

Run: `cat README.md`
Expected: 55 lines starting with `# httpware`, mentions "0.1.0 alpha" status, `RecordedTransport`, and a Quickstart that uses `from pydantic import BaseModel`.

- [ ] **Step 2: Rewrite the top blurb (line 10)**

Replace the existing blurb line with:

```markdown
`httpware` is a thin opinionated wrapper around `httpx2`. It re-exports `httpx2.Request`/`httpx2.Response`, adds a middleware chain composed at client construction, supports opt-in typed response decoding (pydantic and msgspec are both extras), and raises a status-keyed exception tree automatically on 4xx/5xx.
```

- [ ] **Step 3: Rewrite the status note (line 12)**

Replace with:

```markdown
> **Status:** Pre-1.0 (0.3.0). Public API is subject to change between minor releases until v1.0. Resilience middleware (retry / timeout / bulkhead), streaming, and observability are not yet shipped.
```

- [ ] **Step 4: Rewrite the Install section**

Replace the existing Install block (lines 14–26) with:

```markdown
## Install

```bash
pip install httpware                # core only — no decoder
pip install httpware[pydantic]      # + PydanticDecoder (the default-decoder path)
pip install httpware[msgspec]       # + MsgspecDecoder
pip install httpware[all]           # everything declared above (pydantic, msgspec, otel)
```

`AsyncClient()` with no `decoder=` argument defaults to constructing a `PydanticDecoder`; that path requires the `pydantic` extra and raises `ImportError` at `AsyncClient.__init__` if it is missing. The `otel` extra is declared but the OpenTelemetry middleware (Epic 5) has not shipped yet.
```

- [ ] **Step 5: Update the Quickstart**

Prepend a one-line note before the code block, and verify the example still parses:

```markdown
## Quickstart

> Requires: `pip install httpware[pydantic]`

```python
from httpware import AsyncClient
from pydantic import BaseModel


class User(BaseModel):
    id: int
    name: str


async def main() -> None:
    async with AsyncClient(base_url="https://api.example.com") as client:
        user = await client.get("/users/1", response_model=User)
        print(user.name)
```
```

- [ ] **Step 6: Confirm no stale references remain**

Run: `grep -nE 'RecordedTransport|0\.1\.0|respx|niquests' README.md`
Expected: zero matches. If any survive, remove them.

- [ ] **Step 7: Stage (hold the commit until Task 11)**

```bash
git add README.md
```

---

## Task 11: `planning/engineering.md` §1, §3, §7 updates

**Files:**
- Modify: `planning/engineering.md`

- [ ] **Step 1: Update §1 ("Project intent")**

In `planning/engineering.md`, find §1's sentence:

```
`httpware` is a thin opinionated wrapper around `httpx2`. It re-exports `httpx2.Request` and `httpx2.Response` as the public request/response surface and adds three things on top: typed response decoding (via a `ResponseDecoder` protocol; Pydantic ships as the default, msgspec as an opt-in extra), a middleware chain composed at client construction, and a status-keyed exception tree raised automatically on 4xx and 5xx.
```

Replace with:

```
`httpware` is a thin opinionated wrapper around `httpx2`. It re-exports `httpx2.Request` and `httpx2.Response` as the public request/response surface and adds three things on top: typed response decoding (via a `ResponseDecoder` protocol; pydantic and msgspec are both opt-in extras as of 0.3.0), a middleware chain composed at client construction, and a status-keyed exception tree raised automatically on 4xx and 5xx. `AsyncClient(decoder=None)` defaults to constructing a `PydanticDecoder` and so requires the `pydantic` extra; callers can supply an explicit `decoder=` argument to escape the default.
```

- [ ] **Step 2: Update §3 Seam C ("`httpware ↔ optional extras`")**

Find the Seam C "Where:" bullet:

```
- **Where:** `pyproject.toml` extras (`[project.optional-dependencies]`) ↔ the adapter modules that import them.
```

Leave that as-is. After the existing rule line, append a new line:

```
- **Verification:** `tests/test_optional_extras_isolation.py` runs a fresh-subprocess `import httpware` and asserts that neither pydantic nor msgspec ends up in `sys.modules`. New extras must add the same isolation test.
```

- [ ] **Step 3: Update §7 ("Optional-extras pattern")**

The §7 code block already shows pydantic in `[project.optional-dependencies]`, so it is now accurate. After the code block, replace the prose paragraph that ends with "grep for `import pydantic` should return exactly one file" with:

```
Each extra's code lives in a single dedicated module (`decoders/pydantic.py`, `decoders/msgspec.py`, `middleware/observability/otel.py` when Epic 5 lands). The `import` of the extra happens **inside** that module behind an `is_<extra>_installed` guard from `_internal/import_checker.py` — never at package top level. This way, `import httpware` works cleanly without the extras installed, and the seam stays observable: `grep -rE '^from pydantic|^import pydantic' src/httpware/` returns exactly one file (the guarded import in `decoders/pydantic.py`), and the same is true for `msgspec`.
```

- [ ] **Step 4: Verify nothing else in engineering.md references "Pydantic ships as the default"**

Run: `grep -nE 'Pydantic ships as the default|pydantic.*required|required dependency' planning/engineering.md`
Expected: zero matches. If any survive, update them to match the new framing.

- [ ] **Step 5: Stage and commit (bundles README + engineering.md)**

```bash
git add planning/engineering.md
git commit -m "$(cat <<'EOF'
docs: README freshness pass + engineering.md §1/§3/§7 for 0.3.0

README rewrites the post-pivot blurb, replaces the stale "0.1.0 alpha"
status with 0.3.0, drops the RecordedTransport reference, and adds the
[pydantic] extra to install instructions. engineering.md §1 retracts
"Pydantic ships as the default"; §3 Seam C adds the isolation-test
verification rule; §7 spells out the guarded-import pattern explicitly.

Part of the 0.3.0 pydantic-optional-extra work.
EOF
)"
```

---

## Task 12: Draft `planning/releases/0.3.0.md`

**Files:**
- Create: `planning/releases/0.3.0.md`

- [ ] **Step 1: Write the release notes**

Copy this content verbatim into `planning/releases/0.3.0.md`:

```markdown
# httpware 0.3.0 — pydantic as an optional extra

## Breaking changes

- **`pydantic` is no longer a required dependency.** It moved from `[project] dependencies` to `[project.optional-dependencies]`. Install it explicitly: `pip install httpware[pydantic]`. The `httpware[all]` extra continues to include it.
- **`httpware.PydanticDecoder` is no longer re-exported from the top-level package.** Import directly from the submodule: `from httpware.decoders.pydantic import PydanticDecoder`. This mirrors the existing `MsgspecDecoder` import path.
- **`AsyncClient()` with `decoder=None` and no pydantic extra raises `ImportError` at `__init__`.** Pass `decoder=MsgspecDecoder()` or install `httpware[pydantic]` to keep the default behavior.

## Other changes

- `tests/test_decoders_pydantic.py` adds parametrized payload-edge tests that pin current pydantic-core behavior for `b""`, `b"null"`, `b"{}"`, malformed JSON, and invalid UTF-8.
- `tests/test_optional_extras_isolation.py` now covers both pydantic and msgspec via fresh-subprocess `import httpware` checks.
- README freshness pass: status line corrected from "0.1.0 alpha" to "0.3.0"; post-pivot framing replaces the pre-pivot description; `RecordedTransport` reference removed.

## Migration

```python
# 0.2.0
from httpware import AsyncClient, PydanticDecoder

async with AsyncClient(base_url="https://api.example.com") as client:
    user = await client.get("/users/1", response_model=User)
```

```python
# 0.3.0 — option 1: install the extra, code unchanged
# pip install httpware[pydantic]
from httpware import AsyncClient

async with AsyncClient(base_url="https://api.example.com") as client:
    user = await client.get("/users/1", response_model=User)

# 0.3.0 — option 2: import PydanticDecoder from the submodule
from httpware import AsyncClient
from httpware.decoders.pydantic import PydanticDecoder

async with AsyncClient(decoder=PydanticDecoder()) as client:
    user = await client.get("/users/1", response_model=User)
```

## What's next

Epic 3 (resilience middleware — retry, timeout, bulkhead) and Epic 5 (observability) ship in subsequent releases. See `planning/engineering.md` §8.
```

- [ ] **Step 2: Stage and commit**

```bash
git add planning/releases/0.3.0.md
git commit -m "$(cat <<'EOF'
chore(release): draft 0.3.0 release notes

Documents the pydantic-as-optional-extra breaking change with two
migration paths (install the extra, or import PydanticDecoder from the
submodule). Notes the malformed-payload tests, isolation-test addition,
and README freshness pass.

Part of the 0.3.0 pydantic-optional-extra work.
EOF
)"
```

---

## Task 13: Final verification

**Files:** none modified.

- [ ] **Step 1: Verify the full test suite still passes**

Run: `just test`
Expected: every test green.

- [ ] **Step 2: Verify the lint and type checks are clean**

Run: `just lint-ci`
Expected: ruff format/check pass, ty check passes, no errors.

- [ ] **Step 3: Verify CI invariants enforced by the project**

Run: `grep -rE 'httpx2\._' src/httpware/`
Expected: zero matches (the no-`httpx2._` invariant from `CLAUDE.md`).

Run: `grep -rE '^from pydantic|^import pydantic' src/httpware/`
Expected: exactly one match — `src/httpware/decoders/pydantic.py`'s guarded import.

Run: `grep -rE '^from msgspec|^import msgspec' src/httpware/`
Expected: exactly one match — `src/httpware/decoders/msgspec.py`'s guarded import.

Run: `grep -rE 'from __future__ import annotations' src/httpware/`
Expected: zero matches (project rule).

Run: `grep -rE 'print\(' src/httpware/`
Expected: zero matches (project rule).

- [ ] **Step 4: Verify the spec acceptance criteria**

Open `planning/specs/2026-06-04-pydantic-optional-extra-design.md` § Acceptance criteria. Walk each bullet and confirm it is true. Twelve bullets, all should pass.

- [ ] **Step 5: Verify branch state**

Run: `git log --oneline main..HEAD`
Expected: 7 commits on the feature branch, in order:
  1. `feat(extras): guard pydantic import + fail-fast in PydanticDecoder.__init__` (Task 4)
  2. `feat(client): lazy default decoder with fail-fast at __init__` (Task 5)
  3. `feat(api): drop top-level PydanticDecoder re-export` (Task 7)
  4. `test: pin pydantic-core behavior for malformed payloads` (Task 8)
  5. `feat(extras): move pydantic to optional-dependencies + bump to 0.3.0` (Task 9)
  6. `docs: README freshness pass + engineering.md §1/§3/§7 for 0.3.0` (Task 11)
  7. `chore(release): draft 0.3.0 release notes` (Task 12)

- [ ] **Step 6: Push and open the PR**

```bash
git push -u origin feat/v0.3-pydantic-optional
gh pr create --title "feat: pydantic as an optional extra (0.3.0)" --body "$(cat <<'EOF'
## Summary

- Moves `pydantic` from a required dependency to an opt-in extra (`pip install httpware[pydantic]`).
- Drops the top-level `httpware.PydanticDecoder` re-export; consumers import from `httpware.decoders.pydantic` instead, matching the `MsgspecDecoder` pattern.
- `AsyncClient(decoder=None)` without the `pydantic` extra installed now raises `ImportError` at `__init__` with a clear install hint.
- Pins pydantic-core behavior on malformed payloads via parametrized tests.
- Brings `README.md` and `planning/engineering.md` up to date for 0.3.0.

## Spec

[`planning/specs/2026-06-04-pydantic-optional-extra-design.md`](planning/specs/2026-06-04-pydantic-optional-extra-design.md)

## Test plan

- [ ] `just lint-ci` clean
- [ ] `just test` green
- [ ] `grep -rE '^from pydantic|^import pydantic' src/httpware/` returns exactly one file
- [ ] `pip install httpware` (core only, no extra) — `from httpware import AsyncClient` works; `AsyncClient()` raises `ImportError` with the install hint
- [ ] `pip install httpware[pydantic]` — `AsyncClient()` works, default `PydanticDecoder` is constructed
- [ ] `from httpware import PydanticDecoder` fails with `ImportError: cannot import name 'PydanticDecoder'` (breaking change is visible)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Expected: PR URL printed.

---

## Self-review

After completing all tasks, walk this checklist before declaring done:

**Spec coverage** — every requirement in `planning/specs/2026-06-04-pydantic-optional-extra-design.md` has a task:
- Deliverable 1 (pyproject.toml): Task 9 ✓
- Deliverable 2 (import_checker): Task 1 ✓
- Deliverable 3 (decoders/pydantic.py): Task 3 ✓
- Deliverable 4 (client.py): Task 5 ✓
- Deliverable 5 (httpware/__init__.py): Task 7 ✓
- Deliverable 6.1 (test updates): Task 7 ✓
- Deliverable 6.2 (pydantic-isolation test): Task 6 + Task 7 ✓
- Deliverable 6.3 (fail-fast tests): Task 2 + Task 5 ✓
- Deliverable 6.4 (malformed-payload tests): Task 8 ✓
- Deliverable 7.1 (README): Task 10 ✓
- Deliverable 7.2/7.3/7.4 (engineering.md): Task 11 ✓
- Deliverable 8 (release notes): Task 12 ✓
- Deliverable 9 (deferred-work updates after merge): out of band — addressed in the post-merge memory/deferred-work update conversation, not in this plan.

**Type consistency** — the same names used everywhere: `is_pydantic_installed`, `_default_pydantic_decoder`, `MISSING_DEPENDENCY_MESSAGE`, `_DEFAULT_DECODER_MISSING_MESSAGE`, `PydanticDecoder`. No drift.

**Placeholder scan** — no TBDs, no "implement later", no "similar to Task N" hand-waves. Every code change has full code; every test has full code.

**Commit ordering** — 7 logical commits: Task 4 (foundation + decoders guard + tests), Task 5 (client lazy default), Task 7 (top-level drop + test updates), Task 8 (payload tests), Task 9 (pyproject + lock), Task 11 (README + engineering.md), Task 12 (release notes). Matches the spec's §Execution order.

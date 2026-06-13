---
status: shipped
date: 2026-06-04
slug: pydantic-optional-extra
supersedes: null
superseded_by: null
pr: 21
outcome: 'Shipped 0.3.0 — pydantic moves to an extra'
---

# Spec: pydantic as an optional extra (0.3.0)

**Date:** 2026-06-04
**Topic slug:** `pydantic-optional-extra`
**Status:** drafted, awaiting user review
**Target release:** 0.3.0 (breaking)

## Purpose

Make `pydantic` an opt-in extra, the way `msgspec` already is. Today `pydantic` is in `[project] dependencies`, imported unconditionally by `decoders/pydantic.py:5` and by `client.py:10`, and re-exported by `httpware/__init__.py:5`. This contradicts `planning/engineering.md` §1 ("Pydantic and msgspec ship as extras") and §3 Seam C ("each optional dependency is imported only inside its own dedicated module"). The 0.3.0 release brings the implementation in line with the documented seam.

Bundled into the same release: empty/malformed payload-edge tests for `PydanticDecoder`, currently listed as a deferred-work item.

This is the "Item A + Item D" bundle decided in the conversation that produced `planning/specs/2026-06-04-v0.2-retro-and-housekeeping-design.md`. Items B (pin `ruff`/`ty`) and C (carve out a `[test]` extra) are explicitly out of scope and have been removed from `deferred-work.md`.

## Non-goals

- No middleware changes; Epic 3 (resilience) is a later release.
- No streaming changes.
- No observability changes.
- No CI install-strategy change (`just install` keeps `--all-extras`).
- No `_get_adapter` per-instance scoping — stays open in `deferred-work.md`.

## Design decisions

These were locked in during brainstorming; recorded here so future contributors know the *why*:

- **Fail-fast at `AsyncClient.__init__`** when `decoder=None` and pydantic is not installed. Even callers who never use `response_model=` get the error immediately rather than at the first decoder use. Rationale: the error message is more useful at construction time, and the default-decoder model makes pydantic part of the implicit contract — making that explicit at `__init__` avoids surprise late-in-process failures.
- **Drop the `httpware.PydanticDecoder` re-export.** Consumers move to `from httpware.decoders.pydantic import PydanticDecoder`, which mirrors how `MsgspecDecoder` is already accessed. Breaking change for callers using the short import.
- **Full README freshness pass.** README still says "0.1.0 alpha" and mentions `RecordedTransport`; both are wrong post-pivot. The 0.3.0 install-instructions update is the natural moment to fix the broader staleness rather than leaving it for a separate doc PR.

## Deliverable 1 — `pyproject.toml`

### 1.1 Move pydantic to optional-dependencies

Current:

```toml
dependencies = [
    "httpx2>=2.0.0,<3.0",
    "pydantic>=2.0,<3.0",
]

[project.optional-dependencies]
msgspec = ["msgspec>=0.18"]
otel = [
    "opentelemetry-api>=1.20",
    "opentelemetry-sdk>=1.20",
]
all = ["httpware[msgspec,otel]"]
```

Target:

```toml
dependencies = [
    "httpx2>=2.0.0,<3.0",
]

[project.optional-dependencies]
pydantic = ["pydantic>=2.0,<3.0"]
msgspec = ["msgspec>=0.18"]
otel = [
    "opentelemetry-api>=1.20",
    "opentelemetry-sdk>=1.20",
]
all = ["httpware[pydantic,msgspec,otel]"]
```

### 1.2 Version bump

`version = "0.2.0"` → `version = "0.3.0"`.

## Deliverable 2 — `_internal/import_checker.py`

Add a `is_pydantic_installed` flag mirroring `is_msgspec_installed`:

```python
"""Detect optional extras without importing them. Used by adapter modules to gate hard imports."""

from importlib.util import find_spec


is_msgspec_installed = find_spec("msgspec") is not None
is_pydantic_installed = find_spec("pydantic") is not None
```

## Deliverable 3 — `decoders/pydantic.py`

### 3.1 Guard the pydantic import

Current top-level `from pydantic import TypeAdapter` becomes guarded the same way `decoders/msgspec.py` guards its import. The `_get_adapter` function and `PydanticDecoder` class remain defined at module load so the module is importable even without the extra; `PydanticDecoder.__init__` raises `ImportError` with the install hint when the extra is missing.

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

### 3.2 Notes on the implementation

- `TypeAdapter` is referenced in `_get_adapter` and in the `TypeError`-fallback path inside `decode`. Both code paths are only reachable after `PydanticDecoder.__init__` succeeds, which only succeeds if pydantic is installed. So the lazy `TypeAdapter` reference is safe at runtime.
- The string annotation `"TypeAdapter[T]"` on `_get_adapter`'s return type avoids a `NameError` at import when pydantic is absent (the symbol exists at runtime in that case as part of the `if` block; the string keeps `ty` happy when it isn't).
- The `MISSING_DEPENDENCY_MESSAGE` constant is module-level UPPER_CASE per house style.

## Deliverable 4 — `client.py`

### 4.1 Remove the top-level PydanticDecoder import

`client.py:10` currently does `from httpware.decoders.pydantic import PydanticDecoder`. This import is part of the always-installed surface. It must be removed; the default-decoder construction moves to a lazy path.

### 4.2 Fail-fast lazy default decoder

`client.py:88` currently does:

```python
self._decoder = decoder if decoder is not None else PydanticDecoder()
```

Becomes:

```python
self._decoder = decoder if decoder is not None else _default_pydantic_decoder()
```

Where `_default_pydantic_decoder` is a module-level helper in `client.py`:

```python
from httpware._internal import import_checker


_DEFAULT_DECODER_MISSING_MESSAGE = (
    "AsyncClient(decoder=None) defaults to PydanticDecoder, which requires the "
    "'pydantic' extra. Either install it (`pip install httpware[pydantic]`) or "
    "pass an explicit decoder=..."
)


def _default_pydantic_decoder() -> ResponseDecoder:
    if not import_checker.is_pydantic_installed:
        raise ImportError(_DEFAULT_DECODER_MISSING_MESSAGE)
    from httpware.decoders.pydantic import PydanticDecoder
    return PydanticDecoder()
```

The `from httpware.decoders.pydantic import PydanticDecoder` line is local to the helper. It only fires when the default is needed; if a caller passes `decoder=MsgspecDecoder()`, no pydantic code is touched.

### 4.3 Why a separate message constant?

The error a caller sees depends on where they hit the missing-pydantic case:

- `AsyncClient(decoder=None)` with pydantic missing → `_DEFAULT_DECODER_MISSING_MESSAGE` (mentions both install paths and the `decoder=` escape hatch).
- `PydanticDecoder()` called directly with pydantic missing → `MISSING_DEPENDENCY_MESSAGE` (mentions the install only).

Two messages, two precise diagnoses. Both originate from `ImportError`, so consumers can catch one type.

## Deliverable 5 — `httpware/__init__.py`

### 5.1 Drop the PydanticDecoder re-export

Remove line 5 (`from httpware.decoders.pydantic import PydanticDecoder`) and the `"PydanticDecoder"` entry in `__all__` (line 39). The public top-level surface no longer includes `PydanticDecoder`.

### 5.2 Resulting consumer pattern

```python
# 0.2.0
from httpware import AsyncClient, PydanticDecoder

# 0.3.0
from httpware import AsyncClient
from httpware.decoders.pydantic import PydanticDecoder  # only if you need to construct it directly
```

The release notes call this out explicitly.

## Deliverable 6 — Tests

### 6.1 Update existing tests

- **`tests/test_decoders_pydantic.py:11`** — currently `from httpware import PydanticDecoder, ResponseDecoder`. Split into `from httpware import ResponseDecoder` and `from httpware.decoders.pydantic import PydanticDecoder`. All 16 test bodies stay as-is — the decoder is fully importable in the test env because `--all-extras` installs pydantic.
- **`tests/test_public_api.py:34`** — drop `"PydanticDecoder"` from the `expected` set in `test_expected_exports`. Add `"PydanticDecoder"` to the `removed` set in `test_no_removed_symbols_leaked` so top-level leakage is actively guarded against.
- **`tests/test_client_construction.py`** — line 7 already uses the submodule import (`from httpware.decoders.pydantic import PydanticDecoder`); line 53 asserts `isinstance(client._decoder, PydanticDecoder)` after constructing `AsyncClient()` with no `decoder=`. This continues to work because pydantic is installed in the test env. No change.
- **`tests/conftest.py`** — confirmed empty; nothing to change.

### 6.2 New: pydantic-isolation subprocess test

Extend `tests/test_optional_extras_isolation.py` with a pydantic case:

```python
def test_importing_httpware_does_not_import_pydantic() -> None:
    """Fresh subprocess: pydantic must NOT appear in sys.modules after `import httpware`."""
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

This is the regression test for the whole exercise: after the changes, `import httpware` must not transitively pull pydantic.

### 6.3 New: fail-fast tests

A new test file or a new section in an existing file (`tests/test_optional_extras_pydantic_missing.py`) covering the `decoder=None` fail-fast paths. Pydantic IS installed in the test env, so simulate "missing" by patching `httpware._internal.import_checker.is_pydantic_installed = False`:

```python
from unittest.mock import patch
import pytest

from httpware import AsyncClient
from httpware.decoders.pydantic import PydanticDecoder


def test_async_client_default_decoder_raises_when_pydantic_missing() -> None:
    with patch("httpware._internal.import_checker.is_pydantic_installed", False):
        with pytest.raises(ImportError, match="httpware\\[pydantic\\]"):
            AsyncClient()


def test_pydantic_decoder_init_raises_when_pydantic_missing() -> None:
    with patch("httpware._internal.import_checker.is_pydantic_installed", False):
        with pytest.raises(ImportError, match="httpware\\[pydantic\\]"):
            PydanticDecoder()


def test_async_client_accepts_explicit_decoder_without_pydantic() -> None:
    """When pydantic is 'missing' but the caller passes an explicit decoder, no error."""

    class FakeDecoder:
        def decode(self, content: bytes, model: type) -> object:
            return model()

    with patch("httpware._internal.import_checker.is_pydantic_installed", False):
        client = AsyncClient(decoder=FakeDecoder())
        assert client is not None
```

The third test pins the contract: passing an explicit decoder escapes the fail-fast.

### 6.4 New: malformed-payload tests for PydanticDecoder (Item D)

Add to `tests/test_decoders_pydantic.py`:

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
        (b"\xff\xfe\x00\x00", User),  # invalid UTF-8
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

Rationale lives in the test docstring: this test exists to detect *behavior change in a transitive dependency*, not to verify a httpware invariant.

## Deliverable 7 — Docs

### 7.1 `README.md` — full freshness pass

Replace the current top blurb and status note:

- **Top blurb (line 10):** drop the line that says `RecordedTransport replaces respx` (removed in v0.2). Replace with a concise post-pivot framing: `httpware` is a thin opinionated wrapper around `httpx2` with a middleware chain, opt-in typed decoding (pydantic / msgspec), and a status-keyed exception tree raised automatically on 4xx/5xx.
- **Status note (line 12):** update from "0.1.0 alpha" to "0.3.0 — pre-1.0; public API subject to change between minor releases until v1.0. Resilience middleware, streaming, and observability are not yet shipped." (Removes the false 0.1.0 mention.)
- **Install section:** add the `pydantic` extra and rewrite the prose:

  ```bash
  pip install httpware                           # core (no decoder)
  pip install httpware[pydantic]                 # + PydanticDecoder (recommended)
  pip install httpware[msgspec]                  # + MsgspecDecoder
  pip install httpware[all]                      # everything declared above
  ```
  
  Note that `AsyncClient()` with no `decoder=` argument defaults to `PydanticDecoder()` and requires the `pydantic` extra.
- **Quickstart:** keep the pydantic example but prepend a one-line note: `# Requires: pip install httpware[pydantic]`.
- **`otel`, `niquests`, and `all` extras** parenthetical: rewrite to drop `niquests` (not actually declared in pyproject.toml as of v0.2) and mention `otel` as "declared but Epic 5 not yet shipped". The current parenthetical is misleading.

### 7.2 `planning/engineering.md` §1 — Project intent

Current §1 says: "Pydantic ships as the default, msgspec as an opt-in extra." Update to: "Both pydantic and msgspec ship as opt-in extras. The 0.3.0 release made pydantic optional; before that it was a hard dependency. `AsyncClient(decoder=None)` defaults to constructing a `PydanticDecoder` and so requires the `pydantic` extra; callers can supply an explicit `decoder=` argument to escape the default."

### 7.3 `planning/engineering.md` §7 — Optional-extras pattern

The §7 example code block currently shows pydantic in optional-dependencies. Now it is accurate; no change needed beyond an addition to the prose: confirm that the "single dedicated module per extra" rule now applies to pydantic too (file: `decoders/pydantic.py`).

### 7.4 `planning/engineering.md` §3 Seam C

The Seam C rule ("each optional dependency is imported only inside its own dedicated module") becomes uniformly true with this PR. Add a short line: "Verified by `tests/test_optional_extras_isolation.py`, which subprocess-tests that `import httpware` does not transitively load any extra."

## Deliverable 8 — Release notes

Create `planning/releases/0.3.0.md`:

```markdown
# httpware 0.3.0 — pydantic as an optional extra

## Breaking changes

- **`pydantic` is no longer a required dependency.** It moved from `[project] dependencies` to `[project.optional-dependencies]`. Install it explicitly: `pip install httpware[pydantic]`. The `httpware[all]` extra continues to include it.
- **`httpware.PydanticDecoder` is no longer re-exported from the top-level package.** Import directly from the submodule: `from httpware.decoders.pydantic import PydanticDecoder`. This mirrors the existing `MsgspecDecoder` import path.
- **`AsyncClient()` with `decoder=None` and no pydantic extra raises `ImportError` at `__init__`.** Pass `decoder=MsgspecDecoder()` or install `httpware[pydantic]` to keep the default behavior.

## Other changes

- New `tests/test_decoders_pydantic.py` payload-edge tests pin current pydantic-core behavior for `b""`, `b"null"`, `b"{}"`, malformed JSON, and invalid UTF-8.
- `tests/test_optional_extras_isolation.py` now covers both pydantic and msgspec.
- README freshness pass: status line and post-pivot framing corrected.

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

## Deliverable 9 — `planning/deferred-work.md` updates after merge

After this PR ships, move the two "in progress for 0.3.0" items into the "Closed" section. Add a new closed-section entry naming the PR.

## Acceptance criteria

- `pyproject.toml` lists `pydantic` only under `[project.optional-dependencies]`, version is `0.3.0`, and `all` extra includes `pydantic`.
- `_internal/import_checker.py` exports both `is_pydantic_installed` and `is_msgspec_installed`.
- `decoders/pydantic.py` imports pydantic only inside an `if import_checker.is_pydantic_installed:` block; `PydanticDecoder.__init__` raises `ImportError` with `httpware[pydantic]` in the message when the extra is missing.
- `client.py` does not import `PydanticDecoder` at module top; `AsyncClient.__init__` raises `ImportError` immediately when `decoder=None` and pydantic is not installed.
- `httpware/__init__.py` does not export `PydanticDecoder`; `__all__` does not contain it.
- `tests/test_optional_extras_isolation.py` includes a passing pydantic case (subprocess-tested).
- `tests/test_optional_extras_pydantic_missing.py` (or equivalent) exists with 3 fail-fast tests, all passing.
- `tests/test_decoders_pydantic.py` includes 7 new parametrized malformed-payload tests, all passing.
- `README.md` install section shows `httpware[pydantic]`; status line says 0.3.0; `RecordedTransport` reference is gone.
- `planning/engineering.md` §1, §3 Seam C, §7 reflect pydantic-as-extra.
- `planning/releases/0.3.0.md` exists.
- `just lint` and `just test` pass.
- `grep -rE '^from pydantic|^import pydantic' src/httpware/` returns exactly one line (the guarded import in `decoders/pydantic.py`).

## Execution order (one PR)

1. `feat(extras): move pydantic to optional-dependencies + version bump`
   — `pyproject.toml` changes.
2. `feat(extras): add is_pydantic_installed; guard PydanticDecoder import`
   — `_internal/import_checker.py`, `decoders/pydantic.py`.
3. `feat(client): lazy default decoder with fail-fast at __init__`
   — `client.py`.
4. `feat(api): drop top-level PydanticDecoder re-export`
   — `httpware/__init__.py`.
5. `test: pydantic-isolation subprocess + fail-fast + malformed-payload tests`
   — three test files.
6. `docs: README freshness pass + engineering.md §1/§3/§7 updates`
   — `README.md`, `planning/engineering.md`.
7. `chore(release): draft 0.3.0 release notes`
   — `planning/releases/0.3.0.md`.

All on one feature branch. Suggested branch name: `feat/v0.3-pydantic-optional`.

## Out of scope (recorded for clarity)

- Pinning `ruff`/`ty` major versions. Removed from `deferred-work.md` by the housekeeping bundle.
- Carving out a `[test]` extra. Removed from `deferred-work.md` by the housekeeping bundle.
- `_get_adapter` per-instance scoping. Stays open; no configurable `PydanticDecoder` yet.
- Any Epic 3 / 4 / 5 / 6 work.

## Risk and mitigation

- **CI install needs updating to include `pydantic` extra.** `just install` runs `uv sync --all-extras --group lint`; that pulls pydantic via the `pydantic` extra. So no Justfile change is required as long as the CI continues to use `--all-extras`. Verify by running `just install && just test` locally before pushing.
- **Consumers of the published `0.2.0`** doing `from httpware import PydanticDecoder` will break at import time on upgrade. The 0.3.0 release notes spell out the two migration options. No deprecation cycle (0.x — breaking changes are allowed).
- **Type-checker behavior on the `"TypeAdapter[T]"` string annotation.** `ty` should accept the forward reference. If it does not, a `typing.TYPE_CHECKING`-gated `from pydantic import TypeAdapter` block in `decoders/pydantic.py` is the fallback. (Avoid this if possible per the user's typing-import style memory: don't reach for `if TYPE_CHECKING` reflexively.)

---
status: shipped
date: 2026-06-10
slug: decoder-instance-cache
spec: decoder-instance-cache
pr: 42
---

# Per-Instance Decoder Cache Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace module-level `@functools.lru_cache` on `_get_adapter` (pydantic) and `_get_msgspec_decoder` (msgspec) with per-instance `dict[type, ...]` caches owned by each decoder. No public API change; tied to decoder/client lifecycle.

**Architecture:** Each built-in decoder gains a private dict attribute (`_adapters` on `PydanticDecoder`; `_msgspec_decoders` on `MsgspecDecoder`) populated lazily on first `_get_adapter()` / `_get_msgspec_decoder()` call. `decode()` and `can_decode()` route through the new instance methods. The TypeError fallback in `decode()` is preserved. Autouse cache-clear fixtures in both test files are deleted — each test that needs a fresh cache constructs a fresh decoder.

**Tech Stack:** Python 3.11+, pydantic 2.x (optional extra), msgspec (optional extra), `pytest` + `pytest-asyncio` auto mode, `ty` for type checking, `ruff` for lint, `just` task runner.

---

## Spec reference

The validated spec is at `planning/specs/2026-06-10-decoder-instance-cache-design.md`. Read it for the architecture rationale and the test-migration table.

Decisions locked there and not re-debated here:

- Attribute names: `_adapters` on `PydanticDecoder`; `_msgspec_decoders` on `MsgspecDecoder` (avoiding visual collision with `client._decoders`).
- `can_decode` preserves the `msgspec.inspect.type_info` + `CustomType` filter for `MsgspecDecoder` (orthogonal to cache mechanics; do not touch).
- `decode` keeps the `try/except TypeError → uncached construction` fallback for unhashable models.
- Module-level `_get_adapter` / `_get_msgspec_decoder` functions and the `import functools` line are deleted from both modules.
- Test-migration pattern: spy on `pydantic.TypeAdapter` / `msgspec.json.Decoder` (the underlying constructors) — works identically before/after; the spy target is the imported symbol, not the deleted module-level factory.
- 100% line coverage gate stays in force.
- Folded into 0.9.0 (not yet tagged); no release notes line; commit message `refactor(decoders): ...`.

## Sequencing rationale

Two atomic refactors. Each touches one decoder module + its test file. The two decoders are independent — pydantic and msgspec changes can land in either order, but each task must land as one commit (deletion of the module-level factory + introduction of the instance method + test migrations are bound together by the 100% coverage gate).

After each task: run `just lint && just test`. The suite must be green at 100% coverage before commit.

---

## Task 1: `PydanticDecoder` per-instance cache

**Files:**
- Modify: `src/httpware/decoders/pydantic.py`
- Modify: `tests/test_decoders_pydantic.py`

Move `_get_adapter` from a module-level `@functools.lru_cache`-decorated function into a private instance method on `PydanticDecoder`, backed by a per-instance `dict[type, TypeAdapter[typing.Any]]`. Migrate the test file: drop the autouse cache-clear fixture; update the patch target on the unhashable-model fallback test; switch the `can_decode_uses_cache` assertion from `_get_adapter.cache_info()` to `len(decoder._adapters) == 1`. The four `test_cache_invariance_*` tests stay nearly identical — drop the `_get_adapter.cache_clear()` line each, leave everything else unchanged (the spy on `pydantic.TypeAdapter` still pins the construction-once invariant).

- [ ] **Step 1: Write the migrated tests (with the autouse fixture deleted)**

Rewrite `tests/test_decoders_pydantic.py` imports — remove `_get_adapter` from the existing `from httpware.decoders.pydantic import PydanticDecoder, _get_adapter` line. The result:

```python
from httpware.decoders.pydantic import PydanticDecoder
```

Delete the autouse fixture (currently around lines 30-33):

```python
@pytest.fixture(autouse=True)
def _clear_adapter_cache() -> None:
    _get_adapter.cache_clear()
```

The four `test_cache_invariance_*` tests: drop their leading `_get_adapter.cache_clear()` lines (each test currently calls this explicitly even though the autouse fixture also does it). End-state body for the first:

```python
def test_cache_invariance_single_model() -> None:
    with patch("httpware.decoders.pydantic.TypeAdapter", wraps=pydantic.TypeAdapter) as spy:
        decoder = PydanticDecoder()
        for _ in range(1000):
            decoder.decode(b'{"id": 1, "name": "Ada"}', User)
        assert spy.call_count == 1
```

`test_cache_invariance_two_distinct_models` — drop the leading `_get_adapter.cache_clear()`:

```python
def test_cache_invariance_two_distinct_models() -> None:
    with patch("httpware.decoders.pydantic.TypeAdapter", wraps=pydantic.TypeAdapter) as spy:
        decoder = PydanticDecoder()
        for _ in range(500):
            decoder.decode(b'{"id": 1, "name": "Ada"}', User)
            decoder.decode(b'{"id": 1, "name": "Ada"}', UserDC)
        assert spy.call_count == 2  # noqa: PLR2004 — two distinct model types
```

`test_cache_invariance_concurrent_first_calls`:

```python
async def test_cache_invariance_concurrent_first_calls() -> None:
    with patch("httpware.decoders.pydantic.TypeAdapter", wraps=pydantic.TypeAdapter) as spy:
        decoder = PydanticDecoder()

        async def one_decode() -> User:
            return decoder.decode(b'{"id": 1, "name": "Ada"}', User)

        await asyncio.gather(*(one_decode() for _ in range(50)))
        assert spy.call_count == 1
```

`test_cache_invariance_concurrent_first_calls_threadpool`:

```python
def test_cache_invariance_concurrent_first_calls_threadpool() -> None:
    n_workers = 20
    with patch("httpware.decoders.pydantic.TypeAdapter", wraps=pydantic.TypeAdapter) as spy:
        decoder = PydanticDecoder()

        def one_decode(_: int) -> User:
            return decoder.decode(b'{"id": 1, "name": "Ada"}', User)

        with concurrent.futures.ThreadPoolExecutor(max_workers=n_workers) as pool:
            results = list(pool.map(one_decode, range(50)))

        assert all(type(r) is User and r.id == 1 for r in results)
        # `dict` reads/writes are atomic in CPython but the get→set sequence in
        # `_get_adapter` is not — concurrent first-callers may both build a
        # TypeAdapter before one wins (idempotent; loser is GC'd). Bounded by
        # worker count.
        assert 1 <= spy.call_count <= n_workers
```

`test_unhashable_model_falls_back_to_uncached_adapter` — patch target moves from the module-level `_get_adapter` function to the now-method `PydanticDecoder._get_adapter`:

```python
def test_unhashable_model_falls_back_to_uncached_adapter() -> None:
    """Unhashable `model` falls back to a direct uncached `TypeAdapter`.

    When `_get_adapter` raises `TypeError` (e.g., `Annotated[int, unhashable_metadata]`),
    `decode` bypasses the cache so `pydantic.ValidationError` surfaces cleanly instead
    of leaking a `TypeError` to the caller.
    """
    with patch.object(
        PydanticDecoder,
        "_get_adapter",
        side_effect=TypeError("unhashable type"),
    ):
        result = PydanticDecoder().decode(b"42", int)
        assert result == 42  # noqa: PLR2004

        with pytest.raises(pydantic.ValidationError):
            PydanticDecoder().decode(b'"not-an-int"', int)
```

`test_pydantic_can_decode_uses_cache` (added in PR #41 Task 1) — assertion shifts from `_get_adapter.cache_info()` to introspecting the instance dict:

```python
def test_pydantic_can_decode_uses_cache() -> None:
    decoder = PydanticDecoder()
    decoder.can_decode(User)
    decoder.can_decode(User)
    assert len(decoder._adapters) == 1  # noqa: SLF001
    assert User in decoder._adapters  # noqa: SLF001
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_decoders_pydantic.py -v
```
Expected: failures referencing `_get_adapter` being missing as a module attribute, or `decoder._adapters` not existing.

- [ ] **Step 3: Refactor `PydanticDecoder`**

Rewrite `src/httpware/decoders/pydantic.py`:

```python
"""PydanticDecoder — ResponseDecoder backed by per-instance TypeAdapter cache.

Requires the `pydantic` extra: `pip install httpware[pydantic]`. Constructing
`PydanticDecoder()` directly when pydantic is not installed raises ImportError.
The default-decoder path in `client.py:_build_default_decoders()` skips this
class entirely when `is_pydantic_installed` is False, so `AsyncClient()` does
not trip the ImportError when the user is not using `response_model=`.
"""

import typing
from typing import TypeVar

from pydantic import TypeAdapter

from httpware._internal import import_checker


MISSING_DEPENDENCY_MESSAGE = (
    "PydanticDecoder requires the 'pydantic' extra. Install with: pip install httpware[pydantic]"
)

T = TypeVar("T")


class PydanticDecoder:
    """Decode raw response bytes into `model` via a per-instance cached `pydantic.TypeAdapter`."""

    _adapters: dict[type, TypeAdapter[typing.Any]]

    def __init__(self) -> None:
        if not import_checker.is_pydantic_installed:
            raise ImportError(MISSING_DEPENDENCY_MESSAGE)
        self._adapters = {}

    def _get_adapter(self, model: type[T]) -> TypeAdapter[T]:
        adapter = self._adapters.get(model)
        if adapter is None:
            adapter = TypeAdapter(model)
            self._adapters[model] = adapter
        return adapter

    def can_decode(self, model: type) -> bool:
        """True iff pydantic can build a schema for `model`.

        Probes via `_get_adapter`; subsequent calls (including `decode`) reuse
        the cached `TypeAdapter`. Rejects `msgspec.Struct` subclasses —
        pydantic raises `PydanticSchemaGenerationError` (a `TypeError`) when
        building a schema for them.
        """
        try:
            self._get_adapter(model)
        except Exception:  # noqa: BLE001 — can_decode is a probe; any failure means no
            return False
        return True

    def decode(self, content: bytes, model: type[T]) -> T:
        """Validate `content` as JSON against `model` in a single parse pass."""
        try:
            adapter = self._get_adapter(model)
        except TypeError:
            adapter = TypeAdapter(model)
        return adapter.validate_json(content)
```

Removals from the pre-refactor file: `import functools`, module-level `_get_adapter` function, its `@functools.lru_cache(maxsize=1024)` decorator.

The `# ty: ignore` patterns and the docstrings inside `decode` / `can_decode` are preserved verbatim from the pre-refactor version.

- [ ] **Step 4: Run the targeted test file**

```bash
uv run pytest tests/test_decoders_pydantic.py -v
```
Expected: all green.

- [ ] **Step 5: Run lint and full test suite**

```bash
just lint && just test
```
Expected: green; 100% coverage maintained.

If coverage drops below 100%, the most likely cause is the `except Exception` branch in `can_decode` or the `except TypeError` branch in `decode` not being exercised. Verify:
- `test_pydantic_rejects_msgspec_struct` exercises the `can_decode` failure branch.
- `test_unhashable_model_falls_back_to_uncached_adapter` exercises the `decode` failure branch.

- [ ] **Step 6: Commit**

```bash
git add src/httpware/decoders/pydantic.py tests/test_decoders_pydantic.py
git commit -m "refactor(decoders): PydanticDecoder uses per-instance adapter cache"
```

---

## Task 2: `MsgspecDecoder` per-instance cache

**Files:**
- Modify: `src/httpware/decoders/msgspec.py`
- Modify: `tests/test_decoders_msgspec.py`

Mirror of Task 1 for `MsgspecDecoder`. Drop the autouse `_clear_msgspec_cache` fixture; update tests that touched `_get_msgspec_decoder` directly; preserve the `msgspec.inspect.type_info` + `CustomType` filter in `can_decode` (orthogonal to cache mechanics).

- [ ] **Step 1: Write the migrated tests**

Edit `tests/test_decoders_msgspec.py`. Remove `_get_msgspec_decoder` from the existing `from httpware.decoders.msgspec import ...` line. The end-state import block keeps only `MsgspecDecoder`:

```python
from httpware.decoders.msgspec import MsgspecDecoder
```

Delete the autouse fixture (currently after the model definitions):

```python
@pytest.fixture(autouse=True)
def _clear_msgspec_cache() -> None:
    _get_msgspec_decoder.cache_clear()
```

`test_msgspec_can_decode_uses_cache` — assertion shifts to introspecting the instance dict:

```python
def test_msgspec_can_decode_uses_cache() -> None:
    decoder = MsgspecDecoder()
    decoder.can_decode(_Item)
    decoder.can_decode(_Item)
    assert len(decoder._msgspec_decoders) == 1  # noqa: SLF001
    assert _Item in decoder._msgspec_decoders  # noqa: SLF001
```

If there are any additional tests that import / patch / call `_get_msgspec_decoder` directly, migrate them to `patch.object(MsgspecDecoder, "_get_msgspec_decoder", ...)`. Search:

```bash
grep -n "_get_msgspec_decoder\|_clear_msgspec_cache" tests/test_decoders_msgspec.py
```

If a test patches the module-level function and the patch target is `httpware.decoders.msgspec._get_msgspec_decoder`, change it to `patch.object(MsgspecDecoder, "_get_msgspec_decoder", ...)`. If a test only references the symbol for `cache_clear()`, remove the line — the per-instance dict starts empty for a freshly constructed decoder.

Add an unhashable-fallback test mirroring the pydantic one (the msgspec module didn't have an explicit one pre-refactor, but the `try/except TypeError` branch in `decode` needs coverage now that it's an instance method):

```python
def test_unhashable_model_falls_back_to_uncached_decoder() -> None:
    """Unhashable `model` falls back to a direct uncached `msgspec.json.Decoder`.

    When `_get_msgspec_decoder` raises `TypeError`, `decode` bypasses the cache
    so msgspec's own error surfaces cleanly.
    """
    with patch.object(
        MsgspecDecoder,
        "_get_msgspec_decoder",
        side_effect=TypeError("unhashable type"),
    ):
        result = MsgspecDecoder().decode(b"42", int)
        assert result == 42  # noqa: PLR2004
```

This is the msgspec analog of `test_unhashable_model_falls_back_to_uncached_adapter`. The same coverage discipline applies — without it, the `except TypeError` branch in `decode()` goes uncovered after the refactor.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_decoders_msgspec.py -v
```
Expected: failures referencing `_get_msgspec_decoder` being missing as a module attribute, or `decoder._msgspec_decoders` not existing.

- [ ] **Step 3: Refactor `MsgspecDecoder`**

Rewrite `src/httpware/decoders/msgspec.py`:

```python
"""MsgspecDecoder — opt-in ResponseDecoder backed by a per-instance msgspec.json.Decoder cache."""

import typing
from typing import TypeVar

from httpware._internal import import_checker


if import_checker.is_msgspec_installed:
    import msgspec


MISSING_DEPENDENCY_MESSAGE = "MsgspecDecoder requires the 'msgspec' extra. Install with: pip install httpware[msgspec]"

T = TypeVar("T")


class MsgspecDecoder:
    """Decode raw response bytes via a per-instance cached `msgspec.json.Decoder(model)`.

    Requires the `msgspec` extra: `pip install httpware[msgspec]`. Importing
    this module without the extra works (the `msgspec` import is guarded by a
    `find_spec` check), but instantiating the decoder raises `ImportError`.
    """

    _msgspec_decoders: dict[type, "msgspec.json.Decoder[typing.Any]"]

    def __init__(self) -> None:
        if not import_checker.is_msgspec_installed:
            raise ImportError(MISSING_DEPENDENCY_MESSAGE)
        self._msgspec_decoders = {}

    def _get_msgspec_decoder(self, model: type[T]) -> "msgspec.json.Decoder[T]":
        decoder = self._msgspec_decoders.get(model)
        if decoder is None:
            decoder = msgspec.json.Decoder(model)
            self._msgspec_decoders[model] = decoder
        return decoder

    def can_decode(self, model: type) -> bool:
        """True iff msgspec natively understands `model`.

        msgspec builds a Decoder for almost any class via a generic CustomType
        fallback; the Decoder constructor itself does NOT raise on unsupported
        types (e.g. pydantic.BaseModel). We use msgspec.inspect.type_info
        to detect the fallback and reject CustomType results explicitly.
        """
        try:
            info = msgspec.inspect.type_info(model)
        except Exception:  # noqa: BLE001 — can_decode is a probe; any failure means no
            return False
        if isinstance(info, msgspec.inspect.CustomType):
            return False
        try:
            self._get_msgspec_decoder(model)
        except Exception:  # noqa: BLE001 — can_decode is a probe; any failure means no
            return False
        return True

    def decode(self, content: bytes, model: type[T]) -> T:
        """Validate `content` as JSON against `model` in a single parse pass."""
        try:
            decoder = self._get_msgspec_decoder(model)
        except TypeError:
            decoder = msgspec.json.Decoder(model)
        return decoder.decode(content)
```

Removals from the pre-refactor file: `import functools`, module-level `_get_msgspec_decoder` function, its `@functools.lru_cache(maxsize=1024)` decorator.

The `msgspec.inspect.type_info` + `CustomType` filter is preserved verbatim — do not touch it. The `# noqa: BLE001` annotations on the two probe `except Exception` blocks remain.

If the pre-refactor `can_decode` has additional `except` branches inherited from the multi-decoder PR (e.g., `except (TypeError, msgspec.ValidationError)`), keep them as-is — they're orthogonal to the cache refactor. The spec is firm on this: don't touch `can_decode`'s body beyond the `_get_msgspec_decoder` call site.

- [ ] **Step 4: Run the targeted test file**

```bash
uv run pytest tests/test_decoders_msgspec.py -v
```
Expected: all green.

- [ ] **Step 5: Run lint and full test suite**

```bash
just lint && just test
```
Expected: green; 100% coverage maintained.

If coverage drops below 100%, check:
- `test_msgspec_rejects_pydantic_basemodel` exercises the `CustomType` rejection branch.
- The new `test_unhashable_model_falls_back_to_uncached_decoder` exercises the `decode` `except TypeError` branch.
- If the `_get_msgspec_decoder` raise branch in `can_decode` isn't covered, add a test that patches `MsgspecDecoder._get_msgspec_decoder` to raise and asserts `can_decode` returns False:

```python
def test_msgspec_can_decode_returns_false_when_decoder_build_raises() -> None:
    with patch.object(
        MsgspecDecoder,
        "_get_msgspec_decoder",
        side_effect=TypeError("can't build"),
    ):
        assert MsgspecDecoder().can_decode(_Item) is False
```

(If a test with this shape already exists from PR #41, you don't need to add it.)

- [ ] **Step 6: Commit**

```bash
git add src/httpware/decoders/msgspec.py tests/test_decoders_msgspec.py
git commit -m "refactor(decoders): MsgspecDecoder uses per-instance decoder cache"
```

---

## Task 3: Update `planning/engineering.md` Seam B description

**Files:**
- Modify: `planning/engineering.md`

The Seam B section (updated in PR #41 Task 9) describes the cache mechanism as "memoized via `@functools.lru_cache(maxsize=1024)` on a module-level `_get_adapter(model)` factory." After Tasks 1 and 2 land, that's stale. Update it to reflect the per-instance shape.

- [ ] **Step 1: Locate the stale description**

```bash
grep -n "lru_cache\|_get_adapter\|_get_msgspec_decoder" planning/engineering.md
```

Expected: one hit, in the Seam B section's "Rule" line (around line 44).

- [ ] **Step 2: Replace the stale rule line**

Find this paragraph in `planning/engineering.md` (Seam B section, "Rule:" bullet):

```markdown
- **Rule:** the decoder must operate on raw bytes in a single parse pass. Two-pass decoding (`json.loads` then `validate_python`) is rejected: a single bytes-in / typed-object-out pass avoids the redundant intermediate `dict` allocation and parses faster. The Pydantic adapter implements this as `TypeAdapter(model).validate_json(content)`, with the `TypeAdapter` itself memoized via `@functools.lru_cache(maxsize=1024)` on a module-level `_get_adapter(model)` factory; the msgspec adapter mirrors the pattern with a cached `msgspec.json.Decoder(model)`.
```

Replace with:

```markdown
- **Rule:** the decoder must operate on raw bytes in a single parse pass. Two-pass decoding (`json.loads` then `validate_python`) is rejected: a single bytes-in / typed-object-out pass avoids the redundant intermediate `dict` allocation and parses faster. The Pydantic adapter implements this as `TypeAdapter(model).validate_json(content)`, with the `TypeAdapter` cached per-instance on `PydanticDecoder._adapters: dict[type, TypeAdapter]` (populated lazily on first `_get_adapter()` call); the msgspec adapter mirrors the pattern with `MsgspecDecoder._msgspec_decoders: dict[type, msgspec.json.Decoder]`. Cache lifetime matches the decoder/client, not the process — no module-level state, no autouse cache-clear fixtures in tests.
```

- [ ] **Step 3: Run lint and full test suite**

```bash
just lint && just test
```
Expected: green (docs-only change; no code path changed).

- [ ] **Step 4: Commit**

```bash
git add planning/engineering.md
git commit -m "docs(planning): update Seam B for per-instance decoder cache"
```

---

## Self-review checklist

After Task 2 lands, verify against the spec:

- [ ] **Spec coverage:**
  - `PydanticDecoder._adapters` instance attribute + `_get_adapter` instance method (Task 1, Step 3).
  - `MsgspecDecoder._msgspec_decoders` instance attribute + `_get_msgspec_decoder` instance method (Task 2, Step 3).
  - Module-level `_get_adapter` / `_get_msgspec_decoder` deleted (Task 1 / Task 2, Step 3).
  - `import functools` deleted from both modules (Task 1 / Task 2, Step 3).
  - `can_decode` preserves the `msgspec.inspect.type_info` + `CustomType` filter (Task 2, Step 3 — explicit instruction to leave it alone).
  - `decode` keeps the TypeError fallback (Task 1 / Task 2, Step 3).
  - Autouse cache-clear fixtures deleted (Task 1 / Task 2, Step 1).
  - All cache-invariance tests migrated (Task 1 / Task 2, Step 1).
  - `can_decode_uses_cache` assertions shifted to instance-dict inspection (Task 1 / Task 2, Step 1).
  - `planning/engineering.md` Seam B description updated to reflect per-instance cache (Task 3).

- [ ] **No placeholders:** `grep -nE 'TBD|TODO|FIXME' planning/plans/2026-06-10-decoder-instance-cache-plan.md`. Expected: zero hits.

- [ ] **Type consistency:** `_adapters` and `_msgspec_decoders` attribute names are used consistently across the two tasks. `_get_adapter` and `_get_msgspec_decoder` are the method names; not renamed mid-plan.

- [ ] **Final suite:** `just lint && just test` green at 100% coverage after both tasks.

- [ ] **No regression in test count:** `tests/test_decoders_pydantic.py` and `tests/test_decoders_msgspec.py` should have the same number of test functions as before (one new test in msgspec to cover the now-instance-method TypeError fallback — see Task 2 Step 1; one removed autouse fixture from each file).

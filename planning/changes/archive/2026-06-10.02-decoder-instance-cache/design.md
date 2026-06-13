---
status: shipped
date: 2026-06-10
slug: decoder-instance-cache
supersedes: null
superseded_by: null
pr: 42
outcome: 'Shipped 0.9.0 — per-instance decoder cache'
---

# Spec: decoder per-instance cache — drop module-level `@lru_cache`

**Date:** 2026-06-10
**Topic slug:** `decoder-instance-cache`
**Status:** drafted, awaiting user review
**Target release:** folded into `0.9.0` (not yet tagged) — public API unchanged; internal refactor only.

## Purpose

Both built-in decoders cache per-model construction via module-level `@functools.lru_cache(maxsize=1024)`:

- `httpware.decoders.pydantic._get_adapter(model) -> TypeAdapter`
- `httpware.decoders.msgspec._get_msgspec_decoder(model) -> msgspec.json.Decoder`

The lifecycle of these caches is *process-wide*, while the natural owner of the cache — the decoder instance — has a much narrower lifetime (one per `AsyncClient` / `Client`). The mismatch shows up in three places:

1. **Test fixture overhead.** Two autouse `cache_clear()` fixtures live in `tests/test_decoders_pydantic.py` and `tests/test_decoders_msgspec.py` to prevent cross-test pollution. The msgspec one was just added in PR #41 (Task 1 review-loop fix) to mirror the pydantic one.
2. **Hidden global state.** `functools.lru_cache` internals are opaque; debugging "why is this adapter sticking around?" is harder than `decoder._adapters` would be.
3. **`maxsize=1024` is a safety net for a problem that doesn't exist here.** Adapter counts are bounded by the number of `response_model=` types a client decodes, which is bounded by the application's surface area. Per-instance dicts grow with the decoder's lifetime and die with it — no bound needed.

This spec replaces both caches with per-instance `dict[type, ...]` attributes on each decoder. No public API change. Hot-path performance is preserved for the common case (one client per process) and slightly regresses for the rare multi-client-shared-models case.

## Non-goals

- **Cross-decoder cache sharing.** Out of scope. An opt-in `cache=` kwarg was considered and rejected (YAGNI — no documented use case).
- **Changing the unhashable-model fallback.** `decode()` keeps the existing `try/except TypeError → uncached TypeAdapter(model)` pattern; dicts raise TypeError on unhashable keys, same as `lru_cache`.
- **`MissingDecoderError`, `_dispatch_decoder`, default-decoder resolution, the `can_decode` contract.** All unchanged.
- **The `msgspec.inspect.type_info` + `CustomType` filter in `MsgspecDecoder.can_decode`.** Stays exactly as-is — the principled deviation documented in `multi_decoder_routing_shipped` memory is orthogonal to cache mechanics.

## Architecture

### `PydanticDecoder` (`src/httpware/decoders/pydantic.py`)

Replace the module-level `_get_adapter` and the `@functools.lru_cache` decorator with a per-instance dict:

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

**Removals:**
- `import functools`
- Module-level `_get_adapter` function and its `@functools.lru_cache(maxsize=1024)` decorator.

**Type annotation:** `_adapters: dict[type, TypeAdapter[typing.Any]]` at class level (mirrors how the client class annotates `_decoders`). The `TypeAdapter[typing.Any]` is necessary because the dict stores adapters for many different `T` types; the per-method `T` narrowing happens through the `_get_adapter` signature.

### `MsgspecDecoder` (`src/httpware/decoders/msgspec.py`)

Same shape:

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

**Removals:**
- `import functools`
- Module-level `_get_msgspec_decoder` function and its `@functools.lru_cache(maxsize=1024)` decorator.

**Attribute name** is `_msgspec_decoders` (not `_decoders`) to avoid visual collision with `AsyncClient._decoders` / `Client._decoders` (which is the decoder *list*, not the per-model cache). Two attributes with the same name doing different things in adjacent files is a recipe for misreading.

### `PydanticDecoder.decode` and `MsgspecDecoder.decode` semantics

Unchanged. The `try/except TypeError` fallback to an uncached construction still covers:

- Unhashable `model` (e.g., `Annotated[int, some_unhashable_metadata]`) — `dict.get(model)` raises `TypeError` for unhashable keys, same as `lru_cache.__call__`.
- Any failure inside the underlying constructor that the user wants to surface via `pydantic.ValidationError` / `msgspec.DecodeError` at the actual decode site, not as a `TypeError` during cache lookup.

## Tests

The 100% coverage gate is in force throughout (`pyproject.toml:93` — `--cov-fail-under=100`).

### Files touched

- `tests/test_decoders_pydantic.py`
- `tests/test_decoders_msgspec.py`

No new test files. No deleted test files (the existing cache-invariance suite adapts mechanically).

### Removals

In `tests/test_decoders_pydantic.py`:
- The autouse fixture `_clear_adapter_cache` (currently at lines 30-33). Gone — each test that needs a fresh cache constructs a fresh `PydanticDecoder()`, which has its own `_adapters` dict.
- The `from httpware.decoders.pydantic import _get_adapter` import. Replaced with `PydanticDecoder` only.

In `tests/test_decoders_msgspec.py`:
- The autouse fixture `_clear_msgspec_cache` (currently after the model definitions).
- The `_get_msgspec_decoder` import. Replaced with `MsgspecDecoder` only.

### Migrations

For each existing cache-invariance test, the pattern shifts from "patch the module-level factory and assert spy count" to "construct a decoder, drive it, inspect `decoder._adapters` length OR patch `TypeAdapter` itself and count spy calls."

Concrete example. The old test:

```python
def test_cache_invariance_single_model() -> None:
    _get_adapter.cache_clear()
    with patch("httpware.decoders.pydantic.TypeAdapter", wraps=pydantic.TypeAdapter) as spy:
        decoder = PydanticDecoder()
        for _ in range(1000):
            decoder.decode(b'{"id": 1, "name": "Ada"}', User)
        assert spy.call_count == 1
```

The new test (identical body — the spy on `pydantic.TypeAdapter` is on the underlying constructor, not on the deleted module-level factory; the decoder instance is fresh so the cache starts empty):

```python
def test_cache_invariance_single_model() -> None:
    with patch("httpware.decoders.pydantic.TypeAdapter", wraps=pydantic.TypeAdapter) as spy:
        decoder = PydanticDecoder()
        for _ in range(1000):
            decoder.decode(b'{"id": 1, "name": "Ada"}', User)
        assert spy.call_count == 1
```

Drop the `_get_adapter.cache_clear()` line; the per-instance dict starts empty. Everything else is identical. Same for `test_cache_invariance_two_distinct_models`, `test_cache_invariance_concurrent_first_calls`, `test_cache_invariance_concurrent_first_calls_threadpool`.

The `test_unhashable_model_falls_back_to_uncached_adapter` test changes shape slightly. It currently patches `httpware.decoders.pydantic._get_adapter` to raise TypeError. After this spec, `_get_adapter` is a method on the decoder instance; the patch target becomes `PydanticDecoder._get_adapter`:

```python
def test_unhashable_model_falls_back_to_uncached_adapter() -> None:
    decoder = PydanticDecoder()
    with patch.object(decoder, "_get_adapter", side_effect=TypeError("unhashable type")):
        result = decoder.decode(b"42", int)
        assert result == 42

        with pytest.raises(pydantic.ValidationError):
            decoder.decode(b'"not-an-int"', int)
```

(Construct one decoder, patch its method, drive it twice.)

The `test_pydantic_can_decode_uses_cache` test (added in PR #41 Task 1) currently asserts `_get_adapter.cache_info().hits >= 1`. After this spec, the assertion becomes "the same TypeAdapter instance is returned both times" OR "the decoder's `_adapters` dict has exactly one entry after two probes":

```python
def test_pydantic_can_decode_uses_cache() -> None:
    decoder = PydanticDecoder()
    decoder.can_decode(User)
    decoder.can_decode(User)
    assert len(decoder._adapters) == 1
    assert User in decoder._adapters
```

Same for `test_msgspec_can_decode_uses_cache`.

### Net test count

No new tests, no deleted tests. The cache-invariance test count stays the same; the autouse fixtures are removed (-2 lines × 2 files).

## Net diff estimate

- `src/httpware/decoders/pydantic.py`: ~-10 / +12 LOC.
- `src/httpware/decoders/msgspec.py`: ~-12 / +14 LOC.
- `tests/test_decoders_pydantic.py`: ~-6 / +3 LOC.
- `tests/test_decoders_msgspec.py`: ~-6 / +3 LOC.

Total: ~50 LOC churn, no public API surface change, no behavior change for end users.

## Release impact

Folded into `0.9.0` (not yet tagged; multi-decoder routing PR #41 is the headline of that release, but the tag hasn't been cut). This spec is internal refactor only — no release notes line; no `!` commit subject; commit message `refactor(decoders): per-instance cache replaces module-level lru_cache`.

If 0.9.0 has already been tagged by the time this lands, retag the patch as `0.9.1` and surface "per-instance decoder cache" as a brief internal-cleanup note. No user-facing migration.

## Memory updates after merge

The [[msgspec_basemodel_customtype_quirk]] memory's code reference (`src/httpware/decoders/msgspec.py:can_decode`) stays valid — the `type_info` + `CustomType` filter survives this refactor verbatim. No update needed there.

The [[multi_decoder_routing_shipped]] memory mentions "cached `msgspec.json.Decoder(model)`" in passing under headline changes — should be amended to "per-instance cached" if a future reader cares; minor.

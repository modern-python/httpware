---
summary: Shipped in 0.1.0; carry-forward decoder
---

# msgspec decoder via extras (design)

- **Date:** 2026-05-31
- **Status:** approved, ready for plan
- **Scope:** Story 1-6 (sixth story of Epic 1). Adds the second `ResponseDecoder` adapter — `MsgspecDecoder` — gated behind the `msgspec` extra. Introduces a small private `import_checker` module that future opt-in extras (otel, etc.) will reuse. Out of scope: AsyncClient wiring (Story 1-7), RecordedTransport (Story 1-8).
- **Roadmap pointer:** `docs/dev/engineering.md` §8 "Epic 1 — Make typed HTTP requests with sensible defaults".

## Why

Consumers with high-throughput needs want msgspec's validation speed. The `ResponseDecoder` protocol from Story 1-5 was designed for this — pluggable, single-parse-pass, model-driven. Story 1-6 ships the second adapter so when `AsyncClient` lands in 1-7, both decoders are available via `AsyncClient(decoder=PydanticDecoder())` or `AsyncClient(decoder=MsgspecDecoder())`.

The pattern for handling the optional dependency is borrowed from `modern-python/lite-bootstrap`: a small `import_checker` module uses `importlib.util.find_spec` to detect the extra without importing it. The adapter module then conditionally imports the dependency at module load, and raises a hinted `ImportError` only when the decoder is constructed without the extra installed. This keeps the module itself import-safe (useful for capability-probe patterns) and honors seam #5 ("never import an extra at package top-level").

## Decisions

| Decision | Choice |
| --- | --- |
| Import strategy | `find_spec`-based detection in `_internal/import_checker.py`; conditional `import msgspec` at the top of `decoders/msgspec.py`; `ImportError` raised at `MsgspecDecoder.__init__` if the extra is missing. Mirrors lite-bootstrap. |
| Install hint location | Module-level constant `MISSING_DEPENDENCY_MESSAGE = "..."` in `decoders/msgspec.py`. Not a class attribute. |
| Package-root re-export | None. Consumers import via `from httpware.decoders.msgspec import MsgspecDecoder`. Honors seam #5 (re-exporting would force eager `msgspec` load whenever the extra is installed). |
| Caching layer | None. `msgspec.json.decode` is a free function; no per-model adapter object to memoize, unlike `pydantic.TypeAdapter`. |
| Error propagation | `msgspec.ValidationError` and `msgspec.DecodeError` propagate unchanged. Mirrors `PydanticDecoder`'s `pydantic.ValidationError` handling. |
| `__all__` in `msgspec.py` and `import_checker.py` | None. Submodules don't get `__all__` going forward (project convention shift; existing files keep theirs until a follow-up cleanup). |
| `TYPE_CHECKING` block | None. The conditional `import msgspec` is sufficient for `ty`; no separate type-only import is needed. Fallback: `# ty: ignore[unresolved-reference]` on the `msgspec.json.decode` line if ty rejects, but lite-bootstrap precedent suggests it won't. |
| pyproject.toml | Untouched. `msgspec = ["msgspec>=0.18"]` is already declared (Story 1-1). |

## File structure

**New files:**
- `src/httpware/_internal/import_checker.py` — `find_spec`-based detection flags. Initial content is just `is_msgspec_installed`; future extras (otel, etc.) extend it.
- `src/httpware/decoders/msgspec.py` — `MsgspecDecoder` adapter.
- `tests/test_decoders_msgspec.py` — 8 behavioral tests for the decoder.
- `tests/test_optional_extras_isolation.py` — subprocess-based import-time guard. Future stories (5-4 otel) extend this file with their own subprocess checks.

**Modified files:**
- `CHANGELOG.md` — Story 1.6 bullet under `[Unreleased]` / `### Added`.

**Files NOT modified:**
- `pyproject.toml` — extras declaration already in place from Story 1-1.
- `src/httpware/__init__.py` — no package-root re-export of `MsgspecDecoder` (seam contract).
- `src/httpware/decoders/__init__.py` — `ResponseDecoder` protocol stays as-is; no new exports.

## `_internal/import_checker.py`

```python
"""Detect optional extras without importing them. Used by adapter modules to gate hard imports."""

from importlib.util import find_spec


is_msgspec_installed = find_spec("msgspec") is not None
```

Notes:
- One line of state, one purpose. Future stories add more `is_X_installed` flags as additional extras land (otel in Story 5-4, etc.).
- `find_spec` does NOT import the target module; it only checks whether the importer can find it. Side-effect-free.
- Module-level evaluation: the flag is computed once at import time and cached for the process lifetime. Re-installing the extra after process start is not supported (acceptable — the same caveat applies to lite-bootstrap and any other find_spec-based pattern).
- No `__all__`. The module exports one name; users import it via `from httpware._internal import import_checker` and access `import_checker.is_msgspec_installed`.

## `decoders/msgspec.py`

```python
"""MsgspecDecoder — opt-in ResponseDecoder backed by msgspec.json.decode."""

from typing import TypeVar

from httpware._internal import import_checker


if import_checker.is_msgspec_installed:
    import msgspec


MISSING_DEPENDENCY_MESSAGE = (
    "MsgspecDecoder requires the 'msgspec' extra. "
    "Install with: pip install httpware[msgspec]"
)

T = TypeVar("T")


class MsgspecDecoder:
    """Decode raw response bytes via `msgspec.json.decode(content, type=model)`.

    Requires the `msgspec` extra: `pip install httpware[msgspec]`. Importing
    this module without the extra works (the `msgspec` import is guarded by a
    `find_spec` check), but instantiating the decoder raises `ImportError` with
    the install hint.
    """

    def __init__(self) -> None:
        if not import_checker.is_msgspec_installed:
            raise ImportError(MISSING_DEPENDENCY_MESSAGE)

    def decode(self, content: bytes, model: type[T]) -> T:
        """Validate `content` as JSON against `model` in a single parse pass."""
        return msgspec.json.decode(content, type=model)
```

Notes:
- The runtime `import msgspec` is gated by `is_msgspec_installed`; if the flag is False, the `msgspec` name is undefined at module load, but `decode` is never reachable in that case (the constructor raises first).
- No `__all__`.
- The class has no subclassing hooks, but subclassing is permitted; subclasses inherit the same import check.
- Single-pass invariant from `engineering.md` §3 holds: `msgspec.json.decode(content, type=model)` parses bytes and constructs the model in one C-level call.

## Behavior and edge cases

**Decode path:**
- Both `msgspec.Struct` subclasses and pydantic `BaseModel` subclasses are valid `model` arguments — msgspec's decoder accepts both natively.
- Builtin types (`int`, `str`, `list[int]`, etc.) also work.
- Generic containers (`list[Item]`, `dict[str, Item]`) work.

**Error propagation:**
- `msgspec.ValidationError` — validation failure (shape mismatch, type mismatch).
- `msgspec.DecodeError` — JSON parse failure (malformed bytes).
- Both surface unchanged; the user wrote `response_model=X` to validate, and the validation error is the answer. Wrapping would obscure the actual failure.

**Construction:**
- `MsgspecDecoder()` succeeds when the extra is installed.
- Raises `ImportError(MISSING_DEPENDENCY_MESSAGE)` when missing.

**Import-time guarantees:**
- `import httpware` does NOT touch `msgspec` — `httpware/__init__.py` does not import from `httpware.decoders.msgspec` (seam contract).
- `import httpware.decoders.msgspec` only imports the `msgspec` C extension if `is_msgspec_installed` is True. The module itself imports successfully regardless.
- `from httpware.decoders.msgspec import MsgspecDecoder` returns the class even when the extra is missing — only construction fails. This enables capability-probe code.

## Testing

### `tests/test_decoders_msgspec.py` — 8 tests

| Test | Verifies |
| --- | --- |
| `test_decoder_satisfies_response_decoder_protocol` | `isinstance(MsgspecDecoder(), ResponseDecoder)`. |
| `test_decode_into_msgspec_struct` | Decode JSON into a `msgspec.Struct` subclass. |
| `test_decode_into_pydantic_model` | Decode JSON into a pydantic `BaseModel` — verifies msgspec handles both natively. |
| `test_decode_into_builtin_type` | `decode(b'42', int) == 42`. |
| `test_decode_into_list_of_struct` | `decode(b'[{"name":"a","qty":1}]', list[Item])` returns `[Item(...)]`. |
| `test_decode_validation_error_propagates` | Schema mismatch (`"qty"` is not an int) raises `msgspec.ValidationError` unchanged. |
| `test_decode_json_parse_error_propagates` | Malformed JSON (`b'{'`) raises `msgspec.DecodeError` unchanged. |
| `test_construction_raises_without_extra_via_monkeypatch` | Monkeypatch `httpware._internal.import_checker.is_msgspec_installed = False`; `MsgspecDecoder()` raises `ImportError` containing the install-hint string. |

### `tests/test_optional_extras_isolation.py` — 1 test

| Test | Verifies |
| --- | --- |
| `test_importing_httpware_does_not_import_msgspec` | Subprocess: `python -c "import httpware; import sys; sys.exit(0 if 'msgspec' not in sys.modules else 1)"`. Asserts exit code 0. |

The subprocess approach is necessary because `msgspec` IS installed in the test environment (via the `[msgspec]` extra and CI's `--all-extras` flag) — an in-process check would see `msgspec` in `sys.modules` from previous tests. The subprocess gets a fresh interpreter.

Future stories extend this file with their own subprocess tests as new extras land (Story 5-4 OpenTelemetry, etc.).

### Coverage and constraints

- **Coverage expectation:** 100% line coverage on `import_checker.py` (one line) and `decoders/msgspec.py` (all branches).
- **No `httpx2` import** in either new source file or new test file. The existing `tests/test_no_httpx2_leakage.py` continues to pass.
- **No `from __future__ import annotations`.**
- **No `print()`, no `logging.basicConfig`.**
- **No `# type: ignore`.** If `ty` rejects `msgspec.json.decode(...)` because of the conditional `import msgspec`, fallback is `# ty: ignore[unresolved-reference]` on that one line with an explanatory comment. Lite-bootstrap precedent suggests this won't be needed.

## CHANGELOG entry

Under `[Unreleased]` / `### Added`:

```markdown
- `MsgspecDecoder` opt-in `ResponseDecoder` adapter behind the `[msgspec]` extra; `msgspec.json.decode(content, type=model)` in a single C-level parse pass. Accepts `msgspec.Struct`, pydantic `BaseModel`, and builtin types as `model`. `msgspec.ValidationError` and `msgspec.DecodeError` propagate unchanged. Module import is safe without the extra (gated by `httpware._internal.import_checker.is_msgspec_installed`); only `MsgspecDecoder()` construction raises `ImportError` with an install hint when the extra is missing. `import httpware` does NOT eagerly load `msgspec` — `MsgspecDecoder` is reachable only via `from httpware.decoders.msgspec import MsgspecDecoder` (Story 1.6).
```

## Constraints and invariants

- Honors the five protocol seams; specifically seam #5 (optional extras isolated to their own modules; no package-root re-export).
- Decoder satisfies the `ResponseDecoder` protocol structurally (no nominal inheritance required).
- Module-level `import msgspec` (when reached) is the SOLE `msgspec` import in the project — the same single-seam rule that applies to `httpx2`. Future test addition could mirror `tests/test_no_httpx2_leakage.py` if msgspec confinement becomes a CI-enforced invariant; deferred for now (msgspec is not as broadly used as httpx2 across the codebase).
- `import_checker.py` itself never imports the modules it checks; only `find_spec`.

## Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| `ty` rejects `msgspec.json.decode(...)` because `msgspec` is imported inside a runtime `if`. | Add `# ty: ignore[unresolved-reference]` on the call site with a comment pointing at the `import_checker` guard. Decided at implementation time; not expected based on lite-bootstrap precedent. |
| Subprocess isolation test is flaky on the CI runner (e.g., `python` not on PATH). | Use `sys.executable` instead of bare `python` in the subprocess invocation. Standard pytest pattern. |
| A future story breaks the "no package-root re-export" invariant by adding `from httpware.decoders.msgspec import MsgspecDecoder` to `httpware/__init__.py`. | The subprocess isolation test catches this regression: `import httpware` would then transitively load `msgspec`, and the assertion would fail. |
| `MsgspecDecoder()` construction inside an `AsyncClient(decoder=MsgspecDecoder())` argument expression raises `ImportError` from deep inside a config-building stack when the extra is missing. | This is the intended behavior — the user is explicitly asking for the decoder. The install-hint message names the right extra and command. AsyncClient (Story 1-7) does not need to wrap or intercept. |
| msgspec API drift (`msgspec.json.decode` signature change in a future major). | `msgspec>=0.18,<1.0` is the implicit constraint via the `[msgspec]` extra. Pin upper bound explicitly in pyproject if drift becomes a concern. Deferred. |

## Definition of done

- `src/httpware/_internal/import_checker.py` exists with `is_msgspec_installed`.
- `src/httpware/decoders/msgspec.py` exists with `MsgspecDecoder` and `MISSING_DEPENDENCY_MESSAGE`. No `__all__`.
- `tests/test_decoders_msgspec.py` contains 8 passing tests; 100% line coverage on the new source files.
- `tests/test_optional_extras_isolation.py` contains the subprocess-based import-isolation test; passes.
- `CHANGELOG.md` has a Story 1.6 bullet under `[Unreleased]` / `### Added`.
- `just test` shows the increment from the post-2.3 baseline of 198 → 207 passed, 1 deselected, 100% coverage.
- `just lint-ci` clean.
- `tests/test_no_httpx2_leakage.py` still passes.
- `import httpware` (via subprocess) does not load `msgspec` into `sys.modules`.
- Story 1-6 lands as a single PR off `main` via the branch `story/1-6-msgspec-decoder-via-extras`.

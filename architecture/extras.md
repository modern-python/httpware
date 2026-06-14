# Optional extras

A protocol seam is a documented internal boundary. AI agents and contributors must respect it — never cross a seam except through its protocol.

## Seam C: `httpware` ↔ optional extras

- **Where:** `pyproject.toml` extras (`[project.optional-dependencies]`) ↔ the adapter modules that import them.
- **Contract:** each optional dependency is imported only inside its own dedicated module (e.g., `pydantic` in `decoders/pydantic.py`; `msgspec` in `decoders/msgspec.py`). New extras are declared in `pyproject.toml` at the same time the code that uses them lands — not earlier.
- **Rule:** never import an extra at package top-level. The package must import cleanly when the extra is not installed.
- **Verification:** `tests/test_optional_extras_isolation.py` runs a fresh-subprocess `import httpware` and asserts that neither pydantic nor msgspec ends up in `sys.modules`. New extras must add the same isolation test.

## The optional-extras pattern

`httpware` core has a small dependency set. Capabilities that pull in heavyweight dependencies (`pydantic`, `msgspec`) live behind extras declared in `pyproject.toml`:

```toml
[project.optional-dependencies]
pydantic = ["pydantic>=2.0,<3.0"]
msgspec = ["msgspec>=0.18"]
```

Each extra's code lives in a single dedicated module (`decoders/pydantic.py`, `decoders/msgspec.py`). The `import` of the extra happens **inside** that module behind an `is_<extra>_installed` guard from `_internal/import_checker.py` — never at package top level. This way, `import httpware` works cleanly without the extras installed, and the seam stays observable: `grep -rnE 'from pydantic|import pydantic' src/httpware/ | grep -v import_checker` returns exactly one indented line (the guarded import in `decoders/pydantic.py`), and the same is true for `msgspec`.

New extras are added at the same time as the code that uses them — never preemptively. The `otel` extra is paired with the code that uses it: `Retry`, `Bulkhead`, `CircuitBreaker`, and `AsyncTimeout` add events to the active OpenTelemetry span via `trace.get_current_span().add_event(...)`.

Caller-facing pattern: `AsyncClient()` / `Client()` default `decoders=None` resolves via `_build_default_decoders()` against installed extras (pydantic-first when both are present, the installed one when only one is present, empty tuple when neither). Consumers override by passing `decoders=[...]` explicitly; `decoders=[]` is honored as an opt-out. The auto-resolution is a snapshot of `import_checker.is_<extra>_installed` flags at `__init__` time — there is no runtime re-detection or implicit registry beyond the two built-in decoders.

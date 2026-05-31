# Contributing to httpware

Thank you for your interest in contributing. `httpware` is an open-source resilience-first async HTTP client framework for Python, maintained under the [`modern-python`](https://github.com/modern-python) org.

## Quick start

```bash
git clone https://github.com/modern-python/httpware.git
cd httpware
just install        # uv lock --upgrade && uv sync --all-extras --frozen --group lint
just lint           # ruff format + ruff check + ty check
just test           # pytest with coverage
```

## Development workflow

1. **Open an issue first** for non-trivial changes — design discussion catches issues earlier than code review.
2. **Branch from `main`**, use a descriptive name (`feat/retry-budget-jitter`, `fix/transport-cancel-leak`).
3. **Run `just lint` and `just test`** locally before pushing. CI will reject changes that fail either.
4. **Add tests** for any code change. Property-based tests (via Hypothesis) are required for concurrency-sensitive code (retry budget, bulkhead, retry interleaving).
5. **Open a pull request** against `main`. PR titles use conventional-commits style (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`).

## Code style

- `ruff format` enforces formatting; do not hand-format.
- Type-check with `ty` (Astral). Use `# ty: ignore[<rule>]` for suppressions, not `# type: ignore`.
- Do NOT use `from __future__ import annotations`. Python 3.11+ is the floor.
- Module docstrings are required; per-method docstrings only when types alone are insufficient.

See `docs/concepts/middleware.md` and `docs/recipes/custom-middleware.md` (once published) for architecture conventions.

## Architecture invariants

These are enforced by CI grep gates. Do not break them in pull requests:

- No `import httpx2` outside `src/httpware/transports/httpx2.py`.
- No `httpx2._*` (private API) usage anywhere in the library.
- No `from __future__ import annotations`.
- No `print()` calls.
- No `logging.basicConfig()` or bare `logging.getLogger()`.

## Code of Conduct

By participating in this project, you agree to abide by its Code of Conduct. Be excellent to one another.

## License

By contributing, you agree that your contributions will be licensed under the project's MIT license.

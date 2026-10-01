# Contributing to httpware

Thank you for your interest in contributing. httpware is maintained under the [`modern-python`](https://github.com/modern-python) org.

## Quick start

```bash
git clone https://github.com/modern-python/httpware.git
cd httpware
just install        # uv lock --upgrade && uv sync --all-extras --frozen --group lint
just lint           # eof-fixer + ruff format + ruff check + ty check
just test           # pytest with coverage
```

## Development workflow

1. For a non-trivial change, open an issue first so the design can be discussed before code review.
2. Branch from `main` with a descriptive name, such as `feat/retry-budget-jitter` or `fix/transport-cancel-leak`.
3. Run `just lint` and `just test` before pushing. CI rejects changes that fail either.
4. Add tests for every code change. Concurrency-sensitive code (retry budget, bulkhead, retry interleaving) also needs property-based tests with Hypothesis.
5. Open a pull request against `main`. PR titles follow conventional commits (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`).

## Code style

- `ruff format` enforces formatting; do not hand-format.
- Type-check with `ty` (Astral). Use `# ty: ignore[<rule>]` for suppressions, not `# type: ignore`.
- Don't use `from __future__ import annotations`; the minimum Python version is 3.11.
- Module, class, and public-method docstrings are required (PEP 257).

## Architecture invariants

Pull requests must keep these rules. CI does not check all of them; `AGENTS.md`
lists the ones only enforced in review.

- No `httpx2._*` (private API) usage anywhere in the library.
- No `from __future__ import annotations`.
- No `print()` calls.
- No `logging.basicConfig()` or bare `logging.getLogger()`.
- Type suppressions use `# ty: ignore[<rule>]`, never `# type: ignore` or `# mypy: ignore`.

## Code of Conduct

By participating in this project, you agree to follow the [`modern-python` Code of Conduct](https://github.com/modern-python/.github/blob/main/CODE_OF_CONDUCT.md).

## License

By contributing, you agree that your contributions will be licensed under the project's MIT license.

# CLAUDE.md

Guidance for AI agents (Claude Code, etc.) working in this repository.

## Project Overview

`httpware` is a Python async HTTP client framework for building resilient service clients. It supersedes `community-of-python/base-client` and ships under the `modern-python` org. The framework is a thin opinionated wrapper around `httpx2`: it re-exports `httpx2.Request`/`httpx2.Response`, adds a middleware chain, typed response decoding, and a status-keyed exception tree raised automatically on 4xx/5xx.

**Where to find what:**

- [`planning/engineering.md`](planning/engineering.md) — the distilled design reference: invariants and *why*, the three protocol seams, exception contract, module layout, testing patterns, optional-extras pattern, remaining roadmap. Read this before adding any new module or extension point.
- [`planning/deferred-work.md`](planning/deferred-work.md) — review-surfaced items that are real but not actionable now.
- [`planning/specs/`](planning/specs/) and [`planning/plans/`](planning/plans/) — per-feature design specs and implementation plans (active work).

**Per-feature workflow:** brainstorming → spec in `planning/specs/` → writing-plans → plan in `planning/plans/` → executing-plans (or subagent-driven-development) → requesting-code-review → finishing-a-development-branch. Topic slugs are kebab-case descriptions (`msgspec-decoder-adapter`), not story IDs.

## Commands

This project uses `just` (task runner) and `uv` (package manager).

```bash
just install      # uv lock --upgrade && uv sync --all-extras --frozen --group lint
just lint         # eof-fixer + ruff format + ruff check --fix + ty check
just lint-ci      # same checks without auto-fixing (used in CI)
just test         # uv run pytest (with coverage by default)
just test-branch  # pytest with branch coverage
```

`just test` passes extra args to pytest:

```bash
just test tests/test_client.py
just test tests/test_client.py -k test_get_returns_typed_response
```

Without `just`:

```bash
uv run ruff format . && uv run ruff check . --fix && uv run ty check
uv run pytest
```

## Architecture invariants (CI-enforced)

These are non-negotiable. CI rejects PRs that violate them.

- **No `httpx2` private API**: `grep -rE 'httpx2\._' src/httpware/` must return zero matches. Public symbols only.
- **No `from __future__ import annotations`**: Python 3.11+ floor; PEP 604/585 syntax is native.
- **No `print()`**: enforced by ruff.
- **No global logging config**: no `logging.basicConfig()`, no bare `logging.getLogger()`. Acquire `logging.getLogger("httpware")` or `logging.getLogger(f"httpware.{module}")` only.
- **Type suppressions**: use `# ty: ignore[<rule>]`, never `# type: ignore` or `# mypy: ignore`.

## Code conventions

- **Modules**: `snake_case` (`client.py`, `errors.py`, `middleware/chain.py`).
- **Classes**: `PascalCase`. `Http` is two letters: `AsyncClient`, not `ASYNCClient`.
- **Methods**: `snake_case`. No `a` prefix on async methods (match `httpx2`); `aclose()` is the sole exception.
- **Private symbols**: `_leading_underscore`. Cross-module private code lives in `_internal/`.
- **Imports**: absolute paths inside `src/httpware/`; relative imports only within the same subpackage.
- **Docstrings**: PEP 257. Module/class/public-method required; `D1` (missing docstring) is ignored.
- **Exception construction**: status-keyed errors take a single positional `response: httpx2.Response`. Subclasses do not override `__init__`. All fields available via `exc.response.*`.

## Module layout

```
src/httpware/
├── __init__.py                    # public exports + __all__
├── client.py                      # AsyncClient (thin wrapper over httpx2.AsyncClient)
├── errors.py                      # status-keyed exception hierarchy holding httpx2.Response
├── middleware/                    # protocol, Next type, chain composition, phase decorators
├── decoders/                      # ResponseDecoder protocol + Pydantic/msgspec adapters
├── _internal/                     # private cross-module helpers
└── py.typed
```

## Protocol seams

Three documented internal boundaries. AI agents must respect them — never cross a seam except through its documented protocol.

1. **`AsyncClient ↔ Middleware`** — middleware chain composed at `AsyncClient.__init__`, frozen for the client's lifetime. Internal terminal calls `httpx2.AsyncClient.send`, maps exceptions, raises `StatusError` on 4xx/5xx.
2. **`AsyncClient ↔ ResponseDecoder`** — called when `response_model` is provided. Signature: `decode(content: bytes, model: type[T]) -> T`.
3. **`httpware ↔ optional extras`** — each opt-in dependency imported only inside its dedicated module.

## Testing

- `pytest-asyncio` auto mode — async tests do NOT need `@pytest.mark.asyncio`.
- Property-based tests (Hypothesis) for concurrency-sensitive code: `RetryBudget`, `Bulkhead`, retry interleaving. Files named `test_*_props.py`.
- Tests inject `httpx2.MockTransport` via `AsyncClient(httpx2_client=httpx2.AsyncClient(transport=mock))`. No `respx`, no `RecordedTransport`.

## When in doubt

- Check [`planning/engineering.md`](planning/engineering.md) before adding a new module or extension point.
- Surface ambiguity as a documentation gap rather than improvising.

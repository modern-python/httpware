# CLAUDE.md

Guidance for AI agents (Claude Code, etc.) working in this repository.

## Project Overview

`httpware` is a Python async HTTP client framework for building resilient service clients. It supersedes `community-of-python/base-client` and ships under the `modern-python` org. The framework owns the abstraction layer above the underlying HTTP client (`httpx2` by default); consumers never import the transport.

**Source-of-truth planning artifacts** live in this repo under `docs/`:

- `docs/prd.md` — Product Requirements Document (47 FRs, 25 NFRs)
- `docs/architecture.md` — 12 architectural decisions, 5 protocol seams, full module layout
- `docs/epics.md` — 6 epics, 32 stories with Given/When/Then acceptance criteria
- `docs/product-brief-httpware.md` — executive brief (history of how the project was scoped)
- `docs/product-brief-httpware-distillate.md` — PRD-ready detail pack with verified facts, API patterns, performance specifics, rejected alternatives, open questions

Stories under active dev live in `docs/stories/`. (Initial planning artifacts were authored in the predecessor repo `community-of-python/base-client` and copied here at the end of Story 1.1; both copies are kept in sync until base-client is archived.)

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

- **No `httpx2` leakage**: `import httpx2` / `from httpx2` is allowed ONLY inside `src/httpware/transports/httpx2.py`. The mapping of `httpx2` exceptions to `httpware` exceptions happens at that single seam.
- **No `httpx2` private API**: `grep -rE 'httpx2\._' src/httpware/` must return zero matches.
- **No `from __future__ import annotations`**: Python 3.11+ floor; PEP 604/585 syntax is native.
- **No `print()`**: enforced by ruff.
- **No global logging config**: no `logging.basicConfig()`, no bare `logging.getLogger()`. Acquire `logging.getLogger("httpware")` or `logging.getLogger(f"httpware.{module}")` only.
- **Type suppressions**: use `# ty: ignore[<rule>]`, never `# type: ignore` or `# mypy: ignore`.

## Code conventions

- **Modules**: `snake_case` (`client.py`, `request.py`, `transports/httpx2.py`).
- **Classes**: `PascalCase`. `Http` is two letters: `Httpx2Transport`, not `HTTPX2Transport`.
- **Methods**: `snake_case`. No `a` prefix on async methods (match `httpx2`); `aclose()` is the sole exception.
- **Private symbols**: `_leading_underscore`. Cross-module private code lives in `_internal/`.
- **Imports**: absolute paths inside `src/httpware/`; relative imports only within the same subpackage.
- **Docstrings**: PEP 257. Module/class/public-method required; `D1` (missing docstring) is ignored.
- **Exception construction**: keyword arguments only. Mandatory fields: `status: int`, `body: bytes`, `headers: Mapping`, `json: Any | None`, `request_method: str`, `request_url: str`.

## Module layout

```
src/httpware/
├── __init__.py                    # public exports + __all__
├── client.py                      # AsyncClient
├── request.py                     # Request + with_*
├── response.py                    # Response, StreamResponse
├── errors.py                      # status-keyed exception hierarchy
├── config.py                      # Limits, Timeout, ClientConfig, Redactor
├── middleware/                    # protocols + built-in middleware
├── transports/                    # Transport protocol + Httpx2Transport + RecordedTransport
├── decoders/                      # ResponseDecoder protocol + adapters
├── _internal/                     # private cross-module helpers
└── py.typed
```

Story 1.1 ships only the scaffold; subsequent stories add modules.

## Protocol seams

Five documented internal boundaries. AI agents must respect them — never cross a seam except through its documented protocol.

1. **`Middleware ↔ Transport`** — chain bottom calls `transport.__call__`.
2. **`AsyncClient ↔ Middleware`** — chain composed at construction.
3. **`AsyncClient ↔ ResponseDecoder`** — called when `response_model` provided.
4. **`Httpx2Transport ↔ httpx2`** — only `transports/httpx2.py` imports `httpx2`.
5. **`httpware ↔ optional extras`** — extras imported only inside their dedicated modules.

## Testing

- `pytest-asyncio` auto mode — async tests do NOT need `@pytest.mark.asyncio`.
- Property-based tests (Hypothesis) for concurrency-sensitive code: `RetryBudget`, `Bulkhead`, retry interleaving. Files named `test_*_props.py`.
- Tests for transport-level mocking use `RecordedTransport` (shipped with the library); not `respx`.

## When in doubt

- Check the architecture document (`base-client/docs/architecture.md`) before adding a new module or extension point.
- Surface ambiguity as a documentation gap rather than improvising.

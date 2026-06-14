# CLAUDE.md

Guidance for AI agents (Claude Code, etc.) working in this repository.

## Project Overview

`httpware` is a Python HTTP client framework with sync and async clients for building resilient service clients. It supersedes `community-of-python/base-client` and ships under the `modern-python` org. The framework is a thin opinionated wrapper around `httpx2`: it re-exports `httpx2.Request`/`httpx2.Response`, adds a middleware chain, typed response decoding, and a status-keyed exception tree raised automatically on 4xx/5xx.

**Where to find what:**

- [`architecture/`](architecture/) (repo root) — the per-capability living truth (overview, client, middleware, decoders, errors, resilience, optional extras, testing); the promotion target on every ship. **Read the relevant file before changing that capability.**
- [`planning/README.md`](planning/README.md) — the planning conventions (two axes, change bundles, three lanes, frontmatter) + the change Index.
- [`planning/changes/{active,archive}/<YYYY-MM-DD.NN-slug>/`](planning/changes/) — per-change bundles (`design.md` + `plan.md`, or `change.md` for the lightweight lane).
- [`planning/audits/`](planning/audits/) — findings reports + `scripts/` tooling.
- [`planning/retros/`](planning/retros/) — retrospectives.
- [`planning/releases/`](planning/releases/) — per-version release notes (also published on GitHub Releases).
- [`planning/deferred.md`](planning/deferred.md) — review-surfaced, not-yet-actionable items.
- [`planning/_templates/`](planning/_templates/) — design/plan/change templates.

**Per-feature workflow:** brainstorming → `design.md` in `planning/changes/active/<id>/` → writing-plans → `plan.md` in the same bundle → executing-plans (or subagent-driven-development) → requesting-code-review → finishing-a-development-branch. On ship, promote the conclusions into the affected `architecture/<capability>.md` by hand and move the bundle to `planning/changes/archive/`. Topic slugs are kebab-case descriptions (`msgspec-decoder-adapter`), not story IDs.

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

## Architecture invariants

These are non-negotiable, but **most are NOT machine-checked — don't rely on CI to catch a violation.** Enforced by ruff: `print()` (`T201`) and a blanket `# type: ignore` (`PGH003`). Partially: `httpx2._` (ruff `SLF001` catches attribute access, not a *used* private import). Review-only: the future-import and global-logging bans.

- **No `httpx2` private API**: `grep -rE 'httpx2\._' src/httpware/` should return zero matches (run in review — not wired into CI). Public symbols only.
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
- **Exception construction**: status-keyed `StatusError` subclasses (the 4xx/5xx tree) take a single positional `response: httpx2.Response` and do NOT override `__init__` — all fields via `exc.response.*`. This rule scopes to `StatusError` only; non-status `ClientError` subclasses such as `DecodeError`, `MissingDecoderError`, `BulkheadFullError`, `RetryBudgetExhaustedError`, and `CircuitOpenError` deliberately define `__init__` with keyword-only fields. See `architecture/errors.md`.

## Module layout

```
src/httpware/
├── __init__.py                    # public exports + __all__
├── client.py                      # AsyncClient + Client (thin wrappers over httpx2.AsyncClient / httpx2.Client)
├── errors.py                      # status-keyed exception hierarchy holding httpx2.Response
├── middleware/                    # protocol, Next type, chain composition, phase decorators
├── decoders/                      # ResponseDecoder protocol + Pydantic/msgspec adapters
├── _internal/                     # private cross-module helpers
└── py.typed
```

## Protocol seams

Three documented internal boundaries. AI agents must respect them — never cross a seam except through its documented protocol.

1. **Seam A** — `Client`/`AsyncClient` ↔ `Middleware`/`AsyncMiddleware` — middleware chain composed at `Client.__init__` and `AsyncClient.__init__`, frozen for the client's lifetime. Internal terminal calls `httpx2.Client.send` or `httpx2.AsyncClient.send`, maps exceptions, raises `StatusError` on 4xx/5xx. Sync and async surfaces are kept at parity.
2. **Seam B** — `Client`/`AsyncClient` ↔ `ResponseDecoder` list — both clients take `decoders: Sequence[ResponseDecoder] | None` (a *list*, not a single decoder; `None` resolves against installed extras, pydantic-first). When `response_model` is provided, `send`/`send_with_response` (sync and async alike) walk the list and the first decoder whose `can_decode(model: type) -> bool` returns True runs `decode(content: bytes, model: type[T]) -> T`; if no decoder claims the model, `MissingDecoderError` is raised *before* the HTTP call. Decoder exceptions are wrapped as `DecodeError` at the seam. Full contract: [`architecture/decoders.md`](architecture/decoders.md).
3. **Seam C** — `httpware` ↔ optional extras — each opt-in dependency imported only inside its dedicated module.

## Testing

- `pytest-asyncio` auto mode — async tests do NOT need `@pytest.mark.asyncio`.
- Property-based tests (Hypothesis) for concurrency-sensitive code: `RetryBudget`, `Bulkhead`, retry interleaving. Files named `test_*_props.py`.
- Tests inject `httpx2.MockTransport` via `AsyncClient(httpx2_client=httpx2.AsyncClient(transport=mock))` for async or `Client(httpx2_client=httpx2.Client(transport=mock))` for sync. No `respx`, no `RecordedTransport`.

## When in doubt

- Check the relevant [`architecture/`](architecture/) capability file before adding a new module or extension point.
- Surface ambiguity as a documentation gap rather than improvising.

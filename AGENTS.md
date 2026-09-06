# AGENTS.md

Guidance for AI agents (Claude Code, etc.) working in this repository.

## Project Overview

`httpware` is a Python HTTP client framework with sync and async clients for building resilient service clients. It ships under the `modern-python` org and is a thin opinionated wrapper around `httpx2`: it re-exports `httpx2.Request`/`httpx2.Response`, adds a middleware chain, typed response decoding, and a status-keyed exception tree raised automatically on 4xx/5xx.

**Where to find what:**

- [`architecture/`](architecture/) (repo root) — the per-capability living truth, one file per capability ([`architecture/README.md`](architecture/README.md) is the index). The promotion target on every ship. **Read the relevant file before changing that capability.**
- [`planning/README.md`](planning/README.md) — the planning convention (Quick path + the two-axis convention) and the generated change Index.
- [`planning/changes/<YYYY-MM-DD.NN-slug>.md`](planning/changes/) — flat change files, one per change (design template for the full lane, change template for the lightweight lane).
- [`planning/decisions/`](planning/decisions/), [`planning/audits/`](planning/audits/), [`planning/retros/`](planning/retros/), [`planning/releases/`](planning/releases/), [`planning/deferred.md`](planning/deferred.md) — decisions, findings sweeps, retrospectives, release notes, and deferred items.

## Workflow

Planning follows the portable two-axis convention — `architecture/` (repo root) is the living **truth home** and promotion target; `planning/changes/` holds the flat change files. **Start at the [Quick path](planning/README.md#quick-path-start-here)** in `planning/README.md` to choose a lane (Full / Lightweight / Tiny), create a change file, and ship — that file is the authoritative spec. Run `just check-planning` to validate changes and `just index` to print the change listing.

## Commands

This project uses `just` (task runner) and `uv` (package manager). `just --list` is the source of truth; non-obvious notes:

- `just lint` auto-fixes; `just lint-ci` is the read-only CI variant (and runs the planning validator).
- `just test` runs pytest with coverage and forwards extra args: `just test tests/test_client.py -k test_name`.
- Without `just`: `uv run ruff format . && uv run ruff check . --fix && uv run ty check && uv run pytest`.

## Architecture

> Quick orientation. The authoritative, code-current account of each capability lives in [`architecture/`](architecture/). **When a change alters a capability's behavior, update the matching `architecture/<capability>.md` in the same PR** — that promotion is what keeps `architecture/` true; code that changes without it silently rots the truth home.

`httpware` is a thin wrapper over `httpx2` (`httpx2.Request`/`httpx2.Response` are public surface, not abstracted away) built around three documented protocol seams. **Invariants that must not break:**

- **Three protocol seams, crossed only through their protocols.** Seam A: `Client`/`AsyncClient` ↔ middleware chain, composed at `__init__` and frozen for the client's lifetime; the internal terminal calls `httpx2.*.send`, maps exceptions, and raises `StatusError` on 4xx/5xx. Seam B: clients ↔ `decoders: Sequence[ResponseDecoder] | None` — first decoder whose `can_decode` is True runs; `MissingDecoderError` raises *before* the HTTP call if none claims the model; decoder failures wrap as `DecodeError`. Seam C: `httpware` ↔ optional extras — each opt-in dependency imported only inside its dedicated module.
- **Sync/async parity.** `Client` and `AsyncClient` carry identical features (typed decoding, middleware, resilience, `stream()`); a change to one surface must mirror to the other.
- **House invariants** (most review-only, not CI-checked): no `httpx2._` private API; no `from __future__ import annotations` (3.11+ floor); no `print()` (ruff `T201`); no global logging config (`logging.getLogger("httpware")` / namespaced children only); type suppressions use `# ty: ignore[<rule>]`, never `# type: ignore`.
- **Errors.** Status-keyed `StatusError` subclasses take a single positional `response` and never override `__init__`; non-status `ClientError` subclasses (`DecodeError`, `MissingDecoderError`, `BulkheadFullError`, `RetryBudgetExhaustedError`, `CircuitOpenError`, `ResponseTooLargeError`) do.

| Capability | File |
|---|---|
| What httpware is + architectural invariants + module layout | [`architecture/overview.md`](architecture/overview.md) |
| Sync `Client` / async `AsyncClient` parity, `stream()` | [`architecture/client.md`](architecture/client.md) |
| Seam A — middleware protocol, `Next`, chain composition | [`architecture/middleware.md`](architecture/middleware.md) |
| Seam B — `ResponseDecoder` protocol, pydantic/msgspec resolution | [`architecture/decoders.md`](architecture/decoders.md) |
| Status-keyed exception tree, construction invariant, redaction | [`architecture/errors.md`](architecture/errors.md) |
| Resilience suite (retry, budget, bulkhead, circuit breaker, timeout) | [`architecture/resilience.md`](architecture/resilience.md) |
| Seam C — optional extras isolation | [`architecture/extras.md`](architecture/extras.md) |
| House code conventions (naming, imports, docstrings) | [`architecture/conventions.md`](architecture/conventions.md) |
| Testing conventions | [`architecture/testing.md`](architecture/testing.md) |

## When in doubt

- Check the relevant [`architecture/`](architecture/) capability file before adding a new module or extension point.
- Surface ambiguity as a documentation gap rather than improvising.

## Agent skills

- **Issue tracker** — Issues live in GitHub Issues (`modern-python/httpware`), managed via the `gh` CLI; external PRs are not a triage surface. See `planning/agents/issue-tracker.md`.
- **Triage labels** — Canonical defaults: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `planning/agents/triage-labels.md`.
- **Domain docs** — Single-context: one `CONTEXT.md` at the repo root + ADRs under `planning/adr/`. See `planning/agents/domain.md`.

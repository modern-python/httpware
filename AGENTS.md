# AGENTS.md

Guidance for AI agents (Claude Code, etc.) working in this repository.

## Project Overview

`httpware` is a thin, opinionated wrapper around `httpx2` with sync and async clients for building
resilient service clients; [`CONTEXT.md`](CONTEXT.md) opens with what it does and owns the
vocabulary. Read it before naming a concept in code, a test name, or an issue title. It ships
under the `modern-python` org.

## Commands

`just` (task runner) and `uv` (package manager). The [`justfile`](justfile) is the source of truth:
`just --list`, or read it. The one thing it does not say: `just docs-build` runs `mkdocs --strict`
over the site only, and `docs/adr/` and `docs/agents/` are excluded from it (`exclude_docs` in
`mkdocs.yml`) because they are read on GitHub rather than published. Their links are covered
instead by the `links` job in `.github/workflows/_checks.yml`, which runs lychee `--offline` over
every `*.md` in the repo.

## Architecture

`httpx2` is part of the public surface: `httpx2.Request` and `httpx2.Response` are
re-exported as-is. Three protocol seams (client ↔ middleware chain, client ↔ decoder list, and
httpware ↔ optional extras) are defined in `CONTEXT.md` and named **A**, **B** and **C** in the
module docstrings that implement them. Never cross a seam except through its protocol.

### Key files

Every module under `src/httpware/` is named for what it does; read it. What a single-file read will
**not** tell you:

- `client.py` holds **both worlds**, `Client` and `AsyncClient`, hand-maintained at parity;
  nothing generates one from the other. A feature added to one must be mirrored to the other;
  `tests/test_client_parity.py` says why, and names the sole exception (`AsyncTimeout` has no sync
  sibling).
- `errors.py` owns the tree and both construction rules. Status-keyed `StatusError` subclasses take
  a single positional `response` and never define `__init__`; the six non-status subclasses are
  keyword-only. Pickling and copying go through one `__reduce__` on `ClientError`: it rebuilds the
  instance from `args` without calling `__init__` and restores `__dict__`, so a new class needs no
  pickling code, only picklable attributes. Adding a class means picking a construction side and
  adding a case to `_ERROR_FACTORIES` in `tests/test_errors.py`, which an invariant test enforces
  for every exported error class.
- `decoders/_resolver.py` is the **single dispatch path** for Seam B: `_DecoderResolver.resolve`
  walks the frozen decoder tuple, raises `MissingDecoderError` *before* the HTTP call when nothing
  claims the model, and returns a `_BoundDecoder` whose `decode` wraps any decoder-side failure as
  `DecodeError`. A decoder's `can_decode` runs outside that wrap, so it must never raise.
- `_internal/` is the cross-module private home; `_internal/observability.py:_emit_event` is the
  single fan-out to both a logging record and an OTel span event, and the event names it takes are
  a public contract (see `CONTEXT.md`). Logic shared only by a sync/async sibling pair stays a
  free function in the module that owns the behaviour; `_internal/` is for sharing across
  otherwise unrelated modules.
- `middleware/resilience/` keeps the shared logic objects (`_RetryPolicy`, `_CircuitBreakerState`,
  `RetryBudget`, `_backoff`, `_event_loop_guard`) written once and driven by both worlds. New
  resilience logic goes in a shared object, not into each world's shell.

**House invariants, review-only.** Nothing in CI catches these: no `httpx2._` private API (ruff
`SLF001` flags private *attribute* access but not a used private *import*); no
`from __future__ import annotations` (3.11+ floor); no global logging config
(`logging.getLogger("httpware")` and namespaced children only).

### Testing patterns

Transport mocking is `httpx2.MockTransport` passed as `transport=`, never `respx`, which
targets `httpx` rather than `httpx2` and patches its internals. Concurrency-sensitive components carry
Hypothesis property tests in `test_*_props.py`, and `stress`-marked tests drive real thread
parallelism: they run under the GIL for coverage, but the proof comes from the free-threaded
`3.14t` and `3.15t` CI jobs.

## Workflow

Every link in `README.md` must be absolute: `https://github.com/modern-python/<repo>/blob/main/<path>`,
or `.../tree/main/<path>` for a directory. Never a relative path: `README.md` is also the PyPI long
description, and PyPI does not rewrite relative links, so a relative one 404s on the package page.

Before pushing a raised dependency floor, run the `floors` steps from
[`_checks.yml`](.github/workflows/_checks.yml) locally. If resolution fails, raise the direct floor
it names.

## Code Style

- Design principle: thin wrapper, small public surface. `httpware.__all__` is checked against an
  explicit expected set in `tests/test_public_api.py`, so a symbol cannot appear unnoticed
- `Http` is two letters in a class name (`AsyncClient`, not `ASYNCClient`); no `a` prefix on async
  methods, matching `httpx2`; `aclose()` is the sole exception
- Docstrings: public API documents the contract; internal helpers get a one-line contract, plus at
  most one or two lines for a non-obvious constraint. Never narrate implementation or justify
  code to a reviewer; cross-file rationale lives in an invariant test's docstring

## Agent skills

### Issue tracker

GitHub issues on `modern-python/httpware`, via `gh`. See `docs/agents/issue-tracker.md`.

### Triage labels

The five canonical roles, each label string equal to its name. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `CONTEXT.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.

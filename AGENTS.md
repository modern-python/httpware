# AGENTS.md

Guidance for AI agents (Claude Code, etc.) working in this repository.

## Project Overview

`httpware` is a thin, opinionated wrapper around `httpx2` with sync and async clients for building
resilient service clients; [`CONTEXT.md`](CONTEXT.md) opens with what it does and owns the
vocabulary — read it before naming a concept in code, a test name, or an issue title. It ships
under the `modern-python` org.

## Commands

`just` (task runner) and `uv` (package manager). The [`justfile`](justfile) is the source of truth —
`just --list`, or read it. The one thing it does not say: `just docs-build` runs `mkdocs --strict`
over the site only, and `docs/adr/` and `docs/agents/` are excluded from it (`exclude_docs` in
`mkdocs.yml`) because they are read on GitHub rather than published. Their links are covered
instead by the `links` job in `.github/workflows/_checks.yml`, which runs lychee `--offline` over
every `*.md` in the repo.

## Architecture

`httpx2` is public surface, not an abstraction to hide: `httpx2.Request` and `httpx2.Response` are
re-exported as-is. Three protocol seams — client ↔ middleware chain, client ↔ decoder list, and
httpware ↔ optional extras — are defined in `CONTEXT.md` and named **A**, **B** and **C** in the
module docstrings that implement them. Never cross a seam except through its protocol.

Behavior detail has no prose home — it lives in the code and its `INVARIANT:`-marked tests. Before
writing prose about a capability, run the admission check in **Where a fact goes** below.

### Key files

Every module under `src/httpware/` is named for what it does; read it. What a single-file read will
**not** tell you:

- `client.py` holds **both worlds** — `Client` and `AsyncClient` — and they are hand-maintained at
  parity, not generated. A feature added to one must be mirrored to the other;
  `tests/test_client_parity.py` says why, and names the sole exception (`AsyncTimeout` has no sync
  sibling).
- `errors.py` owns the tree and both construction rules. Status-keyed `StatusError` subclasses take
  a single positional `response` and never define `__init__`; the six non-status subclasses are
  keyword-only and inherit `__reduce__` from `_KeywordReduceMixin`, whose precondition is enforced
  by `tests/test_errors.py::test_keyword_reduce_classes_dict_mirrors_their_init_parameters`. Adding
  a class means picking a side, and both sides are checked.
- `decoders/_resolver.py` is the **single dispatch path** for Seam B: `_DecoderResolver.resolve`
  walks the frozen decoder tuple, raises `MissingDecoderError` *before* the HTTP call when nothing
  claims the model, and returns a `_BoundDecoder` whose `decode` wraps any decoder-side failure as
  `DecodeError`. A decoder's `can_decode` runs outside that wrap, so it must never raise.
- `_internal/` is the cross-module private home; `_internal/observability.py:_emit_event` is the
  single fan-out to both a logging record and an OTel span event, and the event names it takes are
  a public contract (see `CONTEXT.md`).
- `middleware/resilience/` keeps the shared logic objects (`_RetryPolicy`, `_CircuitBreakerState`,
  `RetryBudget`, `_backoff`, `_event_loop_guard`) written once and driven by both worlds. New
  resilience logic goes in a shared object, not into each world's shell.

**House invariants, review-only** — nothing in CI catches these: no `httpx2._` private API (ruff
`SLF001` flags private *attribute* access but not a used private *import*); no
`from __future__ import annotations` (3.11+ floor); no global logging config —
`logging.getLogger("httpware")` and namespaced children only.

### Testing patterns

Transport mocking is `httpx2.MockTransport` passed as `httpx2_client=`, never `respx` — `respx`
targets `httpx`, not `httpx2`, and patches its internals. Concurrency-sensitive components carry
Hypothesis property tests in `test_*_props.py`, and `stress`-marked tests drive real thread
parallelism: they run under the GIL for coverage, but the proof comes from the free-threaded
`3.14t` CI job.

## Workflow

Two things outlive the PR, and there are exactly two places to put them: an alternative
**rejected** with reasoning becomes an ADR in [`docs/adr/`](docs/adr/) (`NNNN-slug.md`,
sequential), and real work **not scheduled** becomes a GitHub issue. There is no third state, and
no separate truth-home directory — a behaviour change is reviewed with the diff, not promoted to a
page.

### Where a fact goes

Four homes, one owner each:

| Home | Holds |
|---|---|
| `src/httpware/` | anything readable from the module — the default |
| a named test | an **invariant**: must stay true, and a change could silently break it |
| `docs/adr/` | a rejected alternative, with the reasoning that would otherwise be re-litigated |
| `docs/` | anything a user needs |

Before writing a line anywhere:

> Can an agent get this by reading `src/httpware/`? → **don't write it.**
> Would a wrong change here fail a test? → it belongs **in the test**, not in prose.
> Does a user need it? → **`docs/`**.
> Otherwise it does not get written.

**Prose about mechanism has no home. There is no file to add a paragraph to.** This file included:
it is always loaded, so a line that restates a docstring, a justfile comment, or `pyproject.toml`
costs every turn and rots in two places at once.

An invariant is a test whose name is the claim, with a docstring opening `INVARIANT:` and a second
paragraph naming **what breaks it** — design rationale, not a report of what this one test catches;
a sibling test may be the one that trips. Both ADRs and `INVARIANT:` docstrings ratchet: nothing
prunes a record once its call is settled. Keeping them lean is a standing habit.

## Code Style

- Design principle: thin wrapper, small public surface. `httpware.__all__` is checked against an
  explicit expected set in `tests/test_public_api.py`, so a symbol cannot appear unnoticed
- `Http` is two letters in a class name (`AsyncClient`, not `ASYNCClient`); no `a` prefix on async
  methods, matching `httpx2` — `aclose()` is the sole exception
- Type suppressions are `# ty: ignore[<rule>]`, never `# type: ignore`: this project checks with
  `ty`, which silently accepts the latter without checking the rule
- Docstrings: public API documents the contract; internal helpers get a one-line contract, plus at
  most 1–2 lines for a genuinely non-obvious constraint. Never narrate implementation or justify
  code to a reviewer — cross-file rationale lives in an `INVARIANT:` test docstring or an ADR

## Agent skills

- **Issues and specs** — GitHub Issues on `modern-python/httpware`, via `gh`:
  [`docs/agents/issue-tracker.md`](docs/agents/issue-tracker.md)
- **Triage labels** — the five canonical roles: [`docs/agents/triage-labels.md`](docs/agents/triage-labels.md)
- **Domain docs** — single-context, `CONTEXT.md` + `docs/adr/`: [`docs/agents/domain.md`](docs/agents/domain.md)

---
status: shipped
date: 2026-06-14
slug: docs-ux-restructure
spec: docs-ux-restructure
pr: 60
---

# docs-ux-restructure — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps
> use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `README.md` a thin runnable front-door, keep `docs/index.md` as the
single canonical home, add a "Why httpware" hook, fix two nav nits, and scrub the
base-client mention — closing audit findings G1, G3, G4, nav, and G2 (won't-do).

**Spec:** [`design.md`](./design.md)

**Branch:** `docs/ux-restructure`

**Commit strategy:** Per-task commits; squash on merge via PR.

**No code touched** — this is docs only. "Verification" means `mkdocs build
--strict`, a live run of the one example, and `just lint` as a regression check.
There is no pytest for prose.

---

### Task 1: Create branch and commit the planning bundle

**Files:**
- Create: `planning/changes/active/.gitkeep` (already on disk, uncommitted)
- Create: `planning/changes/active/2026-06-14.01-docs-ux-restructure/design.md` (already on disk)
- Create: `planning/changes/active/2026-06-14.01-docs-ux-restructure/plan.md` (this file)

Get the design + plan under version control on a fresh branch before editing docs.

- [ ] **Step 1: Create the branch off the current main**

  ```bash
  git checkout main && git pull --ff-only origin main
  git checkout -b docs/ux-restructure
  ```

- [ ] **Step 2: Commit the bundle**

  ```bash
  git add planning/changes/active/.gitkeep \
          planning/changes/active/2026-06-14.01-docs-ux-restructure/
  git commit -m "docs(planning): add docs-ux-restructure design + plan

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 2: Scrub the base-client mention

**Files:**
- Modify: `CLAUDE.md` (the "Project Overview" sentence)

Remove the only live base-client reference. Frozen history (`retros/`, `archive/`,
`audits/`) is intentionally left alone.

- [ ] **Step 1: Edit the sentence**

  Find this text in `CLAUDE.md`:

  > It supersedes `community-of-python/base-client` and ships under the `modern-python` org. The framework is a thin opinionated wrapper around `httpx2`:

  Replace with:

  > It ships under the `modern-python` org and is a thin opinionated wrapper around `httpx2`:

- [ ] **Step 2: Verify no live base-client mention remains**

  Run: `grep -rin "base-client\|base_client" CLAUDE.md README.md docs/ architecture/`
  Expected: no matches (httpx2's own `BaseClient` class lives in `.venv`, which is not searched here).

- [ ] **Step 3: Commit**

  ```bash
  git add CLAUDE.md
  git commit -m "docs: remove base-client reference from project overview

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 3: Rewrite README.md to a thin front-door (G1 + G3 + G4)

**Files:**
- Modify: `README.md` (full rewrite below; badge block preserved verbatim)

Replace the dense intro + three duplicated quickstart sections + the full
observability table with: a 3-bullet "Why httpware", install, ONE runnable typed
quickstart, and a Documentation links section (absolute URLs — PyPI/GitHub render
without mkdocs).

- [ ] **Step 1: Overwrite `README.md` with exactly this content**

````markdown
# httpware

[![PyPI version](https://img.shields.io/pypi/v/httpware.svg)](https://pypi.org/project/httpware/)
[![Supported Python versions](https://img.shields.io/pypi/pyversions/httpware.svg)](https://pypi.org/project/httpware/)
[![Downloads](https://img.shields.io/pypi/dm/httpware.svg)](https://pypistats.org/packages/httpware)
[![Coverage](https://img.shields.io/badge/coverage-100%25-brightgreen.svg)](https://github.com/modern-python/httpware/actions/workflows/ci.yml)
[![CI](https://github.com/modern-python/httpware/actions/workflows/ci.yml/badge.svg)](https://github.com/modern-python/httpware/actions/workflows/ci.yml)
[![License](https://img.shields.io/github/license/modern-python/httpware.svg)](https://github.com/modern-python/httpware/blob/main/LICENSE)
[![GitHub stars](https://img.shields.io/github/stars/modern-python/httpware)](https://github.com/modern-python/httpware/stargazers)
[![Context7](https://img.shields.io/badge/Context7-docs-blue)](https://context7.com/modern-python/httpware)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![ty](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ty/main/assets/badge/v0.json)](https://github.com/astral-sh/ty)

**A Python HTTP client framework with sync and async clients for building resilient service clients.**

## Why httpware

- **Typed errors, no `raise_for_status()`** — 4xx/5xx automatically raise a status-keyed exception tree (`NotFoundError`, `RateLimitedError`, …), all under `httpware.StatusError`.
- **Typed response bodies** — `response_model=YourType` decodes the body straight to your pydantic or msgspec model; a missing decoder fails fast, *before* the request goes out.
- **Production resilience as composable middleware** — retry + retry-budget, bulkhead, circuit breaker, and timeout, composed at construction — all over standard `httpx2`.

Built on `httpx2`: httpware re-exports `httpx2.Request`/`httpx2.Response` and stays a thin wrapper, not a new HTTP abstraction.

> **Status:** Pre-1.0. Public API is subject to change between minor releases until v1.0.

## Install

```bash
pip install httpware                # core only — no decoder
pip install httpware[pydantic]      # + PydanticDecoder — BaseModel, dataclasses, primitives, generics
pip install httpware[msgspec]       # + MsgspecDecoder — Struct, dataclasses, primitives, generics
pip install httpware[pydantic,msgspec]   # both — BaseModel routes to pydantic, Struct to msgspec
pip install httpware[all]           # everything (pydantic, msgspec, otel)
```

## Quickstart

A typed GET against a live API (needs `pip install httpware[pydantic]`):

```python
import asyncio

from httpware import AsyncClient
from pydantic import BaseModel


class User(BaseModel):
    id: int
    name: str


async def main() -> None:
    async with AsyncClient(base_url="https://jsonplaceholder.typicode.com") as client:
        user = await client.get("/users/1", response_model=User)
        print(user.name)  # Leanne Graham


asyncio.run(main())
```

The sync `Client` is identical — swap `AsyncClient` → `Client` and drop the `await` / `async with`. A 4xx/5xx response raises a typed `StatusError`; a malformed body raises `DecodeError`. Both subclass `httpware.ClientError`.

## Documentation

Full guides live at **[httpware.modern-python.org](https://httpware.modern-python.org)**:

- **[Quickstart & observability](https://httpware.modern-python.org/)** — resilience middleware, streaming, and the stable logger/event contract.
- **[Middleware](https://httpware.modern-python.org/middleware/)** — write your own (auth, tracing, request-ID propagation).
- **[Resilience](https://httpware.modern-python.org/resilience/)** — retry + retry-budget, bulkhead, circuit breaker, timeout.
- **[Errors](https://httpware.modern-python.org/errors/)** — the exception tree and catching strategies.
- **[Testing](https://httpware.modern-python.org/testing/)** — `httpx2.MockTransport` injection.
- **[Recipes](https://httpware.modern-python.org/recipes/modern-di/)** — DI wiring, phase-decorator patterns, link-header pagination.

## 🗒️ [Release notes](https://github.com/modern-python/httpware/releases) · 📦 [PyPI](https://pypi.org/project/httpware) · 📝 [License](LICENSE)

## Part of `modern-python`

Browse the full list of templates and libraries in
[`modern-python`](https://github.com/modern-python) — see the org profile for the categorized index.
````

- [ ] **Step 2: Confirm the README has no relative `docs/` links and no leftover duplicated sections**

  Run: `grep -nE '\]\(docs/|## Observability|### With resilience|### Streaming' README.md`
  Expected: no matches.

- [ ] **Step 3: Commit**

  ```bash
  git add README.md
  git commit -m "docs: slim README to a runnable front-door (G1, G3, G4)

  Why-httpware hook, one runnable typed quickstart against jsonplaceholder,
  and a Documentation links section. Full quickstart/resilience/streaming/
  errors/observability detail now lives canonically in docs/index.md.

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 4: Add "Why httpware" to docs/index.md and make its leading example runnable (G1 + G4)

**Files:**
- Modify: `docs/index.md` (intro area + the "First request" async & sync examples)

`docs/index.md` stays the canonical full page; add the same value-prop hook and
fix the dead leading example. jsonplaceholder only serves users 1–10, so the path
must change to `/users/1`, not just the host.

- [ ] **Step 1: Insert the "Why httpware" block after the intro paragraph**

  Find (the intro paragraph + Status blockquote, lines ~3–5):

  ```markdown
  A Python HTTP client framework with sync and async clients for building resilient service clients. `httpware` is a thin opinionated wrapper around `httpx2` — it re-exports `httpx2.Request`/`httpx2.Response` as the public request/response surface, adds a middleware chain (with a built-in resilience suite: `AsyncRetry`/`Retry` + `RetryBudget`, `AsyncBulkhead`/`Bulkhead`), opt-in typed response decoding, and a status-keyed exception tree raised automatically on 4xx/5xx.

  > **Status:** Pre-1.0. Public API is subject to change between minor releases until v1.0.
  ```

  Replace with:

  ```markdown
  A Python HTTP client framework with sync and async clients for building resilient service clients. `httpware` is a thin opinionated wrapper around `httpx2` — it re-exports `httpx2.Request`/`httpx2.Response` as the public request/response surface, adds a middleware chain (with a built-in resilience suite: `AsyncRetry`/`Retry` + `RetryBudget`, `AsyncBulkhead`/`Bulkhead`), opt-in typed response decoding, and a status-keyed exception tree raised automatically on 4xx/5xx.

  ## Why httpware

  - **Typed errors, no `raise_for_status()`** — 4xx/5xx automatically raise a status-keyed exception tree (`NotFoundError`, `RateLimitedError`, …), all under `httpware.StatusError`.
  - **Typed response bodies** — `response_model=YourType` decodes the body straight to your pydantic or msgspec model; a missing decoder fails fast, *before* the request goes out.
  - **Production resilience as composable middleware** — retry + retry-budget, bulkhead, circuit breaker, and timeout, composed at construction — all over standard `httpx2`.

  > **Status:** Pre-1.0. Public API is subject to change between minor releases until v1.0.
  ```

- [ ] **Step 2: Make the async leading example runnable**

  Find:

  ```python
      async with AsyncClient(base_url="https://example.test") as client:
          response = await client.get("/users/42")
  ```

  Replace with:

  ```python
      async with AsyncClient(base_url="https://jsonplaceholder.typicode.com") as client:
          response = await client.get("/users/1")
  ```

- [ ] **Step 3: Make the sync leading example runnable**

  Find:

  ```python
  with Client(base_url="https://example.test") as client:
      response = client.get("/users/42")
  ```

  Replace with:

  ```python
  with Client(base_url="https://jsonplaceholder.typicode.com") as client:
      response = client.get("/users/1")
  ```

- [ ] **Step 4: Confirm the leading examples no longer use the dead host**

  Run: `sed -n '20,50p' docs/index.md | grep -nE 'example.test|/users/42'`
  Expected: no matches. (Note: `docs/testing.md` keeps `example.test` — those are MockTransport examples with no real network, intentionally left.)

- [ ] **Step 5: Commit**

  ```bash
  git add docs/index.md
  git commit -m "docs: add why-httpware hook and a runnable first example (G1, G4)

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 5: Reorder mkdocs nav — Middleware before Resilience (nav nit)

**Files:**
- Modify: `mkdocs.yml` (the `nav:` block)

Resilience is built on the middleware chain and forward-references it, so
Middleware should come first.

- [ ] **Step 1: Edit the nav order**

  Find:

  ```yaml
  nav:
    - Quick-Start: index.md
    - Resilience: resilience.md
    - Middleware: middleware.md
    - Errors: errors.md
  ```

  Replace with:

  ```yaml
  nav:
    - Quick-Start: index.md
    - Middleware: middleware.md
    - Resilience: resilience.md
    - Errors: errors.md
  ```

- [ ] **Step 2: Commit**

  ```bash
  git add mkdocs.yml
  git commit -m "docs: order Middleware before Resilience in nav

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 6: Link the bare architecture/*.md references (nav nit)

**Files:**
- Modify: `docs/middleware.md` (two spots), `docs/errors.md`, `docs/resilience.md`, `docs/testing.md`

On the published site `architecture/` is not built, so these bare inline-code
paths render as unclickable dead ends. Convert each to an absolute GitHub source
link (matching the pattern `docs/index.md` already uses).

- [ ] **Step 1: `docs/middleware.md` — the inline "See" reference**

  Find: `See `architecture/middleware.md`.`
  Replace with: `See [`architecture/middleware.md`](https://github.com/modern-python/httpware/blob/main/architecture/middleware.md).`

- [ ] **Step 2: `docs/middleware.md` — the "see also" bullet**

  Find: `- **`architecture/middleware.md` (Seam A)** — the formal protocol contract and why the chain is frozen at construction.`
  Replace with: `- **[`architecture/middleware.md`](https://github.com/modern-python/httpware/blob/main/architecture/middleware.md) (Seam A)** — the formal protocol contract and why the chain is frozen at construction.`

- [ ] **Step 3: `docs/errors.md`**

  Find: `- **`architecture/errors.md`** — the formal exception contract.`
  Replace with: `- **[`architecture/errors.md`](https://github.com/modern-python/httpware/blob/main/architecture/errors.md)** — the formal exception contract.`

- [ ] **Step 4: `docs/resilience.md`**

  Find: `- **`architecture/middleware.md`** — the formal Middleware/Seam-A contract.`
  Replace with: `- **[`architecture/middleware.md`](https://github.com/modern-python/httpware/blob/main/architecture/middleware.md)** — the formal Middleware/Seam-A contract.`

- [ ] **Step 5: `docs/testing.md`**

  Find: `- **`architecture/testing.md`** — the project's own testing patterns (Hypothesis property-based tests, `pytest-asyncio` auto-mode, the `RecordedTransport`-was-removed history).`
  Replace with: `- **[`architecture/testing.md`](https://github.com/modern-python/httpware/blob/main/architecture/testing.md)** — the project's own testing patterns (Hypothesis property-based tests, `pytest-asyncio` auto-mode, the `RecordedTransport`-was-removed history).`

- [ ] **Step 6: Verify no bare architecture path remains in published pages**

  Run: `grep -rnE '`architecture/[a-z]+\.md`' docs/*.md | grep -v 'github.com'`
  Expected: no matches.

- [ ] **Step 7: Commit**

  ```bash
  git add docs/middleware.md docs/errors.md docs/resilience.md docs/testing.md
  git commit -m "docs: link bare architecture/*.md references to GitHub source

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 7: Verify the whole change, update audit + Index, commit

**Files:**
- Modify: `planning/audits/2026-06-13-docs-audit.md` (mark G1/G3/G4/nav resolved, G2 won't-do)
- Modify: `planning/README.md` (add the bundle to the Index "Active")

- [ ] **Step 1: Strict docs build**

  ```bash
  uv run --with-requirements docs/requirements.txt mkdocs build --strict && rm -rf site
  ```
  Expected: `Documentation built in …s` with no warnings/errors.

- [ ] **Step 2: Run the README quickstart for real**

  ```bash
  uv run --with pydantic python - <<'PY'
  import asyncio
  from httpware import AsyncClient
  from pydantic import BaseModel

  class User(BaseModel):
      id: int
      name: str

  async def main() -> None:
      async with AsyncClient(base_url="https://jsonplaceholder.typicode.com") as client:
          print(await client.get("/users/1", response_model=User))

  asyncio.run(main())
  PY
  ```
  Expected: `id=1 name='Leanne Graham'` (requires network).

- [ ] **Step 3: Lint regression check**

  Run: `just lint`
  Expected: all checks pass (no source touched).

- [ ] **Step 4: Mark the audit findings resolved**

  In `planning/audits/2026-06-13-docs-audit.md`, under the onboarding/UX list, append `**Resolved** (2026-06-14.01)` to **G1**, **G3**, **G4**, and the navigation-nits paragraph. For **G2**, append: `**Won't do** (2026-06-14.01) — base-client scrubbed from CLAUDE.md; no migration guide.` Leave **G6** open.

- [ ] **Step 5: Add the bundle to the planning Index**

  In `planning/README.md`, under `### Active`, replace `_None._` with:

  ```markdown
  - **[docs-ux-restructure](changes/active/2026-06-14.01-docs-ux-restructure/design.md)** (draft, 2026-06-14) — Thin README front-door + canonical `docs/index.md`, why-httpware hook (G1), runnable first example (G4), nav nits, base-client scrub. G2 dropped, G6 deferred.
  ```

- [ ] **Step 6: Commit**

  ```bash
  git add planning/audits/2026-06-13-docs-audit.md planning/README.md
  git commit -m "docs(planning): mark docs-UX findings resolved + index the bundle

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

- [ ] **Step 7: Push and open the PR**

  ```bash
  git push -u origin docs/ux-restructure
  gh pr create --base main --head docs/ux-restructure \
    --title "docs: UX restructure — thin README, canonical site, runnable example" \
    --body "Closes audit findings G1, G3, G4, nav nits; G2 dropped (base-client scrubbed). See planning/changes/active/2026-06-14.01-docs-ux-restructure/. mkdocs --strict + live example run + just lint all green."
  ```

---

## Notes for the executor

- **Don't touch `docs/testing.md`'s `example.test`** — those are `MockTransport`
  examples; the host is never dialed.
- **README links must be absolute** (`https://httpware.modern-python.org/…`) — PyPI
  renders the README without mkdocs, so relative `docs/…` links 404 there.
- The `architecture/*.md` files are **not** part of the mkdocs build; that's why
  they're linked to GitHub, not cross-linked in-site.

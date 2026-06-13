---
status: shipped
date: 2026-06-06
slug: modern-di-recipe
spec: modern-di-recipe
pr: 29
---

# `modern-di` recipe + `AsyncClient.aclose()` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `httpware.AsyncClient.aclose()` and ship a setup-friction recipe page at `docs/recipes/modern-di.md` showing how to wire `AsyncClient` into a `modern-di` container.

**Architecture:** Two thin pieces in one PR. (1) A standalone `aclose()` method on `AsyncClient` (mirrors the body of `__aexit__`, idempotent via the existing `_owns_client` + `is_closed` guards). (2) A new `docs/recipes/modern-di.md` page in linear-narrative form — minimal wire → multi-backend collision → wrapper-subclass fix → middleware composition — plus a small `mkdocs.yml` nav update and one back-link from `docs/index.md`. The two pieces are bundled because the recipe's `finalizer=AsyncClient.aclose` reads as a clean one-liner; without the method it would have to call `__aexit__(None, None, None)` directly, which signals a library gap.

**Tech Stack:** Python 3.11+, `httpx2`, `modern-di` (recipe only — not a project dependency), `pytest` + `pytest-asyncio` auto-mode, `ruff`, `ty`, `mkdocs` + `mkdocs-material`. Task runner: `just`. Package manager: `uv`.

**Spec:** `planning/specs/2026-06-06-modern-di-recipe-design.md` — commit `a2c1fbc`.

**Note on a spec-vs-tree discrepancy:** the spec says new tests go in `tests/test_client.py`. That file does not exist — tests in this project are split per concern. The actual home for the new tests is `tests/test_client_lifecycle.py`. This plan uses the correct path throughout.

---

## File structure

| Path | Action | Responsibility |
|---|---|---|
| `src/httpware/client.py` | Modify | Add `async def aclose(self)` to `AsyncClient` |
| `tests/test_client_lifecycle.py` | Modify | Add two new tests covering `aclose()` |
| `docs/recipes/` | Create (dir) | New folder for setup-friction recipes |
| `docs/recipes/modern-di.md` | Create | The recipe page itself |
| `mkdocs.yml` | Modify | Add `Recipes` nav section |
| `docs/index.md` | Modify | Add one bullet under "Where to go next" |

No new test file is created — the existing `test_client_lifecycle.py` already groups the lifecycle tests by concern and the new tests fit naturally beside `test_aexit_*`.

---

## Task 1: Add `AsyncClient.aclose()` with TDD

**Files:**
- Modify: `src/httpware/client.py:768-770` (existing `__aexit__` body) — add new `aclose()` method directly after line 770
- Modify: `tests/test_client_lifecycle.py:33` (end of file) — append two new tests

- [ ] **Step 1: Add the first failing test — `test_aclose_closes_owned_httpx2_client`**

Append to `tests/test_client_lifecycle.py` (after the existing `test_aexit_is_idempotent_for_owned_client`):

```python


async def test_aclose_closes_owned_httpx2_client() -> None:
    client = AsyncClient()
    await client.aclose()
    assert client._httpx2_client.is_closed  # noqa: SLF001
```

- [ ] **Step 2: Run it — confirm it fails for the right reason**

```bash
uv run pytest tests/test_client_lifecycle.py::test_aclose_closes_owned_httpx2_client -v
```

Expected: `FAILED ... AttributeError: 'AsyncClient' object has no attribute 'aclose'`.

If the failure is anything else (e.g., import error, fixture problem), stop and resolve before proceeding.

- [ ] **Step 3: Add the second failing test — `test_aclose_is_idempotent_for_owned_client`**

Append to `tests/test_client_lifecycle.py`:

```python


async def test_aclose_is_idempotent_for_owned_client() -> None:
    client = AsyncClient()
    await client.aclose()
    # Second call must not raise — the boolean prevents a double-close on httpx2 internals.
    await client.aclose()
    assert client._httpx2_client.is_closed  # noqa: SLF001
```

- [ ] **Step 4: Run both new tests — confirm both fail**

```bash
uv run pytest tests/test_client_lifecycle.py -v -k "test_aclose"
```

Expected: both `test_aclose_closes_owned_httpx2_client` and `test_aclose_is_idempotent_for_owned_client` FAIL with `AttributeError: 'AsyncClient' object has no attribute 'aclose'`.

- [ ] **Step 5: Add the `aclose()` method to `AsyncClient`**

In `src/httpware/client.py`, after the existing `__aexit__` method (which ends at line 770 with `await self._httpx2_client.aclose()`), append:

```python

    async def aclose(self) -> None:
        """Close the underlying httpx2 client if we own it.

        Idempotent — safe to call after ``__aexit__`` or another ``aclose()`` call.
        Use this when the client is not managed by ``async with`` (e.g., wired
        into a DI container's lifecycle).
        """
        if self._owns_client and not self._httpx2_client.is_closed:
            await self._httpx2_client.aclose()
```

Insertion point: directly under the closing line of `__aexit__`. The new method becomes the final method of `AsyncClient`.

- [ ] **Step 6: Run the two new tests — confirm both pass**

```bash
uv run pytest tests/test_client_lifecycle.py -v -k "test_aclose"
```

Expected: both PASS.

- [ ] **Step 7: Run the full test_client_lifecycle.py file — confirm nothing else broke**

```bash
uv run pytest tests/test_client_lifecycle.py -v
```

Expected: all 5 tests PASS (3 existing `test_aexit_*` + 2 new `test_aclose_*`).

- [ ] **Step 8: Run the full lint pipeline**

```bash
just lint
```

Expected: clean — no ruff or `ty` errors.

If ty flags an issue with the new method (e.g., missing return type), fix it inline rather than suppressing.

- [ ] **Step 9: Run the full test suite — confirm no other test relied on `aclose` NOT existing**

```bash
just test
```

Expected: all tests PASS. Coverage of `src/httpware/client.py` should increase by the body of `aclose()` (a handful of lines).

- [ ] **Step 10: Commit**

```bash
git add src/httpware/client.py tests/test_client_lifecycle.py
git commit -m "$(cat <<'EOF'
feat(client): add AsyncClient.aclose() standalone teardown

Mirrors the body of __aexit__: closes the underlying httpx2 client iff
we own it and it isn't already closed. Idempotent.

Use case: DI containers, background workers, anything not request-shaped
that can't lean on `async with`. Aligns the library with its own CLAUDE.md
naming convention which already names aclose() as the sole a-prefixed
method exception.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Write the `modern-di` recipe page + nav + back-link

**Files:**
- Create: `docs/recipes/modern-di.md`
- Modify: `mkdocs.yml` (the `nav:` block)
- Modify: `docs/index.md` (the "Where to go next" section)

- [ ] **Step 1: Create the recipe page**

Write `docs/recipes/modern-di.md` with the full content below.

````markdown
# Wiring `AsyncClient` into `modern-di`

If you wire your app's dependencies with [`modern-di`](https://modern-di.modern-python.org/) and want connection-pool teardown and middleware composition to flow through the container's lifecycle, this is the bridge. Both libraries ship under the [`modern-python`](https://github.com/modern-python) org.

## The minimal wire-up

```python
from modern_di import Container, Group, Scope, providers

from httpware import AsyncClient


class ServiceClients(Group):
    api = providers.Factory(
        scope=Scope.APP,
        creator=AsyncClient,
        kwargs={"base_url": "https://api.example.com"},
        cache_settings=providers.CacheSettings(finalizer=AsyncClient.aclose),
    )


async def main() -> None:
    async with Container(scope=Scope.APP, groups=[ServiceClients]) as container:
        client = await container.resolve(AsyncClient)
        response = await client.get("/users/1")
        print(response.status_code)
```

Breaking that down:

- **`Scope.APP`** ties the client to the application lifetime. One client per process; the connection pool is reused across all calls.
- **`cache_settings=providers.CacheSettings(...)`** is what makes the provider a singleton. Without it, `Factory` returns a fresh `AsyncClient` on every resolve.
- **`finalizer=AsyncClient.aclose`** is the unbound async method. `modern-di` detects it as a coroutine function (via `inspect.iscoroutinefunction`) and `await`s it on container teardown.

A common first instinct here is `finalizer=lambda c: c.aclose()`. **That does not work** — the lambda itself is sync, so `modern-di` calls it synchronously and discards the returned coroutine unawaited. The underlying connection pool leaks. Pass the unbound async method directly, or wrap in `async def`.

See the [`modern-di` factories docs](https://modern-di.modern-python.org/providers/factories/) for the broader `CacheSettings` story (scopes, `clear_cache`, sync vs async finalizers).

## Adding a second backend hits a type collision

The obvious move when you talk to a second backend — register another `Factory(creator=AsyncClient, ...)` — fails at container construction:

```python
class ServiceClients(Group):
    user_api = providers.Factory(
        scope=Scope.APP,
        creator=AsyncClient,
        kwargs={"base_url": "https://users.example.com"},
        cache_settings=providers.CacheSettings(finalizer=AsyncClient.aclose),
    )
    billing_api = providers.Factory(
        scope=Scope.APP,
        creator=AsyncClient,
        kwargs={"base_url": "https://billing.example.com"},
        cache_settings=providers.CacheSettings(finalizer=AsyncClient.aclose),
    )

# At Container(...) construction:
# modern_di.exceptions.DuplicateProviderTypeError: AsyncClient is already registered
```

`modern-di` resolves dependencies by `bound_type`, which defaults to the creator's return type. Both providers default to `bound_type=AsyncClient` and collide in the providers registry.

## Fix: one wrapper subclass per backend

Give each provider a distinct `bound_type` by subclassing `AsyncClient`:

```python
from modern_di import Container, Group, Scope, providers

from httpware import AsyncClient


class UserApi(AsyncClient):
    """Typing handle for the User service backend."""


class BillingApi(AsyncClient):
    """Typing handle for the Billing service backend."""


class ServiceClients(Group):
    user_api = providers.Factory(
        scope=Scope.APP,
        creator=UserApi,
        kwargs={"base_url": "https://users.example.com"},
        cache_settings=providers.CacheSettings(finalizer=UserApi.aclose),
    )
    billing_api = providers.Factory(
        scope=Scope.APP,
        creator=BillingApi,
        kwargs={"base_url": "https://billing.example.com"},
        cache_settings=providers.CacheSettings(finalizer=BillingApi.aclose),
    )


async def main() -> None:
    async with Container(scope=Scope.APP, groups=[ServiceClients]) as container:
        users = await container.resolve(UserApi)
        billing = await container.resolve(BillingApi)
        # ... use them
```

A couple of notes:

- Subclasses are **typing-only**. Empty body, no overrides. They inherit `__init__`, `aclose`, and every HTTP method unchanged.
- Each `Factory` now has a distinct `bound_type`, so `container.resolve(UserApi)` and `container.resolve(BillingApi)` route to the right provider.
- `modern-di`'s error suggestions are subclass-aware. If a caller asks for `container.resolve(AsyncClient)` after only the subclasses are registered, the error message points them at the right subclass.

## Middleware in `kwargs=`

`AsyncClient`'s middleware chain is composed once at construction and frozen for the client's lifetime. With a singleton-scoped `Factory`, "once at construction" means "once per container build." Drop the middleware list into `kwargs=`:

```python
from httpware import AsyncClient, Bulkhead, Retry


class ServiceClients(Group):
    user_api = providers.Factory(
        scope=Scope.APP,
        creator=UserApi,
        kwargs={
            "base_url": "https://users.example.com",
            "middleware": [Bulkhead(max_concurrent=10), Retry()],
        },
        cache_settings=providers.CacheSettings(finalizer=UserApi.aclose),
    )
```

Each cached singleton owns its own `Bulkhead` and `Retry` state — what you want when different backends have different reliability profiles.

## See also

- **[Quick-Start](../index.md)** — the base `AsyncClient` API.
- **[Middleware guide](../middleware.md)** — what `Bulkhead` and `Retry` are doing in `kwargs[middleware]`.
- **[Resilience reference](../resilience.md)** — every parameter on `Retry`, `RetryBudget`, `Bulkhead`.
- **[`modern-di` factories](https://modern-di.modern-python.org/providers/factories/)** — `CacheSettings`, scopes, the broader provider story.
````

- [ ] **Step 2: Update `mkdocs.yml` to add the `Recipes` nav section**

Open `mkdocs.yml`. The existing `nav:` block is:

```yaml
nav:
  - Quick-Start: index.md
  - Resilience: resilience.md
  - Middleware: middleware.md
  - Errors: errors.md
  - Testing: testing.md
  - Development:
      - Contributing: dev/contributing.md
```

Replace it with:

```yaml
nav:
  - Quick-Start: index.md
  - Resilience: resilience.md
  - Middleware: middleware.md
  - Errors: errors.md
  - Testing: testing.md
  - Recipes:
      - modern-di: recipes/modern-di.md
  - Development:
      - Contributing: dev/contributing.md
```

- [ ] **Step 3: Update `docs/index.md` "Where to go next" with a recipe back-link**

In `docs/index.md`, locate the `## Where to go next` section. The current bullets are:

```markdown
- **[Resilience reference](resilience.md)** — every parameter on `Retry`, `RetryBudget`, and `Bulkhead`; the retry-rule matrix; Retry-After parsing; budget sharing.
- **[Middleware guide](middleware.md)** — write your own middleware. Covers the Middleware Protocol, the phase decorators, a worked Request-ID propagation example, and OpenTelemetry wiring.
- **[Errors reference](errors.md)** — the full exception tree, catching strategies, `exc.response.*` access pattern.
- **[Testing guide](testing.md)** — mock-transport injection pattern for testing code that uses `httpware`.
- **[Engineering Notes](https://github.com/modern-python/httpware/blob/main/planning/engineering.md)** — design invariants, the three protocol seams, exception contract, module layout, testing patterns, optional-extras pattern. Lives in the repo at `planning/engineering.md`.
- **[Contributing](dev/contributing.md)** — setup, conventions, workflow.
- **[Release notes](https://github.com/modern-python/httpware/releases)** — per-version changelogs.
```

Insert a new bullet between **Testing guide** and **Engineering Notes**:

```markdown
- **[Recipes](recipes/modern-di.md)** — wiring `AsyncClient` into a `modern-di` container.
```

Final section after the edit:

```markdown
- **[Resilience reference](resilience.md)** — ...
- **[Middleware guide](middleware.md)** — ...
- **[Errors reference](errors.md)** — ...
- **[Testing guide](testing.md)** — mock-transport injection pattern for testing code that uses `httpware`.
- **[Recipes](recipes/modern-di.md)** — wiring `AsyncClient` into a `modern-di` container.
- **[Engineering Notes](https://github.com/modern-python/httpware/blob/main/planning/engineering.md)** — ...
- **[Contributing](dev/contributing.md)** — setup, conventions, workflow.
- **[Release notes](https://github.com/modern-python/httpware/releases)** — per-version changelogs.
```

- [ ] **Step 4: Build the docs site with `--strict` to catch broken links**

```bash
uv run --with mkdocs --with mkdocs-material mkdocs build --strict
```

Expected: build completes with no warnings. `--strict` turns broken intra-site links and ambiguous references into errors.

If it fails: most likely a relative link target. Verify:
- `../index.md`, `../middleware.md`, `../resilience.md` exist relative to `docs/recipes/modern-di.md` — they do; `docs/` is the docs root.
- `recipes/modern-di.md` from `docs/index.md` resolves — it does.

- [ ] **Step 5: Eyeball the rendered page locally**

```bash
uv run --with mkdocs --with mkdocs-material mkdocs serve
```

Open `http://127.0.0.1:8000/recipes/modern-di/` in a browser. Check:
- The "Recipes" section appears in the left nav with `modern-di` under it.
- Code blocks render syntax-highlighted.
- All "See also" links work.
- The new bullet on the index page links to the recipe.

Kill the server with Ctrl+C when satisfied.

- [ ] **Step 6: Commit**

```bash
git add docs/recipes/modern-di.md mkdocs.yml docs/index.md
git commit -m "$(cat <<'EOF'
docs(recipes): add modern-di setup-friction recipe

Linear-narrative walk-through of wiring AsyncClient into a modern-di
container: minimal Factory + finalizer → multi-backend type collision
(DuplicateProviderTypeError) → per-backend wrapper-subclass fix →
middleware in kwargs.

Adds a new top-level "Recipes" nav section (single item for now) and
one back-link from the index's "Where to go next".

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: End-to-end verification of the recipe sample

**Files:**
- Create (scratch, not committed): `/tmp/verify_modern_di_recipe.py`

This task is verification-only — no source changes, no commit. It confirms the recipe's claims actually hold against the current code.

- [ ] **Step 1: Write the verification script**

Create `/tmp/verify_modern_di_recipe.py` (the repo's `tests/` directory is reserved for the formal test suite; this is a one-off check, not a regression test):

```python
"""End-to-end check that the modern-di recipe in docs/recipes/modern-di.md
actually wires AsyncClient.aclose into Container teardown."""

import asyncio

from modern_di import Container, Group, Scope, providers

from httpware import AsyncClient


class ServiceClients(Group):
    api = providers.Factory(
        scope=Scope.APP,
        creator=AsyncClient,
        kwargs={"base_url": "https://api.example.test"},
        cache_settings=providers.CacheSettings(finalizer=AsyncClient.aclose),
    )


async def main() -> None:
    captured: AsyncClient | None = None
    async with Container(scope=Scope.APP, groups=[ServiceClients]) as container:
        captured = await container.resolve(AsyncClient)
        assert captured._httpx2_client.is_closed is False, "client should be open during scope"
    assert captured is not None
    assert captured._httpx2_client.is_closed is True, "finalizer should have closed the client"
    print("OK: container teardown invoked AsyncClient.aclose; underlying httpx2 client is closed.")


asyncio.run(main())
```

- [ ] **Step 2: Run it**

```bash
uv run --with modern-di python /tmp/verify_modern_di_recipe.py
```

Expected output: `OK: container teardown invoked AsyncClient.aclose; underlying httpx2 client is closed.`

If the assertions fire:
- "client should be open during scope" → the finalizer fired too early (a `modern-di` bug or a scope misconfiguration); flag the issue, don't paper over it.
- "finalizer should have closed the client" → the finalizer wasn't awaited. Most likely cause: `aclose` was passed as something other than an unbound async method, or `inspect.iscoroutinefunction(AsyncClient.aclose)` returns `False` (which would mean `aclose` isn't `async def` — check `client.py`).

- [ ] **Step 3: Run the multi-backend variation**

Replace the body of `/tmp/verify_modern_di_recipe.py` with the wrapper-subclass form to confirm the collision-fix actually resolves to distinct providers:

```python
"""End-to-end check for the multi-backend wrapper-subclass form."""

import asyncio

from modern_di import Container, Group, Scope, providers

from httpware import AsyncClient


class UserApi(AsyncClient):
    pass


class BillingApi(AsyncClient):
    pass


class ServiceClients(Group):
    user_api = providers.Factory(
        scope=Scope.APP,
        creator=UserApi,
        kwargs={"base_url": "https://users.example.test"},
        cache_settings=providers.CacheSettings(finalizer=UserApi.aclose),
    )
    billing_api = providers.Factory(
        scope=Scope.APP,
        creator=BillingApi,
        kwargs={"base_url": "https://billing.example.test"},
        cache_settings=providers.CacheSettings(finalizer=BillingApi.aclose),
    )


async def main() -> None:
    captured_user: UserApi | None = None
    captured_billing: BillingApi | None = None
    async with Container(scope=Scope.APP, groups=[ServiceClients]) as container:
        captured_user = await container.resolve(UserApi)
        captured_billing = await container.resolve(BillingApi)
        assert isinstance(captured_user, UserApi)
        assert isinstance(captured_billing, BillingApi)
        assert captured_user is not captured_billing
    assert captured_user is not None and captured_billing is not None
    assert captured_user._httpx2_client.is_closed is True
    assert captured_billing._httpx2_client.is_closed is True
    print("OK: two backends resolve to distinct subclass instances; both finalizers ran.")


asyncio.run(main())
```

```bash
uv run --with modern-di python /tmp/verify_modern_di_recipe.py
```

Expected: `OK: two backends resolve to distinct subclass instances; both finalizers ran.`

- [ ] **Step 4: Confirm the collision claim — the documented error actually fires**

Replace the script body once more, this time with the broken form from the recipe's collision section:

```python
"""End-to-end check that the documented DuplicateProviderTypeError actually fires."""

from modern_di import Container, Group, Scope, providers

from httpware import AsyncClient


class ServiceClients(Group):
    user_api = providers.Factory(
        scope=Scope.APP,
        creator=AsyncClient,
        kwargs={"base_url": "https://users.example.test"},
        cache_settings=providers.CacheSettings(finalizer=AsyncClient.aclose),
    )
    billing_api = providers.Factory(
        scope=Scope.APP,
        creator=AsyncClient,
        kwargs={"base_url": "https://billing.example.test"},
        cache_settings=providers.CacheSettings(finalizer=AsyncClient.aclose),
    )


try:
    Container(scope=Scope.APP, groups=[ServiceClients])
except Exception as exc:  # noqa: BLE001 - we want the exact class name
    print(f"OK: collision raised {type(exc).__module__}.{type(exc).__name__}: {exc}")
else:
    raise SystemExit("FAIL: expected DuplicateProviderTypeError, got no error")
```

```bash
uv run --with modern-di python /tmp/verify_modern_di_recipe.py
```

Expected: a line starting `OK: collision raised modern_di.exceptions.DuplicateProviderTypeError: ...`.

If the exception name or fully-qualified path differs from what the recipe's "At `Container(...)` construction" comment shows, update the recipe text to match exactly. This is a docs-accuracy gate.

- [ ] **Step 5: Final cleanup and full repo health check**

```bash
rm /tmp/verify_modern_di_recipe.py
just lint
just test
uv run --with mkdocs --with mkdocs-material mkdocs build --strict
```

All four commands must succeed. If `mkdocs build --strict` warns about anything, fix it before declaring the work done.

- [ ] **Step 6: No commit for this task**

This task produced no source changes — it was verification only. Move on to PR creation per the user's normal workflow.

---

## Self-review notes

- **Spec coverage:**
  - `aclose()` method on `AsyncClient` → Task 1 Step 5.
  - Two tests for `aclose()` → Task 1 Steps 1 and 3.
  - `docs/recipes/modern-di.md` with all six spec sections → Task 2 Step 1.
  - `mkdocs.yml` nav update → Task 2 Step 2.
  - `docs/index.md` "Where to go next" bullet → Task 2 Step 3.
  - "Local run of the Section 2 minimal-wire sample" acceptance criterion → Task 3 Step 2.
  - `mkdocs build --strict` acceptance criterion → Task 2 Step 4 and Task 3 Step 5.
  - All spec-listed exclusions (modern-di primer, Gateway example, FastAPI/Litestar coverage, back-links from other reference pages, back-link from modern-di repo) → respected by omission.

- **Type consistency:** `AsyncClient.aclose` is referenced identically in the source (Task 1 Step 5), the recipe sample finalizer (Task 2 Step 1), and the verification script (Task 3 Step 1). `UserApi`, `BillingApi` names match across recipe and verification script.

- **Naming:** test names follow the existing `test_aexit_*` pattern in `test_client_lifecycle.py` — `test_aclose_closes_owned_httpx2_client` and `test_aclose_is_idempotent_for_owned_client`. Spec used slightly looser names; plan tightened them to the existing convention.

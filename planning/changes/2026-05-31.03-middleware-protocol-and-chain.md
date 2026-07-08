---
summary: Shipped in 0.1.0; survived the v0.2 pivot
---

# Middleware protocol and chain composition (design)

- **Date:** 2026-05-31
- **Status:** approved, ready for plan
- **Scope:** Story 2-1 (first story of Epic 2). Defines the `Middleware` Protocol, `Next` type alias, and the `compose()` chain composer. Out of scope: decorators (2-2), `Request` helpers (2-3), auth coercion (2-4), AsyncClient wiring (2-5), streaming middleware chain (Epic 4).
- **Roadmap pointer:** `docs/dev/engineering.md` §8 "Epic 2 — Compose request-handling logic via middleware".

## Why

Epic 2 makes `httpware` extensible: consumers write middleware to add tracing, signing, correlation IDs, etc., and built-in resilience (retry, bulkhead, timeout) lives on the same axis. Story 2-1 is the foundation — it ships the protocol surface, the `Next` callable type, and the composition mechanism. Nothing else in Epic 2 can land until this seam (Seam 2: `AsyncClient ↔ Middleware`) is defined.

The shape is essentially decided by the archived architecture document (`docs/archive/architecture.md` "Middleware Execution Model"): a recursive async-callable onion. This spec ports that design forward with a few small choices that the archive left open.

## Decisions

| Decision | Choice |
| --- | --- |
| Protocol shape | `@runtime_checkable Protocol` with `async def __call__(self, request: Request, next: Next) -> Response`. Matches `Transport` and `ResponseDecoder`. |
| `Next` type | `Next: TypeAlias = Callable[[Request], Awaitable[Response]]`. PEP 695 `type Next = ...` would require 3.12+; project floor is 3.11. |
| Composition | Recursive closure fold via `_internal/chain.compose(middlewares, transport) -> Next`. Bottom of chain is `transport.__call__` (bound method, no wrapper). |
| Empty list | `compose([], transport)` returns `transport.__call__` directly (identity at the bottom). |
| Sequence type | `Sequence[Middleware]` over `list[Middleware]` — accepts tuples; no mutation required. |
| Cancellation | No `try`/`except` blocks in `compose` or `_wrap`; `CancelledError` and all other exceptions propagate untouched. Verified by test. |
| Scope | Strict epic boundary. Stories 2-2 through 2-5 land as their own units. |
| Public exports | Both `httpware.middleware.{Middleware, Next}` and `httpware.{Middleware, Next}`. Matches the existing `Request` / `Response` / `Httpx2Transport` re-export pattern at package root. |
| `compose` visibility | Private (`_internal/chain.compose`). Consumers don't compose chains; AsyncClient (Story 2-5) does. |

## File structure

**New files:**

```
src/httpware/
├── middleware/
│   └── __init__.py            # Middleware Protocol + Next type alias (~25 lines)
└── _internal/
    ├── __init__.py            # empty marker
    └── chain.py               # compose() + private _wrap() (~30 lines)
```

**Modified files:**

```
src/httpware/__init__.py       # re-export Middleware, Next at package root
```

**New tests:**

```
tests/test_middleware.py       # protocol surface + chain composition (~11 tests)
```

**Files not touched:** `request.py`, `response.py`, `errors.py`, `config.py`, `transports/`, `decoders/`. Story 2-1 is purely additive.

## Protocol surface

`src/httpware/middleware/__init__.py`:

```python
"""Middleware protocol — the AsyncClient ↔ Middleware seam (Seam 2)."""

from collections.abc import Awaitable, Callable
from typing import Protocol, TypeAlias, runtime_checkable

from httpware.request import Request
from httpware.response import Response


Next: TypeAlias = Callable[[Request], Awaitable[Response]]


@runtime_checkable
class Middleware(Protocol):
    """Structural protocol every middleware satisfies.

    A middleware receives the incoming `Request` and a `Next` callable. It may
    inspect/transform the request, await `next(request)` to forward to the rest
    of the chain (eventually the transport), inspect/transform the returned
    `Response`, short-circuit by returning a `Response` without calling `next`,
    or raise.
    """

    async def __call__(self, request: Request, next: Next) -> Response:
        """Process `request`; call `next(request)` to forward, or synthesize a Response."""
        ...


__all__ = ["Middleware", "Next"]
```

Notes:
- `next` shadows the Python builtin in the method body. Standard for this pattern (ASGI convention). Implementers may name the parameter whatever they want; structural typing matches by position and type, not name.
- `@runtime_checkable` mirrors the other two structural protocols in the codebase (`Transport`, `ResponseDecoder`). Enables `isinstance(obj, Middleware)` for AsyncClient's per-construction validation in Story 2-5. The deferred-work entry on `_ProtocolMeta.__instancecheck__` µs-cost applies only if validation runs per-request; per-construction is fine.

## Chain composition

`src/httpware/_internal/chain.py`:

```python
"""Middleware chain composition — wires a middleware list against a Transport.

Private helper. AsyncClient calls `compose` at construction time and stores the
returned `Next` callable; per-request dispatch awaits that callable.
"""

from collections.abc import Sequence

from httpware.middleware import Middleware, Next
from httpware.request import Request
from httpware.response import Response
from httpware.transports import Transport


def compose(middlewares: Sequence[Middleware], transport: Transport) -> Next:
    """Fold `middlewares` into a single `Next` callable terminating at `transport`.

    The outermost middleware in the input sequence is the first to receive the
    request; its `next` argument forwards to the next middleware, and so on,
    until the innermost middleware's `next` calls `transport.__call__`. An
    empty sequence returns `transport.__call__` directly.

    The returned callable is reusable across many requests; it captures
    references to `middlewares` and `transport` by closure.
    """
    chain: Next = transport.__call__
    for middleware in reversed(middlewares):
        chain = _wrap(middleware, chain)
    return chain


def _wrap(middleware: Middleware, next_call: Next) -> Next:
    async def _call(request: Request) -> Response:
        return await middleware(request, next_call)

    return _call


__all__ = ["compose"]
```

Notes:
- Bottom of chain: `transport.__call__` is a bound method satisfying `Callable[[Request], Awaitable[Response]]`. Direct assignment; no wrapper coroutine.
- Each chain layer is one closure: `_wrap` captures `middleware` and `next_call`, returns a coroutine function with the `Next` signature.
- Empty sequence: `reversed(())` is a no-op iterator; `chain` stays as `transport.__call__`. Test asserts identity.
- No exception handling anywhere in the file. `CancelledError` and all other exceptions propagate up. This is the cancellation contract.

## Public exports

`src/httpware/__init__.py` adds:

```python
from httpware.middleware import Middleware, Next
```

…and adds `"Middleware"` and `"Next"` to `__all__` in their alphabetic positions.

Result: consumers can write either of:

```python
from httpware import Middleware, Next
from httpware.middleware import Middleware, Next
```

Both work; the package-root path is the canonical user-facing one (matches `Request`, `Response`, `Httpx2Transport`).

## Testing

`tests/test_middleware.py` covers protocol + chain in one file. Approximate test list:

| Test | Verifies |
| --- | --- |
| `test_empty_list_composes_to_transport_call` | `compose([], transport)(req)` returns the same response as awaiting `transport(req)` directly. (Behavioral check, not identity — the chain may add a thin terminal wrapper if the implementation needs one; see Risks.) |
| `test_single_middleware_wraps_transport` | One middleware sees the request, calls `next`, returns the transport's response. |
| `test_chain_runs_outer_to_inner` | Three middlewares append to a shared list; final order asserts outer → inner → transport → inner → outer (onion). |
| `test_short_circuit_returns_synthesized_response` | Middleware that does NOT call `next` returns a synthesized Response; transport (and any inner middleware) is never invoked. |
| `test_middleware_can_transform_request_before_forwarding` | Outer middleware mutates request via `with_header`; inner sees the mutation. |
| `test_middleware_can_transform_response_before_returning` | Outer middleware awaits `next`, returns a modified Response; caller sees the modification. |
| `test_exception_in_middleware_propagates` | Middleware raises a custom exception; bubbles through unchanged. |
| `test_exception_in_transport_propagates_through_chain` | Transport raises; exception passes through each middleware unmodified. |
| `test_cancelled_error_propagates_through_chain` | `asyncio.CancelledError` raised mid-chain propagates to the caller. Explicit per NFR15. |
| `test_runtime_checkable_isinstance_works` | `isinstance(some_middleware, Middleware)` returns True for a valid impl, False for an unrelated callable. |
| `test_compose_returned_callable_is_reusable` | The `Next` returned by `compose` can be awaited multiple times across sequential requests; closure captures don't accumulate state. |

**Fixtures:**
- `FakeTransport` implementing `Transport`: `async def __call__` returns a fixed Response; `stream()` and `aclose()` stubs. Lives in `tests/test_middleware.py` (file-scoped — not yet shared with other test files).
- `record_calls(*labels)` factory: returns middleware-class instances that append labels to a shared list. Used by the ordering test.

**Coverage expectation:** 100% line coverage on `middleware/__init__.py`, `_internal/__init__.py`, and `_internal/chain.py`. The Protocol method body (`...`) is excluded via standard coverage pragma if needed; typical for Protocol stubs.

## Constraints and invariants

- **No `httpx2` import.** Neither new file imports `httpx2`. The existing `tests/test_no_httpx2_leakage.py` continues to pass without modification.
- **No `from __future__ import annotations`.** PEP 604/585 syntax is native (already enforced repo-wide).
- **No `print()`, no global logging config.** Middleware module does no logging in Story 2-1; observability emission lands in Epic 5.
- **Type suppressions.** None expected. If `ty` flags the bound-method assignment to `Next`, suppress with `# ty: ignore[<rule>]` and document the reason. Should not be needed — `Transport.__call__` already has the matching signature.
- **Keyword-only construction.** N/A for Story 2-1 (no new dataclass or exception types).

## Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| `ty` rejects `chain: Next = transport.__call__` because `Next` is a value-level alias and bound-method assignment is subtle. | If flagged, change to `chain: Next = transport.__call__`. If still flagged, fall back to `async def _terminal(req): return await transport(req)` at the bottom (one extra async frame per call; acceptable). Decided at implementation time, documented as a code comment if used. |
| Middleware swallows `CancelledError` silently (a user bug, not ours). | Story 2-2's `@on_error` decorator excludes `CancelledError` by design (catches `Exception` only). Story 2-1 itself has no exception handlers, so the protocol can't introduce this risk; it can only be introduced by user code. The cancellation test verifies the chain doesn't accidentally swallow it. |
| `runtime_checkable` µs-cost amortizes badly if AsyncClient calls `isinstance` per request (Story 1-7 deferred concern). | Story 1-7 / 2-5 spec must validate `middleware=[...]` at construction time only. Not a Story 2-1 problem to solve; flagged in the design pointer to the deferred-work entry. |
| Sequence vs list semantic surprise — a user passes a `dict.values()` view and expects fresh ordering each call. | `compose` consumes the sequence once (during construction) and stores closures over the captured `middleware` references. Subsequent mutations to the original sequence have no effect. Test `test_compose_returned_callable_is_reusable` covers reuse; no test for the dict-view edge case (not a real user pattern). |

## Definition of done

- `src/httpware/middleware/__init__.py` exports `Middleware` (runtime-checkable Protocol) and `Next` (TypeAlias).
- `src/httpware/_internal/__init__.py` exists as an empty package marker.
- `src/httpware/_internal/chain.py` exports `compose(middlewares, transport) -> Next`.
- `src/httpware/__init__.py` re-exports `Middleware` and `Next` at the package root and adds them to `__all__`.
- `tests/test_middleware.py` contains the 11 tests listed above; all pass.
- `just test` continues green; 100% line coverage on the new modules.
- `just lint-ci` clean: `ruff format --check`, `ruff check --no-fix`, `ty check` all pass.
- `tests/test_no_httpx2_leakage.py` still passes (no `httpx2` import added).
- CHANGELOG.md gets a `[Unreleased]` bullet for Story 2.1.
- Story 2-1 lands as a single PR off `main` via the branch `story/2-1-middleware-protocol-and-chain`.

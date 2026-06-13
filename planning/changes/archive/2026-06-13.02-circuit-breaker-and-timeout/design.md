---
status: shipped
date: 2026-06-13
slug: circuit-breaker-and-timeout
supersedes: null
superseded_by: null
pr: 51
outcome: 'Shipped 0.10.0 — CircuitBreaker + AsyncTimeout'
---

# Spec: CircuitBreaker + AsyncTimeout — completing the resilience suite

**Date:** 2026-06-13
**Topic slug:** `circuit-breaker-and-timeout`
**Status:** drafted, awaiting user review
**Target release:** `0.10.0` (minor — purely additive API; no deprecations, no contract changes)
**Branch:** `feat/circuit-breaker-timeout` off `main`

## Purpose

`httpware`'s resilience suite ships `Retry`/`AsyncRetry` (+ `RetryBudget`) and `Bulkhead`/`AsyncBulkhead` — two of the ~5 strategies that define the Polly / Resilience4j shape. This spec adds the two that let the suite be honestly described as a composable resilience pipeline:

1. **`CircuitBreaker` + `AsyncCircuitBreaker`** — a *classic* consecutive-failure circuit breaker (Polly's pre-v8 default).
2. **`AsyncTimeout`** — an overall wall-clock deadline across the whole inner pipeline (async only).

Both are pure stdlib (`asyncio.timeout`, `time.monotonic`, `threading.Lock`, `enum`). No new optional extra. They slot into the existing middleware chain (Seam A) and reuse the existing observability helper (`_emit_event`) and error conventions (`ClientError` subclass + module-level `_reconstruct_*` + `__reduce__`).

## Resolved design decisions (settled in brainstorming — not open for re-litigation)

1. **Timeout is async-only.** `AsyncTimeout` bounds total wall-clock across everything `next` wraps — most importantly across an `AsyncRetry` loop, whose attempts and backoff sleeps `httpx2` cannot bound. It does **not** duplicate `httpx2`'s per-call connect/read/write/pool timeouts. **No sync `Timeout` ships:** a sync total-deadline cannot interrupt a blocking call mid-flight (sync Python has no cancellation), and `httpx2` already covers sync per-call timeouts. This is the one deliberate break from sync/async parity in the project; the docstring states why.
2. **The breaker v1 trips on consecutive failures** (Polly *classic* breaker): open after `failure_threshold` consecutive counted failures → probe after `reset_timeout` → close after `success_threshold` consecutive half-open successes. Rolling-window / failure-rate (Resilience4j / Polly-v8 default) is **deferred to v2**; the config is shaped so adding a `window` mode later is purely additive.
3. **Failure classification = 5xx + network + timeout, excluding 429.** A *counted failure* is `NetworkError`, httpware `TimeoutError`, or a `StatusError` whose `status_code` is in the effective failure set (default = all 5xx, 500–599). 4xx including 429 do **not** trip the breaker (429 = healthy-but-throttling; tripping amplifies the incident) and count as breaker *successes*. Any other exception type (e.g. `BulkheadFullError`, `ValueError`) propagates unchanged and does **not** affect circuit state.
4. **Control surface is events-only (YAGNI).** No public `state` property, no `reset()` / `isolate()`. Monitoring goes through the observability events. State introspection and manual control can be added additively in a later release if a concrete consumer demand surfaces.
5. **Recommended ordering is breaker-outside-retry.** Documented (not enforced): `AsyncTimeout → AsyncCircuitBreaker → AsyncBulkhead → AsyncRetry → terminal` (corrected during implementation: AsyncBulkhead sits outside AsyncRetry to keep one slot per logical call, consistent with the existing `test_bulkhead_outside_retry_holds_one_slot_across_attempts` guidance). With the breaker outside retry, an open circuit short-circuits the *entire* retry loop (don't hammer a service that's already down), and the breaker counts one outcome per fully-exhausted retry sequence rather than per attempt.

## Non-goals

- **No sync `Timeout`.** See decision 1. Sync callers configure `httpx2`'s timeouts directly.
- **No rolling-window / failure-rate breaker.** Deferred to v2. Config shaped to make it additive (a future `window`/`failure_rate` mode coexists with the consecutive-failure default).
- **No public state introspection or manual control** (`state`, `reset()`, `isolate()`). See decision 4.
- **No per-call retry coupling.** The breaker does not know about `AsyncRetry`; it is plain middleware. Ordering is the user's choice; we only *recommend* one.
- **No new optional extra.** Pure stdlib.
- **No change to `Retry`, `Bulkhead`, `RetryBudget`, the clients, decoders, or any existing error.** Purely additive. The only edits to existing files are export lists, docs, and centralized event-name assertions in `test_observability.py`.
- **No enforced ordering.** The chain composition in `client.py` is untouched; we do not validate or reorder middleware.

## Architecture

### File layout

```
src/httpware/errors.py                                  # + CircuitOpenError (append)
src/httpware/middleware/resilience/timeout.py           # NEW — AsyncTimeout
src/httpware/middleware/resilience/circuit_breaker.py   # NEW — CircuitBreaker + AsyncCircuitBreaker
src/httpware/middleware/resilience/__init__.py          # + 3 new names (imports + __all__)
src/httpware/__init__.py                                # + 3 new names (imports + __all__)
tests/test_timeout.py                                   # NEW
tests/test_circuit_breaker.py                           # NEW — async
tests/test_circuit_breaker_sync.py                      # NEW — sync mirror
tests/test_circuit_breaker_props.py                     # NEW — hypothesis invariant (optional but specified)
tests/test_errors.py                                    # + CircuitOpenError fields/pickle
# (event names asserted in the feature test files above, not test_observability.py)
docs/resilience.md                                      # + CircuitBreaker + AsyncTimeout sections
README.md                                               # resilience paragraph
planning/releases/0.10.0.md                             # NEW
```

### Piece 1 — `CircuitOpenError`

Appended to `errors.py`, mirroring `BulkheadFullError`'s module-level `_reconstruct_*` + `__reduce__` exactly (`errors.py:188-214`). A `ClientError` subclass with one keyword-only field `retry_after: float | None` — seconds until the circuit will next admit a probe, or `None` when a concurrent probe already holds the half-open slot.

```python
def _reconstruct_circuit_open(
    cls: "type[CircuitOpenError]",
    retry_after: float | None,
) -> "CircuitOpenError":
    return cls(retry_after=retry_after)


class CircuitOpenError(ClientError):
    """Raised when a CircuitBreaker refuses a request because the circuit is not closed.

    Fires when the circuit is OPEN, or when it is HALF_OPEN and the single probe
    slot is already taken. The request is never forwarded to ``next``. ``retry_after``
    carries the seconds until the circuit will next admit a probe, when known
    (``None`` when a concurrent probe is already in flight).
    """

    retry_after: float | None

    def __init__(self, *, retry_after: float | None) -> None:
        self.retry_after = retry_after
        if retry_after is None:
            super().__init__("circuit open (a probe request is already in flight)")
        else:
            super().__init__(f"circuit open (retry_after={retry_after:.3f}s)")

    def __reduce__(self) -> tuple[Any, ...]:
        return (_reconstruct_circuit_open, (type(self), self.retry_after))
```

`Any` is already imported in `errors.py` (`from typing import Any`). Exported from `httpware/__init__.py` (imports block + `__all__`, alphabetical).

This is a non-status `ClientError` that defines `__init__` with a keyword-only field — consistent with `BulkheadFullError`, `RetryBudgetExhaustedError`, `DecodeError`, `MissingDecoderError`. The "no `__init__` override" rule scopes only to `StatusError` subclasses (CLAUDE.md §Exception construction).

### Piece 2 — `AsyncTimeout` (`resilience/timeout.py`)

Async-only. Bounds total wall-clock for `next(request)` to complete. Drop-in from the brief; the correctness hinge is `cm.expired()`:

- `asyncio.timeout(self._timeout)` raises `TimeoutError` on expiry.
- httpware's `TimeoutError` **subclasses `builtins.TimeoutError`** (`errors.py:51`), so an inner per-call timeout surfacing through `next` (e.g. an `httpx2` read timeout, possibly via a retry) is *also* a `TimeoutError`. We must not re-label it as our overall deadline.
- `cm.expired()` is the discriminator: `True` ⇒ our deadline fired (re-wrap as httpware `TimeoutError`, emit `timeout.exceeded`); `False` ⇒ inner timeout (re-raise unchanged).

```python
"""AsyncTimeout middleware — overall wall-clock deadline across the inner pipeline.

See planning/specs/2026-06-13-circuit-breaker-and-timeout-design.md for the contract.

This is NOT a per-call timeout — httpx2's connect/read/write/pool timeouts are the
right tool for bounding a single outbound call, and AsyncTimeout does not duplicate
them. What httpx2 cannot bound is the total wall-clock across the whole middleware
pipeline (most importantly across an AsyncRetry loop, whose attempts and backoff
sleeps it knows nothing about). Place AsyncTimeout outermost to enforce
"this whole operation must finish within `timeout` seconds, even across retries."

Async-only by design: a sync total-deadline cannot interrupt a blocking httpx2 call
mid-flight (sync Python has no cancellation), and httpx2 already covers sync per-call
timeouts. Sync callers configure httpx2's timeouts directly; there is no sync Timeout.
"""

import asyncio
import logging

import httpx2

from httpware._internal.observability import _emit_event
from httpware.errors import TimeoutError as HttpwareTimeoutError  # noqa: A004
from httpware.middleware import AsyncNext


_TIMEOUT_INVALID = "timeout must be > 0"

_LOGGER = logging.getLogger("httpware.timeout")


class AsyncTimeout:
    """Bounds total wall-clock time spent in the inner pipeline.

    Parameters
    ----------
    timeout
        Required. Overall deadline in seconds for ``next(request)`` to complete,
        including everything it wraps (retries, backoff sleeps, the call itself).
        Must be ``> 0``. On expiry the middleware raises ``httpware.TimeoutError``.

    Place outermost in the chain for an overall-operation deadline. For bounding a
    single outbound call (connect/read/write/pool), configure ``httpx2`` instead.
    """

    def __init__(self, *, timeout: float) -> None:
        if timeout <= 0:
            raise ValueError(_TIMEOUT_INVALID)
        self._timeout = timeout

    async def __call__(self, request: httpx2.Request, next: AsyncNext) -> httpx2.Response:  # noqa: A002
        """Invoke next under an asyncio.timeout; raise httpware.TimeoutError on expiry.

        Only a deadline THIS middleware imposed is re-wrapped: ``cm.expired()``
        distinguishes our own expiry from an inner ``TimeoutError`` (e.g. an httpx2
        per-call timeout surfacing through a retry), which propagates unchanged.
        """
        try:
            async with asyncio.timeout(self._timeout) as cm:
                return await next(request)
        except TimeoutError as exc:
            if not cm.expired():
                raise  # inner TimeoutError, not our deadline — leave it untouched
            _emit_event(
                _LOGGER,
                "timeout.exceeded",
                level=logging.WARNING,
                message="overall timeout exceeded",
                attributes={
                    "timeout": self._timeout,
                    "method": request.method,
                    "url": str(request.url),
                },
            )
            raise HttpwareTimeoutError(f"overall timeout of {self._timeout}s exceeded") from exc
```

### Piece 3 — `CircuitBreaker` + `AsyncCircuitBreaker` (`resilience/circuit_breaker.py`)

Mirrors `bulkhead.py`'s shape: a shared, sharable instance (pass the same one to multiple clients = one shared circuit); the async class carries the `_check_loop` single-event-loop guard verbatim (`bulkhead.py:78-96`); the sync class guards all state under a `threading.Lock` (mirroring sync `Bulkhead`). Module-level message constants for `ValueError`s.

#### Constructor (identical signature, both classes)

```python
class AsyncCircuitBreaker:
    def __init__(
        self,
        *,
        failure_threshold: int = 5,          # consecutive failures that open; >= 1
        reset_timeout: float = 30.0,         # seconds OPEN before a probe; >= 0
        success_threshold: int = 1,          # consecutive half-open successes to close; >= 1
        failure_status_codes: frozenset[int] | None = None,  # None -> all 5xx (500-599)
        _now: Callable[[], float] = time.monotonic,          # seam for deterministic tests
    ) -> None: ...
```

Validation (module-level message constants, like `bulkhead.py:32-33`):
- `failure_threshold >= 1` else `ValueError(_FAILURE_THRESHOLD_INVALID)`
- `reset_timeout >= 0` else `ValueError(_RESET_TIMEOUT_INVALID)`
- `success_threshold >= 1` else `ValueError(_SUCCESS_THRESHOLD_INVALID)`

**Spec-author choice — `failure_status_codes` normalization:** at construction, `None` is normalized to `frozenset(range(500, 600))`. There is then exactly one classification code path (set membership); no per-request None-branch. The stored attribute is always a `frozenset[int]`.

#### Internal state representation

**Spec-author choice:** a private `enum.Enum` named `_CircuitState` with members `CLOSED`, `OPEN`, `HALF_OPEN`. Not exported (decision 4 — events only). Per-instance mutable fields: `_state`, `_consecutive_failures`, `_consecutive_successes`, `_opened_at: float`, `_probe_in_flight: bool`.

#### State machine

State transitions are synchronous (no `await` between read and mutate), so under asyncio they are atomic. The sync class wraps every read+transition (the admit decision and the record-outcome step) in the `threading.Lock`. The async class relies on cooperative scheduling plus `_check_loop` to reject cross-loop misuse.

The request flow is two synchronous critical sections around the single `await next(request)` / `next(request)`:

**Admit (before `next`)** — decide the request's role or reject:
- **CLOSED** → role `closed`; call `next`.
- **OPEN**:
  - if `_now() - _opened_at >= reset_timeout` → transition to **HALF_OPEN**, set `_probe_in_flight = True`, emit `circuit.half_open` (INFO; attrs `method`, `url`), role `probe`; call `next`.
  - else → raise `CircuitOpenError(retry_after = max(0.0, reset_timeout - (_now() - _opened_at)))`, emit `circuit.rejected` (WARNING; attrs `retry_after`, `method`, `url`). `next` is **not** called.
- **HALF_OPEN**:
  - if `_probe_in_flight` → raise `CircuitOpenError(retry_after=None)`, emit `circuit.rejected`. `next` is **not** called.
  - else (a prior probe succeeded but `success_threshold` not yet met) → set `_probe_in_flight = True`, role `probe`; call `next`.

**Record (after `next`), in `finally` + result/except handling:**
- Classify the outcome:
  - **counted failure** = `next` raised `NetworkError`, httpware `TimeoutError`, or a `StatusError` with `status_code` in the effective failure set.
  - **success** = `next` returned a response, OR raised a `StatusError` whose `status_code` is *not* in the failure set (e.g. 404, 429).
  - **non-counted** = any other exception type → clears `_probe_in_flight` (if probe), leaves all state unchanged, re-raises.
- On **success**:
  - CLOSED → `_consecutive_failures = 0`.
  - HALF_OPEN → `_consecutive_successes += 1`; if `>= success_threshold` → **CLOSED**, reset all counters, emit `circuit.closed` (INFO; attrs `method`, `url`). Else stay HALF_OPEN (the next request becomes the next probe).
- On **counted failure**:
  - CLOSED → `_consecutive_failures += 1`; if `>= failure_threshold` → **OPEN**, `_opened_at = _now()`, emit `circuit.opened` (WARNING; attrs `failure_threshold`, `failures`, `method`, `url`). Re-raise the original exception unwrapped.
  - HALF_OPEN → **OPEN**, `_opened_at = _now()`, `_consecutive_successes = 0`, emit `circuit.opened` (re-open; `failures` reported as `1` — the single probe failure that re-opened the circuit). Re-raise unwrapped.
- `_probe_in_flight` is cleared in `finally` whenever the request held the probe slot, regardless of outcome (success, counted failure, non-counted exception, cancellation).

Counted failures **re-raise the original exception unwrapped** (matching `AsyncRetry`'s treatment of `StatusError`). The breaker never wraps a downstream error; it only *adds* `CircuitOpenError` when it refuses to forward.

#### Concurrency

- **Async:** carry `_check_loop` (cached-loop fast path + `threading.Lock` double-checked write, including the `# pragma: no cover` inner race arm) verbatim from `AsyncBulkhead`. The admit/record critical sections contain no `await`, so they are atomic under a single event loop. The probe gate is the synchronous `_probe_in_flight` flag set inside admit before the `await` and cleared in `finally`.
- **Sync:** a `threading.Lock` guards every state read + transition and the probe flag (mirror sync `Bulkhead`). Sharable across `Client`s. A sync instance **cannot** be shared with an async one (documented, like `Bulkhead`).

#### Exports

`resilience/__init__.py` and `httpware/__init__.py`: add `AsyncCircuitBreaker`, `AsyncTimeout`, `CircuitBreaker` to imports + `__all__` (keep alphabetical). Update the `resilience/__init__.py` module docstring to mention the new primitives.

### Observability (public, stable once shipped)

Loggers: `httpware.circuit_breaker`, `httpware.timeout`. Events:

| Event | Level | Attributes |
|-------|-------|------------|
| `circuit.opened` | WARNING | `failure_threshold`, `failures`, `method`, `url` |
| `circuit.rejected` | WARNING | `retry_after`, `method`, `url` |
| `circuit.half_open` | INFO | `method`, `url` |
| `circuit.closed` | INFO | `method`, `url` |
| `timeout.exceeded` | WARNING | `timeout`, `method`, `url` |

These names join `retry.*` / `bulkhead.*` as the stable observability surface; renames are breaking changes.

## Testing

TDD, 100% branch coverage enforced (`--cov-fail-under=100`). `httpx2.MockTransport` injected via `AsyncClient(httpx2_client=httpx2.AsyncClient(transport=mock))` / `Client(httpx2_client=httpx2.Client(transport=mock))`. Drive time with an injected `_now` (a small advancing-clock helper). Reuse the `_ResponseSequence` + `_client` pattern from `tests/test_retry.py`.

**`tests/test_circuit_breaker.py` (async) + `tests/test_circuit_breaker_sync.py` (sync mirror)** — every branch:
- closed passes through; `N` consecutive counted-failures → OPEN (assert `circuit.opened`).
- OPEN fast-fails with `CircuitOpenError`, `next` not called, `retry_after` set and clamped ≥ 0 (assert `circuit.rejected`).
- after `reset_timeout` (advance `_now`) → HALF_OPEN admits one probe (assert `circuit.half_open`).
- probe counted-failure → OPEN again, `_opened_at` reset, success counter zeroed.
- probe success × `success_threshold` → CLOSED (assert `circuit.closed`); cover `success_threshold > 1` (stay HALF_OPEN between probes).
- 429 and 404 do **not** count as failures (CLOSED counter resets; treated as success).
- non-counted exception (`ValueError`) propagates unchanged, no state change, probe flag cleared.
- a success mid-streak resets the consecutive-failure counter.
- half-open second concurrent request fast-fails with `retry_after=None` (assert `circuit.rejected`).
- ctor validation for all three numeric params (one test each).
- custom `failure_status_codes` set: a code in the set trips; a 5xx *not* in the set is a success.
- **async only:** `_check_loop` raises `RuntimeError` on cross-loop use (mirror the bulkhead cross-loop test).

**`tests/test_circuit_breaker_props.py` (hypothesis):** invariant "while OPEN and before `reset_timeout` elapses, `next` is never called" — generate random failure/advance sequences, assert the transport's call count does not increase while the circuit is OPEN pre-timeout. Mirror the `test_*_props.py` convention.

**`tests/test_timeout.py`:**
- pass-through returns the response when under budget.
- expiry raises `httpware.TimeoutError` chained from `builtins.TimeoutError` (assert `__cause__`) and emits `timeout.exceeded`.
- an inner `TimeoutError` raised by `next` propagates unchanged (cm not expired) — assert it is the *inner* exception, not the overall-deadline message.
- `timeout <= 0` raises `ValueError` at construction.
- Deterministic: inject a `next` that `await asyncio.sleep(...)`s under a controllable clock; no wall-clock dependence.

**`tests/test_errors.py`:** `CircuitOpenError` is a `ClientError`, stores `retry_after`, summary string for both `None` and a float, pickle round-trip via `__reduce__` (mirror `test_bulkhead_full_error_pickleable`).

**Event-name assertions:** there is no central event-name registry test (`test_observability.py` only unit-tests the `_emit_event` helper), so the 5 new event names are asserted in their own feature test files via `caplog` — `circuit.opened`/`circuit.rejected` in `test_open_emits_opened_event_and_rejects`, `circuit.half_open`/`circuit.closed` in `test_reset_timeout_admits_probe_then_closes`, `timeout.exceeded` in `test_expiry_raises_httpware_timeout_chained_from_builtin`.

`# pragma: no cover` only for genuinely-unreachable invariant arms (e.g. the `_check_loop` inner race arm), matching the existing style.

## Docs + release

- **`docs/resilience.md`:** a CircuitBreaker section and an AsyncTimeout section; the recommended ordering `AsyncTimeout → AsyncCircuitBreaker → AsyncBulkhead → AsyncRetry → terminal` (documented, not enforced); the rationale notes ("why no sync Timeout", "why not duplicate httpx2 per-call timeouts", "429/4xx count as successes, not failures").
- **`README.md`:** extend the resilience paragraph from "Retry + Bulkhead" to include CircuitBreaker + AsyncTimeout.
- **`planning/releases/0.10.0.md`:** new release notes (additive minor; new public names; new observability events).

## Green gate

`just lint` clean (eof-fixer + ruff format + ruff check --fix + ty). `just test` → 100% coverage, all pass. Commit per piece (`CircuitOpenError` → `AsyncTimeout` → breaker → exports → docs/release). Minor bump `0.10.0` (additive API, pre-1.0). The tag name *is* the version (`uv version $GITHUB_REF_NAME`); `pyproject.toml` version is not bumped (see release-mechanics convention).

## Open questions

None. All design decisions resolved in brainstorming (see "Resolved design decisions" above).

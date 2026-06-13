# httpware delta audit — 2026-06-13 (0.10.0 circuit-breaker + async-timeout)

**Status:** complete
**Baseline:** 0.9.1 → 0.10.0 (`2a2b541`)
**Scope:** `circuit_breaker.py`, `timeout.py`, `CircuitOpenError`, their tests, and the 0.10.0 docs.
**Method:** six adversarial finders across dimensions (concurrency, state machine, exception classification, AsyncTimeout, API/docs, test quality), then per-finding triage; the two headline production findings were reproduced directly.

## Summary

- Blockers: 0
- High: 1
- Medium: 6
- Low: 8
- Nits / informational: 2

No blockers. The state machine, async atomicity claim, sync lock coverage, cross-loop guard, `cm.expired()` discriminator, exception-clause ordering, exception chaining, pickle round-trip, export symmetry, and the property/concurrent tests' soundness were all verified **correct** (see Negative results). The headline is a **test-contract gap**, echoing the 0.9.0 audit's pattern: the five observability event-name strings are the documented stable public surface, yet **no test asserts any event name** — every test discriminates events by substring on the human-readable `message`, and `_emit_event` never puts `event_name` on the log record (it goes only to OTel `add_event`). Renaming `circuit.opened` → anything passes 100% of tests. The two real production bugs are both small and bounded: `AsyncTimeout` accepts `nan`/`inf` (the `timeout <= 0` guard is false for both), and a probe-slot/state leak if an observability emit raises mid-transition (no `finally` around the half-open/open mutation).

## Findings

### High

#### H1 — Observability event names are never asserted; a rename of the stable public surface passes silently
*(test quality — verified)*

`tests/test_circuit_breaker.py`, `tests/test_circuit_breaker_sync.py`, `tests/test_timeout.py`; root cause `src/httpware/_internal/observability.py:40`.

`_emit_event` does `logger.log(level, message, extra=attributes)` — the `event_name` (`circuit.opened`, `circuit.rejected`, `circuit.half_open`, `circuit.closed`, `timeout.exceeded`) is **not** on the log record; it is passed only to OTel's `add_event`. Every circuit/timeout test discriminates events with substrings on `message` (`"opened" in r.message`, `any("half-open" in m …)`). The spec calls these five strings "the stable observability surface; renames are breaking changes" and claims they are asserted in the feature tests — they are not. Renaming any event string in source would not fail a single test. Verified: `event_name` is absent from the record; only `test_observability.py` ever exercises `add_event`, with a synthetic `"test.event"`.

**Direction:** assert each event name — either mock `trace.get_current_span().add_event` and assert the name (mirroring `test_observability.py`), or add `event_name` to the structured log record's extras and assert it (the latter also lets users filter logs by event, but changes the emission shape — decide deliberately).

### Medium

#### M1 — `AsyncTimeout` accepts `nan` and `inf` (`timeout <= 0` guard is false for both)
*(production — reproduced)*

`src/httpware/middleware/resilience/timeout.py:47`. `float('nan') <= 0` and `float('inf') <= 0` are both `False`, so the constructor accepts them. Reproduced: `AsyncTimeout(timeout=float('nan'))` and `(float('inf'))` are both ACCEPTED. `asyncio.timeout(nan)` fires nondeterministically (NaN breaks the timer heap ordering); `asyncio.timeout(inf)` never fires (silent no-op). A caller passing `math.inf` to mean "no limit", or `nan` from a bad config parse, gets silent misbehavior instead of a clear error.

**Direction:** `if not math.isfinite(timeout) or timeout <= 0: raise ValueError(...)` (add `import math`). Add a test asserting `nan`/`inf` are rejected (folds in Low L8).

#### M2 — Probe-slot / state leak if an observability emit raises mid-transition → permanent HALF_OPEN wedge
*(production — verified by trace; low probability)*

`src/httpware/middleware/resilience/circuit_breaker.py` `admit` (OPEN→HALF_OPEN branch) and `_open`. In `admit`, `self._probe_in_flight = True` is set and then `self._emit(...)` is called — all inside `admit`, **before** `__call__` enters its `try` block, and there is no `finally` clearing the flag. `_emit` → `_emit_event` calls `trace.get_current_span().add_event(...)` outside any guard (only the OTel *import* is guarded). If `add_event` raises (a recording span with a broken exporter / attribute validation), the exception propagates out of `admit` with `_state` already HALF_OPEN and `_probe_in_flight` already `True` and nothing to reset them. The circuit then wedges permanently in HALF_OPEN — every later request takes the probe-in-flight arm and raises `CircuitOpenError(retry_after=None)` forever, even after the service recovers. The same emit-after-mutate shape in `_open` would instead mask the original failure exception. Affects both sync and async. Requires OTel installed + a recording span whose `add_event` raises, so probability is low, but the failure mode (silent permanent wedge) is severe.

**Direction:** make state-mutating transitions resilient to observability failure — e.g. emit *before* mutating state where possible, or move the flag-set/emit so that an emit failure cannot strand the slot, or harden `_emit_event` to never propagate exceptions from `add_event` (note: shared helper — also used by retry/bulkhead).

#### M3 — `retry_after` value and the `max(0.0, …)` clamp are never asserted
*(test quality)*

`tests/test_circuit_breaker.py:105,126`, sync `:88,97` — `retry_after` is only checked `is not None`. With the injected `_Clock` the value is fully deterministic (open at t=0, `reset_timeout=30`, reject at t=10 ⇒ `retry_after == 20.0`). The clamp `max(0.0, reset_timeout - elapsed)` could be deleted or return wrong/negative arithmetic and every test still passes.

**Direction:** advance the clock a known amount before the reject and assert the exact `retry_after`; add a case pinning the `0.0` floor.

#### M4 — "429/4xx resets the failure streak" is proven only via the `200` branch
*(test quality)*

`test_404_and_429_do_not_count_as_failures` interleaves only 404/429, so the failure counter is always already 0 — the `on_success` reset runs 0→0, a no-op. The streak-reset is proven by `test_success_resets_failure_streak` via a `200` (response-returned branch), not the StatusError-not-in-set branch. A bug routing 429 to `release_probe`/no-op instead of `on_success` would survive. Sequence `[500, 429, 500, 500]` at `failure_threshold=2` should stay CLOSED (429 resets) but would open under such a bug.

**Direction:** add `[500, 429, 500, 500]` (threshold=2), assert it never opens (`handler.calls == 4`).

#### M5 — `docs/index.md` Observability section omits the new loggers/events
*(docs)*

`docs/index.md:148–158` still lists only `httpware.retry` / `httpware.bulkhead` and the `retry.*` / `bulkhead.*` events as the stable contract. `httpware.circuit_breaker` (4 events) and `httpware.timeout` (1 event) are absent. README was updated; the docs landing page was not — undercutting the "stable public contract" claim on the most-read page.

**Direction:** extend `docs/index.md` to list all four families, or cross-reference `docs/resilience.md`.

#### M6 — README logging example suppresses the INFO recovery events
*(docs)*

`README.md:129` sets `httpware.circuit_breaker` to `WARNING`. `circuit.half_open` and `circuit.closed` are emitted at `INFO` (`circuit_breaker.py` `admit`/`on_success`). Users copying the snippet silently miss exactly the events that show the circuit probing and recovering — only `opened`/`rejected` (WARNING) appear.

**Direction:** use `INFO` for `httpware.circuit_breaker` in the snippet, or comment that recovery events fire at INFO.

### Low

- **L1 — `docs/resilience.md` AsyncRetry section is now false** (`:28–29`): "httpware does not own a structured-cancellation timeout knob" — `AsyncTimeout` is exactly that, documented in the same file. (The sync `Retry` occurrence at `:320` remains accurate.) *(docs)*
- **L2 — `docs/index.md:141` + `README.md:115` Errors lists omit `CircuitOpenError`** from the resilience-refusal enumeration. `docs/errors.md` correctly includes it. *(docs)*
- **L3 — `docs/resilience.md:159` OPEN-state wording imprecise**: "All requests are rejected" — the first request after `reset_timeout` is admitted as the probe (lazy transition), not rejected. *(docs)*
- **L4 — `src/httpware/_internal/observability.py:5–6` docstring** lists only `httpware.retry`/`httpware.bulkhead` as stable loggers; add the two new ones. *(docs)*
- **L5 — No sync mirror of `test_non_counted_exception_in_probe_releases_slot`**: the sync wrapper's `except BaseException → release_probe(role=probe)` arm is behaviorally untested (branch coverage is satisfied only via the shared `_CircuitBreakerState` exercised by the async test). *(test quality)*
- **L6 — `success_threshold > 1` with a probe failure mid-streak is untested**: no test where probe-1 succeeds (counter→1), probe-2 fails → reopen, and a later close must re-accumulate from 0. A failure to zero `_consecutive_successes` on reopen would close one probe early, undetected. *(test quality)*
- **L7 — Reachable boundary configs untested**: `reset_timeout=0` (OPEN immediately admits a probe; the `retry_after` reject branch is unreachable) and empty `failure_status_codes` (normalizes to `frozenset()`; no status ever trips — only network/timeout do). Both are accepted at construction. *(test quality)*
- **L8 — `failures=1` on probe-reopen + reopen `circuit.opened` event unasserted**, and (after M2's fix) `nan`/`inf` rejection needs a test. *(test quality)*

### Nits / informational

- **N1 — Spec/impl type divergence (informational, no action):** the spec declares `failure_status_codes: frozenset[int] | None`; the impl uses `Collection[int] | None` (frozen internally). This is the deliberate ergonomics fix from the PR-review round (a code comment documents it; tests pass a plain set and a list). The spec is the outlier; no user-facing inconsistency.
- **N2 — `TransportError` (non-`NetworkError`, e.g. `httpx2.InvalidURL`) is treated as a foreign exception by the breaker** (no state change) — correct (it's a programming error, not a transient failure), but the module docstring doesn't say so. A one-line note would prevent surprise.

## Negative results (attacked, found sound)

- **Async atomicity:** no `await` exists inside `admit`/`on_success`/`on_failure` or between `admit()` returning and the `try` block; transitions are atomic under one event loop. No double-probe, no interleave leak. `CancelledError` cannot fire mid-`admit` (no await point).
- **Sync lock coverage:** every shared-state read/mutation is under `self._lock`; `next()` is correctly outside it; the TOCTOU window between admit and record is benign (the `_probe_in_flight` flag, set under lock, serializes the probe).
- **Cross-loop guard:** `_check_loop` is verbatim from `AsyncBulkhead` (incl. the `# pragma: no cover` race arm) and runs before any mutation.
- **Exception classification:** `StatusError` / `(NetworkError, TimeoutError)` / `BaseException` clauses are genuinely disjoint under the hierarchy; `StatusError`-not-in-set correctly routes to `on_success`; `CancelledError`/`KeyboardInterrupt`/`SystemExit` and foreign suite exceptions (`BulkheadFullError`, `RetryBudgetExhaustedError`, `DecodeError`, `MissingDecoderError`) all release the probe and re-raise with no state change; counted failures re-raise unwrapped; `CircuitOpenError` never chains a downstream error.
- **`AsyncTimeout` `cm.expired()` discriminator:** airtight — a near-simultaneous inner `asyncio.timeout`, an external task cancel, and our own deadline are all distinguished correctly (confirmed experimentally); `__cause__` is a `builtins.TimeoutError`; the middleware is stateless and safe to share.
- **State machine:** threshold boundaries (`>= N`, opens on exactly N), `reset_timeout` boundary (`>=`, inclusive), counter resets on open/close, probe-flag lifecycle, and `success_threshold>1` multi-probe all correct.
- **Tests that ARE sound:** the property test is non-vacuous (deterministic coverage, real invariant); both concurrent-probe tests genuinely force the probe-in-flight rejection; the timeout tests assert exact attributes + `__cause__`; the `CircuitOpenError` pickle/field/summary tests are substantive; `handler.calls`-based assertions genuinely distinguish opened-vs-closed.
- **Conventions / exports:** no `from __future__ import annotations`, no `# type: ignore`, no `print()`, no `basicConfig`, no `httpx2._`, no `__all__` in submodules; the four new names are symmetric across both `__init__.py`s and `test_public_api.py`; defaults match docs.

## Closure note

All findings are bounded and well-understood. Suggested grouping for closure (process-weight-matched, not one PR per finding):
1. **Production fixes** (M1 `nan`/`inf` guard + test; M2 emit-safety / no-wedge) — one small PR.
2. **Test hardening** (H1 event-name assertions; M3 `retry_after` value; M4 429-resets-streak; L5–L8) — one PR.
3. **Docs sweep** (M5, M6, L1–L4, N2) — one docs PR.

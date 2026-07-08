---
summary: Read-only `state` property + public `CircuitState` enum on the circuit breaker. Shipped 0.14.0; closed the read-only-state half of the deferred CircuitBreaker introspection item.
---

# Design: Read-only `state` introspection on the circuit breaker

## Summary

Expose the circuit breaker's current state through a typed public enum
`CircuitState` and a read-only `state` property on `AsyncCircuitBreaker` /
`CircuitBreaker`. Additive, no behavior change. Ships as 0.14.0.

## Motivation

The breaker currently has no way to ask "what state is the circuit in right
now?" — useful for health/readiness endpoints, ops dashboards, and tests.
Resilience4j (registry) and Polly (`StateProvider`) both expose this. It was
parked under the CircuitBreaker deferred entry as the cheap, barely-speculative
half of "manual control + state introspection" — explicitly the part worth
building when convenient rather than parking indefinitely. The manual-control
half (`force_open`/`force_closed`) stays deferred.

## Non-goals

- **Manual control** (`force_open`/`force_closed`) — stays deferred (YAGNI for
  an HTTP client).
- **An "effective"/computed state** that reads the clock to report `HALF_OPEN`
  once `reset_timeout` has elapsed but before any request. The property is a
  pure read of the stored state (see Design §3).
- **Per-call state** surfaced on responses or exceptions.

## Design

### 1. Promote `_CircuitState` → public `CircuitState`

The state enum is currently `_CircuitState` (private) in
`src/httpware/middleware/resilience/circuit_breaker.py`, a `str`-valued enum
with members `CLOSED = "closed"`, `OPEN = "open"`, `HALF_OPEN = "half_open"`.
Rename it to `CircuitState` (drop the leading underscore), keeping the values,
and update every internal reference. Because the old name was underscore-private,
nothing external could depend on it — no deprecation shim needed.

Export it as a public symbol:
- add `"CircuitState"` to `httpware.middleware.resilience.__all__` (alongside
  `AsyncCircuitBreaker`/`CircuitBreaker`),
- add it to top-level `httpware.__all__` and the `httpware/__init__.py` imports,
  so `from httpware import CircuitState` works (mirroring how
  `AsyncCircuitBreaker` is already top-level re-exported).

### 2. The `state` property

A pure, side-effect-free read:

```python
# on _CircuitBreakerState
@property
def state(self) -> CircuitState:
    return self._state

# on AsyncCircuitBreaker and CircuitBreaker
@property
def state(self) -> CircuitState:
    return self._state.state
```

No lock and no clock read — a single attribute read of the stored enum. (A sync
reader sees a momentary value; that is the nature of introspection and matches
how Resilience4j/Polly expose it. No `threading.Lock` is taken for a single
reference read.)

### 3. Raw stored-state semantics

The breaker transitions `OPEN → HALF_OPEN` *lazily*, inside `admit`, on the
next request after `reset_timeout`. `state` reports the **raw stored** value, so
between `reset_timeout` elapsing and the next request it still reads `OPEN`. This
is deliberate: a property must not mutate (the lazy transition flips
`_probe_in_flight` and the state) and must not duplicate the transition logic.
The caveat is documented; for health-check use it is the honest answer ("the
circuit is open; a probe will be admitted on the next call").

## Testing

Sync + async mirrors:

- `state` is `CircuitState.CLOSED` on a fresh breaker.
- After enough counted failures to trip, `state` is `CircuitState.OPEN`.
- After `reset_timeout` elapses AND a request is admitted as the probe, `state`
  is `CircuitState.HALF_OPEN`.
- After `success_threshold` probe successes, `state` is back to
  `CircuitState.CLOSED`.
- Raw-read caveat: with the circuit OPEN and `reset_timeout` elapsed but no
  request made, `state` still reads `OPEN` (pinned `_now` clock).
- `from httpware import CircuitState` resolves; `"CircuitState"` is in
  `httpware.__all__` and `httpware.middleware.resilience.__all__`
  (extend the existing public-API test).

`just test` green; `just lint` clean.

## Risk

- **Rename churn (low × low).** Renaming `_CircuitState` touches every internal
  reference in `circuit_breaker.py`; a missed reference is a `NameError` caught
  immediately by the existing breaker suite + `ty`.
- **Staleness confusion (low × low).** The raw-read caveat could surprise a user
  expecting `HALF_OPEN` the instant `reset_timeout` passes; mitigated by the doc
  note. Reporting raw stored state is the simpler, correct-for-a-property choice.

## Out of scope

Manual control, computed/effective state, response-level state — all excluded
above. No change to trip behavior, event surface, or composition order.

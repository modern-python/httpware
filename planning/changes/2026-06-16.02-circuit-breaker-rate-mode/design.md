---
status: shipped
date: 2026-06-16
slug: circuit-breaker-rate-mode
summary: Added an opt-in time-based failure-rate trip mode to the circuit breaker (classic stays default). Shipped 0.13.0; closed deferred item "CircuitBreaker v2 (a)".
supersedes: null
superseded_by: null
pr: 69
outcome: Shipped 0.13.0 — opt-in time-based failure-rate trip mode (failure_rate_threshold + window_seconds + minimum_calls) on both breakers; classic stays default. Closed the "CircuitBreaker v2 (a)" deferred item; count-based windows, slow-call axis, and manual control + state remain deferred.
---

# Design: CircuitBreaker v2 — time-based failure-rate trip mode

## Summary

Add an additive, opt-in **time-based failure-rate** trip mode to
`AsyncCircuitBreaker` / `CircuitBreaker`. The classic consecutive-failure model
stays the default and is byte-unchanged; nothing trips differently unless the
caller sets `failure_rate_threshold`. Rate mode opens the circuit when the
failure rate over a rolling time window meets the threshold, once a minimum call
volume is observed. Ships as 0.13.0.

## Motivation

The 0.10.0 breaker ships only the classic model: open after N *consecutive*
counted failures. That cannot catch *partial* degradation — a steady 50% error
rate that alternates success/fail never reaches a consecutive streak, so the
breaker never trips while half the traffic is failing. This was deferred to v2
in the 0.10.0 spec, with the config deliberately shaped so a rate mode is purely
additive (see [`deferred.md`](../../deferred.md) → "CircuitBreaker v2").

The verified comparison in `deferred.md` (2026-06-13) shows rate-over-window is
the mainstream model for service-level breakers: Hystrix (time-bucketed),
Polly v8 (time-based only), and Envoy/Istio outlier detection (time intervals)
are all time-based; Resilience4j defaults to count-based but offers both. We
choose **time-based** because the mental model matches the HTTP domain ("trip if
>50% of calls failed in the last 30s"), it degrades sanely under variable
traffic (a count-based window can hold hour-old outcomes when traffic is low),
and it is consistent with the existing wall-clock `reset_timeout`.

## Non-goals

- **Count-based windows.** Deferred; the config leaves room to add a window-type
  selector later if anyone asks.
- **Slow-call rate axis.** Resilience4j-only; redundant with `AsyncTimeout`.
- **Manual control / read-only `state` introspection** (deferred item b). Stays
  parked as YAGNI; independent design axis.
- **Rate-based half-open recovery.** Half-open stays identical to v1 in both
  modes (consecutive `success_threshold` probe successes) — simpler, and the
  trip mode is the only behavioral change.

## Design

### 1. Opt-in config shape

`failure_rate_threshold` is the mode switch on both wrappers' `__init__`:

```python
AsyncCircuitBreaker(
    failure_rate_threshold=0.5,   # None (default) = classic; set = rate mode
    window_seconds=30.0,          # rolling window duration (default 30.0)
    minimum_calls=20,             # floor before the rate is evaluated (default 20)
    # unchanged, shared by both modes:
    reset_timeout=30.0,
    success_threshold=1,
    failure_status_codes=None,
)
```

- **Shared across modes:** `reset_timeout`, `success_threshold` (half-open
  recovery), `failure_status_codes` (the counted-failure set — 429/4xx remain
  successes).
- **Classic-only:** `failure_threshold`. In rate mode it is **silently ignored**
  (documented). The two thresholds don't conflict — the mode is selected solely
  by whether `failure_rate_threshold` is `None` — so no raise-on-both guard is
  added.
- **Validation** (in `_CircuitBreakerState.__init__`, alongside the existing
  checks): when `failure_rate_threshold is not None`, require
  `0.0 < failure_rate_threshold <= 1.0`; require `window_seconds > 0`; require
  `minimum_calls >= 1`. New message constants follow the existing
  `_FAILURE_THRESHOLD_INVALID` pattern.

### 2. Time-based rolling-bucket window

A new internal `_RollingWindow` (or inline state on `_CircuitBreakerState`):
`window_seconds` divided into a fixed **10 buckets** (`_BUCKET_COUNT`), each a
`[successes, failures]` pair tagged with the time-slot it represents. Bucket
width = `window_seconds / 10`.

Recording an outcome (synchronous, no await):
1. `slot = floor(self._now() / bucket_width)`.
2. `index = slot % _BUCKET_COUNT`. If the bucket at `index` carries a stale slot
   tag (`!= slot`), reset it to `[0, 0]` and retag — this evicts data older than
   one full window in O(`_BUCKET_COUNT`), independent of call volume.
3. Increment the bucket's success or failure count.

Rate computation sums `(successes, failures)` across buckets whose slot tag is
within the last `_BUCKET_COUNT` slots (live), giving `total` and `failures`;
`rate = failures / total` when `total > 0`. Eviction-on-read drops buckets that
fell out of the window since the last write.

All bucket reads/writes happen inside the same synchronous critical section the
breaker already uses (async: lock-free under one event loop; sync:
`threading.Lock`), and `_now()` is read inside that section.

### 3. State-machine integration — mode changes only the CLOSED trip test

The trip mode affects exactly one decision: when to open from CLOSED. Everything
else is shared.

- **CLOSED, rate mode:** `on_success` and `on_failure` record the outcome into
  the window (a counted failure increments failures; a success increments
  successes). After recording, if `total >= minimum_calls` **and**
  `rate >= failure_rate_threshold`, open the circuit. The classic consecutive
  counters are not used in rate mode.
- **CLOSED, classic mode:** unchanged — consecutive-failure counter, open at
  `failure_threshold`.
- **OPEN → HALF_OPEN → CLOSED:** identical for both modes — lazy probe after
  `reset_timeout`, `success_threshold` consecutive probe successes close it, one
  probe failure re-opens. On transition to CLOSED, the window is cleared (all
  buckets reset) so recovery starts from a clean slate.
- **`release_probe` and non-counted exceptions** never touch the window —
  consistent with today (programming errors can't trip the breaker).

This logic lives entirely in the shared `_CircuitBreakerState`, so
`AsyncCircuitBreaker` and `CircuitBreaker` reach parity with no per-wrapper code
(the wrappers' `__init__` just forward the three new params).

### 4. Observability

Event names are unchanged (`circuit.opened`, `circuit.rejected`,
`circuit.half_open`, `circuit.closed`) — the stable observability surface is
preserved. In rate mode, `circuit.opened` carries rate attributes instead of the
classic ones: `failure_rate`, `failure_rate_threshold`, `window_seconds`,
`observed_calls` (the `total`). Classic mode keeps emitting `failure_threshold` +
`failures`. `circuit.rejected`/`half_open`/`closed` are unchanged.

## Testing

Deterministic tests with a pinned `_now` callable (the existing constructor
already accepts `_now`), sync + async mirrors:

- **Trips at threshold:** with `minimum_calls` met and `rate >=
  failure_rate_threshold`, the circuit opens; an alternating 50% pattern that
  never trips the classic breaker DOES trip rate mode.
- **Volume floor:** below `minimum_calls`, a 100%-failure burst does NOT open.
- **Time eviction:** failures recorded, then `_now` advanced past
  `window_seconds`, then fresh successes — old failures age out and the rate
  reflects only the live window.
- **Classic unchanged:** existing breaker tests stay green (no behavior drift
  when `failure_rate_threshold is None`).
- **Half-open in rate mode:** open → probe after `reset_timeout` →
  `success_threshold` successes close → window cleared (a subsequent single
  failure doesn't immediately re-trip).
- **Validation:** out-of-range `failure_rate_threshold`, non-positive
  `window_seconds`, `minimum_calls < 1` raise `ValueError`.
- **Hypothesis prop** (`test_circuit_breaker_props.py` companion) for the
  rolling-window recorder: arbitrary interleavings of outcomes and time advances
  never miscount the live-window totals or evict live data.

`just test` green; `just lint` clean.

## Risk

- **Window-eviction correctness (medium × high).** Off-by-one in slot tagging or
  the modulo ring could count stale data or drop live data. Mitigated by the
  Hypothesis prop on the recorder and explicit time-advance tests; the standard
  slot-tag-and-retag pattern is well understood.
- **Concurrency (low × high).** Recording stays a synchronous mutation, so the
  async lock-free atomicity invariant and the sync `threading.Lock` both still
  hold — no new await points. Eviction reads `_now()` inside the critical
  section. This matches the `deferred.md` concurrency note.
- **Config confusion (low × low).** `failure_threshold` being ignored in rate
  mode could surprise; mitigated by docstring + `architecture/resilience.md`
  wording.

## Out of scope

Count-based windows; slow-call axis; manual control + `state`; rate-based
half-open; any change to classic-mode behavior, `AsyncTimeout`, or the
composition-order recommendation.

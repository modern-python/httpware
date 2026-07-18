# Deferred Work

Items raised in reviews that are real but not actionable now.

As of 0.7.0, all planned epics (3, 4, 5, 6) are closed — see the [change Index](README.md). The Open section below is the long-tail register: items that remain technically real but depend on speculative future work, so they're parked here pending a concrete trigger.

## Open

### Free-threading

- **3.13t free-threaded CI** — blocked on a msgspec cp313t wheel; add the interpreter to the `pytest-freethreaded` job when the wheel ships.

### Resilience

- **CircuitBreaker — manual control** (`src/httpware/middleware/resilience/circuit_breaker.py`) — the trip-mode work is done (0.13.0 shipped the opt-in time-based failure-rate mode) and 0.14.0 shipped the read-only `state` property + public `CircuitState` enum. The one remaining piece is `force_open`/`force_closed` (Polly's `ManualControl`) — the genuinely YAGNI half for an HTTP *client* (you'd usually just stop sending requests), keyed off the 0.10.0 audit's events-only control-surface decision (decision 4). Demand-gated.

  **Don't regress:** httpware's HTTP-native failure classification (429/4xx = success out of the box) is already ahead of the generic-predicate breakers — preserve it in any future work here.

  **Decided against (don't re-propose):**

  - **Count-based window variant** (`window_type="count"`) — time-based + `minimum_calls` already covers the fixed-sample-size rationale, and count-based adds a real staleness downside for HTTP health detection (a low-traffic "last N calls" window can reflect outcomes from minutes ago). Polly v8 *removed* count-based; Hystrix and Envoy are time-based. For a spiky low-volume backend, a longer `window_seconds` + `minimum_calls` is the better tool. Revisit only on concrete Resilience4j-parity demand.
  - **Slow-call-rate dimension** — Resilience4j-only, and redundant with `AsyncTimeout`.

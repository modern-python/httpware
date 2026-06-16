# Deferred Work

Items raised in reviews that are real but not actionable now.

As of 0.7.0, all planned epics (3, 4, 5, 6) are closed — see the [change Index](README.md). The Open section below is the long-tail register: items that remain technically real but depend on speculative future work, so they're parked here pending a concrete trigger.

## Open

### Resilience

- **CircuitBreaker v2 — manual control + read-only `state`** (`src/httpware/middleware/resilience/circuit_breaker.py`) — 0.13.0 shipped the opt-in **time-based** failure-rate trip mode (`failure_rate_threshold` + `window_seconds` + `minimum_calls`; classic stays default). The one remaining real axis is `force_open`/`force_closed` and a `state` introspection property (Resilience4j's registry, Polly's `StateProvider`/`ManualControl`). Parked as YAGNI in the 0.10.0 audit (decision 4: events-only control surface). Demand-gated; independent of the trip mode.

  **Don't regress:** httpware's HTTP-native failure classification (429/4xx = success out of the box) is already ahead of the generic-predicate breakers — preserve it in any v2 work.

  **Decided against (don't re-propose):**

  - **Count-based window variant** (`window_type="count"`) — time-based + `minimum_calls` already covers the fixed-sample-size rationale, and count-based adds a real staleness downside for HTTP health detection (a low-traffic "last N calls" window can reflect outcomes from minutes ago). Polly v8 *removed* count-based; Hystrix and Envoy are time-based. For a spiky low-volume backend, a longer `window_seconds` + `minimum_calls` is the better tool. Revisit only on concrete Resilience4j-parity demand.
  - **Slow-call-rate dimension** — Resilience4j-only, and redundant with `AsyncTimeout`.

### Documentation

- **Non-streaming hard response-body cap** (2026-06-14 deep audit, Medium) — for a non-streaming `send()`, httpx2 buffers the whole body before httpware reaches the decode seam, so a true cap needs a streaming-with-capped-accumulator rework of the Seam-A terminal. The current `max_error_body_bytes` guard only applies at `stream()` entry and only when `Content-Length` is declared. Revisit trigger: the Seam-A terminal is next reworked, or a concrete large-response abuse is reported. (`src/httpware/client.py`)

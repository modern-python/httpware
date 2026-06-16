# Deferred Work

Items raised in reviews that are real but not actionable now.

As of 0.7.0, all planned epics (3, 4, 5, 6) are closed — see the [change Index](README.md). The Open section below is the long-tail register: items that remain technically real but depend on speculative future work, so they're parked here pending a concrete trigger.

## Open

### Resilience

- **CircuitBreaker v2 — remaining axes** (`src/httpware/middleware/resilience/circuit_breaker.py`) — 0.13.0 shipped axis **(a)**, the opt-in **time-based** failure-rate trip mode (`failure_rate_threshold` + `window_seconds` + `minimum_calls`; classic stays default). Still open, each independent and demand-gated:

  - **Count-based window variant** — a `window_type="count"` selector (ring buffer of the last N outcomes) alongside the shipped time-based window. Resilience4j offers both; we chose time-based first as the better HTTP-service fit. Additive: a new window-type knob, time-based remaining the default. Build if someone needs volume-relative (not time-relative) windows.
  - **(b) Manual control + read-only `state`** — `force_open`/`force_closed` and a `state` introspection property (Resilience4j's registry, Polly's `StateProvider`/`ManualControl`). Parked as YAGNI in the 0.10.0 audit (decision 4: events-only control surface). Independent of the trip mode.
  - **(c) Slow-call-rate dimension** — *don't*: Resilience4j-only, and redundant with `AsyncTimeout`. Recorded here only so a future reader doesn't re-propose it.

  **Don't regress:** httpware's HTTP-native failure classification (429/4xx = success out of the box) is already ahead of the generic-predicate breakers — preserve it in any v2 work.

### Documentation

- **Non-streaming hard response-body cap** (2026-06-14 deep audit, Medium) — for a non-streaming `send()`, httpx2 buffers the whole body before httpware reaches the decode seam, so a true cap needs a streaming-with-capped-accumulator rework of the Seam-A terminal. The current `max_error_body_bytes` guard only applies at `stream()` entry and only when `Content-Length` is declared. Revisit trigger: the Seam-A terminal is next reworked, or a concrete large-response abuse is reported. (`src/httpware/client.py`)

# Deferred Work

Items raised in reviews that are real but not actionable now.

As of 0.7.0, all planned epics (3, 4, 5, 6) are closed — see the [change Index](README.md). The Open section below is the long-tail register: items that remain technically real but depend on speculative future work, so they're parked here pending a concrete trigger.

## Open

### Client API surface

- **Per-verb-with-response siblings** (`get_with_response`, `post_with_response`, `request_with_response`) — the v0.8.2 spec deliberately ships only `send_with_response`; the verb-method shape would add ~400 LOC of overload boilerplate per side for a pattern (response headers + typed body) that's almost always paired with a GET and `build_request`. Revisit if a concrete consumer demand surfaces. (`src/httpware/client.py`)

### Resilience

- **CircuitBreaker v2 — rolling-window / failure-rate mode** (`src/httpware/middleware/resilience/circuit_breaker.py`) — the 0.10.0 breaker ships only the *classic consecutive-failure* model (open after N counted failures in a row; any success resets the streak). That can't catch *partial* degradation (e.g. a steady 50% error rate that alternates success/fail never trips). Deferred to v2 in the 0.10.0 spec; the config was shaped so a rate mode is purely additive (a new opt-in `failure_rate_threshold` + window + `minimum_calls`, with classic remaining the default). Demand-gated: build when someone needs rate-based tripping.

  **Comparison with the reference implementations** (verified against current docs, 2026-06-13):

  | Axis | httpware v1 (shipped) | Resilience4j | Polly v8 |
  |---|---|---|---|
  | Trip model | consecutive count (`failure_threshold=5`) | failure **rate** over sliding window (`failureRateThreshold=50%`) | failure **rate** over time window (`FailureRatio=0.1`) |
  | Window | none (one counter) | count-based (default, size 100) *or* time-based | time-based only (`SamplingDuration=30s`) |
  | Min-volume floor | n/a | `minimumNumberOfCalls=100` | `MinimumThroughput=100` |
  | Consecutive-count mode | only mode | non-default | **removed in v8** (was v7 default) |
  | Half-open recovery | one probe, `success_threshold` consecutive successes (default 1) | permits N calls (default 10), closes on rate over them | one trial call, success→close (≈ httpware default) |
  | OPEN→HALF_OPEN | lazy (next request) | lazy, or optional timer (`automaticTransition…`) | lazy (next request after `BreakDuration=5s`) |
  | Failure classification | HTTP-native: `failure_status_codes` (5xx), **429/4xx = success** | generic exception predicate (`recordExceptions`/`ignoreExceptions`) | generic predicate (`ShouldHandle`, default all except cancellation) |
  | Slow-call trip axis | none (latency is `AsyncTimeout`'s job) | yes — `slowCallRateThreshold` (100%) / `slowCallDurationThreshold` (60s) | none |
  | Control surface | events-only (no `state`/`reset`/`isolate` — audit decision 4) | registry: state + metrics + manual transitions | `StateProvider` (read) + `ManualControl` (Isolate/Close) |

  **Takeaways for scoping v2:** (1) Polly v8 *deleted* consecutive-count; Resilience4j doesn't default to it — so httpware v1's only mode is the one both treat as legacy/non-default. Adding rate mode while *keeping* classic is a small edge neither offers. (2) "Polly-v8-equivalent" = just the rate-over-window mode. "Resilience4j-equivalent" additionally implies count-vs-time window choice and (separately) manual control + state introspection. (3) httpware's HTTP-native classification (429-as-success out of the box) is already *ahead* of both generic-predicate libraries — don't regress it. (4) Skip the slow-call axis (Resilience4j-only; redundant with `AsyncTimeout`).

  Three separable additions, rough priority: **(a) rate-over-window trip mode** (the core ask; additive opt-in), **(b) manual control + read-only `state`** (independent; both libraries have it, httpware parked it as YAGNI), **(c) slow-call-rate dimension** (don't — covered by `AsyncTimeout`).

  **Concurrency note:** the window recorder (ring buffer for count-based; time-bucketed counters for time-based) is more state than v1's single counter, but recording an outcome stays a synchronous mutation, so the async lock-free atomicity invariant and the sync `threading.Lock` both still hold. Time-based eviction must read `_now()` inside the same synchronous critical section.

### Documentation

- **Custom-`ResponseDecoder` guide** (audit finding G6, [2026-06-13 docs audit](audits/2026-06-13-docs-audit.md)) — the decoder seam (Seam B) is a documented extension point, but unlike middleware it has no "write your own" guide. A short page would show the `can_decode(model: type) -> bool` / `decode(content: bytes, model: type[T]) -> T` protocol, how `decoders=[...]` ordering resolves a model, and a worked third-party-adapter example. Decided alongside the `2026-06-14.01` docs-UX restructure: **defer the guide, and ship no auto API reference / mkdocstrings** (prose carries the signatures). Demand-gated. Revisit trigger: someone asks how to write a custom decoder, a third-party decoder adapter ships, or the `decoders/` protocol surface changes. (`docs/`, `src/httpware/decoders/`)

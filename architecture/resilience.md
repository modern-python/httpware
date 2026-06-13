# Resilience

`httpware` ships a resilience suite under `httpware.middleware.resilience`, composed via the standard middleware chain (Seam A). It is pure stdlib — no optional extra.

## Retry + RetryBudget

`Retry` (and `AsyncRetry`) is a retry middleware backed by a Finagle-style `RetryBudget` — a token bucket that caps the proportion of traffic spent on retries so a degraded backend cannot be amplified into a retry storm. `RetryBudget` is a single thread-safe class shared by both worlds. Backoff between attempts uses full-jitter.

## Bulkhead

`Bulkhead` / `AsyncBulkhead` is a concurrency limiter. `AsyncBulkhead` uses `asyncio.Semaphore` with a bounded acquire wait; sync `Bulkhead` uses `threading.Semaphore`. A sync instance cannot share with an async one. Both are sharable across clients (one instance = one shared concurrency pool).

## CircuitBreaker + AsyncTimeout

`AsyncCircuitBreaker` and sync `CircuitBreaker` are a classic consecutive-failure circuit breaker: the circuit opens after `failure_threshold` consecutive counted failures, fast-fails while OPEN, admits one probe after `reset_timeout` (HALF_OPEN), and closes again after `success_threshold` consecutive probe successes; a probe failure re-opens it. A *counted failure* is a `NetworkError`, an httpware `TimeoutError`, or a `StatusError` whose `status_code` is in the effective failure set (default: all 5xx, 500–599); 4xx including 429 count as successes, and any other exception type propagates unchanged without affecting circuit state. When the breaker refuses a request — OPEN, or HALF_OPEN with the single probe slot already taken — it raises `CircuitOpenError` and never forwards to `next`; the error's `retry_after` carries the seconds until the next probe will be admitted, or `None` when a concurrent probe is already in flight. A breaker instance is sharable across clients (one shared circuit); a sync instance cannot be shared with an async one.

`AsyncTimeout` is an async-only middleware that bounds the total wall-clock for the whole inner pipeline (most importantly across an `AsyncRetry` loop, whose attempts and backoff sleeps `httpx2` cannot bound). It is not a per-call timeout — `httpx2`'s connect/read/write/pool timeouts are the right tool for a single outbound call, and `AsyncTimeout` does not duplicate them. It rejects a non-finite or non-positive `timeout` at construction, and on expiry raises httpware `TimeoutError`. There is no sync `Timeout`: a sync total-deadline cannot interrupt a blocking call mid-flight, and `httpx2` already covers sync per-call timeouts. Sync callers configure `httpx2`'s timeouts directly.

The recommended (documented, not enforced) composition order is `AsyncTimeout → AsyncCircuitBreaker → AsyncBulkhead → AsyncRetry → terminal`. With the breaker outside retry, an open circuit short-circuits the entire retry loop and the breaker counts one outcome per fully-exhausted retry sequence rather than per attempt.

## Observability

`Retry`, `Bulkhead`, `CircuitBreaker`, and `AsyncTimeout` emit operational events via stdlib `logging` records on dedicated loggers (`httpware.retry`, `httpware.bulkhead`, `httpware.circuit_breaker`, `httpware.timeout`) and — when `opentelemetry-api` is installed — OpenTelemetry span events on the active span via `trace.get_current_span().add_event(...)`. The circuit-breaker and timeout event names (`circuit.opened`, `circuit.rejected`, `circuit.half_open`, `circuit.closed`, `timeout.exceeded`) join `retry.*` / `bulkhead.*` as the stable observability surface; renames are breaking changes.

# Circuit breaker scope: time-based window, no slow-call rate, no manual control

Rate mode uses a rolling `window_seconds` gated by `minimum_calls`. A count-based "last N calls"
window was rejected because on low traffic it reaches back past deploys and recoveries, and
`minimum_calls` already supplies the sample-size guarantee. A slow-call rate is not added because a
deadline already turns a slow call into a counted failure, provided the breaker sits outside the
deadline. That holds in the recommended order, `AsyncCircuitBreaker → AsyncTimeout → AsyncBulkhead
→ AsyncRetry`: an expired `AsyncTimeout` raises httpware `TimeoutError` through the breaker, which
counts it. With `AsyncTimeout` outside the breaker, the deadline cancels the breaker's call, the
breaker sees `CancelledError`, which it does not count, and a hanging upstream never opens the
circuit. httpware documents this order but does not enforce it, so the argument covers only callers
who follow it. httpx2's per-request timeouts are raised inside the breaker in any order, and they
are the only deadline on the sync side. `force_open()` / `force_closed()` in the style of Polly's
`ManualControl` were declined in [#118](https://github.com/modern-python/httpware/issues/118):
breaker state is per process, so pinning one replica sheds nothing fleet-wide, and the fixes that do
work, a config flag read by every replica or state in Redis, reduce to a check the caller makes
before sending or to I/O inside a transition.

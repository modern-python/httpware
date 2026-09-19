# Circuit breaker scope: time-based window, no slow-call rate, no manual control

Rate mode uses a rolling `window_seconds` gated by `minimum_calls`. A count-based "last N calls"
window was rejected because on low traffic it reaches back past deploys and recoveries, and
`minimum_calls` already supplies the sample-size guarantee. A slow-call rate is not added because
`AsyncTimeout` already converts a slow call into a counted `TimeoutError`. `force_open()` /
`force_closed()` in the style of Polly's `ManualControl` were declined in
[#118](https://github.com/modern-python/httpware/issues/118): breaker state is per process, so
pinning one replica sheds nothing fleet-wide, and the fixes that do work, a config flag read by every
replica or state in Redis, reduce to a check the caller makes before sending or to I/O inside a
transition.

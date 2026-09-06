# The failure-rate window is time-based; no count-based window, no slow-call rate

**Decision:** the opt-in failure-rate mode observes a rolling `window_seconds` window gated by
`minimum_calls`. A count-based window (`window_type="count"`, "the last N calls") and a
slow-call-rate dimension are both declined.

Count-based is the recurring proposal, on the grounds that a fixed sample size makes the rate
statistically meaningful at low traffic. `minimum_calls` already supplies that guarantee, and it
supplies it without the staleness a count window introduces: "the last 20 calls" on a low-traffic
client can reach back minutes, so the breaker ends up deciding present health from outcomes that
predate a deploy or a recovery. For a spiky, low-volume backend the right adjustment is a longer
`window_seconds` with a suitable `minimum_calls`, which stays time-anchored. The ecosystem agrees:
Polly v8 removed its count-based window, and Hystrix and Envoy are time-based.

Slow-call rate — tripping on calls that complete but exceed a latency threshold — is
Resilience4j-only and is already covered here by `AsyncTimeout`, which converts a slow call into
an httpware `TimeoutError`, which is a counted failure. Adding a second latency dimension inside
the breaker would mean two places to configure the same threshold and two ways for them to
disagree.

**Revisit trigger:** concrete Resilience4j-parity demand from a user migrating a real deployment,
naming a behaviour `window_seconds` + `minimum_calls` + `AsyncTimeout` cannot express.

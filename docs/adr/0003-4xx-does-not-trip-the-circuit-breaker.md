# 4xx, including 429, counts as a circuit-breaker success

The default failure set is 5xx only. A 429 means the backend is up and throttling, and a 404 or 422
describes the request, so tripping on either turns a healthy service into an outage for every caller
of a shared breaker. Exceptions other than `NetworkError`, httpware `TimeoutError`, and `StatusError`
leave circuit state untouched, so the breaker cannot trip on load-shedding it caused itself.
`failure_status_codes` is the per-deployment override, not a default worth flipping.

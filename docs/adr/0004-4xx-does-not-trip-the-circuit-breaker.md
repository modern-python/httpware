# 4xx, including 429, counts as a circuit-breaker success

**Decision:** the breaker's default failure set is 5xx only. A 429 is a *success* for circuit
accounting, as is every other 4xx, and any exception type outside `NetworkError` / httpware
`TimeoutError` / `StatusError` propagates without touching circuit state.

The generic breakers httpware is measured against take a predicate over "did the call fail", and
under that framing a 429 is obviously a failure — the caller did not get their response. Applying
that framing to HTTP inverts the mechanism it is part of. 429 means the backend is *up*, is
answering, and is telling the client to slow down; opening the circuit on it converts a
throttling signal into a total outage for that client, and the retry-and-backoff path that already
handles 429 correctly never gets to run. The same holds for the rest of 4xx: a 404 or a 422 is a
statement about the request, and a caller sending malformed requests in a loop should not be able
to trip a shared breaker for every other caller of a perfectly healthy service.

The non-`StatusError` half of the rule is the same argument from the other side. `BulkheadFullError`
and `CircuitOpenError` are httpware's own back-pressure, and `ValueError` is a bug in the caller;
counting any of them would let the breaker trip on load-shedding it caused itself.

`failure_status_codes` exists for callers whose backend genuinely encodes health in a 4xx. That
is a per-deployment override, not a default worth flipping.

**Revisit trigger:** a documented HTTP-native breaker (Envoy, Polly, Resilience4j) shipping 4xx in
its *default* failure set, or a report where the 5xx-only default demonstrably failed to protect a
caller that `failure_status_codes` could not fix.

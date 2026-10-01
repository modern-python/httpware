# Resilience demos

Interactive walk-throughs of each resilience pattern under load. Each one runs a
plain client and an httpware client through the same outage side by side, and pauses
to point out what changes.

- [Circuit breaker](circuit-breaker.md): stop sending requests to a dead backend.
- [Retry and retry budget](retry.md): recover from blips without causing a retry storm.
- [Bulkhead](bulkhead.md): keep one slow dependency from taking down the client.
- [Timeout](timeout.md): bound total latency across retries.
- [Full stack](full-stack.md): how the patterns combine.

!!! note
    The demos simulate httpware's behavior for teaching; httpware itself is not
    running in your browser. See [Resilience](../resilience.md) for the real API.

# Resilience demos

Interactive, self-contained walk-throughs of each resilience pattern under load.
Each runs a plain client and an httpware client through the **same** outage, side by
side, and pauses to point out exactly what changes.

- [Circuit Breaker](circuit-breaker.md) — stop hammering a dead backend
- [Retry + Budget](retry.md) — rescue blips without causing a storm
- [Bulkhead](bulkhead.md) — contain one slow dependency
- [Timeout](timeout.md) — bound total latency across retries
- [Full stack](full-stack.md) — how they compose

!!! note
    These are a faithful **model** of httpware's behavior for teaching, not httpware
    running in your browser. See [Resilience](../resilience.md) for the real API.

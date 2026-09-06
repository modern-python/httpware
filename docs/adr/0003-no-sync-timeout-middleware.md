# No sync `Timeout`: the total deadline is async-only

**Decision:** `AsyncTimeout` has no sync sibling. This is the one deliberate break from sync/async
parity in the project.

`AsyncTimeout` bounds total wall-clock across everything `next` wraps — most importantly across an
`AsyncRetry` loop, whose attempts and backoff sleeps `httpx2` cannot bound. A sync `Timeout` was
specified alongside it and dropped: sync Python has no way to interrupt a blocking call
mid-flight. The only implementations available are a watchdog thread that cannot actually stop the
work, or a check between attempts that silently does nothing during the call it is supposed to
bound. Both ship a name that promises a deadline and delivers a suggestion, which is worse than
not shipping it — a caller who believes a request is bounded builds a queue depth on that belief.

Sync callers are not without a tool: `httpx2`'s connect/read/write/pool timeouts bound each
outbound call, and configuring them is the documented sync answer. `AsyncTimeout` deliberately
does not duplicate those; it exists for the span *between* calls that `httpx2` cannot see.

The cost is a real asymmetry in the resilience suite, and it is the reason parity is a
hand-maintained invariant with a named exception rather than a mechanical one — see
`tests/test_client_parity.py`.

**Revisit trigger:** a sync cancellation mechanism that can actually interrupt a blocking socket
read from another thread lands in CPython or in `httpx2`. Free-threading alone does not supply
one.

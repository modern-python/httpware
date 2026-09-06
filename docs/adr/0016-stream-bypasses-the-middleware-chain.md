# `stream()` bypasses the middleware chain

**Decision:** `Client.stream()` and `AsyncClient.stream()` do not run the middleware chain. An
`apply_middleware=` flag, and a `request.extensions["httpware.stream"]` marker that middleware
would learn to respect, were both rejected.

This is the most surprising thing httpware does, and the question it prompts — "why doesn't my
`Retry` apply to `stream()`?" — has a structural answer rather than an ergonomic one. The
middleware protocol is typed on a fully-buffered `httpx2.Response`, and buffering is not a detail
of that signature but the thing that makes it usable: a middleware inspects the response, and for a
streaming response inspecting `.content` *consumes* the stream the caller asked for. Every
middleware ever written against this protocol — including the built-in resilience suite — assumes
it holds a response it may read. Passing it one it may not read does not extend the protocol; it
breaks the contract silently, and the breakage surfaces in the caller's iteration loop rather than
in the middleware that caused it.

The `extensions` marker is the version that acknowledges this, and it is worse. It converts one
protocol into two — a middleware must now branch on whether it may touch the body — and the cost
lands on every third-party middleware, including ones written before the marker existed, which
would keep type-checking while quietly mishandling streams. Making streaming work through the chain
is a per-middleware stream-awareness policy, not a flag on the client.

`Retry`'s separate refusal to retry a request with a streamed *body* is the same constraint seen
from the other end: a non-replayable body cannot be sent twice, so the middleware declines rather
than retrying something it cannot faithfully repeat.

What `stream()` does keep is the part that does not require buffering the caller's body: 4xx/5xx
still raise the matching `StatusError`, with the error body pre-read so `exc.response.content`
works, and that pre-read is bounded by `max_response_body_bytes` (ADR 0015).

**Revisit trigger:** a middleware protocol that is explicitly typed on an unbuffered response —
i.e. a second, stream-aware protocol added deliberately, not a flag threaded through this one.

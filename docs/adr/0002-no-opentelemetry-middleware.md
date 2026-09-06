# No OpenTelemetry tracing middleware

**Decision:** httpware does not ship an OTel middleware that creates spans. It only *adds events*
to whatever span is already active, and points users at
`opentelemetry-instrumentation-httpx` for the spans themselves.

A tracing middleware is the first thing anyone proposes when they see the `otel` extra. It would
duplicate an instrumentation that already exists, is maintained by the OTel project, and covers
strictly more: the instrumentor wraps the transport, so it sees redirects, retries at the
connection level, and connection reuse — all below httpware's chain, where a middleware cannot
observe them. Two span-creating layers over the same call also produce a doubled span tree that
users then have to configure one of them out of.

The events httpware does emit are the complement, not a subset: `retry.*`, `bulkhead.*`,
`circuit.*` and `timeout.*` describe decisions made *above* the transport, which the instrumentor
has no way to see. `_internal/observability.py` attaches them to `trace.get_current_span()` and
does not create a span of its own; if nothing else started one, they still land as log records.
That is why the `otel` extra is `opentelemetry-api` and not the SDK — httpware is a producer of
events, never a configurer of tracing.

**Revisit trigger:** `opentelemetry-instrumentation-httpx` stops supporting `httpx2`, or httpware
gains a request path that does not go through the wrapped `httpx2` client and therefore produces
no instrumented span at all.

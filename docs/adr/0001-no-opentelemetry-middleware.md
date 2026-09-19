# No OpenTelemetry tracing middleware

httpware ships an `otel` extra but no span-creating middleware. `opentelemetry-instrumentation-httpx`
already wraps the transport and sees redirects, connection reuse, and transport-level retries that a
middleware cannot, and a second span layer would double the tree. httpware only adds `retry.*`,
`bulkhead.*`, `circuit.*`, and `timeout.*` events to the active span, which is why the extra depends
on `opentelemetry-api` and not the SDK.

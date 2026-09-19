# The body cap counts decoded bytes

`max_response_body_bytes` counts decoded bytes accumulated through a streaming read, on every
status. `Content-Length` may reject early but never admit early, because it reports the compressed
size and a 1000:1 gzip bomb passes a header check by construction. It replaced an error-only
pre-check, since memory exhaustion has no status code, and it never applies to caller-driven
`stream()` iteration, whose purpose is bodies too large to buffer. The rebuild through
`httpx2.Response(content=...)` uses only public API and loses `response.elapsed` when a cap is set.
That was accepted over reaching into httpx2 internals.

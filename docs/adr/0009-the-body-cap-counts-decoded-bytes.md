# The body cap counts decoded bytes

`max_response_body_bytes` counts decoded bytes accumulated through a streaming read, on every
status. `Content-Length` may reject early but never admit early, because it reports the compressed
size and a 1000:1 gzip bomb passes a header check by construction. It replaced an error-only
pre-check, since memory exhaustion has no status code, and it never applies to caller-driven
`stream()` iteration, whose purpose is bodies too large to buffer. The response is rebuilt
through `httpx2.Response(content=...)` with public API only: `elapsed`, `next_request` and
`default_encoding` are copied over, and `num_bytes_downloaded`, which has no public setter, reads 0.
Counting bytes in a wrapper around the response stream would avoid the rebuild; that is deferred to
[#170](https://github.com/modern-python/httpware/issues/170).

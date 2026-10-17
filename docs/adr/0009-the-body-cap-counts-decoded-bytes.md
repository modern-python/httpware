# The body cap counts decoded bytes

`max_response_body_bytes` counts decoded bytes accumulated through a streaming read, on every
status. `Content-Length` may reject early but never admit early, because it reports the compressed
size and a 1000:1 gzip bomb passes a header check by construction. It replaced an error-only
pre-check, since memory exhaustion has no status code, and it never applies to caller-driven
`stream()` iteration, whose purpose is bodies too large to buffer. For a body with no
`Content-Encoding` the decoded bytes are the wire bytes, so the cap wraps the public
`Response.stream` in a stream that counts bytes and raises once the count passes the cap, and httpx2
reads the response with its own `read()`. The response stays the one httpx2 built. An encoded body
is read through `iter_bytes()` and rebuilt with `httpx2.Response(content=...)`, using public API
only: `elapsed`, `next_request` and `default_encoding` are copied over, and `num_bytes_downloaded`,
which has no public setter, reads 0.

# The body cap counts decoded bytes; `Content-Length` is an early reject, never an early accept

**Decision:** `max_response_body_bytes` is enforced by accumulating *decoded* bytes through a
streaming read, status-agnostic. The declared `Content-Length` may only reject early, never admit
early. Caller-driven `stream()` iteration is never capped. This replaced `max_error_body_bytes`, an
error-only cap implemented as a `Content-Length` pre-check.

A header check is not a cap, and the arithmetic is not close. `Content-Length` reports the
compressed size while the bytes httpware actually buffers are the decoded ones: a 133-byte gzip
body decodes to 100 KB here, and real compression bombs run around 1000:1. A pre-check that trusts
the header therefore waves through precisely the payloads the cap exists to stop, while
successfully blocking the honest large responses nobody was worried about. Keeping the header as an
early *reject* is still worth it — if even the compressed size exceeds the cap, failing before
reading a byte is free — but the accumulator has to run in every other case, which is what catches
chunked responses that declare no length at all.

Scoping the old cap to error responses was the same mistake in a different place. Memory
exhaustion has no status code; a 200 that decodes to a gigabyte exhausts the process exactly as a
500 does. Capping only the error path bolts the smaller door.

The opposite over-reach was also rejected: capping the bytes a caller pulls through `stream()`.
Choosing `stream()` *is* the decision to own that memory, and a cap there would break the one API
whose entire purpose is handling responses too large to buffer. The cap covers what httpware
buffers on the caller's behalf — the non-streaming terminal, and the error-body pre-read that makes
`exc.response.content` work inside `stream()` — and nothing else.

The mechanism uses only public httpx2 API: `send(request, stream=True)` plus rebuilding through
`httpx2.Response(content=...)`. That constructor does not carry `.elapsed`, which httpx2 sets only
on its own buffered `send()`, so a client with a cap set loses `response.elapsed`. This was
accepted rather than fixed by reaching into httpx2 internals, and the `None`-cap fast path keeps
both `.elapsed` and zero streaming overhead.

**Revisit trigger:** httpx2 exposing a supported way to buffer with a byte bound, which would make
the rebuild — and the `.elapsed` loss with it — unnecessary.

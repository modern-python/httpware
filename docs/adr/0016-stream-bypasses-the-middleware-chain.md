# `stream()` bypasses the middleware chain

The middleware protocol is typed on a buffered `httpx2.Response`, and a middleware that reads
`.content` consumes the stream the caller asked for, so the built-in suite and every third-party
middleware would break silently. An `apply_middleware=` flag and a `request.extensions` marker were
rejected because both turn one protocol into two that existing middleware would mishandle while
still type-checking. 4xx and 5xx still raise `StatusError` with a pre-read error body bounded by the
cap ([ADR-0015](0015-the-body-cap-counts-decoded-bytes.md)). Streaming through the chain needs a
second, explicitly stream-aware protocol, not a flag.

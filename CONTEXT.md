# httpware

A thin, opinionated wrapper around `httpx2`: it re-exports `httpx2.Request` and
`httpx2.Response` as the public request/response surface and adds three things —
a middleware chain composed at client construction, typed response decoding, and
a status-keyed exception tree raised automatically on 4xx and 5xx. `Client` and
`AsyncClient` carry the same features.

## Language

A term is listed only when there is a synonym to reject, or a meaning subtle enough that code and
docs must agree on it. General HTTP and programming vocabulary does not belong here, however
heavily this project uses it. `httpx2`'s own names — `Request`, `Response`, `Timeout`, `Limits`,
`Auth`, `MockTransport` — keep `httpx2`'s meanings; nothing here redefines one.

**Middleware**:
An object satisfying `Middleware` / `AsyncMiddleware`: it takes a request and a continuation
(`Next` / `AsyncNext`) and returns a response. The chain is composed once at client construction
and frozen for the client's lifetime.
_Avoid_: hook — reserved for `httpx2.event_hooks`, a genuinely different mechanism that runs
*below* the chain, once per transport attempt rather than once per logical call.

**Terminal**:
The internal bottom of the middleware chain. It calls `httpx2.Client.send` / `AsyncClient.send`,
maps `httpx2` exceptions to httpware ones, and raises a `StatusError` subclass on 4xx/5xx. It is
private and has no protocol: nothing pluggable lives at the bottom of the chain.
_Avoid_: transport. httpware once shipped a `Transport` protocol and an `Httpx2Transport`; both
were removed when the client became a thin wrapper, and `tests/test_public_api.py` keeps the names
retired. In this repo "transport" is always `httpx2`'s (`httpx2.MockTransport`, transport-level
tracing, `TransportError`).

**Seam**:
A documented *internal* boundary that is crossed only through its protocol. There are exactly
three: **A** client ↔ middleware chain, **B** client ↔ `ResponseDecoder` list, **C** httpware ↔
optional extras. A seam is not an extension point: an extension point is what a user plugs into
(middleware, a custom decoder), while a seam is the boundary the implementation may not reach
across. The letters are cited from module docstrings, so they must not be renumbered casually.

**Decoder**:
An object satisfying `ResponseDecoder` — `can_decode(model)` to claim a model, `decode(content,
model)` to turn raw bytes into it in a single parse pass.
_Avoid_: adapter, which names the third-party object a decoder builds and memoizes per model
(`pydantic.TypeAdapter`, `msgspec.json.Decoder`). Calling the decoder an adapter too leaves
"the adapter cache" ambiguous about which of the two it caches.

**Counted failure**:
The circuit breaker's unit of account: a `NetworkError`, an httpware `TimeoutError`, or a
`StatusError` whose status is in the effective failure set (default: all 5xx). Every other 4xx —
429 included — counts as a *success*, and any other exception type propagates without touching
circuit state. "Failure" alone is ambiguous here: a failed request is very often not a counted
failure.

**Cap**:
`max_response_body_bytes` — the bound on how many bytes httpware buffers on the caller's behalf.
Counted *decoded*, status-agnostic, and never applied to user-driven `stream()` iteration.
_Avoid_: limit — `limits=` on a client is `httpx2.Limits`, the connection-pool configuration, and
has nothing to do with body size. The one sanctioned exception is public and cannot be renamed
without a breaking change: `ResponseTooLargeError.limit` carries the cap that was exceeded. Prose
says cap; that field says `limit`.

**Event**:
One named operational emission from the resilience middleware (`retry.exhausted`,
`circuit.opened`, …). A single `_emit_event` call fans out to both a stdlib logging record on a
namespaced logger and, when `opentelemetry-api` is installed, a span event on the active span. The
names are a public contract in both renderings: renaming one is a breaking change.

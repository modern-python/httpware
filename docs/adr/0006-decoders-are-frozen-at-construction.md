# The decoder list is client-lifetime; no per-call override, no stdlib fallback

**Decision:** `decoders=` is resolved once at `__init__` and frozen for the client's lifetime.
There is no per-call `decoder=` override, and no built-in stdlib-`json` decoder to fall back on
when no extra is installed.

A per-call override reads as a small ergonomic win and is a second home for routing. Today one
question — "which decoder handles this model?" — has one answer, computed by
`_DecoderResolver.resolve` walking the frozen tuple in order. With a per-call override there are
two dispatch sites to keep in agreement, the ordering semantics of the list stop being the whole
story, and `MissingDecoderError`'s pre-flight check has to reason about a decoder the client has
never seen. The frozen list also mirrors the middleware chain, which is composed at `__init__` for
the same reason; a client whose behaviour is settled at construction is one an agent can reason
about by reading the constructor call.

A stdlib fallback is rejected because it silently changes what `response_model=` means. Its
"decoding" would be `json.loads` plus a cast, so `response_model=User` would hand back a `dict`
that type-checks as a `User` and fails somewhere else entirely. `MissingDecoderError` raised
before the request goes out, naming the registered decoders and the install hint, is the honest
failure: the model cannot be produced, and the caller finds out at the call site.

**Revisit trigger:** a concrete case where one client legitimately needs different decoders per
request and cannot be expressed as two clients over a shared `httpx2` client.

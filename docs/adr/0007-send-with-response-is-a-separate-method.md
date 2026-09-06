# `*_with_response` is a separate method, not a flag on `send`

**Decision:** returning `(response, decoded)` is a distinct method name —
`send_with_response` and its per-verb siblings — not
`send(request, *, response_model=M, with_response=True)`.

The flag was the proposal-stage design and is the cheaper diff: one method, one more keyword. It
was rejected because it mixes *shape* with *mode*. `send` has exactly two overloads today, each
returning a single clean value (`httpx2.Response` or `T`); a third, flag-driven conditional return
means every reader of a `send` call has to look up what `with_response=True` does before they know
the type in front of them. A separate name is self-describing at the call site, and it is the name
that shows up in a traceback, in autocomplete, and in a grep for who needs response metadata.

The cost is real and was accepted: more public names, and a caller who wants headers *and* a typed
body from a verb-shaped call has to drop to `build_request` + `send_with_response`. The per-verb
`*_with_response` siblings later closed most of that gap for the verbs where it mattered; `head`
and `options` still have none, because a typed body from either is not a real case —
`request_with_response` covers them.

**Revisit trigger:** the `_with_response` surface needing a third axis (e.g. a raw-bytes variant),
at which point the multiplication of names is worse than one flag and the whole family should be
redesigned together.

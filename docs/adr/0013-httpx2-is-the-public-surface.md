# `httpx2` is the public surface, not an implementation detail

**Decision:** httpware re-exports `httpx2.Request` and `httpx2.Response` and owns no
request/response types of its own. The 0.1.0 design — httpware's own `Request`, `Response`,
`StreamResponse`, a `ClientConfig`/`Timeout`/`Limits` configuration layer, an auth-coercion layer,
and a `Transport` protocol with an `Httpx2Transport` implementation — was withdrawn in 0.2.0 and
is not coming back.

Wrapping the underlying client is the default instinct for a library like this, and each piece of
that layer was individually defensible: a stable surface if httpx2 changes, a place to validate
configuration, freedom to swap the HTTP backend. The sum cost far more than the parts returned.
Two type systems had to be kept in agreement across every httpx2 upgrade, and every feature httpx2
gained arrived at httpware's border needing a translation before anyone could use it. The
abstraction also charged its highest price to the users best equipped to skip it: people who
already know httpx had to learn a second vocabulary for objects they could already handle.

Exposing `httpx2.Response` also turned out to be what makes the error tree cheap. Because
`StatusError` carries the real response, a caught error already offers
`exc.response.request.url`, the headers, the content and the extensions — full context that
httpware defines not one field of. A wrapper would have had to re-expose each of those by hand and
would still have lagged whatever httpx2 added next.

The pivot cut the seams from five to three and `src/httpware/` from fourteen modules to eight. It
also retired a CI invariant that had forbidden `httpx2` imports outside `transports/httpx2.py`;
that rule was deliberately deleted rather than left unenforced, because under this design an
`httpx2` import is correct everywhere. What replaced it is narrower and still live:
`tests/test_public_api.py::test_no_removed_symbols_leaked` keeps the withdrawn names — `Request`,
`Response`, `StreamResponse`, `ClientConfig`, `Transport`, `Httpx2Transport`, `AuthValue` and the
rest — from reappearing at the top level.

The accepted cost is real: an httpx2 major version is a breaking change for httpware, and there is
no seam at which to absorb one. That is the trade the thinness is bought with.

**Revisit trigger:** a second HTTP backend that httpware must support simultaneously, rather than
migrate to. Supporting one successor by moving to it is a version bump, not a reason to reintroduce
the abstraction.

# Every httpx2 client option is forwarded

`Client` and `AsyncClient` forward every keyword of the `httpx2` client constructor to the client
they build and own, typed through `**kwargs: Unpack[TypedDict]`. Forwarding a hand-picked subset
made one missing option, such as `verify`, cost the caller the whole construction: they had to
build the `httpx2` client themselves, move every other option onto it, and close it themselves. A
named parameter per option was rejected because each one had to be listed three times, and an
untyped `httpx2_client_kwargs=` dict because it gives up the checking that the TypedDict keeps.
Two options are refused: `cert`, deprecated by httpx2 in favour of an `ssl.SSLContext` passed as
`verify`, and `event_hooks`, which run below the middleware chain, so an `httpx2.HTTPError` raised
in a hook reaches retry and the circuit breaker as a `TransportError`. `follow_redirects=True`
cannot be combined with `max_response_body_bytes`, because httpx2 reads intermediate redirect
bodies without the cap ([ADR-0009](0009-the-body-cap-counts-decoded-bytes.md)). Unset options
(`None`, an empty `base_url`) are dropped rather than forwarded, because `timeout=None` means "the
httpx2 default" to httpware but "no timeout" to httpx2. `ty` does not reject an unknown key under
`Unpack`, so the constructor checks keys at runtime, and
`tests/test_client_options.py::test_options_cover_every_httpx2_client_kwarg_except_excluded` fails
when an httpx2 upgrade adds an option nobody has forwarded or refused.

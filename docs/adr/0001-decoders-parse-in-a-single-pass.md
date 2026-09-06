# Decoders parse raw bytes in a single pass

**Decision:** a `ResponseDecoder` turns response bytes into the model in one parse. Two-pass
decoding — `json.loads()` to a `dict`, then a separate validation step — is rejected for the
built-in decoders and is the documented expectation for third-party ones.

The obvious implementation of `decode` is the two-pass one, because it is how most application
code already validates JSON: parse, then feed the resulting `dict` to the model. It is rejected
because the intermediate `dict` is pure waste on a hot path — every key and value is allocated
once to be immediately discarded — and because both libraries ship a bytes-in/model-out entry
point that is faster than the two steps it replaces. `PydanticDecoder` uses
`TypeAdapter(model).validate_json(content)`; `MsgspecDecoder` uses a per-model
`msgspec.json.Decoder`. The per-model object each of them builds is memoized through the shared
helper in `decoders/_caching.py`, so the cost is paid once per model per decoder instance rather
than once per response.

The rule survives its original rationale: it is now also what keeps error reporting honest. A
single pass means the library's own exception (`pydantic.ValidationError`,
`msgspec.ValidationError`) is what reaches `DecodeError.original`, pointing at the field that
actually failed. A two-pass decoder would surface a JSON syntax error and a validation error as
two unrelated failures from two different layers.

**Revisit trigger:** a model shape that neither library can build a single-pass parser for, where
the only working implementation is parse-then-validate. At that point the rule needs an exception
with a named shape, not a repeal.

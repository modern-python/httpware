# Decoders claim every model their library can build; list order resolves ties

**Decision:** `can_decode` returns True for anything the underlying library can actually build a
parser for, not only for that library's native base class. Narrow claims — `PydanticDecoder`
accepting only `BaseModel` subclasses, `MsgspecDecoder` only `Struct` subclasses — are rejected.
Where two decoders both claim a shape, the order of `decoders=` decides.

Narrow claiming reads as the safe default: each decoder handles its own kind, nothing overlaps,
dispatch is unambiguous. It fails on the models people actually use. `response_model=dict`,
`list[Foo]`, a plain dataclass, `int` — none of these is a `BaseModel` or a `Struct`, so under
narrow claims *no* decoder accepts them and `response_model=` raises `MissingDecoderError` for the
majority of real cases. The user's only recourse would be to write a third catch-all decoder, which
makes the two built-ins a special case of a mechanism they do not participate in.

Broad claiming inverts that, and the overlap it creates is smaller than it looks. Native types
still route correctly without any tie-breaking, because each library genuinely rejects the other's:
msgspec cannot build a parser for a `BaseModel`, and pydantic will not claim a `Struct`. What
actually overlaps is the library-agnostic middle — dataclasses, primitives, generic containers —
where either library would produce an equally correct result, so picking the earlier entry in a
list the user wrote is a defensible answer rather than a coin flip. That also makes the ordering
semantics of `decoders=` load-bearing and worth documenting, which is the same property ADR 0006
relies on when it refuses a per-call override.

The obligation this puts on implementers is that `can_decode` must never raise. It runs inside
`_DecoderResolver.resolve`, which is *outside* the `_BoundDecoder.decode` wrap that turns decoder
failures into `DecodeError` — so an exception escaping a probe escapes the `ClientError` contract
entirely and reaches the caller as whatever the library threw. A decoder that cannot decide must
return False. Both built-ins treat any probe failure as False for exactly this reason. This is a
documented obligation on third-party decoders, not an enforced guard: the alternative, wrapping
every `can_decode` call defensively, would silently convert a broken probe into a wrong routing
decision, which is harder to diagnose than a loud failure.

**Revisit trigger:** two decoders in wide use that both claim a shared shape and produce
*materially different* results for it — at which point list order is choosing semantics, not just
an implementation, and the tie needs a real rule.

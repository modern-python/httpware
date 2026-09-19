# Decoder dispatch is a frozen ordered list with broad claims

`decoders=` is resolved once at `__init__` and walked in order by `_DecoderResolver.resolve`. There
is no per-call override, which would be a second dispatch site the pre-flight `MissingDecoderError`
check cannot see, and no stdlib `json` fallback, which would return a `dict` that type-checks as the
model. Each decoder claims every model its library can parse, not only its native base class,
because narrow claims reject `dict`, `list[Foo]`, dataclasses, and primitives; native types still
route unambiguously since each library rejects the other's, and list order settles the
library-agnostic middle. `can_decode` runs outside the `DecodeError` wrap and must return False
rather than raise. A defensive wrap was rejected because it would turn a broken probe into a silent
misroute.

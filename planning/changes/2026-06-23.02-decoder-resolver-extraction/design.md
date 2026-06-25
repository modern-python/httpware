---
summary: Extract a _DecoderResolver (+ generic _BoundDecoder) for Seam B, collapsing the 4-site resolve/raise/decode/wrap smear in client.py.
---

# Design: Extract a `_DecoderResolver` for Seam B

## Summary

The decoder seam (Seam B) is real — two adapters, pydantic and msgspec — but the
logic for *using* it is copy-pasted across four `send` / `send_with_response`
methods on the two clients. This change pulls that logic behind one
`_DecoderResolver` (plus a small generic `_BoundDecoder`) in a new
`decoders/_resolver.py`, so the resolution + pre-flight error + decode-wrapping
live once and the four call sites shrink to `resolve → dispatch → decode`.
Behaviour is unchanged.

## Motivation

- The same ~8-line block appears at `client.py:185`, `:213`, `:1200`, `:1228`:
  walk `_decoders`, raise `MissingDecoderError(registered_names=…)` if none
  claims the model (pre-flight, before the HTTP call), then `decoder.decode(...)`
  wrapping any failure as `DecodeError`. Plus `_dispatch_decoder` defined twice.
- **Depth:** the `ResponseDecoder` protocol is a clean interface, but its *use*
  is shallow — smeared across four call sites instead of behind one module.
  Extracting concentrates it: one place to change the error wording or
  resolution, and a seam testable directly with a fake decoder list (no HTTP).
- **Deletion test:** delete the resolver and the 8-line block reappears in all
  four methods — it concentrates real complexity, so it earns its keep.
  (Contrast `_dispatch_decoder` *today*: a 3-line loop, shallow on its own; the
  win is bundling resolution **with** the pre-flight error and decode-wrapping.)
- Fully synchronous (`can_decode`/`decode` are sync), so **one** resolver shape
  serves both `Client` and `AsyncClient` — no sync/async twins.

## Non-goals

- No behaviour change. Resolution order, the pre-flight `MissingDecoderError`
  (with its `registered_names` snapshot), and `DecodeError` wrapping stay
  byte-identical.
- Not changing the `ResponseDecoder` protocol, the pydantic/msgspec adapters, or
  `_build_default_decoders()` (stays in `client.py`, still tested there).
- Not touching the `decoders=None → defaults` resolution — the resolver takes
  the already-built tuple.

## Design

### 1. `decoders/_resolver.py` — `_DecoderResolver` + `_BoundDecoder`

```python
class _BoundDecoder(Generic[T]):
    """A decoder bound to the model it will decode into."""

    def __init__(self, decoder: ResponseDecoder, model: type[T]) -> None:
        self._decoder = decoder
        self._model = model

    def decode(self, response: httpx2.Response) -> T:
        try:
            return self._decoder.decode(response.content, self._model)
        except Exception as exc:
            raise DecodeError(response=response, model=self._model, original=exc) from exc


class _DecoderResolver:
    """Resolves a response_model to the first claiming decoder; the Seam B orchestrator."""

    def __init__(self, decoders: tuple[ResponseDecoder, ...]) -> None:
        self._decoders = decoders

    def resolve(self, model: type[T]) -> _BoundDecoder[T]:
        for decoder in self._decoders:
            if decoder.can_decode(model):
                return _BoundDecoder(decoder, model)
        raise MissingDecoderError(
            model=model,
            registered_names=tuple(type(d).__name__ for d in self._decoders),
        )
```

`_BoundDecoder` seals the decoder and the model together at resolve time, so a
decoder/model mismatch is unrepresentable downstream; the caller's remaining
knowledge shrinks to "decode this response". Lives in a new private module
inside the decoders subpackage — co-located with the protocol + adapters it
orchestrates, no import cycle (`decoders/` never imports `client`).

### 2. The four call sites collapse

```python
bound = self._decoder_resolver.resolve(response_model)   # pre-flight; may raise MissingDecoderError
response = self._dispatch(request)
return bound.decode(response)                            # post-HTTP; wraps DecodeError
```

`send_with_response` is the same but returns `(response, bound.decode(response))`.
The pre-flight invariant — `MissingDecoderError` before the HTTP call — stays
enforced by call ordering (`resolve` before `_dispatch`), exactly as
`_dispatch_decoder` is called before `_dispatch` today.

### 3. What the clients hold

- Keep `self._decoders` (four test files assert `client._decoders == …` via
  `# noqa: SLF001` — it stays a public-by-convention attribute).
- Add `self._decoder_resolver = _DecoderResolver(self._decoders)` in both
  `__init__`s.
- Remove both `_dispatch_decoder` methods (used nowhere but the four sites).

## Out of scope

- Folding `_build_default_decoders()` into the resolver.
- Any change to streaming (`stream()` never decodes — no `response_model`).

## Testing

- **Parity net:** existing decoder/client suites stay green unchanged —
  `test_decoders_pydantic.py`, `test_decoders_msgspec.py`,
  `test_client_decoders_default.py`, `test_client_construction.py`,
  `test_client_sync.py`, `test_optional_extras_pydantic_missing.py`.
- **New seam tests:** `tests/test_decoder_resolver.py` drives `resolve` /
  `_BoundDecoder.decode` directly with a fake decoder list (no client, no
  `MockTransport`): claiming model → bound that decodes; no claimer →
  `MissingDecoderError` with the right `registered_names` and order; decode
  success; decode raises → `DecodeError` carrying `response` / `model` /
  `original`; first-match-wins ordering across two fakes.
- `just lint` and `just test` both clean (100% coverage gate).

## Risk

- **Behavioural drift** (low × medium): a reordering changes resolution
  precedence or the `registered_names` content. *Mitigation:* extract under the
  green decoder/client suites, which assert defaults, ordering, and error
  identity; do not edit them in this change.
- **Pre-flight ordering regression** (low × medium): `MissingDecoderError` must
  still fire before the HTTP call. *Mitigation:* the call sites keep `resolve`
  strictly before `_dispatch`; existing tests assert no request is sent on a
  missing decoder.
- **Typing** (low × low): `_BoundDecoder` must be `Generic[T]` so `T` flows to
  `send`'s overloads. *Mitigation:* `ty check` in the gate; `send`'s overload
  tests in `test_client_typing.py` cover the surface.

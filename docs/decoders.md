# Decoders

`httpware`'s typed-response extension point is the **`ResponseDecoder` protocol**. A decoder turns raw response bytes into a typed object: when you pass `response_model=` to `send` / `send_with_response`, the client walks its decoder list, picks the first one that claims your model, and hands it the body.

The built-in `PydanticDecoder` and `MsgspecDecoder` are themselves implementations of this protocol; nothing about them is privileged. Reach for a custom decoder when you need a body **format** the built-ins don't speak (CSV, XML, MessagePack, a bespoke binary frame) or a **type system** they don't cover (`attrs`, `marshmallow`, your own class hierarchy). If pydantic or msgspec already decodes your model, you don't need one — see [When NOT to write a decoder](#when-not-to-write-a-decoder).

## The protocol

One symbol, exported from `httpware`:

```python
from typing import Protocol, TypeVar, runtime_checkable

T = TypeVar("T")


@runtime_checkable
class ResponseDecoder(Protocol):
    def can_decode(self, model: type) -> bool: ...
    def decode(self, content: bytes, model: type[T]) -> T: ...
```

Two methods, two distinct jobs:

- **`can_decode(model) -> bool`** — the dispatch predicate. The client walks `decoders=[...]` in order and picks the **first** decoder that returns `True`. Claim every model you can actually handle (broad is correct — list ordering, not narrow predicates, encodes the caller's preference), but **reject another library's native types**: a CSV decoder has no business claiming a `pydantic.BaseModel`. `can_decode` **MUST NOT raise** — it runs at dispatch time, before the HTTP call and *outside* the `DecodeError` wrap that protects `decode`, so an exception here escapes `httpware`'s `ClientError` contract instead of being translated. A decoder that can't decide must return `False` (decline), not raise.
- **`decode(content, model) -> T`** — the decode itself, raw response bytes in, a `model` instance out. Any exception you raise here is caught by the client and wrapped as `httpware.DecodeError` (carrying `response`, `model`, and the `original` exception). You do **not** need to raise `DecodeError` yourself — raise whatever your parser raises and let the seam translate it.

The protocol is `@runtime_checkable` and structural: any object with these two methods satisfies it. You do not subclass anything.

## How the client resolves a model

Both clients take `decoders: Sequence[ResponseDecoder] | None = None`, composed once at `__init__` and frozen for the client's lifetime.

- **Order is preference.** `decoders=[CsvDecoder(), PydanticDecoder()]` asks the CSV decoder first; pydantic only sees models CSV declined. List position is how you disambiguate a shape two decoders could both claim.
- **`decoders=None`** resolves against installed extras — pydantic-first when both are present, either-only when one is, an empty tuple when neither. To *add* a decoder without losing the built-ins, list them explicitly: `decoders=[CsvDecoder(), PydanticDecoder()]`.
- **No claimer is a pre-flight error.** When `response_model=` is set and no decoder claims it, the client raises `MissingDecoderError` **before** sending the request — you find out at wiring time, not after a wasted round-trip. This is distinct from `DecodeError`: `MissingDecoderError` means *nothing handles this model* (fix: install an extra or pass `decoders=[...]`); `DecodeError` means *a decoder ran and the payload was malformed* (fix: the server or the model). See [Errors](errors.md).

## Decoders are sync — for both clients

Unlike middleware, which has separate `AsyncMiddleware` and `Middleware` flavors, there is **one** `ResponseDecoder` protocol, shared by `AsyncClient` and `Client` alike. `decode` is a synchronous method: by the time it runs, the body has already been read off the wire, so decoding is pure CPU work with nothing to await. Write one decoder and pass it to either client.

## Writing your own

### Worked example: a CSV decoder

A decoder for `text/csv` endpoints that returns a `list` of dataclass rows. Both built-ins are JSON, so this is the case they can't cover — and it shows the seam's real shape: raw bytes in, typed object out, no JSON anywhere.

```python
import csv
import dataclasses
import io
import typing

from httpware import AsyncClient
from httpware.decoders.pydantic import PydanticDecoder

T = typing.TypeVar("T")


class CsvDecoder:
    """Decode a text/csv body into a list of dataclass rows.

    Claims only `list[<dataclass>]`; declines everything else so the JSON
    decoders keep their models.
    """

    def can_decode(self, model: type) -> bool:
        if typing.get_origin(model) is not list:
            return False
        args = typing.get_args(model)
        return len(args) == 1 and dataclasses.is_dataclass(args[0])

    def decode(self, content: bytes, model: type[T]) -> T:
        (row_type,) = typing.get_args(model)
        field_types = {f.name: f.type for f in dataclasses.fields(row_type)}
        reader = csv.DictReader(io.StringIO(content.decode("utf-8")))
        return [
            row_type(**{name: field_types[name](value) for name, value in row.items()})
            for row in reader
        ]
```

`can_decode` is total and never raises: a non-`list` model, a bare `list`, or `list[int]` all fall through to `False`. `decode` coerces each CSV cell with its field's type (CSV values arrive as strings) — a real decoder would handle optionals, dates, and missing columns; this is where your domain logic goes. Wire it ahead of the built-ins so it gets first refusal on `list[...]` models while pydantic still handles everything else:

```python
@dataclasses.dataclass
class Sale:
    id: int
    amount: float
    region: str


async def main() -> None:
    async with AsyncClient(
        base_url="https://reports.example.com",
        decoders=[CsvDecoder(), PydanticDecoder()],
    ) as client:
        sales = await client.send(
            client.build_request("GET", "/sales.csv"),
            response_model=list[Sale],
        )
        # sales: list[Sale]
```

The same decoder instance works with a sync `Client(decoders=[CsvDecoder(), PydanticDecoder()])`.

### A note on claiming the right models

`can_decode` is a contract with the *rest of the list*. Claim too broadly and you steal models from decoders behind you; claim too narrowly and your decoder never runs. The rule of thumb: claim exactly the types you natively own, and reject another library's. An adapter for a third-party type system narrows its claim to that system — for example, a [`cattrs`](https://catt.rs)-backed decoder for `attrs` classes:

```python
import json

import attrs


class CattrsDecoder:
    def __init__(self, converter):  # a configured cattrs.Converter
        self._converter = converter

    def can_decode(self, model: type) -> bool:
        return attrs.has(model)  # only attrs classes; everything else declines

    def decode(self, content, model):
        return self._converter.structure(json.loads(content), model)
```

Note this decoder is **two-pass** (`json.loads`, then `structure`). The built-in adapters deliberately decode in a single bytes-in pass (`TypeAdapter.validate_json`, `msgspec.json.Decoder.decode`) to skip the intermediate `dict` allocation — but that's a *performance choice for the built-ins*, not a protocol obligation. A custom decoder may go two-pass when its underlying library only structures from native Python objects; you pay one extra allocation, nothing more.

### When NOT to write a decoder

- **Your model is JSON.** Dataclasses, `TypedDict`s, primitives, pydantic models, and msgspec `Struct`s are all covered by the built-in `PydanticDecoder` / `MsgspecDecoder`. Install the extra (`httpware[pydantic]` or `httpware[msgspec]`) instead of writing a decoder.
- **You only want raw bytes or text.** Don't pass `response_model=` at all — call `send` (or a verb method) without it and read `response.content` / `response.text` directly. Decoders are for *typed* bodies.
- **The transform is per-call, not per-type.** If the shaping depends on the request rather than the model, it's a [middleware](middleware.md) concern, not a decoder.

## See also

- **[`architecture/decoders.md`](https://github.com/modern-python/httpware/blob/main/architecture/decoders.md) (Seam B)** — the formal protocol contract: dispatch order, the `can_decode` no-raise obligation, the single-pass rule, and the per-instance adapter cache.
- **`src/httpware/decoders/pydantic.py` and `msgspec.py`** — the built-in adapters as reference implementations, including how they memoize a `can_decode` verdict and cache the underlying parser per model.
- **[Quick-Start: typed responses](index.md)** — composing `response_model=` with the default decoder list.

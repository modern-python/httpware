# Decoders

A decoder turns raw response bytes into a typed object. When you pass `response_model=` to a request, the client goes through its decoder list, picks the first decoder that accepts your type, and hands it the body.

`PydanticDecoder` and `MsgspecDecoder` implement the same `ResponseDecoder` protocol you would. Write your own when the body is in a format the built-ins can't read (CSV, XML, MessagePack, a custom binary format) or the type comes from a library they don't support (`attrs`, `marshmallow`, your own classes). If pydantic or msgspec already decodes your type, you don't need one; see [When not to write a decoder](#when-not-to-write-a-decoder).

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

`can_decode(model)` decides whether the decoder takes a type. The client asks each decoder in `decoders=[...]` order and uses the first one that returns `True`. Accept every type you can handle and let the list order express the caller's preference, but reject types that belong to another library: a CSV decoder should not accept a `pydantic.BaseModel`. `can_decode` must never raise. It runs before the request and outside the `DecodeError` wrapping that protects `decode`, so an exception there reaches the caller as something other than a `ClientError`. If the decoder can't tell, return `False`.

`decode(content, model)` takes the raw body and returns an instance of `model`. The client wraps any exception it raises in `httpware.DecodeError`, with `response`, `model` and the `original` exception attached, so raise whatever your parser raises.

The protocol is structural and `@runtime_checkable`: any object with these two methods satisfies it, with no base class.

## How the client resolves a model

Both clients take `decoders: Sequence[ResponseDecoder] | None = None`. The list is fixed when the client is built.

- Order is preference. With `decoders=[CsvDecoder(), PydanticDecoder()]`, pydantic only sees the types the CSV decoder declined. When two decoders could both handle a type, the earlier one wins.
- `decoders=None` uses the installed extras: pydantic then msgspec when both are installed, whichever one is installed, or no decoders at all. Passing a list replaces the defaults, so include the built-ins you still want: `decoders=[CsvDecoder(), PydanticDecoder()]`.
- If `response_model=` is set and no decoder accepts it, the client raises `MissingDecoderError` before sending the request. That means nothing handles the type, and the fix is to install an extra or pass `decoders=[...]`. A `DecodeError` instead means a decoder ran and the body didn't fit the type, which points at the server or the model. See [Errors](errors.md).

## One sync protocol for both clients

Middleware comes in sync and async versions, but there is only one `ResponseDecoder` protocol, used by both clients. `decode` is synchronous because the body has already been read when it runs, so there is nothing to await. The same decoder works with either client.

## Writing your own

### Worked example: a CSV decoder

This decoder reads `text/csv` responses into a `list` of dataclass rows. Both built-ins only read JSON, so they can't handle this case.

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
        return [row_type(**{name: field_types[name](value) for name, value in row.items()}) for row in reader]
```

`can_decode` never raises: a non-`list` type, a bare `list` and `list[int]` all return `False`. `decode` converts each CSV cell, which arrives as a string, with its field's type. A real decoder would also handle optional fields, dates and missing columns. Put it before the built-ins so it sees `list[...]` types first, while pydantic still handles everything else:

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

`can_decode` affects the other decoders in the list. Accept too much and you take types from the decoders after yours; accept too little and yours never runs. Accept exactly the types your decoder is for, and reject types from other libraries. A decoder for a third-party type system should accept only that system's types, as in this [`cattrs`](https://catt.rs) decoder for `attrs` classes:

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

This decoder makes two passes: `json.loads`, then `structure`. The built-ins decode straight from bytes (`TypeAdapter.validate_json`, `msgspec.json.Decoder.decode`) to avoid building an intermediate `dict`, but that is only an optimization. Two passes are fine when your library can only work from Python objects; the cost is one extra allocation.

### When not to write a decoder

- The body is JSON. `PydanticDecoder` and `MsgspecDecoder` handle dataclasses, `TypedDict`s, primitives, pydantic models and msgspec `Struct`s. Install `httpware[pydantic]` or `httpware[msgspec]`.
- You want raw bytes or text. Leave out `response_model=` and read `response.content` or `response.text`.
- The shaping depends on the request rather than the type. That belongs in [middleware](middleware.md).

## See also

- [`src/httpware/decoders/`](https://github.com/modern-python/httpware/tree/main/src/httpware/decoders): the built-in decoders, including how they cache `can_decode` results and parsers per type.
- [Quickstart: typed responses](index.md#typed-responses): `response_model=` with the default decoders.

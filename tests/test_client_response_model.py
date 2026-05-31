"""Unit tests for AsyncClient response_model integration with ResponseDecoder."""

from typing import TypeVar

from pydantic import BaseModel

from httpware import AsyncClient, RecordedTransport
from httpware.response import Response


T = TypeVar("T")


def _transport(content: bytes) -> RecordedTransport:
    return RecordedTransport(
        default=Response(
            status=200,
            headers={},
            content=content,
            url="/",
            elapsed=0.0,
        )
    )


class _Item(BaseModel):
    name: str
    qty: int


async def test_response_model_none_returns_raw_response() -> None:
    transport = _transport(content=b'{"name":"x","qty":1}')
    client = AsyncClient(transport=transport)
    result = await client.get("/foo")
    assert isinstance(result, Response)
    assert result.content == b'{"name":"x","qty":1}'


async def test_response_model_invokes_decoder() -> None:
    transport = _transport(content=b'{"name":"x","qty":1}')
    client = AsyncClient(transport=transport)
    result = await client.get("/foo", response_model=_Item)
    assert isinstance(result, _Item)
    assert result == _Item(name="x", qty=1)


async def test_response_model_uses_supplied_decoder() -> None:
    transport = _transport(content=b'{"name":"x","qty":1}')
    seen: list[tuple[bytes, type]] = []

    class _SpyDecoder:
        def decode(self, content: bytes, model: type[T]) -> T:
            seen.append((content, model))
            return model(name="spy", qty=999)

    client = AsyncClient(transport=transport, decoder=_SpyDecoder())
    result = await client.get("/foo", response_model=_Item)
    assert seen == [(b'{"name":"x","qty":1}', _Item)]
    assert isinstance(result, _Item)
    assert result.name == "spy"

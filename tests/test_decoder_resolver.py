"""Seam-level tests for _DecoderResolver / _BoundDecoder.

Drives resolve() and _BoundDecoder.decode() directly with a fake decoder list.
Covers resolution, the pre-flight MissingDecoderError (with registered_names +
ordering), first-match-wins, and DecodeError wrapping. The last tests run both
clients over MockTransport to decode a response a middleware built but never read.
"""

import httpx2
import pytest

from httpware import AsyncClient, Client
from httpware.decoders._resolver import _DecoderResolver
from httpware.errors import DecodeError, MissingDecoderError


class _Wanted:
    pass


class _Other:
    pass


class _FakeDecoder:
    def __init__(
        self,
        claims: set[type],
        *,
        decoded: object = "OK",
        raises: Exception | None = None,
    ) -> None:
        self._claims = claims
        self._decoded = decoded
        self._raises = raises

    def can_decode(self, model: type) -> bool:
        return model in self._claims

    def decode(self, content: bytes, model: type) -> object:  # noqa: ARG002 — fake returns a preset
        if self._raises is not None:
            raise self._raises
        return self._decoded


def _response(content: bytes = b"payload") -> httpx2.Response:
    return httpx2.Response(200, content=content)


def test_resolve_returns_bound_that_decodes() -> None:
    resolver = _DecoderResolver((_FakeDecoder({_Wanted}, decoded="decoded!"),))
    bound = resolver.resolve(_Wanted)
    assert bound.decode(_response()) == "decoded!"


def test_resolve_no_claimer_raises_missing_decoder() -> None:
    resolver = _DecoderResolver((_FakeDecoder({_Other}),))
    with pytest.raises(MissingDecoderError) as ei:
        resolver.resolve(_Wanted)
    assert ei.value.model is _Wanted
    assert ei.value.registered_names == ("_FakeDecoder",)


def test_empty_decoder_tuple_raises_with_empty_names() -> None:
    resolver = _DecoderResolver(())
    with pytest.raises(MissingDecoderError) as ei:
        resolver.resolve(_Wanted)
    assert ei.value.registered_names == ()


def test_first_claiming_decoder_wins() -> None:
    first = _FakeDecoder({_Wanted}, decoded="first")
    second = _FakeDecoder({_Wanted}, decoded="second")
    resolver = _DecoderResolver((first, second))
    assert resolver.resolve(_Wanted).decode(_response()) == "first"


def test_decode_failure_wraps_as_decode_error() -> None:
    boom = ValueError("bad payload")
    resolver = _DecoderResolver((_FakeDecoder({_Wanted}, raises=boom),))
    response = _response(b"garbage")
    with pytest.raises(DecodeError) as ei:
        resolver.resolve(_Wanted).decode(response)
    assert ei.value.response is response
    assert ei.value.model is _Wanted
    assert ei.value.original is boom
    assert ei.value.__cause__ is boom


class _EchoDecoder:
    def can_decode(self, model: type) -> bool:
        return model is bytes

    def decode(self, content: bytes, model: type) -> object:  # noqa: ARG002 — echoes the body
        return content


def _unread_response() -> httpx2.Response:
    return httpx2.Response(200, stream=httpx2.ByteStream(b"streamed"))


def test_bound_decoder_reads_an_unread_response() -> None:
    bound = _DecoderResolver((_EchoDecoder(),)).resolve(bytes)
    assert bound.decode(_unread_response()) == b"streamed"


def _never_called(request: httpx2.Request) -> httpx2.Response:  # pragma: no cover — the request must not go out
    raise AssertionError(request.url)


def test_client_decodes_unread_response_from_middleware() -> None:
    def synthesize(request: httpx2.Request, next: object) -> httpx2.Response:  # noqa: A002, ARG001
        return _unread_response()

    client = Client(
        httpx2_client=httpx2.Client(transport=httpx2.MockTransport(_never_called)),
        decoders=[_EchoDecoder()],
        middleware=[synthesize],
    )
    assert client.get("https://example.test/x", response_model=bytes) == b"streamed"


async def test_async_client_decodes_unread_response_from_middleware() -> None:
    async def synthesize(request: httpx2.Request, next: object) -> httpx2.Response:  # noqa: A002, ARG001
        return _unread_response()

    client = AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=httpx2.MockTransport(_never_called)),
        decoders=[_EchoDecoder()],
        middleware=[synthesize],
    )
    assert await client.get("https://example.test/x", response_model=bytes) == b"streamed"

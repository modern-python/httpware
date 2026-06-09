"""Tests for AsyncClient construction and ownership semantics."""

from unittest.mock import patch

import httpx2
import pytest

from httpware import AsyncClient
from httpware.client import _build_default_decoders
from httpware.decoders.msgspec import MsgspecDecoder
from httpware.decoders.pydantic import PydanticDecoder


def test_construction_with_no_args_works() -> None:
    client = AsyncClient()
    assert isinstance(client, AsyncClient)


def test_construction_with_forwarded_kwargs() -> None:
    client = AsyncClient(
        base_url="https://example.test",
        headers={"x-shared": "1"},
        params={"trace": "yes"},
        timeout=10.0,
    )
    assert isinstance(client, AsyncClient)


def test_construction_with_caller_owned_httpx2_client() -> None:
    transport = httpx2.MockTransport(lambda req: httpx2.Response(200, request=req))
    caller = httpx2.AsyncClient(transport=transport)
    client = AsyncClient(httpx2_client=caller)
    assert isinstance(client, AsyncClient)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"base_url": "https://example.test"},
        {"headers": {"x": "1"}},
        {"params": {"x": "1"}},
        {"cookies": {"x": "1"}},
        {"timeout": 5.0},
        {"limits": httpx2.Limits(max_connections=10)},
        {"auth": httpx2.BasicAuth("u", "p")},
    ],
)
def test_caller_owned_client_with_forwarded_kwargs_is_typeerror(kwargs: dict) -> None:
    transport = httpx2.MockTransport(lambda req: httpx2.Response(200, request=req))
    caller = httpx2.AsyncClient(transport=transport)
    with pytest.raises(TypeError, match="httpx2_client"):
        AsyncClient(httpx2_client=caller, **kwargs)


def test_default_decoder_is_pydantic_decoder() -> None:
    client = AsyncClient()
    assert isinstance(client._decoder, PydanticDecoder)  # noqa: SLF001


def test_explicit_decoder_is_honored() -> None:
    class _Stub:
        def can_decode(self, model: type) -> bool:  # noqa: ARG002  # pragma: no cover
            return True

        def decode(self, content: bytes, model: type) -> object:  # noqa: ARG002  # pragma: no cover
            return None

    client = AsyncClient(decoder=_Stub())
    assert isinstance(client._decoder, _Stub)  # noqa: SLF001


@pytest.mark.parametrize(
    "kwargs",
    [
        {"cookies": {"session": "abc"}},
        {"limits": httpx2.Limits(max_connections=5)},
        {"auth": httpx2.BasicAuth("user", "pass")},
    ],
)
def test_construction_with_optional_forwarded_kwargs(kwargs: dict) -> None:
    """Exercises cookies/limits/auth branches in __init__ when no httpx2_client is supplied."""
    client = AsyncClient(**kwargs)
    assert isinstance(client, AsyncClient)


def test_explicit_middleware_is_honored() -> None:
    captured: list[str] = []

    class _Tag:
        async def __call__(self, request, next) -> httpx2.Response:  # noqa: A002, ANN001  # pragma: no cover
            captured.append("tag")
            return await next(request)

    client = AsyncClient(middleware=(_Tag(),))
    assert client._user_middleware == (client._user_middleware[0],)  # noqa: SLF001
    assert len(client._user_middleware) == 1  # noqa: SLF001


def test_build_default_decoders_both_extras_installed() -> None:
    result = _build_default_decoders()
    assert len(result) == 2  # noqa: PLR2004
    assert isinstance(result[0], PydanticDecoder)
    assert isinstance(result[1], MsgspecDecoder)


def test_build_default_decoders_pydantic_only() -> None:
    with patch("httpware._internal.import_checker.is_msgspec_installed", False):
        result = _build_default_decoders()
    assert len(result) == 1
    assert isinstance(result[0], PydanticDecoder)


def test_build_default_decoders_msgspec_only() -> None:
    with patch("httpware._internal.import_checker.is_pydantic_installed", False):
        result = _build_default_decoders()
    assert len(result) == 1
    assert isinstance(result[0], MsgspecDecoder)


def test_build_default_decoders_neither_installed() -> None:
    with (
        patch("httpware._internal.import_checker.is_pydantic_installed", False),
        patch("httpware._internal.import_checker.is_msgspec_installed", False),
    ):
        result = _build_default_decoders()
    assert result == ()


def test_build_default_decoders_returns_tuple() -> None:
    result = _build_default_decoders()
    assert isinstance(result, tuple)

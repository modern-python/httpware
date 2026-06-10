"""Default decoder resolution under varying extras-installed states.

Covers the behavior matrix in planning/specs/2026-06-09-multi-decoder-design.md
— `AsyncClient()` / `Client()` resolve `decoders=None` against the
`import_checker` flags at __init__ time.
"""

from unittest.mock import patch

from httpware import AsyncClient, Client
from httpware.decoders.msgspec import MsgspecDecoder
from httpware.decoders.pydantic import PydanticDecoder


def test_async_default_both_extras_installed() -> None:
    client = AsyncClient()
    types = tuple(type(d) for d in client._decoders)  # noqa: SLF001
    assert types == (PydanticDecoder, MsgspecDecoder)


def test_async_default_pydantic_only() -> None:
    with patch("httpware._internal.import_checker.is_msgspec_installed", False):
        client = AsyncClient()
    types = tuple(type(d) for d in client._decoders)  # noqa: SLF001
    assert types == (PydanticDecoder,)


def test_async_default_msgspec_only() -> None:
    with patch("httpware._internal.import_checker.is_pydantic_installed", False):
        client = AsyncClient()
    types = tuple(type(d) for d in client._decoders)  # noqa: SLF001
    assert types == (MsgspecDecoder,)


def test_async_default_neither_installed() -> None:
    with (
        patch("httpware._internal.import_checker.is_pydantic_installed", False),
        patch("httpware._internal.import_checker.is_msgspec_installed", False),
    ):
        client = AsyncClient()
    assert client._decoders == ()  # noqa: SLF001


def test_async_empty_explicit_decoders() -> None:
    client = AsyncClient(decoders=[])
    assert client._decoders == ()  # noqa: SLF001


def test_async_explicit_decoders_skip_default_probe() -> None:
    class _Custom:
        def can_decode(self, model: type) -> bool:  # noqa: ARG002  # pragma: no cover
            return True

        def decode(self, content: bytes, model: type) -> object:  # noqa: ARG002  # pragma: no cover
            return None

    custom = _Custom()
    with (
        patch("httpware._internal.import_checker.is_pydantic_installed", False),
        patch("httpware._internal.import_checker.is_msgspec_installed", False),
    ):
        client = AsyncClient(decoders=[custom])
    assert client._decoders == (custom,)  # noqa: SLF001


def test_sync_default_both_extras_installed() -> None:
    client = Client()
    types = tuple(type(d) for d in client._decoders)  # noqa: SLF001
    assert types == (PydanticDecoder, MsgspecDecoder)
    client.close()


def test_sync_default_pydantic_only() -> None:
    with patch("httpware._internal.import_checker.is_msgspec_installed", False):
        client = Client()
    types = tuple(type(d) for d in client._decoders)  # noqa: SLF001
    assert types == (PydanticDecoder,)
    client.close()


def test_sync_default_msgspec_only() -> None:
    with patch("httpware._internal.import_checker.is_pydantic_installed", False):
        client = Client()
    types = tuple(type(d) for d in client._decoders)  # noqa: SLF001
    assert types == (MsgspecDecoder,)
    client.close()


def test_sync_default_neither_installed() -> None:
    with (
        patch("httpware._internal.import_checker.is_pydantic_installed", False),
        patch("httpware._internal.import_checker.is_msgspec_installed", False),
    ):
        client = Client()
    assert client._decoders == ()  # noqa: SLF001
    client.close()


def test_sync_empty_explicit_decoders() -> None:
    client = Client(decoders=[])
    assert client._decoders == ()  # noqa: SLF001
    client.close()

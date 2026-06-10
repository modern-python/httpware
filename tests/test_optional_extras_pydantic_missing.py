"""Fail-fast tests for the pydantic optional-extra (0.3.0).

Pydantic IS installed in the CI test environment via `--all-extras`. To
simulate the "extra not installed" case, patch
`httpware._internal.import_checker.is_pydantic_installed = False` for the
duration of the test.
"""

from unittest.mock import patch

import pytest

from httpware import AsyncClient, Client
from httpware.decoders.pydantic import PydanticDecoder


class _FakeDecoder:
    """Test stand-in for ResponseDecoder; never called at runtime."""

    def can_decode(self, model: type) -> bool:  # noqa: ARG002 — name pinned by ResponseDecoder protocol
        return True  # pragma: no cover

    def decode(self, content: bytes, model: type) -> object:  # noqa: ARG002 — name pinned by ResponseDecoder protocol
        return model()  # pragma: no cover


def test_pydantic_decoder_init_raises_when_pydantic_missing() -> None:
    with (
        patch("httpware._internal.import_checker.is_pydantic_installed", False),
        pytest.raises(ImportError, match=r"httpware\[pydantic\]"),
    ):
        PydanticDecoder()


def test_async_client_no_pydantic_constructs_without_raising() -> None:
    """AsyncClient() with pydantic missing must not raise — lazy default policy."""
    with patch("httpware._internal.import_checker.is_pydantic_installed", False):
        client = AsyncClient()
    assert all(not isinstance(d, PydanticDecoder) for d in client._decoders)  # noqa: SLF001


def test_sync_client_no_pydantic_constructs_without_raising() -> None:
    """Client() with pydantic missing must not raise — lazy default policy."""
    with patch("httpware._internal.import_checker.is_pydantic_installed", False):
        client = Client()
    assert all(not isinstance(d, PydanticDecoder) for d in client._decoders)  # noqa: SLF001
    client.close()


def test_async_client_accepts_explicit_decoders_without_pydantic() -> None:
    """An explicit decoders= list is honored regardless of pydantic install state."""
    fake = _FakeDecoder()
    with patch("httpware._internal.import_checker.is_pydantic_installed", False):
        client = AsyncClient(decoders=[fake])
    assert client._decoders == (fake,)  # noqa: SLF001


def test_sync_client_accepts_explicit_decoders_without_pydantic() -> None:
    fake = _FakeDecoder()
    with patch("httpware._internal.import_checker.is_pydantic_installed", False):
        client = Client(decoders=[fake])
    assert client._decoders == (fake,)  # noqa: SLF001
    client.close()

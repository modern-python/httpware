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


def test_async_client_default_decoder_raises_when_pydantic_missing() -> None:
    with (
        patch("httpware._internal.import_checker.is_pydantic_installed", False),
        pytest.raises(ImportError, match=r"httpware\[pydantic\]"),
    ):
        AsyncClient()


def test_sync_client_default_decoder_raises_when_pydantic_missing() -> None:
    with (
        patch("httpware._internal.import_checker.is_pydantic_installed", False),
        pytest.raises(ImportError, match=r"httpware\[pydantic\]"),
    ):
        Client()


def test_async_client_accepts_explicit_decoder_without_pydantic() -> None:
    """An explicit decoder= escapes the fail-fast AND is actually wired to the client."""
    fake = _FakeDecoder()
    with patch("httpware._internal.import_checker.is_pydantic_installed", False):
        client = AsyncClient(decoder=fake)
    assert client._decoder is fake  # noqa: SLF001 — wired the explicit decoder, not a default


def test_sync_client_accepts_explicit_decoder_without_pydantic() -> None:
    """Sync mirror: explicit decoder= escapes the fail-fast AND is wired for sync Client too."""
    fake = _FakeDecoder()
    with patch("httpware._internal.import_checker.is_pydantic_installed", False):
        client = Client(decoder=fake)
    assert client._decoder is fake  # noqa: SLF001 — wired the explicit decoder, not a default

"""Fail-fast tests for the pydantic optional-extra (0.3.0).

Pydantic IS installed in the CI test environment via `--all-extras`. To
simulate the "extra not installed" case, patch
`httpware._internal.import_checker.is_pydantic_installed = False` for the
duration of the test.
"""

from unittest.mock import patch

import pytest

from httpware import AsyncClient
from httpware.decoders.pydantic import PydanticDecoder


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


def test_async_client_accepts_explicit_decoder_without_pydantic() -> None:
    """An explicit decoder= escapes the fail-fast even when pydantic is 'missing'."""

    class _FakeDecoder:
        def decode(self, content: bytes, model: type) -> object:  # noqa: ARG002 — name pinned by ResponseDecoder protocol
            return model()  # pragma: no cover

    with patch("httpware._internal.import_checker.is_pydantic_installed", False):
        client = AsyncClient(decoder=_FakeDecoder())
        assert client is not None

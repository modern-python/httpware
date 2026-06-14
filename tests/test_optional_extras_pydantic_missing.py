"""Fail-fast tests for the pydantic optional-extra (0.3.0).

Pydantic IS installed in the CI test environment via `--all-extras`. To
simulate the "extra not installed" case, patch
`httpware._internal.import_checker.is_pydantic_installed = False` for the
duration of the test.
"""

import subprocess
import sys
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


def test_pydantic_decoder_module_imports_when_pydantic_absent() -> None:
    """The decoder module must import cleanly when pydantic is genuinely absent.

    pydantic IS installed in CI (via `--all-extras`), so true absence is
    simulated in a fresh subprocess: setting `sys.modules['pydantic'] = None`
    makes `importlib.util.find_spec('pydantic')` return None (so
    `is_pydantic_installed` is False) and any `import pydantic` raise
    ImportError. With the module-level import guarded, importing the decoder
    module must NOT raise, and `PydanticDecoder()` must raise the friendly
    extra-missing ImportError — not a bare ModuleNotFoundError at module load.
    """
    script = (
        "import sys\n"
        "sys.modules['pydantic'] = None\n"
        "from httpware._internal import import_checker\n"
        "assert import_checker.is_pydantic_installed is False\n"
        "import httpware.decoders.pydantic as pyd\n"
        "try:\n"
        "    pyd.PydanticDecoder()\n"
        "except ImportError as exc:\n"
        "    sys.exit(0 if 'httpware[pydantic]' in str(exc) else 2)\n"
        "sys.exit(3)\n"
    )
    result = subprocess.run(  # noqa: S603 — `script` is a test-authored constant, not untrusted input
        [sys.executable, "-c", script], check=False, capture_output=True
    )
    assert result.returncode == 0, (
        f"decoder module failed to import or guard without pydantic; rc={result.returncode} "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )


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

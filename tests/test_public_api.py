"""Verify public API exports are correct and stable."""

import httpware
from httpware import AuthValue  # noqa: F401


def test_all_exports_present() -> None:
    """Verify all symbols in __all__ are actually exported."""
    for symbol in httpware.__all__:
        assert hasattr(httpware, symbol), f"{symbol} in __all__ but not exported"


def test_auth_value_is_public() -> None:
    """Verify AuthValue type alias is exported."""
    assert "AuthValue" in httpware.__all__

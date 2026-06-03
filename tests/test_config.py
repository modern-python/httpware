"""Unit tests for httpware.config types."""

from dataclasses import FrozenInstanceError

import pytest

from httpware import ClientConfig, Limits, Timeout
from httpware.decoders.pydantic import PydanticDecoder


def test_timeout_defaults() -> None:
    assert Timeout() == Timeout(connect=5.0, read=30.0, write=30.0, pool=5.0)


def test_limits_defaults() -> None:
    assert Limits() == Limits(max_connections=100, max_keepalive_connections=20, keepalive_expiry=5.0)


def test_client_config_defaults() -> None:
    cfg = ClientConfig()
    assert cfg.base_url is None
    assert cfg.default_headers == {}
    assert cfg.default_query == {}
    assert cfg.timeout == Timeout()
    assert cfg.limits == Limits()
    assert isinstance(cfg.decoder, PydanticDecoder)
    assert cfg.middleware == ()


def test_client_config_default_mappings_are_independent() -> None:
    c1 = ClientConfig()
    c2 = ClientConfig()
    assert c1.default_headers is not c2.default_headers
    assert c1.default_query is not c2.default_query


def test_timeout_is_frozen() -> None:
    t = Timeout()
    with pytest.raises(FrozenInstanceError):
        t.read = 60.0  # ty: ignore[invalid-assignment]


def test_limits_is_frozen() -> None:
    lim = Limits()
    with pytest.raises(FrozenInstanceError):
        lim.max_connections = 50  # ty: ignore[invalid-assignment]


def test_client_config_is_frozen() -> None:
    cfg = ClientConfig()
    with pytest.raises(FrozenInstanceError):
        cfg.base_url = "https://example.com"  # ty: ignore[invalid-assignment]


@pytest.mark.parametrize("field", ["connect", "read", "write", "pool"])
def test_timeout_rejects_negative(field: str) -> None:
    with pytest.raises(ValueError, match=rf"Timeout\.{field} must be non-negative"):
        Timeout(**{field: -1.0})


def test_timeout_accepts_zero() -> None:
    # Zero is a valid sentinel (fail immediately on this phase).
    Timeout(connect=0.0, read=0.0, write=0.0, pool=0.0)


@pytest.mark.parametrize("field", ["max_connections", "max_keepalive_connections"])
def test_limits_rejects_negative_int(field: str) -> None:
    with pytest.raises(ValueError, match=f"{field} must be non-negative"):
        Limits(**{field: -1})


def test_limits_rejects_negative_keepalive_expiry() -> None:
    with pytest.raises(ValueError, match="keepalive_expiry must be non-negative"):
        Limits(keepalive_expiry=-0.5)


def test_limits_accepts_zero() -> None:
    Limits(max_connections=0, max_keepalive_connections=0, keepalive_expiry=0.0)


def test_client_config_strips_trailing_slash_from_base_url() -> None:
    cfg = ClientConfig(base_url="https://api.example.com/")
    assert cfg.base_url == "https://api.example.com"


def test_client_config_leaves_base_url_without_trailing_slash() -> None:
    cfg = ClientConfig(base_url="https://api.example.com")
    assert cfg.base_url == "https://api.example.com"


def test_client_config_strips_multiple_trailing_slashes() -> None:
    cfg = ClientConfig(base_url="https://api.example.com///")
    assert cfg.base_url == "https://api.example.com"


def test_client_config_allows_none_base_url() -> None:
    cfg = ClientConfig(base_url=None)
    assert cfg.base_url is None


def test_client_config_rejects_empty_base_url() -> None:
    with pytest.raises(ValueError, match="base_url must be a non-empty string or None"):
        ClientConfig(base_url="")


def test_client_config_rejects_slash_only_base_url() -> None:
    with pytest.raises(ValueError, match="base_url must be a non-empty string or None"):
        ClientConfig(base_url="/")


def test_client_config_rejects_multiple_slashes_only_base_url() -> None:
    with pytest.raises(ValueError, match="base_url must be a non-empty string or None"):
        ClientConfig(base_url="///")


def test_client_config_rejects_non_str_base_url() -> None:
    with pytest.raises(ValueError, match="base_url must be a non-empty string or None"):
        ClientConfig(base_url=123)  # ty: ignore[invalid-argument-type]

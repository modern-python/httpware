"""Unit tests for httpware.config types."""

from dataclasses import FrozenInstanceError

import pytest

from httpware import ClientConfig, Limits, Timeout


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

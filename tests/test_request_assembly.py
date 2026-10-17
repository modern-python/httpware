"""Tests for request assembly functions in httpware.client module."""

import httpx2
import pytest

from httpware import Client
from httpware.client import _BODY_REQUEST_OPTION_DEFAULTS, _REQUEST_OPTION_DEFAULTS, _request_kwargs


_CLIENT = Client.__new__(Client)


class TestRequestKwargs:
    """Tests for _request_kwargs."""

    def test_no_options_returns_empty_dict(self) -> None:
        assert _request_kwargs(_CLIENT, "post", {}, _BODY_REQUEST_OPTION_DEFAULTS) == {}

    def test_all_unset_returns_empty_dict(self) -> None:
        """When every option is passed at its unset value, return empty dict."""
        options = dict.fromkeys(_BODY_REQUEST_OPTION_DEFAULTS) | {"timeout": httpx2.USE_CLIENT_DEFAULT}
        assert _request_kwargs(_CLIENT, "post", options, _BODY_REQUEST_OPTION_DEFAULTS) == {}

    def test_all_set_returns_full_dict(self) -> None:
        """When all options are set to real values, return dict with all keys."""
        options = {
            "params": {"key": "value"},
            "headers": {"X-Test": "header"},
            "cookies": {"session": "123"},
            "timeout": 5.0,
            "extensions": {"timeout": 10.0},
            "json": {"data": "json"},
            "content": b"binary content",
            "data": {"form": "data"},
            "files": [("file", ("name.txt", b"content"))],
        }
        assert _request_kwargs(_CLIENT, "post", options, _BODY_REQUEST_OPTION_DEFAULTS) == options

    def test_timeout_use_client_default_omitted(self) -> None:
        """When timeout is httpx2.USE_CLIENT_DEFAULT, it is omitted."""
        options = {"timeout": httpx2.USE_CLIENT_DEFAULT}
        assert _request_kwargs(_CLIENT, "get", options, _REQUEST_OPTION_DEFAULTS) == {}

    def test_timeout_none_is_included(self) -> None:
        """When timeout is None (not USE_CLIENT_DEFAULT), it is included."""
        assert _request_kwargs(_CLIENT, "get", {"timeout": None}, _REQUEST_OPTION_DEFAULTS) == {"timeout": None}

    def test_timeout_numeric_value_is_included(self) -> None:
        """When timeout is a numeric value, it is included."""
        timeout_value = 10.5
        result = _request_kwargs(_CLIENT, "get", {"timeout": timeout_value}, _REQUEST_OPTION_DEFAULTS)
        assert result == {"timeout": timeout_value}

    def test_unknown_option_raises_type_error_naming_it(self) -> None:
        with pytest.raises(TypeError, match=r"^Client\.get\(\) got an unexpected keyword argument 'json'$"):
            _request_kwargs(_CLIENT, "get", {"json": {"a": 1}}, _REQUEST_OPTION_DEFAULTS)

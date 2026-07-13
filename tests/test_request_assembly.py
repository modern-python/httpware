"""Tests for request assembly functions in httpware.client module."""

import httpx2

from httpware.client import _assemble_httpx2_client_kwargs, _assemble_request_kwargs


class TestAssembleHttpx2ClientKwargs:
    """Tests for _assemble_httpx2_client_kwargs."""

    def test_all_unset_returns_empty_dict(self) -> None:
        """When all arguments are at their unset values, return empty dict."""
        result = _assemble_httpx2_client_kwargs(
            base_url="",
            headers=None,
            params=None,
            cookies=None,
            timeout=None,
            limits=None,
            auth=None,
        )
        assert result == {}

    def test_all_set_returns_full_dict(self) -> None:
        """When all arguments are set to real values, return dict with all keys."""
        timeout_val = 10.0
        limits_val = httpx2.Limits(max_connections=100)
        auth_val = httpx2.BasicAuth("user", "pass")
        headers_val = {"X-Test": "value"}
        params_val = {"key": "value"}
        cookies_val = {"session": "abc123"}
        base_url_val = "https://example.com"

        result = _assemble_httpx2_client_kwargs(
            base_url=base_url_val,
            headers=headers_val,
            params=params_val,
            cookies=cookies_val,
            timeout=timeout_val,
            limits=limits_val,
            auth=auth_val,
        )

        assert result == {
            "base_url": base_url_val,
            "headers": headers_val,
            "params": params_val,
            "cookies": cookies_val,
            "timeout": timeout_val,
            "limits": limits_val,
            "auth": auth_val,
        }

    def test_base_url_empty_string_omitted(self) -> None:
        """When base_url is an empty string, it is omitted (falsy string check)."""
        result = _assemble_httpx2_client_kwargs(
            base_url="",
            headers=None,
            params=None,
            cookies=None,
            timeout=None,
            limits=None,
            auth=None,
        )
        assert "base_url" not in result
        assert result == {}

    def test_base_url_non_empty_string_included(self) -> None:
        """When base_url is a non-empty string, it is included."""
        result = _assemble_httpx2_client_kwargs(
            base_url="https://example.com",
            headers=None,
            params=None,
            cookies=None,
            timeout=None,
            limits=None,
            auth=None,
        )
        assert "base_url" in result
        assert result["base_url"] == "https://example.com"


class TestAssembleRequestKwargs:
    """Tests for _assemble_request_kwargs."""

    def test_all_unset_returns_empty_dict(self) -> None:
        """When all arguments are at their unset values, return empty dict."""
        result = _assemble_request_kwargs(
            params=None,
            headers=None,
            cookies=None,
            timeout=httpx2.USE_CLIENT_DEFAULT,
            extensions=None,
            json=None,
            content=None,
            data=None,
            files=None,
        )
        assert result == {}

    def test_all_set_returns_full_dict(self) -> None:
        """When all arguments are set to real values, return dict with all keys."""
        params_val = {"key": "value"}
        headers_val = {"X-Test": "header"}
        cookies_val = {"session": "123"}
        timeout_val = 5.0
        extensions_val = {"timeout": 10.0}
        json_val = {"data": "json"}
        content_val = b"binary content"
        data_val = {"form": "data"}
        files_val = [("file", ("name.txt", b"content"))]

        result = _assemble_request_kwargs(
            params=params_val,
            headers=headers_val,
            cookies=cookies_val,
            timeout=timeout_val,
            extensions=extensions_val,
            json=json_val,
            content=content_val,
            data=data_val,
            files=files_val,
        )

        assert result == {
            "params": params_val,
            "headers": headers_val,
            "cookies": cookies_val,
            "timeout": timeout_val,
            "extensions": extensions_val,
            "json": json_val,
            "content": content_val,
            "data": data_val,
            "files": files_val,
        }

    def test_timeout_use_client_default_omitted(self) -> None:
        """When timeout is httpx2.USE_CLIENT_DEFAULT, it is omitted."""
        result = _assemble_request_kwargs(
            params=None,
            headers=None,
            cookies=None,
            timeout=httpx2.USE_CLIENT_DEFAULT,
            extensions=None,
            json=None,
            content=None,
            data=None,
            files=None,
        )
        assert "timeout" not in result
        assert result == {}

    def test_timeout_none_is_included(self) -> None:
        """When timeout is None (not USE_CLIENT_DEFAULT), it is included."""
        result = _assemble_request_kwargs(
            params=None,
            headers=None,
            cookies=None,
            timeout=None,
            extensions=None,
            json=None,
            content=None,
            data=None,
            files=None,
        )
        assert "timeout" in result
        assert result["timeout"] is None

    def test_timeout_numeric_value_is_included(self) -> None:
        """When timeout is a numeric value, it is included."""
        timeout_value = 10.5
        result = _assemble_request_kwargs(
            params=None,
            headers=None,
            cookies=None,
            timeout=timeout_value,
            extensions=None,
            json=None,
            content=None,
            data=None,
            files=None,
        )
        assert "timeout" in result
        assert result["timeout"] == timeout_value

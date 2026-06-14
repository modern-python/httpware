"""Unit tests for the URL redaction helper."""

import pytest

from httpware._internal.redaction import redact_url


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        # no-op cases (common-path guard: bytes unchanged)
        ("https://example.test/path", "https://example.test/path"),
        ("https://example.test/path?page=2&limit=10", "https://example.test/path?page=2&limit=10"),
        ("not-a-url", "not-a-url"),
        ("https://example.test", "https://example.test"),
        # userinfo stripped
        ("https://user:pass@example.test/p", "https://example.test/p"),
        ("https://user:pass@example.test:8443/p", "https://example.test:8443/p"),
        ("https://user:pass@[2001:db8::1]:8443/p", "https://[2001:db8::1]:8443/p"),
        # sensitive query value masked, key + other params preserved
        ("https://example.test/p?api_key=abc123", "https://example.test/p?api_key=REDACTED"),
        ("https://example.test/p?page=2&access_token=xyz", "https://example.test/p?page=2&access_token=REDACTED"),
        # case-insensitive key match
        ("https://example.test/p?API_KEY=abc", "https://example.test/p?API_KEY=REDACTED"),
        # userinfo AND query both handled
        ("https://u:p@example.test/p?token=t", "https://example.test/p?token=REDACTED"),
    ],
)
def test_redact_url(url: str, expected: str) -> None:
    assert redact_url(url) == expected


def test_redact_url_masks_repeated_sensitive_keys() -> None:
    result = redact_url("https://example.test/p?token=a&token=b&page=1")
    assert "token=a" not in result
    assert "token=b" not in result
    assert result.count("token=REDACTED") == 2  # noqa: PLR2004 — two token params above
    assert "page=1" in result


def test_redact_url_masks_blank_sensitive_value() -> None:
    assert redact_url("https://example.test/p?secret=") == "https://example.test/p?secret=REDACTED"


def test_redact_url_masks_fragment_secret() -> None:
    result = redact_url("https://example.test/p?page=2#access_token=topsecret")
    assert "topsecret" not in result
    assert "access_token=REDACTED" in result
    assert "page=2" in result


def test_redact_url_preserves_benign_fragment() -> None:
    assert redact_url("https://example.test/p#section-3") == "https://example.test/p#section-3"


def test_redact_url_masks_whitespace_padded_key() -> None:
    # a space-padded sensitive key name must still be masked
    result = redact_url("https://example.test/p?%20api_key=topsecret")
    assert "topsecret" not in result
    assert "REDACTED" in result


def test_strip_userinfo_no_hostname_does_not_produce_triple_slash() -> None:
    """http://user:pass@/path must strip creds without yielding http:///path."""
    result = redact_url("http://user:pass@/path")
    assert "user" not in result
    assert "pass" not in result
    assert ":///" not in result  # must not be triple-slash
    assert result == "http:/path"  # no authority, just scheme + path

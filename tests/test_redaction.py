"""Unit tests for the URL redaction helper."""

import pytest

from httpware._internal.redaction import redact_url


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://example.test/path", "https://example.test/path"),
        ("not-a-url", "not-a-url"),
        ("https://example.test", "https://example.test"),
        ("https://user:pass@example.test/p", "https://example.test/p"),
        ("https://user:pass@example.test:8443/p", "https://example.test:8443/p"),
        ("https://user:pass@[2001:db8::1]:8443/p", "https://[2001:db8::1]:8443/p"),
        ("https://user:p@ss@example.test/p", "https://example.test/p"),
        ("https://example.test/p?api_key=abc123", "https://example.test/p?api_key=REDACTED"),
        ("https://example.test/p?page=2&limit=10", "https://example.test/p?page=REDACTED&limit=REDACTED"),
        (
            "https://bucket.test/k?X-Amz-Credential=AKIA%2F1&X-Amz-Signature=deadbeef",
            "https://bucket.test/k?X-Amz-Credential=REDACTED&X-Amz-Signature=REDACTED",
        ),
        ("https://example.test/p?API_KEY=abc", "https://example.test/p?API_KEY=REDACTED"),
        ("https://example.test/p?sig=abc==", "https://example.test/p?sig=REDACTED"),
        ("https://example.test/p?%20api_key=topsecret", "https://example.test/p?%20api_key=REDACTED"),
        ("https://example.test/p?flag&page=2", "https://example.test/p?flag&page=REDACTED"),
        ("https://u:p@example.test/p?token=t", "https://example.test/p?token=REDACTED"),
    ],
)
def test_redact_url(url: str, expected: str) -> None:
    assert redact_url(url) == expected


def test_redact_url_masks_repeated_keys() -> None:
    assert redact_url("https://example.test/p?token=a&token=b&page=1") == (
        "https://example.test/p?token=REDACTED&token=REDACTED&page=REDACTED"
    )


def test_redact_url_masks_blank_value() -> None:
    assert redact_url("https://example.test/p?secret=") == "https://example.test/p?secret=REDACTED"


def test_redact_url_masks_fragment_values() -> None:
    assert redact_url("https://example.test/p?page=2#access_token=topsecret&state=xyz") == (
        "https://example.test/p?page=REDACTED#access_token=REDACTED&state=REDACTED"
    )


def test_redact_url_preserves_benign_fragment() -> None:
    assert redact_url("https://example.test/p#section-3") == "https://example.test/p#section-3"


def test_strip_userinfo_no_hostname_does_not_produce_triple_slash() -> None:
    """http://user:pass@/path must strip creds without yielding http:///path."""
    assert redact_url("http://user:pass@/path") == "http:/path"


def test_redact_url_at_sign_in_path_without_userinfo_keeps_path() -> None:
    assert redact_url("https://example.test/@handle?page=2") == "https://example.test/@handle?page=REDACTED"


def test_strip_userinfo_no_hostname_preserves_query_and_fragment() -> None:
    """The no-authority reconstruction keeps the masked query and the fragment, with no triple-slash."""
    assert redact_url("http://user:pass@/path?api_key=secret#section") == "http:/path?api_key=REDACTED#section"

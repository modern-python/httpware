"""Unit tests for httpware.response.Response."""

from dataclasses import FrozenInstanceError

import pytest

from httpware import Response


def test_response_is_frozen() -> None:
    resp = Response(status=200, headers={}, content=b"", url="/", elapsed=0.0)
    with pytest.raises(FrozenInstanceError):
        resp.status = 500  # ty: ignore[invalid-assignment]


def test_response_text_defaults_to_utf8() -> None:
    resp = Response(status=200, headers={}, content=b"hello", url="/", elapsed=0.0)
    assert resp.text == "hello"


def test_response_text_decodes_unicode_default() -> None:
    body = "café".encode()
    resp = Response(status=200, headers={}, content=body, url="/", elapsed=0.0)
    assert resp.text == "café"


@pytest.mark.parametrize("header_name", ["content-type", "Content-Type", "CONTENT-TYPE"])
def test_response_text_honors_explicit_charset(header_name: str) -> None:
    body = "café".encode("latin-1")
    resp = Response(
        status=200,
        headers={header_name: "text/plain; charset=latin-1"},
        content=body,
        url="/",
        elapsed=0.0,
    )
    assert resp.text == "café"


def test_response_text_falls_back_to_utf8_on_missing_charset() -> None:
    resp = Response(
        status=200,
        headers={"content-type": "application/json"},
        content=b'{"x": 1}',
        url="/",
        elapsed=0.0,
    )
    assert resp.text == '{"x": 1}'


@pytest.mark.parametrize(
    "content_type",
    [
        'text/plain; charset="latin-1"',
        "text/plain; charset='latin-1'",
    ],
)
def test_response_text_strips_quotes_around_charset(content_type: str) -> None:
    body = "café".encode("latin-1")
    resp = Response(
        status=200,
        headers={"content-type": content_type},
        content=body,
        url="/",
        elapsed=0.0,
    )
    assert resp.text == "café"


def test_response_text_falls_back_to_utf8_on_unknown_charset() -> None:
    resp = Response(
        status=200,
        headers={"content-type": "text/plain; charset=not-a-real-codec"},
        content=b"hello",
        url="/",
        elapsed=0.0,
    )
    assert resp.text == "hello"


def test_response_json_parses_body() -> None:
    resp = Response(status=200, headers={}, content=b'{"a": 1, "b": [2, 3]}', url="/", elapsed=0.0)
    assert resp.json() == {"a": 1, "b": [2, 3]}


def test_response_equality_on_identical_fields() -> None:
    r1 = Response(status=200, headers={"a": "1"}, content=b"x", url="/", elapsed=0.5)
    r2 = Response(status=200, headers={"a": "1"}, content=b"x", url="/", elapsed=0.5)
    assert r1 == r2
    assert r1 != Response(status=200, headers={"a": "1"}, content=b"x", url="/", elapsed=0.6)
    assert r1 != Response(status=201, headers={"a": "1"}, content=b"x", url="/", elapsed=0.5)


def test_response_with_headers_merges_new_headers() -> None:
    resp = Response(status=200, headers={"keep": "1"}, content=b"", url="/", elapsed=0.0)
    new = resp.with_headers({"x-trace": "abc"})
    assert new.headers == {"keep": "1", "x-trace": "abc"}
    assert resp.headers == {"keep": "1"}


def test_response_with_headers_overrides_existing_key() -> None:
    resp = Response(status=200, headers={"x-trace": "old"}, content=b"", url="/", elapsed=0.0)
    new = resp.with_headers({"x-trace": "new"})
    assert new.headers == {"x-trace": "new"}
    assert resp.headers == {"x-trace": "old"}


def test_response_with_status_replaces_status() -> None:
    resp = Response(status=200, headers={"a": "1"}, content=b"body", url="/x", elapsed=0.5)
    new = resp.with_status(503)
    assert new.status == 503  # noqa: PLR2004
    assert new.headers == {"a": "1"}
    assert new.content == b"body"
    assert new.url == "/x"
    assert new.elapsed == 0.5  # noqa: PLR2004
    assert resp.status == 200  # noqa: PLR2004


def test_response_with_status_accepts_arbitrary_int() -> None:
    resp = Response(status=200, headers={}, content=b"", url="/", elapsed=0.0)
    # No validation by design — value objects don't enforce protocol semantics.
    new = resp.with_status(99)
    assert new.status == 99  # noqa: PLR2004

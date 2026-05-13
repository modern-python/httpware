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


def test_response_json_parses_body() -> None:
    resp = Response(status=200, headers={}, content=b'{"a": 1, "b": [2, 3]}', url="/", elapsed=0.0)
    assert resp.json() == {"a": 1, "b": [2, 3]}


def test_response_equality_on_identical_fields() -> None:
    r1 = Response(status=200, headers={"a": "1"}, content=b"x", url="/", elapsed=0.5)
    r2 = Response(status=200, headers={"a": "1"}, content=b"x", url="/", elapsed=0.5)
    assert r1 == r2

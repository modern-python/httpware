"""Unit tests for httpware.request.Request."""

from dataclasses import FrozenInstanceError

import pytest

from httpware import Request


def test_request_is_frozen() -> None:
    req = Request(method="GET", url="https://example.com/")
    with pytest.raises(FrozenInstanceError):
        req.method = "POST"  # ty: ignore[invalid-assignment]


def test_request_default_mappings_are_empty_and_independent() -> None:
    r1 = Request(method="GET", url="/")
    r2 = Request(method="GET", url="/")
    assert r1.headers == {}
    assert r1.params == {}
    assert r1.cookies == {}
    assert r1.extensions == {}
    assert r1.body is None
    assert r1.headers is not r2.headers


def test_request_equality_on_identical_fields() -> None:
    r1 = Request(method="GET", url="/x", headers={"a": "1"})
    r2 = Request(method="GET", url="/x", headers={"a": "1"})
    assert r1 == r2


def test_with_header_adds_when_absent() -> None:
    r = Request(method="GET", url="/")
    new = r.with_header("X-Trace", "abc")
    assert new.headers == {"X-Trace": "abc"}
    assert r.headers == {}
    assert new is not r


def test_with_header_replaces_when_present() -> None:
    r = Request(method="GET", url="/", headers={"X-Trace": "old"})
    new = r.with_header("X-Trace", "new")
    assert new.headers == {"X-Trace": "new"}
    assert r.headers == {"X-Trace": "old"}


def test_with_url_returns_new_instance() -> None:
    r = Request(method="GET", url="/a")
    new = r.with_url("/b")
    assert new.url == "/b"
    assert r.url == "/a"
    assert new is not r


def test_with_body_returns_new_instance() -> None:
    r = Request(method="POST", url="/")
    new = r.with_body(b"payload")
    assert new.body == b"payload"
    assert r.body is None
    assert new is not r


def test_with_query_replaces_params() -> None:
    r = Request(method="GET", url="/", params={"a": "1"})
    new = r.with_query({"b": "2"})
    assert new.params == {"b": "2"}
    assert r.params == {"a": "1"}
    assert new is not r

"""Unit tests for httpware.errors."""

import builtins
import copy
import pickle

import pytest

import httpware.errors
from httpware import (
    STATUS_TO_EXCEPTION,
    BadRequestError,
    ClientError,
    ClientStatusError,
    ConflictError,
    ForbiddenError,
    InternalServerError,
    NotFoundError,
    RateLimitedError,
    ServerStatusError,
    ServiceUnavailableError,
    StatusError,
    TimeoutError,  # noqa: A004
    TransportError,
    UnauthorizedError,
    UnprocessableEntityError,
)


_LEAF_HIERARCHY = [
    (BadRequestError, ClientStatusError),
    (UnauthorizedError, ClientStatusError),
    (ForbiddenError, ClientStatusError),
    (NotFoundError, ClientStatusError),
    (ConflictError, ClientStatusError),
    (UnprocessableEntityError, ClientStatusError),
    (RateLimitedError, ClientStatusError),
    (InternalServerError, ServerStatusError),
    (ServiceUnavailableError, ServerStatusError),
]


@pytest.mark.parametrize(("leaf", "category"), _LEAF_HIERARCHY)
def test_leaf_inherits_full_chain(leaf: type[StatusError], category: type[StatusError]) -> None:
    assert issubclass(leaf, category)
    assert issubclass(leaf, StatusError)
    assert issubclass(leaf, ClientError)


def test_transport_error_inherits_client_error() -> None:
    assert issubclass(TransportError, ClientError)


def test_timeout_error_inherits_client_error() -> None:
    assert issubclass(TimeoutError, ClientError)


def test_timeout_error_is_builtins_timeout_error() -> None:
    """``httpware.TimeoutError`` is also a ``builtins.TimeoutError``.

    So ``except builtins.TimeoutError`` (the form ``asyncio.wait_for``
    raises) catches httpware-raised timeouts too.
    """
    assert issubclass(TimeoutError, builtins.TimeoutError)
    assert isinstance(TimeoutError(), builtins.TimeoutError)
    assert isinstance(TimeoutError(), ClientError)


def test_builtins_timeout_error_is_not_httpware_timeout() -> None:
    """The shadow is one-way: a bare ``builtins.TimeoutError`` is NOT a ``httpware.TimeoutError``."""
    assert not isinstance(builtins.TimeoutError(), TimeoutError)


def test_status_error_rejects_positional_args() -> None:
    with pytest.raises(TypeError):
        NotFoundError(404, b"", {}, None, "GET", "/x")  # ty: ignore[missing-argument, too-many-positional-arguments]


def test_status_error_rejects_missing_kwarg() -> None:
    with pytest.raises(TypeError):
        NotFoundError(status=404)  # ty: ignore[missing-argument]


def test_status_error_stores_all_fields() -> None:
    status = 404
    body = b"not found"
    headers = {"X-Trace": "abc"}
    payload = {"error": "not found"}
    method = "GET"
    url = "/users/1"
    exc = NotFoundError(
        status=status,
        body=body,
        headers=headers,
        json=payload,
        request_method=method,
        request_url=url,
    )
    assert exc.status == status
    assert exc.body == body
    assert exc.headers == headers
    assert exc.json == payload
    assert exc.request_method == method
    assert exc.request_url == url


def test_headers_are_defensively_copied() -> None:
    """Caller mutation of the source dict after ``raise`` must not bleed into the exception."""
    headers: dict[str, str] = {"X-Trace": "abc"}
    exc = NotFoundError(
        status=404,
        body=b"",
        headers=headers,
        json=None,
        request_method="GET",
        request_url="/x",
    )
    headers["X-Trace"] = "MUTATED"
    headers["X-Added"] = "leaked"
    assert exc.headers["X-Trace"] == "abc"
    assert "X-Added" not in exc.headers


def test_headers_are_read_only() -> None:
    """The defensive copy is a ``MappingProxyType``; consumers cannot mutate it."""
    exc = NotFoundError(
        status=404,
        body=b"",
        headers={"X-Trace": "abc"},
        json=None,
        request_method="GET",
        request_url="/x",
    )
    with pytest.raises(TypeError):
        exc.headers["X-Trace"] = "MUTATED"  # ty: ignore[invalid-assignment]


def test_repr_format_4xx_leaf() -> None:
    exc = NotFoundError(
        status=404,
        body=b"",
        headers={},
        json=None,
        request_method="GET",
        request_url="/users/1",
    )
    assert repr(exc) == "<NotFoundError status=404 method=GET url=/users/1>"


def test_repr_format_5xx_leaf() -> None:
    exc = InternalServerError(
        status=500,
        body=b"",
        headers={},
        json=None,
        request_method="POST",
        request_url="/x",
    )
    assert repr(exc) == "<InternalServerError status=500 method=POST url=/x>"


def test_repr_does_not_leak_body_or_headers() -> None:
    exc = NotFoundError(
        status=404,
        body=b"secret-token-abc",
        headers={"Authorization": "Bearer s3cret"},
        json=None,
        request_method="GET",
        request_url="/x",
    )
    r = repr(exc)
    assert "secret-token-abc" not in r
    assert "Authorization" not in r
    assert "s3cret" not in r


def test_repr_strips_userinfo_from_url() -> None:
    """``__repr__`` must drop ``user:pass@`` userinfo from the request URL."""
    exc = NotFoundError(
        status=404,
        body=b"",
        headers={},
        json=None,
        request_method="GET",
        request_url="https://alice:s3cret@example.com/path",
    )
    r = repr(exc)
    assert "alice" not in r
    assert "s3cret" not in r
    assert "example.com/path" in r


def test_str_strips_userinfo_from_url() -> None:
    """The summary message passed to ``Exception.__init__`` must also drop userinfo."""
    exc = NotFoundError(
        status=404,
        body=b"",
        headers={},
        json=None,
        request_method="GET",
        request_url="https://alice:s3cret@example.com/path",
    )
    s = str(exc)
    assert "alice" not in s
    assert "s3cret" not in s
    assert "example.com/path" in s


def test_repr_preserves_explicit_port_when_stripping_userinfo() -> None:
    """Stripping userinfo must keep the explicit port (``:8443``) in the rebuilt URL."""
    exc = NotFoundError(
        status=404,
        body=b"",
        headers={},
        json=None,
        request_method="GET",
        request_url="https://alice:s3cret@example.com:8443/path",
    )
    r = repr(exc)
    assert "alice" not in r
    assert "s3cret" not in r
    assert "example.com:8443/path" in r


def test_repr_handles_at_sign_in_path_without_userinfo() -> None:
    """A bare ``@`` in the path (no userinfo) must leave the URL untouched."""
    exc = NotFoundError(
        status=404,
        body=b"",
        headers={},
        json=None,
        request_method="GET",
        request_url="https://example.com/users/@alice/profile",
    )
    assert repr(exc) == "<NotFoundError status=404 method=GET url=https://example.com/users/@alice/profile>"


def test_status_error_direct_construction() -> None:
    """The ``StatusError`` base is directly constructible — used by AC4 fallback callers."""
    status = 999
    exc = StatusError(
        status=status,
        body=b"",
        headers={},
        json=None,
        request_method="GET",
        request_url="/x",
    )
    assert exc.status == status
    assert repr(exc) == "<StatusError status=999 method=GET url=/x>"


def test_client_status_error_fallback_construction() -> None:
    """``ClientStatusError`` is the fallback target for unknown 4xx codes (e.g. 418)."""
    status = 418
    exc = ClientStatusError(
        status=status,
        body=b"",
        headers={},
        json=None,
        request_method="GET",
        request_url="/teapot",
    )
    assert exc.status == status
    assert repr(exc) == "<ClientStatusError status=418 method=GET url=/teapot>"


def test_server_status_error_fallback_construction() -> None:
    """``ServerStatusError`` is the fallback target for unknown 5xx codes (e.g. 504)."""
    status = 504
    exc = ServerStatusError(
        status=status,
        body=b"",
        headers={},
        json=None,
        request_method="POST",
        request_url="/x",
    )
    assert exc.status == status
    assert repr(exc) == "<ServerStatusError status=504 method=POST url=/x>"


def test_status_error_pickle_round_trip() -> None:
    """Exceptions survive ``pickle.dumps`` / ``pickle.loads`` across process boundaries."""
    original = NotFoundError(
        status=404,
        body=b"not found",
        headers={"X-Trace": "abc"},
        json={"error": "not found"},
        request_method="GET",
        request_url="/users/1",
    )
    revived = pickle.loads(pickle.dumps(original))  # noqa: S301
    assert type(revived) is NotFoundError
    assert revived.status == original.status
    assert revived.body == original.body
    assert dict(revived.headers) == dict(original.headers)
    assert revived.json == original.json
    assert revived.request_method == original.request_method
    assert revived.request_url == original.request_url
    assert repr(revived) == repr(original)
    assert str(revived) == str(original)


def test_status_error_deepcopy_round_trip() -> None:
    original = InternalServerError(
        status=500,
        body=b"",
        headers={"X-Trace": "abc"},
        json=None,
        request_method="POST",
        request_url="/x",
    )
    revived = copy.deepcopy(original)
    assert type(revived) is InternalServerError
    assert revived.status == original.status
    assert dict(revived.headers) == dict(original.headers)
    assert repr(revived) == repr(original)


_STATUS_MAPPING = [
    (400, BadRequestError),
    (401, UnauthorizedError),
    (403, ForbiddenError),
    (404, NotFoundError),
    (409, ConflictError),
    (422, UnprocessableEntityError),
    (429, RateLimitedError),
    (500, InternalServerError),
    (503, ServiceUnavailableError),
]


@pytest.mark.parametrize(("code", "cls"), _STATUS_MAPPING)
def test_status_to_exception_mapping(code: int, cls: type[StatusError]) -> None:
    assert STATUS_TO_EXCEPTION[code] is cls


def test_status_to_exception_has_only_nine_entries() -> None:
    assert len(STATUS_TO_EXCEPTION) == len(_STATUS_MAPPING)


def test_unknown_4xx_falls_back_to_client_status_error() -> None:
    assert STATUS_TO_EXCEPTION.get(418, ClientStatusError) is ClientStatusError


def test_unknown_5xx_falls_back_to_server_status_error() -> None:
    assert STATUS_TO_EXCEPTION.get(504, ServerStatusError) is ServerStatusError


def test_top_level_reexports_match_errors_module() -> None:
    assert NotFoundError is httpware.errors.NotFoundError
    assert ClientError is httpware.errors.ClientError
    assert STATUS_TO_EXCEPTION is httpware.errors.STATUS_TO_EXCEPTION

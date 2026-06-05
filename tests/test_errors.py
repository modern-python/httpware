"""Tests for the status-keyed exception tree in httpware.errors."""

import builtins
import pickle

import httpx2
import pytest

from httpware.errors import (
    STATUS_TO_EXCEPTION,
    BadRequestError,
    ClientError,
    ClientStatusError,
    ConflictError,
    ForbiddenError,
    InternalServerError,
    NetworkError,
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


def _make_response(status: int, *, url: str = "https://example.test/x", method: str = "GET") -> httpx2.Response:
    request = httpx2.Request(method, url)
    return httpx2.Response(status, request=request)


def test_inheritance_tree() -> None:
    assert issubclass(StatusError, ClientError)
    assert issubclass(TransportError, ClientError)
    assert issubclass(TimeoutError, ClientError)
    assert issubclass(TimeoutError, builtins.TimeoutError)
    assert issubclass(ClientStatusError, StatusError)
    assert issubclass(ServerStatusError, StatusError)
    for exc in (
        BadRequestError,
        UnauthorizedError,
        ForbiddenError,
        NotFoundError,
        ConflictError,
        UnprocessableEntityError,
        RateLimitedError,
    ):
        assert issubclass(exc, ClientStatusError), exc
    for exc in (InternalServerError, ServiceUnavailableError):
        assert issubclass(exc, ServerStatusError), exc


def test_status_to_exception_table() -> None:
    assert {
        400: BadRequestError,
        401: UnauthorizedError,
        403: ForbiddenError,
        404: NotFoundError,
        409: ConflictError,
        422: UnprocessableEntityError,
        429: RateLimitedError,
        500: InternalServerError,
        503: ServiceUnavailableError,
    } == STATUS_TO_EXCEPTION


def test_status_error_stores_response() -> None:
    response = _make_response(404)
    exc = NotFoundError(response)
    assert exc.response is response


def test_status_error_summary_message_includes_status_method_url() -> None:
    exc = NotFoundError(_make_response(404, url="https://example.test/missing", method="GET"))
    assert str(exc) == "404 GET https://example.test/missing"


def test_status_error_strips_userinfo_in_summary_message() -> None:
    exc = NotFoundError(_make_response(404, url="https://user:pass@example.test/x"))
    assert "user" not in str(exc)
    assert "pass" not in str(exc)
    assert str(exc) == "404 GET https://example.test/x"


def test_status_error_repr_strips_userinfo() -> None:
    exc = NotFoundError(_make_response(404, url="https://user:pass@example.test/x"))
    r = repr(exc)
    assert "user" not in r
    assert "pass" not in r
    assert "NotFoundError" in r
    assert "status=404" in r


_NOT_FOUND = 404


def test_status_error_pickleable() -> None:
    exc = NotFoundError(_make_response(_NOT_FOUND, url="https://example.test/x"))
    restored = pickle.loads(pickle.dumps(exc))  # noqa: S301
    assert isinstance(restored, NotFoundError)
    assert restored.response.status_code == _NOT_FOUND
    assert str(restored.response.request.url) == "https://example.test/x"


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (400, BadRequestError),
        (401, UnauthorizedError),
        (404, NotFoundError),
        (429, RateLimitedError),
        (500, InternalServerError),
        (503, ServiceUnavailableError),
    ],
)
def test_per_status_subclasses_construct(status: int, expected: type[StatusError]) -> None:
    response = _make_response(status)
    exc = expected(response)
    assert isinstance(exc, expected)
    assert exc.response.status_code == status


def test_status_error_strips_userinfo_with_username_only() -> None:
    exc = NotFoundError(_make_response(404, url="https://user@example.test/x"))
    assert "user" not in str(exc)
    assert str(exc) == "404 GET https://example.test/x"


def test_status_error_summary_preserves_port() -> None:
    exc = NotFoundError(_make_response(404, url="https://user:pass@example.test:8080/x"))
    assert "user" not in str(exc)
    assert "pass" not in str(exc)
    assert str(exc) == "404 GET https://example.test:8080/x"


def test_status_error_summary_passthrough_when_at_in_query_only() -> None:
    # `@` in query-string with no userinfo — should fall through after urlsplit returns no user/pass.
    exc = NotFoundError(_make_response(404, url="https://example.test/x?email=foo@bar.com"))
    assert str(exc) == "404 GET https://example.test/x?email=foo@bar.com"


def test_status_error_strips_userinfo_with_ipv6_host() -> None:
    exc = NotFoundError(_make_response(404, url="https://user:pass@[::1]:8080/x"))
    assert "user" not in str(exc)
    assert "pass" not in str(exc)
    assert str(exc) == "404 GET https://[::1]:8080/x"


def test_timeout_error_is_builtin_timeout_error() -> None:
    exc = TimeoutError("timed out")
    assert isinstance(exc, builtins.TimeoutError)
    assert isinstance(exc, ClientError)


def test_transport_error_is_client_error() -> None:
    exc = TransportError("connection refused")
    assert isinstance(exc, ClientError)


def test_network_error_is_transport_error() -> None:
    exc = NetworkError("connection refused")
    assert isinstance(exc, TransportError)
    assert isinstance(exc, ClientError)

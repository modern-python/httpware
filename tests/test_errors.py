"""Tests for the status-keyed exception tree in httpware.errors."""

import builtins
import pickle
from http import HTTPStatus

import httpx2
import pydantic
import pytest

from httpware.errors import (
    STATUS_TO_EXCEPTION,
    BadRequestError,
    BulkheadFullError,
    CircuitOpenError,
    ClientError,
    ClientStatusError,
    ConflictError,
    DecodeError,
    ForbiddenError,
    InternalServerError,
    MissingDecoderError,
    NetworkError,
    NotFoundError,
    RateLimitedError,
    RetryBudgetExhaustedError,
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


class _DecodeErrorModel(pydantic.BaseModel):
    id: int


def test_inheritance_tree() -> None:
    assert issubclass(StatusError, ClientError)
    assert issubclass(TransportError, ClientError)
    assert issubclass(TimeoutError, ClientError)
    assert issubclass(TimeoutError, builtins.TimeoutError)
    assert issubclass(ClientStatusError, StatusError)
    assert issubclass(ServerStatusError, StatusError)
    assert issubclass(DecodeError, ClientError)
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
_RETRY_AFTER_2_5 = 2.5
_RETRY_ATTEMPTS_3 = 3
_RETRY_ATTEMPTS_2 = 2
_RETRY_ATTEMPTS_5 = 5
_MAX_CONCURRENT_5 = 5
_ACQUIRE_TIMEOUT_1_0 = 1.0


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


def test_retry_budget_exhausted_error_is_client_error() -> None:
    exc = RetryBudgetExhaustedError(last_response=None, last_exception=None, attempts=_RETRY_ATTEMPTS_3)
    assert isinstance(exc, ClientError)
    assert exc.last_response is None
    assert exc.last_exception is None
    assert exc.attempts == _RETRY_ATTEMPTS_3


def test_retry_budget_exhausted_error_carries_last_response_and_exception() -> None:
    response = _make_response(503, url="https://example.test/x")
    inner = RuntimeError("boom")
    exc = RetryBudgetExhaustedError(last_response=response, last_exception=inner, attempts=_RETRY_ATTEMPTS_2)
    assert exc.last_response is response
    assert exc.last_exception is inner
    assert exc.attempts == _RETRY_ATTEMPTS_2


def test_retry_budget_exhausted_error_summary_mentions_attempts() -> None:
    exc = RetryBudgetExhaustedError(last_response=None, last_exception=None, attempts=_RETRY_ATTEMPTS_5)
    assert str(exc) == f"retry budget exhausted after {_RETRY_ATTEMPTS_5} attempt(s)"


_SERVICE_UNAVAILABLE = 503


def test_retry_budget_exhausted_error_pickleable() -> None:
    response = _make_response(_SERVICE_UNAVAILABLE, url="https://example.test/x")
    inner = RuntimeError("boom")
    exc = RetryBudgetExhaustedError(
        last_response=response,
        last_exception=inner,
        attempts=_RETRY_ATTEMPTS_3,
    )
    restored = pickle.loads(pickle.dumps(exc))  # noqa: S301
    assert isinstance(restored, RetryBudgetExhaustedError)
    assert restored.attempts == _RETRY_ATTEMPTS_3
    assert restored.last_response is not None
    assert restored.last_response.status_code == _SERVICE_UNAVAILABLE


def test_bulkhead_full_error_is_client_error() -> None:
    exc = BulkheadFullError(max_concurrent=_MAX_CONCURRENT_5, acquire_timeout=_ACQUIRE_TIMEOUT_1_0)
    assert isinstance(exc, ClientError)
    assert exc.max_concurrent == _MAX_CONCURRENT_5
    assert exc.acquire_timeout == _ACQUIRE_TIMEOUT_1_0


def test_bulkhead_full_error_accepts_none_acquire_timeout() -> None:
    exc = BulkheadFullError(max_concurrent=_MAX_CONCURRENT_5, acquire_timeout=None)
    assert exc.acquire_timeout is None


def test_bulkhead_full_error_summary_mentions_caps() -> None:
    exc = BulkheadFullError(max_concurrent=_MAX_CONCURRENT_5, acquire_timeout=_ACQUIRE_TIMEOUT_1_0)
    assert str(exc) == "bulkhead full (max_concurrent=5, acquire_timeout=1.0)"


def test_bulkhead_full_error_pickleable() -> None:
    exc = BulkheadFullError(max_concurrent=_MAX_CONCURRENT_5, acquire_timeout=_ACQUIRE_TIMEOUT_1_0)
    restored = pickle.loads(pickle.dumps(exc))  # noqa: S301
    assert isinstance(restored, BulkheadFullError)
    assert restored.max_concurrent == _MAX_CONCURRENT_5
    assert restored.acquire_timeout == _ACQUIRE_TIMEOUT_1_0


def test_decode_error_is_client_error() -> None:
    response = _make_response(200)
    inner = ValueError("bad payload")
    exc = DecodeError(response=response, model=_DecodeErrorModel, original=inner)
    assert isinstance(exc, ClientError)


def test_decode_error_stores_fields() -> None:
    response = _make_response(200)
    inner = ValueError("bad payload")
    exc = DecodeError(response=response, model=_DecodeErrorModel, original=inner)
    assert exc.response is response
    assert exc.model is _DecodeErrorModel
    assert exc.original is inner


def test_decode_error_summary_includes_model_and_original() -> None:
    response = _make_response(200)
    inner = ValueError("bad payload")
    exc = DecodeError(response=response, model=_DecodeErrorModel, original=inner)
    summary = str(exc)
    assert "_DecodeErrorModel" in summary
    assert "bad payload" in summary
    assert summary.startswith("failed to decode response into ")


def test_decode_error_rejects_positional_args() -> None:
    response = _make_response(200)
    inner = ValueError("bad payload")
    with pytest.raises(TypeError):
        DecodeError(response, _DecodeErrorModel, inner)  # ty: ignore[missing-argument, too-many-positional-arguments]


def test_decode_error_chaining_via_raise_from() -> None:
    response = _make_response(200)
    inner = ValueError("bad payload")
    raised: DecodeError | None = None
    try:
        try:
            raise inner
        except ValueError as caught:
            raise DecodeError(response=response, model=_DecodeErrorModel, original=caught) from caught
    except DecodeError as exc:
        raised = exc
    assert raised is not None
    assert raised.__cause__ is inner
    assert raised.original is inner


def test_decode_error_pickleable() -> None:
    response = _make_response(200, url="https://example.test/p")
    inner = ValueError("bad payload")
    exc = DecodeError(response=response, model=_DecodeErrorModel, original=inner)
    restored = pickle.loads(pickle.dumps(exc))  # noqa: S301
    assert isinstance(restored, DecodeError)
    assert restored.model is _DecodeErrorModel
    assert isinstance(restored.original, ValueError)
    assert str(restored.original) == "bad payload"
    assert restored.response.status_code == HTTPStatus.OK


class _Foo:
    pass


def test_missing_decoder_error_carries_model() -> None:
    exc = MissingDecoderError(model=_Foo, registered_names=())
    assert exc.model is _Foo


def test_missing_decoder_error_carries_registered_names() -> None:
    exc = MissingDecoderError(model=_Foo, registered_names=("PydanticDecoder",))
    assert exc.registered_names == ("PydanticDecoder",)


def test_missing_decoder_error_no_registered_message() -> None:
    exc = MissingDecoderError(model=_Foo, registered_names=())
    msg = str(exc)
    assert "no decoders registered" in msg
    assert "httpware[pydantic]" in msg
    assert "httpware[msgspec]" in msg


def test_missing_decoder_error_single_registered_message() -> None:
    exc = MissingDecoderError(model=_Foo, registered_names=("PydanticDecoder",))
    assert "registered decoders (PydanticDecoder) all rejected" in str(exc)


def test_missing_decoder_error_two_registered_message() -> None:
    exc = MissingDecoderError(
        model=_Foo,
        registered_names=("PydanticDecoder", "MsgspecDecoder"),
    )
    assert "registered decoders (PydanticDecoder + MsgspecDecoder) all rejected" in str(exc)


def test_missing_decoder_error_is_client_error() -> None:
    exc = MissingDecoderError(model=_Foo, registered_names=())
    assert isinstance(exc, ClientError)


def test_missing_decoder_error_pickle_roundtrip() -> None:
    exc = MissingDecoderError(
        model=_Foo,
        registered_names=("PydanticDecoder", "MsgspecDecoder"),
    )
    revived = pickle.loads(pickle.dumps(exc))  # noqa: S301
    assert isinstance(revived, MissingDecoderError)
    assert revived.model is _Foo
    assert revived.registered_names == ("PydanticDecoder", "MsgspecDecoder")


def test_circuit_open_error_is_client_error() -> None:
    exc = CircuitOpenError(retry_after=_RETRY_AFTER_2_5)
    assert isinstance(exc, ClientError)
    assert exc.retry_after == _RETRY_AFTER_2_5


def test_circuit_open_error_accepts_none_retry_after() -> None:
    exc = CircuitOpenError(retry_after=None)
    assert exc.retry_after is None


def test_circuit_open_error_summary_with_retry_after() -> None:
    exc = CircuitOpenError(retry_after=_RETRY_AFTER_2_5)
    assert str(exc) == "circuit open (retry_after=2.500s)"


def test_circuit_open_error_summary_with_none_retry_after() -> None:
    exc = CircuitOpenError(retry_after=None)
    assert str(exc) == "circuit open (a probe request is already in flight)"


def test_circuit_open_error_pickleable_with_float() -> None:
    exc = CircuitOpenError(retry_after=_RETRY_AFTER_2_5)
    restored = pickle.loads(pickle.dumps(exc))  # noqa: S301
    assert isinstance(restored, CircuitOpenError)
    assert restored.retry_after == _RETRY_AFTER_2_5


def test_circuit_open_error_pickleable_with_none() -> None:
    exc = CircuitOpenError(retry_after=None)
    restored = pickle.loads(pickle.dumps(exc))  # noqa: S301
    assert isinstance(restored, CircuitOpenError)
    assert restored.retry_after is None


def test_status_error_message_masks_query_secret() -> None:
    request = httpx2.Request("GET", "https://example.test/p?api_key=topsecret&page=2")
    response = httpx2.Response(404, request=request)
    exc = NotFoundError(response)
    assert "topsecret" not in str(exc)
    assert "api_key=REDACTED" in str(exc)
    assert "page=2" in str(exc)
    assert "topsecret" not in repr(exc)

"""Tests for the sync Retry middleware.

Mirror of test_retry.py. Mocks the transport via httpx2.MockTransport;
injects a recording ``_sleep`` callable so the suite runs instantly.
"""

import datetime
import email.utils
import logging
import typing
from collections.abc import Callable
from http import HTTPStatus

import httpx2
import pytest

from httpware import Client, NotFoundError, ServiceUnavailableError
from httpware._internal.status import STREAMING_BODY_MARKER, _is_streaming_body_sync
from httpware.errors import NetworkError, RetryBudgetExhaustedError, StatusError, TransportError
from httpware.errors import TimeoutError as HttpwareTimeoutError
from httpware.middleware.resilience.budget import RetryBudget
from httpware.middleware.resilience.retry import (
    DEFAULT_IDEMPOTENT_METHODS,
    DEFAULT_RETRY_STATUS_CODES,
    Retry,
)


class _SleepRecorder:
    def __init__(self) -> None:
        self.calls: list[float] = []

    def __call__(self, delay: float) -> None:
        self.calls.append(delay)


class _ResponseSequence:
    def __init__(self, statuses: list[int]) -> None:
        self._statuses = list(statuses)
        self.calls: int = 0

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.calls += 1
        status = self._statuses.pop(0) if self._statuses else HTTPStatus.OK
        return httpx2.Response(status, request=request)


class _ResponseSequenceWithHeaders:
    """Mock handler that returns (status, headers) tuples in sequence."""

    def __init__(self, responses: list[tuple[int, dict[str, str]]]) -> None:
        self._responses = list(responses)
        self.calls = 0

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.calls += 1
        status, headers = self._responses.pop(0)
        return httpx2.Response(status, request=request, headers=headers)


def _client(handler: Callable[[httpx2.Request], httpx2.Response], *, retry: Retry) -> Client:
    transport = httpx2.MockTransport(handler)
    return Client(
        httpx2_client=httpx2.Client(transport=transport),
        middleware=[retry],
    )


def _zero_budget() -> RetryBudget:
    """Return a budget that always refuses withdrawal (floor=0, percent=0)."""
    return RetryBudget(ttl=10.0, min_retries_per_sec=0.0, percent_can_retry=0.0)


def test_default_retry_status_codes_match_spec() -> None:
    # Module-level constant is shared with AsyncRetry; this test mirrors test_retry.py.
    assert frozenset({408, 429, 502, 503, 504}) == DEFAULT_RETRY_STATUS_CODES


def test_default_idempotent_methods_match_spec() -> None:
    assert frozenset({"GET", "HEAD", "OPTIONS", "PUT", "DELETE"}) == DEFAULT_IDEMPOTENT_METHODS


def test_succeeds_first_try_no_sleep() -> None:
    sleeper = _SleepRecorder()
    handler = _ResponseSequence([HTTPStatus.OK])
    client = _client(handler, retry=Retry(_sleep=sleeper))
    response = client.get("https://example.test/x")
    assert response.status_code == HTTPStatus.OK
    assert handler.calls == 1
    assert sleeper.calls == []


def test_retries_503_then_succeeds() -> None:
    sleeper = _SleepRecorder()
    handler = _ResponseSequence([HTTPStatus.SERVICE_UNAVAILABLE, HTTPStatus.OK])
    client = _client(handler, retry=Retry(_sleep=sleeper, base_delay=0.01, max_delay=0.02))
    response = client.get("https://example.test/x")
    assert response.status_code == HTTPStatus.OK
    assert handler.calls == 2  # noqa: PLR2004
    assert len(sleeper.calls) == 1
    assert 0.0 <= sleeper.calls[0] <= 0.02  # noqa: PLR2004


def test_gives_up_after_max_attempts_and_reraises_status_error() -> None:
    sleeper = _SleepRecorder()
    handler = _ResponseSequence([HTTPStatus.SERVICE_UNAVAILABLE] * 3)
    client = _client(handler, retry=Retry(_sleep=sleeper, base_delay=0.01, max_delay=0.02, max_attempts=3))
    with pytest.raises(ServiceUnavailableError) as info:
        client.get("https://example.test/x")
    assert handler.calls == 3  # noqa: PLR2004
    assert len(sleeper.calls) == 2  # noqa: PLR2004
    notes = getattr(info.value, "__notes__", [])
    assert any("gave up after 3 attempts" in note for note in notes)


def test_does_not_retry_non_retryable_status() -> None:
    sleeper = _SleepRecorder()
    handler = _ResponseSequence([HTTPStatus.NOT_FOUND])
    client = _client(handler, retry=Retry(_sleep=sleeper))
    with pytest.raises(NotFoundError):
        client.get("https://example.test/missing")
    assert handler.calls == 1
    assert sleeper.calls == []


def test_does_not_retry_non_idempotent_method() -> None:
    sleeper = _SleepRecorder()
    handler = _ResponseSequence([HTTPStatus.SERVICE_UNAVAILABLE])
    client = _client(handler, retry=Retry(_sleep=sleeper))
    with pytest.raises(ServiceUnavailableError):
        client.post("https://example.test/x")  # POST is not idempotent by default
    assert handler.calls == 1


def test_max_attempts_one_means_no_retries() -> None:
    sleeper = _SleepRecorder()
    handler = _ResponseSequence([HTTPStatus.SERVICE_UNAVAILABLE])
    client = _client(handler, retry=Retry(_sleep=sleeper, max_attempts=1))
    with pytest.raises(ServiceUnavailableError):
        client.get("https://example.test/x")
    assert handler.calls == 1
    assert sleeper.calls == []


def test_max_attempts_zero_rejected() -> None:
    with pytest.raises(ValueError, match="max_attempts must be >= 1"):
        Retry(max_attempts=0)


def test_streamed_body_request_is_refused() -> None:
    sleeper = _SleepRecorder()
    handler = _ResponseSequence([HTTPStatus.SERVICE_UNAVAILABLE])
    client = _client(handler, retry=Retry(_sleep=sleeper))

    # Manually craft a request with the streaming-body marker set.
    request = httpx2.Request("GET", "https://example.test/x")
    request.extensions[STREAMING_BODY_MARKER] = True

    with pytest.raises(ServiceUnavailableError) as info:
        client.send(request)

    notes = getattr(info.value, "__notes__", [])
    assert any("stream that cannot replay" in note for note in notes)
    assert sleeper.calls == []  # no retry attempted; no backoff


def test_streaming_body_refusal_emits_log_event(caplog: pytest.LogCaptureFixture) -> None:
    """Cover the streaming-body refusal _emit_event branch in sync Retry."""
    sleeper = _SleepRecorder()
    handler = _ResponseSequence([HTTPStatus.SERVICE_UNAVAILABLE])
    client = _client(handler, retry=Retry(_sleep=sleeper))

    request = httpx2.Request("GET", "https://example.test/x")
    request.extensions[STREAMING_BODY_MARKER] = True

    with caplog.at_level(logging.WARNING, logger="httpware.retry"), pytest.raises(ServiceUnavailableError):
        client.send(request)
    assert any("retry refused" in r.getMessage() for r in caplog.records)


def test_streaming_body_refusal_on_non_idempotent_method() -> None:
    """Streaming-body marker added to exception even when method isn't idempotent."""
    sleeper = _SleepRecorder()

    def handler(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        msg = "transient"
        raise httpx2.ConnectError(msg)

    client = _client(handler, retry=Retry(_sleep=sleeper))
    request = client.build_request("POST", "https://example.test/x")
    request.extensions[STREAMING_BODY_MARKER] = True
    with pytest.raises(NetworkError) as info:
        client.send(request)
    notes = getattr(info.value, "__notes__", [])
    assert any("stream that cannot replay" in note for note in notes)


def test_streaming_body_refusal_status_error_on_non_idempotent_method() -> None:
    """Status-error path: non-idempotent + retryable status + streaming marker -> note added."""
    sleeper = _SleepRecorder()
    handler = _ResponseSequence([HTTPStatus.SERVICE_UNAVAILABLE])
    client = _client(handler, retry=Retry(_sleep=sleeper))
    request = client.build_request("POST", "https://example.test/x")
    request.extensions[STREAMING_BODY_MARKER] = True
    with pytest.raises(ServiceUnavailableError) as info:
        client.send(request)
    notes = getattr(info.value, "__notes__", [])
    assert any("stream that cannot replay" in note for note in notes)


def test_client_post_with_sync_generator_content_marks_extensions() -> None:
    """Posting with a sync generator body sets the streaming marker on request.extensions."""
    seen_extensions: list[dict[str, object]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen_extensions.append(dict(request.extensions))
        return httpx2.Response(HTTPStatus.OK, request=request)

    def streamed_body() -> typing.Iterator[bytes]:
        yield b"chunk1"
        yield b"chunk2"

    transport = httpx2.MockTransport(handler)
    client = Client(httpx2_client=httpx2.Client(transport=transport))
    client.post("https://example.test/upload", content=streamed_body())

    assert len(seen_extensions) == 1
    assert seen_extensions[0].get(STREAMING_BODY_MARKER) is True


def test_client_post_with_list_content_does_not_mark_extensions() -> None:
    """A list body is replayable; should NOT be marked as streaming."""
    seen_extensions: list[dict[str, object]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen_extensions.append(dict(request.extensions))
        return httpx2.Response(HTTPStatus.OK, request=request)

    transport = httpx2.MockTransport(handler)
    client = Client(httpx2_client=httpx2.Client(transport=transport))
    client.post("https://example.test/upload", content=[b"chunk1", b"chunk2"])

    assert len(seen_extensions) == 1
    assert STREAMING_BODY_MARKER not in seen_extensions[0]


def test_budget_exhausted_raises_with_payload() -> None:
    sleeper = _SleepRecorder()
    # Tiny budget: 0 floor, 0 retries.
    budget = RetryBudget(ttl=10.0, min_retries_per_sec=0.0, percent_can_retry=0.0)
    handler = _ResponseSequence([HTTPStatus.SERVICE_UNAVAILABLE, HTTPStatus.OK])
    client = _client(handler, retry=Retry(_sleep=sleeper, budget=budget, max_attempts=3))
    with pytest.raises(RetryBudgetExhaustedError) as info:
        client.get("https://example.test/x")
    assert info.value.attempts == 1
    assert info.value.last_response is not None
    assert info.value.last_response.status_code == HTTPStatus.SERVICE_UNAVAILABLE


def test_budget_exhausted_on_network_error_carries_exception_not_response() -> None:
    sleeper = _SleepRecorder()

    def handler(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        msg = "transient"
        raise httpx2.ConnectError(msg)

    client = _client(
        handler,
        retry=Retry(_sleep=sleeper, budget=_zero_budget(), base_delay=0.01, max_delay=0.02),
    )
    with pytest.raises(RetryBudgetExhaustedError) as info:
        client.get("https://example.test/x")
    assert info.value.last_response is None
    assert isinstance(info.value.last_exception, NetworkError)


def test_retry_after_seconds_honored() -> None:
    sleeper = _SleepRecorder()

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            HTTPStatus.TOO_MANY_REQUESTS,
            request=request,
            headers={"Retry-After": "1"},
        )

    client = _client(handler, retry=Retry(_sleep=sleeper, base_delay=0.01, max_delay=0.5, max_attempts=2))
    with pytest.raises(StatusError):
        client.get("https://example.test/x")
    # Retry-After=1 clamped to max_delay=0.5
    assert sleeper.calls == [0.5]


def test_retry_after_http_date_overrides_backoff() -> None:
    sleeper = _SleepRecorder()
    future = datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=3)
    http_date = email.utils.format_datetime(future, usegmt=True)
    handler = _ResponseSequenceWithHeaders(
        [
            (HTTPStatus.SERVICE_UNAVAILABLE, {"Retry-After": http_date}),
            (HTTPStatus.OK, {}),
        ]
    )
    client = _client(handler, retry=Retry(_sleep=sleeper, base_delay=0.01, max_delay=10.0))
    response = client.get("https://example.test/x")
    assert response.status_code == HTTPStatus.OK
    assert len(sleeper.calls) == 1
    assert 2.0 <= sleeper.calls[0] <= 4.0  # noqa: PLR2004


def test_malformed_retry_after_falls_back_to_backoff() -> None:
    sleeper = _SleepRecorder()
    handler = _ResponseSequenceWithHeaders(
        [
            (HTTPStatus.SERVICE_UNAVAILABLE, {"Retry-After": "not-a-number"}),
            (HTTPStatus.OK, {}),
        ]
    )
    client = _client(handler, retry=Retry(_sleep=sleeper, base_delay=0.01, max_delay=0.05))
    client.get("https://example.test/x")
    assert len(sleeper.calls) == 1
    assert 0.0 <= sleeper.calls[0] <= 0.05  # noqa: PLR2004


def test_respect_retry_after_false_ignores_header() -> None:
    sleeper = _SleepRecorder()
    handler = _ResponseSequenceWithHeaders(
        [
            (HTTPStatus.SERVICE_UNAVAILABLE, {"Retry-After": "5"}),
            (HTTPStatus.OK, {}),
        ]
    )
    client = _client(
        handler,
        retry=Retry(_sleep=sleeper, respect_retry_after=False, base_delay=0.01, max_delay=0.02),
    )
    client.get("https://example.test/x")
    assert len(sleeper.calls) == 1
    assert 0.0 <= sleeper.calls[0] <= 0.02  # noqa: PLR2004


def test_retries_on_network_error() -> None:
    sleeper = _SleepRecorder()
    call_count = {"n": 0}

    def handler(request: httpx2.Request) -> httpx2.Response:
        call_count["n"] += 1
        if call_count["n"] < 2:  # noqa: PLR2004
            msg = "transient"
            raise httpx2.ConnectError(msg)
        return httpx2.Response(HTTPStatus.OK, request=request)

    client = _client(handler, retry=Retry(_sleep=sleeper, base_delay=0.01, max_delay=0.02))
    response = client.get("https://example.test/x")
    assert response.status_code == HTTPStatus.OK
    assert call_count["n"] == 2  # noqa: PLR2004
    assert len(sleeper.calls) == 1


def test_retries_on_httpware_timeout_error() -> None:
    sleeper = _SleepRecorder()
    call_count = {"n": 0}

    def handler(request: httpx2.Request) -> httpx2.Response:
        call_count["n"] += 1
        if call_count["n"] < 2:  # noqa: PLR2004
            msg = "read timeout"
            raise httpx2.ReadTimeout(msg)
        return httpx2.Response(HTTPStatus.OK, request=request)

    client = _client(handler, retry=Retry(_sleep=sleeper, base_delay=0.01, max_delay=0.02))
    response = client.get("https://example.test/x")
    assert response.status_code == HTTPStatus.OK
    assert call_count["n"] == 2  # noqa: PLR2004
    assert isinstance(HttpwareTimeoutError("x"), HttpwareTimeoutError)  # type smoke


def test_does_not_retry_on_bare_transport_error_like_invalid_url() -> None:
    sleeper = _SleepRecorder()

    def handler(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        msg = "bad url"
        raise httpx2.InvalidURL(msg)

    client = _client(handler, retry=Retry(_sleep=sleeper))
    with pytest.raises(TransportError) as info:
        client.get("https://example.test/x")
    assert not isinstance(info.value, NetworkError)
    assert sleeper.calls == []


def test_network_error_exhaustion_reraises_with_note() -> None:
    sleeper = _SleepRecorder()

    def handler(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        msg = "never works"
        raise httpx2.ConnectError(msg)

    client = _client(handler, retry=Retry(_sleep=sleeper, max_attempts=2, base_delay=0.01, max_delay=0.02))
    with pytest.raises(NetworkError) as info:
        client.get("https://example.test/x")
    notes = getattr(info.value, "__notes__", [])
    assert any("gave up after 2 attempts" in note for note in notes)


def test_does_not_retry_network_error_on_non_idempotent_method() -> None:
    sleeper = _SleepRecorder()
    call_count = {"n": 0}

    def handler(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        call_count["n"] += 1
        msg = "transient"
        raise httpx2.ConnectError(msg)

    client = _client(handler, retry=Retry(_sleep=sleeper))
    with pytest.raises(NetworkError):
        client.post("https://example.test/x", json={"x": 1})
    assert call_count["n"] == 1
    assert sleeper.calls == []


def test_retries_post_when_method_explicitly_included() -> None:
    sleeper = _SleepRecorder()
    handler = _ResponseSequence([HTTPStatus.SERVICE_UNAVAILABLE, HTTPStatus.OK])
    client = _client(
        handler,
        retry=Retry(
            _sleep=sleeper,
            base_delay=0.01,
            max_delay=0.02,
            retry_methods=frozenset({"GET", "POST"}),
        ),
    )
    response = client.post("https://example.test/x", json={"k": "v"})
    assert response.status_code == HTTPStatus.OK
    assert handler.calls == 2  # noqa: PLR2004
    assert len(sleeper.calls) == 1


def test_default_budget_is_fresh_per_instance() -> None:
    r1 = Retry()
    r2 = Retry()
    assert r1.budget is not r2.budget


def test_explicit_budget_shared_across_retry_instances() -> None:
    shared = RetryBudget(ttl=10.0, min_retries_per_sec=1.0, percent_can_retry=0.0)
    r1 = Retry(budget=shared)
    r2 = Retry(budget=shared)
    assert r1.budget is r2.budget


def test_emits_giving_up_log_event(caplog: pytest.LogCaptureFixture) -> None:
    sleeper = _SleepRecorder()
    handler = _ResponseSequence([HTTPStatus.SERVICE_UNAVAILABLE] * 2)
    client = _client(handler, retry=Retry(_sleep=sleeper, base_delay=0.01, max_attempts=2))
    with caplog.at_level(logging.WARNING, logger="httpware.retry"), pytest.raises(ServiceUnavailableError):
        client.get("https://example.test/x")
    assert any("retry gave up" in r.getMessage() for r in caplog.records)


def test_emits_budget_refused_log_event(caplog: pytest.LogCaptureFixture) -> None:
    sleeper = _SleepRecorder()
    handler = _ResponseSequence([HTTPStatus.SERVICE_UNAVAILABLE, HTTPStatus.OK])
    client = _client(handler, retry=Retry(_sleep=sleeper, budget=_zero_budget(), max_attempts=3))
    with caplog.at_level(logging.WARNING, logger="httpware.retry"), pytest.raises(RetryBudgetExhaustedError):
        client.get("https://example.test/x")
    assert any("budget refused" in r.getMessage() for r in caplog.records)


def test_is_streaming_body_sync_predicates() -> None:
    assert _is_streaming_body_sync(None) is False
    assert _is_streaming_body_sync(b"bytes") is False
    assert _is_streaming_body_sync("str") is False
    assert _is_streaming_body_sync({"k": "v"}) is False
    assert _is_streaming_body_sync([1, 2]) is False
    assert _is_streaming_body_sync((1, 2)) is False
    assert _is_streaming_body_sync(iter([1, 2])) is True
    assert _is_streaming_body_sync(x for x in range(3)) is True  # generator

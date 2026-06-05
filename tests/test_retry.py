"""Tests for the Retry middleware.

Mocks the transport via httpx2.MockTransport; injects a recording `_sleep`
callable so the suite runs instantly without freezegun.
"""

import asyncio
import datetime
import email.utils
import logging
import typing
from collections.abc import Callable
from http import HTTPStatus

import httpx2
import pytest

from httpware import AsyncClient, NotFoundError, ServiceUnavailableError, TransportError
from httpware.client import _is_streaming_body
from httpware.errors import NetworkError, RetryBudgetExhaustedError
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

    async def __call__(self, delay: float) -> None:
        self.calls.append(delay)


class _ResponseSequence:
    """Mock-transport handler that returns a fixed sequence of responses."""

    def __init__(self, statuses: list[int]) -> None:
        self._statuses = list(statuses)
        self.calls: int = 0

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.calls += 1
        status = self._statuses.pop(0) if self._statuses else HTTPStatus.OK
        return httpx2.Response(status, request=request)


def _client(handler: Callable[[httpx2.Request], httpx2.Response], *, retry: Retry) -> AsyncClient:
    transport = httpx2.MockTransport(handler)
    return AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=transport),
        middleware=[retry],
    )


def test_default_retry_status_codes_match_spec() -> None:
    assert frozenset({408, 429, 502, 503, 504}) == DEFAULT_RETRY_STATUS_CODES


def test_default_idempotent_methods_match_spec() -> None:
    assert frozenset({"GET", "HEAD", "OPTIONS", "PUT", "DELETE"}) == DEFAULT_IDEMPOTENT_METHODS


async def test_succeeds_first_try_no_sleep() -> None:
    sleeper = _SleepRecorder()
    handler = _ResponseSequence([HTTPStatus.OK])
    client = _client(handler, retry=Retry(_sleep=sleeper))
    response = await client.get("https://example.test/x")
    assert response.status_code == HTTPStatus.OK
    assert handler.calls == 1
    assert sleeper.calls == []


async def test_retries_503_then_succeeds() -> None:
    sleeper = _SleepRecorder()
    handler = _ResponseSequence([HTTPStatus.SERVICE_UNAVAILABLE, HTTPStatus.OK])
    client = _client(handler, retry=Retry(_sleep=sleeper, base_delay=0.01, max_delay=0.02))
    response = await client.get("https://example.test/x")
    assert response.status_code == HTTPStatus.OK
    assert handler.calls == 2  # noqa: PLR2004 — "2" is intentional literal in test assertion
    assert len(sleeper.calls) == 1
    assert 0.0 <= sleeper.calls[0] <= 0.02  # noqa: PLR2004 — 0.02 matches max_delay literal above


async def test_gives_up_after_max_attempts_and_reraises_status_error() -> None:
    sleeper = _SleepRecorder()
    handler = _ResponseSequence([HTTPStatus.SERVICE_UNAVAILABLE] * 3)
    client = _client(handler, retry=Retry(_sleep=sleeper, base_delay=0.01, max_delay=0.02, max_attempts=3))
    with pytest.raises(ServiceUnavailableError) as info:
        await client.get("https://example.test/x")
    assert handler.calls == 3  # noqa: PLR2004 — "3" is intentional literal in test assertion
    assert len(sleeper.calls) == 2  # noqa: PLR2004 — max_attempts=3 → 2 sleeps between 3 attempts
    notes = getattr(info.value, "__notes__", [])
    assert any("gave up after 3 attempts" in note for note in notes)


async def test_does_not_retry_non_retryable_status() -> None:
    sleeper = _SleepRecorder()
    handler = _ResponseSequence([HTTPStatus.NOT_FOUND])
    client = _client(handler, retry=Retry(_sleep=sleeper))
    with pytest.raises(NotFoundError):
        await client.get("https://example.test/x")
    assert handler.calls == 1
    assert sleeper.calls == []


async def test_does_not_retry_non_idempotent_methods_by_default() -> None:
    sleeper = _SleepRecorder()
    handler = _ResponseSequence([HTTPStatus.SERVICE_UNAVAILABLE])
    client = _client(handler, retry=Retry(_sleep=sleeper))
    with pytest.raises(ServiceUnavailableError):
        await client.post("https://example.test/x", json={"x": 1})
    assert handler.calls == 1
    assert sleeper.calls == []


async def test_retries_post_when_method_explicitly_included() -> None:
    sleeper = _SleepRecorder()
    handler = _ResponseSequence([HTTPStatus.SERVICE_UNAVAILABLE, HTTPStatus.OK])
    methods = frozenset(DEFAULT_IDEMPOTENT_METHODS | {"POST"})
    client = _client(
        handler,
        retry=Retry(_sleep=sleeper, retry_methods=methods, base_delay=0.01, max_delay=0.02),
    )
    response = await client.post("https://example.test/x", json={"x": 1})
    assert response.status_code == HTTPStatus.OK
    assert handler.calls == 2  # noqa: PLR2004 — "2" is intentional literal in test assertion


async def test_max_attempts_one_means_no_retries() -> None:
    sleeper = _SleepRecorder()
    handler = _ResponseSequence([HTTPStatus.SERVICE_UNAVAILABLE])
    client = _client(handler, retry=Retry(_sleep=sleeper, max_attempts=1))
    with pytest.raises(ServiceUnavailableError):
        await client.get("https://example.test/x")
    assert handler.calls == 1
    assert sleeper.calls == []


def test_max_attempts_zero_rejected() -> None:
    with pytest.raises(ValueError, match="max_attempts must be >= 1"):
        Retry(max_attempts=0)


async def test_budget_exhausted_raises_retry_budget_exhausted_error() -> None:
    # NOTE: lives here for coverage of the Retry loop's budget-exhaustion branch.
    # Task 11 adds the broader budget-gate + sharing tests (carry-through behavior,
    # last_response / last_exception field population). Do NOT duplicate this test.
    sleeper = _SleepRecorder()
    handler = _ResponseSequence([HTTPStatus.SERVICE_UNAVAILABLE, HTTPStatus.SERVICE_UNAVAILABLE])
    # Budget with zero tolerance: percent_can_retry=0.0, min_retries_per_sec=0.0 → ceiling=0
    stingy_budget = RetryBudget(percent_can_retry=0.0, min_retries_per_sec=0.0)
    client = _client(
        handler,
        retry=Retry(_sleep=sleeper, budget=stingy_budget, max_attempts=3, base_delay=0.01),
    )
    with pytest.raises(RetryBudgetExhaustedError) as info:
        await client.get("https://example.test/x")
    assert handler.calls == 1
    assert info.value.attempts == 1
    assert sleeper.calls == []


async def test_retries_on_network_error() -> None:
    sleeper = _SleepRecorder()
    call_count = {"n": 0}

    def handler(request: httpx2.Request) -> httpx2.Response:
        call_count["n"] += 1
        if call_count["n"] < 2:  # noqa: PLR2004 — "2" is intentional literal in test assertion
            msg = "transient"
            raise httpx2.ConnectError(msg)
        return httpx2.Response(HTTPStatus.OK, request=request)

    client = _client(handler, retry=Retry(_sleep=sleeper, base_delay=0.01, max_delay=0.02))
    response = await client.get("https://example.test/x")
    assert response.status_code == HTTPStatus.OK
    assert call_count["n"] == 2  # noqa: PLR2004 — "2" is intentional literal in test assertion
    assert len(sleeper.calls) == 1


async def test_retries_on_httpware_timeout_error() -> None:
    sleeper = _SleepRecorder()
    call_count = {"n": 0}

    def handler(request: httpx2.Request) -> httpx2.Response:
        call_count["n"] += 1
        if call_count["n"] < 2:  # noqa: PLR2004 — "2" is intentional literal in test assertion
            msg = "read timeout"
            raise httpx2.ReadTimeout(msg)
        return httpx2.Response(HTTPStatus.OK, request=request)

    client = _client(handler, retry=Retry(_sleep=sleeper, base_delay=0.01, max_delay=0.02))
    response = await client.get("https://example.test/x")
    assert response.status_code == HTTPStatus.OK
    assert call_count["n"] == 2  # noqa: PLR2004 — "2" is intentional literal in test assertion
    assert len(sleeper.calls) == 1


async def test_does_not_retry_on_bare_transport_error_like_invalid_url() -> None:
    sleeper = _SleepRecorder()

    def handler(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        msg = "bad url"
        raise httpx2.InvalidURL(msg)

    client = _client(handler, retry=Retry(_sleep=sleeper))
    with pytest.raises(TransportError) as info:
        await client.get("https://example.test/x")
    assert not isinstance(info.value, NetworkError)
    assert sleeper.calls == []


async def test_network_error_exhaustion_reraises_with_note() -> None:
    sleeper = _SleepRecorder()

    def handler(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        msg = "never works"
        raise httpx2.ConnectError(msg)

    client = _client(handler, retry=Retry(_sleep=sleeper, max_attempts=2, base_delay=0.01, max_delay=0.02))
    with pytest.raises(NetworkError) as info:
        await client.get("https://example.test/x")
    notes = getattr(info.value, "__notes__", [])
    assert any("gave up after 2 attempts" in note for note in notes)


async def test_does_not_retry_network_error_on_non_idempotent_method() -> None:
    sleeper = _SleepRecorder()
    call_count = {"n": 0}

    def handler(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        call_count["n"] += 1
        msg = "transient"
        raise httpx2.ConnectError(msg)

    client = _client(handler, retry=Retry(_sleep=sleeper))
    with pytest.raises(NetworkError):
        await client.post("https://example.test/x", json={"x": 1})
    assert call_count["n"] == 1
    assert sleeper.calls == []


async def test_attempt_timeout_fires_and_retries() -> None:
    sleeper = _SleepRecorder()
    call_count = {"n": 0}

    async def handler_async(request: httpx2.Request) -> httpx2.Response:
        call_count["n"] += 1
        if call_count["n"] < 2:  # noqa: PLR2004 — "2" is intentional literal in test assertion
            await asyncio.sleep(1.0)  # exceeds attempt_timeout
        return httpx2.Response(HTTPStatus.OK, request=request)

    transport = httpx2.MockTransport(handler_async)
    client = AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=transport),
        middleware=[Retry(_sleep=sleeper, attempt_timeout=0.05, base_delay=0.01, max_delay=0.02)],
    )
    response = await client.get("https://example.test/x")
    # coverage[thread] loses the coroutine frame after asyncio.timeout-induced cancellation.
    # The assertions DO execute — verified by intentionally breaking them (test fails as
    # expected). Pragmas mask a tooling limitation, not dead code.
    assert response.status_code == HTTPStatus.OK  # pragma: no cover
    assert call_count["n"] == 2  # pragma: no cover  # noqa: PLR2004 — "2" is intentional literal in test assertion


async def test_attempt_timeout_exhaustion_raises_httpware_timeout() -> None:
    sleeper = _SleepRecorder()

    async def slow_handler(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        await asyncio.sleep(1.0)
        msg = "should not reach"  # pragma: no cover
        raise AssertionError(msg)  # pragma: no cover

    transport = httpx2.MockTransport(slow_handler)
    client = AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=transport),
        middleware=[Retry(_sleep=sleeper, attempt_timeout=0.05, max_attempts=2, base_delay=0.01, max_delay=0.02)],
    )
    with pytest.raises(HttpwareTimeoutError) as info:
        await client.get("https://example.test/x")
    notes = getattr(info.value, "__notes__", [])
    assert any("gave up after 2 attempts" in note for note in notes)


async def test_attempt_timeout_does_not_retry_on_non_idempotent_method() -> None:
    sleeper = _SleepRecorder()

    async def slow_handler(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        await asyncio.sleep(1.0)
        msg = "should not reach"  # pragma: no cover
        raise AssertionError(msg)  # pragma: no cover

    transport = httpx2.MockTransport(slow_handler)
    client = AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=transport),
        middleware=[Retry(_sleep=sleeper, attempt_timeout=0.05)],
    )
    with pytest.raises(HttpwareTimeoutError):
        await client.post("https://example.test/x", json={"x": 1})
    assert sleeper.calls == []  # not retried


class _ResponseSequenceWithHeaders:
    """Mock handler that returns (status, headers) tuples in sequence."""

    def __init__(self, responses: list[tuple[int, dict[str, str]]]) -> None:
        self._responses = list(responses)
        self.calls = 0

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.calls += 1
        status, headers = self._responses.pop(0)
        return httpx2.Response(status, request=request, headers=headers)


async def test_retry_after_seconds_overrides_backoff() -> None:
    sleeper = _SleepRecorder()
    handler = _ResponseSequenceWithHeaders(
        [
            (HTTPStatus.SERVICE_UNAVAILABLE, {"Retry-After": "2"}),
            (HTTPStatus.OK, {}),
        ]
    )
    client = _client(handler, retry=Retry(_sleep=sleeper, base_delay=0.01, max_delay=5.0))
    response = await client.get("https://example.test/x")
    assert response.status_code == HTTPStatus.OK
    assert sleeper.calls == [2.0]


async def test_retry_after_http_date_overrides_backoff() -> None:
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
    response = await client.get("https://example.test/x")
    assert response.status_code == HTTPStatus.OK
    assert len(sleeper.calls) == 1
    assert 2.0 <= sleeper.calls[0] <= 4.0  # noqa: PLR2004 — ~3 seconds, with clock-skew tolerance


async def test_retry_after_capped_at_max_delay() -> None:
    sleeper = _SleepRecorder()
    handler = _ResponseSequenceWithHeaders(
        [
            (HTTPStatus.SERVICE_UNAVAILABLE, {"Retry-After": "9999"}),
            (HTTPStatus.OK, {}),
        ]
    )
    client = _client(handler, retry=Retry(_sleep=sleeper, base_delay=0.01, max_delay=2.5))
    await client.get("https://example.test/x")
    assert sleeper.calls == [2.5]


async def test_malformed_retry_after_falls_back_to_backoff() -> None:
    sleeper = _SleepRecorder()
    handler = _ResponseSequenceWithHeaders(
        [
            (HTTPStatus.SERVICE_UNAVAILABLE, {"Retry-After": "not-a-number"}),
            (HTTPStatus.OK, {}),
        ]
    )
    client = _client(handler, retry=Retry(_sleep=sleeper, base_delay=0.01, max_delay=0.05))
    await client.get("https://example.test/x")
    assert len(sleeper.calls) == 1
    assert 0.0 <= sleeper.calls[0] <= 0.05  # noqa: PLR2004 — 0.05 matches max_delay literal above


async def test_respect_retry_after_false_ignores_header() -> None:
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
    await client.get("https://example.test/x")
    assert len(sleeper.calls) == 1
    assert 0.0 <= sleeper.calls[0] <= 0.02  # noqa: PLR2004 — backoff range, not 5


def _zero_budget() -> RetryBudget:
    """Return a budget that always refuses withdrawal (floor=0, percent=0)."""
    return RetryBudget(ttl=10.0, min_retries_per_sec=0.0, percent_can_retry=0.0)


async def test_budget_exhausted_raises_specific_exception() -> None:
    sleeper = _SleepRecorder()
    handler = _ResponseSequence([HTTPStatus.SERVICE_UNAVAILABLE, HTTPStatus.OK])
    client = _client(
        handler,
        retry=Retry(_sleep=sleeper, budget=_zero_budget(), base_delay=0.01, max_delay=0.02),
    )
    with pytest.raises(RetryBudgetExhaustedError) as info:
        await client.get("https://example.test/x")
    assert info.value.attempts == 1  # one attempt made, budget refused before retry
    assert info.value.last_response is not None
    assert info.value.last_response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
    assert isinstance(info.value.last_exception, ServiceUnavailableError)


async def test_budget_exhausted_on_network_error_carries_exception_not_response() -> None:
    sleeper = _SleepRecorder()

    def handler(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        msg = "transient"
        raise httpx2.ConnectError(msg)

    client = _client(
        handler,
        retry=Retry(_sleep=sleeper, budget=_zero_budget(), base_delay=0.01, max_delay=0.02),
    )
    with pytest.raises(RetryBudgetExhaustedError) as info:
        await client.get("https://example.test/x")
    assert info.value.last_response is None
    assert isinstance(info.value.last_exception, NetworkError)


async def test_default_budget_is_fresh_per_instance() -> None:
    r1 = Retry()
    r2 = Retry()
    assert r1.budget is not r2.budget


async def test_explicit_budget_shared_across_retry_instances() -> None:
    shared = RetryBudget(ttl=10.0, min_retries_per_sec=1.0, percent_can_retry=0.0)
    r1 = Retry(budget=shared)
    r2 = Retry(budget=shared)
    assert r1.budget is r2.budget
    # 10 retries total before exhaustion (floor=10)
    for _ in range(10):
        assert shared.try_withdraw() is True
    assert shared.try_withdraw() is False


async def test_client_post_with_async_iterable_content_marks_extensions() -> None:
    """Posting with an async-iterable body sets the httpware.streaming_body marker on request.extensions."""
    seen_extensions: list[dict[str, object]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen_extensions.append(dict(request.extensions))
        return httpx2.Response(HTTPStatus.OK, request=request)

    async def streamed_body() -> typing.AsyncIterator[bytes]:
        yield b"chunk1"
        yield b"chunk2"

    transport = httpx2.MockTransport(handler)
    client = AsyncClient(httpx2_client=httpx2.AsyncClient(transport=transport))
    await client.post("https://example.test/upload", content=streamed_body())

    assert len(seen_extensions) == 1
    assert seen_extensions[0].get("httpware.streaming_body") is True


async def test_client_post_with_bytes_content_does_not_mark_extensions() -> None:
    seen_extensions: list[dict[str, object]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen_extensions.append(dict(request.extensions))
        return httpx2.Response(HTTPStatus.OK, request=request)

    transport = httpx2.MockTransport(handler)
    client = AsyncClient(httpx2_client=httpx2.AsyncClient(transport=transport))
    await client.post("https://example.test/upload", content=b"hi")

    assert len(seen_extensions) == 1
    assert "httpware.streaming_body" not in seen_extensions[0]


async def test_client_post_with_dict_data_does_not_mark_extensions() -> None:
    seen_extensions: list[dict[str, object]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen_extensions.append(dict(request.extensions))
        return httpx2.Response(HTTPStatus.OK, request=request)

    transport = httpx2.MockTransport(handler)
    client = AsyncClient(httpx2_client=httpx2.AsyncClient(transport=transport))
    await client.post("https://example.test/upload", data={"k": "v"})

    assert len(seen_extensions) == 1
    assert "httpware.streaming_body" not in seen_extensions[0]


async def test_client_post_with_async_iterable_data_marks_extensions() -> None:
    seen_extensions: list[dict[str, object]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen_extensions.append(dict(request.extensions))
        return httpx2.Response(HTTPStatus.OK, request=request)

    async def streamed_data() -> typing.AsyncIterator[bytes]:
        yield b"x"

    transport = httpx2.MockTransport(handler)
    client = AsyncClient(httpx2_client=httpx2.AsyncClient(transport=transport))
    await client.post("https://example.test/upload", data=streamed_data())

    assert len(seen_extensions) == 1
    assert seen_extensions[0].get("httpware.streaming_body") is True


def test_is_streaming_body_true_for_async_iterable_files() -> None:
    """_is_streaming_body returns True for an async-iterable, covering the files= path."""

    async def streamed_files() -> typing.AsyncIterator[bytes]:
        yield b"x"  # pragma: no cover

    assert _is_streaming_body(streamed_files()) is True


async def test_retry_refuses_streamed_body_request() -> None:
    """Retry must not replay a request with a streaming body — re-raise with a PEP-678 note."""
    sleeper = _SleepRecorder()
    call_count = {"n": 0}

    def handler(request: httpx2.Request) -> httpx2.Response:
        call_count["n"] += 1
        return httpx2.Response(HTTPStatus.SERVICE_UNAVAILABLE, request=request)

    async def streamed_body() -> typing.AsyncIterator[bytes]:
        yield b"x"

    transport = httpx2.MockTransport(handler)
    client = AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=transport),
        middleware=[Retry(_sleep=sleeper, base_delay=0.001, max_delay=0.002)],
    )

    with pytest.raises(ServiceUnavailableError) as info:
        await client.post("https://example.test/upload", content=streamed_body())

    assert call_count["n"] == 1
    assert sleeper.calls == []  # no retry attempted
    notes = getattr(info.value, "__notes__", [])
    assert any("not retrying" in note and "stream" in note for note in notes)


async def test_retry_refuses_streamed_body_does_not_consume_budget() -> None:
    """When Retry refuses for streaming-body reasons, no budget token is withdrawn."""
    sleeper = _SleepRecorder()
    budget = RetryBudget(ttl=10.0, min_retries_per_sec=10.0, percent_can_retry=0.2)

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(HTTPStatus.SERVICE_UNAVAILABLE, request=request)

    async def streamed_body() -> typing.AsyncIterator[bytes]:
        yield b"x"

    transport = httpx2.MockTransport(handler)
    client = AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=transport),
        middleware=[Retry(_sleep=sleeper, budget=budget, base_delay=0.001, max_delay=0.002)],
    )

    with pytest.raises(ServiceUnavailableError):
        await client.post("https://example.test/upload", content=streamed_body())

    # Budget should be untouched: deposits OK (every attempt deposits), but no withdrawals.
    # Check via _withdrawn deque emptiness.
    assert len(budget._withdrawn) == 0  # noqa: SLF001 — implementation-detail access for invariant


async def test_retry_refuses_streamed_body_network_error_non_idempotent() -> None:
    """Streaming POST that hits a NetworkError gets the PEP-678 note."""
    sleeper = _SleepRecorder()

    def handler(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        msg = "transient"
        raise httpx2.ConnectError(msg)

    async def streamed_body() -> typing.AsyncIterator[bytes]:
        yield b"x"

    transport = httpx2.MockTransport(handler)
    client = AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=transport),
        middleware=[Retry(_sleep=sleeper, base_delay=0.001, max_delay=0.002)],
    )

    with pytest.raises(NetworkError) as info:
        await client.post("https://example.test/upload", content=streamed_body())

    assert sleeper.calls == []  # no retry attempted
    notes = getattr(info.value, "__notes__", [])
    assert any("not retrying" in note and "stream" in note for note in notes)


async def test_retry_refuses_streamed_body_attempt_timeout_non_idempotent() -> None:
    """Streaming POST that times out per attempt_timeout gets the PEP-678 note."""
    sleeper = _SleepRecorder()

    async def slow_handler(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        await asyncio.sleep(1.0)
        msg = "should not reach"  # pragma: no cover
        raise AssertionError(msg)  # pragma: no cover

    async def streamed_body() -> typing.AsyncIterator[bytes]:
        yield b"x"

    transport = httpx2.MockTransport(slow_handler)
    client = AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=transport),
        middleware=[Retry(_sleep=sleeper, attempt_timeout=0.05, base_delay=0.001, max_delay=0.002)],
    )

    with pytest.raises(HttpwareTimeoutError) as info:
        await client.post("https://example.test/upload", content=streamed_body())

    assert sleeper.calls == []  # no retry attempted
    notes = getattr(info.value, "__notes__", [])
    assert any("not retrying" in note and "stream" in note for note in notes)


async def test_retry_refuses_streamed_body_idempotent_method() -> None:
    """Streaming GET that hits a retryable status gets the PEP-678 note instead of retrying."""
    sleeper = _SleepRecorder()
    call_count = {"n": 0}

    def handler(request: httpx2.Request) -> httpx2.Response:
        call_count["n"] += 1
        return httpx2.Response(HTTPStatus.SERVICE_UNAVAILABLE, request=request)

    async def streamed_body() -> typing.AsyncIterator[bytes]:
        yield b"x"

    transport = httpx2.MockTransport(handler)
    client = AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=transport),
        middleware=[Retry(_sleep=sleeper, base_delay=0.001, max_delay=0.002)],
    )

    with pytest.raises(ServiceUnavailableError) as info:
        await client.put("https://example.test/data", content=streamed_body())

    assert call_count["n"] == 1
    assert sleeper.calls == []  # no retry attempted
    notes = getattr(info.value, "__notes__", [])
    assert any("not retrying" in note and "stream" in note for note in notes)


async def test_retry_giving_up_emits_observability_event(caplog: pytest.LogCaptureFixture) -> None:
    """When max_attempts is exhausted, emit one WARNING record on httpware.retry."""
    sleeper = _SleepRecorder()
    handler = _ResponseSequence([HTTPStatus.SERVICE_UNAVAILABLE] * 3)
    client = _client(handler, retry=Retry(_sleep=sleeper, max_attempts=3, base_delay=0.001, max_delay=0.002))

    with caplog.at_level(logging.WARNING, logger="httpware.retry"), pytest.raises(ServiceUnavailableError):
        await client.get("https://example.test/x")

    retry_records = [r for r in caplog.records if r.name == "httpware.retry"]
    giving_up_records = [r for r in retry_records if r.message.startswith("retry gave up")]
    assert len(giving_up_records) == 1
    record = giving_up_records[0]
    assert record.levelno == logging.WARNING
    assert record.attempts == 3  # noqa: PLR2004 — 3 matches max_attempts=3 literal above  # ty: ignore[unresolved-attribute]
    assert record.method == "GET"  # ty: ignore[unresolved-attribute]
    assert record.last_status == HTTPStatus.SERVICE_UNAVAILABLE  # ty: ignore[unresolved-attribute]
    assert record.last_exception_type == "ServiceUnavailableError"  # ty: ignore[unresolved-attribute]


async def test_retry_budget_refused_emits_observability_event(caplog: pytest.LogCaptureFixture) -> None:
    """When the budget refuses a retry, emit one WARNING record on httpware.retry."""
    sleeper = _SleepRecorder()
    stingy_budget = RetryBudget(percent_can_retry=0.0, min_retries_per_sec=0.0)
    handler = _ResponseSequence([HTTPStatus.SERVICE_UNAVAILABLE, HTTPStatus.SERVICE_UNAVAILABLE])
    client = _client(
        handler,
        retry=Retry(_sleep=sleeper, budget=stingy_budget, max_attempts=3, base_delay=0.001),
    )

    with caplog.at_level(logging.WARNING, logger="httpware.retry"), pytest.raises(RetryBudgetExhaustedError):
        await client.get("https://example.test/x")

    retry_records = [r for r in caplog.records if r.name == "httpware.retry"]
    budget_records = [r for r in retry_records if "budget" in r.message]
    assert len(budget_records) == 1
    record = budget_records[0]
    assert record.attempts == 1  # ty: ignore[unresolved-attribute]
    assert record.method == "GET"  # ty: ignore[unresolved-attribute]
    assert record.last_status == HTTPStatus.SERVICE_UNAVAILABLE  # ty: ignore[unresolved-attribute]


async def test_retry_streaming_refused_emits_observability_event(caplog: pytest.LogCaptureFixture) -> None:
    """When the streaming-body marker prevents a retryable retry, emit one WARNING record on httpware.retry.

    Uses an idempotent method (PUT) so we hit the retryable-failure-path streaming-refusal site,
    NOT the non-idempotent early-exit sites (which don't emit the event per the spec).
    """
    sleeper = _SleepRecorder()
    handler = _ResponseSequence([HTTPStatus.SERVICE_UNAVAILABLE, HTTPStatus.SERVICE_UNAVAILABLE])
    client = _client(handler, retry=Retry(_sleep=sleeper, base_delay=0.001, max_delay=0.002))

    async def streamed_body() -> typing.AsyncIterator[bytes]:
        yield b"x"

    with caplog.at_level(logging.WARNING, logger="httpware.retry"), pytest.raises(ServiceUnavailableError):
        await client.put("https://example.test/x", content=streamed_body())

    retry_records = [r for r in caplog.records if r.name == "httpware.retry"]
    streaming_records = [r for r in retry_records if "stream" in r.message]
    assert len(streaming_records) == 1
    record = streaming_records[0]
    assert record.method == "PUT"  # ty: ignore[unresolved-attribute]
    assert record.last_exception_type == "ServiceUnavailableError"  # ty: ignore[unresolved-attribute]

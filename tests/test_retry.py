"""Tests for the Retry middleware.

Mocks the transport via httpx2.MockTransport; injects a recording `_sleep`
callable so the suite runs instantly without freezegun.
"""

import asyncio
import datetime
import email.utils
from collections.abc import Callable
from http import HTTPStatus

import httpx2
import pytest

from httpware import AsyncClient, NotFoundError, ServiceUnavailableError, TransportError
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

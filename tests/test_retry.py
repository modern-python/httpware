"""Tests for the Retry middleware.

Mocks the transport via httpx2.MockTransport; injects a recording `_sleep`
callable so the suite runs instantly without freezegun.
"""

from collections.abc import Callable
from http import HTTPStatus

import httpx2
import pytest

from httpware import AsyncClient, NotFoundError, ServiceUnavailableError, TransportError
from httpware.errors import NetworkError, RetryBudgetExhaustedError
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

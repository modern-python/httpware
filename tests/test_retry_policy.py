"""Seam-level tests for _RetryPolicy.decide.

Drives the decision directly — no client, no MockTransport — across the full
matrix: classification, streaming-body refusal, exhaustion, Retry-After
handling, budget refusal, and the delay returned on a normal retry. The jitter
path is random, so it is asserted by bounds; the Retry-After path by exact value.
"""

import httpx2
import pytest

from httpware._internal.status import STREAMING_BODY_MARKER
from httpware.errors import (
    NetworkError,
    NotFoundError,
    RetryBudgetExhaustedError,
    ServiceUnavailableError,
    StatusError,
    TimeoutError,  # noqa: A004
)
from httpware.middleware.resilience.budget import RetryBudget
from httpware.middleware.resilience.retry import (
    DEFAULT_IDEMPOTENT_METHODS,
    DEFAULT_RETRY_STATUS_CODES,
    _RetryPolicy,
)


_URL = "https://example.test/x"
_BASE_DELAY = 0.1
_MAX_DELAY = 5.0


def _policy(
    *,
    max_attempts: int = 3,
    respect_retry_after: bool = True,
    budget: RetryBudget | None = None,
) -> _RetryPolicy:
    return _RetryPolicy(
        max_attempts=max_attempts,
        base_delay=_BASE_DELAY,
        max_delay=_MAX_DELAY,
        retry_status_codes=DEFAULT_RETRY_STATUS_CODES,
        retry_methods=DEFAULT_IDEMPOTENT_METHODS,
        respect_retry_after=respect_retry_after,
        budget=budget,
    )


def _zero_budget() -> RetryBudget:
    """A budget that always refuses withdrawal (floor=0, percent=0)."""
    return RetryBudget(ttl=10.0, min_retries_per_sec=0.0, percent_can_retry=0.0)


def _request(method: str = "PUT", *, streaming: bool = False) -> httpx2.Request:
    extensions = {STREAMING_BODY_MARKER: True} if streaming else None
    return httpx2.Request(method, _URL, extensions=extensions)


def _status_exc(
    status: int,
    request: httpx2.Request,
    *,
    retry_after: str | None = None,
) -> StatusError:
    headers = {"Retry-After": retry_after} if retry_after is not None else None
    response = httpx2.Response(status, headers=headers, request=request)
    cls = ServiceUnavailableError if status >= 500 else NotFoundError  # noqa: PLR2004
    return cls(response)


def _notes(exc: BaseException) -> list[str]:
    return list(getattr(exc, "__notes__", []))


# ---- retryable failures return a sleep delay


def test_retryable_status_returns_delay_within_bounds() -> None:
    request = _request("PUT")
    exc = _status_exc(503, request)
    delay = _policy().decide(attempt=0, request=request, exc=exc)
    assert 0.0 <= delay <= _BASE_DELAY  # full-jitter ceiling at attempt 0 is base_delay


def test_retryable_network_returns_delay_within_bounds() -> None:
    request = _request("PUT")
    delay = _policy().decide(attempt=0, request=request, exc=NetworkError("boom"))
    assert 0.0 <= delay <= _BASE_DELAY


def test_retryable_timeout_returns_delay_within_bounds() -> None:
    request = _request("PUT")
    delay = _policy().decide(attempt=0, request=request, exc=TimeoutError("slow"))
    assert 0.0 <= delay <= _BASE_DELAY


# ---- classification re-raises the original, untouched


def test_non_retryable_status_reraises_unwrapped() -> None:
    request = _request("PUT")
    exc = _status_exc(404, request)
    with pytest.raises(NotFoundError) as ei:
        _policy().decide(attempt=0, request=request, exc=exc)
    assert ei.value is exc
    assert _notes(ei.value) == []


def test_non_eligible_method_reraises_unwrapped() -> None:
    request = _request("POST")
    exc = _status_exc(503, request)
    with pytest.raises(ServiceUnavailableError) as ei:
        _policy().decide(attempt=0, request=request, exc=exc)
    assert ei.value is exc
    assert _notes(ei.value) == []


# ---- terminal raises carry the right note


def test_streaming_body_refused_with_note() -> None:
    request = _request("PUT", streaming=True)
    exc = _status_exc(503, request)
    with pytest.raises(ServiceUnavailableError) as ei:
        _policy().decide(attempt=0, request=request, exc=exc)
    assert any("stream that cannot replay" in note for note in _notes(ei.value))


def test_exhaustion_adds_gave_up_note() -> None:
    request = _request("PUT")
    exc = _status_exc(503, request)
    with pytest.raises(ServiceUnavailableError) as ei:
        _policy(max_attempts=3).decide(attempt=2, request=request, exc=exc)
    assert any("gave up after 3 attempts" in note for note in _notes(ei.value))


def test_retry_after_exceeding_max_delay_gives_up() -> None:
    request = _request("PUT")
    exc = _status_exc(503, request, retry_after="10")  # > max_delay (5.0)
    with pytest.raises(ServiceUnavailableError) as ei:
        _policy().decide(attempt=0, request=request, exc=exc)
    assert any("exceeded max_delay" in note for note in _notes(ei.value))


# ---- Retry-After handling


def test_retry_after_within_max_delay_returned_exactly() -> None:
    request = _request("PUT")
    exc = _status_exc(503, request, retry_after="2")  # <= max_delay
    delay = _policy().decide(attempt=0, request=request, exc=exc)
    assert delay == 2.0


def test_respect_retry_after_false_ignores_header() -> None:
    request = _request("PUT")
    exc = _status_exc(503, request, retry_after="2")
    delay = _policy(respect_retry_after=False).decide(attempt=0, request=request, exc=exc)
    assert delay <= _BASE_DELAY  # jitter, not the 2.0 header value


# ---- budget refusal


def test_budget_refusal_raises_with_cause_and_fields() -> None:
    request = _request("PUT")
    exc = _status_exc(503, request)
    policy = _policy(max_attempts=3, budget=_zero_budget())
    with pytest.raises(RetryBudgetExhaustedError) as ei:
        policy.decide(attempt=0, request=request, exc=exc)
    assert ei.value.attempts == 1
    assert ei.value.last_response is exc.response
    assert ei.value.last_exception is exc
    assert ei.value.__cause__ is exc


# ---- construction-time validation moved onto the policy


def test_invalid_max_attempts_rejected() -> None:
    with pytest.raises(ValueError, match="max_attempts must be >= 1"):
        _policy(max_attempts=0)

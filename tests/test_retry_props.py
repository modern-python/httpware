"""Hypothesis property tests for AsyncRetry.

Properties verified:
1. Total attempts never exceed max_attempts.
2. Total sleep time never exceeds max_attempts * max_delay.
3. Non-retryable statuses (NOT in retry_status_codes) cause exactly one attempt.
4. Non-idempotent methods (NOT in retry_methods) cause exactly one attempt,
   regardless of response status.
"""

import math
from http import HTTPStatus

import httpx2
from hypothesis import given, settings
from hypothesis import strategies as st

from httpware import AsyncClient
from httpware.middleware.resilience.budget import RetryBudget
from httpware.middleware.resilience.retry import (
    DEFAULT_IDEMPOTENT_METHODS,
    DEFAULT_RETRY_STATUS_CODES,
    AsyncRetry,
)


class _SleepRecorder:
    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, delay: float) -> None:
        self.calls.append(delay)


def _always_status(status: int) -> httpx2.MockTransport:
    return httpx2.MockTransport(lambda req: httpx2.Response(status, request=req))


_RETRYABLE_STATUS_STRATEGY = st.sampled_from(sorted(DEFAULT_RETRY_STATUS_CODES))
_NON_RETRYABLE_STATUS_STRATEGY = st.sampled_from(
    [
        HTTPStatus.BAD_REQUEST,
        HTTPStatus.UNAUTHORIZED,
        HTTPStatus.NOT_FOUND,
        HTTPStatus.CONFLICT,
    ]
)
_IDEMPOTENT_METHODS = st.sampled_from(sorted(DEFAULT_IDEMPOTENT_METHODS))
_NON_IDEMPOTENT_METHODS = st.sampled_from(["POST", "PATCH"])


@given(
    max_attempts=st.integers(min_value=1, max_value=5),
    status=_RETRYABLE_STATUS_STRATEGY,
    method=_IDEMPOTENT_METHODS,
)
@settings(max_examples=50, deadline=None)
async def test_total_attempts_never_exceeds_max_attempts(
    max_attempts: int,
    status: int,
    method: str,
) -> None:
    sleeper = _SleepRecorder()
    call_count = {"n": 0}

    def handler(request: httpx2.Request) -> httpx2.Response:
        call_count["n"] += 1
        return httpx2.Response(status, request=request)

    transport = httpx2.MockTransport(handler)
    client = AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=transport),
        middleware=[
            AsyncRetry(
                _sleep=sleeper,
                max_attempts=max_attempts,
                base_delay=0.001,
                max_delay=0.002,
                budget=RetryBudget(ttl=60.0, min_retries_per_sec=1000.0),
            )
        ],
    )
    try:  # noqa: SIM105 — contextlib.suppress can't be used in async Hypothesis tests
        await client.request(method, "https://example.test/x")
    except Exception:  # noqa: BLE001, S110 — we only care about call count
        pass
    assert call_count["n"] <= max_attempts


@given(
    max_attempts=st.integers(min_value=1, max_value=5),
    base_delay=st.floats(min_value=0.001, max_value=0.01),
    max_delay=st.floats(min_value=0.001, max_value=0.05),
)
@settings(max_examples=30, deadline=None)
async def test_total_sleep_never_exceeds_max_attempts_times_max_delay(
    max_attempts: int,
    base_delay: float,
    max_delay: float,
) -> None:
    sleeper = _SleepRecorder()
    transport = _always_status(HTTPStatus.SERVICE_UNAVAILABLE)
    client = AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=transport),
        middleware=[
            AsyncRetry(
                _sleep=sleeper,
                max_attempts=max_attempts,
                base_delay=base_delay,
                max_delay=max_delay,
                budget=RetryBudget(ttl=60.0, min_retries_per_sec=1000.0),
            )
        ],
    )
    try:  # noqa: SIM105 — contextlib.suppress can't be used in async Hypothesis tests
        await client.get("https://example.test/x")
    except Exception:  # noqa: BLE001, S110
        pass
    total = sum(sleeper.calls)
    assert total <= max_attempts * max_delay + 1e-9


@given(
    status=_NON_RETRYABLE_STATUS_STRATEGY,
    method=_IDEMPOTENT_METHODS,
)
@settings(max_examples=30, deadline=None)
async def test_non_retryable_status_causes_one_attempt(status: int, method: str) -> None:
    sleeper = _SleepRecorder()
    call_count = {"n": 0}

    def handler(request: httpx2.Request) -> httpx2.Response:
        call_count["n"] += 1
        return httpx2.Response(status, request=request)

    transport = httpx2.MockTransport(handler)
    client = AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=transport),
        middleware=[AsyncRetry(_sleep=sleeper, max_attempts=3, base_delay=0.001, max_delay=0.002)],
    )
    try:  # noqa: SIM105 — contextlib.suppress can't be used in async Hypothesis tests
        await client.request(method, "https://example.test/x")
    except Exception:  # noqa: BLE001, S110
        pass
    assert call_count["n"] == 1
    assert sleeper.calls == []


@given(
    status=_RETRYABLE_STATUS_STRATEGY,
    method=_NON_IDEMPOTENT_METHODS,
)
@settings(max_examples=30, deadline=None)
async def test_non_idempotent_method_causes_one_attempt(status: int, method: str) -> None:
    sleeper = _SleepRecorder()
    call_count = {"n": 0}

    def handler(request: httpx2.Request) -> httpx2.Response:
        call_count["n"] += 1
        return httpx2.Response(status, request=request)

    transport = httpx2.MockTransport(handler)
    client = AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=transport),
        middleware=[AsyncRetry(_sleep=sleeper, max_attempts=3, base_delay=0.001, max_delay=0.002)],
    )
    try:  # noqa: SIM105 — contextlib.suppress can't be used in async Hypothesis tests
        await client.request(method, "https://example.test/x")
    except Exception:  # noqa: BLE001, S110
        pass
    assert call_count["n"] == 1
    assert sleeper.calls == []


@given(
    deposits=st.integers(min_value=1, max_value=20),
    percent=st.floats(
        min_value=0.0,
        max_value=0.5,
        allow_nan=False,
        allow_infinity=False,
    ),
)
@settings(max_examples=50, deadline=None)
def test_budget_exhaustion_is_reachable_and_deterministic(
    deposits: int,
    percent: float,
) -> None:
    """When floor=0 and a finite percent is set, the budget MUST refuse withdrawals after exactly ceiling permits."""
    budget = RetryBudget(ttl=60.0, min_retries_per_sec=0.0, percent_can_retry=percent)
    for _ in range(deposits):
        budget.deposit()
    expected_ceiling = math.ceil(deposits * percent)
    for permit in range(expected_ceiling):
        assert budget.try_withdraw(), f"budget refused early at permit {permit}/{expected_ceiling}"
    # The (ceiling + 1)-th withdrawal MUST fail.
    assert not budget.try_withdraw()

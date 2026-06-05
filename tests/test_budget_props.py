"""Hypothesis property tests for RetryBudget.

Properties verified:
1. `try_withdraw()` never permits more than `floor + int(deposits * percent)` over any window.
2. After advancing the clock past `ttl`, all prior deposits expire (no retries permitted
   beyond the floor).
3. `deposit()` is monotonically non-decreasing in permitted retries (more deposits cannot
   reduce the budget).
"""

from collections.abc import Callable

from hypothesis import given, settings
from hypothesis import strategies as st

from httpware.middleware.resilience.budget import RetryBudget


class _Clock:
    def __init__(self) -> None:
        self._t = 0.0

    def now(self) -> float:
        return self._t

    def advance(self, seconds: float) -> None:
        self._t += seconds


def _budget(
    *,
    ttl: float,
    min_retries_per_sec: float,
    percent_can_retry: float,
    now: Callable[[], float],
) -> RetryBudget:
    return RetryBudget(
        ttl=ttl,
        min_retries_per_sec=min_retries_per_sec,
        percent_can_retry=percent_can_retry,
        _now=now,
    )


@given(
    ttl=st.floats(min_value=0.1, max_value=60.0, allow_nan=False, allow_infinity=False),
    min_rps=st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False),
    percent=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    deposits=st.integers(min_value=0, max_value=10_000),
)
@settings(max_examples=200, deadline=None)
def test_try_withdraw_never_exceeds_theoretical_bound(
    ttl: float,
    min_rps: float,
    percent: float,
    deposits: int,
) -> None:
    clock = _Clock()
    budget = _budget(ttl=ttl, min_retries_per_sec=min_rps, percent_can_retry=percent, now=clock.now)
    for _ in range(deposits):
        budget.deposit()
    floor = int(min_rps * ttl)
    ceiling = int(deposits * percent) + floor
    permitted = 0
    # Try up to ceiling + 10 times to confirm the cap holds.
    for _ in range(ceiling + 10):
        if budget.try_withdraw():
            permitted += 1
    assert permitted <= ceiling


@given(
    ttl=st.floats(min_value=0.1, max_value=10.0, allow_nan=False, allow_infinity=False),
    deposits=st.integers(min_value=1, max_value=1000),
    percent=st.floats(min_value=0.01, max_value=1.0, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=100, deadline=None)
def test_advancing_past_ttl_purges_deposits(ttl: float, deposits: int, percent: float) -> None:
    clock = _Clock()
    budget = _budget(ttl=ttl, min_retries_per_sec=0.0, percent_can_retry=percent, now=clock.now)
    for _ in range(deposits):
        budget.deposit()
    clock.advance(ttl + 0.1)
    # After purge, no deposits remain; floor is 0 → no retries permitted.
    assert budget.try_withdraw() is False


@given(
    extra_deposits=st.integers(min_value=0, max_value=100),
)
@settings(max_examples=50, deadline=None)
def test_more_deposits_never_decreases_budget(extra_deposits: int) -> None:
    clock = _Clock()
    budget = _budget(ttl=10.0, min_retries_per_sec=1.0, percent_can_retry=0.5, now=clock.now)
    # Establish a baseline
    for _ in range(10):
        budget.deposit()
    initial_permitted = sum(1 for _ in range(100) if budget.try_withdraw())
    # Reset by creating a fresh budget with the same starting deposits + extra
    budget2 = _budget(ttl=10.0, min_retries_per_sec=1.0, percent_can_retry=0.5, now=clock.now)
    for _ in range(10 + extra_deposits):
        budget2.deposit()
    new_permitted = sum(1 for _ in range(100 + extra_deposits) if budget2.try_withdraw())
    assert new_permitted >= initial_permitted

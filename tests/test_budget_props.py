"""Hypothesis property tests for RetryBudget.

Properties verified:
1. `try_withdraw()` never permits more than `floor + int(deposits * percent)` over any window.
2. After advancing the clock past `ttl`, all prior deposits expire (no retries permitted
   beyond the floor).
3. `deposit()` is monotonically non-decreasing in permitted retries (more deposits cannot
   reduce the budget).
4. Against a reference that keeps every timestamp, each `try_withdraw()` answer is one the
   reference allows when events stop counting anywhere between 0.9 * ttl and ttl after
   they were recorded.
"""

import math
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
    expected_ceiling = math.ceil(deposits * percent) + floor
    permitted = 0
    # Try up to expected_ceiling + 10 times to confirm the cap holds exactly.
    for _ in range(expected_ceiling + 10):
        if budget.try_withdraw():
            permitted += 1
    assert permitted == expected_ceiling


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
    # ttl * 2.0 is self-evidently past the TTL window for any positive ttl, and stays
    # safe across the full strategy range without depending on a hard-coded epsilon.
    clock.advance(ttl * 2.0)
    # After purge, no deposits remain; floor is 0 → no retries permitted.
    assert budget.try_withdraw() is False


@given(
    ttl=st.floats(min_value=0.1, max_value=60.0, allow_nan=False, allow_infinity=False),
    min_rps=st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False),
    percent=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    base_deposits=st.integers(min_value=0, max_value=100),
    extra_deposits=st.integers(min_value=0, max_value=100),
)
@settings(max_examples=50, deadline=None)
def test_more_deposits_never_decreases_budget(
    ttl: float,
    min_rps: float,
    percent: float,
    base_deposits: int,
    extra_deposits: int,
) -> None:
    clock = _Clock()
    budget = _budget(ttl=ttl, min_retries_per_sec=min_rps, percent_can_retry=percent, now=clock.now)
    for _ in range(base_deposits):
        budget.deposit()
    initial_permitted = sum(1 for _ in range(base_deposits + 200) if budget.try_withdraw())
    # Fresh budget with the same starting deposits + extra
    budget2 = _budget(ttl=ttl, min_retries_per_sec=min_rps, percent_can_retry=percent, now=clock.now)
    for _ in range(base_deposits + extra_deposits):
        budget2.deposit()
    new_permitted = sum(1 for _ in range(base_deposits + extra_deposits + 200) if budget2.try_withdraw())
    assert new_permitted >= initial_permitted


_EDGE = 1e-9


def _live(timestamps: list[float], now: float, max_age: float) -> int:
    return sum(1 for t in timestamps if now - t <= max_age)


def _ceiling(deposits: int, percent: float, floor: int) -> int:
    return math.ceil(deposits * percent) + floor


@given(
    ttl=st.floats(min_value=0.1, max_value=60.0, allow_nan=False, allow_infinity=False),
    min_rps=st.floats(min_value=0.0, max_value=5.0, allow_nan=False, allow_infinity=False),
    percent=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    start=st.floats(min_value=0.0, max_value=1e6, allow_nan=False, allow_infinity=False),
    ops=st.lists(
        st.tuples(st.booleans(), st.floats(min_value=0.0, max_value=0.5, allow_nan=False, allow_infinity=False)),
        max_size=300,
    ),
)
@settings(max_examples=200, deadline=None)
def test_matches_timestamp_reference_within_one_bucket(
    ttl: float,
    min_rps: float,
    percent: float,
    start: float,
    ops: list[tuple[bool, float]],
) -> None:
    clock = _Clock()
    clock.advance(start)
    budget = _budget(ttl=ttl, min_retries_per_sec=min_rps, percent_can_retry=percent, now=clock.now)
    floor = int(min_rps * ttl)
    shortest = 0.9 * ttl * (1 - _EDGE)
    longest = ttl * (1 + _EDGE)
    deposits: list[float] = []
    withdrawn: list[float] = []
    for is_deposit, step in ops:
        clock.advance(step * ttl)
        now = clock.now()
        if is_deposit:
            budget.deposit()
            deposits.append(now)
            continue
        permitted = budget.try_withdraw()
        must_permit = _live(withdrawn, now, longest) < _ceiling(_live(deposits, now, shortest), percent, floor)
        must_refuse = _live(withdrawn, now, shortest) >= _ceiling(_live(deposits, now, longest), percent, floor)
        if must_permit:
            assert permitted
        if must_refuse:
            assert not permitted
        if permitted:
            withdrawn.append(now)

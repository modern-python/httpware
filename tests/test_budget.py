"""Unit tests for RetryBudget token-bucket math.

Tests inject a deterministic `_now` callable rather than monkeypatching `time.monotonic`,
so they cannot be perturbed by other tests sharing the same module.
"""

import math
import time

import pytest

from httpware.middleware.resilience.budget import RetryBudget


class _Clock:
    """Mutable clock for deterministic tests. Pass `clock.now` as `_now`."""

    def __init__(self, start: float = 0.0) -> None:
        self._t = start

    def now(self) -> float:
        return self._t

    def advance(self, seconds: float) -> None:
        self._t += seconds


def test_defaults_match_spec() -> None:
    budget = RetryBudget()
    assert budget._ttl == 10.0  # noqa: SLF001, PLR2004
    assert budget._min_retries_per_sec == 10.0  # noqa: SLF001, PLR2004
    assert budget._percent_can_retry == 0.2  # noqa: SLF001, PLR2004


def test_floor_permits_min_retries_per_sec_times_ttl_with_zero_deposits() -> None:
    # floor = min_retries_per_sec * ttl = 10 * 10 = 100 permitted withdrawals
    clock = _Clock()
    budget = RetryBudget(ttl=10.0, min_retries_per_sec=10.0, percent_can_retry=0.0, _now=clock.now)
    permitted = sum(1 for _ in range(101) if budget.try_withdraw())
    assert permitted == 100  # noqa: PLR2004


def test_percent_can_retry_ceiling_with_deposits() -> None:
    # 1000 deposits * 0.2 = 200 retries permitted (plus floor 100 = 300 total)
    clock = _Clock()
    budget = RetryBudget(ttl=10.0, min_retries_per_sec=10.0, percent_can_retry=0.2, _now=clock.now)
    for _ in range(1000):
        budget.deposit()
    permitted = sum(1 for _ in range(500) if budget.try_withdraw())
    assert permitted == 300  # noqa: PLR2004


def test_ttl_expiry_purges_old_deposits() -> None:
    clock = _Clock()
    budget = RetryBudget(ttl=1.0, min_retries_per_sec=0.0, percent_can_retry=0.5, _now=clock.now)
    for _ in range(10):
        budget.deposit()
    # 10 deposits * 0.5 = 5 retries available immediately
    assert budget.try_withdraw() is True
    # Advance past TTL; deposits expire
    clock.advance(2.0)
    # With min_retries_per_sec=0 and no live deposits, no retries permitted
    assert budget.try_withdraw() is False


def test_try_withdraw_returns_false_when_exhausted() -> None:
    clock = _Clock()
    budget = RetryBudget(ttl=10.0, min_retries_per_sec=1.0, percent_can_retry=0.0, _now=clock.now)
    # floor = 1 * 10 = 10 retries
    for _ in range(10):
        assert budget.try_withdraw() is True
    assert budget.try_withdraw() is False


def test_deposit_after_exhaustion_unblocks_at_ceil_boundary() -> None:
    """With math.ceil, 1 deposit at 20% yields ceil(0.2)=1, raising the ceiling by 1."""
    clock = _Clock()
    budget = RetryBudget(ttl=10.0, min_retries_per_sec=1.0, percent_can_retry=0.2, _now=clock.now)
    # exhaust the floor (10)
    for _ in range(10):
        budget.try_withdraw()
    assert budget.try_withdraw() is False
    # one deposit: ceil(1 * 0.2) = ceil(0.2) = 1 → ceiling becomes 11, one new retry permitted
    budget.deposit()
    assert budget.try_withdraw() is True
    assert budget.try_withdraw() is False
    # 4 more deposits (5 total): ceil(5 * 0.2) = ceil(1.0) = 1 → same ceiling, no additional retries
    for _ in range(4):
        budget.deposit()
    assert budget.try_withdraw() is False
    # 1 more deposit (6 total): ceil(6 * 0.2) = ceil(1.2) = 2 → ceiling becomes 12, one more retry
    budget.deposit()
    assert budget.try_withdraw() is True
    assert budget.try_withdraw() is False


def test_withdrawn_also_expires_after_ttl() -> None:
    """After TTL passes, prior withdrawals no longer count against the budget."""
    clock = _Clock()
    budget = RetryBudget(ttl=1.0, min_retries_per_sec=10.0, percent_can_retry=0.0, _now=clock.now)
    for _ in range(10):
        budget.try_withdraw()
    assert budget.try_withdraw() is False
    clock.advance(2.0)
    assert budget.try_withdraw() is True


def test_default_now_is_time_monotonic() -> None:
    """When _now is not passed, the budget uses time.monotonic by default."""
    budget = RetryBudget()
    assert budget._now is time.monotonic  # noqa: SLF001


@pytest.mark.parametrize("ttl", [0.0, -1.0, math.nan, math.inf])
def test_invalid_ttl_rejected(ttl: float) -> None:
    with pytest.raises(ValueError, match="ttl must be a finite number > 0"):
        RetryBudget(ttl=ttl)


@pytest.mark.parametrize("min_retries_per_sec", [-1.0, math.nan, math.inf])
def test_invalid_min_retries_per_sec_rejected(min_retries_per_sec: float) -> None:
    with pytest.raises(ValueError, match="min_retries_per_sec must be a finite number >= 0"):
        RetryBudget(min_retries_per_sec=min_retries_per_sec)


@pytest.mark.parametrize("percent_can_retry", [-0.1, math.nan, math.inf])
def test_invalid_percent_can_retry_rejected(percent_can_retry: float) -> None:
    with pytest.raises(ValueError, match="percent_can_retry must be a finite number >= 0"):
        RetryBudget(percent_can_retry=percent_can_retry)


def test_boundary_budget_values_accepted() -> None:
    clock = _Clock()
    budget = RetryBudget(ttl=0.001, min_retries_per_sec=0.0, percent_can_retry=2.0, _now=clock.now)
    budget.deposit()
    assert budget.try_withdraw() is True
    assert budget.try_withdraw() is True
    assert budget.try_withdraw() is False


def test_deposit_counts_until_its_bucket_leaves_the_window() -> None:
    # ttl=10 gives 1 s buckets; a deposit at 0.5 lives in bucket [0, 1) and stops counting at 10.0
    clock = _Clock(0.5)
    budget = RetryBudget(ttl=10.0, min_retries_per_sec=0.0, percent_can_retry=1.0, _now=clock.now)
    budget.deposit()
    clock.advance(9.49)
    assert budget.try_withdraw() is True
    clock.advance(0.01)
    assert budget.try_withdraw() is False


def test_expired_buckets_release_only_their_own_counts() -> None:
    clock = _Clock()
    budget = RetryBudget(ttl=10.0, min_retries_per_sec=0.0, percent_can_retry=1.0, _now=clock.now)
    budget.deposit()
    clock.advance(5.0)
    budget.deposit()
    budget.deposit()
    clock.advance(5.0)
    # the first deposit has expired, the two later ones still count
    assert budget.try_withdraw() is True
    assert budget.try_withdraw() is True
    assert budget.try_withdraw() is False


def test_withdrawal_expires_with_its_bucket() -> None:
    clock = _Clock()
    budget = RetryBudget(ttl=10.0, min_retries_per_sec=0.1, percent_can_retry=0.0, _now=clock.now)
    assert budget.try_withdraw() is True
    clock.advance(9.0)
    assert budget.try_withdraw() is False
    clock.advance(1.0)
    assert budget.try_withdraw() is True


def test_earlier_timestamp_counts_in_the_current_bucket() -> None:
    times = iter([5.0, 4.0, 14.5])
    budget = RetryBudget(ttl=10.0, min_retries_per_sec=0.0, percent_can_retry=1.0, _now=lambda: next(times))
    budget.deposit()
    budget.deposit()
    # both deposits sit in the bucket for [5, 6), which is still live at 14.5
    assert budget._deposits == 2  # noqa: SLF001, PLR2004
    assert budget.try_withdraw() is True

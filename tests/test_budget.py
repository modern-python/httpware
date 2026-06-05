"""Unit tests for RetryBudget token-bucket math.

Tests inject a deterministic `_now` callable rather than monkeypatching `time.monotonic`,
so they cannot be perturbed by other tests sharing the same module.
"""

import time

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


def test_deposit_after_exhaustion_does_not_immediately_unblock() -> None:
    """A single deposit at 20% percent_can_retry contributes 0.2 → int() truncates to 0 → no new retries."""
    clock = _Clock()
    budget = RetryBudget(ttl=10.0, min_retries_per_sec=1.0, percent_can_retry=0.2, _now=clock.now)
    # exhaust the floor (10)
    for _ in range(10):
        budget.try_withdraw()
    assert budget.try_withdraw() is False
    # one deposit: 1 * 0.2 = 0.2 → int() → 0
    budget.deposit()
    assert budget.try_withdraw() is False
    # 5 more deposits: 6 * 0.2 = 1.2 → int() → 1 new retry permitted
    for _ in range(5):
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

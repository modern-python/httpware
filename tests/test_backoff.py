"""Unit tests for the full-jitter backoff helper.

Integration coverage comes from ``tests/test_retry.py`` (Retry middleware drives
``full_jitter_delay`` per attempt). The pure-function tests here pin the bound
and the cap independently of the middleware orchestration.
"""

from httpware.middleware.resilience._backoff import full_jitter_delay


BASE_DELAY = 0.1
MAX_DELAY = 5.0


def test_full_jitter_delay_bounded_by_min_of_max_and_exponential() -> None:
    # attempt_index=0, base=0.1 → ceiling = min(5.0, 0.1*1) = 0.1
    delay = full_jitter_delay(0, base_delay=BASE_DELAY, max_delay=MAX_DELAY)
    assert 0.0 <= delay <= BASE_DELAY


def test_full_jitter_delay_capped_at_max_delay() -> None:
    # attempt_index=10, base=0.1 → exp = 102.4 → capped to 5.0
    delay = full_jitter_delay(10, base_delay=BASE_DELAY, max_delay=MAX_DELAY)
    assert 0.0 <= delay <= MAX_DELAY


def test_full_jitter_delay_uses_injected_random() -> None:
    # Inject a deterministic mock that returns the upper bound
    delay = full_jitter_delay(
        0,
        base_delay=BASE_DELAY,
        max_delay=MAX_DELAY,
        _random_uniform=lambda _lo, hi: hi,
    )
    assert delay == BASE_DELAY

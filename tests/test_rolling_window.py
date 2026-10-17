"""Unit tests for the time-bucketed _RollingWindow used by rate-mode CircuitBreaker."""

from hypothesis import given, settings
from hypothesis import strategies as st

from httpware.middleware.resilience.circuit_breaker import _BUCKET_COUNT, _RollingWindow


def test_counts_within_window() -> None:
    w = _RollingWindow(window_seconds=10.0)
    w.record(0.0, failed=True)
    w.record(1.0, failed=True)
    w.record(2.0, failed=False)
    total, failures = w.totals(2.0)
    assert (total, failures) == (3, 2)


def test_empty_window_is_zero() -> None:
    w = _RollingWindow(window_seconds=10.0)
    assert w.totals(0.0) == (0, 0)


def test_stale_buckets_evicted_by_time() -> None:
    w = _RollingWindow(window_seconds=10.0)
    w.record(0.0, failed=True)
    w.record(0.5, failed=True)
    # advance a full window past those records
    w.record(11.0, failed=False)
    total, failures = w.totals(11.0)
    assert (total, failures) == (1, 0)


def test_totals_excludes_stale_without_new_write() -> None:
    w = _RollingWindow(window_seconds=10.0)
    w.record(0.0, failed=True)
    # no write after the window elapses — totals() alone must drop the stale bucket
    assert w.totals(20.0) == (0, 0)


def test_clear_resets_everything() -> None:
    w = _RollingWindow(window_seconds=10.0)
    w.record(0.0, failed=True)
    w.record(1.0, failed=False)
    w.clear()
    assert w.totals(1.0) == (0, 0)


@given(
    events=st.lists(
        st.tuples(st.floats(min_value=0.0, max_value=1000.0), st.booleans()),
        min_size=1,
        max_size=200,
    ),
)
@settings(max_examples=100, deadline=None)
def test_totals_match_live_events(events: list[tuple[float, bool]]) -> None:
    """totals() at the final time asserts the live-window totals exactly."""
    window_seconds = 10.0
    w = _RollingWindow(window_seconds=window_seconds)
    ordered = sorted(events, key=lambda e: e[0])
    for now, failed in ordered:
        w.record(now, failed=failed)
    final = ordered[-1][0]
    bucket_width = window_seconds / _BUCKET_COUNT
    live_cutoff_slot = int(final // bucket_width) - _BUCKET_COUNT + 1
    expected_live = [(t, f) for (t, f) in ordered if int(t // bucket_width) >= live_cutoff_slot]
    total, failures = w.totals(final)
    assert total == len(expected_live)
    assert failures == sum(1 for _, f in expected_live if f)
    assert 0 <= failures <= total


def test_partial_advance_evicts_only_expired_buckets() -> None:
    w = _RollingWindow(window_seconds=10.0)
    w.record(0.0, failed=True)
    w.record(4.0, failed=False)
    w.record(5.0, failed=True)
    assert w.totals(10.0) == (2, 1)
    assert w.totals(14.0) == (1, 1)
    assert w.totals(15.0) == (0, 0)


def test_earlier_timestamp_counts_in_the_current_bucket() -> None:
    w = _RollingWindow(window_seconds=10.0)
    w.record(5.0, failed=False)
    w.record(4.0, failed=True)
    assert w.totals(14.5) == (2, 1)
    assert w.totals(15.0) == (0, 0)


_EDGE = 1e-9


@given(
    window_seconds=st.floats(min_value=0.1, max_value=120.0, allow_nan=False, allow_infinity=False),
    start=st.floats(min_value=0.0, max_value=1e6, allow_nan=False, allow_infinity=False),
    steps=st.lists(
        st.tuples(st.floats(min_value=0.0, max_value=0.5, allow_nan=False, allow_infinity=False), st.booleans()),
        min_size=1,
        max_size=300,
    ),
)
@settings(max_examples=200, deadline=None)
def test_totals_within_one_bucket_of_timestamp_reference(
    window_seconds: float,
    start: float,
    steps: list[tuple[float, bool]],
) -> None:
    """An outcome counts until somewhere between 0.9 and 1.0 window lengths after it was recorded."""
    w = _RollingWindow(window_seconds=window_seconds)
    shortest = 0.9 * window_seconds * (1 - _EDGE)
    longest = window_seconds * (1 + _EDGE)
    now = start
    events: list[tuple[float, bool]] = []
    for step, failed in steps:
        now += step * window_seconds
        w.record(now, failed=failed)
        events.append((now, failed))
        total, failures = w.totals(now)
        assert sum(1 for t, _ in events if now - t <= shortest) <= total
        assert total <= sum(1 for t, _ in events if now - t <= longest)
        assert sum(1 for t, f in events if f and now - t <= shortest) <= failures
        assert failures <= sum(1 for t, f in events if f and now - t <= longest)

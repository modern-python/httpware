"""Finagle-style token-bucket retry budget.

Thread-safe and asyncio-safe: all mutations go through a threading.Lock held for a
constant-time update of per-bucket counters, so a sync thread holding it delays an
event loop sharing the budget only briefly. Safe to share across threads, across
coroutines on one event loop, and across (sync Client, AsyncClient) pairs in the same
process.
"""

import math
import threading
import time
from collections.abc import Callable


_BUCKET_COUNT = 10

_TTL_INVALID = "ttl must be a finite number > 0"
_MIN_RETRIES_PER_SEC_INVALID = "min_retries_per_sec must be a finite number >= 0"
_PERCENT_CAN_RETRY_INVALID = "percent_can_retry must be a finite number >= 0"


def _validate_budget_config(*, ttl: float, min_retries_per_sec: float, percent_can_retry: float) -> None:
    if not (ttl > 0 and math.isfinite(ttl)):
        raise ValueError(_TTL_INVALID)
    if not (min_retries_per_sec >= 0 and math.isfinite(min_retries_per_sec)):
        raise ValueError(_MIN_RETRIES_PER_SEC_INVALID)
    if not (percent_can_retry >= 0 and math.isfinite(percent_can_retry)):
        raise ValueError(_PERCENT_CAN_RETRY_INVALID)


class RetryBudget:
    """Token-bucket budget bounding retry rate to prevent retry storms.

    Each request deposits a token; each retry attempts to withdraw one.
    Available retries are bounded by `percent_can_retry` of recent deposits,
    plus a `min_retries_per_sec * ttl` floor. Deposits and withdrawals are counted in
    ten buckets of `ttl / 10` each, so one stops counting between 0.9 * ttl and ttl
    after it was recorded.
    """

    def __init__(
        self,
        *,
        ttl: float = 10.0,
        min_retries_per_sec: float = 10.0,
        percent_can_retry: float = 0.2,
        _now: Callable[[], float] = time.monotonic,
    ) -> None:
        _validate_budget_config(ttl=ttl, min_retries_per_sec=min_retries_per_sec, percent_can_retry=percent_can_retry)
        self._ttl = ttl
        self._min_retries_per_sec = min_retries_per_sec
        self._percent_can_retry = percent_can_retry
        self._now = _now
        self._lock = threading.Lock()
        self._bucket_width = ttl / _BUCKET_COUNT
        self._floor = int(min_retries_per_sec * ttl)
        self._slot: float = -math.inf
        self._index = 0
        self._bucket_deposits = [0] * _BUCKET_COUNT
        self._bucket_withdrawn = [0] * _BUCKET_COUNT
        self._deposits = 0
        self._withdrawn = 0

    def _rotate(self, slot: float) -> None:
        """Make `slot` the current bucket, dropping buckets that fell out of the window. The caller holds self._lock."""
        current = int(slot)
        if current - self._slot >= _BUCKET_COUNT:
            self._bucket_deposits = [0] * _BUCKET_COUNT
            self._bucket_withdrawn = [0] * _BUCKET_COUNT
            self._deposits = 0
            self._withdrawn = 0
        else:
            for stale in range(int(self._slot) + 1, current + 1):
                index = stale % _BUCKET_COUNT
                self._deposits -= self._bucket_deposits[index]
                self._withdrawn -= self._bucket_withdrawn[index]
                self._bucket_deposits[index] = 0
                self._bucket_withdrawn[index] = 0
        self._slot = current
        self._index = current % _BUCKET_COUNT

    def deposit(self) -> None:
        """Record a request (success or failure attempt). Adds one token."""
        slot = self._now() // self._bucket_width
        with self._lock:
            if slot > self._slot:
                self._rotate(slot)
            self._bucket_deposits[self._index] += 1
            self._deposits += 1

    def try_withdraw(self) -> bool:
        """Atomically attempt to spend one retry token.

        Returns True if a retry is permitted, False if the budget is exhausted.
        Never blocks.
        """
        slot = self._now() // self._bucket_width
        with self._lock:
            if slot > self._slot:
                self._rotate(slot)
            if self._withdrawn >= math.ceil(self._deposits * self._percent_can_retry) + self._floor:
                return False
            self._bucket_withdrawn[self._index] += 1
            self._withdrawn += 1
            return True

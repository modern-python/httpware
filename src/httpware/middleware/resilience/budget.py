"""Finagle-style token-bucket retry budget.

Thread-safe and asyncio-safe: all mutations go through a threading.Lock,
which ensures no torn state across concurrent accesses. When a RetryBudget
is shared between a sync Client (pool thread) and an AsyncClient (event-loop
thread), a sync thread holding the lock can briefly block the loop thread's
acquisition; the critical section (purge + append/compare) is intentionally
tiny to bound this latency. Safe to share across threads, across coroutines
on one event loop, and across (sync Client, AsyncClient) pairs in the same
process.
"""

import math
import threading
import time
from collections import deque
from collections.abc import Callable


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
    plus a `min_retries_per_sec * ttl` floor.
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
        self._deposits: deque[float] = deque()
        self._withdrawn: deque[float] = deque()

    def _purge(self, now: float) -> None:
        # Caller must hold self._lock.
        # Strict `< cutoff` keeps entries at exactly `now - ttl`: window is [now - ttl, now].
        cutoff = now - self._ttl
        while self._deposits and self._deposits[0] < cutoff:
            self._deposits.popleft()
        while self._withdrawn and self._withdrawn[0] < cutoff:
            self._withdrawn.popleft()

    def deposit(self) -> None:
        """Record a request (success or failure attempt). Adds one token."""
        now = self._now()
        with self._lock:
            self._purge(now)
            self._deposits.append(now)

    def try_withdraw(self) -> bool:
        """Atomically attempt to spend one retry token.

        Returns True if a retry is permitted, False if the budget is exhausted.
        Never blocks.
        """
        now = self._now()
        with self._lock:
            self._purge(now)
            floor = int(self._min_retries_per_sec * self._ttl)
            ceiling = math.ceil(len(self._deposits) * self._percent_can_retry) + floor
            if len(self._withdrawn) >= ceiling:
                return False
            self._withdrawn.append(now)
            return True

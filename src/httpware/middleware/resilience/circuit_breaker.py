"""CircuitBreaker + AsyncCircuitBreaker — consecutive-failure and failure-rate circuit breakers.

A counted failure is a NetworkError, an httpware TimeoutError, or a StatusError whose
status_code is in the effective failure set (default: all 5xx). 4xx — including 429 —
count as successes: 429 means healthy-but-throttling, and tripping on it amplifies
incidents. Any other exception propagates without affecting circuit state. In
particular, non-NetworkError transport problems — e.g. httpx2.InvalidURL from a
malformed URL — are foreign: they propagate unchanged and do not increment the
failure counter, so programming errors cannot trip the breaker.

State machine (classic / consecutive-failure):
    CLOSED    — forward; count consecutive counted-failures; open at failure_threshold.
    OPEN      — fast-fail with CircuitOpenError; after reset_timeout the next request
                becomes the half-open probe.
    HALF_OPEN — admit exactly one probe at a time; success_threshold consecutive probe
                successes close the circuit; one probe failure re-opens it.

Trip modes:
    Classic (default) — opens when consecutive counted-failures reach failure_threshold.
        Set failure_threshold to use this mode; leave failure_rate_threshold unset.
    Rate (opt-in) — opens when the failure rate over a rolling window_seconds window
        meets or exceeds failure_rate_threshold, provided at least minimum_calls
        outcomes have been observed in that window. Set failure_rate_threshold to
        activate; failure_threshold is ignored in this mode.
    Half-open recovery and event names are identical across both modes.

The lock-free _CircuitBreakerState holds the transition logic, shared by both wrappers.
AsyncCircuitBreaker relies on asyncio atomicity (no await inside a transition) plus a
single-event-loop guard; CircuitBreaker (sync) serializes transitions with a
threading.Lock. Both are sharable across clients (one shared circuit); a sync instance
cannot be shared with an async one.
"""

import asyncio
import enum
import logging
import threading
import time
import typing
from collections.abc import Callable, Collection

import httpx2

from httpware._internal.observability import _emit_event
from httpware.errors import CircuitOpenError, NetworkError, StatusError, TimeoutError  # noqa: A004
from httpware.middleware import AsyncNext, Next
from httpware.middleware.resilience._event_loop_guard import check_event_loop


_FAILURE_THRESHOLD_INVALID = "failure_threshold must be >= 1"
_RESET_TIMEOUT_INVALID = "reset_timeout must be >= 0"
_SUCCESS_THRESHOLD_INVALID = "success_threshold must be >= 1"
_FAILURE_RATE_THRESHOLD_INVALID = "failure_rate_threshold must be in (0, 1]"
_WINDOW_SECONDS_INVALID = "window_seconds must be > 0"
_MINIMUM_CALLS_INVALID = "minimum_calls must be >= 1"
_CROSS_LOOP_MSG = (
    "AsyncCircuitBreaker is bound to a single event loop. First seen on {first!r}; "
    "current request is on {current!r}. Use one AsyncCircuitBreaker per loop; "
    "cross-thread sharing requires the sync CircuitBreaker primitive."
)

_DEFAULT_FAILURE_STATUS_CODES = frozenset(range(500, 600))

_BUCKET_COUNT = 10

_ROLE_CLOSED = "closed"
_ROLE_PROBE = "probe"

_LOGGER = logging.getLogger("httpware.circuit_breaker")


class CircuitState(enum.Enum):
    """Lifecycle state of a circuit breaker: CLOSED, OPEN, or HALF_OPEN."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class _RollingWindow:
    """Time-bucketed success/failure counters over a rolling window.

    `window_seconds` is split into `_BUCKET_COUNT` buckets. Each bucket holds
    [successes, failures] tagged with the integer time-slot it represents; a
    bucket whose slot is stale is reset on write, and `totals` filters to the
    live slot range so data older than the window never counts. Every method is
    synchronous and reads `now` from its caller (so the breaker's critical
    section owns the clock read).
    """

    def __init__(self, window_seconds: float) -> None:
        self._bucket_width = window_seconds / _BUCKET_COUNT
        self._slot = [-1] * _BUCKET_COUNT
        self._success = [0] * _BUCKET_COUNT
        self._failure = [0] * _BUCKET_COUNT

    def _current_slot(self, now: float) -> int:
        return int(now // self._bucket_width)

    def record(self, now: float, *, failed: bool) -> None:
        slot = self._current_slot(now)
        index = slot % _BUCKET_COUNT
        if self._slot[index] != slot:  # bucket reused for a new slot — evict
            self._slot[index] = slot
            self._success[index] = 0
            self._failure[index] = 0
        if failed:
            self._failure[index] += 1
        else:
            self._success[index] += 1

    def totals(self, now: float) -> tuple[int, int]:
        """Return (total, failures) across buckets still inside the window at `now`."""
        slot = self._current_slot(now)
        oldest = slot - _BUCKET_COUNT + 1
        total = 0
        failures = 0
        for i in range(_BUCKET_COUNT):
            if oldest <= self._slot[i] <= slot:
                total += self._success[i] + self._failure[i]
                failures += self._failure[i]
        return total, failures

    def clear(self) -> None:
        self._slot = [-1] * _BUCKET_COUNT
        self._success = [0] * _BUCKET_COUNT
        self._failure = [0] * _BUCKET_COUNT


class _CircuitBreakerState:
    """Lock-free circuit-breaker state machine shared by the sync + async wrappers.

    Every method is synchronous and performs no I/O beyond logging. The async wrapper
    calls these directly (atomic under a single event loop because no await occurs
    inside a transition); the sync wrapper wraps each call in a threading.Lock.
    """

    def __init__(  # noqa: PLR0913 — breaker state has many orthogonal knobs; a dataclass would be worse
        self,
        *,
        failure_threshold: int,
        reset_timeout: float,
        success_threshold: int,
        failure_status_codes: Collection[int] | None,
        failure_rate_threshold: float | None,
        window_seconds: float,
        minimum_calls: int,
        now: Callable[[], float],
    ) -> None:
        if failure_threshold < 1:
            raise ValueError(_FAILURE_THRESHOLD_INVALID)
        if reset_timeout < 0:
            raise ValueError(_RESET_TIMEOUT_INVALID)
        if success_threshold < 1:
            raise ValueError(_SUCCESS_THRESHOLD_INVALID)
        if failure_rate_threshold is not None and not (0.0 < failure_rate_threshold <= 1.0):
            raise ValueError(_FAILURE_RATE_THRESHOLD_INVALID)
        if window_seconds <= 0:
            raise ValueError(_WINDOW_SECONDS_INVALID)
        if minimum_calls < 1:
            raise ValueError(_MINIMUM_CALLS_INVALID)
        self._failure_threshold = failure_threshold
        self._reset_timeout = reset_timeout
        self._success_threshold = success_threshold
        # Accept any Collection (set, frozenset, list, ...) and freeze it so callers
        # aren't forced to construct a frozenset just to satisfy the type checker.
        self._failure_status_codes = (
            frozenset(failure_status_codes) if failure_status_codes is not None else _DEFAULT_FAILURE_STATUS_CODES
        )
        self._failure_rate_threshold = failure_rate_threshold
        self._minimum_calls = minimum_calls
        self._rate_mode = failure_rate_threshold is not None
        self._window = _RollingWindow(window_seconds) if self._rate_mode else None
        self._window_seconds = window_seconds
        self._now = now
        self._state = CircuitState.CLOSED
        self._consecutive_failures = 0
        self._consecutive_successes = 0
        self._opened_at = 0.0
        self._probe_in_flight = False

    def is_failure_status(self, status_code: int) -> bool:
        return status_code in self._failure_status_codes

    @property
    def state(self) -> CircuitState:
        """The circuit's current stored state (raw read; no lazy OPEN→HALF_OPEN transition)."""
        return self._state

    def admit(self, request: httpx2.Request) -> str:
        """Decide the request's role, or raise CircuitOpenError. No await inside."""
        if self._state is CircuitState.CLOSED:
            return _ROLE_CLOSED
        if self._state is CircuitState.OPEN:
            elapsed = self._now() - self._opened_at
            if elapsed >= self._reset_timeout:
                self._state = CircuitState.HALF_OPEN
                self._probe_in_flight = True
                self._emit(request, "circuit.half_open", logging.INFO, "circuit half-open — admitting probe", {})
                return _ROLE_PROBE
            retry_after = max(0.0, self._reset_timeout - elapsed)
            self._emit(
                request,
                "circuit.rejected",
                logging.WARNING,
                "circuit open — rejecting request",
                {"retry_after": retry_after},
            )
            raise CircuitOpenError(retry_after=retry_after)
        # HALF_OPEN
        if self._probe_in_flight:
            self._emit(
                request,
                "circuit.rejected",
                logging.WARNING,
                "circuit half-open — rejecting request (probe in flight)",
                {"retry_after": None},
            )
            raise CircuitOpenError(retry_after=None)
        self._probe_in_flight = True
        return _ROLE_PROBE

    def on_success(self, role: str, request: httpx2.Request) -> None:
        if role == _ROLE_PROBE:
            self._probe_in_flight = False
        if self._state is CircuitState.CLOSED:
            if self._rate_mode:
                self._record_outcome(request, failed=False)
            else:
                self._consecutive_failures = 0
        elif self._state is CircuitState.HALF_OPEN:
            self._consecutive_successes += 1
            if self._consecutive_successes >= self._success_threshold:
                self._state = CircuitState.CLOSED
                self._consecutive_failures = 0
                self._consecutive_successes = 0
                if self._rate_mode:
                    self._window.clear()  # ty: ignore[unresolved-attribute]
                self._emit(request, "circuit.closed", logging.INFO, "circuit closed — service recovered", {})

    def on_failure(self, role: str, request: httpx2.Request) -> None:
        if role == _ROLE_PROBE:
            self._probe_in_flight = False
        if self._state is CircuitState.CLOSED:
            if self._rate_mode:
                self._record_outcome(request, failed=True)
            else:
                self._consecutive_failures += 1
                if self._consecutive_failures >= self._failure_threshold:
                    self._open(request, failures=self._consecutive_failures)
        elif self._state is CircuitState.HALF_OPEN:
            self._open(request, failures=1)  # 1 = the single probe failure that re-opened the circuit

    def release_probe(self, role: str) -> None:
        """Release the probe slot without recording success or failure (non-counted exc)."""
        if role == _ROLE_PROBE:
            self._probe_in_flight = False

    def _enter_open(self, request: httpx2.Request, message: str, attributes: dict[str, typing.Any]) -> None:
        self._state = CircuitState.OPEN
        self._opened_at = self._now()
        self._consecutive_failures = 0
        self._consecutive_successes = 0
        self._emit(request, "circuit.opened", logging.WARNING, message, attributes)

    def _open(self, request: httpx2.Request, *, failures: int) -> None:
        self._enter_open(
            request,
            "circuit opened — failure threshold reached",
            {"failure_threshold": self._failure_threshold, "failures": failures},
        )

    def _open_rate(self, request: httpx2.Request, *, total: int, failures: int) -> None:
        self._enter_open(
            request,
            "circuit opened — failure rate threshold reached",
            {
                "failure_rate": failures / total,
                "failure_rate_threshold": self._failure_rate_threshold,
                "window_seconds": self._window_seconds,
                "observed_calls": total,
            },
        )

    def _record_outcome(self, request: httpx2.Request, *, failed: bool) -> None:
        # Only reached in rate mode, where _window and _failure_rate_threshold are non-None.
        now = self._now()
        self._window.record(now, failed=failed)  # ty: ignore[unresolved-attribute]
        total, failures = self._window.totals(now)  # ty: ignore[unresolved-attribute]
        threshold = self._failure_rate_threshold
        if threshold is not None and total >= self._minimum_calls and failures / total >= threshold:
            self._open_rate(request, total=total, failures=failures)

    def _emit(
        self,
        request: httpx2.Request,
        event_name: str,
        level: int,
        message: str,
        attributes: dict[str, typing.Any],
    ) -> None:
        _emit_event(
            _LOGGER,
            event_name,
            level=level,
            message=message,
            attributes={**attributes, "method": request.method, "url": str(request.url)},
        )


class AsyncCircuitBreaker:
    """Async classic circuit breaker middleware. See the module docstring for the contract."""

    def __init__(  # noqa: PLR0913 — breaker has many orthogonal knobs; a dataclass would be worse
        self,
        *,
        failure_threshold: int = 5,
        reset_timeout: float = 30.0,
        success_threshold: int = 1,
        failure_status_codes: Collection[int] | None = None,
        failure_rate_threshold: float | None = None,
        window_seconds: float = 30.0,
        minimum_calls: int = 20,
        _now: Callable[[], float] = time.monotonic,
    ) -> None:
        self._state = _CircuitBreakerState(
            failure_threshold=failure_threshold,
            reset_timeout=reset_timeout,
            success_threshold=success_threshold,
            failure_status_codes=failure_status_codes,
            failure_rate_threshold=failure_rate_threshold,
            window_seconds=window_seconds,
            minimum_calls=minimum_calls,
            now=_now,
        )
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_lock = threading.Lock()

    def _check_loop(self) -> None:
        check_event_loop(
            lambda: self._loop,
            lambda loop: setattr(self, "_loop", loop),
            self._loop_lock,
            _CROSS_LOOP_MSG,
        )

    @property
    def state(self) -> CircuitState:
        """Current circuit state — CLOSED, OPEN, or HALF_OPEN.

        Read-only and side-effect-free (a single atomic attribute read; intentionally lock-free).
        """
        return self._state.state

    async def __call__(self, request: httpx2.Request, next: AsyncNext) -> httpx2.Response:  # noqa: A002
        """Admit, forward, then record the outcome. Fast-fail when the circuit is not closed."""
        self._check_loop()
        role = self._state.admit(request)
        try:
            response = await next(request)
        except StatusError as exc:
            if self._state.is_failure_status(exc.response.status_code):
                self._state.on_failure(role, request)
            else:
                self._state.on_success(role, request)
            raise
        except (NetworkError, TimeoutError):
            self._state.on_failure(role, request)
            raise
        except BaseException:
            self._state.release_probe(role)
            raise
        self._state.on_success(role, request)
        return response


class CircuitBreaker:
    """Sync classic circuit breaker middleware. Mirror of AsyncCircuitBreaker.

    Serializes every state transition with a threading.Lock. Sharable across Clients
    (one shared circuit); a sync instance cannot be shared with an AsyncClient.
    """

    def __init__(  # noqa: PLR0913 — breaker has many orthogonal knobs; a dataclass would be worse
        self,
        *,
        failure_threshold: int = 5,
        reset_timeout: float = 30.0,
        success_threshold: int = 1,
        failure_status_codes: Collection[int] | None = None,
        failure_rate_threshold: float | None = None,
        window_seconds: float = 30.0,
        minimum_calls: int = 20,
        _now: Callable[[], float] = time.monotonic,
    ) -> None:
        self._state = _CircuitBreakerState(
            failure_threshold=failure_threshold,
            reset_timeout=reset_timeout,
            success_threshold=success_threshold,
            failure_status_codes=failure_status_codes,
            failure_rate_threshold=failure_rate_threshold,
            window_seconds=window_seconds,
            minimum_calls=minimum_calls,
            now=_now,
        )
        self._lock = threading.Lock()

    @property
    def state(self) -> CircuitState:
        """Current circuit state — CLOSED, OPEN, or HALF_OPEN.

        Read-only and side-effect-free (a single atomic attribute read; intentionally lock-free).
        """
        return self._state.state

    def __call__(self, request: httpx2.Request, next: Next) -> httpx2.Response:  # noqa: A002
        """Admit, forward, then record the outcome. Fast-fail when the circuit is not closed."""
        with self._lock:
            role = self._state.admit(request)
        try:
            response = next(request)
        except StatusError as exc:
            with self._lock:
                if self._state.is_failure_status(exc.response.status_code):
                    self._state.on_failure(role, request)
                else:
                    self._state.on_success(role, request)
            raise
        except (NetworkError, TimeoutError):
            with self._lock:
                self._state.on_failure(role, request)
            raise
        except BaseException:
            with self._lock:
                self._state.release_probe(role)
            raise
        with self._lock:
            self._state.on_success(role, request)
        return response

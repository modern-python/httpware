"""CircuitBreaker + AsyncCircuitBreaker — consecutive-failure and failure-rate circuit breakers.

KeyedCircuitBreaker + AsyncKeyedCircuitBreaker run one such circuit per circuit key (default:
the request URL's origin), so one failing upstream does not open the circuit for the others.

A counted failure is a NetworkError, an httpware TimeoutError, or a StatusError whose
status_code is in the effective failure set (default: all 5xx). 4xx — including 429 —
count as successes: 429 means healthy-but-throttling, and tripping on it amplifies
incidents. A RetryBudgetExhaustedError is classified by its last_exception. Any other
exception propagates without affecting circuit state. In
particular, non-NetworkError transport problems — e.g. httpx2.InvalidURL from a
malformed URL — are foreign: they propagate unchanged and do not increment the
failure counter, so programming errors cannot trip the breaker.

State machine (classic / consecutive-failure):
    CLOSED    — forward; count consecutive counted-failures; open at failure_threshold.
    OPEN      — fast-fail with CircuitOpenError; after reset_timeout the next request
                becomes the half-open probe.
    HALF_OPEN — admit exactly one probe at a time; success_threshold consecutive probe
                successes close the circuit; one probe failure re-opens it.

An outcome applies only to the state its request was admitted under: a request still in
flight when the circuit changes state finishes without touching the circuit.

circuit.rejected is emitted at most once per second per circuit; its `suppressed`
attribute counts the rejections not emitted since the previous one.

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
import functools
import logging
import math
import threading
import time
import typing
from collections.abc import Callable, Collection, Hashable

import httpx2

from httpware._internal.observability import _emit_event
from httpware.errors import (
    CircuitOpenError,
    NetworkError,
    RetryBudgetExhaustedError,
    StatusError,
    TimeoutError,  # noqa: A004
)
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
_KEYED_CROSS_LOOP_MSG = (
    "AsyncKeyedCircuitBreaker is bound to a single event loop. First seen on {first!r}; "
    "current request is on {current!r}. Use one AsyncKeyedCircuitBreaker per loop; "
    "cross-thread sharing requires the sync KeyedCircuitBreaker primitive."
)

_DEFAULT_FAILURE_STATUS_CODES = frozenset(range(500, 600))

_BUCKET_COUNT = 10

_SUCCESS = 0
_FAILURE = 1
_FOREIGN = 2

_PROBE = 1
_EPOCH_STEP = 2

_REJECTED_EVENT_INTERVAL = 1.0

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


class _RejectionError(Exception):
    """Raised by `admit` to refuse a request; `message` is None when the event is suppressed."""

    def __init__(self, retry_after: float | None, message: str | None, suppressed: int) -> None:
        self.retry_after = retry_after
        self.message = message
        self.suppressed = suppressed


class _CircuitBreakerState:
    """Lock-free circuit-breaker state machine shared by the sync + async wrappers.

    Every method is synchronous and performs no I/O beyond logging. The async wrapper
    calls these directly (atomic under a single event loop because no await occurs
    inside a transition); the sync wrapper wraps `admit` and `record` in a threading.Lock.
    `admit` hands out a ticket: the epoch, which every transition advances by two, plus one
    for the probe. `record` ignores a ticket from an earlier epoch.
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
        key: str | None = None,
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
        self._key = key
        self._state = CircuitState.CLOSED
        self._consecutive_failures = 0
        self._consecutive_successes = 0
        self._opened_at = 0.0
        self._probe_in_flight = False
        self._epoch = 0
        self._rejected_emitted_at = -math.inf
        self._rejections_suppressed = 0

    @property
    def state(self) -> CircuitState:
        """The circuit's current stored state (raw read; no lazy OPEN→HALF_OPEN transition)."""
        return self._state

    def admit(self, request: httpx2.Request) -> int:
        """Return the request's ticket, or raise _RejectionError. No await inside."""
        if self._state is CircuitState.CLOSED:
            return self._epoch
        now = self._now()
        if self._state is CircuitState.OPEN:
            elapsed = now - self._opened_at
            if elapsed < self._reset_timeout:
                self._reject(now, max(0.0, self._reset_timeout - elapsed), "circuit open — rejecting request")
            self._move_to(CircuitState.HALF_OPEN)
            self._emit(request, "circuit.half_open", logging.INFO, "circuit half-open — admitting probe", {})
        elif self._probe_in_flight:
            self._reject(now, None, "circuit half-open — rejecting request (probe in flight)")
        self._probe_in_flight = True
        return self._epoch + _PROBE

    def classify(self, exc: BaseException | None) -> int:
        """Map an exception raised past the breaker to _SUCCESS, _FAILURE or _FOREIGN."""
        if isinstance(exc, RetryBudgetExhaustedError):
            exc = exc.last_exception
        if isinstance(exc, StatusError):
            return _FAILURE if exc.response.status_code in self._failure_status_codes else _SUCCESS
        if isinstance(exc, (NetworkError, TimeoutError)):
            return _FAILURE
        return _FOREIGN

    def record(self, ticket: int, outcome: int, request: httpx2.Request) -> None:
        """Apply an admitted request's outcome; a no-op if the circuit has transitioned since."""
        if ticket == self._epoch:
            if outcome == _SUCCESS and not self._rate_mode:
                self._consecutive_failures = 0
            elif outcome != _FOREIGN:
                self._record_closed(request, failed=outcome == _FAILURE)
        elif ticket == self._epoch + _PROBE:
            self._probe_in_flight = False
            if outcome == _SUCCESS:
                self._record_probe_success(request)
            elif outcome == _FAILURE:
                self._open(request, failures=1)  # 1 = the single probe failure that re-opened the circuit

    def rejected(self, request: httpx2.Request, rejection: _RejectionError) -> CircuitOpenError:
        """Emit the rejection's event unless `admit` suppressed it; return the error to raise."""
        if rejection.message is not None:
            self._emit(
                request,
                "circuit.rejected",
                logging.WARNING,
                rejection.message,
                {"retry_after": rejection.retry_after, "suppressed": rejection.suppressed},
            )
        return CircuitOpenError(retry_after=rejection.retry_after)

    def _reject(self, now: float, retry_after: float | None, message: str) -> typing.NoReturn:
        if now - self._rejected_emitted_at < _REJECTED_EVENT_INTERVAL:
            self._rejections_suppressed += 1
            raise _RejectionError(retry_after, None, 0)
        self._rejected_emitted_at = now
        suppressed, self._rejections_suppressed = self._rejections_suppressed, 0
        raise _RejectionError(retry_after, message, suppressed)

    def _record_closed(self, request: httpx2.Request, *, failed: bool) -> None:
        if self._rate_mode:
            self._record_outcome(request, failed=failed)
        elif failed:
            self._consecutive_failures += 1
            if self._consecutive_failures >= self._failure_threshold:
                self._open(request, failures=self._consecutive_failures)

    def _record_probe_success(self, request: httpx2.Request) -> None:
        self._consecutive_successes += 1
        if self._consecutive_successes >= self._success_threshold:
            self._move_to(CircuitState.CLOSED)
            self._consecutive_failures = 0
            self._consecutive_successes = 0
            if self._rate_mode:
                self._window.clear()  # ty: ignore[unresolved-attribute]
            self._emit(request, "circuit.closed", logging.INFO, "circuit closed — service recovered", {})

    def _move_to(self, state: CircuitState) -> None:
        self._state = state
        self._epoch += _EPOCH_STEP

    def _enter_open(self, request: httpx2.Request, message: str, attributes: dict[str, typing.Any]) -> None:
        self._move_to(CircuitState.OPEN)
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
        attributes = {**attributes, "method": request.method, "url": str(request.url)}
        if self._key is not None:
            attributes["circuit_key"] = self._key
        _emit_event(_LOGGER, event_name, level=level, message=message, attributes=attributes)


async def _call_async(state: _CircuitBreakerState, request: httpx2.Request, next: AsyncNext) -> httpx2.Response:  # noqa: A002
    try:
        ticket = state.admit(request)
    except _RejectionError as rejection:
        raise state.rejected(request, rejection) from None
    try:
        response = await next(request)
    except BaseException as exc:
        state.record(ticket, state.classify(exc), request)
        raise
    state.record(ticket, _SUCCESS, request)
    return response


def _call_sync(
    state: _CircuitBreakerState,
    lock: threading.Lock,
    request: httpx2.Request,
    next: Next,  # noqa: A002
) -> httpx2.Response:
    try:
        with lock:
            ticket = state.admit(request)
    except _RejectionError as rejection:
        raise state.rejected(request, rejection) from None
    try:
        response = next(request)
    except BaseException as exc:
        outcome = state.classify(exc)
        with lock:
            state.record(ticket, outcome, request)
        raise
    with lock:
        state.record(ticket, _SUCCESS, request)
    return response


def _origin(request: httpx2.Request) -> str:
    return f"{request.url.scheme}://{request.url.netloc.decode('ascii')}"


class _KeyedStates:
    """One lazily created _CircuitBreakerState per circuit key; the map is never pruned.

    Not synchronized: the async wrapper relies on its single event loop, the sync wrapper
    calls `get` under its lock.
    """

    def __init__(self, key: Callable[[httpx2.Request], Hashable], **config: typing.Any) -> None:  # noqa: ANN401
        self._key = key
        self._new_state = functools.partial(_CircuitBreakerState, **config)
        self._new_state()  # validates the config at construction instead of on the first request
        self._states: dict[Hashable, _CircuitBreakerState] = {}

    def get(self, request: httpx2.Request) -> _CircuitBreakerState:
        circuit_key = self._key(request)
        state = self._states.get(circuit_key)
        if state is None:
            state = self._states[circuit_key] = self._new_state(key=str(circuit_key))
        return state


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
        return await _call_async(self._state, request, next)


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
        return _call_sync(self._state, self._lock, request, next)


class AsyncKeyedCircuitBreaker:
    """Async circuit breaker with one independent circuit per circuit key.

    `key` maps a request to its circuit key; the default is the request URL's origin as a string
    such as "https://api.example" (scheme, host and non-default port; never userinfo). Every
    circuit behaves exactly like an AsyncCircuitBreaker built with the same arguments. Circuits
    are created on first use and kept for the breaker's lifetime, so the key must take a small,
    bounded set of values.
    """

    def __init__(  # noqa: PLR0913 — breaker has many orthogonal knobs; a dataclass would be worse
        self,
        *,
        key: Callable[[httpx2.Request], Hashable] = _origin,
        failure_threshold: int = 5,
        reset_timeout: float = 30.0,
        success_threshold: int = 1,
        failure_status_codes: Collection[int] | None = None,
        failure_rate_threshold: float | None = None,
        window_seconds: float = 30.0,
        minimum_calls: int = 20,
        _now: Callable[[], float] = time.monotonic,
    ) -> None:
        self._states = _KeyedStates(
            key,
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
            _KEYED_CROSS_LOOP_MSG,
        )

    async def __call__(self, request: httpx2.Request, next: AsyncNext) -> httpx2.Response:  # noqa: A002
        """Pick the request's circuit, then admit, forward and record the outcome on it."""
        self._check_loop()
        return await _call_async(self._states.get(request), request, next)


class KeyedCircuitBreaker:
    """Sync circuit breaker with one independent circuit per circuit key. Mirror of AsyncKeyedCircuitBreaker.

    One threading.Lock serializes circuit lookup and every transition across all keys.
    """

    def __init__(  # noqa: PLR0913 — breaker has many orthogonal knobs; a dataclass would be worse
        self,
        *,
        key: Callable[[httpx2.Request], Hashable] = _origin,
        failure_threshold: int = 5,
        reset_timeout: float = 30.0,
        success_threshold: int = 1,
        failure_status_codes: Collection[int] | None = None,
        failure_rate_threshold: float | None = None,
        window_seconds: float = 30.0,
        minimum_calls: int = 20,
        _now: Callable[[], float] = time.monotonic,
    ) -> None:
        self._states = _KeyedStates(
            key,
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

    def __call__(self, request: httpx2.Request, next: Next) -> httpx2.Response:  # noqa: A002
        """Pick the request's circuit, then admit, forward and record the outcome on it."""
        with self._lock:
            state = self._states.get(request)
        return _call_sync(state, self._lock, request, next)

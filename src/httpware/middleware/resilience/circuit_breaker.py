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

An outage episode runs from CLOSED to OPEN until the circuit is CLOSED again. Within one,
circuit.rejected is emitted at most once per second; its `suppressed` attribute counts the
rejections not emitted since the previous one, and the first rejection of an episode is
always emitted. circuit.closed carries `rejected`, the episode's total rejection count.

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
threading.Lock and emits events only after releasing it, so a logging handler may send
requests through the same breaker. A request to a closed circuit is admitted without the
lock; its outcome is still recorded under it. Both are sharable across clients (one shared circuit);
a sync instance cannot be shared with an async one.
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
    "AsyncCircuitBreaker is bound to the event loop it first ran on ({first!r}) and was called from {current!r}. "
    "Create async resilience middleware, and the AsyncClient holding it, once per event loop, "
    "for example inside the coroutine passed to asyncio.run(). "
    "Sharing one instance across pytest-asyncio's function-scoped loops is the usual way to hit this."
)
_KEYED_CROSS_LOOP_MSG = (
    "AsyncKeyedCircuitBreaker is bound to the event loop it first ran on ({first!r}) and was called from {current!r}. "
    "Create async resilience middleware, and the AsyncClient holding it, once per event loop, "
    "for example inside the coroutine passed to asyncio.run(). "
    "Sharing one instance across pytest-asyncio's function-scoped loops is the usual way to hit this."
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

    `window_seconds` is split into `_BUCKET_COUNT` buckets, one per integer time-slot; the
    window is the current slot and the `_BUCKET_COUNT - 1` before it. Running totals are
    kept beside the buckets, so recording and reading are constant-time. Every method is
    synchronous and reads `now` from its caller (so the breaker's critical section owns
    the clock read).
    """

    def __init__(self, window_seconds: float) -> None:
        self._bucket_width = window_seconds / _BUCKET_COUNT
        self._slot: float = -math.inf
        self._index = 0
        self._success = [0] * _BUCKET_COUNT
        self._failure = [0] * _BUCKET_COUNT
        self._total = 0
        self._failures = 0

    def _advance(self, now: float) -> None:
        slot = now // self._bucket_width
        if slot <= self._slot:
            return
        current = int(slot)
        if current - self._slot >= _BUCKET_COUNT:
            self.clear()
        else:
            for stale in range(int(self._slot) + 1, current + 1):
                index = stale % _BUCKET_COUNT
                self._total -= self._success[index] + self._failure[index]
                self._failures -= self._failure[index]
                self._success[index] = 0
                self._failure[index] = 0
        self._slot = current
        self._index = current % _BUCKET_COUNT

    def record(self, now: float, *, failed: bool) -> None:
        self._advance(now)
        if failed:
            self._failure[self._index] += 1
            self._failures += 1
        else:
            self._success[self._index] += 1
        self._total += 1

    def totals(self, now: float) -> tuple[int, int]:
        """Return (total, failures) across buckets still inside the window at `now`."""
        self._advance(now)
        return self._total, self._failures

    def clear(self) -> None:
        self._success = [0] * _BUCKET_COUNT
        self._failure = [0] * _BUCKET_COUNT
        self._total = 0
        self._failures = 0


_Event = tuple[str, int, str, dict[str, typing.Any]]


class _HalfOpened(Exception):  # noqa: N818
    """Raised by `admit` when it moved the circuit to HALF_OPEN; carries the probe's ticket and events."""

    def __init__(self, ticket: int, events: list[_Event] | None) -> None:
        self.ticket = ticket
        self.events = events


class _RejectionError(Exception):
    """Raised by `admit` to refuse a request, carrying the events to emit once the lock is released."""

    def __init__(self, retry_after: float | None, events: list[_Event] | None) -> None:
        self.retry_after = retry_after
        self.events = events


class _CircuitBreakerState:
    """Lock-free circuit-breaker state machine shared by the sync + async wrappers.

    Every method is synchronous and performs no I/O. The async wrapper calls these directly
    (atomic under a single event loop because no await occurs inside a transition); the sync
    wrapper wraps `admit` and `record` in a threading.Lock. Transitions queue their events;
    the caller takes them with the outcome and emits them outside any lock.
    `admit` hands out a ticket: the epoch, which every transition advances by two, plus one
    for the probe. `record` ignores a ticket from an earlier epoch.
    `closed_ticket` is the epoch while CLOSED and None otherwise, so one read admits without the lock.
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
        self.closed_ticket: int | None = 0
        self._rejected_emitted_at = -math.inf
        self._rejections_suppressed = 0
        self._episode_rejections = 0
        self._events: list[_Event] | None = None

    @property
    def state(self) -> CircuitState:
        """The circuit's current stored state (raw read; no lazy OPEN→HALF_OPEN transition)."""
        return self._state

    def admit(self, request: httpx2.Request) -> int:
        """Return the request's ticket, or raise _RejectionError or _HalfOpened. No await inside."""
        ticket = self.closed_ticket
        if ticket is not None:
            return ticket
        now = self._now()
        if self._state is CircuitState.OPEN:
            elapsed = now - self._opened_at
            if elapsed < self._reset_timeout:
                self._reject(request, now, max(0.0, self._reset_timeout - elapsed), "circuit open — rejecting request")
            self._move_to(CircuitState.HALF_OPEN)
            self._probe_in_flight = True
            self._queue(request, "circuit.half_open", logging.INFO, "circuit half-open — admitting probe", {})
            raise _HalfOpened(self._epoch + _PROBE, self.take_events())
        if self._probe_in_flight:
            self._reject(request, now, None, "circuit half-open — rejecting request (probe in flight)")
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

    def record(self, ticket: int, outcome: int, request: httpx2.Request) -> list[_Event] | None:
        """Apply an admitted request's outcome and return the events it queued.

        A no-op if the circuit has transitioned since the ticket was issued.
        """
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
        events = self._events
        if events is not None:
            self._events = None
        return events

    def take_events(self) -> list[_Event] | None:
        """Return and clear the queued events."""
        events, self._events = self._events, None
        return events

    def _reject(self, request: httpx2.Request, now: float, retry_after: float | None, message: str) -> typing.NoReturn:
        self._episode_rejections += 1
        if now - self._rejected_emitted_at < _REJECTED_EVENT_INTERVAL:
            self._rejections_suppressed += 1
            raise _RejectionError(retry_after, None)
        self._rejected_emitted_at = now
        suppressed, self._rejections_suppressed = self._rejections_suppressed, 0
        attributes = {"retry_after": retry_after, "suppressed": suppressed}
        self._queue(request, "circuit.rejected", logging.WARNING, message, attributes)
        raise _RejectionError(retry_after, self.take_events())

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
            attributes = {"rejected": self._episode_rejections}
            self._queue(request, "circuit.closed", logging.INFO, "circuit closed — service recovered", attributes)

    def _move_to(self, state: CircuitState) -> None:
        self._state = state
        self._epoch += _EPOCH_STEP
        self.closed_ticket = self._epoch if state is CircuitState.CLOSED else None

    def _enter_open(self, request: httpx2.Request, message: str, attributes: dict[str, typing.Any]) -> None:
        if self._state is CircuitState.CLOSED:
            self._rejected_emitted_at = -math.inf
            self._rejections_suppressed = 0
            self._episode_rejections = 0
        self._move_to(CircuitState.OPEN)
        self._opened_at = self._now()
        self._consecutive_failures = 0
        self._consecutive_successes = 0
        self._queue(request, "circuit.opened", logging.WARNING, message, attributes)

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

    def _queue(
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
        if self._events is None:
            self._events = []
        self._events.append((event_name, level, message, attributes))


def _emit_events(events: list[_Event]) -> None:
    for event_name, level, message, attributes in events:
        _emit_event(_LOGGER, event_name, level=level, message=message, attributes=attributes)


def _half_opened(half_opened: _HalfOpened) -> int:
    if half_opened.events is not None:
        _emit_events(half_opened.events)
    return half_opened.ticket


def _rejected(rejection: _RejectionError) -> CircuitOpenError:
    if rejection.events is not None:
        _emit_events(rejection.events)
    return CircuitOpenError(retry_after=rejection.retry_after)


def _admit(state: _CircuitBreakerState, request: httpx2.Request) -> int:
    try:
        return state.admit(request)
    except _RejectionError as rejection:
        raise _rejected(rejection) from None
    except _HalfOpened as half_opened:
        return _half_opened(half_opened)


def _admit_locked(state: _CircuitBreakerState, lock: threading.Lock, request: httpx2.Request) -> int:
    try:
        with lock:
            return state.admit(request)
    except _RejectionError as rejection:
        raise _rejected(rejection) from None
    except _HalfOpened as half_opened:
        return _half_opened(half_opened)


async def _call_async(state: _CircuitBreakerState, request: httpx2.Request, next: AsyncNext) -> httpx2.Response:  # noqa: A002
    ticket = state.closed_ticket
    if ticket is None:
        ticket = _admit(state, request)
    try:
        response = await next(request)
    except BaseException as exc:
        events = state.record(ticket, state.classify(exc), request)
        if events is not None:
            _emit_events(events)
        raise
    events = state.record(ticket, _SUCCESS, request)
    if events is not None:
        _emit_events(events)
    return response


def _call_sync(
    state: _CircuitBreakerState,
    lock: threading.Lock,
    request: httpx2.Request,
    next: Next,  # noqa: A002
) -> httpx2.Response:
    ticket = state.closed_ticket
    if ticket is None:
        ticket = _admit_locked(state, lock, request)
    try:
        response = next(request)
    except BaseException as exc:
        outcome = state.classify(exc)
        with lock:
            events = state.record(ticket, outcome, request)
        if events is not None:
            _emit_events(events)
        raise
    with lock:
        events = state.record(ticket, _SUCCESS, request)
    if events is not None:
        _emit_events(events)
    return response


def _origin(request: httpx2.Request) -> tuple[str, bytes, int | None]:
    url = request.url
    return url.scheme, url.raw_host, url.port


def _origin_label(request: httpx2.Request) -> str:
    return f"{request.url.scheme}://{request.url.netloc.decode('ascii')}"


class _KeyedStates:
    """One lazily created _CircuitBreakerState per circuit key; the map is never pruned.

    Lookups read the map without a lock; creating a circuit takes `_create_lock`.
    """

    def __init__(self, key: Callable[[httpx2.Request], Hashable], **config: typing.Any) -> None:  # noqa: ANN401
        self._key = key
        self._new_state = functools.partial(_CircuitBreakerState, **config)
        self._new_state()  # validates the config at construction instead of on the first request
        self._states: dict[Hashable, _CircuitBreakerState] = {}
        self._create_lock = threading.Lock()

    def get(self, request: httpx2.Request) -> _CircuitBreakerState:
        circuit_key = self._key(request)
        state = self._states.get(circuit_key)
        if state is None:
            state = self._create(circuit_key, request)
        return state

    def _create(self, circuit_key: Hashable, request: httpx2.Request) -> _CircuitBreakerState:
        label = _origin_label(request) if self._key is _origin else str(circuit_key)
        with self._create_lock:
            state = self._states.get(circuit_key)
            if state is None:
                state = self._states[circuit_key] = self._new_state(key=label)
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

    `key` maps a request to its circuit key; the default is the request URL's origin (scheme, host
    and non-default port; never userinfo), shown in events as "https://api.example". Every
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

    One threading.Lock serializes every transition across all keys. Looking up an existing
    circuit and admitting into a closed one take no lock.
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
        return _call_sync(self._states.get(request), self._lock, request, next)

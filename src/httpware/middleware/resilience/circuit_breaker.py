"""CircuitBreaker + AsyncCircuitBreaker — classic consecutive-failure circuit breaker.

See planning/specs/2026-06-13-circuit-breaker-and-timeout-design.md for the contract.

A counted failure is a NetworkError, an httpware TimeoutError, or a StatusError whose
status_code is in the effective failure set (default: all 5xx). 4xx — including 429 —
count as successes: 429 means healthy-but-throttling, and tripping on it amplifies
incidents. Any other exception propagates without affecting circuit state.

State machine (classic / consecutive-failure):
    CLOSED    — forward; count consecutive counted-failures; open at failure_threshold.
    OPEN      — fast-fail with CircuitOpenError; after reset_timeout the next request
                becomes the half-open probe.
    HALF_OPEN — admit exactly one probe at a time; success_threshold consecutive probe
                successes close the circuit; one probe failure re-opens it.

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
from collections.abc import Callable

import httpx2

from httpware._internal.observability import _emit_event
from httpware.errors import CircuitOpenError, NetworkError, StatusError, TimeoutError  # noqa: A004
from httpware.middleware import AsyncNext, Next


_FAILURE_THRESHOLD_INVALID = "failure_threshold must be >= 1"
_RESET_TIMEOUT_INVALID = "reset_timeout must be >= 0"
_SUCCESS_THRESHOLD_INVALID = "success_threshold must be >= 1"
_CROSS_LOOP_MSG = (
    "AsyncCircuitBreaker is bound to a single event loop. First seen on {first!r}; "
    "current request is on {current!r}. Use one AsyncCircuitBreaker per loop; "
    "cross-thread sharing requires the sync CircuitBreaker primitive."
)

_DEFAULT_FAILURE_STATUS_CODES = frozenset(range(500, 600))

_ROLE_CLOSED = "closed"
_ROLE_PROBE = "probe"

_LOGGER = logging.getLogger("httpware.circuit_breaker")


class _CircuitState(enum.Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class _CircuitBreakerState:
    """Lock-free circuit-breaker state machine shared by the sync + async wrappers.

    Every method is synchronous and performs no I/O beyond logging. The async wrapper
    calls these directly (atomic under a single event loop because no await occurs
    inside a transition); the sync wrapper wraps each call in a threading.Lock.
    """

    def __init__(
        self,
        *,
        failure_threshold: int,
        reset_timeout: float,
        success_threshold: int,
        failure_status_codes: frozenset[int] | None,
        now: Callable[[], float],
    ) -> None:
        if failure_threshold < 1:
            raise ValueError(_FAILURE_THRESHOLD_INVALID)
        if reset_timeout < 0:
            raise ValueError(_RESET_TIMEOUT_INVALID)
        if success_threshold < 1:
            raise ValueError(_SUCCESS_THRESHOLD_INVALID)
        self._failure_threshold = failure_threshold
        self._reset_timeout = reset_timeout
        self._success_threshold = success_threshold
        self._failure_status_codes = (
            failure_status_codes if failure_status_codes is not None else _DEFAULT_FAILURE_STATUS_CODES
        )
        self._now = now
        self._state = _CircuitState.CLOSED
        self._consecutive_failures = 0
        self._consecutive_successes = 0
        self._opened_at = 0.0
        self._probe_in_flight = False

    def is_failure_status(self, status_code: int) -> bool:
        return status_code in self._failure_status_codes

    def admit(self, request: httpx2.Request) -> str:
        """Decide the request's role, or raise CircuitOpenError. No await inside."""
        if self._state is _CircuitState.CLOSED:
            return _ROLE_CLOSED
        if self._state is _CircuitState.OPEN:
            elapsed = self._now() - self._opened_at
            if elapsed >= self._reset_timeout:
                self._state = _CircuitState.HALF_OPEN
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
        if self._state is _CircuitState.CLOSED:
            self._consecutive_failures = 0
        elif self._state is _CircuitState.HALF_OPEN:
            self._consecutive_successes += 1
            if self._consecutive_successes >= self._success_threshold:
                self._state = _CircuitState.CLOSED
                self._consecutive_failures = 0
                self._consecutive_successes = 0
                self._emit(request, "circuit.closed", logging.INFO, "circuit closed — service recovered", {})

    def on_failure(self, role: str, request: httpx2.Request) -> None:
        if role == _ROLE_PROBE:
            self._probe_in_flight = False
        if self._state is _CircuitState.CLOSED:
            self._consecutive_failures += 1
            if self._consecutive_failures >= self._failure_threshold:
                self._open(request, failures=self._consecutive_failures)
        elif self._state is _CircuitState.HALF_OPEN:
            self._open(request, failures=1)  # 1 = the single probe failure that re-opened the circuit

    def release_probe(self, role: str) -> None:
        """Release the probe slot without recording success or failure (non-counted exc)."""
        if role == _ROLE_PROBE:
            self._probe_in_flight = False

    def _open(self, request: httpx2.Request, *, failures: int) -> None:
        self._state = _CircuitState.OPEN
        self._opened_at = self._now()
        self._consecutive_failures = 0
        self._consecutive_successes = 0
        self._emit(
            request,
            "circuit.opened",
            logging.WARNING,
            "circuit opened — failure threshold reached",
            {"failure_threshold": self._failure_threshold, "failures": failures},
        )

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

    def __init__(
        self,
        *,
        failure_threshold: int = 5,
        reset_timeout: float = 30.0,
        success_threshold: int = 1,
        failure_status_codes: frozenset[int] | None = None,
        _now: Callable[[], float] = time.monotonic,
    ) -> None:
        self._state = _CircuitBreakerState(
            failure_threshold=failure_threshold,
            reset_timeout=reset_timeout,
            success_threshold=success_threshold,
            failure_status_codes=failure_status_codes,
            now=_now,
        )
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_lock = threading.Lock()

    def _check_loop(self) -> None:
        current = asyncio.get_running_loop()
        cached = self._loop
        if cached is current:
            return
        if cached is not None:
            raise RuntimeError(_CROSS_LOOP_MSG.format(first=cached, current=current))
        with self._loop_lock:
            if self._loop is None:
                self._loop = current
            # pragma below: inner double-check-with-lock race arm; only reachable when
            # two threads simultaneously pass the outer check, which single-threaded
            # tests can't trigger.
            elif self._loop is not current:  # pragma: no cover
                raise RuntimeError(_CROSS_LOOP_MSG.format(first=self._loop, current=current))

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

    def __init__(
        self,
        *,
        failure_threshold: int = 5,
        reset_timeout: float = 30.0,
        success_threshold: int = 1,
        failure_status_codes: frozenset[int] | None = None,
        _now: Callable[[], float] = time.monotonic,
    ) -> None:
        self._state = _CircuitBreakerState(
            failure_threshold=failure_threshold,
            reset_timeout=reset_timeout,
            success_threshold=success_threshold,
            failure_status_codes=failure_status_codes,
            now=_now,
        )
        self._lock = threading.Lock()

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

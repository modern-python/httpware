"""AsyncRetry + Retry middleware — automatic retry of transient failures with budget control.

See architecture/resilience.md (Retry + RetryBudget section) for the full contract.

Status-code retry: the client terminal raises StatusError subclasses on 4xx/5xx,
so the retry middleware catches StatusError and inspects exc.response.status_code. The
original StatusError subclass is re-raised unwrapped on exhaustion, with a PEP 678 note
added.

The decision logic lives in the lock-free, stateless _RetryPolicy, shared by both
wrappers (mirroring _CircuitBreakerState). AsyncRetry and Retry are thin loop drivers:
they own the attempt loop, the terminal call, and the sleep, and differ only in
``await next`` vs ``next`` and ``asyncio.sleep`` vs ``time.sleep``. _RetryPolicy holds
the immutable config plus the shared RetryBudget; per-attempt state stays as wrapper
locals, so a single instance is safe across the concurrent requests it serves.
"""

import asyncio
import datetime
import email.utils
import logging
import time
from collections.abc import Awaitable, Callable
from http import HTTPStatus

import httpx2

from httpware._internal.observability import _emit_event
from httpware._internal.status import STREAMING_BODY_MARKER
from httpware.errors import NetworkError, RetryBudgetExhaustedError, StatusError, TimeoutError  # noqa: A004
from httpware.middleware import AsyncNext, Next
from httpware.middleware.resilience._backoff import full_jitter_delay
from httpware.middleware.resilience.budget import RetryBudget


DEFAULT_RETRY_STATUS_CODES = frozenset(
    {
        int(HTTPStatus.REQUEST_TIMEOUT),
        int(HTTPStatus.TOO_MANY_REQUESTS),
        int(HTTPStatus.BAD_GATEWAY),
        int(HTTPStatus.SERVICE_UNAVAILABLE),
        int(HTTPStatus.GATEWAY_TIMEOUT),
    }
)

DEFAULT_IDEMPOTENT_METHODS = frozenset(
    {
        "GET",
        "HEAD",
        "OPTIONS",
        "PUT",
        "DELETE",
    }
)

# Catch surface for both wrappers. Narrow by design: anything not in this tuple
# (e.g. httpx2.InvalidURL, programming errors) propagates untouched.
_RETRYABLE_EXCEPTIONS = (StatusError, NetworkError, TimeoutError)

_MAX_ATTEMPTS_INVALID = "max_attempts must be >= 1"
_STREAMING_BODY_REFUSAL_NOTE = "httpware: not retrying — request body is a stream that cannot replay across attempts"
_RETRY_AFTER_EXCEEDS_MAX_DELAY_NOTE = (
    "httpware: Retry-After ({retry_after}s) exceeded max_delay ({max_delay}s); giving up"
)

_LOGGER = logging.getLogger("httpware.retry")


def _parse_retry_after(value: str) -> float | None:
    """Parse a Retry-After header value. Returns None on malformed input."""
    try:
        return max(0.0, float(int(value)))  # clamp: negative integers are malformed servers
    except (ValueError, OverflowError):
        pass
    try:
        parsed = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if parsed is None:  # pragma: no cover — parsedate_to_datetime raises rather than returning None in CPython 3.11+
        return None
    now = datetime.datetime.now(datetime.UTC)
    delta = (parsed - now).total_seconds()
    return max(0.0, delta)


class _RetryPolicy:
    """Stateless retry decision module shared by AsyncRetry + Retry.

    Holds the immutable retry config plus the shared RetryBudget and nothing
    per-call mutable, so a single instance is safe across concurrent requests.
    ``decide`` is synchronous and does the whole decision: it returns the delay
    to sleep before the next attempt, or raises the terminal exception (having
    added the PEP 678 note and emitted the event). It is invoked from inside the
    wrapper's ``except`` block, so exception chaining behaves as a direct raise.
    """

    def __init__(  # noqa: PLR0913 — retry policy has many orthogonal knobs; a dataclass would be worse
        self,
        *,
        max_attempts: int,
        base_delay: float,
        max_delay: float,
        retry_status_codes: frozenset[int],
        retry_methods: frozenset[str],
        respect_retry_after: bool,
        budget: RetryBudget | None,
    ) -> None:
        if max_attempts < 1:
            raise ValueError(_MAX_ATTEMPTS_INVALID)
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.retry_status_codes = retry_status_codes
        self.retry_methods = retry_methods
        self.respect_retry_after = respect_retry_after
        self.budget = budget if budget is not None else RetryBudget()

    def decide(  # noqa: C901 — complexity budget: classification + streaming-body refusal + exhaustion + Retry-After branch + budget gate + backoff
        self,
        *,
        attempt: int,
        request: httpx2.Request,
        exc: BaseException,
    ) -> float:
        """Decide the next action after a retryable failure on `attempt`.

        Returns the delay to sleep before retrying, or raises the terminal
        exception. `exc` is the currently-handled exception (one of
        _RETRYABLE_EXCEPTIONS); see the class docstring for chaining semantics.
        """
        method_eligible = request.method.upper() in self.retry_methods
        if isinstance(exc, StatusError):
            retryable_status = exc.response.status_code in self.retry_status_codes
            if not method_eligible or not retryable_status:
                raise exc
            last_response: httpx2.Response | None = exc.response
        else:  # NetworkError | TimeoutError
            if not method_eligible:
                raise exc
            last_response = None

        # ---- retryable failure path
        if request.extensions.get(STREAMING_BODY_MARKER):
            exc.add_note(_STREAMING_BODY_REFUSAL_NOTE)
            _emit_event(
                _LOGGER,
                "retry.streaming_refused",
                level=logging.WARNING,
                message="retry refused — request body is a stream that cannot replay",
                attributes={
                    "method": request.method,
                    "url": str(request.url),
                    "last_exception_type": type(exc).__qualname__,
                },
            )
            raise exc

        if attempt + 1 >= self.max_attempts:
            exc.add_note(f"httpware: gave up after {attempt + 1} attempts")
            _emit_event(
                _LOGGER,
                "retry.giving_up",
                level=logging.WARNING,
                message=f"retry gave up after {attempt + 1} attempts",
                attributes={
                    "attempts": attempt + 1,
                    "method": request.method,
                    "url": str(request.url),
                    "last_status": last_response.status_code if last_response is not None else None,
                    "last_exception_type": type(exc).__qualname__,
                },
            )
            raise exc

        retry_after: float | None = None
        if self.respect_retry_after and last_response is not None:
            header = last_response.headers.get("Retry-After")
            if header is not None:
                retry_after = _parse_retry_after(header)

        if retry_after is not None and retry_after > self.max_delay:
            exc.add_note(
                _RETRY_AFTER_EXCEEDS_MAX_DELAY_NOTE.format(
                    retry_after=retry_after,
                    max_delay=self.max_delay,
                ),
            )
            raise exc

        if not self.budget.try_withdraw():
            _emit_event(
                _LOGGER,
                "retry.budget_refused",
                level=logging.WARNING,
                message=f"retry budget refused after {attempt + 1} attempts",
                attributes={
                    "attempts": attempt + 1,
                    "method": request.method,
                    "url": str(request.url),
                    "last_status": last_response.status_code if last_response is not None else None,
                },
            )
            raise RetryBudgetExhaustedError(
                last_response=last_response,
                last_exception=exc,
                attempts=attempt + 1,
            ) from exc

        if retry_after is not None:
            return retry_after
        return full_jitter_delay(
            attempt,
            base_delay=self.base_delay,
            max_delay=self.max_delay,
        )


class AsyncRetry:
    """Async retry middleware. See the module docstring for the default policy."""

    def __init__(  # noqa: PLR0913 — retry policy has many orthogonal knobs; a dataclass would be worse
        self,
        *,
        max_attempts: int = 3,
        base_delay: float = 0.1,
        max_delay: float = 5.0,
        retry_status_codes: frozenset[int] = DEFAULT_RETRY_STATUS_CODES,
        retry_methods: frozenset[str] = DEFAULT_IDEMPOTENT_METHODS,
        respect_retry_after: bool = True,
        budget: RetryBudget | None = None,
        _sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._policy = _RetryPolicy(
            max_attempts=max_attempts,
            base_delay=base_delay,
            max_delay=max_delay,
            retry_status_codes=retry_status_codes,
            retry_methods=retry_methods,
            respect_retry_after=respect_retry_after,
            budget=budget,
        )
        self.budget = self._policy.budget
        self._sleep = _sleep

    async def __call__(self, request: httpx2.Request, next: AsyncNext) -> httpx2.Response:  # noqa: A002
        """Process a request through the retry loop. See module docstring."""
        self.budget.deposit()
        for attempt in range(self._policy.max_attempts):
            try:
                return await next(request)
            except _RETRYABLE_EXCEPTIONS as exc:
                delay = self._policy.decide(attempt=attempt, request=request, exc=exc)
            await self._sleep(delay)

        msg = "unreachable"  # pragma: no cover
        raise AssertionError(msg)  # pragma: no cover


class Retry:
    """Sync retry middleware. Mirror of AsyncRetry; uses time.sleep instead of asyncio.sleep."""

    def __init__(  # noqa: PLR0913 — retry policy has many orthogonal knobs; a dataclass would be worse
        self,
        *,
        max_attempts: int = 3,
        base_delay: float = 0.1,
        max_delay: float = 5.0,
        retry_status_codes: frozenset[int] = DEFAULT_RETRY_STATUS_CODES,
        retry_methods: frozenset[str] = DEFAULT_IDEMPOTENT_METHODS,
        respect_retry_after: bool = True,
        budget: RetryBudget | None = None,
        _sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._policy = _RetryPolicy(
            max_attempts=max_attempts,
            base_delay=base_delay,
            max_delay=max_delay,
            retry_status_codes=retry_status_codes,
            retry_methods=retry_methods,
            respect_retry_after=respect_retry_after,
            budget=budget,
        )
        self.budget = self._policy.budget
        self._sleep = _sleep

    def __call__(self, request: httpx2.Request, next: Next) -> httpx2.Response:  # noqa: A002
        """Process a request through the sync retry loop. See AsyncRetry for full contract."""
        self.budget.deposit()
        for attempt in range(self._policy.max_attempts):
            try:
                return next(request)
            except _RETRYABLE_EXCEPTIONS as exc:
                delay = self._policy.decide(attempt=attempt, request=request, exc=exc)
            self._sleep(delay)

        msg = "unreachable"  # pragma: no cover
        raise AssertionError(msg)  # pragma: no cover

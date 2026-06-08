"""AsyncRetry middleware — automatic retry of transient failures with budget control.

See planning/specs/2026-06-05-retry-and-retry-budget-design.md for the full contract.

Status-code retry: the AsyncClient terminal raises StatusError subclasses on 4xx/5xx,
so AsyncRetry catches StatusError and inspects exc.response.status_code. The original
StatusError subclass is re-raised unwrapped on exhaustion, with a PEP 678 note added.
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
    except ValueError:
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


class AsyncRetry:
    """Async retry middleware. See module docstring for default policy."""

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
        if max_attempts < 1:
            raise ValueError(_MAX_ATTEMPTS_INVALID)
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.retry_status_codes = retry_status_codes
        self.retry_methods = retry_methods
        self.respect_retry_after = respect_retry_after
        self.budget = budget if budget is not None else RetryBudget()
        self._sleep = _sleep

    async def __call__(self, request: httpx2.Request, next: AsyncNext) -> httpx2.Response:  # noqa: A002, C901, PLR0912, PLR0915 — complexity budget: 3 error clauses + idempotency gate + streaming-body refusal + budget gate + Retry-After branch + backoff
        """Process a request through the retry loop. See module docstring."""
        method_eligible = request.method.upper() in self.retry_methods
        last_exc: BaseException | None = None
        last_response: httpx2.Response | None = None

        self.budget.deposit()
        for attempt in range(self.max_attempts):
            is_last = attempt + 1 >= self.max_attempts
            try:
                return await next(request)
            except StatusError as exc:
                retryable_status = exc.response.status_code in self.retry_status_codes
                if not method_eligible or not retryable_status:
                    raise
                last_exc = exc
                last_response = exc.response
            except (NetworkError, TimeoutError) as exc:
                if not method_eligible:
                    raise
                last_exc = exc
                last_response = None

            # ---- retryable failure path
            if request.extensions.get(STREAMING_BODY_MARKER):
                if last_exc is None:  # pragma: no cover — invariant from except branch
                    msg = "AsyncRetry: streaming-body refusal reached with no last_exc"
                    raise AssertionError(msg)
                last_exc.add_note(_STREAMING_BODY_REFUSAL_NOTE)
                _emit_event(
                    _LOGGER,
                    "retry.streaming_refused",
                    level=logging.WARNING,
                    message="retry refused — request body is a stream that cannot replay",
                    attributes={
                        "method": request.method,
                        "url": str(request.url),
                        "last_exception_type": type(last_exc).__qualname__,
                    },
                )
                raise last_exc

            if is_last:
                if last_exc is None:  # pragma: no cover — structural invariant from except branch
                    msg = "AsyncRetry: last_exc unset on final attempt — unreachable"
                    raise AssertionError(msg)
                last_exc.add_note(f"httpware: gave up after {attempt + 1} attempts")
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
                        "last_exception_type": type(last_exc).__qualname__,
                    },
                )
                raise last_exc

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
                    last_exception=last_exc,
                    attempts=attempt + 1,
                ) from last_exc

            retry_after: float | None = None
            if self.respect_retry_after and last_response is not None:
                header = last_response.headers.get("Retry-After")
                if header is not None:
                    retry_after = _parse_retry_after(header)

            if retry_after is not None and retry_after > self.max_delay:
                if last_exc is None:  # pragma: no cover — retry_after requires last_response which requires last_exc
                    msg = "AsyncRetry: retry_after path reached with no last_exc"
                    raise AssertionError(msg)
                last_exc.add_note(
                    _RETRY_AFTER_EXCEEDS_MAX_DELAY_NOTE.format(
                        retry_after=retry_after,
                        max_delay=self.max_delay,
                    ),
                )
                raise last_exc
            if retry_after is not None:
                delay = retry_after
            else:
                delay = full_jitter_delay(
                    attempt,
                    base_delay=self.base_delay,
                    max_delay=self.max_delay,
                )
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
        if max_attempts < 1:
            raise ValueError(_MAX_ATTEMPTS_INVALID)
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.retry_status_codes = retry_status_codes
        self.retry_methods = retry_methods
        self.respect_retry_after = respect_retry_after
        self.budget = budget if budget is not None else RetryBudget()
        self._sleep = _sleep

    def __call__(self, request: httpx2.Request, next: Next) -> httpx2.Response:  # noqa: A002, C901, PLR0912, PLR0915 — same complexity rationale as AsyncRetry
        """Process a request through the sync retry loop. See AsyncRetry for full contract."""
        method_eligible = request.method.upper() in self.retry_methods
        last_exc: BaseException | None = None
        last_response: httpx2.Response | None = None

        self.budget.deposit()
        for attempt in range(self.max_attempts):
            is_last = attempt + 1 >= self.max_attempts
            try:
                return next(request)
            except StatusError as exc:
                retryable_status = exc.response.status_code in self.retry_status_codes
                if not method_eligible or not retryable_status:
                    raise
                last_exc = exc
                last_response = exc.response
            except (NetworkError, TimeoutError) as exc:
                if not method_eligible:
                    raise
                last_exc = exc
                last_response = None

            # ---- retryable failure path
            if request.extensions.get(STREAMING_BODY_MARKER):
                if last_exc is None:  # pragma: no cover — invariant from except branch
                    msg = "Retry: streaming-body refusal reached with no last_exc"
                    raise AssertionError(msg)
                last_exc.add_note(_STREAMING_BODY_REFUSAL_NOTE)
                _emit_event(
                    _LOGGER,
                    "retry.streaming_refused",
                    level=logging.WARNING,
                    message="retry refused — request body is a stream that cannot replay",
                    attributes={
                        "method": request.method,
                        "url": str(request.url),
                        "last_exception_type": type(last_exc).__qualname__,
                    },
                )
                raise last_exc

            if is_last:
                if last_exc is None:  # pragma: no cover — structural invariant from except branch
                    msg = "Retry: last_exc unset on final attempt — unreachable"
                    raise AssertionError(msg)
                last_exc.add_note(f"httpware: gave up after {attempt + 1} attempts")
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
                        "last_exception_type": type(last_exc).__qualname__,
                    },
                )
                raise last_exc

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
                    last_exception=last_exc,
                    attempts=attempt + 1,
                ) from last_exc

            retry_after: float | None = None
            if self.respect_retry_after and last_response is not None:
                header = last_response.headers.get("Retry-After")
                if header is not None:
                    retry_after = _parse_retry_after(header)

            if retry_after is not None and retry_after > self.max_delay:
                if last_exc is None:  # pragma: no cover — retry_after requires last_response which requires last_exc
                    msg = "Retry: retry_after path reached with no last_exc"
                    raise AssertionError(msg)
                last_exc.add_note(
                    _RETRY_AFTER_EXCEEDS_MAX_DELAY_NOTE.format(
                        retry_after=retry_after,
                        max_delay=self.max_delay,
                    ),
                )
                raise last_exc
            if retry_after is not None:
                delay = retry_after
            else:
                delay = full_jitter_delay(
                    attempt,
                    base_delay=self.base_delay,
                    max_delay=self.max_delay,
                )
            self._sleep(delay)

        msg = "unreachable"  # pragma: no cover
        raise AssertionError(msg)  # pragma: no cover

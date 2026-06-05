"""Retry middleware — automatic retry of transient failures with budget control.

See planning/specs/2026-06-05-retry-and-retry-budget-design.md for the full contract.

Status-code retry: the AsyncClient terminal raises StatusError subclasses on 4xx/5xx,
so Retry catches StatusError and inspects exc.response.status_code. The original
StatusError subclass is re-raised unwrapped on exhaustion, with a PEP 678 note added.
"""

import asyncio
import builtins
import datetime
import email.utils
from collections.abc import Awaitable, Callable
from http import HTTPStatus

import httpx2

from httpware.errors import NetworkError, RetryBudgetExhaustedError, StatusError, TimeoutError  # noqa: A004
from httpware.middleware import Next
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


class Retry:
    """Retry middleware. See module docstring for default policy."""

    def __init__(  # noqa: PLR0913 — retry policy has many orthogonal knobs; a dataclass would be worse
        self,
        *,
        max_attempts: int = 3,
        base_delay: float = 0.1,
        max_delay: float = 5.0,
        attempt_timeout: float | None = None,
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
        self.attempt_timeout = attempt_timeout
        self.retry_status_codes = retry_status_codes
        self.retry_methods = retry_methods
        self.respect_retry_after = respect_retry_after
        self.budget = budget if budget is not None else RetryBudget()
        self._sleep = _sleep

    async def __call__(self, request: httpx2.Request, next: Next) -> httpx2.Response:  # noqa: A002, C901, PLR0912, PLR0915 — complexity budget: 3 error clauses + idempotency gate + streaming-body refusal + budget gate + Retry-After branch + backoff
        """Process a request through the retry loop. See module docstring."""
        method_eligible = request.method.upper() in self.retry_methods
        last_exc: BaseException | None = None
        last_response: httpx2.Response | None = None

        for attempt in range(self.max_attempts):
            is_last = attempt + 1 >= self.max_attempts
            self.budget.deposit()
            try:
                if self.attempt_timeout is not None:
                    async with asyncio.timeout(self.attempt_timeout):
                        return await next(request)
                else:
                    return await next(request)
            except StatusError as exc:
                retryable_status = exc.response.status_code in self.retry_status_codes
                if not method_eligible or not retryable_status:
                    if retryable_status and request.extensions.get("httpware.streaming_body"):
                        exc.add_note(
                            "httpware: not retrying — request body is a stream that cannot replay across attempts"
                        )
                    raise
                last_exc = exc
                last_response = exc.response
            except (NetworkError, TimeoutError) as exc:
                if not method_eligible:
                    if request.extensions.get("httpware.streaming_body"):
                        exc.add_note(
                            "httpware: not retrying — request body is a stream that cannot replay across attempts"
                        )
                    raise
                last_exc = exc
                last_response = None
            except builtins.TimeoutError as exc:
                wrapped = TimeoutError("attempt timed out")
                wrapped.__cause__ = exc  # set now; the retry path (last_exc = wrapped) has no `from` clause
                if not method_eligible:
                    if request.extensions.get("httpware.streaming_body"):
                        wrapped.add_note(
                            "httpware: not retrying — request body is a stream that cannot replay across attempts"
                        )
                    raise wrapped from exc
                last_exc = wrapped
                last_response = None

            # ---- retryable failure path
            if request.extensions.get("httpware.streaming_body"):
                if last_exc is None:  # pragma: no cover — invariant from except branch
                    msg = "Retry: streaming-body refusal reached with no last_exc"
                    raise AssertionError(msg)
                last_exc.add_note(
                    "httpware: not retrying — request body is a stream that cannot replay across attempts"
                )
                raise last_exc

            if is_last:
                if last_exc is None:  # pragma: no cover — structural invariant from except branch
                    msg = "Retry: last_exc unset on final attempt — unreachable"
                    raise AssertionError(msg)
                last_exc.add_note(f"httpware: gave up after {attempt + 1} attempts")
                raise last_exc

            if not self.budget.try_withdraw():
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

            if retry_after is not None:
                delay = min(retry_after, self.max_delay)
            else:
                delay = full_jitter_delay(
                    attempt,
                    base_delay=self.base_delay,
                    max_delay=self.max_delay,
                )
            await self._sleep(delay)

        msg = "unreachable"  # pragma: no cover
        raise AssertionError(msg)  # pragma: no cover

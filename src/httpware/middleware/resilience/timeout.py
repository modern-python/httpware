"""AsyncTimeout middleware — overall wall-clock deadline across the inner pipeline.

This is NOT a per-call timeout — httpx2's connect/read/write/pool timeouts are the
right tool for bounding a single outbound call, and AsyncTimeout does not duplicate
them. What httpx2 cannot bound is the total wall-clock across the whole middleware
pipeline (most importantly across an AsyncRetry loop, whose attempts and backoff
sleeps it knows nothing about). Place AsyncTimeout outermost to enforce
"this whole operation must finish within `timeout` seconds, even across retries."

Async-only by design: a sync total-deadline cannot interrupt a blocking httpx2 call
mid-flight (sync Python has no cancellation), and httpx2 already covers sync per-call
timeouts. Sync callers configure httpx2's timeouts directly; there is no sync Timeout.
"""

import asyncio
import logging
import math

import httpx2

from httpware._internal.observability import _emit_event, _observed_url
from httpware.errors import TimeoutError as HttpwareTimeoutError
from httpware.middleware import AsyncNext


_TIMEOUT_INVALID = "timeout must be a finite number > 0"

_LOGGER = logging.getLogger("httpware.timeout")


class AsyncTimeout:
    """Bounds total wall-clock time spent in the inner pipeline.

    Parameters
    ----------
    timeout
        Required. Overall deadline in seconds for ``next(request)`` to complete,
        including everything it wraps (retries, backoff sleeps, the call itself).
        Must be ``> 0``. On expiry the middleware raises ``httpware.TimeoutError``.

    Place outermost in the chain for an overall-operation deadline. For bounding a
    single outbound call (connect/read/write/pool), configure ``httpx2`` instead.

    """

    def __init__(self, *, timeout: float) -> None:
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError(_TIMEOUT_INVALID)
        self._timeout = timeout

    async def __call__(self, request: httpx2.Request, next: AsyncNext) -> httpx2.Response:  # noqa: A002
        """Invoke next under an asyncio.timeout; raise httpware.TimeoutError on expiry.

        Only a deadline THIS middleware imposed is re-wrapped: ``cm.expired()``
        distinguishes our own expiry from an inner ``TimeoutError`` (e.g. an httpx2
        per-call timeout surfacing through a retry), which propagates unchanged.
        """
        try:
            async with asyncio.timeout(self._timeout) as cm:
                return await next(request)
        except TimeoutError as exc:
            if not cm.expired():
                raise  # inner TimeoutError, not our deadline — leave it untouched
            _emit_event(
                _LOGGER,
                "timeout.exceeded",
                level=logging.WARNING,
                message="overall timeout exceeded",
                attributes={
                    "timeout": self._timeout,
                    "method": request.method,
                    "url": _observed_url(request),
                },
            )
            msg = f"overall timeout of {self._timeout}s exceeded"
            raise HttpwareTimeoutError(msg) from exc

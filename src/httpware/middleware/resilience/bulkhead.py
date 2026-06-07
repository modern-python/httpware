"""AsyncBulkhead middleware — concurrency limiter via asyncio.Semaphore.

See planning/specs/2026-06-05-bulkhead-design.md for the contract.

The middleware owns an asyncio.Semaphore(max_concurrent). On each request,
it acquires a slot (bounded by acquire_timeout via asyncio.timeout) and
releases the slot in a try/finally so success, exceptions, and cancellation
all release deterministically.

AsyncBulkhead is the sharable unit — pass the same instance to multiple
AsyncClient(middleware=[shared]) calls to enforce a joint cap across clients.
"""

import asyncio
import logging

import httpx2

from httpware._internal.observability import _emit_event
from httpware.errors import BulkheadFullError
from httpware.middleware import AsyncNext


_MAX_CONCURRENT_INVALID = "max_concurrent must be >= 1"
_ACQUIRE_TIMEOUT_INVALID = "acquire_timeout must be >= 0"

_LOGGER = logging.getLogger("httpware.bulkhead")


class AsyncBulkhead:
    """Async concurrency limiter middleware backed by ``asyncio.Semaphore``.

    Parameters
    ----------
    max_concurrent
        Required. Maximum number of in-flight requests this AsyncBulkhead permits.
        Must be ``>= 1``. There is no default because no value is universally
        correct — the right cap depends on downstream capacity and SLA.
    acquire_timeout
        Seconds to wait for a slot before raising ``BulkheadFullError``.
        Defaults to ``1.0``. ``None`` waits forever; ``0`` fails fast. Must be
        ``>= 0`` (or ``None``).

    See the module docstring for the algorithm and middleware-ordering guidance.

    """

    def __init__(
        self,
        *,
        max_concurrent: int,
        acquire_timeout: float | None = 1.0,
    ) -> None:
        if max_concurrent < 1:
            raise ValueError(_MAX_CONCURRENT_INVALID)
        if acquire_timeout is not None and acquire_timeout < 0:
            raise ValueError(_ACQUIRE_TIMEOUT_INVALID)
        self._max_concurrent = max_concurrent
        self._acquire_timeout = acquire_timeout
        self._sem = asyncio.Semaphore(max_concurrent)

    async def __call__(self, request: httpx2.Request, next: AsyncNext) -> httpx2.Response:  # noqa: A002
        """Acquire a slot (bounded by acquire_timeout), invoke next, release."""
        try:
            if self._acquire_timeout is None:
                await self._sem.acquire()
            else:
                async with asyncio.timeout(self._acquire_timeout):
                    await self._sem.acquire()
        except TimeoutError as exc:
            _emit_event(
                _LOGGER,
                "bulkhead.rejected",
                level=logging.WARNING,
                message="bulkhead rejected request — acquire_timeout exceeded",
                attributes={
                    "max_concurrent": self._max_concurrent,
                    "acquire_timeout": self._acquire_timeout,
                    "method": request.method,
                    "url": str(request.url),
                },
            )
            raise BulkheadFullError(
                max_concurrent=self._max_concurrent,
                acquire_timeout=self._acquire_timeout,
            ) from exc

        try:
            return await next(request)
        finally:
            self._sem.release()

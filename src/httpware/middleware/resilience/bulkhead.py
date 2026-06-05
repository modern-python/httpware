"""Bulkhead middleware — concurrency limiter via asyncio.Semaphore.

See planning/specs/2026-06-05-bulkhead-design.md for the contract.

The middleware owns an asyncio.Semaphore(max_concurrent). On each request,
it acquires a slot (bounded by acquire_timeout via asyncio.timeout) and
releases the slot in a try/finally so success, exceptions, and cancellation
all release deterministically.

Bulkhead is the sharable unit — pass the same instance to multiple
AsyncClient(middleware=[shared]) calls to enforce a joint cap across clients.
"""

import asyncio

import httpx2

from httpware.errors import BulkheadFullError
from httpware.middleware import Next


_MAX_CONCURRENT_INVALID = "max_concurrent must be >= 1"
_ACQUIRE_TIMEOUT_INVALID = "acquire_timeout must be >= 0"


class Bulkhead:
    """Concurrency limiter middleware. See module docstring for behavior."""

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

    async def __call__(self, request: httpx2.Request, next: Next) -> httpx2.Response:  # noqa: A002
        """Acquire a slot (bounded by acquire_timeout), invoke next, release."""
        try:
            if self._acquire_timeout is None:
                await self._sem.acquire()
            else:
                async with asyncio.timeout(self._acquire_timeout):
                    await self._sem.acquire()
        except TimeoutError as exc:
            raise BulkheadFullError(
                max_concurrent=self._max_concurrent,
                acquire_timeout=self._acquire_timeout,
            ) from exc

        try:
            return await next(request)
        finally:
            self._sem.release()

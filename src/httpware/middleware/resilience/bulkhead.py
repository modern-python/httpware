"""AsyncBulkhead middleware — concurrency limiter via asyncio.Semaphore.

See architecture/resilience.md (Bulkhead section) for the contract.

The middleware owns an asyncio.Semaphore(max_concurrent). On each request,
it acquires a slot (bounded by acquire_timeout via asyncio.timeout) and
releases the slot in a try/finally so success, exceptions, and cancellation
all release deterministically.

AsyncBulkhead is the sharable unit — pass the same instance to multiple
AsyncClient(middleware=[shared]) calls to enforce a joint cap across clients.

AsyncBulkhead is single-event-loop: the underlying asyncio.Semaphore binds
to whichever loop first awaits it, and cross-loop wake-ups are not thread
safe. A single instance acquired from a second event loop (e.g. another
thread running asyncio.run) raises RuntimeError on entry rather than
deadlocking silently. To cap a sync+async or cross-thread workload, use
a Bulkhead and an AsyncBulkhead with matching max_concurrent.
"""

import asyncio
import logging
import threading

import httpx2

from httpware._internal.observability import _emit_event
from httpware.errors import BulkheadFullError
from httpware.middleware import AsyncNext, Next


_MAX_CONCURRENT_INVALID = "max_concurrent must be >= 1"
_ACQUIRE_TIMEOUT_INVALID = "acquire_timeout must be >= 0"
_ASYNCBULKHEAD_CROSS_LOOP_MSG = (
    "AsyncBulkhead is bound to a single event loop. First seen on {first!r}; "
    "current request is on {current!r}. Use one AsyncBulkhead per loop; "
    "cross-thread sharing requires the sync Bulkhead primitive."
)

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

    See the module docstring for the algorithm, middleware-ordering guidance,
    and the single-event-loop constraint.

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
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_lock = threading.Lock()

    def _check_loop(self) -> None:
        current = asyncio.get_running_loop()
        cached = self._loop
        if cached is current:
            return
        if cached is not None:
            raise RuntimeError(
                _ASYNCBULKHEAD_CROSS_LOOP_MSG.format(first=cached, current=current),
            )
        with self._loop_lock:
            if self._loop is None:
                self._loop = current
            # pragma below: inner double-check-with-lock race arm; only
            # reachable when two threads simultaneously pass the outer
            # cached-loop check, which single-threaded tests can't trigger.
            elif self._loop is not current:  # pragma: no cover
                raise RuntimeError(
                    _ASYNCBULKHEAD_CROSS_LOOP_MSG.format(first=self._loop, current=current),
                )

    async def __call__(self, request: httpx2.Request, next: AsyncNext) -> httpx2.Response:  # noqa: A002
        """Acquire a slot (bounded by acquire_timeout), invoke next, release."""
        self._check_loop()
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


class Bulkhead:
    """Sync concurrency limiter backed by threading.Semaphore.

    Bulkhead is the sharable unit — pass the same instance to multiple
    Client(middleware=[shared]) calls to enforce a joint cap across clients.

    Bulkhead is per-world: a single instance cannot be shared between a Client
    and an AsyncClient (the underlying semaphore primitives differ). To cap
    a sync+async mixed workload, use a Bulkhead and an AsyncBulkhead with
    matching max_concurrent.
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
        self._sem = threading.Semaphore(max_concurrent)

    def __call__(self, request: httpx2.Request, next: Next) -> httpx2.Response:  # noqa: A002
        """Acquire a slot (bounded by acquire_timeout), invoke next, release."""
        # threading.Semaphore.acquire(timeout=None) blocks until acquired;
        # acquire(timeout=0) returns immediately (True if a slot was available,
        # False otherwise). Both match AsyncBulkhead's contract.
        acquired = self._sem.acquire(timeout=self._acquire_timeout)
        if not acquired:
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
            )

        try:
            return next(request)
        finally:
            self._sem.release()

"""An async resilience middleware binds to its first event loop; a second loop is rejected.

This deterministically exercises the guard's outer cross-loop raise (the reachable arm). The
inner double-checked-lock arm stays `# pragma: no cover`: it needs two threads to bind the loop
simultaneously, which free-threading can reach but only nondeterministically.
"""

import asyncio
from http import HTTPStatus

import httpx2
import pytest

from httpware import AsyncBulkhead, AsyncClient


def _ok(request: httpx2.Request) -> httpx2.Response:
    return httpx2.Response(HTTPStatus.OK, request=request)


async def _drive(bulkhead: AsyncBulkhead) -> None:
    client = AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=httpx2.MockTransport(_ok)),
        middleware=[bulkhead],
    )
    async with client:
        await client.get("https://example.test/x")


def test_async_bulkhead_rejects_second_event_loop() -> None:
    bulkhead = AsyncBulkhead(max_concurrent=2)
    asyncio.run(_drive(bulkhead))  # binds to loop #1
    with pytest.raises(RuntimeError, match="single event loop"):
        asyncio.run(_drive(bulkhead))  # loop #2 -> rejected

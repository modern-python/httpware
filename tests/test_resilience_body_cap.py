"""Resilience interaction with max_response_body_bytes.

ResponseTooLargeError is a non-status ClientError, so it must fall outside the
retry/circuit-breaker failure classifications. These tests lock that behavior so
a future refactor can't silently make a cap trip retryable or breaker-counting.
"""

import httpx2
import pytest

from httpware import AsyncClient, CircuitState, ResponseTooLargeError
from httpware.middleware.resilience.circuit_breaker import AsyncCircuitBreaker
from httpware.middleware.resilience.retry import AsyncRetry


class _CountingHandler:
    """Mock transport that counts calls and always returns the same response."""

    def __init__(self, status: int, body: bytes) -> None:
        self.status = status
        self.body = body
        self.calls = 0

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.calls += 1
        return httpx2.Response(self.status, content=self.body, request=request)


def _client(handler: _CountingHandler, *, middleware: list[object], cap: int) -> AsyncClient:
    return AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
        middleware=middleware,  # ty: ignore[invalid-argument-type]
        max_response_body_bytes=cap,
    )


async def test_response_too_large_is_not_retried() -> None:
    handler = _CountingHandler(200, b"x" * 200)
    client = _client(handler, middleware=[AsyncRetry()], cap=10)
    request = client.build_request("GET", "https://example.test/x")
    with pytest.raises(ResponseTooLargeError):
        await client.send(request)
    assert handler.calls == 1  # not retried — a single terminal attempt
    await client.aclose()


async def test_over_cap_retryable_5xx_surfaces_as_too_large_not_retried() -> None:
    # 503 is retryable, but the cap trips first: cap-wins / fail-hard.
    handler = _CountingHandler(503, b"x" * 200)
    client = _client(handler, middleware=[AsyncRetry()], cap=10)
    request = client.build_request("GET", "https://example.test/x")
    with pytest.raises(ResponseTooLargeError) as caught:
        await client.send(request)
    assert caught.value.status_code == 503  # noqa: PLR2004 — the retryable status, surfaced not retried
    assert handler.calls == 1
    await client.aclose()


async def test_response_too_large_does_not_trip_circuit_breaker() -> None:
    # failure_threshold=1: one real failure would open the circuit; a cap trip must not.
    handler = _CountingHandler(500, b"x" * 200)
    breaker = AsyncCircuitBreaker(failure_threshold=1)
    client = _client(handler, middleware=[breaker], cap=10)
    request = client.build_request("GET", "https://example.test/x")
    for _ in range(3):
        with pytest.raises(ResponseTooLargeError):
            await client.send(request)
    assert breaker.state is CircuitState.CLOSED  # neither success nor failure recorded
    assert handler.calls == 3  # noqa: PLR2004 — breaker never opened, every call reached the transport
    await client.aclose()

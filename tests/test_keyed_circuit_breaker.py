"""Tests for the AsyncKeyedCircuitBreaker middleware.

The per-circuit state machine is covered by test_circuit_breaker.py; these tests pin what keying
adds: which requests share a circuit, which do not, and the key on emitted events.
"""

import asyncio
import logging
from collections.abc import Callable
from http import HTTPStatus

import httpx2
import pytest

from httpware import (
    AsyncClient,
    AsyncKeyedCircuitBreaker,
    AsyncRetry,
    CircuitOpenError,
    InternalServerError,
    NetworkError,
)


_ATTEMPTS = 3


class _Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


class _PerHost:
    """Mock-transport handler: hosts in `failing` answer 500, every other host answers 200."""

    def __init__(self, failing: set[str]) -> None:
        self.failing = failing
        self.calls: list[str] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.calls.append(request.url.host)
        status = HTTPStatus.INTERNAL_SERVER_ERROR if request.url.host in self.failing else HTTPStatus.OK
        return httpx2.Response(status, request=request)


def _client(
    handler: Callable[[httpx2.Request], httpx2.Response],
    *,
    breaker: AsyncKeyedCircuitBreaker,
) -> AsyncClient:
    return AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
        middleware=[breaker],
    )


async def _fail_n(client: AsyncClient, url: str, n: int) -> None:
    for _ in range(n):
        with pytest.raises(InternalServerError):
            await client.get(url)


def test_failure_threshold_below_one_rejected() -> None:
    with pytest.raises(ValueError, match="failure_threshold must be >= 1"):
        AsyncKeyedCircuitBreaker(failure_threshold=0)


async def test_open_circuit_on_one_origin_leaves_another_available() -> None:
    handler = _PerHost(failing={"a.test"})
    async with _client(handler, breaker=AsyncKeyedCircuitBreaker(failure_threshold=2)) as client:
        await _fail_n(client, "https://a.test/x", 2)
        with pytest.raises(CircuitOpenError):
            await client.get("https://a.test/x")
        response = await client.get("https://b.test/x")
    assert response.status_code == HTTPStatus.OK
    assert handler.calls == ["a.test", "a.test", "b.test"]


async def test_requests_to_the_same_origin_share_one_circuit() -> None:
    handler = _PerHost(failing={"a.test"})
    async with _client(handler, breaker=AsyncKeyedCircuitBreaker(failure_threshold=2)) as client:
        await _fail_n(client, "https://a.test/one", 1)
        await _fail_n(client, "https://A.test:443/two?q=1", 1)
        with pytest.raises(CircuitOpenError):
            await client.get("https://a.test/three")


async def test_default_key_separates_scheme_and_port() -> None:
    handler = _PerHost(failing={"a.test"})
    async with _client(handler, breaker=AsyncKeyedCircuitBreaker(failure_threshold=1)) as client:
        await _fail_n(client, "https://a.test/x", 1)
        await _fail_n(client, "http://a.test/x", 1)
        await _fail_n(client, "https://a.test:8443/x", 1)
    assert handler.calls == ["a.test"] * 3


async def test_custom_key_groups_origins() -> None:
    handler = _PerHost(failing={"a.test"})
    breaker = AsyncKeyedCircuitBreaker(failure_threshold=1, key=lambda _: "all")
    async with _client(handler, breaker=breaker) as client:
        await _fail_n(client, "https://a.test/x", 1)
        with pytest.raises(CircuitOpenError):
            await client.get("https://b.test/x")


async def test_each_origin_recovers_through_its_own_half_open_probe() -> None:
    clock = _Clock()
    handler = _PerHost(failing={"a.test", "b.test"})
    breaker = AsyncKeyedCircuitBreaker(failure_threshold=1, reset_timeout=10.0, _now=clock)
    async with _client(handler, breaker=breaker) as client:
        await _fail_n(client, "https://a.test/x", 1)
        clock.t = 5.0
        await _fail_n(client, "https://b.test/x", 1)
        handler.failing = set()
        clock.t = 10.0
        assert (await client.get("https://a.test/x")).status_code == HTTPStatus.OK
        with pytest.raises(CircuitOpenError) as exc_info:
            await client.get("https://b.test/x")
    assert exc_info.value.retry_after == pytest.approx(5.0)


async def test_half_open_probe_slot_is_per_origin() -> None:
    clock = _Clock()
    started = {"a.test": asyncio.Event(), "b.test": asyncio.Event()}
    release = asyncio.Event()

    async def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/fail":
            return httpx2.Response(HTTPStatus.INTERNAL_SERVER_ERROR, request=request)
        started[request.url.host].set()
        await release.wait()
        return httpx2.Response(HTTPStatus.OK, request=request)

    breaker = AsyncKeyedCircuitBreaker(failure_threshold=1, reset_timeout=1.0, _now=clock)
    async with AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
        middleware=[breaker],
    ) as client:
        await _fail_n(client, "https://a.test/fail", 1)
        await _fail_n(client, "https://b.test/fail", 1)
        clock.t = 1.0
        probe_a = asyncio.create_task(client.get("https://a.test/slow"))
        probe_b = asyncio.create_task(client.get("https://b.test/slow"))
        await started["a.test"].wait()
        await started["b.test"].wait()
        with pytest.raises(CircuitOpenError):
            await client.get("https://a.test/slow")
        release.set()
        responses = await asyncio.gather(probe_a, probe_b)
    assert [r.status_code for r in responses] == [HTTPStatus.OK, HTTPStatus.OK]


async def test_outside_retry_counts_one_outcome_per_retry_sequence() -> None:
    handler = _PerHost(failing={"a.test"})
    breaker = AsyncKeyedCircuitBreaker(failure_threshold=2)
    async with AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
        middleware=[breaker, AsyncRetry(max_attempts=_ATTEMPTS, base_delay=0.0, retry_status_codes=frozenset({500}))],
    ) as client:
        await _fail_n(client, "https://a.test/x", 1)
        assert len(handler.calls) == _ATTEMPTS
        await _fail_n(client, "https://a.test/x", 1)
        with pytest.raises(CircuitOpenError):
            await client.get("https://a.test/x")
    assert len(handler.calls) == 2 * _ATTEMPTS


async def test_network_error_counts_against_its_origin_only() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.host == "a.test":
            msg = "refused"
            raise httpx2.ConnectError(msg, request=request)
        return httpx2.Response(HTTPStatus.OK, request=request)

    async with _client(handler, breaker=AsyncKeyedCircuitBreaker(failure_threshold=1)) as client:
        with pytest.raises(NetworkError):
            await client.get("https://a.test/x")
        with pytest.raises(CircuitOpenError):
            await client.get("https://a.test/x")
        assert (await client.get("https://b.test/x")).status_code == HTTPStatus.OK


async def test_events_carry_the_circuit_key(caplog: pytest.LogCaptureFixture) -> None:
    handler = _PerHost(failing={"a.test"})
    async with _client(handler, breaker=AsyncKeyedCircuitBreaker(failure_threshold=1)) as client:
        with caplog.at_level(logging.WARNING, logger="httpware.circuit_breaker"):
            await _fail_n(client, "https://a.test/x", 1)
            with pytest.raises(CircuitOpenError):
                await client.get("https://a.test/x")
    records = [r for r in caplog.records if r.name == "httpware.circuit_breaker"]
    assert [r.event for r in records] == ["circuit.opened", "circuit.rejected"]  # ty: ignore[unresolved-attribute]
    expected = str(httpx2.URL("https://a.test").origin)
    assert all(r.circuit_key == expected for r in records)  # ty: ignore[unresolved-attribute]


def test_cross_loop_use_raises_runtimeerror() -> None:
    breaker = AsyncKeyedCircuitBreaker()
    handler = _PerHost(failing=set())

    async def _run_once(url: str) -> None:
        async with _client(handler, breaker=breaker) as client:
            await client.get(url)

    asyncio.run(_run_once("https://a.test/x"))
    with pytest.raises(RuntimeError, match="AsyncKeyedCircuitBreaker is bound to a single event loop"):
        asyncio.run(_run_once("https://b.test/x"))

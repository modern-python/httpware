"""Tests for the sync KeyedCircuitBreaker middleware. Mirror of test_keyed_circuit_breaker.py."""

import logging
import threading
from collections.abc import Callable
from http import HTTPStatus

import httpx2
import pytest

from httpware import (
    CircuitOpenError,
    Client,
    InternalServerError,
    KeyedCircuitBreaker,
    NetworkError,
    Retry,
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


def _client(handler: Callable[[httpx2.Request], httpx2.Response], *, breaker: KeyedCircuitBreaker) -> Client:
    return Client(
        httpx2_client=httpx2.Client(transport=httpx2.MockTransport(handler)),
        middleware=[breaker],
    )


def _fail_n(client: Client, url: str, n: int) -> None:
    for _ in range(n):
        with pytest.raises(InternalServerError):
            client.get(url)


def test_failure_threshold_below_one_rejected() -> None:
    with pytest.raises(ValueError, match="failure_threshold must be >= 1"):
        KeyedCircuitBreaker(failure_threshold=0)


def test_open_circuit_on_one_origin_leaves_another_available() -> None:
    handler = _PerHost(failing={"a.test"})
    with _client(handler, breaker=KeyedCircuitBreaker(failure_threshold=2)) as client:
        _fail_n(client, "https://a.test/x", 2)
        with pytest.raises(CircuitOpenError):
            client.get("https://a.test/x")
        response = client.get("https://b.test/x")
    assert response.status_code == HTTPStatus.OK
    assert handler.calls == ["a.test", "a.test", "b.test"]


def test_requests_to_the_same_origin_share_one_circuit() -> None:
    handler = _PerHost(failing={"a.test"})
    with _client(handler, breaker=KeyedCircuitBreaker(failure_threshold=2)) as client:
        _fail_n(client, "https://a.test/one", 1)
        _fail_n(client, "https://A.test:443/two?q=1", 1)
        with pytest.raises(CircuitOpenError):
            client.get("https://a.test/three")


def test_default_key_separates_scheme_and_port() -> None:
    handler = _PerHost(failing={"a.test"})
    with _client(handler, breaker=KeyedCircuitBreaker(failure_threshold=1)) as client:
        _fail_n(client, "https://a.test/x", 1)
        _fail_n(client, "http://a.test/x", 1)
        _fail_n(client, "https://a.test:8443/x", 1)
    assert handler.calls == ["a.test"] * 3


def test_custom_key_groups_origins() -> None:
    handler = _PerHost(failing={"a.test"})
    breaker = KeyedCircuitBreaker(failure_threshold=1, key=lambda _: "all")
    with _client(handler, breaker=breaker) as client:
        _fail_n(client, "https://a.test/x", 1)
        with pytest.raises(CircuitOpenError):
            client.get("https://b.test/x")


def test_each_origin_recovers_through_its_own_half_open_probe() -> None:
    clock = _Clock()
    handler = _PerHost(failing={"a.test", "b.test"})
    breaker = KeyedCircuitBreaker(failure_threshold=1, reset_timeout=10.0, _now=clock)
    with _client(handler, breaker=breaker) as client:
        _fail_n(client, "https://a.test/x", 1)
        clock.t = 5.0
        _fail_n(client, "https://b.test/x", 1)
        handler.failing = set()
        clock.t = 10.0
        assert client.get("https://a.test/x").status_code == HTTPStatus.OK
        with pytest.raises(CircuitOpenError) as exc_info:
            client.get("https://b.test/x")
    assert exc_info.value.retry_after == pytest.approx(5.0)


def test_half_open_probe_slot_is_per_origin() -> None:
    clock = _Clock()
    started = {"a.test": threading.Event(), "b.test": threading.Event()}
    release = threading.Event()

    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/fail":
            return httpx2.Response(HTTPStatus.INTERNAL_SERVER_ERROR, request=request)
        started[request.url.host].set()
        release.wait()
        return httpx2.Response(HTTPStatus.OK, request=request)

    breaker = KeyedCircuitBreaker(failure_threshold=1, reset_timeout=1.0, _now=clock)
    responses: list[httpx2.Response] = []
    with _client(handler, breaker=breaker) as client:
        _fail_n(client, "https://a.test/fail", 1)
        _fail_n(client, "https://b.test/fail", 1)
        clock.t = 1.0
        probes = [
            threading.Thread(target=lambda host=host: responses.append(client.get(f"https://{host}/slow")))
            for host in started
        ]
        for probe in probes:
            probe.start()
        for event in started.values():
            event.wait()
        with pytest.raises(CircuitOpenError):
            client.get("https://a.test/slow")
        release.set()
        for probe in probes:
            probe.join()
    assert [r.status_code for r in responses] == [HTTPStatus.OK, HTTPStatus.OK]


def test_outside_retry_counts_one_outcome_per_retry_sequence() -> None:
    handler = _PerHost(failing={"a.test"})
    breaker = KeyedCircuitBreaker(failure_threshold=2)
    with Client(
        httpx2_client=httpx2.Client(transport=httpx2.MockTransport(handler)),
        middleware=[breaker, Retry(max_attempts=_ATTEMPTS, base_delay=0.0, retry_status_codes=frozenset({500}))],
    ) as client:
        _fail_n(client, "https://a.test/x", 1)
        assert len(handler.calls) == _ATTEMPTS
        _fail_n(client, "https://a.test/x", 1)
        with pytest.raises(CircuitOpenError):
            client.get("https://a.test/x")
    assert len(handler.calls) == 2 * _ATTEMPTS


def test_network_error_counts_against_its_origin_only() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.host == "a.test":
            msg = "refused"
            raise httpx2.ConnectError(msg, request=request)
        return httpx2.Response(HTTPStatus.OK, request=request)

    with _client(handler, breaker=KeyedCircuitBreaker(failure_threshold=1)) as client:
        with pytest.raises(NetworkError):
            client.get("https://a.test/x")
        with pytest.raises(CircuitOpenError):
            client.get("https://a.test/x")
        assert client.get("https://b.test/x").status_code == HTTPStatus.OK


def test_events_carry_the_circuit_key(caplog: pytest.LogCaptureFixture) -> None:
    handler = _PerHost(failing={"a.test"})
    with (
        _client(handler, breaker=KeyedCircuitBreaker(failure_threshold=1)) as client,
        caplog.at_level(logging.WARNING, logger="httpware.circuit_breaker"),
    ):
        _fail_n(client, "https://a.test/x", 1)
        with pytest.raises(CircuitOpenError):
            client.get("https://a.test/x")
    records = [r for r in caplog.records if r.name == "httpware.circuit_breaker"]
    assert [r.event for r in records] == ["circuit.opened", "circuit.rejected"]  # ty: ignore[unresolved-attribute]
    expected = str(httpx2.URL("https://a.test").origin)
    assert all(r.circuit_key == expected for r in records)  # ty: ignore[unresolved-attribute]

"""Free-threaded stress: KeyedCircuitBreaker creates and drives per-origin circuits consistently in parallel.

Threads race to create the circuit for the same few origins and then fail through them. Every call
must raise a 5xx StatusError or CircuitOpenError, and afterwards every origin must fast-fail.
Every exception is collected so the single `except` branch always runs (see
test_circuit_breaker_freethreaded_stress.py for why).
"""

import contextlib
import threading
from http import HTTPStatus

import httpx2
import pytest

from httpware import Client, InternalServerError, KeyedCircuitBreaker
from httpware.errors import CircuitOpenError, StatusError


_N_THREADS = 16
_N_OPS = 50
_HOSTS = ("a.test", "b.test", "c.test", "d.test")


def _fail(request: httpx2.Request) -> httpx2.Response:
    return httpx2.Response(HTTPStatus.INTERNAL_SERVER_ERROR, request=request)


@pytest.mark.stress
def test_keyed_circuit_breaker_opens_every_origin_under_parallel_failures() -> None:
    breaker = KeyedCircuitBreaker(failure_threshold=5, reset_timeout=60.0)
    client = Client(
        httpx2_client=httpx2.Client(transport=httpx2.MockTransport(_fail)),
        middleware=[breaker],
    )
    errors: list[Exception] = []
    guard = threading.Lock()

    def worker(index: int) -> None:
        for op in range(_N_OPS):
            try:
                client.get(f"https://{_HOSTS[(index + op) % len(_HOSTS)]}/x")
            except Exception as exc:  # noqa: BLE001
                with guard:
                    errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(_N_THREADS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == _N_THREADS * _N_OPS
    assert all(isinstance(exc, (StatusError, CircuitOpenError)) for exc in errors)
    for host in _HOSTS:
        with pytest.raises(CircuitOpenError):
            client.get(f"https://{host}/x")
    client.close()


@pytest.mark.stress
def test_racing_first_requests_share_one_circuit_per_origin() -> None:
    """Every thread finds the same circuit for an origin, so no recorded failure is lost to a duplicate."""
    breaker = KeyedCircuitBreaker(failure_threshold=_N_THREADS * _N_OPS + 1)
    start = threading.Barrier(_N_THREADS)

    def worker(index: int) -> None:
        start.wait()
        for op in range(_N_OPS):
            request = httpx2.Request("GET", f"https://{_HOSTS[(index + op) % len(_HOSTS)]}/x")
            with contextlib.suppress(InternalServerError):
                breaker(request, _raise_500)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(_N_THREADS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    states = breaker._states._states  # noqa: SLF001
    assert len(states) == len(_HOSTS)
    assert sum(state._consecutive_failures for state in states.values()) == _N_THREADS * _N_OPS  # noqa: SLF001
    assert {state._consecutive_failures for state in states.values()} == {_N_THREADS * _N_OPS // len(_HOSTS)}  # noqa: SLF001


def _raise_500(request: httpx2.Request) -> httpx2.Response:
    raise InternalServerError(httpx2.Response(HTTPStatus.INTERNAL_SERVER_ERROR, request=request))

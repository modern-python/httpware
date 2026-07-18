"""Free-threaded stress: CircuitBreaker transitions stay consistent under parallel failures.

Many threads drive concurrent 5xx requests. Every call must raise an expected error type — a
StatusError while the request is forwarded, or CircuitOpenError once the breaker fast-fails —
and the breaker must end OPEN with no torn state. Verify-first: expected to PASS.

Collect *every* exception (not just unexpected ones) so the single `except` branch always runs
and stays covered under the 100% gate; then assert all collected errors are of the expected
types. A catch-all that only fires on the unexpected path would be dead code on a passing run
and would drop coverage below 100%.
"""

import threading
from http import HTTPStatus

import httpx2
import pytest

from httpware import CircuitBreaker, CircuitState, Client
from httpware.errors import CircuitOpenError, StatusError


_N_THREADS = 16
_N_OPS = 50


def _fail(request: httpx2.Request) -> httpx2.Response:
    return httpx2.Response(HTTPStatus.INTERNAL_SERVER_ERROR, request=request)


@pytest.mark.stress
def test_circuit_breaker_opens_consistently_under_parallel_failures() -> None:
    breaker = CircuitBreaker(failure_threshold=5, reset_timeout=60.0)
    client = Client(
        httpx2_client=httpx2.Client(transport=httpx2.MockTransport(_fail)),
        middleware=[breaker],
    )
    errors: list[Exception] = []
    guard = threading.Lock()

    def worker() -> None:
        for _ in range(_N_OPS):
            try:
                client.get("https://example.test/x")
            except Exception as exc:  # noqa: BLE001
                with guard:
                    errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(_N_THREADS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    client.close()

    # Every request fails: a 5xx StatusError while forwarding, or CircuitOpenError once open.
    # No torn state means no other type leaks and the count is exact.
    assert len(errors) == _N_THREADS * _N_OPS
    assert all(isinstance(exc, (StatusError, CircuitOpenError)) for exc in errors)
    assert breaker.state is CircuitState.OPEN

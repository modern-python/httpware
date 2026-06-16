"""Public API surface — what `from httpware import ...` exposes."""

import httpware
import httpware.middleware
from httpware import CircuitState
from httpware.middleware.resilience import CircuitState as ResilienceCircuitState


def test_all_exports_resolve() -> None:
    for symbol in httpware.__all__:
        assert hasattr(httpware, symbol), f"{symbol} declared in __all__ but missing"


def test_no_removed_symbols_leaked() -> None:
    removed = {
        "Request",
        "Response",
        "StreamResponse",
        "Timeout",
        "Limits",
        "ClientConfig",
        "Transport",
        "Httpx2Transport",
        "RecordedTransport",
        "AuthValue",
        "PydanticDecoder",
    }
    leaked = removed & set(dir(httpware))
    assert not leaked, f"removed symbols still exposed: {leaked}"


def test_expected_exports() -> None:
    expected = {
        "AsyncBulkhead",
        "AsyncCircuitBreaker",
        "AsyncClient",
        "AsyncMiddleware",
        "AsyncNext",
        "AsyncRetry",
        "AsyncTimeout",
        "BadRequestError",
        "Bulkhead",
        "BulkheadFullError",
        "CircuitBreaker",
        "CircuitOpenError",
        "CircuitState",
        "Client",
        "ClientError",
        "ClientStatusError",
        "ConflictError",
        "DecodeError",
        "ForbiddenError",
        "InternalServerError",
        "Middleware",
        "MissingDecoderError",
        "NetworkError",
        "Next",
        "NotFoundError",
        "RateLimitedError",
        "ResponseDecoder",
        "ResponseTooLargeError",
        "Retry",
        "RetryBudget",
        "RetryBudgetExhaustedError",
        "ServerStatusError",
        "ServiceUnavailableError",
        "STATUS_TO_EXCEPTION",
        "StatusError",
        "TimeoutError",
        "TransportError",
        "UnauthorizedError",
        "UnprocessableEntityError",
        "after_response",
        "async_after_response",
        "async_before_request",
        "async_on_error",
        "before_request",
        "on_error",
    }
    actual = set(httpware.__all__)
    assert expected == actual, (
        f"__all__ mismatch:\n  missing from __all__: {expected - actual}\n  unexpected in __all__: {actual - expected}"
    )


def test_circuit_state_exported() -> None:
    assert CircuitState is ResilienceCircuitState
    assert {m.value for m in CircuitState} == {"closed", "open", "half_open"}


def test_missing_decoder_error_exported() -> None:
    assert "MissingDecoderError" in httpware.__all__
    assert httpware.MissingDecoderError.__module__ == "httpware.errors"


def test_middleware_module_all_contains_exactly_ten_public_names() -> None:
    """httpware.middleware.__all__ must list the 10 public protocol/decorator names only."""
    expected = {
        "AsyncMiddleware",
        "AsyncNext",
        "Middleware",
        "Next",
        "after_response",
        "async_after_response",
        "async_before_request",
        "async_on_error",
        "before_request",
        "on_error",
    }
    assert set(httpware.middleware.__all__) == expected


def test_middleware_module_all_does_not_leak_internals() -> None:
    """httpware.middleware.__all__ must not expose imported helpers or submodules."""
    leaked = {"httpx2", "Protocol", "Callable", "Awaitable", "TypeAlias", "runtime_checkable", "chain", "resilience"}
    assert not leaked & set(httpware.middleware.__all__)

"""Public API surface — what `from httpware import ...` exposes."""

import httpware


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
        "AsyncClient",
        "AsyncMiddleware",
        "AsyncNext",
        "AsyncRetry",
        "BadRequestError",
        "Bulkhead",
        "BulkheadFullError",
        "CircuitOpenError",
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


def test_missing_decoder_error_exported() -> None:
    assert "MissingDecoderError" in httpware.__all__
    assert httpware.MissingDecoderError.__module__ == "httpware.errors"

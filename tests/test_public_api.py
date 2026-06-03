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
    }
    leaked = removed & set(dir(httpware))
    assert not leaked, f"removed 0.1 symbols still exposed: {leaked}"


def test_expected_exports() -> None:
    expected = {
        "AsyncClient",
        "Middleware",
        "Next",
        "ResponseDecoder",
        "PydanticDecoder",
        "ClientError",
        "TransportError",
        "TimeoutError",
        "StatusError",
        "ClientStatusError",
        "ServerStatusError",
        "BadRequestError",
        "UnauthorizedError",
        "ForbiddenError",
        "NotFoundError",
        "ConflictError",
        "UnprocessableEntityError",
        "RateLimitedError",
        "InternalServerError",
        "ServiceUnavailableError",
        "STATUS_TO_EXCEPTION",
        "before_request",
        "after_response",
        "on_error",
    }
    missing = expected - set(httpware.__all__)
    assert not missing, f"expected exports missing from __all__: {missing}"

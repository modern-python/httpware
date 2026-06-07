"""httpware — thin async HTTP client wrapper over httpx2."""

from httpware.client import AsyncClient
from httpware.decoders import ResponseDecoder
from httpware.errors import (
    STATUS_TO_EXCEPTION,
    BadRequestError,
    BulkheadFullError,
    ClientError,
    ClientStatusError,
    ConflictError,
    ForbiddenError,
    InternalServerError,
    NetworkError,
    NotFoundError,
    RateLimitedError,
    RetryBudgetExhaustedError,
    ServerStatusError,
    ServiceUnavailableError,
    StatusError,
    TimeoutError,  # noqa: A004
    TransportError,
    UnauthorizedError,
    UnprocessableEntityError,
)
from httpware.middleware import (
    AsyncMiddleware,
    AsyncNext,
    async_after_response,
    async_before_request,
    async_on_error,
)
from httpware.middleware.resilience import AsyncBulkhead, AsyncRetry, RetryBudget


__all__ = [
    "STATUS_TO_EXCEPTION",
    "AsyncBulkhead",
    "AsyncClient",
    "AsyncMiddleware",
    "AsyncNext",
    "AsyncRetry",
    "BadRequestError",
    "BulkheadFullError",
    "ClientError",
    "ClientStatusError",
    "ConflictError",
    "ForbiddenError",
    "InternalServerError",
    "NetworkError",
    "NotFoundError",
    "RateLimitedError",
    "ResponseDecoder",
    "RetryBudget",
    "RetryBudgetExhaustedError",
    "ServerStatusError",
    "ServiceUnavailableError",
    "StatusError",
    "TimeoutError",
    "TransportError",
    "UnauthorizedError",
    "UnprocessableEntityError",
    "async_after_response",
    "async_before_request",
    "async_on_error",
]

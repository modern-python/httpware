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
from httpware.middleware import Middleware, Next, after_response, before_request, on_error
from httpware.middleware.resilience import Bulkhead, Retry, RetryBudget


__all__ = [
    "STATUS_TO_EXCEPTION",
    "AsyncClient",
    "BadRequestError",
    "Bulkhead",
    "BulkheadFullError",
    "ClientError",
    "ClientStatusError",
    "ConflictError",
    "ForbiddenError",
    "InternalServerError",
    "Middleware",
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
    "StatusError",
    "TimeoutError",
    "TransportError",
    "UnauthorizedError",
    "UnprocessableEntityError",
    "after_response",
    "before_request",
    "on_error",
]

"""httpware — thin async HTTP client wrapper over httpx2."""

from httpware.client import AsyncClient
from httpware.decoders import ResponseDecoder
from httpware.errors import (
    STATUS_TO_EXCEPTION,
    BadRequestError,
    ClientError,
    ClientStatusError,
    ConflictError,
    ForbiddenError,
    InternalServerError,
    NotFoundError,
    RateLimitedError,
    ServerStatusError,
    ServiceUnavailableError,
    StatusError,
    TimeoutError,  # noqa: A004
    TransportError,
    UnauthorizedError,
    UnprocessableEntityError,
)
from httpware.middleware import Middleware, Next, after_response, before_request, on_error


__all__ = [
    "STATUS_TO_EXCEPTION",
    "AsyncClient",
    "BadRequestError",
    "ClientError",
    "ClientStatusError",
    "ConflictError",
    "ForbiddenError",
    "InternalServerError",
    "Middleware",
    "Next",
    "NotFoundError",
    "RateLimitedError",
    "ResponseDecoder",
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

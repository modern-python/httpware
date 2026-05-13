"""httpware — resilience-first async HTTP client framework for Python."""

from httpware.config import ClientConfig, Limits, Timeout
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
from httpware.request import Request
from httpware.response import Response


__all__ = [
    "STATUS_TO_EXCEPTION",
    "BadRequestError",
    "ClientConfig",
    "ClientError",
    "ClientStatusError",
    "ConflictError",
    "ForbiddenError",
    "InternalServerError",
    "Limits",
    "NotFoundError",
    "RateLimitedError",
    "Request",
    "Response",
    "ServerStatusError",
    "ServiceUnavailableError",
    "StatusError",
    "Timeout",
    "TimeoutError",
    "TransportError",
    "UnauthorizedError",
    "UnprocessableEntityError",
]

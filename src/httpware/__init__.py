"""httpware — resilience-first async HTTP client framework for Python."""

from httpware.client import AsyncClient
from httpware.config import ClientConfig, Limits, Timeout
from httpware.decoders import ResponseDecoder
from httpware.decoders.pydantic import PydanticDecoder
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
from httpware.request import Request
from httpware.response import Response, StreamResponse
from httpware.transports import Transport
from httpware.transports.httpx2 import Httpx2Transport
from httpware.transports.recorded import RecordedTransport


__all__ = [
    "STATUS_TO_EXCEPTION",
    "AsyncClient",
    "BadRequestError",
    "ClientConfig",
    "ClientError",
    "ClientStatusError",
    "ConflictError",
    "ForbiddenError",
    "Httpx2Transport",
    "InternalServerError",
    "Limits",
    "Middleware",
    "Next",
    "NotFoundError",
    "PydanticDecoder",
    "RateLimitedError",
    "RecordedTransport",
    "Request",
    "Response",
    "ResponseDecoder",
    "ServerStatusError",
    "ServiceUnavailableError",
    "StatusError",
    "StreamResponse",
    "Timeout",
    "TimeoutError",
    "Transport",
    "TransportError",
    "UnauthorizedError",
    "UnprocessableEntityError",
    "after_response",
    "before_request",
    "on_error",
]

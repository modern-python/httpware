"""Status-keyed exception hierarchy.

Auto-raise fires at four sites (all in client.py): both clients' internal
terminals (Client._terminal / AsyncClient._terminal) and both stream() methods
(Client.stream / AsyncClient.stream).
Unknown 4xx falls back to ClientStatusError; unknown 5xx to ServerStatusError.
The fallback assumes 400 <= status < 600.

__repr__ and the summary message run response.request.url through
_internal.redaction.redact_url, which strips user:pass@ userinfo and masks the
values of known-sensitive query parameters. NOTE: the full request headers
(Authorization, Cookie, ...) remain reachable via exc.response.request — handler
authors must redact those before logging.
"""

import builtins
from collections.abc import Mapping
from typing import Any, Literal

import httpx2

from httpware._internal.redaction import redact_url


class ClientError(Exception):
    """Root of the httpware exception tree."""


class TransportError(ClientError):
    """Connection / network / protocol failure raised before a response was received."""


class NetworkError(TransportError):
    """Transient network-layer failure (connect/read/write/close). Safe to retry.

    Pool-acquisition timeouts are NOT under this class; they raise ``TimeoutError``
    via ``httpx2.PoolTimeout`` (a ``TimeoutException`` subclass).
    """


class TimeoutError(ClientError, builtins.TimeoutError):  # noqa: A001
    """Client-side timeout (connect / read / write / pool).

    Inherits from both ``httpware.ClientError`` and ``builtins.TimeoutError`` so
    ``except builtins.TimeoutError`` / ``except OSError`` (the form
    ``asyncio.wait_for`` uses) also catches httpware-raised timeouts.
    Deliberate shadowing of the builtin; do not rename.
    """


def _reconstruct_status_error(cls: "type[StatusError]", response: httpx2.Response) -> "StatusError":
    return cls(response)


class StatusError(ClientError):
    """Base for HTTP-status-keyed errors.

    Holds the raw httpx2.Response. Subclasses do not override __init__.
    """

    response: httpx2.Response

    def __init__(self, response: httpx2.Response) -> None:
        self.response = response
        super().__init__(self._summary())

    def _summary(self) -> str:
        method = self.response.request.method
        url = redact_url(str(self.response.request.url))
        return f"{self.response.status_code} {method} {url}"

    def __repr__(self) -> str:
        cls_name = type(self).__name__
        method = self.response.request.method
        url = redact_url(str(self.response.request.url))
        return f"<{cls_name} status={self.response.status_code} method={method} url={url}>"

    def __reduce__(self) -> tuple[Any, ...]:
        return (_reconstruct_status_error, (type(self), self.response))


class ClientStatusError(StatusError):
    """Base for 4xx HTTP status errors."""


class ServerStatusError(StatusError):
    """Base for 5xx HTTP status errors."""


class BadRequestError(ClientStatusError):
    """HTTP 400."""


class UnauthorizedError(ClientStatusError):
    """HTTP 401."""


class ForbiddenError(ClientStatusError):
    """HTTP 403."""


class NotFoundError(ClientStatusError):
    """HTTP 404."""


class ConflictError(ClientStatusError):
    """HTTP 409."""


class UnprocessableEntityError(ClientStatusError):
    """HTTP 422."""


class RateLimitedError(ClientStatusError):
    """HTTP 429."""


class InternalServerError(ServerStatusError):
    """HTTP 500."""


class ServiceUnavailableError(ServerStatusError):
    """HTTP 503."""


STATUS_TO_EXCEPTION: Mapping[int, type[StatusError]] = {
    400: BadRequestError,
    401: UnauthorizedError,
    403: ForbiddenError,
    404: NotFoundError,
    409: ConflictError,
    422: UnprocessableEntityError,
    429: RateLimitedError,
    500: InternalServerError,
    503: ServiceUnavailableError,
}


def _reconstruct_kwonly(cls: type, kwargs: dict[str, Any]) -> Any:  # noqa: ANN401
    return cls(**kwargs)


class _KeywordReduceMixin:
    """Shared __reduce__ for keyword-only ClientError subclasses.

    For subclasses whose __init__ is keyword-only and whose instance
    __dict__ exactly mirrors it. Reconstruction replays self.__dict__ as
    keyword arguments (cls(**kwargs)): an attribute stored beyond
    __init__'s keyword parameters raises TypeError on unpickle (unexpected
    keyword argument); a keyword parameter __init__ doesn't assign to self
    is silently dropped if it has a default (unpickle reverts to it) or
    raises TypeError if it doesn't (missing required argument).
    """

    def __reduce__(self) -> tuple[Any, ...]:
        return (_reconstruct_kwonly, (type(self), self.__dict__))


class RetryBudgetExhaustedError(_KeywordReduceMixin, ClientError):
    """Raised when a retry was needed but the RetryBudget refused to permit it.

    Carries the last response and/or exception observed before the budget refused,
    plus the number of attempts already completed.
    """

    last_response: httpx2.Response | None
    last_exception: BaseException | None
    attempts: int

    def __init__(
        self,
        *,
        last_response: httpx2.Response | None,
        last_exception: BaseException | None,
        attempts: int,
    ) -> None:
        self.last_response = last_response
        self.last_exception = last_exception
        self.attempts = attempts
        super().__init__(f"retry budget exhausted after {attempts} attempt(s)")


class BulkheadFullError(_KeywordReduceMixin, ClientError):
    """Raised when ``acquire_timeout`` elapses before an AsyncBulkhead slot becomes available.

    Carries the configured caps for caller logging/alerting.
    """

    max_concurrent: int
    acquire_timeout: float | None

    def __init__(self, *, max_concurrent: int, acquire_timeout: float | None) -> None:
        self.max_concurrent = max_concurrent
        self.acquire_timeout = acquire_timeout
        super().__init__(f"bulkhead full (max_concurrent={max_concurrent}, acquire_timeout={acquire_timeout})")


class CircuitOpenError(_KeywordReduceMixin, ClientError):
    """Raised when a CircuitBreaker refuses a request because the circuit is not closed.

    Fires when the circuit is OPEN, or when it is HALF_OPEN and the single probe
    slot is already taken. The request is never forwarded to ``next``. ``retry_after``
    carries the seconds until the circuit will next admit a probe, when known
    (``None`` when a concurrent probe is already in flight).
    """

    retry_after: float | None

    def __init__(self, *, retry_after: float | None) -> None:
        self.retry_after = retry_after
        if retry_after is None:
            super().__init__("circuit open (a probe request is already in flight)")
        else:
            super().__init__(f"circuit open (retry_after={retry_after:.3f}s)")


class DecodeError(_KeywordReduceMixin, ClientError):
    """Raised when the active ResponseDecoder failed to decode response.content.

    The HTTP call itself succeeded — status was 2xx/3xx and the transport
    delivered the body intact — but the body could not be parsed into the
    requested response_model. Always chained from the underlying library
    exception via ``raise ... from exc``; that exception is also exposed as
    ``self.original`` for structured handling.
    """

    response: httpx2.Response
    model: type
    original: BaseException

    def __init__(
        self,
        *,
        response: httpx2.Response,
        model: type,
        original: BaseException,
    ) -> None:
        self.response = response
        self.model = model
        self.original = original
        super().__init__(f"failed to decode response into {model.__name__}: {original}")


def _missing_decoder_summary(model: type, registered_names: tuple[str, ...]) -> str:
    if not registered_names:
        hint = (
            "no decoders registered. Install `pip install httpware[pydantic]` "
            "or `pip install httpware[msgspec]`, or pass decoders=[...] explicitly."
        )
    else:
        joined = " + ".join(registered_names)
        hint = f"registered decoders ({joined}) all rejected it. Pass a custom decoder via decoders=[...]."
    return f"no decoder for response_model={model!r}: {hint}"


class MissingDecoderError(_KeywordReduceMixin, ClientError):
    """Raised when response_model= is set but no registered decoder claims the model.

    Fires at .send() entry, BEFORE the HTTP call — no point sending a request
    whose response cannot be decoded. Distinct from DecodeError, which means
    the decoder ran and the payload was malformed.
    """

    model: type
    registered_names: tuple[str, ...]

    def __init__(self, *, model: type, registered_names: tuple[str, ...]) -> None:
        self.model = model
        self.registered_names = registered_names
        super().__init__(_missing_decoder_summary(model, registered_names))


class ResponseTooLargeError(_KeywordReduceMixin, ClientError):
    """Raised when a response body exceeds the client's max_response_body_bytes cap.

    Status-agnostic: fires on any non-streaming send() and on stream()'s internal
    error pre-read, counting DECODED bytes. Only raised when
    max_response_body_bytes is set (opt-in). `reason` discriminates the two trip
    modes:

    - "declared": the response's declared Content-Length already exceeds the cap,
      so the body is rejected BEFORE a byte is read (`content_length` holds it).
    - "streamed": the decoded body crossed the cap mid-read (the chunked or
      compression-bomb case); `content_length` is whatever the server declared
      and is unrelated to the cap. The true oversized size is unknown by design.
    """

    status_code: int
    limit: int
    content_length: int | None
    reason: Literal["declared", "streamed"]

    def __init__(
        self,
        *,
        status_code: int,
        limit: int,
        content_length: int | None,
        reason: Literal["declared", "streamed"],
    ) -> None:
        self.status_code = status_code
        self.limit = limit
        self.content_length = content_length
        self.reason = reason
        if reason == "declared":
            detail = f"declared content_length={content_length} exceeds max_response_body_bytes={limit}"
        else:
            detail = f"decoded body exceeded max_response_body_bytes={limit}"
        super().__init__(f"response body too large: status={status_code} {detail}")

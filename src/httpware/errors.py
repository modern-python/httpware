"""Status-keyed exception hierarchy.

Auto-raise rule lives at AsyncClient's internal terminal (see client.py).
Unknown 4xx falls back to ClientStatusError; unknown 5xx to ServerStatusError.
The fallback assumes 400 <= status < 600.

__repr__ and the summary message strip user:pass@ userinfo from
response.request.url to avoid leaking credentials in tracebacks.
Query-string secrets are NOT stripped here.
"""

import builtins
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx2


def _strip_userinfo(url: str) -> str:
    if "@" not in url or "://" not in url:
        return url
    parts = urlsplit(url)
    if parts.username is None and parts.password is None:
        return url
    hostname = parts.hostname or ""
    if ":" in hostname:  # IPv6 literal — re-wrap in brackets
        hostname = f"[{hostname}]"
    netloc = hostname
    if parts.port is not None:
        netloc = f"{netloc}:{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


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
        url = _strip_userinfo(str(self.response.request.url))
        return f"{self.response.status_code} {method} {url}"

    def __repr__(self) -> str:
        cls_name = type(self).__name__
        method = self.response.request.method
        url = _strip_userinfo(str(self.response.request.url))
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


def _reconstruct_budget_exhausted(
    cls: "type[RetryBudgetExhaustedError]",
    last_response: httpx2.Response | None,
    last_exception: BaseException | None,
    attempts: int,
) -> "RetryBudgetExhaustedError":
    return cls(last_response=last_response, last_exception=last_exception, attempts=attempts)


class RetryBudgetExhaustedError(ClientError):
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

    def __reduce__(self) -> tuple[Any, ...]:
        return (
            _reconstruct_budget_exhausted,
            (type(self), self.last_response, self.last_exception, self.attempts),
        )


def _reconstruct_bulkhead_full(
    cls: "type[BulkheadFullError]",
    max_concurrent: int,
    acquire_timeout: float | None,
) -> "BulkheadFullError":
    return cls(max_concurrent=max_concurrent, acquire_timeout=acquire_timeout)


class BulkheadFullError(ClientError):
    """Raised when ``acquire_timeout`` elapses before an AsyncBulkhead slot becomes available.

    Carries the configured caps for caller logging/alerting.
    """

    max_concurrent: int
    acquire_timeout: float | None

    def __init__(self, *, max_concurrent: int, acquire_timeout: float | None) -> None:
        self.max_concurrent = max_concurrent
        self.acquire_timeout = acquire_timeout
        super().__init__(f"bulkhead full (max_concurrent={max_concurrent}, acquire_timeout={acquire_timeout})")

    def __reduce__(self) -> tuple[Any, ...]:
        return (
            _reconstruct_bulkhead_full,
            (type(self), self.max_concurrent, self.acquire_timeout),
        )


def _reconstruct_decode_error(
    cls: "type[DecodeError]",
    response: httpx2.Response,
    model: type,
    original: BaseException,
) -> "DecodeError":
    return cls(response=response, model=model, original=original)


class DecodeError(ClientError):
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

    def __reduce__(self) -> tuple[Any, ...]:
        return (
            _reconstruct_decode_error,
            (type(self), self.response, self.model, self.original),
        )


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


def _reconstruct_missing_decoder(
    cls: "type[MissingDecoderError]",
    model: type,
    registered_names: tuple[str, ...],
) -> "MissingDecoderError":
    return cls(model=model, registered_names=registered_names)


class MissingDecoderError(ClientError):
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

    def __reduce__(self) -> tuple[Any, ...]:
        return (_reconstruct_missing_decoder, (type(self), self.model, self.registered_names))

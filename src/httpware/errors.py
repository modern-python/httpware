"""Status-keyed exception hierarchy with plain typed fields.

Fallback rule: unknown 4xx statuses fall back to ``ClientStatusError``;
unknown 5xx fall back to ``ServerStatusError``. The fallback assumes
``400 <= status < 600`` — callers must guard against non-error statuses
(1xx informational, 2xx success, 3xx redirect) before consulting
``STATUS_TO_EXCEPTION``. The resolution logic lives at the transport
seam (Story 1.4); this module only ships the classes and the lookup dict.

``__repr__`` and the summary message passed to ``Exception.__init__``
strip ``user:pass@`` userinfo from ``request_url`` to avoid leaking
credentials in tracebacks, log lines, and exception reporters.
Query-string secrets (e.g. ``?api_key=...``) are NOT stripped here —
full redaction is the responsibility of the ``Redactor`` middleware
(Story 5.3).
"""

import builtins
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any
from urllib.parse import urlsplit, urlunsplit


def _strip_userinfo(url: str) -> str:
    """Drop the ``user:pass@`` portion of ``url`` if present."""
    if "@" not in url or "://" not in url:
        return url
    parts = urlsplit(url)
    if parts.username is None and parts.password is None:
        return url
    netloc = parts.hostname or ""
    if parts.port is not None:
        netloc = f"{netloc}:{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def _reconstruct_status_error(
    cls: "type[StatusError]",
    status: int,
    body: bytes,
    headers: Mapping[str, str],
    json: Any,  # noqa: ANN401
    request_method: str,
    request_url: str,
) -> "StatusError":
    """Pickle / copy reconstructor for ``StatusError`` subclasses."""
    return cls(
        status=status,
        body=body,
        headers=headers,
        json=json,
        request_method=request_method,
        request_url=request_url,
    )


class ClientError(Exception):
    """Root of the httpware exception tree."""


class TransportError(ClientError):
    """Connection / network / protocol failure raised before a response was received."""


class TimeoutError(ClientError, builtins.TimeoutError):  # noqa: A001
    """Client-side timeout (connect / read / write / pool).

    Inherits from both ``httpware.ClientError`` and ``builtins.TimeoutError``
    so ``except httpware.TimeoutError`` catches httpware-raised timeouts AND
    ``except builtins.TimeoutError`` / ``except OSError`` (the form
    ``asyncio.wait_for`` uses) also catches them. Deliberately shadows
    ``builtins.TimeoutError``; see Decision 3 in ``docs/architecture.md``.
    Do not "fix" this name.
    """


class StatusError(ClientError):
    """Base for HTTP-status-keyed errors with plain typed fields."""

    status: int
    body: bytes
    headers: Mapping[str, str]
    json: Any
    request_method: str
    request_url: str

    def __init__(
        self,
        *,
        status: int,
        body: bytes,
        headers: Mapping[str, str],
        json: Any | None,  # noqa: ANN401
        request_method: str,
        request_url: str,
    ) -> None:
        """Store all six fields and emit a short summary message to ``Exception.__init__``.

        Subclasses overriding ``__init__`` MUST call
        ``super().__init__(status=..., body=..., headers=..., json=...,
        request_method=..., request_url=...)`` to register ``args`` and the
        summary message; otherwise ``str(exc)`` is silently empty.
        ``headers`` is defensively copied into a read-only ``MappingProxyType``
        so caller mutations after ``raise`` do not bleed into the exception.
        """
        self.status = status
        self.body = body
        self.headers = MappingProxyType(dict(headers))
        self.json = json
        self.request_method = request_method
        self.request_url = request_url
        super().__init__(f"{status} {request_method} {_strip_userinfo(request_url)}")

    def __repr__(self) -> str:
        cls_name = type(self).__name__
        safe_url = _strip_userinfo(self.request_url)
        return f"<{cls_name} status={self.status} method={self.request_method} url={safe_url}>"

    def __reduce__(self) -> tuple[Any, ...]:
        return (
            _reconstruct_status_error,
            (
                type(self),
                self.status,
                self.body,
                dict(self.headers),
                self.json,
                self.request_method,
                self.request_url,
            ),
        )


class ClientStatusError(StatusError):
    """Base for 4xx HTTP status errors."""


class ServerStatusError(StatusError):
    """Base for 5xx HTTP status errors."""


class BadRequestError(ClientStatusError):
    """HTTP 400 Bad Request."""


class UnauthorizedError(ClientStatusError):
    """HTTP 401 Unauthorized."""


class ForbiddenError(ClientStatusError):
    """HTTP 403 Forbidden."""


class NotFoundError(ClientStatusError):
    """HTTP 404 Not Found."""


class ConflictError(ClientStatusError):
    """HTTP 409 Conflict."""


class UnprocessableEntityError(ClientStatusError):
    """HTTP 422 Unprocessable Entity."""


class RateLimitedError(ClientStatusError):
    """HTTP 429 Too Many Requests."""


class InternalServerError(ServerStatusError):
    """HTTP 500 Internal Server Error."""


class ServiceUnavailableError(ServerStatusError):
    """HTTP 503 Service Unavailable."""


# Unknown 4xx → ``ClientStatusError``; unknown 5xx → ``ServerStatusError``.
# Fallback assumes ``400 <= status < 600`` — callers must guard against
# non-error codes (1xx/2xx/3xx) before consulting this dict. The fallback
# resolution lives at the call site (Story 1.4 inlines it at the transport
# seam).
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

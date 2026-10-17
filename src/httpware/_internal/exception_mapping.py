"""httpx2 -> httpware exception mapping (shared).

map_httpx2_exception is a pure function. Client._terminal, AsyncClient._terminal
and both stream() methods call it from an inline `except MAPPED_HTTPX2_ERRORS`, and
next to that clause turn the RuntimeError httpx2 raises on a closed client into
TransportError. Clause ordering:
TimeoutException -> InvalidURL/CookieConflict -> NetworkError/RemoteProtocolError
-> HTTPError (subclass before parent so the right type wins).
"""

import httpx2

from httpware.errors import NetworkError, TimeoutError, TransportError  # noqa: A004


MAPPED_HTTPX2_ERRORS = (httpx2.HTTPError, httpx2.InvalidURL, httpx2.CookieConflict)
"""The httpx2 exceptions map_httpx2_exception translates."""


def map_httpx2_exception(exc: BaseException) -> NetworkError | TimeoutError | TransportError:
    """Map an httpx2 exception to its httpware equivalent.

    Order is significant: more-specific httpx2 types must match before more
    general ones. We return the mapped exception; the caller does `raise ... from exc`.
    """
    if isinstance(exc, httpx2.TimeoutException):
        return TimeoutError(str(exc))
    if isinstance(exc, (httpx2.InvalidURL, httpx2.CookieConflict)):
        return TransportError(str(exc))
    if isinstance(exc, (httpx2.NetworkError, httpx2.RemoteProtocolError)):
        return NetworkError(str(exc))
    if isinstance(exc, httpx2.HTTPError):
        return TransportError(str(exc))
    return TransportError(str(exc))  # pragma: no cover — defensive default; httpx2.HTTPError is the root

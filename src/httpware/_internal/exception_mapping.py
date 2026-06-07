"""httpx2 -> httpware exception mapping.

Pure function used by both Client._terminal and AsyncClient._terminal,
and by both stream() methods. Clause ordering: TimeoutException ->
InvalidURL/CookieConflict -> NetworkError -> HTTPError (subclass before
parent so the right type wins).
"""

import httpx2

from httpware.errors import NetworkError, TimeoutError, TransportError  # noqa: A004


def map_httpx2_exception(exc: BaseException) -> NetworkError | TimeoutError | TransportError:
    """Map an httpx2 exception to its httpware equivalent.

    Order is significant: more-specific httpx2 types must match before more
    general ones. We return the mapped exception; the caller does `raise ... from exc`.
    """
    if isinstance(exc, httpx2.TimeoutException):
        return TimeoutError(str(exc))
    if isinstance(exc, (httpx2.InvalidURL, httpx2.CookieConflict)):
        return TransportError(str(exc))
    if isinstance(exc, httpx2.NetworkError):
        return NetworkError(str(exc))
    if isinstance(exc, httpx2.HTTPError):
        return TransportError(str(exc))
    return TransportError(str(exc))  # pragma: no cover — defensive default; httpx2.HTTPError is the root

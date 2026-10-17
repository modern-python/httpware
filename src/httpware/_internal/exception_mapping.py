"""httpx2 -> httpware exception mapping + context-manager wrappers (shared).

map_httpx2_exception is a pure function used by both Client._terminal and
AsyncClient._terminal, and by both stream() methods. Clause ordering:
TimeoutException -> InvalidURL/CookieConflict -> NetworkError/RemoteProtocolError
-> HTTPError (subclass before parent so the right type wins). The two context managers
below wrap it for use as `with`/`async with` blocks around the httpx2 call,
and also turn the RuntimeError httpx2 raises on a closed client into TransportError.
"""

import contextlib
from collections.abc import AsyncGenerator, Generator

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
    if isinstance(exc, (httpx2.NetworkError, httpx2.RemoteProtocolError)):
        return NetworkError(str(exc))
    if isinstance(exc, httpx2.HTTPError):
        return TransportError(str(exc))
    return TransportError(str(exc))  # pragma: no cover — defensive default; httpx2.HTTPError is the root


@contextlib.asynccontextmanager
async def _httpx2_exception_mapper(client: httpx2.AsyncClient) -> AsyncGenerator[None]:
    """Map httpx2 exceptions, and use of a closed `client`, to httpware exceptions.

    Shared by AsyncClient._terminal and stream().
    """
    try:
        yield
    except httpx2.HTTPError as exc:
        raise map_httpx2_exception(exc) from exc
    except (httpx2.InvalidURL, httpx2.CookieConflict) as exc:
        raise map_httpx2_exception(exc) from exc
    except RuntimeError as exc:
        if client.is_closed:
            raise TransportError(str(exc)) from exc
        raise


@contextlib.contextmanager
def _httpx2_exception_mapper_sync(client: httpx2.Client) -> Generator[None]:
    """Sync sibling of _httpx2_exception_mapper."""
    try:
        yield
    except httpx2.HTTPError as exc:
        raise map_httpx2_exception(exc) from exc
    except (httpx2.InvalidURL, httpx2.CookieConflict) as exc:
        raise map_httpx2_exception(exc) from exc
    except RuntimeError as exc:
        if client.is_closed:
            raise TransportError(str(exc)) from exc
        raise

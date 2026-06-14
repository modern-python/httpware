"""Status-code dispatch + streaming-body detection.

Shared by Client and AsyncClient. The STREAMING_BODY_MARKER is the public
extensions key both Retry and AsyncRetry read; renaming it is breaking.
"""

from http import HTTPStatus

import httpx2

from httpware.errors import STATUS_TO_EXCEPTION, ClientStatusError, ServerStatusError


STREAMING_BODY_MARKER = "httpware.streaming_body"
"""Set on ``httpx2.Request.extensions`` when content/data/files is a non-replayable
iterable (async-iterable for AsyncClient, sync iterator/generator for Client).
Retry / AsyncRetry read this marker to refuse retrying a streamed-body request
(the consumed iterator cannot replay across attempts)."""


def _raise_on_status_error(response: httpx2.Response) -> None:
    """Raise the appropriate StatusError subclass for a 4xx/5xx response. No-op for 2xx/3xx."""
    status = response.status_code
    if HTTPStatus.BAD_REQUEST <= status < 600:  # noqa: PLR2004 — 600 is the synthetic upper bound for 5xx
        exc_class = STATUS_TO_EXCEPTION.get(
            status,
            ClientStatusError if status < HTTPStatus.INTERNAL_SERVER_ERROR else ServerStatusError,
        )
        raise exc_class(response)


def _is_replayable_type(value: object) -> bool:
    """Return True if value is a replayable type (safe to replay across retry attempts)."""
    return isinstance(value, (bytes, bytearray, memoryview, str, dict, list, tuple))


def _is_streaming_body_async(value: object) -> bool:
    """Return True if value is a non-replayable body (async-iterable or sync non-replayable iterable)."""
    if value is None:
        return False
    if _is_replayable_type(value):
        return False
    return hasattr(value, "__aiter__") or hasattr(value, "__iter__")


def _is_streaming_body_sync(value: object) -> bool:
    """Return True if value is a sync iterable body that cannot be safely replayed for retry."""
    if value is None:
        return False
    if _is_replayable_type(value):
        return False
    return hasattr(value, "__iter__")

"""Response-body cap enforcement: validate, read-capped (sync + async)."""

import typing
from collections.abc import Mapping
from http import HTTPStatus

import httpx2

from httpware.errors import ResponseTooLargeError


_MAX_RESPONSE_BODY_BYTES_INVALID = "max_response_body_bytes must be >= 1"


def _validate_max_response_body_bytes(cap: int | None) -> None:
    """Reject a non-None cap below 1. None means unbounded (the default)."""
    if cap is not None and cap < 1:
        raise ValueError(_MAX_RESPONSE_BODY_BYTES_INVALID)


def _parse_content_length(raw: str | None) -> int | None:
    """Return a non-negative int Content-Length, or None for missing/garbage. Never raises."""
    if raw is None:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value >= 0 else None


class _CapExceeded(Exception):  # noqa: N818 — internal control-flow signal, not a user-facing error
    """Internal signal: decoded bytes crossed the cap mid-read. Carries bytes read so far."""

    def __init__(self, *, read: int) -> None:
        self.read = read
        super().__init__(f"decoded body exceeded cap after {read} bytes")


def _accumulate_capped(chunks: typing.Iterable[bytes], cap: int) -> bytes:
    """Concatenate `chunks`, raising `_CapExceeded` the moment the running total exceeds `cap`.

    Counts decoded bytes (the in-memory footprint). Grown in a single bytearray
    so there is no transient list-plus-join double allocation.
    """
    buf = bytearray()
    for chunk in chunks:
        buf += chunk
        if len(buf) > cap:
            raise _CapExceeded(read=len(buf))
    return bytes(buf)


def _safe_extensions(extensions: Mapping[str, typing.Any]) -> dict[str, typing.Any]:
    """Copy response extensions, dropping the now-stale `network_stream`.

    The rebuilt buffered Response never touches its network stream, so carrying a
    consumed/closed one wholesale is sloppy. `http_version`/`reason_phrase` and
    any other keys are preserved.
    """
    return {key: value for key, value in extensions.items() if key != "network_stream"}


# Headers describing the wire encoding of the body. The accumulator yields the
# DECODED body, so these no longer apply; httpx2 recomputes content-length from
# the buffered content. Carrying content-encoding forward makes httpx2 try to
# re-decode already-decoded bytes and raise.
_WIRE_BODY_HEADERS = ("content-encoding", "content-length", "transfer-encoding")
_BODILESS_STATUS = frozenset({HTTPStatus.NO_CONTENT, HTTPStatus.NOT_MODIFIED})  # 204, 304


def _buffered_headers(headers: httpx2.Headers) -> httpx2.Headers:
    """Copy `headers`, stripping wire-encoding headers stale after decoding+buffering."""
    out = httpx2.Headers(headers)
    for name in _WIRE_BODY_HEADERS:
        if name in out:
            del out[name]
    return out


def _response_has_body(method: str, status_code: int) -> bool:
    """Whether a response carries a message body (RFC 9110 §6.4.1).

    HEAD responses and 204/304 never have a body regardless of a declared
    Content-Length, so they must never trip the cap.
    """
    return method.upper() != "HEAD" and status_code not in _BODILESS_STATUS


def _read_capped(response: httpx2.Response, cap: int, request: httpx2.Request) -> httpx2.Response:
    """Buffer a streaming sync `response` under `cap` decoded bytes; return a buffered Response.

    Raises `ResponseTooLargeError` (reason="declared") if the declared
    Content-Length already exceeds `cap` — before any byte is read — and
    (reason="streamed") if the decoded body crosses `cap` mid-read. Does not
    close `response`; the caller owns the stream lifecycle.
    """
    if not _response_has_body(request.method, response.status_code):
        response.read()  # empty body; preserve the original response (and its headers)
        return response
    content_length = _parse_content_length(response.headers.get("content-length"))
    if content_length is not None and content_length > cap:
        raise ResponseTooLargeError(
            status_code=response.status_code, limit=cap, content_length=content_length, reason="declared"
        )
    try:
        content = _accumulate_capped(response.iter_bytes(), cap)
    except _CapExceeded:
        raise ResponseTooLargeError(
            status_code=response.status_code, limit=cap, content_length=content_length, reason="streamed"
        ) from None
    return httpx2.Response(
        status_code=response.status_code,
        headers=_buffered_headers(response.headers),
        content=content,
        request=request,
        extensions=_safe_extensions(response.extensions),
        history=response.history,
    )


async def _read_capped_async(response: httpx2.Response, cap: int, request: httpx2.Request) -> httpx2.Response:
    """Async mirror of `_read_capped` (counts decoded bytes from `aiter_bytes`)."""
    if not _response_has_body(request.method, response.status_code):
        await response.aread()  # empty body; preserve the original response (and its headers)
        return response
    content_length = _parse_content_length(response.headers.get("content-length"))
    if content_length is not None and content_length > cap:
        raise ResponseTooLargeError(
            status_code=response.status_code, limit=cap, content_length=content_length, reason="declared"
        )
    buf = bytearray()
    async for chunk in response.aiter_bytes():
        buf += chunk
        if len(buf) > cap:
            raise ResponseTooLargeError(
                status_code=response.status_code, limit=cap, content_length=content_length, reason="streamed"
            )
    return httpx2.Response(
        status_code=response.status_code,
        headers=_buffered_headers(response.headers),
        content=bytes(buf),
        request=request,
        extensions=_safe_extensions(response.extensions),
        history=response.history,
    )

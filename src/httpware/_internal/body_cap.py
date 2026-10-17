"""Response-body cap enforcement: validate, read-capped (sync + async)."""

import contextlib
import datetime as dt
import typing
from collections.abc import AsyncGenerator, AsyncIterator, Iterator, Mapping
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


def _reject_if_declared_length_exceeds_cap(response: httpx2.Response, cap: int) -> int | None:
    """Return the parsed Content-Length, raising ResponseTooLargeError(reason="declared") if it already exceeds cap."""
    content_length = _parse_content_length(response.headers.get("content-length"))
    if content_length is not None and content_length > cap:
        raise ResponseTooLargeError(
            status_code=response.status_code, limit=cap, content_length=content_length, reason="declared"
        )
    return content_length


class _CappedSyncStream(httpx2.SyncByteStream):
    """Wrap a response stream, raising ResponseTooLargeError(reason="streamed") once it yields more than `cap` bytes."""

    def __init__(self, stream: httpx2.SyncByteStream, cap: int, status_code: int, content_length: int | None) -> None:
        self._stream = stream
        self._cap = cap
        self._status_code = status_code
        self._content_length = content_length

    @property
    def elapsed(self) -> dt.timedelta | None:
        """The wrapped stream's `elapsed`, which httpx2 reads back as `Response.elapsed`."""
        return getattr(self._stream, "elapsed", None)

    def __iter__(self) -> Iterator[bytes]:
        read = 0
        for chunk in self._stream:
            read += len(chunk)
            if read > self._cap:
                raise ResponseTooLargeError(
                    status_code=self._status_code,
                    limit=self._cap,
                    content_length=self._content_length,
                    reason="streamed",
                )
            yield chunk

    def close(self) -> None:
        self._stream.close()


class _CappedAsyncStream(httpx2.AsyncByteStream):
    """Async mirror of `_CappedSyncStream`."""

    def __init__(self, stream: httpx2.AsyncByteStream, cap: int, status_code: int, content_length: int | None) -> None:
        self._stream = stream
        self._cap = cap
        self._status_code = status_code
        self._content_length = content_length

    @property
    def elapsed(self) -> dt.timedelta | None:
        """The wrapped stream's `elapsed`, which httpx2 reads back as `Response.elapsed`."""
        return getattr(self._stream, "elapsed", None)

    async def __aiter__(self) -> AsyncIterator[bytes]:
        chunks = self._stream.__aiter__()
        try:
            read = 0
            async for chunk in chunks:
                read += len(chunk)
                if read > self._cap:
                    raise ResponseTooLargeError(
                        status_code=self._status_code,
                        limit=self._cap,
                        content_length=self._content_length,
                        reason="streamed",
                    )
                yield chunk
        finally:
            if isinstance(chunks, AsyncGenerator):
                await chunks.aclose()

    async def aclose(self) -> None:
        await self._stream.aclose()


def _build_buffered_response(response: httpx2.Response, content: bytes, request: httpx2.Request) -> httpx2.Response:
    """Rebuild a buffered Response from the closed streaming `response` and its final decoded `content`."""
    buffered = httpx2.Response(
        status_code=response.status_code,
        headers=_buffered_headers(response.headers),
        content=content,
        request=request,
        extensions=_safe_extensions(response.extensions),
        history=response.history,
        default_encoding=response.default_encoding,
    )
    buffered.next_request = response.next_request
    with contextlib.suppress(RuntimeError):  # httpx2 has no elapsed for a stream it never closed
        buffered.elapsed = response.elapsed
    return buffered


def _read_capped(response: httpx2.Response, cap: int, request: httpx2.Request) -> httpx2.Response:
    """Buffer a streaming sync `response` under `cap` decoded bytes; return a buffered Response.

    Raises `ResponseTooLargeError` (reason="declared") if the declared
    Content-Length already exceeds `cap` — before any byte is read — and
    (reason="streamed") if the decoded body crosses `cap` mid-read. An unencoded
    body is read into `response` itself, which is closed on any error; an encoded
    one is read into a rebuilt Response. Closes `response` once its whole body is read;
    on any other path the caller closes it.
    """
    if not _response_has_body(request.method, response.status_code):
        response.read()  # empty body; preserve the original response (and its headers)
        return response
    content_length = _reject_if_declared_length_exceeds_cap(response, cap)
    if "content-encoding" not in response.headers:
        stream = typing.cast("httpx2.SyncByteStream", response.stream)
        response.stream = _CappedSyncStream(stream, cap, response.status_code, content_length)
        try:
            response.read()
        except BaseException:
            response.close()
            raise
        return response
    try:
        content = _accumulate_capped(response.iter_bytes(), cap)
    except _CapExceeded:
        raise ResponseTooLargeError(
            status_code=response.status_code, limit=cap, content_length=content_length, reason="streamed"
        ) from None
    response.close()
    return _build_buffered_response(response, content, request)


async def _read_capped_async(response: httpx2.Response, cap: int, request: httpx2.Request) -> httpx2.Response:
    """Async mirror of `_read_capped` (counts decoded bytes from `aiter_bytes`)."""
    if not _response_has_body(request.method, response.status_code):
        await response.aread()  # empty body; preserve the original response (and its headers)
        return response
    content_length = _reject_if_declared_length_exceeds_cap(response, cap)
    if "content-encoding" not in response.headers:
        stream = typing.cast("httpx2.AsyncByteStream", response.stream)
        response.stream = _CappedAsyncStream(stream, cap, response.status_code, content_length)
        try:
            await response.aread()
        except BaseException:
            await response.aclose()
            raise
        return response
    buf = bytearray()
    async for chunk in response.aiter_bytes():
        buf += chunk
        if len(buf) > cap:
            raise ResponseTooLargeError(
                status_code=response.status_code, limit=cap, content_length=content_length, reason="streamed"
            )
    await response.aclose()
    return _build_buffered_response(response, bytes(buf), request)


def _fits_declared_length(response: httpx2.Response, cap: int) -> bool:
    """Whether `response` may carry a body within `cap`: no body, or no Content-Length above it."""
    if not _response_has_body(response.request.method, response.status_code):
        return True
    content_length = _parse_content_length(response.headers.get("content-length"))
    return content_length is None or content_length <= cap


def _discard_within_cap(response: httpx2.Response, cap: int) -> None:
    """Read and discard `response`'s body, stopping once it is declared or read past `cap` decoded bytes."""
    if not _fits_declared_length(response, cap):
        return
    read = 0
    for chunk in response.iter_bytes():
        read += len(chunk)
        if read > cap:
            return


async def _discard_within_cap_async(response: httpx2.Response, cap: int) -> None:
    """Async mirror of `_discard_within_cap`."""
    if not _fits_declared_length(response, cap):
        return
    read = 0
    async with contextlib.aclosing(response.aiter_bytes()) as chunks:
        async for chunk in chunks:
            read += len(chunk)
            if read > cap:
                return

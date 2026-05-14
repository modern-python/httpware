"""Httpx2Transport — adapts the httpx2 AsyncClient to the Transport protocol.

This is the only file in `httpware` that imports `httpx2`. The v0
method / header / multi-valued-header contracts are documented on the
`Httpx2Transport` class.
"""

import asyncio
import dataclasses
import json
import time
from contextlib import AbstractAsyncContextManager
from typing import Any

import httpx2

from httpware.config import Limits, Timeout
from httpware.errors import (
    STATUS_TO_EXCEPTION,
    ClientStatusError,
    ServerStatusError,
    TimeoutError,  # noqa: A004
    TransportError,
)
from httpware.request import Request
from httpware.response import Response, StreamResponse


def _try_decode_json(resp: httpx2.Response) -> Any | None:  # noqa: ANN401
    """Best-effort JSON decode of `resp.content`; never raises."""
    content_type = ""
    for key, value in resp.headers.items():
        if key.lower() == "content-type":
            content_type = value
            break
    # Strict match on the bare media type: ``application/json`` only.
    # Splitting on ``;`` strips parameters (e.g. ``; charset=utf-8``) and
    # avoids ``application/jsonpatch`` false-positives that ``startswith``
    # would accept. ``+json`` variants (``application/problem+json``,
    # ``application/vnd.api+json``) are deferred per Open Question (a).
    media_type = content_type.split(";", 1)[0].strip().lower()
    if media_type != "application/json":
        return None
    if not resp.content:
        return None
    try:
        return json.loads(resp.content)
    except json.JSONDecodeError:
        return None


class Httpx2Transport:
    """Default `Transport` implementation backed by `httpx2.AsyncClient`.

    This is the only place in ``httpware`` that imports ``httpx2``. It owns
    three v0 contracts the rest of the library relies on:

    * The wire ``method`` is uppercased at this seam; the
      ``httpware.Request.method`` itself is left untouched.
    * ``headers`` returned to callers (and stored on ``StatusError``) use
      the lowercase ASCII keys that ``httpx2.Response.headers`` already
      emits. A case-insensitive header type is deferred until middleware
      needs it.
    * ``Mapping[str, str]`` is single-valued. ``dict(resp.headers)``
      collapses duplicate-key headers (``Set-Cookie``, ``Via``, ``Link``)
      to the last value only; the multi-valued contract widens together
      with the case-insensitive type in a later story.
    """

    def __init__(
        self,
        *,
        client: httpx2.AsyncClient | None = None,
        limits: Limits | None = None,
        timeout: Timeout | None = None,
    ) -> None:
        """Store the (optionally user-supplied) client and lazy-init config."""
        if client is not None and (limits is not None or timeout is not None):
            msg = "Pass limits/timeout only when client is None."
            raise ValueError(msg)
        self._client: httpx2.AsyncClient | None = client
        self._limits: Limits | None = limits
        self._timeout: Timeout | None = timeout
        self._closed: bool = False
        self._init_lock: asyncio.Lock | None = None

    async def _get_client(self) -> httpx2.AsyncClient:
        if self._closed:
            msg = "Httpx2Transport is closed."
            raise TransportError(msg)
        if self._client is not None:
            return self._client
        if self._init_lock is None:
            self._init_lock = asyncio.Lock()
        async with self._init_lock:
            if self._client is None:
                limits = self._limits or Limits()
                timeout = self._timeout or Timeout()
                httpx2_limits = httpx2.Limits(**dataclasses.asdict(limits))
                httpx2_timeout = httpx2.Timeout(
                    connect=timeout.connect,
                    read=timeout.read,
                    write=timeout.write,
                    pool=timeout.pool,
                )
                self._client = httpx2.AsyncClient(limits=httpx2_limits, timeout=httpx2_timeout)
        return self._client

    async def __call__(self, request: Request) -> Response:
        """Send `request` and return a `Response`, raising on 4xx/5xx."""
        client = await self._get_client()
        method = request.method.upper()
        try:
            httpx2_req = httpx2.Request(
                method=method,
                url=request.url,
                headers=dict(request.headers),
                params=dict(request.params),
                cookies=dict(request.cookies),
                content=request.body,
                extensions=dict(request.extensions),
            )
            start = time.monotonic()
            resp = await client.send(httpx2_req)
        except httpx2.TimeoutException as exc:
            raise TimeoutError(str(exc)) from exc
        except httpx2.HTTPError as exc:
            raise TransportError(str(exc)) from exc
        except (httpx2.InvalidURL, httpx2.CookieConflict) as exc:
            raise TransportError(str(exc)) from exc
        except RuntimeError as exc:
            # ``httpx2.AsyncClient.send`` raises a bare RuntimeError when
            # the client has been closed externally; there is no public
            # attribute we can interrogate ahead of time.
            if "closed" in str(exc):
                raise TransportError(str(exc)) from exc
            raise
        elapsed = time.monotonic() - start
        status = resp.status_code
        # ``dict(...)`` collapses duplicate-key headers (Set-Cookie etc.)
        # to the last value — see class docstring; widens with the
        # multi-valued header contract in a later story.
        headers = dict(resp.headers)
        if 400 <= status < 600:  # noqa: PLR2004
            exc_class = STATUS_TO_EXCEPTION.get(
                status,
                ClientStatusError if status < 500 else ServerStatusError,  # noqa: PLR2004
            )
            raise exc_class(
                status=status,
                body=resp.content,
                headers=headers,
                json=_try_decode_json(resp),
                request_method=method,
                request_url=request.url,
            )
        return Response(
            status=status,
            headers=headers,
            content=resp.content,
            url=str(resp.url),
            elapsed=elapsed,
        )

    def stream(self, request: Request) -> AbstractAsyncContextManager[StreamResponse]:  # noqa: ARG002
        """Open a streaming response — not yet implemented (Story 4.1)."""
        if self._closed:
            msg = "Httpx2Transport is closed."
            raise TransportError(msg)
        msg = "Streaming arrives in Epic 4 (Story 4.1)."
        raise NotImplementedError(msg)

    async def aclose(self) -> None:
        """Close the underlying client; safe to call repeatedly."""
        if self._closed:
            return
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        self._closed = True

"""RecordedTransport — built-in Transport test double."""

from collections.abc import Mapping
from contextlib import AbstractAsyncContextManager

from httpware.request import Request
from httpware.response import Response, StreamResponse


class RecordedTransport:
    """Built-in Transport test double.

    Construct with a route table mapping (method, url) → Response | BaseException.
    `await transport(request)` looks up `(request.method.upper(), request.url)`; on
    match returns the Response or raises the Exception. On no-match, uses the
    `default` (Response, BaseException, or RuntimeError("No route for METHOD URL")
    when None).

    Every call appends the Request to `transport.requests`. Tests can assert on
    `transport.last_request`, iterate `transport.requests`, or count
    `transport.aclose_calls` for lifecycle assertions.

    Routes fire indefinitely — the same (method, url) yields the same canned
    Response on every match. To express "different replies on repeat calls",
    swap the route between calls via `add_route(...)` or construct a new
    transport per call.

    `stream()` raises NotImplementedError; streaming lands in Epic 4 (Story 4-1).
    """

    def __init__(
        self,
        routes: Mapping[tuple[str, str], Response | BaseException] | None = None,
        *,
        default: Response | BaseException | None = None,
    ) -> None:
        self._routes: dict[tuple[str, str], Response | BaseException] = (
            {(m.upper(), u): v for (m, u), v in routes.items()}
            if routes is not None
            else {}
        )
        self._default = default
        self.requests: list[Request] = []
        self.aclose_calls = 0

    @property
    def last_request(self) -> Request | None:
        """The most recently observed Request, or None if no calls have been made."""
        return self.requests[-1] if self.requests else None

    def add_route(
        self,
        method: str,
        url: str,
        response_or_exception: Response | BaseException,
    ) -> None:
        """Add or replace a route entry."""
        self._routes[(method.upper(), url)] = response_or_exception

    async def __call__(self, request: Request) -> Response:
        self.requests.append(request)
        key = (request.method.upper(), request.url)
        result: Response | BaseException | None
        result = self._routes.get(key, self._default)
        if isinstance(result, BaseException):
            raise result
        if result is None:
            msg = f"No route for {request.method} {request.url}"
            raise RuntimeError(msg)
        return result

    def stream(
        self,
        request: Request,
    ) -> AbstractAsyncContextManager[StreamResponse]:
        """Streaming not implemented in v0 — landing in Epic 4 (Story 4-1)."""
        msg = "RecordedTransport.stream() is not implemented; streaming lands in Epic 4"
        raise NotImplementedError(msg)

    async def aclose(self) -> None:
        self.aclose_calls += 1

"""Transport protocol — the middleware ↔ transport seam (Seam 1)."""

from contextlib import AbstractAsyncContextManager
from typing import Protocol, runtime_checkable

from httpware.request import Request
from httpware.response import Response, StreamResponse


@runtime_checkable
class Transport(Protocol):
    """Structural protocol every transport adapter satisfies."""

    async def __call__(self, request: Request) -> Response:
        """Send `request` and return the buffered response."""
        ...

    def stream(self, request: Request) -> AbstractAsyncContextManager[StreamResponse]:
        """Open a streaming response for `request` as an async context manager."""
        ...

    async def aclose(self) -> None:
        """Release any resources held by the transport."""
        ...


__all__ = ["Transport"]

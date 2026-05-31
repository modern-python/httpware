"""Tests for the Middleware protocol and chain composition."""

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from typing import get_type_hints

import pytest

from httpware._internal.chain import compose
from httpware.middleware import Middleware, Next
from httpware.request import Request
from httpware.response import Response, StreamResponse


class _SignalMiddleware:
    """Minimal valid Middleware implementation used by tests."""

    async def __call__(self, request: Request, next: Next) -> Response:  # noqa: A002
        return await next(request)


def test_runtime_checkable_isinstance_works() -> None:
    """A class implementing `__call__` satisfies the Middleware Protocol at runtime."""
    # runtime_checkable checks for presence of __call__, not signature details
    assert isinstance(_SignalMiddleware(), Middleware)


def test_next_type_alias_resolves_to_callable() -> None:
    """`Next` resolves to `Callable[[Request], Awaitable[Response]]`."""
    expected = Callable[[Request], Awaitable[Response]]
    assert Next == expected


def test_next_annotation_on_signal_middleware() -> None:
    """`next` parameter on `_SignalMiddleware.__call__` is annotated with `Next`."""
    hints = get_type_hints(_SignalMiddleware.__call__)
    assert hints["next"] == Next


class _OkTransport:
    """Minimal Transport: returns a fixed Response, no streaming, no aclose work."""

    async def __call__(self, request: Request) -> Response:
        return Response(
            status=200,
            headers={"x-from": "transport"},
            content=b"transport",
            url=request.url,
            elapsed=0.0,
        )

    def stream(  # pragma: no cover - not exercised in 2-1
        self, request: Request
    ) -> AbstractAsyncContextManager[StreamResponse]:
        raise NotImplementedError

    async def aclose(self) -> None:  # pragma: no cover - not exercised in 2-1
        return None


def _make_request(method: str = "GET", url: str = "https://example.test/") -> Request:
    return Request(method=method, url=url)


async def test_empty_list_composes_to_transport_call() -> None:
    """compose([], transport) yields a callable that behaves like transport(req)."""
    transport = _OkTransport()
    dispatch = compose([], transport)

    request = _make_request()
    response = await dispatch(request)

    assert response.status == 200  # noqa: PLR2004
    assert response.content == b"transport"
    assert response.headers["x-from"] == "transport"


async def test_single_middleware_wraps_transport() -> None:
    """One middleware sees the request, calls next, returns the transport's response unchanged."""
    seen: list[Request] = []

    class Tap:
        async def __call__(self, request: Request, next: Next) -> Response:  # noqa: A002
            seen.append(request)
            return await next(request)

    transport = _OkTransport()
    request = _make_request()

    response = await compose([Tap()], transport)(request)

    assert seen == [request]
    assert response.content == b"transport"


async def test_chain_runs_outer_to_inner() -> None:
    """Three middlewares form an onion: outer→inner→transport→inner→outer."""
    log: list[str] = []

    def labeled(name: str) -> Middleware:
        class Labeled:
            async def __call__(self, request: Request, next: Next) -> Response:  # noqa: A002
                log.append(f"{name}:before")
                response = await next(request)
                log.append(f"{name}:after")
                return response

        return Labeled()

    dispatch = compose([labeled("A"), labeled("B"), labeled("C")], _OkTransport())
    await dispatch(_make_request())

    assert log == [
        "A:before",
        "B:before",
        "C:before",
        "C:after",
        "B:after",
        "A:after",
    ]


async def test_middleware_can_transform_request_before_forwarding() -> None:
    """An outer middleware mutates the request via with_header; the inner sees the mutation."""
    seen: list[Request] = []

    class Stamp:
        async def __call__(self, request: Request, next: Next) -> Response:  # noqa: A002
            stamped = request.with_header("x-trace", "abc123")
            return await next(stamped)

    class Inspect:
        async def __call__(self, request: Request, next: Next) -> Response:  # noqa: A002
            seen.append(request)
            return await next(request)

    await compose([Stamp(), Inspect()], _OkTransport())(_make_request())

    assert seen[0].headers["x-trace"] == "abc123"


async def test_middleware_can_transform_response_before_returning() -> None:
    """An outer middleware awaits next, then returns a modified Response; caller sees it."""

    class AddHeader:
        async def __call__(self, request: Request, next: Next) -> Response:  # noqa: A002
            response = await next(request)
            return Response(
                status=response.status,
                headers={**response.headers, "x-trace": "abc123"},
                content=response.content,
                url=response.url,
                elapsed=response.elapsed,
            )

    response = await compose([AddHeader()], _OkTransport())(_make_request())

    assert response.headers["x-trace"] == "abc123"
    assert response.headers["x-from"] == "transport"  # original still present


async def test_short_circuit_returns_synthesized_response() -> None:
    """A middleware that does NOT call next returns a synthesized Response; transport never runs."""
    transport_calls = 0

    class CountingTransport(_OkTransport):
        async def __call__(self, request: Request) -> Response:
            nonlocal transport_calls
            transport_calls += 1
            return await super().__call__(request)

    class ShortCircuit:
        async def __call__(self, request: Request, next: Next) -> Response:  # noqa: A002, ARG002
            return Response(
                status=418,
                headers={},
                content=b"teapot",
                url=request.url,
                elapsed=0.0,
            )

    class NeverReached:
        async def __call__(self, request: Request, next: Next) -> Response:  # noqa: A002, ARG002
            msg = "inner middleware should not be invoked"
            raise AssertionError(msg)

    response = await compose([ShortCircuit(), NeverReached()], CountingTransport())(_make_request())

    assert response.status == 418  # noqa: PLR2004
    assert response.content == b"teapot"
    assert transport_calls == 0


async def test_exception_in_middleware_propagates() -> None:
    """A custom exception raised inside a middleware bubbles through the chain unchanged."""

    class CustomError(Exception):
        pass

    class Boom:
        async def __call__(self, request: Request, next: Next) -> Response:  # noqa: A002, ARG002
            msg = "boom"
            raise CustomError(msg)

    with pytest.raises(CustomError, match="boom"):
        await compose([Boom()], _OkTransport())(_make_request())


async def test_exception_in_transport_propagates_through_chain() -> None:
    """An exception raised by the transport passes through every middleware unmodified."""

    class TransportFail:
        async def __call__(self, request: Request) -> Response:  # noqa: ARG002
            msg = "transport failed"
            raise RuntimeError(msg)

        def stream(  # pragma: no cover - not exercised
            self, request: Request
        ) -> AbstractAsyncContextManager[StreamResponse]:
            raise NotImplementedError

        async def aclose(self) -> None:  # pragma: no cover - not exercised
            return None

    class Passthrough:
        async def __call__(self, request: Request, next: Next) -> Response:  # noqa: A002
            return await next(request)

    with pytest.raises(RuntimeError, match="transport failed"):
        await compose([Passthrough(), Passthrough()], TransportFail())(_make_request())


async def test_cancelled_error_propagates_through_chain() -> None:
    """asyncio.CancelledError raised mid-chain propagates to the caller (NFR15)."""

    class Cancel:
        async def __call__(self, request: Request, next: Next) -> Response:  # noqa: A002, ARG002
            raise asyncio.CancelledError

    class Passthrough:
        async def __call__(self, request: Request, next: Next) -> Response:  # noqa: A002
            return await next(request)

    with pytest.raises(asyncio.CancelledError):
        await compose([Passthrough(), Cancel()], _OkTransport())(_make_request())


async def test_compose_returned_callable_is_reusable() -> None:
    """The Next returned by compose can be awaited sequentially across multiple requests."""
    count = 0

    class Counter:
        async def __call__(self, request: Request, next: Next) -> Response:  # noqa: A002
            nonlocal count
            count += 1
            return await next(request)

    dispatch = compose([Counter()], _OkTransport())

    for _ in range(3):
        response = await dispatch(_make_request())
        assert response.status == 200  # noqa: PLR2004

    assert count == 3  # noqa: PLR2004


def test_middleware_and_next_are_reexported_at_package_root() -> None:
    """`from httpware import Middleware, Next` works in addition to the subpackage path."""
    import httpware  # noqa: PLC0415

    assert httpware.Middleware is Middleware
    assert httpware.Next is Next
    assert "Middleware" in httpware.__all__
    assert "Next" in httpware.__all__

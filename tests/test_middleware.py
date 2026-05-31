"""Tests for the Middleware protocol and chain composition."""

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from typing import get_type_hints

import pytest

import httpware
from httpware._internal.chain import compose
from httpware.middleware import Middleware, Next, after_response, before_request, on_error
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


async def test_before_request_transforms_request() -> None:
    """@before_request wraps an async request transform; downstream sees the mutation."""

    @before_request
    async def stamp(request: Request) -> Request:
        return request.with_header("x-trace", "abc123")

    seen: list[Request] = []

    class Inspect:
        async def __call__(self, request: Request, next: Next) -> Response:  # noqa: A002
            seen.append(request)
            return await next(request)

    await compose([stamp, Inspect()], _OkTransport())(_make_request())

    assert seen[0].headers["x-trace"] == "abc123"


async def test_after_response_transforms_response() -> None:
    """@after_response wraps an async response transform; caller sees the modification."""

    @after_response
    async def add_header(request: Request, response: Response) -> Response:  # noqa: ARG001
        return Response(
            status=response.status,
            headers={**response.headers, "x-trace": "abc123"},
            content=response.content,
            url=response.url,
            elapsed=response.elapsed,
        )

    response = await compose([add_header], _OkTransport())(_make_request())

    assert response.headers["x-trace"] == "abc123"
    assert response.headers["x-from"] == "transport"  # original still present


def test_middleware_and_next_are_reexported_at_package_root() -> None:
    """`from httpware import Middleware, Next` works in addition to the subpackage path."""
    assert httpware.Middleware is Middleware
    assert httpware.Next is Next
    assert "Middleware" in httpware.__all__
    assert "Next" in httpware.__all__


class _FailingTransport:
    """Transport whose __call__ raises a chosen exception."""

    def __init__(self, exc: BaseException) -> None:
        self._exc = exc

    async def __call__(self, request: Request) -> Response:  # noqa: ARG002
        raise self._exc

    def stream(  # pragma: no cover - not exercised in 2-2
        self, request: Request
    ) -> AbstractAsyncContextManager[StreamResponse]:
        raise NotImplementedError

    async def aclose(self) -> None:  # pragma: no cover - not exercised in 2-2
        return None


async def test_on_error_returns_response_swallows_exception() -> None:
    """When the handler returns a Response, the caller gets it; no exception escapes."""

    @on_error
    async def recover(request: Request, exc: Exception) -> Response | None:  # noqa: ARG001
        return Response(
            status=503,
            headers={"x-recovered": "true"},
            content=b"recovered",
            url=request.url,
            elapsed=0.0,
        )

    transport = _FailingTransport(RuntimeError("boom"))
    response = await compose([recover], transport)(_make_request())

    assert response.status == 503  # noqa: PLR2004
    assert response.headers["x-recovered"] == "true"
    assert response.content == b"recovered"


async def test_on_error_returns_none_reraises() -> None:
    """When the handler returns None, the original exception is re-raised with traceback intact."""

    @on_error
    async def pass_through(request: Request, exc: Exception) -> Response | None:  # noqa: ARG001
        return None

    transport = _FailingTransport(RuntimeError("boom"))

    with pytest.raises(RuntimeError, match="boom"):
        await compose([pass_through], transport)(_make_request())


async def test_on_error_does_not_catch_cancelled_error() -> None:
    """asyncio.CancelledError is not Exception; the handler must not be invoked."""
    invocations: list[Exception] = []

    @on_error
    async def should_not_run(request: Request, exc: Exception) -> Response | None:  # noqa: ARG001
        invocations.append(exc)
        return None

    class Cancel:
        async def __call__(self, request: Request, next: Next) -> Response:  # noqa: A002, ARG002
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await compose([should_not_run, Cancel()], _OkTransport())(_make_request())

    assert invocations == []


async def test_on_error_handler_receives_correct_exception_instance() -> None:
    """The handler's `exc` parameter is the same instance the transport raised."""
    raised = RuntimeError("specific instance")
    seen: list[Exception] = []

    @on_error
    async def capture(request: Request, exc: Exception) -> Response | None:  # noqa: ARG001
        seen.append(exc)
        return None

    with pytest.raises(RuntimeError):
        await compose([capture], _FailingTransport(raised))(_make_request())

    assert seen == [raised]
    assert seen[0] is raised


def test_decorators_satisfy_middleware_protocol() -> None:
    """Each decorator returns an object that isinstance() recognizes as Middleware."""

    @before_request
    async def br(request: Request) -> Request:
        return request

    @after_response
    async def ar(request: Request, response: Response) -> Response:  # noqa: ARG001
        return response

    @on_error
    async def oe(request: Request, exc: Exception) -> Response | None:  # noqa: ARG001
        return None

    assert isinstance(br, Middleware)
    assert isinstance(ar, Middleware)
    assert isinstance(oe, Middleware)


async def test_decorated_middlewares_compose_in_chain() -> None:
    """Phase decorators interoperate with class-based middleware in one compose() call."""

    @before_request
    async def stamp(request: Request) -> Request:
        return request.with_header("x-stamp", "1")

    @after_response
    async def tag(request: Request, response: Response) -> Response:  # noqa: ARG001
        return Response(
            status=response.status,
            headers={**response.headers, "x-tag": "1"},
            content=response.content,
            url=response.url,
            elapsed=response.elapsed,
        )

    seen_headers: list[str] = []

    class Inspect:
        async def __call__(self, request: Request, next: Next) -> Response:  # noqa: A002
            seen_headers.append(request.headers.get("x-stamp", ""))
            return await next(request)

    response = await compose([stamp, Inspect(), tag], _OkTransport())(_make_request())

    assert seen_headers == ["1"]  # stamp ran before Inspect
    assert response.headers["x-tag"] == "1"  # tag ran after the chain


def test_repr_shows_original_function_name() -> None:
    """repr() includes the phase name and the original user function's qualname."""

    @before_request
    async def my_stamp(request: Request) -> Request:
        return request

    @after_response
    async def my_tag(request: Request, response: Response) -> Response:  # noqa: ARG001
        return response

    @on_error
    async def my_recover(request: Request, exc: Exception) -> Response | None:  # noqa: ARG001
        return None

    assert "before_request" in repr(my_stamp)
    assert "my_stamp" in repr(my_stamp)
    assert "after_response" in repr(my_tag)
    assert "my_tag" in repr(my_tag)
    assert "on_error" in repr(my_recover)
    assert "my_recover" in repr(my_recover)


def test_decorators_reexported_at_package_root() -> None:
    """`from httpware import before_request, after_response, on_error` works."""
    assert httpware.before_request is before_request
    assert httpware.after_response is after_response
    assert httpware.on_error is on_error
    assert "before_request" in httpware.__all__
    assert "after_response" in httpware.__all__
    assert "on_error" in httpware.__all__

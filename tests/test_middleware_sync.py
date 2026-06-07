"""Tests for the sync Middleware protocol, Next type, chain composition, and decorators."""

from http import HTTPStatus

import httpx2
import pytest

from httpware.middleware import (
    Middleware,
    Next,
    after_response,
    before_request,
    on_error,
)
from httpware.middleware.chain import compose


def _make_request(url: str = "https://example.test/x") -> httpx2.Request:
    return httpx2.Request("GET", url)


def _make_response(status: int = HTTPStatus.OK, *, request: httpx2.Request | None = None) -> httpx2.Response:
    if request is None:  # pragma: no cover
        request = _make_request()
    return httpx2.Response(status, request=request)


def test_middleware_protocol_is_runtime_checkable() -> None:
    class _OkMiddleware:
        def __call__(self, request: httpx2.Request, next: Next) -> httpx2.Response:  # noqa: A002  # pragma: no cover
            return next(request)

    assert isinstance(_OkMiddleware(), Middleware)


def test_empty_chain_calls_terminal_directly() -> None:
    seen: list[httpx2.Request] = []

    def terminal(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return _make_response(200, request=request)

    dispatch = compose((), terminal)
    request = _make_request()
    response = dispatch(request)
    assert response.status_code == HTTPStatus.OK
    assert seen == [request]


def test_chain_runs_middleware_in_order() -> None:
    order: list[str] = []

    class _M:
        def __init__(self, label: str) -> None:
            self.label = label

        def __call__(self, request: httpx2.Request, next: Next) -> httpx2.Response:  # noqa: A002
            order.append(f"{self.label}.before")
            response = next(request)
            order.append(f"{self.label}.after")
            return response

    def terminal(request: httpx2.Request) -> httpx2.Response:
        order.append("terminal")
        return _make_response(200, request=request)

    dispatch = compose((_M("a"), _M("b")), terminal)
    dispatch(_make_request())
    assert order == ["a.before", "b.before", "terminal", "b.after", "a.after"]


def test_before_request_decorator_transforms_request() -> None:
    @before_request
    def add_header(request: httpx2.Request) -> httpx2.Request:
        return httpx2.Request(request.method, request.url, headers={**request.headers, "X-Custom": "1"})

    captured: list[httpx2.Request] = []

    def terminal(request: httpx2.Request) -> httpx2.Response:
        captured.append(request)
        return _make_response(200, request=request)

    dispatch = compose((add_header,), terminal)
    dispatch(_make_request())
    assert captured[0].headers["x-custom"] == "1"


def test_after_response_decorator_transforms_response() -> None:
    @after_response
    def upgrade_status(request: httpx2.Request, response: httpx2.Response) -> httpx2.Response:
        return httpx2.Response(HTTPStatus.IM_USED, request=request, headers=response.headers, content=response.content)

    def terminal(request: httpx2.Request) -> httpx2.Response:
        return _make_response(HTTPStatus.OK, request=request)

    dispatch = compose((upgrade_status,), terminal)
    response = dispatch(_make_request())
    assert response.status_code == HTTPStatus.IM_USED


def test_on_error_decorator_can_translate_exception() -> None:
    @on_error
    def swallow(request: httpx2.Request, exc: Exception) -> httpx2.Response | None:
        if isinstance(exc, RuntimeError) and str(exc) == "boom":
            return _make_response(HTTPStatus.SERVICE_UNAVAILABLE, request=request)
        return None  # pragma: no cover

    def terminal(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        msg = "boom"
        raise RuntimeError(msg)

    dispatch = compose((swallow,), terminal)
    response = dispatch(_make_request())
    assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE


def test_on_error_returns_none_reraises() -> None:
    @on_error
    def passthrough(
        request: httpx2.Request,  # noqa: ARG001
        exc: Exception,  # noqa: ARG001
    ) -> httpx2.Response | None:
        return None

    def terminal(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        msg = "boom"
        raise RuntimeError(msg)

    dispatch = compose((passthrough,), terminal)
    with pytest.raises(RuntimeError, match="boom"):
        dispatch(_make_request())


def test_before_request_repr() -> None:
    @before_request
    def my_transform(request: httpx2.Request) -> httpx2.Request:
        return request  # pragma: no cover

    assert "before_request" in repr(my_transform)
    assert "my_transform" in repr(my_transform)


def test_after_response_repr() -> None:
    @after_response
    def my_transform(request: httpx2.Request, response: httpx2.Response) -> httpx2.Response:  # noqa: ARG001
        return response  # pragma: no cover

    assert "after_response" in repr(my_transform)
    assert "my_transform" in repr(my_transform)


def test_on_error_repr() -> None:
    @on_error
    def my_handler(request: httpx2.Request, exc: Exception) -> httpx2.Response | None:  # noqa: ARG001
        return None  # pragma: no cover

    assert "on_error" in repr(my_handler)
    assert "my_handler" in repr(my_handler)

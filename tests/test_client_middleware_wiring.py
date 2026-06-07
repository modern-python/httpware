"""Tests for AsyncClient ↔ middleware chain integration."""

from http import HTTPStatus

import httpx2
import pytest

from httpware import (
    AsyncClient,
    AsyncNext,
    InternalServerError,
    NotFoundError,
    async_after_response,
    async_before_request,
    async_on_error,
)


async def test_before_request_runs() -> None:
    @async_before_request
    async def add_header(request: httpx2.Request) -> httpx2.Request:
        return httpx2.Request(
            request.method,
            request.url,
            headers={**request.headers, "x-injected": "1"},
        )

    captured: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured.append(request)
        return httpx2.Response(HTTPStatus.OK, request=request)

    transport = httpx2.MockTransport(handler)
    client = AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=transport),
        middleware=(add_header,),
    )
    await client.get("https://example.test/x")
    assert captured[0].headers["x-injected"] == "1"


async def test_after_response_runs() -> None:
    @async_after_response
    async def tag_status(request: httpx2.Request, response: httpx2.Response) -> httpx2.Response:
        return httpx2.Response(
            HTTPStatus.IM_USED,
            request=request,
            headers=response.headers,
            content=response.content,
        )

    transport = httpx2.MockTransport(lambda req: httpx2.Response(HTTPStatus.OK, request=req))
    client = AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=transport),
        middleware=(tag_status,),
    )
    response = await client.get("https://example.test/x")
    assert response.status_code == HTTPStatus.IM_USED


async def test_on_error_catches_status_error() -> None:
    @async_on_error
    async def convert_404(request: httpx2.Request, exc: Exception) -> httpx2.Response | None:
        if isinstance(exc, NotFoundError):
            return httpx2.Response(HTTPStatus.OK, request=request, content=b"recovered")
        return None  # let other exceptions propagate

    transport_404 = httpx2.MockTransport(lambda req: httpx2.Response(HTTPStatus.NOT_FOUND, request=req))
    client = AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=transport_404),
        middleware=(convert_404,),
    )
    response = await client.get("https://example.test/x")
    assert response.status_code == HTTPStatus.OK
    assert response.content == b"recovered"

    # Also exercise the return-None branch (non-404 → passes through to re-raise).
    transport_500 = httpx2.MockTransport(lambda req: httpx2.Response(HTTPStatus.INTERNAL_SERVER_ERROR, request=req))
    client2 = AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=transport_500),
        middleware=(convert_404,),
    )
    with pytest.raises(InternalServerError):
        await client2.get("https://example.test/x")


async def test_middleware_runs_outer_to_inner_then_inner_to_outer() -> None:
    order: list[str] = []

    class _Tag:
        def __init__(self, name: str) -> None:
            self.name = name

        async def __call__(self, request: httpx2.Request, next: AsyncNext) -> httpx2.Response:  # noqa: A002
            order.append(f"{self.name}.in")
            response = await next(request)
            order.append(f"{self.name}.out")
            return response

    transport = httpx2.MockTransport(lambda req: httpx2.Response(HTTPStatus.OK, request=req))
    client = AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=transport),
        middleware=(_Tag("a"), _Tag("b")),
    )
    await client.get("https://example.test/x")
    assert order == ["a.in", "b.in", "b.out", "a.out"]

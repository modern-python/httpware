"""max_response_body_bytes with follow_redirects=True: httpware follows the hops itself, under the cap."""

from collections.abc import AsyncIterator, Callable, Iterator
from http import HTTPStatus

import httpx2
import pytest

from httpware import AsyncClient, Client
from httpware.errors import ResponseTooLargeError, TransportError


def _looping(request: httpx2.Request) -> httpx2.Response:
    return httpx2.Response(HTTPStatus.FOUND, headers={"location": request.url.path + "x"})


def _authorization_seen(seen: dict[tuple[str, str], str | None], location: str) -> httpx2.MockTransport:
    def handler(request: httpx2.Request) -> httpx2.Response:
        seen[request.url.host, request.url.path] = request.headers.get("authorization")
        if request.url.path == "/start":
            return httpx2.Response(HTTPStatus.FOUND, headers={"location": location})
        return httpx2.Response(HTTPStatus.OK)

    return httpx2.MockTransport(handler)


def _redirecting(request: httpx2.Request) -> httpx2.Response:
    if request.url.path == "/start":
        return httpx2.Response(HTTPStatus.FOUND, headers={"location": "/final"})
    return httpx2.Response(HTTPStatus.OK, content=b"done")


def _huge_intermediate_body(pulled: list[bytes]) -> httpx2.MockTransport:
    async def huge_body() -> AsyncIterator[bytes]:
        for _ in range(100):
            pulled.append(b"x" * 1024)
            yield pulled[-1]

    return _redirect_with_body(huge_body)


def _huge_intermediate_body_sync(pulled: list[bytes]) -> httpx2.MockTransport:
    def huge_body() -> Iterator[bytes]:
        for _ in range(100):
            pulled.append(b"x" * 1024)
            yield pulled[-1]

    return _redirect_with_body(huge_body)


def _redirect_with_body(body: Callable[[], AsyncIterator[bytes] | Iterator[bytes]]) -> httpx2.MockTransport:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/start":
            return httpx2.Response(HTTPStatus.FOUND, headers={"location": "/final"}, content=body())
        return httpx2.Response(HTTPStatus.OK, content=b"done")

    return httpx2.MockTransport(handler)


async def test_async_follows_redirects_under_a_body_cap() -> None:
    async with AsyncClient(
        transport=httpx2.MockTransport(_redirecting),
        follow_redirects=True,
        max_response_body_bytes=1024,
    ) as client:
        response = await client.get("https://example.test/start")
    assert response.status_code == HTTPStatus.OK
    assert response.content == b"done"
    assert str(response.url) == "https://example.test/final"


async def test_async_never_reads_an_intermediate_redirect_body() -> None:
    pulled: list[bytes] = []
    async with AsyncClient(
        transport=_huge_intermediate_body(pulled),
        follow_redirects=True,
        max_response_body_bytes=1024,
    ) as client:
        response = await client.get("https://example.test/start")
    assert response.content == b"done"
    assert pulled == []


async def test_async_stream_never_reads_an_intermediate_redirect_body() -> None:
    pulled: list[bytes] = []
    async with (
        AsyncClient(
            transport=_huge_intermediate_body(pulled),
            follow_redirects=True,
            max_response_body_bytes=1024,
        ) as client,
        client.stream("GET", "https://example.test/start") as response,
    ):
        body = await response.aread()
    assert body == b"done"
    assert pulled == []


async def test_async_records_redirect_history_under_a_body_cap() -> None:
    async with AsyncClient(
        transport=httpx2.MockTransport(_redirecting),
        follow_redirects=True,
        max_response_body_bytes=1024,
    ) as client:
        response = await client.get("https://example.test/start")
    assert [(hop.status_code, str(hop.url)) for hop in response.history] == [
        (HTTPStatus.FOUND, "https://example.test/start")
    ]


async def test_async_rejects_a_final_body_over_the_cap_after_redirects() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/start":
            return httpx2.Response(HTTPStatus.FOUND, headers={"location": "/final"})
        return httpx2.Response(HTTPStatus.OK, content=b"x" * 2048)

    async with AsyncClient(
        transport=httpx2.MockTransport(handler),
        follow_redirects=True,
        max_response_body_bytes=1024,
    ) as client:
        with pytest.raises(ResponseTooLargeError):
            await client.get("https://example.test/start")


@pytest.mark.parametrize("cap", [None, 1024])
async def test_async_too_many_redirects_is_the_same_error_with_or_without_a_cap(cap: int | None) -> None:
    async with AsyncClient(
        transport=httpx2.MockTransport(_looping),
        follow_redirects=True,
        max_redirects=3,
        max_response_body_bytes=cap,
    ) as client:
        with pytest.raises(TransportError, match="Exceeded maximum allowed redirects") as caught:
            await client.get("https://example.test/a")
    assert type(caught.value) is TransportError


@pytest.mark.parametrize(
    ("location", "expected"),
    [
        (
            "/final",
            {("example.test", "/start"): "Basic dTpw", ("example.test", "/final"): "Basic dTpw"},
        ),
        (
            "https://other.test/final",
            {("example.test", "/start"): "Basic dTpw", ("other.test", "/final"): None},
        ),
    ],
)
async def test_async_client_auth_does_not_follow_a_redirect_to_another_origin(
    location: str,
    expected: dict[tuple[str, str], str | None],
) -> None:
    seen: dict[tuple[str, str], str | None] = {}
    async with AsyncClient(
        transport=_authorization_seen(seen, location),
        auth=httpx2.BasicAuth("u", "p"),
        follow_redirects=True,
        max_response_body_bytes=1024,
    ) as client:
        await client.get("https://example.test/start")
    assert seen == expected


async def test_async_caller_provided_client_follows_redirects_under_a_body_cap() -> None:
    caller = httpx2.AsyncClient(transport=httpx2.MockTransport(_redirecting), follow_redirects=True)
    async with AsyncClient(httpx2_client=caller, max_response_body_bytes=1024) as client:
        response = await client.get("https://example.test/start")
    await caller.aclose()
    assert response.content == b"done"


def test_sync_never_reads_an_intermediate_redirect_body() -> None:
    pulled: list[bytes] = []
    with Client(
        transport=_huge_intermediate_body_sync(pulled),
        follow_redirects=True,
        max_response_body_bytes=1024,
    ) as client:
        response = client.get("https://example.test/start")
    assert response.content == b"done"
    assert pulled == []


def test_sync_stream_never_reads_an_intermediate_redirect_body() -> None:
    pulled: list[bytes] = []
    with (
        Client(
            transport=_huge_intermediate_body_sync(pulled),
            follow_redirects=True,
            max_response_body_bytes=1024,
        ) as client,
        client.stream("GET", "https://example.test/start") as response,
    ):
        body = response.read()
    assert body == b"done"
    assert pulled == []


def test_sync_follows_redirects_under_a_body_cap() -> None:
    with Client(
        transport=httpx2.MockTransport(_redirecting),
        follow_redirects=True,
        max_response_body_bytes=1024,
    ) as client:
        response = client.get("https://example.test/start")
    assert response.status_code == HTTPStatus.OK
    assert response.content == b"done"
    assert str(response.url) == "https://example.test/final"


def test_sync_records_redirect_history_under_a_body_cap() -> None:
    with Client(
        transport=httpx2.MockTransport(_redirecting),
        follow_redirects=True,
        max_response_body_bytes=1024,
    ) as client:
        response = client.get("https://example.test/start")
    assert [(hop.status_code, str(hop.url)) for hop in response.history] == [
        (HTTPStatus.FOUND, "https://example.test/start")
    ]


def test_sync_rejects_a_final_body_over_the_cap_after_redirects() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/start":
            return httpx2.Response(HTTPStatus.FOUND, headers={"location": "/final"})
        return httpx2.Response(HTTPStatus.OK, content=b"x" * 2048)

    with (
        Client(
            transport=httpx2.MockTransport(handler),
            follow_redirects=True,
            max_response_body_bytes=1024,
        ) as client,
        pytest.raises(ResponseTooLargeError),
    ):
        client.get("https://example.test/start")


@pytest.mark.parametrize("cap", [None, 1024])
def test_sync_too_many_redirects_is_the_same_error_with_or_without_a_cap(cap: int | None) -> None:
    with (
        Client(
            transport=httpx2.MockTransport(_looping),
            follow_redirects=True,
            max_redirects=3,
            max_response_body_bytes=cap,
        ) as client,
        pytest.raises(TransportError, match="Exceeded maximum allowed redirects") as caught,
    ):
        client.get("https://example.test/a")
    assert type(caught.value) is TransportError


@pytest.mark.parametrize(
    ("location", "expected"),
    [
        (
            "/final",
            {("example.test", "/start"): "Basic dTpw", ("example.test", "/final"): "Basic dTpw"},
        ),
        (
            "https://other.test/final",
            {("example.test", "/start"): "Basic dTpw", ("other.test", "/final"): None},
        ),
    ],
)
def test_sync_client_auth_does_not_follow_a_redirect_to_another_origin(
    location: str,
    expected: dict[tuple[str, str], str | None],
) -> None:
    seen: dict[tuple[str, str], str | None] = {}
    with Client(
        transport=_authorization_seen(seen, location),
        auth=httpx2.BasicAuth("u", "p"),
        follow_redirects=True,
        max_response_body_bytes=1024,
    ) as client:
        client.get("https://example.test/start")
    assert seen == expected


def test_sync_caller_provided_client_follows_redirects_under_a_body_cap() -> None:
    caller = httpx2.Client(transport=httpx2.MockTransport(_redirecting), follow_redirects=True)
    with Client(httpx2_client=caller, max_response_body_bytes=1024) as client:
        response = client.get("https://example.test/start")
    caller.close()
    assert response.content == b"done"

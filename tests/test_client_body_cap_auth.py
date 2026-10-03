"""max_response_body_bytes with a multi-step auth flow: intermediate auth responses stay under the cap."""

import typing
from collections.abc import AsyncIterator, Callable, Generator, Iterator
from http import HTTPStatus

import httpx2
import pytest

from httpware import AsyncClient, Client
from httpware.errors import ResponseTooLargeError, TransportError


_CHALLENGE = 'Digest realm="api", nonce="abc", qop="auth"'


class _TokenRefreshAuth(httpx2.Auth):
    requires_response_body = True

    def auth_flow(self, request: httpx2.Request) -> Generator[httpx2.Request, httpx2.Response]:
        response = yield request
        if response.status_code == HTTPStatus.UNAUTHORIZED:
            token_response = yield httpx2.Request("POST", "https://example.test/token")
            request.headers["authorization"] = f"Bearer {token_response.json()['token']}"
            yield request


def _token_endpoint(token_padding: int) -> httpx2.MockTransport:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/token":
            return httpx2.Response(HTTPStatus.OK, json={"token": "fresh", "padding": "x" * token_padding})
        if request.headers.get("authorization") == "Bearer fresh":
            return httpx2.Response(HTTPStatus.OK, content=b"done")
        return httpx2.Response(HTTPStatus.UNAUTHORIZED)

    return httpx2.MockTransport(handler)


def _digest_challenge(body: Callable[[], AsyncIterator[bytes] | Iterator[bytes]]) -> httpx2.MockTransport:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.headers.get("authorization", "").startswith("Digest "):
            return httpx2.Response(HTTPStatus.OK, content=b"done")
        return httpx2.Response(HTTPStatus.UNAUTHORIZED, headers={"www-authenticate": _CHALLENGE}, content=body())

    return httpx2.MockTransport(handler)


def _huge_challenge_body(pulled: list[bytes]) -> httpx2.MockTransport:
    async def huge_body() -> AsyncIterator[bytes]:
        for _ in range(100):
            pulled.append(b"x" * 1024)
            yield pulled[-1]

    return _digest_challenge(huge_body)


def _huge_challenge_body_sync(pulled: list[bytes]) -> httpx2.MockTransport:
    def huge_body() -> Iterator[bytes]:
        for _ in range(100):
            pulled.append(b"x" * 1024)
            yield pulled[-1]

    return _digest_challenge(huge_body)


@pytest.mark.parametrize(("cap", "challenge_read"), [(None, True), (1024, False)])
async def test_async_reads_a_digest_challenge_body_only_without_a_cap(
    cap: int | None,
    challenge_read: bool,
) -> None:
    pulled: list[bytes] = []
    async with AsyncClient(
        transport=_huge_challenge_body(pulled),
        auth=httpx2.DigestAuth("u", "p"),
        max_response_body_bytes=cap,
    ) as client:
        response = await client.get("https://example.test/")
    assert response.content == b"done"
    assert bool(pulled) is challenge_read


@pytest.mark.parametrize(("cap", "challenge_read"), [(None, True), (1024, False)])
def test_sync_reads_a_digest_challenge_body_only_without_a_cap(
    cap: int | None,
    challenge_read: bool,
) -> None:
    pulled: list[bytes] = []
    with Client(
        transport=_huge_challenge_body_sync(pulled),
        auth=httpx2.DigestAuth("u", "p"),
        max_response_body_bytes=cap,
    ) as client:
        response = client.get("https://example.test/")
    assert response.content == b"done"
    assert bool(pulled) is challenge_read


async def test_async_auth_flow_reading_bodies_gets_them_under_the_cap() -> None:
    async with AsyncClient(
        transport=_token_endpoint(token_padding=0),
        auth=_TokenRefreshAuth(),
        max_response_body_bytes=1024,
    ) as client:
        response = await client.get("https://example.test/")
    assert response.content == b"done"


async def test_async_auth_flow_reading_bodies_rejects_one_over_the_cap() -> None:
    async with AsyncClient(
        transport=_token_endpoint(token_padding=2048),
        auth=_TokenRefreshAuth(),
        max_response_body_bytes=1024,
    ) as client:
        with pytest.raises(ResponseTooLargeError):
            await client.get("https://example.test/")


def test_sync_auth_flow_reading_bodies_gets_them_under_the_cap() -> None:
    with Client(
        transport=_token_endpoint(token_padding=0),
        auth=_TokenRefreshAuth(),
        max_response_body_bytes=1024,
    ) as client:
        response = client.get("https://example.test/")
    assert response.content == b"done"


def test_sync_auth_flow_reading_bodies_rejects_one_over_the_cap() -> None:
    with (
        Client(
            transport=_token_endpoint(token_padding=2048),
            auth=_TokenRefreshAuth(),
            max_response_body_bytes=1024,
        ) as client,
        pytest.raises(ResponseTooLargeError),
    ):
        client.get("https://example.test/")


def _echo_authorization(request: httpx2.Request) -> httpx2.Response:
    return httpx2.Response(HTTPStatus.OK, content=request.headers.get("authorization", "").encode())


@pytest.mark.parametrize("cap", [None, 1024])
async def test_async_url_credentials_authenticate_with_or_without_a_cap(cap: int | None) -> None:
    async with AsyncClient(transport=httpx2.MockTransport(_echo_authorization), max_response_body_bytes=cap) as client:
        response = await client.get("https://u:p@example.test/")
    assert response.content == b"Basic dTpw"


@pytest.mark.parametrize("cap", [None, 1024])
def test_sync_url_credentials_authenticate_with_or_without_a_cap(cap: int | None) -> None:
    with Client(transport=httpx2.MockTransport(_echo_authorization), max_response_body_bytes=cap) as client:
        response = client.get("https://u:p@example.test/")
    assert response.content == b"Basic dTpw"


def _digest_behind_redirect(request: httpx2.Request) -> httpx2.Response:
    if request.url.path == "/start":
        return httpx2.Response(HTTPStatus.FOUND, headers={"location": "/final"})
    if request.headers.get("authorization", "").startswith("Digest "):
        return httpx2.Response(HTTPStatus.OK, content=b"done")
    return httpx2.Response(HTTPStatus.UNAUTHORIZED, headers={"www-authenticate": _CHALLENGE})


def _history_shape(response: httpx2.Response) -> list[tuple[int, str, list[typing.Any]]]:
    return [(hop.status_code, hop.url.path, _history_shape(hop)) for hop in response.history]


def _malformed_challenge(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
    return httpx2.Response(HTTPStatus.UNAUTHORIZED, headers={"www-authenticate": 'Digest realm="api"'})


@pytest.mark.parametrize("cap", [None, 1024])
async def test_async_digest_after_a_redirect_is_the_same_with_or_without_a_cap(cap: int | None) -> None:
    async with AsyncClient(
        transport=httpx2.MockTransport(_digest_behind_redirect),
        auth=httpx2.DigestAuth("u", "p"),
        follow_redirects=True,
        max_response_body_bytes=cap,
    ) as client:
        response = await client.get("https://example.test/start")
    assert response.content == b"done"
    assert _history_shape(response) == [
        (HTTPStatus.UNAUTHORIZED, "/final", []),
        (HTTPStatus.FOUND, "/start", [(HTTPStatus.UNAUTHORIZED, "/final", [])]),
    ]


@pytest.mark.parametrize("cap", [None, 1024])
def test_sync_digest_after_a_redirect_is_the_same_with_or_without_a_cap(cap: int | None) -> None:
    with Client(
        transport=httpx2.MockTransport(_digest_behind_redirect),
        auth=httpx2.DigestAuth("u", "p"),
        follow_redirects=True,
        max_response_body_bytes=cap,
    ) as client:
        response = client.get("https://example.test/start")
    assert response.content == b"done"
    assert _history_shape(response) == [
        (HTTPStatus.UNAUTHORIZED, "/final", []),
        (HTTPStatus.FOUND, "/start", [(HTTPStatus.UNAUTHORIZED, "/final", [])]),
    ]


@pytest.mark.parametrize("cap", [None, 1024])
async def test_async_auth_flow_error_is_the_same_with_or_without_a_cap(cap: int | None) -> None:
    async with AsyncClient(
        transport=httpx2.MockTransport(_malformed_challenge),
        auth=httpx2.DigestAuth("u", "p"),
        max_response_body_bytes=cap,
    ) as client:
        with pytest.raises(TransportError, match="Malformed Digest") as caught:
            await client.get("https://example.test/")
    assert type(caught.value) is TransportError


@pytest.mark.parametrize("cap", [None, 1024])
def test_sync_auth_flow_error_is_the_same_with_or_without_a_cap(cap: int | None) -> None:
    with (
        Client(
            transport=httpx2.MockTransport(_malformed_challenge),
            auth=httpx2.DigestAuth("u", "p"),
            max_response_body_bytes=cap,
        ) as client,
        pytest.raises(TransportError, match="Malformed Digest") as caught,
    ):
        client.get("https://example.test/")
    assert type(caught.value) is TransportError


@pytest.mark.parametrize("cap", [None, 1024])
async def test_async_auth_steps_count_toward_max_redirects_with_or_without_a_cap(cap: int | None) -> None:
    async with AsyncClient(
        transport=httpx2.MockTransport(_digest_behind_redirect),
        auth=httpx2.DigestAuth("u", "p"),
        max_redirects=0,
        max_response_body_bytes=cap,
    ) as client:
        with pytest.raises(TransportError, match="Exceeded maximum allowed redirects"):
            await client.get("https://example.test/final")


@pytest.mark.parametrize("cap", [None, 1024])
def test_sync_auth_steps_count_toward_max_redirects_with_or_without_a_cap(cap: int | None) -> None:
    with (
        Client(
            transport=httpx2.MockTransport(_digest_behind_redirect),
            auth=httpx2.DigestAuth("u", "p"),
            max_redirects=0,
            max_response_body_bytes=cap,
        ) as client,
        pytest.raises(TransportError, match="Exceeded maximum allowed redirects"),
    ):
        client.get("https://example.test/final")


async def test_async_stream_never_reads_a_digest_challenge_body_under_a_cap() -> None:
    pulled: list[bytes] = []
    async with (
        AsyncClient(
            transport=_huge_challenge_body(pulled),
            auth=httpx2.DigestAuth("u", "p"),
            max_response_body_bytes=1024,
        ) as client,
        client.stream("GET", "https://example.test/") as response,
    ):
        body = await response.aread()
    assert body == b"done"
    assert pulled == []


def test_sync_stream_never_reads_a_digest_challenge_body_under_a_cap() -> None:
    pulled: list[bytes] = []
    with (
        Client(
            transport=_huge_challenge_body_sync(pulled),
            auth=httpx2.DigestAuth("u", "p"),
            max_response_body_bytes=1024,
        ) as client,
        client.stream("GET", "https://example.test/") as response,
    ):
        body = response.read()
    assert body == b"done"
    assert pulled == []


async def test_async_stream_rejects_an_auth_read_body_over_the_cap() -> None:
    async with AsyncClient(
        transport=_token_endpoint(token_padding=2048),
        auth=_TokenRefreshAuth(),
        max_response_body_bytes=1024,
    ) as client:
        with pytest.raises(ResponseTooLargeError):
            async with client.stream("GET", "https://example.test/"):
                pytest.fail("unreachable")  # pragma: no cover — stream() raises on enter


def test_sync_stream_rejects_an_auth_read_body_over_the_cap() -> None:
    with (
        Client(
            transport=_token_endpoint(token_padding=2048),
            auth=_TokenRefreshAuth(),
            max_response_body_bytes=1024,
        ) as client,
        pytest.raises(ResponseTooLargeError),
        client.stream("GET", "https://example.test/"),
    ):
        pytest.fail("unreachable")  # pragma: no cover — stream() raises on enter

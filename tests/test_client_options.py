"""httpx2 client options are forwarded to the owned httpx2 client by both worlds."""

import inspect
import ssl
import typing
from http import HTTPStatus
from unittest.mock import patch

import httpx2
import pytest

from httpware import AsyncClient, Client
from httpware.client import _AsyncClientOptions, _ClientOptions


_EXCLUDED = {"cert", "event_hooks"}


def _ok(request: httpx2.Request) -> httpx2.Response:
    return httpx2.Response(HTTPStatus.OK, request=request)


def _samples() -> dict[str, typing.Any]:
    transport = httpx2.MockTransport(_ok)
    return {
        "base_url": "https://example.test",
        "headers": {"x": "1"},
        "params": {"x": "1"},
        "cookies": {"x": "1"},
        "timeout": 5.0,
        "limits": httpx2.Limits(max_connections=10),
        "auth": httpx2.BasicAuth("u", "p"),
        "verify": ssl.create_default_context(),
        "trust_env": False,
        "http1": False,
        "http2": True,
        "proxy": "http://proxy.test:8080",
        "follow_redirects": True,
        "max_redirects": 3,
        "default_encoding": "latin-1",
        "mounts": {"http://": transport},
        "transport": transport,
    }


_KEYS = sorted(_samples())


_WORLDS = [
    pytest.param(AsyncClient, "AsyncClient", id="async"),
    pytest.param(Client, "Client", id="sync"),
]


@pytest.mark.parametrize(
    ("httpx2_name", "option_keys"),
    [
        pytest.param("AsyncClient", _AsyncClientOptions.__optional_keys__, id="async"),
        pytest.param("Client", _ClientOptions.__optional_keys__, id="sync"),
    ],
)
def test_options_cover_every_httpx2_client_kwarg_except_excluded(httpx2_name: str, option_keys: frozenset[str]) -> None:
    httpx2_kwargs = set(inspect.signature(getattr(httpx2, httpx2_name).__init__).parameters) - {"self"}

    assert option_keys == httpx2_kwargs - _EXCLUDED
    assert set(_KEYS) == option_keys


@pytest.mark.parametrize("key", _KEYS)
@pytest.mark.parametrize(("client_cls", "httpx2_name"), _WORLDS)
def test_option_is_forwarded_to_owned_httpx2_client(
    client_cls: type,
    httpx2_name: str,
    key: str,
) -> None:
    value = _samples()[key]
    with patch.object(httpx2, httpx2_name) as httpx2_cls:
        client_cls(**{key: value})

    httpx2_cls.assert_called_once_with(**{key: value})


@pytest.mark.parametrize(("client_cls", "httpx2_name"), _WORLDS)
def test_unset_options_are_not_forwarded(
    client_cls: type,
    httpx2_name: str,
) -> None:
    with patch.object(httpx2, httpx2_name) as httpx2_cls:
        client_cls(base_url="", headers=None, timeout=None, proxy=None, transport=None)

    httpx2_cls.assert_called_once_with()


@pytest.mark.parametrize("key", _KEYS)
@pytest.mark.parametrize(("client_cls", "httpx2_name"), _WORLDS)
def test_option_with_caller_owned_httpx2_client_is_typeerror(
    client_cls: type,
    httpx2_name: str,
    key: str,
) -> None:
    caller = getattr(httpx2, httpx2_name)(transport=httpx2.MockTransport(_ok))
    with pytest.raises(TypeError, match=f"httpx2_client.*{key}"):
        client_cls(httpx2_client=caller, **{key: _samples()[key]})


@pytest.mark.parametrize("key", ["cert", "event_hooks", "verfy"])
@pytest.mark.parametrize("client_cls", [AsyncClient, Client])
def test_unsupported_option_is_typeerror(client_cls: type, key: str) -> None:
    with pytest.raises(TypeError, match=key):
        client_cls(**{key: object()})


def test_type_checkers_reject_unsupported_async_options() -> None:
    with pytest.raises(TypeError, match="verfy"):
        AsyncClient(verfy=True)  # ty: ignore[unknown-argument]
    with pytest.raises(TypeError, match="cert"):
        AsyncClient(cert="client.pem")  # ty: ignore[unknown-argument]


def test_type_checkers_reject_unsupported_sync_options() -> None:
    with pytest.raises(TypeError, match="verfy"):
        Client(verfy=True)  # ty: ignore[unknown-argument]
    with pytest.raises(TypeError, match="cert"):
        Client(cert="client.pem")  # ty: ignore[unknown-argument]


@pytest.mark.parametrize("client_cls", [AsyncClient, Client])
def test_follow_redirects_with_body_cap_is_valueerror(client_cls: type) -> None:
    with pytest.raises(ValueError, match="follow_redirects"):
        client_cls(follow_redirects=True, max_response_body_bytes=1024)


@pytest.mark.parametrize(("client_cls", "httpx2_name"), _WORLDS)
def test_caller_owned_client_following_redirects_with_body_cap_is_valueerror(
    client_cls: type,
    httpx2_name: str,
) -> None:
    caller = getattr(httpx2, httpx2_name)(follow_redirects=True)
    with pytest.raises(ValueError, match="follow_redirects"):
        client_cls(httpx2_client=caller, max_response_body_bytes=1024)


@pytest.mark.parametrize("client_cls", [AsyncClient, Client])
def test_body_cap_without_following_redirects_is_accepted(client_cls: type) -> None:
    client_cls(follow_redirects=False, max_response_body_bytes=1024)


async def test_async_transport_option_keeps_the_httpx2_client_owned() -> None:
    async with AsyncClient(transport=httpx2.MockTransport(_ok)) as client:
        response = await client.get("https://example.test/")
    assert response.status_code == HTTPStatus.OK
    assert client._httpx2_client.is_closed  # noqa: SLF001


def test_sync_transport_option_keeps_the_httpx2_client_owned() -> None:
    with Client(transport=httpx2.MockTransport(_ok)) as client:
        response = client.get("https://example.test/")
    assert response.status_code == HTTPStatus.OK
    assert client._httpx2_client.is_closed  # noqa: SLF001

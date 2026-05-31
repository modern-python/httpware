"""Unit tests for httpware.client.AsyncClient construction."""

# ruff: noqa: SLF001

from httpware import AsyncClient, Limits, RecordedTransport, Timeout
from httpware.decoders.pydantic import PydanticDecoder
from httpware.middleware import Middleware
from httpware.request import Request
from httpware.response import Response
from httpware.transports.httpx2 import Httpx2Transport


def test_init_defaults_provide_transport_and_decoder() -> None:
    client = AsyncClient()
    assert isinstance(client._transport, Httpx2Transport)
    assert isinstance(client._config.decoder, PydanticDecoder)
    assert client._config.middleware == ()


def test_init_accepts_explicit_transport() -> None:
    transport = RecordedTransport()
    client = AsyncClient(transport=transport)
    assert client._transport is transport


def test_init_accepts_explicit_decoder() -> None:
    decoder = PydanticDecoder()
    client = AsyncClient(decoder=decoder)
    assert client._config.decoder is decoder


def test_init_accepts_middleware_sequence() -> None:
    class _M:
        async def __call__(self, request: Request, next) -> Response:  # noqa: A002, ANN001
            return await next(request)

    middleware: list[Middleware] = [_M()]
    client = AsyncClient(middleware=middleware)
    assert client._config.middleware == tuple(middleware)


def test_init_normalizes_float_timeout() -> None:
    client = AsyncClient(timeout=2.5)
    assert client._config.timeout == Timeout(connect=2.5, read=2.5, write=2.5, pool=2.5)


def test_init_keeps_timeout_instance() -> None:
    t = Timeout(connect=1.0, read=60.0, write=10.0, pool=2.0)
    client = AsyncClient(timeout=t)
    assert client._config.timeout is t


def test_init_normalizes_none_timeout() -> None:
    client = AsyncClient(timeout=None)
    assert client._config.timeout == Timeout()


def test_init_default_limits() -> None:
    client = AsyncClient()
    assert client._config.limits == Limits()


def test_from_url_classmethod_sets_base_url() -> None:
    client = AsyncClient.from_url("https://api.example.com/v1")
    assert client._config.base_url == "https://api.example.com/v1"


def test_init_owns_transport_by_default() -> None:
    client = AsyncClient()
    assert client._owns_transport is True


def test_construction_does_not_create_httpx2_client() -> None:
    """Construction is side-effect-free; the httpx2.AsyncClient is lazily created on first request."""
    client = AsyncClient()
    # Httpx2Transport stores `_client` lazily; until first call, _client is None.
    # The attribute is private; we check it via getattr to keep the test resilient.
    assert getattr(client._transport, "_client", "missing") is None


def test_init_no_auth_means_no_auth_middleware() -> None:
    transport = RecordedTransport()
    client = AsyncClient(transport=transport)
    assert client._config.middleware == ()
    assert client._auth is None
    assert client._user_middleware == ()


def test_init_with_string_auth_appends_bearer_middleware() -> None:
    transport = RecordedTransport()
    client = AsyncClient(transport=transport, auth="tok")
    assert len(client._config.middleware) == 1
    assert isinstance(client._config.middleware[0], Middleware)
    assert client._auth == "tok"
    assert client._user_middleware == ()


def test_init_with_user_middleware_plus_auth() -> None:
    class _M:
        async def __call__(self, request, next) -> Response:  # noqa: A002, ANN001
            return await next(request)

    m1 = _M()
    m2 = _M()
    transport = RecordedTransport()
    client = AsyncClient(transport=transport, middleware=[m1, m2], auth="tok")
    _expected_len = 3
    assert len(client._config.middleware) == _expected_len
    assert client._config.middleware[0] is m1
    assert client._config.middleware[1] is m2
    # The third entry is the auth middleware; identity-test that user_middleware excludes it.
    assert client._user_middleware == (m1, m2)

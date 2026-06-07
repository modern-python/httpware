"""Tests for the sync Client — construction, methods, lifecycle, error mapping."""

from http import HTTPStatus

import httpx2
import pytest

from httpware import Client, NotFoundError
from httpware.decoders.pydantic import PydanticDecoder


# ---------- Construction ----------


def test_construction_with_no_args_works() -> None:
    client = Client()
    assert isinstance(client, Client)
    client.close()


def test_construction_with_forwarded_kwargs() -> None:
    client = Client(
        base_url="https://example.test",
        headers={"x-shared": "1"},
        params={"trace": "yes"},
        timeout=10.0,
    )
    assert isinstance(client, Client)
    client.close()


def test_construction_with_caller_owned_httpx2_client() -> None:
    transport = httpx2.MockTransport(lambda req: httpx2.Response(200, request=req))
    caller = httpx2.Client(transport=transport)
    client = Client(httpx2_client=caller)
    assert isinstance(client, Client)
    caller.close()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"base_url": "https://example.test"},
        {"headers": {"x": "1"}},
        {"params": {"x": "1"}},
        {"cookies": {"x": "1"}},
        {"timeout": 5.0},
        {"limits": httpx2.Limits(max_connections=10)},
        {"auth": httpx2.BasicAuth("u", "p")},
    ],
)
def test_caller_owned_client_with_forwarded_kwargs_is_typeerror(kwargs: dict) -> None:
    transport = httpx2.MockTransport(lambda req: httpx2.Response(200, request=req))
    caller = httpx2.Client(transport=transport)
    with pytest.raises(TypeError, match="httpx2_client"):
        Client(httpx2_client=caller, **kwargs)
    caller.close()


def test_default_decoder_is_pydantic_decoder() -> None:
    client = Client()
    assert isinstance(client._decoder, PydanticDecoder)  # noqa: SLF001
    client.close()


def test_explicit_decoder_is_honored() -> None:
    class _Stub:
        def decode(self, content: bytes, model: type) -> object:  # noqa: ARG002  # pragma: no cover
            return None

    client = Client(decoder=_Stub())
    assert isinstance(client._decoder, _Stub)  # noqa: SLF001
    client.close()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"cookies": {"session": "abc"}},
        {"limits": httpx2.Limits(max_connections=5)},
        {"auth": httpx2.BasicAuth("user", "pass")},
    ],
)
def test_construction_with_optional_forwarded_kwargs(kwargs: dict) -> None:
    """Exercises cookies/limits/auth branches in __init__ when no httpx2_client is supplied."""
    client = Client(**kwargs)
    assert isinstance(client, Client)
    client.close()


def test_explicit_middleware_is_honored() -> None:
    class _Tag:
        def __call__(self, request, next) -> httpx2.Response:  # noqa: A002, ANN001  # pragma: no cover
            return next(request)

    client = Client(middleware=(_Tag(),))
    assert len(client._user_middleware) == 1  # noqa: SLF001
    client.close()


# ---------- Methods ----------


def _echo_handler(request: httpx2.Request) -> httpx2.Response:
    return httpx2.Response(
        HTTPStatus.OK,
        request=request,
        json={
            "method": request.method,
            "url": str(request.url),
            "headers": dict(request.headers),
            "content": request.content.decode() if request.content else "",
        },
    )


def _client_with_handler(handler, **kwargs) -> Client:  # noqa: ANN001, ANN003
    transport = httpx2.MockTransport(handler)
    return Client(httpx2_client=httpx2.Client(transport=transport, **kwargs))


def test_get_returns_httpx2_response() -> None:
    client = _client_with_handler(_echo_handler)
    response = client.get("https://example.test/x")
    assert isinstance(response, httpx2.Response)
    assert response.json()["method"] == "GET"


@pytest.mark.parametrize(
    "method_name",
    ["get", "post", "put", "patch", "delete", "head", "options"],
)
def test_each_per_method_helper_uses_correct_verb(method_name: str) -> None:
    client = _client_with_handler(_echo_handler)
    method = getattr(client, method_name)
    response = method("https://example.test/x")
    assert response.json()["method"] == method_name.upper()


def test_post_json_body_serialized() -> None:
    client = _client_with_handler(_echo_handler)
    response = client.post("https://example.test/x", json={"k": "v"})
    payload = response.json()
    assert "application/json" in payload["headers"]["content-type"]
    assert payload["content"] == '{"k":"v"}'


def test_get_with_params_forwards_query() -> None:
    captured: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured.append(request)
        return httpx2.Response(HTTPStatus.OK, request=request)

    client = _client_with_handler(handler)
    client.get("https://example.test/x", params={"a": "1"})
    assert "a=1" in str(captured[0].url)


def test_get_with_headers_merges() -> None:
    captured: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured.append(request)
        return httpx2.Response(HTTPStatus.OK, request=request)

    client = _client_with_handler(handler)
    client.get("https://example.test/x", headers={"x-trace": "abc"})
    assert captured[0].headers["x-trace"] == "abc"


def test_get_raises_typed_status_error_on_404() -> None:
    client = _client_with_handler(lambda req: httpx2.Response(HTTPStatus.NOT_FOUND, request=req))
    with pytest.raises(NotFoundError):
        client.get("https://example.test/missing")


def test_request_method_takes_arbitrary_verb() -> None:
    client = _client_with_handler(_echo_handler)
    response = client.request("PROPFIND", "https://example.test/x")
    assert response.json()["method"] == "PROPFIND"


def test_base_url_is_applied() -> None:
    captured: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured.append(request)
        return httpx2.Response(HTTPStatus.OK, request=request)

    transport = httpx2.MockTransport(handler)
    underlying = httpx2.Client(transport=transport, base_url="https://example.test")
    client = Client(httpx2_client=underlying)
    client.get("/relative")
    assert str(captured[0].url) == "https://example.test/relative"


def test_get_with_cookies_forwarded() -> None:
    """Exercises the cookies branch in _request_with_body."""
    captured: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured.append(request)
        return httpx2.Response(HTTPStatus.OK, request=request)

    client = _client_with_handler(handler)
    client.get("https://example.test/x", cookies={"token": "abc"})
    assert "token=abc" in captured[0].headers.get("cookie", "")


def test_get_with_explicit_timeout() -> None:
    """Exercises the timeout branch in _request_with_body."""
    client = _client_with_handler(_echo_handler)
    response = client.get("https://example.test/x", timeout=5.0)
    assert response.status_code == HTTPStatus.OK


def test_get_with_extensions() -> None:
    """Exercises the extensions branch in _request_with_body."""
    client = _client_with_handler(_echo_handler)
    response = client.get("https://example.test/x", extensions={"trace": True})
    assert response.status_code == HTTPStatus.OK


def test_post_with_content_body() -> None:
    """Exercises the content branch in _request_with_body."""
    client = _client_with_handler(_echo_handler)
    response = client.post("https://example.test/x", content=b"raw-bytes")
    assert response.json()["content"] == "raw-bytes"


def test_post_with_data_body() -> None:
    """Exercises the data branch in _request_with_body."""
    client = _client_with_handler(_echo_handler)
    response = client.post("https://example.test/x", data={"field": "value"})
    assert response.status_code == HTTPStatus.OK


def test_post_with_files_body() -> None:
    """Exercises the files branch in _request_with_body."""
    client = _client_with_handler(_echo_handler)
    response = client.post("https://example.test/x", files={"upload": b"file-content"})
    assert response.status_code == HTTPStatus.OK


def test_runtime_error_without_closed_reraises() -> None:
    """Exercises the RuntimeError re-raise branch in _terminal (error not containing 'closed')."""

    def boom(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        msg = "unexpected internal failure"
        raise RuntimeError(msg)

    client = _client_with_handler(boom)
    with pytest.raises(RuntimeError, match="unexpected internal failure"):
        client.get("https://example.test/x")


def test_terminal_runtime_error_with_closed_maps_to_transport_error() -> None:
    """A RuntimeError mentioning 'closed' should be remapped to TransportError."""
    from httpware.errors import TransportError

    transport = httpx2.MockTransport(lambda req: httpx2.Response(HTTPStatus.OK, request=req))
    underlying = httpx2.Client(transport=transport)
    client = Client(httpx2_client=underlying)
    underlying.close()
    with pytest.raises(TransportError):
        client.get("https://example.test/x")


def test_send_with_response_model_decodes() -> None:
    """Exercises the response_model decode path in send()."""
    import pydantic

    class _User(pydantic.BaseModel):
        id: int  # noqa: A003
        name: str

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(HTTPStatus.OK, request=request, json={"id": 1, "name": "alice"})

    client = _client_with_handler(handler)
    user = client.get("https://example.test/u", response_model=_User)
    assert isinstance(user, _User)
    assert user.id == 1
    assert user.name == "alice"


def test_build_request_delegates_to_underlying() -> None:
    client = _client_with_handler(_echo_handler)
    req = client.build_request("GET", "https://example.test/x")
    assert isinstance(req, httpx2.Request)
    assert req.method == "GET"


# ---------- Lifecycle ----------


def test_exit_closes_owned_httpx2_client() -> None:
    client = Client()
    with client:
        pass
    assert client._httpx2_client.is_closed  # noqa: SLF001


def test_exit_does_not_close_borrowed_httpx2_client() -> None:
    transport = httpx2.MockTransport(lambda req: httpx2.Response(HTTPStatus.OK, request=req))
    underlying = httpx2.Client(transport=transport)
    client = Client(httpx2_client=underlying)
    with client:
        pass
    assert not underlying.is_closed
    underlying.close()


def test_exit_is_idempotent_for_owned_client() -> None:
    client = Client()
    with client:
        pass
    # Second use should not raise
    client.__exit__(None, None, None)


def test_close_closes_owned_httpx2_client() -> None:
    client = Client()
    client.close()
    assert client._httpx2_client.is_closed  # noqa: SLF001


def test_close_is_idempotent_for_owned_client() -> None:
    client = Client()
    client.close()
    client.close()
    assert client._httpx2_client.is_closed  # noqa: SLF001


def test_close_does_not_close_borrowed_httpx2_client() -> None:
    transport = httpx2.MockTransport(lambda req: httpx2.Response(HTTPStatus.OK, request=req))
    underlying = httpx2.Client(transport=transport)
    client = Client(httpx2_client=underlying)
    client.close()
    assert not underlying.is_closed
    underlying.close()

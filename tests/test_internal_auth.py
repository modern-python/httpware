"""Unit tests for httpware._internal.auth._normalize_auth."""

import pytest

from httpware._internal.auth import _normalize_auth
from httpware.middleware import Next
from httpware.request import Request
from httpware.response import Response


def _make_request(headers: dict[str, str] | None = None) -> Request:
    return Request(method="GET", url="/foo", headers=headers or {})


def _ok_response() -> Response:
    return Response(status=200, headers={}, content=b"", url="/foo", elapsed=0.0)


async def _identity_next(request: Request) -> Response:  # noqa: ARG001
    return _ok_response()


def test_none_returns_none() -> None:
    assert _normalize_auth(None) is None


async def test_string_returns_bearer_middleware() -> None:
    mw = _normalize_auth("token")
    assert mw is not None

    seen: list[Request] = []

    async def _capture_next(request: Request) -> Response:
        seen.append(request)
        return _ok_response()

    await mw(_make_request(), _capture_next)

    assert seen[0].headers["Authorization"] == "Bearer token"


async def test_string_bearer_skips_if_authorization_already_present() -> None:
    mw = _normalize_auth("ignored")
    assert mw is not None

    seen: list[Request] = []

    async def _capture_next(request: Request) -> Response:
        seen.append(request)
        return _ok_response()

    await mw(_make_request(headers={"Authorization": "Basic xyz"}), _capture_next)

    assert seen[0].headers["Authorization"] == "Basic xyz"


async def test_sync_callable_returns_token_provider_middleware() -> None:
    mw = _normalize_auth(lambda: "sync-tok")
    assert mw is not None

    seen: list[Request] = []

    async def _capture_next(request: Request) -> Response:
        seen.append(request)
        return _ok_response()

    await mw(_make_request(), _capture_next)

    assert seen[0].headers["Authorization"] == "Bearer sync-tok"


async def test_async_callable_returns_token_provider_middleware() -> None:
    async def _provider() -> str:
        return "async-tok"

    mw = _normalize_auth(_provider)
    assert mw is not None

    seen: list[Request] = []

    async def _capture_next(request: Request) -> Response:
        seen.append(request)
        return _ok_response()

    await mw(_make_request(), _capture_next)

    assert seen[0].headers["Authorization"] == "Bearer async-tok"


async def test_callable_token_provider_skips_if_authorization_already_present() -> None:
    calls = 0

    def _provider() -> str:
        nonlocal calls
        calls += 1
        return "should-not-set"

    mw = _normalize_auth(_provider)
    assert mw is not None

    seen: list[Request] = []

    async def _capture_next(request: Request) -> Response:
        seen.append(request)
        return _ok_response()

    await mw(_make_request(headers={"authorization": "Basic existing"}), _capture_next)

    assert seen[0].headers["authorization"] == "Basic existing"
    assert calls == 0


async def test_callable_token_provider_calls_provider_per_request() -> None:
    calls = 0

    def _provider() -> str:
        nonlocal calls
        calls += 1
        return f"tok-{calls}"

    mw = _normalize_auth(_provider)
    assert mw is not None

    async def _ok_next(request: Request) -> Response:  # noqa: ARG001
        return _ok_response()

    await mw(_make_request(), _ok_next)
    await mw(_make_request(), _ok_next)
    await mw(_make_request(), _ok_next)

    assert calls == 3  # noqa: PLR2004


async def test_middleware_returned_unchanged() -> None:
    class _PassthroughMw:
        async def __call__(self, request: Request, next: Next) -> Response:  # noqa: A002
            return await next(request)

    mw = _PassthroughMw()
    assert _normalize_auth(mw) is mw


def test_one_arg_callable_raises_typeerror() -> None:
    with pytest.raises(TypeError, match=r"`auth=`.*0 args.*2 args.*1"):
        _normalize_auth(lambda x: "tok")  # noqa: ARG005 — intentional 1-arg callable


def test_non_callable_non_string_non_middleware_raises_typeerror() -> None:
    with pytest.raises(TypeError, match=r"`auth=`.*string.*Middleware.*int"):
        _normalize_auth(42)  # ty: ignore[invalid-argument-type]

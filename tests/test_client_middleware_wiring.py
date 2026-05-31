"""Unit tests for AsyncClient middleware wiring through compose() and with_options."""

from httpware import AsyncClient, RecordedTransport
from httpware.middleware import Middleware, Next
from httpware.request import Request
from httpware.response import Response


def _make_transport() -> RecordedTransport:
    return RecordedTransport(
        default=Response(
            status=200,
            headers={},
            content=b"",
            url="/",
            elapsed=0.0,
        )
    )


def _make_recording_middleware(label: str, log: list[str]) -> Middleware:
    class _M:
        async def __call__(self, request: Request, next: Next) -> Response:  # noqa: A002
            log.append(label)
            return await next(request)

    return _M()


async def test_middleware_runs_per_request() -> None:
    transport = _make_transport()
    log: list[str] = []
    client = AsyncClient(
        transport=transport,
        middleware=[_make_recording_middleware("A", log)],
    )
    await client.get("/foo")
    assert log == ["A"]
    assert len(transport.requests) == 1


async def test_with_options_recomposes_middleware() -> None:
    transport = _make_transport()
    parent_log: list[str] = []
    view_log: list[str] = []
    client = AsyncClient(
        transport=transport,
        middleware=[_make_recording_middleware("parent", parent_log)],
    )
    view = client.with_options(
        middleware=[_make_recording_middleware("view", view_log)],
    )
    await view.get("/foo")
    assert view_log == ["view"]
    assert parent_log == []  # parent's middleware does NOT run for view calls


async def test_with_options_inherits_middleware_when_unset() -> None:
    transport = _make_transport()
    log: list[str] = []
    client = AsyncClient(
        transport=transport,
        middleware=[_make_recording_middleware("inherited", log)],
    )
    view = client.with_options(timeout=10)
    await view.get("/foo")
    assert log == ["inherited"]


async def test_view_shares_transport_with_parent() -> None:
    transport = _make_transport()
    client = AsyncClient(transport=transport)
    view = client.with_options(timeout=10)
    assert view._transport is client._transport  # noqa: SLF001


async def test_view_does_not_own_transport() -> None:
    client = AsyncClient()
    view = client.with_options(timeout=10)
    assert view._owns_transport is False  # noqa: SLF001


async def test_with_options_overrides_base_url() -> None:
    transport = _make_transport()
    client = AsyncClient(transport=transport, base_url="https://api.test/v1")
    view = client.with_options(base_url="https://other.test/v2")
    assert view._config.base_url == "https://other.test/v2"  # noqa: SLF001


async def test_with_options_overrides_default_headers() -> None:
    transport = _make_transport()
    client = AsyncClient(transport=transport, default_headers={"x-old": "1"})
    view = client.with_options(default_headers={"x-new": "2"})
    assert view._config.default_headers == {"x-new": "2"}  # noqa: SLF001


async def test_with_options_overrides_default_query() -> None:
    transport = _make_transport()
    client = AsyncClient(transport=transport, default_query={"old": "1"})
    view = client.with_options(default_query={"new": "2"})
    assert view._config.default_query == {"new": "2"}  # noqa: SLF001


async def test_with_options_overrides_decoder() -> None:
    transport = _make_transport()

    class _NoopDecoder:
        def decode(self, content: bytes, model: type) -> object:  # pragma: no cover  # noqa: ARG002
            return content

    new_decoder = _NoopDecoder()
    client = AsyncClient(transport=transport)
    view = client.with_options(decoder=new_decoder)
    assert view._config.decoder is new_decoder  # noqa: SLF001

"""Unit tests for AsyncClient HTTP method shortcuts."""

from contextlib import AbstractAsyncContextManager

import pytest

from httpware import AsyncClient
from httpware.request import Request
from httpware.response import Response, StreamResponse


class _RecordingTransport:
    """Captures the last-seen Request and returns a canned Response."""

    def __init__(self) -> None:
        self.last_request: Request | None = None
        self.canned = Response(
            status=200,
            headers={"x-from": "transport"},
            content=b"body",
            url="https://example.test/",
            elapsed=0.0,
        )

    async def __call__(self, request: Request) -> Response:
        self.last_request = request
        return self.canned

    def stream(  # pragma: no cover - not exercised
        self, request: Request
    ) -> AbstractAsyncContextManager[StreamResponse]:
        raise NotImplementedError

    async def aclose(self) -> None:  # pragma: no cover - not exercised
        return None


async def test_get_builds_request_with_method_and_url() -> None:
    transport = _RecordingTransport()
    client = AsyncClient(transport=transport)

    await client.get("https://api.example.com/users")

    assert transport.last_request is not None
    assert transport.last_request.method == "GET"
    assert transport.last_request.url == "https://api.example.com/users"
    assert transport.last_request.body is None


async def test_relative_path_joins_with_base_url() -> None:
    transport = _RecordingTransport()
    client = AsyncClient(base_url="https://api.example.com/v1", transport=transport)
    await client.get("/users")
    assert transport.last_request is not None
    assert transport.last_request.url == "https://api.example.com/v1/users"


async def test_relative_path_without_leading_slash_joins_same_way() -> None:
    transport = _RecordingTransport()
    client = AsyncClient(base_url="https://api.example.com/v1", transport=transport)
    await client.get("users")
    assert transport.last_request is not None
    assert transport.last_request.url == "https://api.example.com/v1/users"


async def test_absolute_url_bypasses_base_url() -> None:
    transport = _RecordingTransport()
    client = AsyncClient(base_url="https://api.example.com/v1", transport=transport)
    await client.get("https://other.com/foo")
    assert transport.last_request is not None
    assert transport.last_request.url == "https://other.com/foo"


async def test_default_headers_merged_with_per_call_headers() -> None:
    transport = _RecordingTransport()
    client = AsyncClient(
        default_headers={"x-keep": "1", "x-override": "default"},
        transport=transport,
    )
    await client.get("/", headers={"x-override": "per-call", "x-add": "2"})
    assert transport.last_request is not None
    assert transport.last_request.headers == {
        "x-keep": "1",
        "x-override": "per-call",
        "x-add": "2",
    }


async def test_default_query_merged_with_per_call_params() -> None:
    transport = _RecordingTransport()
    client = AsyncClient(default_query={"k": "default"}, transport=transport)
    await client.get("/", params={"k": "per-call", "extra": "1"})
    assert transport.last_request is not None
    assert transport.last_request.params == {"k": "per-call", "extra": "1"}


async def test_post_with_json_serializes_and_sets_content_type() -> None:
    transport = _RecordingTransport()
    client = AsyncClient(transport=transport)
    await client.post("/users", json={"name": "alice"})
    assert transport.last_request is not None
    assert transport.last_request.method == "POST"
    assert transport.last_request.body == b'{"name": "alice"}'
    assert transport.last_request.headers["content-type"] == "application/json"


async def test_post_with_content_preserves_bytes_unchanged() -> None:
    transport = _RecordingTransport()
    client = AsyncClient(transport=transport)
    await client.post("/users", content=b"raw bytes")
    assert transport.last_request is not None
    assert transport.last_request.body == b"raw bytes"
    assert "content-type" not in transport.last_request.headers


async def test_post_json_and_content_raises_typeerror() -> None:
    transport = _RecordingTransport()
    client = AsyncClient(transport=transport)
    with pytest.raises(TypeError, match="`json` or `content`"):
        await client.post("/users", json={"a": 1}, content=b"raw")


async def test_post_per_call_content_type_skips_auto_injection() -> None:
    transport = _RecordingTransport()
    client = AsyncClient(transport=transport)
    await client.post(
        "/users",
        json={"a": 1},
        headers={"Content-Type": "application/vnd.custom+json"},
    )
    assert transport.last_request is not None
    # The user-supplied Content-Type wins; the auto-injection is skipped because the case-insensitive
    # check finds an existing entry.
    assert transport.last_request.headers["Content-Type"] == "application/vnd.custom+json"


@pytest.mark.parametrize(
    ("client_method_name", "expected_wire_method"),
    [
        ("get", "GET"),
        ("post", "POST"),
        ("put", "PUT"),
        ("patch", "PATCH"),
        ("delete", "DELETE"),
        ("head", "HEAD"),
        ("options", "OPTIONS"),
    ],
)
async def test_each_method_emits_correct_wire_method(
    client_method_name: str, expected_wire_method: str
) -> None:
    transport = _RecordingTransport()
    client = AsyncClient(transport=transport)
    method = getattr(client, client_method_name)
    await method("/foo")
    assert transport.last_request is not None
    assert transport.last_request.method == expected_wire_method


async def test_request_method_uses_first_positional_method_arg() -> None:
    transport = _RecordingTransport()
    client = AsyncClient(transport=transport)
    await client.request("CUSTOM", "/foo")
    assert transport.last_request is not None
    assert transport.last_request.method == "CUSTOM"

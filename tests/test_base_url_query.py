"""A `base_url` carrying a query string is rejected at construction."""

import httpx2
import pytest

from httpware import AsyncClient, Client


_BASE_URL_WITH_QUERY = "https://example.test/api?key=secret"


def test_async_client_rejects_base_url_with_query() -> None:
    with pytest.raises(ValueError, match="query string") as exc_info:
        AsyncClient(base_url=_BASE_URL_WITH_QUERY)
    assert "secret" not in str(exc_info.value)


def test_sync_client_rejects_base_url_with_query() -> None:
    with pytest.raises(ValueError, match="query string") as exc_info:
        Client(base_url=_BASE_URL_WITH_QUERY)
    assert "secret" not in str(exc_info.value)


def test_async_client_rejects_caller_owned_httpx2_client_base_url_with_query() -> None:
    with pytest.raises(ValueError, match="query string"):
        AsyncClient(httpx2_client=httpx2.AsyncClient(base_url=_BASE_URL_WITH_QUERY))


def test_sync_client_rejects_caller_owned_httpx2_client_base_url_with_query() -> None:
    with pytest.raises(ValueError, match="query string"):
        Client(httpx2_client=httpx2.Client(base_url=_BASE_URL_WITH_QUERY))


@pytest.mark.parametrize(
    "base_url", ["", "https://example.test", "https://example.test/api/", "https://example.test/#f"]
)
def test_base_url_without_query_is_accepted(base_url: str) -> None:
    assert Client(base_url=base_url)
    assert AsyncClient(base_url=base_url)

"""Type-checked verification that AsyncClient.{get,post,...} overloads narrow correctly.

This file is checked by `ty` as part of `just lint-ci`. If the @overload
declarations are wrong, the typed assignments below fail to type-check.

The runtime test below just ensures the module imports cleanly so coverage
notices the file.
"""

from pydantic import BaseModel

from httpware import AsyncClient, Response


class _Item(BaseModel):
    name: str


async def _check_overload_types(client: AsyncClient) -> None:
    # No response_model → Response
    resp: Response = await client.get("/foo")
    assert resp is not None

    # response_model=type[T] → T
    item: _Item = await client.get("/foo", response_model=_Item)
    assert item is not None

    # POST: same pattern
    resp_post: Response = await client.post("/foo", json={"a": 1})
    item_post: _Item = await client.post("/foo", json={"a": 1}, response_model=_Item)
    assert resp_post is not None
    assert item_post is not None

    # request(method, path, ...) shape
    resp_req: Response = await client.request("PURGE", "/foo")
    item_req: _Item = await client.request("PURGE", "/foo", response_model=_Item)
    assert resp_req is not None
    assert item_req is not None


def test_typing_module_imports_cleanly() -> None:
    """Runtime stub so coverage notices this file is reachable; ty does the real work."""
    assert AsyncClient is not None

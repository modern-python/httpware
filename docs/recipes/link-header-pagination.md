# Link header pagination

GitLab, GitHub, and other APIs paginate via the [RFC 5988](https://datatracker.ietf.org/doc/html/rfc5988) `Link` response header: each page response carries a `Link: <…>; rel="next"` header pointing to the next page. To walk all pages you need both the decoded body **and** the response headers from the same call — `client.get(..., response_model=...)` returns only the body.

`send_with_response` returns both atomically. It routes the decoded body through the configured `ResponseDecoder`, so decoder failures surface as `DecodeError` — caught by `except httpware.ClientError` like every other failure mode.

## The pagination loop

```python
from httpware import AsyncClient
from pydantic import BaseModel


class Tag(BaseModel):
    name: str


async def main() -> None:
    async with AsyncClient(base_url="https://gitlab.example/api/v4") as client:
        url = "/projects/1/repository/tags"
        params: dict[str, str] | None = {"per_page": "100", "page": "1"}
        while url:
            request = client.build_request("GET", url, params=params)
            response, tags = await client.send_with_response(request, response_model=list[Tag])
            for tag in tags:
                process(tag)
            url = next_link(response.headers.get("link"))   # caller's parser
            params = None                                    # next link carries query
```

`process` and `next_link` are caller-defined. Pick a Link-header parser that fits your project — there are several on PyPI, and the format is small enough to hand-roll.

## When to use which API

- **Body only, high-level verb:** `client.get(..., response_model=...)`
- **Body only, custom `Request`:** `client.send(request, response_model=...)`
- **Body + response metadata:** `client.send_with_response(request, response_model=...)`

`send_with_response` is not for streaming responses — use [`stream()`](../index.md#streaming-responses) for those.

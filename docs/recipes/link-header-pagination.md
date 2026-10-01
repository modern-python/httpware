# Link header pagination

GitLab, GitHub and other APIs paginate with the [RFC 5988](https://datatracker.ietf.org/doc/html/rfc5988) `Link` header: each page carries a `Link: <…>; rel="next"` header that points to the next one. Walking the pages takes both the decoded body and the headers of each response, but `client.get(..., response_model=...)` returns only the body.

`send_with_response` returns the response and the decoded body together. Decoding goes through the client's decoders as usual, so a bad body raises `DecodeError`, which `except httpware.ClientError` catches like any other failure.

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
            url = next_link(response.headers.get("link"))  # caller's parser
            params = None  # next link carries query
```

`process` and `next_link` are yours to write. There are several Link header parsers on PyPI, and the format is small enough to parse by hand.

## Shorthand: per-verb `*_with_response`

If you don't need to build the `Request` yourself, each verb has a `*_with_response` method that does both steps in one call:

```python
# two-step (pre-built request, required when you need full Request control)
request = client.build_request("GET", url, params=params)
response, tags = await client.send_with_response(request, response_model=list[Tag])

# one-call shorthand (equivalent for the simple case)
response, tags = await client.get_with_response(url, params=params, response_model=list[Tag])
```

The methods are `get_with_response`, `post_with_response`, `put_with_response`, `patch_with_response`, `delete_with_response` and `request_with_response`. For HEAD and OPTIONS, use `request_with_response`.

## When to use which API

| You need | From a URL | From a `Request` you built |
|---|---|---|
| The body | `client.get(url, response_model=...)` | `client.send(request, response_model=...)` |
| The body and the response | `client.get_with_response(url, response_model=...)` | `client.send_with_response(request, response_model=...)` |

None of these stream. For streaming responses, use [`stream()`](../index.md#streaming-responses).

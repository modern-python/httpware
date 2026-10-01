# Errors reference

Every exception httpware raises subclasses `ClientError`. A response with a 4xx or 5xx status raises a `StatusError` subclass for that status, so you never call `response.raise_for_status()`.

`Client` and `AsyncClient` raise the same classes, so `from httpware import NotFoundError` works for both. The resilience middleware that raise `RetryBudgetExhaustedError`, `BulkheadFullError` and `CircuitOpenError` are described in [Resilience](resilience.md).

## The exception tree

```
ClientError                          (catch-all for anything httpware raises)
├── TransportError                   (connection, network or protocol failure before a response)
│   └── NetworkError                 (transient and safe to retry; AsyncRetry retries it by default)
├── TimeoutError                     (also a builtins.TimeoutError, so except OSError catches it)
├── StatusError                      (got a response but its status was 4xx/5xx)
│   ├── ClientStatusError            (any 4xx; raised as is for unmapped 4xx codes)
│   │   ├── BadRequestError          (400)
│   │   ├── UnauthorizedError        (401)
│   │   ├── ForbiddenError           (403)
│   │   ├── NotFoundError            (404)
│   │   ├── ConflictError            (409)
│   │   ├── UnprocessableEntityError (422)
│   │   └── RateLimitedError         (429)
│   └── ServerStatusError            (any 5xx; raised as is for unmapped 5xx codes)
│       ├── InternalServerError     (500)
│       └── ServiceUnavailableError (503)
├── RetryBudgetExhaustedError       (a retry was needed but the budget refused)
├── BulkheadFullError                (acquire_timeout elapsed before a slot opened)
├── CircuitOpenError                 (circuit is OPEN or HALF_OPEN probe slot taken; request not forwarded)
├── DecodeError                      (response_model= decoder failed; HTTP call itself succeeded)
├── MissingDecoderError              (no registered decoder claims response_model=; fires before the HTTP call)
└── ResponseTooLargeError            (response body exceeds max_response_body_bytes; status-agnostic)
```

## Status-to-exception mapping

| Status | Exception class |
|---|---|
| 400 | `BadRequestError` |
| 401 | `UnauthorizedError` |
| 403 | `ForbiddenError` |
| 404 | `NotFoundError` |
| 409 | `ConflictError` |
| 422 | `UnprocessableEntityError` |
| 429 | `RateLimitedError` |
| 500 | `InternalServerError` |
| 503 | `ServiceUnavailableError` |
| other 4xx | `ClientStatusError` (fallback) |
| other 5xx | `ServerStatusError` (fallback) |

Only statuses from 400 to 599 raise. Any other status returns the response unchanged.

The numbered rows are exported as `STATUS_TO_EXCEPTION`, a `Mapping[int, type[StatusError]]`, so you can look up a class in code with `STATUS_TO_EXCEPTION.get(404)`. The two fallback rows are not in the mapping.

## Catching strategies

The examples below assume a module logger in your own namespace (not under `httpware.*`): `_LOGGER = logging.getLogger("myapp")`.

```python
import logging

from httpware import (
    AsyncClient,
    ClientError,
    StatusError,
    NetworkError,
    TimeoutError,
    NotFoundError,
    RetryBudgetExhaustedError,
    BulkheadFullError,
)

_LOGGER = logging.getLogger("myapp")


async def fetch(client: AsyncClient, user_id: int) -> dict | None:
    try:
        return await client.get(f"/users/{user_id}", response_model=dict)
    except NotFoundError:
        # The most specific catch: treat a missing user as None.
        return None
    except StatusError as exc:
        # Any other 4xx or 5xx. exc.response has the headers, body and request.
        _LOGGER.warning("upstream returned %s for %s", exc.response.status_code, exc.response.request.url)
        raise
    except NetworkError:
        # Transient transport failure. If the client has AsyncRetry, an idempotent
        # request was already retried and this is the last attempt's error.
        raise
    except (RetryBudgetExhaustedError, BulkheadFullError) as exc:
        # A resilience middleware refused the call; ease off upstream.
        _LOGGER.error("resilience refused: %s", exc)
        raise
    except ClientError:
        # Anything else httpware raised.
        raise
```

`httpware.TimeoutError` also subclasses `builtins.TimeoutError`, the class `asyncio.wait_for` raises, so `except builtins.TimeoutError` and `except OSError` both catch it.

## `exc.response.*` access pattern

For any `StatusError` subclass, the raw `httpx2.Response` is on `exc.response`:

```python
exc.response.status_code  # 404
exc.response.headers  # httpx2.Headers, case-insensitive
exc.response.content  # raw bytes
exc.response.text  # decoded body
exc.response.json()  # parsed JSON (raises if not JSON)
exc.response.request  # the failing httpx2.Request
exc.response.request.url  # the failing URL (httpx2.URL)
exc.response.request.method  # the HTTP method
```

The exception's `repr` and message strip `user:pass@` userinfo and mask the values of known-sensitive query and URL-fragment parameters (`api_key`, `apikey`, `access_token`, `refresh_token`, `token`, `secret`, `client_secret`, `password`, `passwd`, `pwd`, `auth`, `authorization`, `sig`, `signature`, `key`, `private_key`, `session`, `sessionid`, `x-api-key`) as `REDACTED`, keeping the keys. Values under other names are left as they are, so avoid putting other secrets in query strings. Request headers such as `Authorization` and `Cookie` are never redacted, and `exc.response.request.headers` returns them in full.

## Resilience-error payloads

`RetryBudgetExhaustedError` carries:
- `last_response: httpx2.Response | None`: the last response before the budget refused, or `None` if every failure was at the transport level.
- `last_exception: BaseException | None`: the last exception before the budget refused.
- `attempts: int`: how many attempts were completed.

`BulkheadFullError` carries:
- `max_concurrent: int`: the configured cap.
- `acquire_timeout: float | None`: the configured timeout.

`CircuitOpenError` carries:
- `retry_after: float | None`: seconds until the circuit admits its next probe, or `None` when a probe is already in flight.

You can use these fields in your own logging and alerts:

```python
except RetryBudgetExhaustedError as exc:
    _LOGGER.error(
        "budget exhausted after %d attempts; last_status=%s",
        exc.attempts,
        exc.last_response.status_code if exc.last_response is not None else None,
    )
```

## `DecodeError`

`DecodeError` means the HTTP call succeeded but the decoder could not turn the body into the `response_model=` type. Every decoder's failures are wrapped this way, whether it is `PydanticDecoder`, `MsgspecDecoder` or your own, so `except httpware.ClientError` covers decoding too.

Fields:

- `response: httpx2.Response`: the response whose body failed to decode, with its status, headers and `request`.
- `model: type`: the type passed as `response_model=`.
- `original: BaseException`: the decoder's own exception, such as `pydantic.ValidationError`, `msgspec.ValidationError` or `msgspec.DecodeError`. It is also `exc.__cause__`.

```python
from httpware import AsyncClient, DecodeError


try:
    user = await client.get("/users/1", response_model=User)
except DecodeError as exc:
    _LOGGER.error(
        "decode failed for %s into %s: %s",
        exc.response.request.url,
        exc.model.__name__,
        exc.original,
    )
    raise
```

## `MissingDecoderError`

`send()`, `send_with_response()` and the verb methods raise `MissingDecoderError` when `response_model=` is set and no registered decoder accepts the type. It carries:

- `model: type`: the `response_model=` value nobody accepted.
- `registered_names: tuple[str, ...]`: class names of the decoders that rejected it. An empty tuple means no decoders were registered.

The message reads `no decoder for response_model=<Model>: <hint>`. There are two hints.

- No decoders were registered. Install an extra or pass a decoder list:

        no decoders registered. Install `pip install httpware[pydantic]` or `pip install httpware[msgspec]`, or pass decoders=[...] explicitly.

- Every registered decoder rejected the type. Neither built-in handles it, so pass your own `ResponseDecoder` in `decoders=[...]`:

        registered decoders (PydanticDecoder + MsgspecDecoder) all rejected it. Pass a custom decoder via decoders=[...].

Unlike `DecodeError`, this error is raised before the request is sent.

## `ResponseTooLargeError`

Both clients accept `max_response_body_bytes: int | None = None`. By default there is no limit. When it is set, a response body larger than the cap raises `ResponseTooLargeError` instead of being returned, whatever the status: a `200` trips it as easily as a `500`. The cap counts decoded bytes, after decompression. It applies to `send()` and the verb methods, and to the error body that `stream()` reads before raising a `StatusError`. Bytes you read yourself while iterating a `stream()` are never capped. Setting the cap together with `follow_redirects=True`, on the client or on a passed `httpx2_client`, raises `ValueError`, because `httpx2` reads every intermediate redirect body without the cap.

`ResponseTooLargeError` carries:

- `status_code: int`: the response's HTTP status code.
- `limit: int`: the `max_response_body_bytes` value that was exceeded.
- `content_length: int | None`: the `Content-Length` the server declared, if any.
- `reason: Literal["declared", "streamed"]`: why the cap tripped.
  - `"declared"`: the declared `Content-Length` was already over `limit`, so no body was read. `content_length` holds that value.
  - `"streamed"`: the decoded body passed `limit` while being read, as with chunked transfer or a compression bomb. Reading stops there, so the real size is unknown and `content_length` is only what the server declared, which may be missing or too small.

`ResponseTooLargeError` is a `ClientError` but not a `StatusError`: it has no `response` and is not in `STATUS_TO_EXCEPTION`. `AsyncRetry` does not retry it and the circuit breaker does not count it.

```python
from httpware import AsyncClient, ResponseTooLargeError

client = AsyncClient(base_url="https://api.example.com", max_response_body_bytes=1_000_000)

try:
    await client.get("/reports/huge")
except ResponseTooLargeError as exc:
    _LOGGER.error("response too large: limit=%d reason=%s content_length=%s", exc.limit, exc.reason, exc.content_length)
    raise
```

## See also

- [Resilience](resilience.md): the middleware that raise `RetryBudgetExhaustedError`, `BulkheadFullError` and `CircuitOpenError`.
- [Middleware](middleware.md): the `@async_on_error` decorator can turn exceptions into responses.
- [`src/httpware/errors.py`](https://github.com/modern-python/httpware/blob/main/src/httpware/errors.py): the exception classes.

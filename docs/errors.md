# Errors reference

`httpware` raises typed exceptions automatically — everything inherits `ClientError`, and HTTP responses with 4xx/5xx status raise status-keyed `StatusError` subclasses without you having to call `response.raise_for_status()`.

For the resilience-specific errors (`RetryBudgetExhaustedError`, `BulkheadFullError`, `CircuitOpenError`) see the [Resilience reference](resilience.md).

The status-keyed exception tree is shared between `Client` and `AsyncClient`. Catching `NotFoundError` in sync code uses the same import as catching it in async code (`from httpware import NotFoundError`).

## The exception tree

```
ClientError                          (catch-all for anything httpware raises)
├── TransportError                   (connection/network/protocol failure pre-response)
│   └── NetworkError                 (transient — safe to retry; covered by AsyncRetry's defaults)
├── TimeoutError                     (also inherits builtins.TimeoutError — except OSError catches it)
├── StatusError                      (got a response but its status was 4xx/5xx)
│   ├── ClientStatusError            (any 4xx — fallback for unknown 4xx codes)
│   │   ├── BadRequestError          (400)
│   │   ├── UnauthorizedError        (401)
│   │   ├── ForbiddenError           (403)
│   │   ├── NotFoundError            (404)
│   │   ├── ConflictError            (409)
│   │   ├── UnprocessableEntityError (422)
│   │   └── RateLimitedError         (429)
│   └── ServerStatusError            (any 5xx — fallback for unknown 5xx codes)
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

The fallback assumes `400 ≤ status < 600`. Statuses outside that range don't raise (they return the response as-is).

The explicit rows above are also exported as the public `STATUS_TO_EXCEPTION` mapping (`Mapping[int, type[StatusError]]`) — `from httpware import STATUS_TO_EXCEPTION` — so you can look up the class for a status code programmatically (e.g. `STATUS_TO_EXCEPTION.get(404)`). The two fallback rows are not in the mapping; they're applied by the raise logic for any unmapped in-range status.

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
        # Specific status — most precise. Convert to None as the "absent" sentinel.
        return None
    except StatusError as exc:
        # Got a response, but its status was 4xx/5xx and not one we handle specifically.
        # exc.response.* is available — headers, content, request, etc.
        _LOGGER.warning("upstream returned %s for %s", exc.response.status_code, exc.response.request.url)
        raise
    except NetworkError:
        # Transient transport failure. Already retried by the default AsyncRetry middleware
        # (if installed) when the method was idempotent. Seeing this means retries
        # exhausted or the method was non-idempotent.
        raise
    except (RetryBudgetExhaustedError, BulkheadFullError) as exc:
        # Resilience refusal — backpressure signal. Back off the caller.
        _LOGGER.error("resilience refused: %s", exc)
        raise
    except ClientError:
        # Catch-all for anything else httpware raised.
        raise
```

`TimeoutError` is doubly-inherited: `except builtins.TimeoutError` and `except OSError` both catch it (matches what `asyncio.wait_for` raises). This lets stdlib-style timeout handling Just Work.

## `exc.response.*` access pattern

For any `StatusError` subclass, the raw `httpx2.Response` is on `exc.response`:

```python
exc.response.status_code  # 404
exc.response.headers  # httpx2.Headers — case-insensitive
exc.response.content  # raw bytes
exc.response.text  # decoded body
exc.response.json()  # parsed JSON (raises if not JSON)
exc.response.request  # the failing httpx2.Request
exc.response.request.url  # the failing URL (httpx2.URL)
exc.response.request.method  # the HTTP method
```

**Security note:** `__repr__` and the exception's summary message strip `user:pass@` userinfo and mask the values of known-sensitive query and URL-fragment parameters (`api_key`, `apikey`, `access_token`, `refresh_token`, `token`, `secret`, `client_secret`, `password`, `passwd`, `pwd`, `auth`, `authorization`, `sig`, `signature`, `key`, `private_key`, `session`, `sessionid`, `x-api-key`) as `REDACTED`, preserving the keys. Query values under other names are **not** masked, so still avoid putting non-standard secrets in query strings. Note that request *headers* (`Authorization`, `Cookie`, etc.) are never redacted — see `exc.response.request.headers` above.

## Resilience-error payloads

`RetryBudgetExhaustedError` carries:
- `last_response: httpx2.Response | None` — the last response observed before the budget refused (None if all failures were transport-level)
- `last_exception: BaseException | None` — the last exception observed before the budget refused
- `attempts: int` — number of attempts already completed

`BulkheadFullError` carries:
- `max_concurrent: int` — the configured cap
- `acquire_timeout: float | None` — the configured timeout

`CircuitOpenError` carries:
- `retry_after: float | None` — seconds until the circuit will next admit a probe; `None` when a concurrent probe is already in flight (HALF_OPEN slot taken).

Use these for caller-side logging / alerting:

```python
except RetryBudgetExhaustedError as exc:
    _LOGGER.error(
        "budget exhausted after %d attempts; last_status=%s",
        exc.attempts,
        exc.last_response.status_code if exc.last_response is not None else None,
    )
```

## `DecodeError`

`DecodeError` is raised when `response_model=` is set on a request and the active `ResponseDecoder` failed to parse the response body. The HTTP call itself succeeded — status was 2xx/3xx and the transport delivered the body intact — but the body could not be coerced into the requested model. The exception is raised independently of which decoder is in use (`PydanticDecoder`, `MsgspecDecoder`, or a third-party decoder), so `except httpware.ClientError` is sufficient to cover the response-model decode path.

Fields:

- `response: httpx2.Response` — the response whose body failed to decode. Status, headers, and the originating `request` are all available via `exc.response.*`.
- `model: type` — the type that was passed as `response_model=`.
- `original: BaseException` — the underlying library exception (e.g., `pydantic.ValidationError`, `msgspec.ValidationError`, `msgspec.DecodeError`). Also available via `exc.__cause__`.

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

Raised by `send()` / `send_with_response()` / verb methods when `response_model=` is set but no registered decoder claims the model. Carries:

- `model: type` — the `response_model=` value that wasn't claimed.
- `registered_names: tuple[str, ...]` — class names of the registered decoders that all rejected the model. Empty tuple means no decoders were registered.

The message reads `no decoder for response_model=<Model>: <hint>`, and the corrective action depends on the hint. The two hints, verbatim:

- **No decoders were registered** — install an extra or pass an explicit decoder list:

        no decoders registered. Install `pip install httpware[pydantic]` or `pip install httpware[msgspec]`, or pass decoders=[...] explicitly.

- **Registered decoders all rejected the model** — your `response_model` type is exotic enough that neither built-in claims it; pass a custom `ResponseDecoder` via `decoders=[...]`:

        registered decoders (PydanticDecoder + MsgspecDecoder) all rejected it. Pass a custom decoder via decoders=[...].

Unlike `DecodeError`, this error fires *before* the HTTP request — no traffic is sent.

## `ResponseTooLargeError`

Both `Client` and `AsyncClient` accept a `max_response_body_bytes: int | None = None` constructor argument. It's an opt-in cap — the default `None` means unbounded, matching current behavior. When set, a response body that exceeds the cap raises `ResponseTooLargeError` instead of being returned. The check is status-agnostic (a `200` can trip it just as easily as a `4xx`/`5xx`), and it counts **decoded** bytes. It fires from the non-streaming terminal (`send()` / verb methods) and from `stream()`'s internal error pre-read; bytes you pull yourself via `stream()` iteration are never capped.

`ResponseTooLargeError` carries:

- `status_code: int` — the response's HTTP status code.
- `limit: int` — the configured `max_response_body_bytes` value that was exceeded.
- `content_length: int | None` — the server-declared `Content-Length`, when known.
- `reason: Literal["declared", "streamed"]` — which trip mode fired:
  - `"declared"` — the declared `Content-Length` already exceeded `limit`; the body was rejected before any byte was read, and `content_length` holds the offending value.
  - `"streamed"` — the decoded body crossed `limit` mid-read (the chunked-transfer or compression-bomb case); the true oversized length is unknown by design, so `content_length` is whatever (possibly absent or understated) value the server declared.

It is a non-status `ClientError` — it does not carry a `StatusError`-style positional `response` and is not in `STATUS_TO_EXCEPTION`. Because it's neither a `StatusError`, `NetworkError`, nor `TimeoutError`, it is not retried by `AsyncRetry` and does not count toward the circuit breaker.

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

- **[Resilience reference](resilience.md)** — `AsyncRetry`, `RetryBudget`, `AsyncBulkhead` parameter tables.
- **[Middleware guide](middleware.md)** — the `@async_on_error` decorator can translate exceptions into responses.
- **`src/httpware/errors.py`** — the tree itself; the construction rules for both halves of it are enforced in `tests/test_errors.py`.

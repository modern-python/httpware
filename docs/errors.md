# Errors reference

`httpware` raises typed exceptions automatically — everything inherits `ClientError`, and HTTP responses with 4xx/5xx status raise status-keyed `StatusError` subclasses without you having to call `response.raise_for_status()`.

For the resilience-specific errors (`RetryBudgetExhaustedError`, `BulkheadFullError`) see the [Resilience reference](resilience.md).

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
└── BulkheadFullError                (acquire_timeout elapsed before a slot opened)
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

## Catching strategies

```python
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
exc.response.status_code     # 404
exc.response.headers          # httpx2.Headers — case-insensitive
exc.response.content          # raw bytes
exc.response.text             # decoded body
exc.response.json()           # parsed JSON (raises if not JSON)
exc.response.request          # the failing httpx2.Request
exc.response.request.url      # the failing URL (httpx2.URL)
exc.response.request.method   # the HTTP method
```

**Security note:** `__repr__` and the exception's summary message strip `user:pass@` userinfo from the URL to avoid leaking credentials in tracebacks. **Query-string secrets are NOT stripped** — keep secrets out of query strings.

## Resilience-error payloads

`RetryBudgetExhaustedError` carries:
- `last_response: httpx2.Response | None` — the last response observed before the budget refused (None if all failures were transport-level)
- `last_exception: BaseException | None` — the last exception observed before the budget refused
- `attempts: int` — number of attempts already completed

`BulkheadFullError` carries:
- `max_concurrent: int` — the configured cap
- `acquire_timeout: float | None` — the configured timeout

Use these for caller-side logging / alerting:

```python
except RetryBudgetExhaustedError as exc:
    _LOGGER.error(
        "budget exhausted after %d attempts; last_status=%s",
        exc.attempts,
        exc.last_response.status_code if exc.last_response is not None else None,
    )
```

## See also

- **[Resilience reference](resilience.md)** — `AsyncRetry`, `RetryBudget`, `AsyncBulkhead` parameter tables.
- **[Middleware guide](middleware.md)** — the `@async_on_error` decorator can translate exceptions into responses.
- **`planning/engineering.md` §4** — the formal exception contract.

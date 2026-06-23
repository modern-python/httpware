# Errors

`StatusError` and all its 4xx/5xx subclasses are constructed with a **single positional `response: httpx2.Response`**. Subclasses do not override `__init__`. All fields are available via `exc.response.*` (status code, headers, content, request, etc.).

```python
raise NotFoundError(response)          # correct
exc.response.status_code               # 404
exc.response.request.url               # URL of the failed request
```

`__repr__` and the `str()` summary redact URL userinfo (`user:pass@`) and mask the values of known-sensitive query and fragment parameters (e.g. `token`, `api_key`, `secret`) to avoid leaking credentials in tracebacks.

The error-mapping table (what `httpx2` exception maps to which `httpware` exception) lives at the terminal in `src/httpware/client.py`. Status-keyed exceptions are looked up via the `STATUS_TO_EXCEPTION` table in `src/httpware/errors.py`. Unknown 4xx falls back to `ClientStatusError`; unknown 5xx falls back to `ServerStatusError`.

`TimeoutError` inherits from both `httpware.ClientError` and `builtins.TimeoutError` so `except builtins.TimeoutError` (the form `asyncio.wait_for` uses) also catches httpware-raised timeouts.

`DecodeError` covers the case where `response_model=` is set, the HTTP call itself succeeded, but the active `ResponseDecoder` raised. The wrap happens at the seam in `Client.send` / `AsyncClient.send` — `except Exception` translates any decoder-side failure into `DecodeError(response=..., model=..., original=...)` with `raise ... from exc` chaining. The `original` attribute exposes the underlying library exception (e.g., `pydantic.ValidationError`, `msgspec.ValidationError`); `__cause__` carries the same reference.

The "no `__init__` override" rule scopes only to `StatusError` subclasses. Non-status `ClientError` subclasses — `DecodeError`, `MissingDecoderError`, `BulkheadFullError`, `RetryBudgetExhaustedError`, `CircuitOpenError`, `ResponseTooLargeError` — deliberately define `__init__` with keyword-only fields.

`ResponseTooLargeError` is raised when `max_response_body_bytes` is set and a response body would exceed the cap — status-agnostic (a `200` can trip it), counting **decoded** bytes. It fires from the non-streaming terminal (`send()`) and from `stream()`'s internal error pre-read; user-driven `stream()` iteration is never capped. The `reason` field discriminates the two trip modes: `"declared"` (the declared `Content-Length` already exceeds the cap, rejected before any byte is read — `content_length` holds it) and `"streamed"` (the decoded body crossed the cap mid-read, the chunked or compression-bomb case, where the true size is unknown by design). It is a non-status `ClientError`; it does not carry a `StatusError`-style positional `response` and is not in `STATUS_TO_EXCEPTION`. Because it is neither a `StatusError`, `NetworkError`, nor `TimeoutError`, it is not retried and does not count toward the circuit breaker.

## Security: request headers are reachable via `exc.response.request`

`StatusError` holds the raw `httpx2.Response`. Request headers — including `Authorization`, `Cookie`, and `Proxy-Authorization` — remain reachable at `exc.response.request.headers`. httpware masks URL userinfo and known-sensitive query/fragment values in messages and `repr`, but does **not** strip headers. Handler authors must redact before logging or serializing a caught error.

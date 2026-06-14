# Client

`httpware` ships two clients: a sync `Client` and an async `AsyncClient`, both at the top level. They are thin wrappers over `httpx2.Client` and `httpx2.AsyncClient` respectively. Both carry full feature parity: typed decoding, the middleware chain, the full resilience suite, and `stream()`.

## The internal terminal

The bottom of the middleware chain (the "terminal") is internal. It calls `self._httpx2_client.send(request)`, maps `httpx2` errors to `httpware` errors, and raises a `StatusError` subclass on 4xx/5xx. The error-mapping table (what `httpx2` exception maps to which `httpware` exception) lives at the terminal in `src/httpware/client.py`; status-keyed exceptions are looked up via the `STATUS_TO_EXCEPTION` table in `src/httpware/errors.py`. The same terminal lifecycle holds in both worlds: `Client.send` / `AsyncClient.send` enter the middleware chain first, and it is the internal terminal — `Client._terminal` / `AsyncClient._terminal` — that calls `httpx2.Client.send` / `httpx2.AsyncClient.send`.

## Sync/async parity

The sync and async surfaces are kept at parity. Shared state is thread-safe where it must be: `RetryBudget` is a single class used by both worlds and is thread-safe. Sync `Bulkhead` uses `threading.Semaphore` and cannot share an instance with `AsyncBulkhead`.

The async middleware surface uses the `Async*`/`async_*` prefix, aligning with httpx2's convention.

## Streaming

Both `Client.stream()` (sync) and `AsyncClient.stream()` (async) provide a context-manager API for chunked response bodies. Both bypass the middleware chain by design.

## Proxy environment (`trust_env`)

`httpware` wraps `httpx2.Client` / `httpx2.AsyncClient`, which default to `trust_env=True`. The `HTTP_PROXY`, `HTTPS_PROXY`, and `NO_PROXY` environment variables and `.netrc` credentials are therefore honored by default — no httpware behavior to configure. To opt out, supply an explicit httpx2 client:

```python
Client(httpx2_client=httpx2.Client(trust_env=False))
AsyncClient(httpx2_client=httpx2.AsyncClient(trust_env=False))
```

## Bounded error bodies (`max_error_body_bytes`)

Both `Client` and `AsyncClient` accept `max_error_body_bytes: int | None = None`. The default (`None`) is backward-compatible: error bodies are read without a size limit.

When set, `stream()` raises `ResponseTooLargeError` on a 4xx/5xx response whose declared `Content-Length` header exceeds the cap — before the body is read. Responses without a declared `Content-Length` (chunked transfer) are still read unbounded: a hard mid-read cap would require httpx2 private API, which this project forbids.

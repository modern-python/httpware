# Client

`httpware` ships two clients: a sync `Client` and an async `AsyncClient`, both at the top level. They are thin wrappers over `httpx2.Client` and `httpx2.AsyncClient` respectively. Both carry full feature parity: typed decoding, the middleware chain, the full resilience suite, and `stream()`.

## The internal terminal

The bottom of the middleware chain (the "terminal") is internal. It calls `self._httpx2_client.send(request)`, maps `httpx2` errors to `httpware` errors, and raises a `StatusError` subclass on 4xx/5xx. The error-mapping table (what `httpx2` exception maps to which `httpware` exception) lives in `src/httpware/_internal/exception_mapping.py` and fires at the terminal in `src/httpware/client.py`; status-keyed exceptions are looked up via the `STATUS_TO_EXCEPTION` table in `src/httpware/errors.py`. The same terminal lifecycle holds in both worlds: `Client.send` / `AsyncClient.send` enter the middleware chain first, and it is the internal terminal — `Client._terminal` / `AsyncClient._terminal` — that calls `httpx2.Client.send` / `httpx2.AsyncClient.send`.

## Sync/async parity

The sync and async surfaces are kept at parity. Shared state is thread-safe where it must be: `RetryBudget` is a single class used by both worlds and is thread-safe. Sync `Bulkhead` uses `threading.Semaphore` and cannot share an instance with `AsyncBulkhead`.

The async middleware surface uses the `Async*`/`async_*` prefix, aligning with httpx2's convention.

## `send_with_response` and per-verb siblings

`send_with_response(request, *, response_model)` returns `(httpx2.Response, T)` atomically — the decoded body and the raw response together. This is the building block for cases where response metadata (headers, status) is needed alongside the typed body, such as Link-header pagination.

The per-verb `*_with_response` siblings — `get_with_response`, `post_with_response`, `put_with_response`, `patch_with_response`, `delete_with_response`, and `request_with_response` — are the one-call ergonomic form: `response_model` is required, they return `tuple[httpx2.Response, T]`, and they accept the same keyword arguments as their non-`_with_response` counterparts; there is no `head_with_response` or `options_with_response` — use `request_with_response` for those methods.

## Streaming

Both `Client.stream()` (sync) and `AsyncClient.stream()` (async) provide a context-manager API for chunked response bodies. Both bypass the middleware chain by design.

## Proxy environment (`trust_env`)

`httpware` wraps `httpx2.Client` / `httpx2.AsyncClient`, which default to `trust_env=True`. The `HTTP_PROXY`, `HTTPS_PROXY`, and `NO_PROXY` environment variables and `.netrc` credentials are therefore honored by default — no httpware behavior to configure. To opt out, supply an explicit httpx2 client:

```python
Client(httpx2_client=httpx2.Client(trust_env=False))
AsyncClient(httpx2_client=httpx2.AsyncClient(trust_env=False))
```

## Bounded response bodies (`max_response_body_bytes`)

Both `Client` and `AsyncClient` accept `max_response_body_bytes: int | None = None`. The default (`None`) is unbounded; a non-`None` value below `1` is rejected with `ValueError` at construction. The cap is **status-agnostic** (a `200` trips it the same as a `500`) and counts **decoded** bytes — the actual in-memory footprint, and the only measure that catches a compression bomb (a 133-byte gzip body decoding to 100 KB).

The cap bounds memory that httpware buffers on your behalf, at two sites:

- **The non-streaming terminal** (`send()` and the per-verb helpers). When a cap is set, the terminal switches from `httpx2.send(request)` to `send(request, stream=True)` and accumulates decoded bytes through the shared `_read_capped` helper, failing fast with `ResponseTooLargeError` the moment the cap is crossed. When the cap is `None`, the terminal keeps the plain buffered `send()` fast path — zero streaming overhead.
- **`stream()`'s internal error pre-read** — the 4xx/5xx body httpware reads so `exc.response.content` works is routed through the same `_read_capped`. **User-driven `stream()` iteration is never capped** — you chose streaming to own that memory.

The declared `Content-Length` is used only as an *early reject* (if even the compressed size already exceeds the cap, fail before reading a byte); it is never an early accept, so the accumulator always runs — chunked and bomb bodies are caught, not waved through. `ResponseTooLargeError.reason` is `"declared"` or `"streamed"` accordingly. Entirely public httpx2 API — no private access.

**Bodiless responses bypass the cap.** Responses that carry no message body — to a `HEAD` request, or with status `204`/`304` — buffer nothing, so the cap never applies to them even when they declare a large `Content-Length` (`HEAD` legitimately echoes the entity length). These are returned unchanged, preserving their original headers.

**Rebuilt headers.** The accumulator yields the *decoded* body, so the rebuilt Response drops the wire-encoding headers (`Content-Encoding`, `Transfer-Encoding`, and the now-incorrect compressed `Content-Length`); httpx2 recomputes `Content-Length` from the buffered content. Carrying `Content-Encoding` forward would make httpx2 re-decode already-decoded bytes and raise.

**Caveat:** on the capped path the buffered response is rebuilt via the public `httpx2.Response(content=...)` constructor, which does not carry `.elapsed` (httpx2 only sets it on its own buffered `send()`). Clients that set a cap and read `response.elapsed` will find it absent; the `None`-cap fast path preserves it.

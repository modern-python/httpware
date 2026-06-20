---
status: shipped
date: 2026-06-05
slug: streaming
summary: Shipped 0.5.0 — stream()
supersedes: null
superseded_by: null
pr: 26
outcome: 'Shipped 0.5.0 — stream()'
---

# Spec: AsyncClient.stream context manager (0.5.0, Epic 4 story 4-3)

**Date:** 2026-06-05
**Topic slug:** `streaming`
**Status:** drafted, awaiting user review
**Target release:** 0.5.0
**Epic 4 stories rolled in:** 4-3 (the only surviving Epic 4 story post-v0.2 pivot).

## Purpose

Add `AsyncClient.stream(method, url, **kwargs)` — an async context manager that streams the response body. Mirrors `httpx2.AsyncClient.stream()` directly; **bypasses the middleware chain for v1** (revisit later if user feedback warrants); **auto-raises `StatusError` subclasses on 4xx/5xx** (consistent with `client.get()`/`client.post()`/etc., body pre-read before raising so `exc.response.content` works). Wraps the request and body-consumption phases in a new `_httpx2_exception_mapper` helper shared with `_terminal`, so users see consistent `httpware` exception types regardless of which client method they call.

Also in scope: **`Retry` refuses to retry requests with streamed bodies.** Async-iterable bodies can't replay across retry attempts. Detection via an `httpware.streaming_body` marker added to `request.extensions` by `_request_with_body` when `content=`/`data=`/`files=` is async-iterable; Retry reads the marker and refuses the retry path with a clear PEP-678 note. Closes the open deferred-work item.

After this PR ships, Epic 4 is closed and the Retry-streamed-body deferred-work item is closed.

## Non-goals

Items deliberately deferred so this slice ships clean:

- **No middleware-chain composition for `stream()`.** `stream()` bypasses Retry, Bulkhead, and any user-installed middleware **for v1**. Documented in the `stream()` docstring. Rationale: the middleware protocol operates on `(request, response)` pairs where the response is a fully-buffered `httpx2.Response`. Streaming responses fundamentally break that model (reading `.content` consumes the stream). Composing streams with middleware requires a per-middleware stream-aware policy (e.g., a `request.extensions["httpware.stream"]` marker and updates to every middleware) — meaningful additional design + code. Defer until real-user feedback shows the need. Revisiting is purely additive (add an `apply_middleware: bool = False` parameter and the marker mechanism in a follow-up).
- **No `StreamResponse` wrapper type.** Returns `httpx2.Response` directly. Pre-v0.2 there was a `StreamResponse` class; the v0.2 thin-wrapper pivot deleted it (engineering.md §8 historical: *"`4-1` `StreamResponse` type, `4-2` transport stream implementation"* explicitly deleted). This slice does not bring it back.
- **No `response_model=` decoding parameter.** Doesn't apply to streams (the body isn't a single bytes blob to decode upfront). Not exposed in the `stream()` signature.
- **No Bulkhead-during-stream integration.** Bulkhead doesn't see `stream()` calls (bypass). If users want stream concurrency limits, they manage at the call site (their own semaphore, etc.).
- **No marker-based auto-detection beyond `content`/`data`/`files`.** Retry's streamed-body refusal triggers only when a streaming body was passed through `_request_with_body`'s kwargs. Manually-constructed `httpx2.Request` objects with hand-set streaming bodies are NOT detected. Users constructing requests manually accept the responsibility.

## Architecture

Three coordinated changes:

1. **`src/httpware/client.py`** — add `AsyncClient.stream()` (an `@contextlib.asynccontextmanager` method, ~40 lines). Extract a new module-level `_httpx2_exception_mapper` `@asynccontextmanager` helper (~12 lines) used by both `_terminal` and `stream()` — one source of truth for the httpx2→httpware exception dispatch. Refactor `_terminal` to use the helper. In `_request_with_body`, detect async-iterable `content`/`data`/`files` and mark `request.extensions["httpware.streaming_body"] = True`.

2. **`src/httpware/middleware/resilience/retry.py`** — in `Retry.__call__`, before each retry attempt, check `request.extensions.get("httpware.streaming_body")`. If True and a retry would otherwise happen, refuse: raise the original error with a PEP-678 note (`"httpware: not retrying — request body is a stream that cannot replay"`).

No new files. No new module.

```text
src/httpware/
├── client.py                              # AsyncClient — add stream() + _httpx2_exception_mapper + streaming-body marker
└── middleware/resilience/retry.py         # Retry — refuse retry when streaming-body marker is set
```

## Public API

```python
import contextlib

@contextlib.asynccontextmanager
async def stream(
    self,
    method: str,
    url: str,
    *,
    params: typing.Any | None = None,
    headers: typing.Any | None = None,
    cookies: typing.Any | None = None,
    timeout: typing.Any = httpx2.USE_CLIENT_DEFAULT,
    extensions: typing.Any | None = None,
    json: typing.Any | None = None,
    content: typing.Any | None = None,
    data: typing.Any | None = None,
    files: typing.Any | None = None,
) -> AsyncIterator[httpx2.Response]:
    """Stream an HTTP response. Bypasses the middleware chain.

    Yields an httpx2.Response; consume the body via response.aiter_bytes(),
    response.aiter_text(), response.aiter_lines(), or response.aiter_raw().
    The body is NOT pre-read for 2xx responses (the streaming property is
    preserved); the response is closed when the context exits.

    Bypasses the middleware chain (no Retry, no Bulkhead, no user-installed
    middleware) for v1 — see the design spec for rationale.

    Auto-raises StatusError subclasses on 4xx/5xx (NotFoundError,
    ServiceUnavailableError, etc.) — consistent with client.get()/post()/etc.
    On error, the response body is pre-read so exc.response.content is
    accessible. You lose the streaming property on errors; rare in practice
    since 4xx/5xx bodies are typically small.

    Maps httpx2 exceptions raised during the request OR body consumption to
    httpware exceptions consistently with the rest of AsyncClient.
    """
```

Usage:

```python
async with client.stream("GET", "/big-file") as response:
    # response.status_code is guaranteed 2xx or 3xx here — 4xx/5xx auto-raise
    async for chunk in response.aiter_bytes():
        process(chunk)

# Catch like any other status error:
try:
    async with client.stream("GET", "/maybe-missing") as response:
        ...
except NotFoundError as exc:
    body_text = exc.response.text  # pre-read on error; available here
```

Sharing a streaming body (e.g., for upload):

```python
async def body() -> AsyncIterator[bytes]:
    async for chunk in some_source():
        yield chunk

async with client.stream("POST", "/upload", content=body()) as response:
    ...
```

(Note: with streamed REQUEST bodies, do not put `Retry` in the middleware chain for non-stream calls until the Retry-streamed-body refusal PR lands. The stream() method itself bypasses Retry, so it's safe.)

## Implementation algorithm

### `_httpx2_exception_mapper` (shared helper)

New module-level helper at the top of `client.py`:

```python
@contextlib.asynccontextmanager
async def _httpx2_exception_mapper() -> AsyncIterator[None]:
    """Map httpx2 exceptions to httpware exceptions. Shared by _terminal and stream()."""
    try:
        yield
    except httpx2.TimeoutException as exc:
        raise TimeoutError(str(exc)) from exc
    except (httpx2.InvalidURL, httpx2.CookieConflict) as exc:
        raise TransportError(str(exc)) from exc
    except httpx2.NetworkError as exc:
        raise NetworkError(str(exc)) from exc
    except httpx2.HTTPError as exc:
        raise TransportError(str(exc)) from exc
```

Clause ordering must match the current `_terminal` (TimeoutException → InvalidURL/CookieConflict → NetworkError → HTTPError). `RuntimeError` "closed" check stays in `_terminal` (it's not an httpx2 error and only applies to the non-stream path).

### `_terminal` refactor

The current except chain in `_terminal` (`client.py:107-118`) becomes:

```python
async def _terminal(self, request: httpx2.Request) -> httpx2.Response:
    try:
        async with _httpx2_exception_mapper():
            response = await self._httpx2_client.send(request)
    except RuntimeError as exc:
        if "closed" in str(exc):
            raise TransportError(str(exc)) from exc
        raise
    # ... status-code dispatch unchanged
```

### `_request_with_body` streaming-body detection

Add a helper and a marker step. Detection function:

```python
def _is_streaming_body(value: typing.Any) -> bool:
    """True if value is an async-iterable that can't be safely replayed for retry."""
    if value is None:
        return False
    if isinstance(value, (bytes, bytearray, memoryview, str, dict)):
        return False
    return hasattr(value, "__aiter__")
```

In `_request_with_body`, after `request = self._httpx2_client.build_request(...)` and before `await self.send(request, ...)`:

```python
if _is_streaming_body(content) or _is_streaming_body(data) or _is_streaming_body(files):
    request.extensions["httpware.streaming_body"] = True
```

### `stream()` method

Signature per "Public API" above. Body:

```python
# Build kwargs (same pattern as _request_with_body but without response_model):
kwargs: dict[str, typing.Any] = {}
if params is not None:
    kwargs["params"] = params
if headers is not None:
    kwargs["headers"] = headers
if cookies is not None:
    kwargs["cookies"] = cookies
if timeout is not httpx2.USE_CLIENT_DEFAULT:
    kwargs["timeout"] = timeout
if extensions is not None:
    kwargs["extensions"] = extensions
if json is not None:
    kwargs["json"] = json
if content is not None:
    kwargs["content"] = content
if data is not None:
    kwargs["data"] = data
if files is not None:
    kwargs["files"] = files

async with _httpx2_exception_mapper():
    async with self._httpx2_client.stream(method, url, **kwargs) as response:
        status = response.status_code
        if HTTPStatus.BAD_REQUEST <= status < 600:  # noqa: PLR2004 — 600 is the synthetic upper bound for 5xx
            await response.aread()  # pre-read body so exc.response.content is accessible
            exc_class = STATUS_TO_EXCEPTION.get(
                status,
                ClientStatusError if status < HTTPStatus.INTERNAL_SERVER_ERROR else ServerStatusError,
            )
            raise exc_class(response)
        yield response
```

Status-code dispatch is byte-for-byte identical to `_terminal`'s (the table lookup, the same fallback, the same `noqa: PLR2004` comment). Both call sites stay in sync — if a future change refines status-error dispatch (e.g., adds new subclasses), both update together. Worth extracting into a helper? Probably yes once both call sites exist; defer to implementation review.

### `Retry.__call__` streaming-body refusal

In `Retry.__call__`, after the per-attempt failure is identified and BEFORE the retry/sleep block (i.e., right before `self.budget.try_withdraw()`):

```python
if request.extensions.get("httpware.streaming_body"):
    if last_exc is None:  # pragma: no cover — invariant
        msg = "Retry: streaming-body refusal reached with no last_exc"
        raise AssertionError(msg)
    last_exc.add_note(
        "httpware: not retrying — request body is a stream that cannot replay across attempts"
    )
    raise last_exc
```

The note is added with PEP 678 `add_note` — same pattern as the max-attempts exhaustion path. Order: streaming-body check comes BEFORE the budget gate so we don't withdraw a budget token for a request we won't retry.

**Clause ordering** matches `_terminal` (`client.py:107-118`) so the same dispatch invariants hold: `httpx2.NetworkError` precedes `httpx2.HTTPError` (subclass before parent), `(InvalidURL, CookieConflict)` catches BEFORE `NetworkError` so they stay non-`NetworkError` (and are therefore non-retryable when Retry's streamed-body fix lands).

Exceptions can arise in three places, all caught by the same try/except:

1. **Request phase** (httpx2 sends the request, gets headers): `__aenter__` of `httpx2.AsyncClient.stream()`. Exceptions propagate to our try/except directly.
2. **Body-consumption phase** (user code inside `async with client.stream(...) as response:` does `async for chunk in response.aiter_bytes()`): Exceptions propagate UP through the `yield response`, the inner `httpx2.stream()` context manager's `__aexit__` runs cleanup, then they hit our outer try/except.
3. **Cleanup phase** (response close at context exit): typically silent; any exception during close is wrapped the same way.

Non-`httpx2` exceptions (user code raises `ValueError` during chunk processing, etc.) are NOT caught by our handlers — they propagate to the user unchanged. `asyncio.CancelledError` (`BaseException` subclass) is never caught.

## Behavior reference

| Situation | Behavior |
|-----------|----------|
| 2xx/3xx response | Yields `httpx2.Response`; user consumes body via aiter methods (streaming preserved) |
| 4xx/5xx response | Pre-reads body, raises `StatusError` subclass (`NotFoundError`, `ServiceUnavailableError`, etc.). Caller's `exc.response.content` / `exc.response.text` are accessible |
| Network error during initial request | Raises `httpware.NetworkError` from `__aenter__` |
| Network error mid-stream | Raises `httpware.NetworkError` from the `async for` line in user code |
| Timeout during request or body consumption | Raises `httpware.TimeoutError` |
| `InvalidURL` / `CookieConflict` | Raises bare `httpware.TransportError` (NOT `NetworkError`) — non-retryable family |
| User code inside `async with` raises | Propagates unchanged; httpx2's context manager cleans up the response |
| `asyncio.CancelledError` during stream | Propagates unchanged; httpx2's context manager cleans up the response; no slot or resource leak |
| `Retry` middleware sees a streaming-body request and a retryable error | Re-raises the original error with PEP-678 note: `"httpware: not retrying — request body is a stream that cannot replay across attempts"` |

## Testing

Per `planning/engineering.md §6`. Three test files touched/created.

### New file `tests/test_client_stream.py`

- `test_streams_response_body_successfully` — handler returns chunks; assert `async for chunk in response.aiter_bytes()` yields them in order
- `test_auto_raises_on_4xx_with_body_preread` — handler returns 404 with a JSON body; expect `NotFoundError`; assert `exc.response.content` is the JSON body (proves pre-read worked)
- `test_auto_raises_on_5xx_with_body_preread` — same with 503 → `ServiceUnavailableError`
- `test_auto_raises_unknown_4xx_falls_back_to_client_status_error` — 418 → `ClientStatusError`
- `test_auto_raises_unknown_5xx_falls_back_to_server_status_error` — 599 → `ServerStatusError`
- `test_3xx_does_not_raise` — 301 redirect response yielded normally
- `test_network_error_during_request_maps_to_network_error` — handler raises `httpx2.ConnectError`; expect `httpware.NetworkError`
- `test_network_error_during_body_consumption_maps_to_network_error` — handler streams partial bytes then raises `httpx2.ReadError`; expect `httpware.NetworkError` when user iterates body
- `test_timeout_during_stream_maps_to_httpware_timeout` — handler raises `httpx2.ReadTimeout`; expect `httpware.TimeoutError`
- `test_invalid_url_maps_to_bare_transport_error` — handler raises `httpx2.InvalidURL`; expect `httpware.TransportError` and NOT `httpware.NetworkError`
- `test_cancellation_propagates_cleanly` — outer task cancels while body iteration is in progress; expect `asyncio.CancelledError` propagates and stream is closed
- `test_user_exception_in_block_propagates_unchanged` — user raises `ValueError` during chunk processing; expect `ValueError` propagates with no httpware wrapping
- `test_bypasses_middleware_chain` — install a recording middleware that increments a counter on `__call__`; do a `stream()` call; assert counter == 0
- `test_forwards_kwargs_to_httpx2` — pass `params`, `headers`, `cookies`, `extensions`; assert they reach the mock transport's recorded request
- `test_stream_with_content_kwarg` — `client.stream("POST", url, content=b"bytes")` works; mock transport sees the bytes
- `test_stream_with_async_iterable_content` — `client.stream("POST", url, content=async_gen())` works (streaming request body — confirms the bypass path doesn't accidentally choke)

### Modified file `tests/test_error_mapping_terminal.py`

No new tests required; existing tests must still pass after the `_terminal` refactor to use `_httpx2_exception_mapper`. Dispatch behavior is byte-for-byte identical.

### Modified file `tests/test_retry.py`

Streaming-body refusal tests:

- `test_retry_refuses_streamed_body_request` — build a request, set `request.extensions["httpware.streaming_body"] = True`, configure Retry, force a retryable failure; expect the original exception to propagate with the PEP-678 note about not retrying. Assert `_sleep` was NOT called (no retry attempt; no backoff).
- `test_retry_refuses_streamed_body_does_not_consume_budget` — same setup with an explicit `RetryBudget`; after the call, assert no budget token was withdrawn (the streaming-body refusal happens BEFORE `budget.try_withdraw()`).
- `test_client_post_with_async_iterable_content_marks_extensions` — call `client.post(url, content=async_gen())` with a recording mock transport; assert the request reached the transport with `request.extensions["httpware.streaming_body"] is True`.
- `test_client_post_with_bytes_content_does_not_mark_extensions` — `client.post(url, content=b"hi")`; assert the marker is NOT present.
- `test_client_post_with_dict_data_does_not_mark_extensions` — `client.post(url, data={"k": "v"})`; assert the marker is NOT present.
- `test_client_post_with_async_iterable_data_marks_extensions` — `client.post(url, data=async_gen())`; assert marker present.
- `test_client_post_with_async_iterable_files_marks_extensions` — `client.post(url, files=async_gen())`; assert marker present.

Coverage target: **100% line coverage** (project standard).

## Public API exports

`stream` is a method on `AsyncClient`, which is already exported from `httpware/__init__.py`. No new top-level exports needed.

## Documentation updates

This PR touches the user-facing docs since we just shipped a docs-sync pass:

- **README.md**: add a brief paragraph (or extend the Quickstart) showing `client.stream()`. Note that Retry refuses streamed-body requests.
- **docs/index.md**: mirror the README addition.
- **planning/engineering.md §1**: append a sentence mentioning the streaming surface.
- **planning/engineering.md §8** roadmap: mark `4-3` shipped; Epic 4 closes.
- **planning/deferred-work.md**: close the "Retry + streaming bodies (Epic 4 interaction)" item (move from Open to a new "Closed by 0.5.0 streaming" section).
- **planning/releases/0.5.0.md**: new release notes file.

## Open questions deferred to implementation

- **`httpx2.NetworkError` symbol existence**: confirmed available (used in slice 1 / NetworkError refinement work). No fallback needed.
- **Whether `httpx2.ReadError` raised mid-stream actually maps to `httpx2.NetworkError`**: the implementer should verify `isinstance(httpx2.ReadError(...), httpx2.NetworkError)` is True (it should be per httpx convention). If it isn't, fall back to enumerating: `except (httpx2.ConnectError, httpx2.ReadError, httpx2.WriteError, httpx2.CloseError) as exc`.
- **`httpx2.Request.extensions` mutability**: should be a `dict[str, Any]` per httpx convention. Implementer must verify `request.extensions["httpware.streaming_body"] = True` works (does not raise on a freshly-built request). If `request.extensions` could be `None` or read-only, swap to `request.extensions = {**(request.extensions or {}), "httpware.streaming_body": True}`.
- **Whether status-code dispatch should be extracted from `_terminal` to a shared helper**: with both `_terminal` and `stream()` doing the same `HTTPStatus.BAD_REQUEST <= status < 600` check + `STATUS_TO_EXCEPTION.get(...)` fallback, extracting may be worth it. Decide during implementation; if extracted, both paths use the helper.

## References

- `planning/engineering.md` §1 (project intent), §3 (protocol seams), §5 (module layout), §8 (roadmap)
- `planning/deferred-work.md` §"Retry + streaming bodies" — **closes** with this PR (Retry's streaming-body refusal lands here)
- `planning/deferred-work.md` §"Closed by the v0.2 thin-wrapper pivot" → "`httpx2.StreamError` family escape from the transport's `except httpx2.HTTPError`" — also closed by this slice's exception mapping
- httpx streaming docs (convention reference): https://www.python-httpx.org/async/#streaming-responses

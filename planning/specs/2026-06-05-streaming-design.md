# Spec: AsyncClient.stream context manager (0.5.0, Epic 4 story 4-3)

**Date:** 2026-06-05
**Topic slug:** `streaming`
**Status:** drafted, awaiting user review
**Target release:** 0.5.0
**Epic 4 stories rolled in:** 4-3 (the only surviving Epic 4 story post-v0.2 pivot).

## Purpose

Add `AsyncClient.stream(method, url, **kwargs)` — an async context manager that streams the response body. Mirrors `httpx2.AsyncClient.stream()` directly; bypasses the middleware chain; wraps the request and body-consumption phases in the same exception-mapping that `AsyncClient._terminal` uses, so users see consistent `httpware` exception types regardless of whether they call `client.get()` or `client.stream()`.

This is the only Epic 4 work; after it ships, Epic 4 is closed. The Retry-refuses-streamed-body deferred-work item (`planning/deferred-work.md` §"Retry + streaming bodies") stays open as a separate small follow-up PR.

## Non-goals

Items deliberately deferred so this slice ships clean:

- **No middleware-chain composition.** `stream()` bypasses Retry, Bulkhead, and any user-installed middleware. Documented in the `stream()` docstring. Rationale: the middleware chain operates on `(request, response)` pairs where the response is a fully-buffered `httpx2.Response`. Streaming responses fundamentally break that model (reading `.content` consumes the stream, defeating the purpose). Retry can't replay consumed streams. Bulkhead's "hold slot for one request" semantics get pathological when a stream stays open for minutes. Bypass is the only sensible v1 default.
- **No `StreamResponse` wrapper type.** Returns `httpx2.Response` directly. Pre-v0.2 there was a `StreamResponse` class; the v0.2 thin-wrapper pivot deleted it (engineering.md §8 historical: *"`4-1` `StreamResponse` type, `4-2` transport stream implementation"* explicitly deleted). This slice does not bring it back.
- **No auto-raise on 4xx/5xx.** `stream()` does NOT raise `StatusError` subclasses on bad status codes — deliberate divergence from `client.get()`/`client.post()`/etc. Users call `response.raise_for_status()` if they want that behavior. Rationale: streams often have meaningful bodies even at 4xx (partial-success responses, structured error bodies); auto-raising would force users to lose access to the response object before they could read it. Matches httpx convention.
- **No `response_model=` decoding parameter.** Doesn't apply to streams (the body isn't a single bytes blob to decode upfront). Not exposed in the `stream()` signature.
- **No Retry-refuses-streamed-body fix.** Separate follow-up PR. The `deferred-work.md` entry stays open. Adding `stream()` makes streaming-body usage more visible, so the latent retry-replay footgun becomes more likely to be hit — call this out in the follow-up.
- **No Bulkhead-during-stream integration.** Bulkhead doesn't see `stream()` calls (bypass). If users want stream concurrency limits, they manage at the call site (their own semaphore, etc.).
- **No `_map_httpx2_exceptions` shared helper.** Intentional duplication of the except chain between `_terminal` and `stream()` — only two call sites, and the duplication keeps each path self-contained and readable. Extract if a third call site emerges.

## Architecture

`AsyncClient.stream()` is a method on the existing `AsyncClient` class in `src/httpware/client.py`. No new files. No new module. The implementation is one method (~30 lines) decorated with `@contextlib.asynccontextmanager`.

```text
src/httpware/
└── client.py              # AsyncClient — add stream() method
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
    The body is NOT pre-read; the response is closed when the context exits.

    Bypasses the middleware chain (no Retry, no Bulkhead, no user-installed
    middleware) — see the design spec for rationale. Maps httpx2 exceptions
    raised during the request OR body consumption to httpware exceptions
    consistently with the rest of AsyncClient.

    Does NOT auto-raise on 4xx/5xx — call response.raise_for_status() if
    you want StatusError-style behavior.
    """
```

Usage:

```python
async with client.stream("GET", "/big-file") as response:
    if response.status_code != 200:
        ...
    async for chunk in response.aiter_bytes():
        process(chunk)
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

Signature is the same as the "Public API" block above (all kwargs named explicitly; same shape as `_request_with_body`). Body:

```python
# Inside the method body, after the signature shown in Public API above:
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

try:
    async with self._httpx2_client.stream(method, url, **kwargs) as response:
        yield response
except httpx2.TimeoutException as exc:
    raise TimeoutError(str(exc)) from exc
except (httpx2.InvalidURL, httpx2.CookieConflict) as exc:
    raise TransportError(str(exc)) from exc
except httpx2.NetworkError as exc:
    raise NetworkError(str(exc)) from exc
except httpx2.HTTPError as exc:
    raise TransportError(str(exc)) from exc
```

The kwarg-passing block mirrors `_request_with_body` (`client.py:166-185`) verbatim except for absent params (`response_model` doesn't apply to streams).

**Clause ordering** matches `_terminal` (`client.py:107-118`) so the same dispatch invariants hold: `httpx2.NetworkError` precedes `httpx2.HTTPError` (subclass before parent), `(InvalidURL, CookieConflict)` catches BEFORE `NetworkError` so they stay non-`NetworkError` (and are therefore non-retryable when Retry's streamed-body fix lands).

Exceptions can arise in three places, all caught by the same try/except:

1. **Request phase** (httpx2 sends the request, gets headers): `__aenter__` of `httpx2.AsyncClient.stream()`. Exceptions propagate to our try/except directly.
2. **Body-consumption phase** (user code inside `async with client.stream(...) as response:` does `async for chunk in response.aiter_bytes()`): Exceptions propagate UP through the `yield response`, the inner `httpx2.stream()` context manager's `__aexit__` runs cleanup, then they hit our outer try/except.
3. **Cleanup phase** (response close at context exit): typically silent; any exception during close is wrapped the same way.

Non-`httpx2` exceptions (user code raises `ValueError` during chunk processing, etc.) are NOT caught by our handlers — they propagate to the user unchanged. `asyncio.CancelledError` (`BaseException` subclass) is never caught.

## Behavior reference

| Situation | Behavior |
|-----------|----------|
| 2xx response | Yields `httpx2.Response`; user consumes body via aiter methods |
| 4xx/5xx response | Yields `httpx2.Response` normally — NO auto-raise. User calls `response.raise_for_status()` for raise-on-error |
| Network error during initial request | Raises `httpware.NetworkError` from `__aenter__` |
| Network error mid-stream | Raises `httpware.NetworkError` from the `async for` line in user code |
| Timeout during request or body consumption | Raises `httpware.TimeoutError` |
| `InvalidURL` / `CookieConflict` | Raises bare `httpware.TransportError` (NOT `NetworkError`) — non-retryable family |
| User code inside `async with` raises | Propagates unchanged; httpx2's context manager cleans up the response |
| `asyncio.CancelledError` during stream | Propagates unchanged; httpx2's context manager cleans up the response; no slot or resource leak |

## Testing

Per `planning/engineering.md §6`. New file `tests/test_client_stream.py`:

- `test_streams_response_body_successfully` — handler returns chunks; assert `async for chunk in response.aiter_bytes()` yields them in order
- `test_does_not_auto_raise_on_4xx` — handler returns 404; assert the context manager yields a Response with `status_code == 404` (no `NotFoundError` raised)
- `test_does_not_auto_raise_on_5xx` — same with 503
- `test_explicit_raise_for_status_works` — user calls `response.raise_for_status()` inside the block; expect `httpx2.HTTPStatusError`
- `test_network_error_during_request_maps_to_network_error` — handler raises `httpx2.ConnectError`; expect `httpware.NetworkError`
- `test_network_error_during_body_consumption_maps_to_network_error` — handler raises `httpx2.ReadError` during the streaming response; expect `httpware.NetworkError` when user iterates body
- `test_timeout_during_stream_maps_to_httpware_timeout` — handler raises `httpx2.ReadTimeout`; expect `httpware.TimeoutError`
- `test_invalid_url_maps_to_bare_transport_error` — handler raises `httpx2.InvalidURL`; expect `httpware.TransportError` and NOT `httpware.NetworkError`
- `test_cancellation_propagates_cleanly` — outer task cancels while body iteration is in progress; expect `asyncio.CancelledError` propagates and stream is closed
- `test_user_exception_in_block_propagates_unchanged` — user raises `ValueError` during chunk processing; expect `ValueError` propagates with no httpware wrapping
- `test_bypasses_middleware_chain` — install a recording middleware that increments a counter on `__call__`; do a `stream()` call; assert counter == 0
- `test_forwards_kwargs_to_httpx2` — pass `params`, `headers`, `cookies`, `extensions`; assert they reach the mock transport's recorded request
- `test_stream_with_content_kwarg` — `client.stream("POST", url, content=b"bytes")` works; mock transport sees the bytes

Coverage target: **100% line coverage** (project standard).

## Public API exports

`stream` is a method on `AsyncClient`, which is already exported from `httpware/__init__.py`. No new top-level exports needed.

## Documentation updates

This PR touches the user-facing docs since we just shipped a docs-sync pass:

- **README.md**: add a brief paragraph (or extend the Quickstart) showing `client.stream()`. Note the no-auto-raise divergence.
- **docs/index.md**: mirror the README addition.
- **planning/engineering.md §1**: append a sentence mentioning the streaming surface.
- **planning/engineering.md §8** roadmap: mark `4-3` shipped; note Epic 4 closes (with the Retry-streamed-body follow-up still open as deferred work).
- **planning/releases/0.5.0.md**: new release notes file.

## Open questions deferred to implementation

- **`httpx2.NetworkError` symbol existence**: confirmed available (used in slice 1 / NetworkError refinement work). No fallback needed.
- **Whether `httpx2.ReadError` raised mid-stream actually maps to `httpx2.NetworkError`**: the implementer should verify `isinstance(httpx2.ReadError(...), httpx2.NetworkError)` is True (it should be per httpx convention). If it isn't, fall back to enumerating: `except (httpx2.ConnectError, httpx2.ReadError, httpx2.WriteError, httpx2.CloseError) as exc`.

## References

- `planning/engineering.md` §1 (project intent), §3 (protocol seams), §5 (module layout), §8 (roadmap)
- `planning/deferred-work.md` §"Retry + streaming bodies" (the open Epic-4-interaction item — stays open after this PR)
- `planning/deferred-work.md` §"Closed by the v0.2 thin-wrapper pivot" → "`httpx2.StreamError` family escape from the transport's `except httpx2.HTTPError`" — closed by this slice's exception mapping
- httpx streaming docs (convention reference): https://www.python-httpx.org/async/#streaming-responses

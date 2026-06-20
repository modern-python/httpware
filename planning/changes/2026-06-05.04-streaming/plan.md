---
status: shipped
date: 2026-06-05
slug: streaming
spec: streaming
pr: 26
---

# AsyncClient.stream + Retry-refuses-streamed-body (0.5.0, Epic 4 story 4-3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `AsyncClient.stream()` (async context-manager yielding `httpx2.Response`, with 4xx/5xx auto-raise + body pre-read, exception mapping via a new shared helper). Close two deferred-work items by also adding `Retry`'s refusal of streamed-body requests (detected via a `request.extensions["httpware.streaming_body"]` marker set in `_request_with_body` when `content`/`data`/`files` is async-iterable).

**Architecture:** Two coordinated changes to `client.py` (helper extraction + `stream()` method + streaming-body marker) and one to `retry.py` (refusal). The `_httpx2_exception_mapper` helper and a `_raise_on_status_error` helper are extracted up front so `_terminal` and `stream()` share dispatch logic — no duplication. `stream()` bypasses the middleware chain (v1 decision); auto-raise on 4xx/5xx with body pre-read keeps consistency with `client.get()`/etc.

**Tech Stack:** Python 3.11+ (`contextlib.asynccontextmanager`, `asyncio`), `httpx2`, `pytest` / `pytest-asyncio` (auto mode), `uv`, `just`, `ruff`, `ty`.

**Target branch:** `feat/v0.5-streaming`. Create from `main` before Task 1: `git checkout main && git pull && git checkout -b feat/v0.5-streaming`.

**Source spec:** [`planning/specs/2026-06-05-streaming-design.md`](../specs/2026-06-05-streaming-design.md). Read it before starting — the *why* for each decision lives there.

---

## File structure

**Modified files:**
- `src/httpware/client.py` — extract `_httpx2_exception_mapper` + `_raise_on_status_error` helpers; refactor `_terminal` to use both; add `_is_streaming_body` helper; add streaming-body marker step in `_request_with_body`; add `stream()` method
- `src/httpware/middleware/resilience/retry.py` — refuse retry when `request.extensions["httpware.streaming_body"]` is True
- `tests/test_retry.py` — add streaming-body refusal tests
- `tests/test_error_mapping_terminal.py` — no test changes; existing tests must still pass after the `_terminal` refactor
- `README.md` — add a streaming snippet to Quickstart
- `docs/index.md` — mirror the README addition
- `planning/engineering.md` — §1 append streaming sentence; §8 mark `4-3` shipped + close Epic 4
- `planning/deferred-work.md` — close the two now-resolved items

**New files:**
- `tests/test_client_stream.py` — unit tests for `AsyncClient.stream()`
- `planning/releases/0.5.0.md` — release notes

**Commit cadence:** one commit per task. Per-task commits keep history reviewable.

---

## Task 1: Branch + extract `_httpx2_exception_mapper` and `_raise_on_status_error` helpers

**Files:**
- Modify: `src/httpware/client.py`

This is a pure refactor of `_terminal`. The dispatch behavior is byte-for-byte identical to today; the existing terminal tests (`tests/test_error_mapping_terminal.py`) cover it and must keep passing. Extracting both helpers up front means `stream()` (Task 4) can use them directly without duplication.

- [ ] **Step 1: Create the branch**

Run:
```bash
git checkout main && git pull && git checkout -b feat/v0.5-streaming
```
Expected: switched to a new branch.

- [ ] **Step 2: Read the current `_terminal` body**

```bash
sed -n '107,130p' src/httpware/client.py
```
Confirm `_terminal` has the structure:
- try/except chain mapping `httpx2.TimeoutException` → `TimeoutError`, `(httpx2.InvalidURL, httpx2.CookieConflict)` → `TransportError`, `httpx2.NetworkError` → `NetworkError`, `httpx2.HTTPError` → `TransportError`, plus a `RuntimeError "closed"` check
- status-code block raising `STATUS_TO_EXCEPTION.get(status, ClientStatusError if status < 500 else ServerStatusError)(response)` for 4xx/5xx

- [ ] **Step 3: Add `contextlib` import**

Add to the existing import block (around line 3, alongside `typing`):
```python
import contextlib
```

Also add `AsyncIterator` to the imports from `collections.abc`. If `collections.abc` is not yet imported (current code uses `Sequence`), make sure both are present:

```python
from collections.abc import AsyncIterator, Sequence
```

- [ ] **Step 4: Add the `_httpx2_exception_mapper` helper at module level**

Insert this `@asynccontextmanager` function immediately before `class AsyncClient:` (i.e., between `_default_pydantic_decoder` and the class definition):

```python
@contextlib.asynccontextmanager
async def _httpx2_exception_mapper() -> AsyncIterator[None]:
    """Map httpx2 exceptions to httpware exceptions. Shared by AsyncClient._terminal and stream()."""
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

Clause ordering MUST match the current `_terminal` exactly: TimeoutException → InvalidURL/CookieConflict → NetworkError → HTTPError. `RuntimeError "closed"` is NOT included here — it's not an httpx2 error and stays inline in `_terminal`.

- [ ] **Step 5: Add the `_raise_on_status_error` helper at module level**

Insert this function immediately after `_httpx2_exception_mapper`:

```python
def _raise_on_status_error(response: httpx2.Response) -> None:
    """Raise the appropriate StatusError subclass for a 4xx/5xx response. No-op for 2xx/3xx."""
    status = response.status_code
    if HTTPStatus.BAD_REQUEST <= status < 600:  # noqa: PLR2004 — 600 is the synthetic upper bound for 5xx
        exc_class = STATUS_TO_EXCEPTION.get(
            status,
            ClientStatusError if status < HTTPStatus.INTERNAL_SERVER_ERROR else ServerStatusError,
        )
        raise exc_class(response)
```

- [ ] **Step 6: Refactor `_terminal` to use both helpers**

Replace the current `_terminal` body (which is the `try`/`except` chain + the status-code block, ~24 lines) with:

```python
async def _terminal(self, request: httpx2.Request) -> httpx2.Response:
    try:
        async with _httpx2_exception_mapper():
            response = await self._httpx2_client.send(request)
    except RuntimeError as exc:
        if "closed" in str(exc):
            raise TransportError(str(exc)) from exc
        raise
    _raise_on_status_error(response)
    return response
```

The `RuntimeError` check stays in `_terminal` (the mapper doesn't cover it — it's a non-httpx2 error specific to the closed-client edge case).

- [ ] **Step 7: Run the existing terminal tests**

```bash
uv run pytest tests/test_error_mapping_terminal.py -v
```
Expected: all PASS. The refactor must not change observable behavior.

- [ ] **Step 8: Run lint + full suite**

```bash
just lint && just test
```
Expected: clean, 100% coverage maintained (was 209 tests; still 209).

- [ ] **Step 9: Stage and commit**

```bash
git add src/httpware/client.py
git commit -m "refactor(client): extract _httpx2_exception_mapper + _raise_on_status_error

Pure refactor of _terminal. Two module-level helpers (one @asynccontextmanager
for the httpx2 exception dispatch, one function for the 4xx/5xx StatusError
raise). _terminal now reads as: enter the mapper, send, raise on status.

Sets up Task 4: AsyncClient.stream() will reuse both helpers verbatim
instead of duplicating the dispatch logic. Behavior is byte-for-byte
identical to today; the existing terminal tests cover it."
```

---

## Task 2: Add `_is_streaming_body` helper + `_request_with_body` streaming-body marker

**Files:**
- Modify: `src/httpware/client.py`
- Modify: `tests/test_retry.py` (or `tests/test_client_construction.py` — pick whichever currently holds AsyncClient/marker-related tests; the spec puts them in test_retry.py since they're part of the Retry-refusal story)

The marker is the detection mechanism Retry will use in Task 3.

- [ ] **Step 1: Write failing tests in `tests/test_retry.py`**

Append to `tests/test_retry.py`:

```python
async def test_client_post_with_async_iterable_content_marks_extensions() -> None:
    """Posting with an async-iterable body sets the httpware.streaming_body marker on request.extensions."""
    seen_extensions: list[dict[str, object]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen_extensions.append(dict(request.extensions))
        return httpx2.Response(HTTPStatus.OK, request=request)

    async def streamed_body() -> typing.AsyncIterator[bytes]:
        yield b"chunk1"
        yield b"chunk2"

    transport = httpx2.MockTransport(handler)
    client = AsyncClient(httpx2_client=httpx2.AsyncClient(transport=transport))
    await client.post("https://example.test/upload", content=streamed_body())

    assert len(seen_extensions) == 1
    assert seen_extensions[0].get("httpware.streaming_body") is True


async def test_client_post_with_bytes_content_does_not_mark_extensions() -> None:
    seen_extensions: list[dict[str, object]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen_extensions.append(dict(request.extensions))
        return httpx2.Response(HTTPStatus.OK, request=request)

    transport = httpx2.MockTransport(handler)
    client = AsyncClient(httpx2_client=httpx2.AsyncClient(transport=transport))
    await client.post("https://example.test/upload", content=b"hi")

    assert len(seen_extensions) == 1
    assert "httpware.streaming_body" not in seen_extensions[0]


async def test_client_post_with_dict_data_does_not_mark_extensions() -> None:
    seen_extensions: list[dict[str, object]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen_extensions.append(dict(request.extensions))
        return httpx2.Response(HTTPStatus.OK, request=request)

    transport = httpx2.MockTransport(handler)
    client = AsyncClient(httpx2_client=httpx2.AsyncClient(transport=transport))
    await client.post("https://example.test/upload", data={"k": "v"})

    assert len(seen_extensions) == 1
    assert "httpware.streaming_body" not in seen_extensions[0]


async def test_client_post_with_async_iterable_data_marks_extensions() -> None:
    seen_extensions: list[dict[str, object]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen_extensions.append(dict(request.extensions))
        return httpx2.Response(HTTPStatus.OK, request=request)

    async def streamed_data() -> typing.AsyncIterator[bytes]:
        yield b"x"

    transport = httpx2.MockTransport(handler)
    client = AsyncClient(httpx2_client=httpx2.AsyncClient(transport=transport))
    await client.post("https://example.test/upload", data=streamed_data())

    assert len(seen_extensions) == 1
    assert seen_extensions[0].get("httpware.streaming_body") is True


async def test_client_post_with_async_iterable_files_marks_extensions() -> None:
    seen_extensions: list[dict[str, object]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen_extensions.append(dict(request.extensions))
        return httpx2.Response(HTTPStatus.OK, request=request)

    async def streamed_files() -> typing.AsyncIterator[bytes]:
        yield b"x"

    transport = httpx2.MockTransport(handler)
    client = AsyncClient(httpx2_client=httpx2.AsyncClient(transport=transport))
    await client.post("https://example.test/upload", files=streamed_files())

    assert len(seen_extensions) == 1
    assert seen_extensions[0].get("httpware.streaming_body") is True
```

`typing` is already imported at the top of `tests/test_retry.py`; if not, add `import typing` to the top.

Run: `uv run pytest tests/test_retry.py -v -k "marks_extensions or does_not_mark_extensions"`
Expected: all 5 FAIL — the marker isn't set yet.

- [ ] **Step 2: Add `_is_streaming_body` helper at module level**

In `src/httpware/client.py`, immediately after `_raise_on_status_error` (added in Task 1), insert:

```python
def _is_streaming_body(value: typing.Any) -> bool:
    """True if value is an async-iterable that cannot be safely replayed for retry."""
    if value is None:
        return False
    if isinstance(value, (bytes, bytearray, memoryview, str, dict)):
        return False
    return hasattr(value, "__aiter__")
```

- [ ] **Step 3: Set the streaming-body marker in `_request_with_body`**

Locate `_request_with_body` (around `client.py:153`). Find the line:
```python
request = self._httpx2_client.build_request(method, url, **kwargs)
return await self.send(request, response_model=response_model)
```

Replace with:
```python
request = self._httpx2_client.build_request(method, url, **kwargs)
if _is_streaming_body(content) or _is_streaming_body(data) or _is_streaming_body(files):
    request.extensions["httpware.streaming_body"] = True
return await self.send(request, response_model=response_model)
```

NOTE: `httpx2.Request.extensions` is a `dict[str, Any]` per httpx convention. If during implementation you find it can be `None` on a freshly-built request, swap to:
```python
extensions_dict = dict(request.extensions or {})
extensions_dict["httpware.streaming_body"] = True
request.extensions = extensions_dict
```

- [ ] **Step 4: Run the new tests**

```bash
uv run pytest tests/test_retry.py -v -k "marks_extensions or does_not_mark_extensions"
```
Expected: all 5 PASS.

- [ ] **Step 5: Lint + full suite**

```bash
just lint && just test
```
Expected: clean, 100% coverage.

- [ ] **Step 6: Stage and commit**

```bash
git add src/httpware/client.py tests/test_retry.py
git commit -m "feat(client): mark requests with async-iterable bodies via extensions

Adds a _is_streaming_body helper and a marker step in _request_with_body:
when content / data / files is an async-iterable, set
request.extensions['httpware.streaming_body'] = True before sending.

Sets up Task 3: Retry will read the marker and refuse to retry streamed-body
requests (they can't replay across attempts). Today the marker has no
consumer; it's harmless metadata."
```

---

## Task 3: `Retry` refuses streamed-body requests

**Files:**
- Modify: `src/httpware/middleware/resilience/retry.py`
- Modify: `tests/test_retry.py`

- [ ] **Step 1: Write failing tests in `tests/test_retry.py`**

Append:

```python
async def test_retry_refuses_streamed_body_request() -> None:
    """Retry must not replay a request with a streaming body — re-raise with a PEP-678 note."""
    sleeper = _SleepRecorder()
    call_count = {"n": 0}

    def handler(request: httpx2.Request) -> httpx2.Response:
        call_count["n"] += 1
        return httpx2.Response(HTTPStatus.SERVICE_UNAVAILABLE, request=request)

    async def streamed_body() -> typing.AsyncIterator[bytes]:
        yield b"x"

    transport = httpx2.MockTransport(handler)
    client = AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=transport),
        middleware=[Retry(_sleep=sleeper, base_delay=0.001, max_delay=0.002)],
    )

    with pytest.raises(ServiceUnavailableError) as info:
        await client.post("https://example.test/upload", content=streamed_body())

    assert call_count["n"] == 1
    assert sleeper.calls == []  # no retry attempted
    notes = getattr(info.value, "__notes__", [])
    assert any("not retrying" in note and "stream" in note for note in notes)


async def test_retry_refuses_streamed_body_does_not_consume_budget() -> None:
    """When Retry refuses for streaming-body reasons, no budget token is withdrawn."""
    sleeper = _SleepRecorder()
    budget = RetryBudget(ttl=10.0, min_retries_per_sec=10.0, percent_can_retry=0.2)

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(HTTPStatus.SERVICE_UNAVAILABLE, request=request)

    async def streamed_body() -> typing.AsyncIterator[bytes]:
        yield b"x"

    transport = httpx2.MockTransport(handler)
    client = AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=transport),
        middleware=[Retry(_sleep=sleeper, budget=budget, base_delay=0.001, max_delay=0.002)],
    )

    with pytest.raises(ServiceUnavailableError):
        await client.post("https://example.test/upload", content=streamed_body())

    # Budget should be untouched: deposits OK (every attempt deposits), but no withdrawals.
    # Check via _withdrawn deque emptiness.
    assert len(budget._withdrawn) == 0  # noqa: SLF001 — implementation-detail access for invariant
```

`Retry`, `RetryBudget`, `_SleepRecorder`, `ServiceUnavailableError`, and `pytest` should already be imported in `tests/test_retry.py`; verify and add any missing imports at the top of the file.

Run: `uv run pytest tests/test_retry.py -v -k "refuses_streamed_body"`
Expected: FAIL — both attempts will retry (Retry doesn't yet check the marker).

- [ ] **Step 2: Add the streamed-body check to `Retry.__call__`**

Read `src/httpware/middleware/resilience/retry.py`. Find the retryable-failure path — specifically, the block just after the `except` clauses and before the `if not self.budget.try_withdraw():` check.

Insert the refusal block immediately after `# ---- retryable failure path` and BEFORE the `if is_last:` check:

```python
            # ---- retryable failure path
            if request.extensions.get("httpware.streaming_body"):
                if last_exc is None:  # pragma: no cover — invariant from except branch
                    msg = "Retry: streaming-body refusal reached with no last_exc"
                    raise AssertionError(msg)
                last_exc.add_note(
                    "httpware: not retrying — request body is a stream that cannot replay across attempts"
                )
                raise last_exc

            if is_last:
                ...
```

The streaming-body check comes FIRST (before is_last + before budget.try_withdraw()) so we don't consume a budget token for a request we won't retry. The PEP-678 note follows the same `add_note` pattern as the max-attempts exhaustion path.

- [ ] **Step 3: Run the new tests**

```bash
uv run pytest tests/test_retry.py -v -k "refuses_streamed_body"
```
Expected: both PASS.

- [ ] **Step 4: Lint + full suite**

```bash
just lint && just test
```
Expected: clean, 100% coverage.

- [ ] **Step 5: Stage and commit**

```bash
git add src/httpware/middleware/resilience/retry.py tests/test_retry.py
git commit -m "feat(resilience): Retry refuses requests with streaming bodies

Closes the deferred-work item 'Retry + streaming bodies'. When the
request was constructed with an async-iterable content/data/files,
_request_with_body marked request.extensions['httpware.streaming_body']
= True. Retry now reads the marker and re-raises the original failure
with a PEP-678 note ('not retrying — request body is a stream that
cannot replay across attempts') instead of retrying with a consumed
iterator.

Check happens BEFORE budget.try_withdraw() so a refused retry doesn't
consume a budget token."
```

---

## Task 4: Add `AsyncClient.stream()` context-manager method

**Files:**
- Modify: `src/httpware/client.py`
- Create: `tests/test_client_stream.py`

This is the largest task — the method body, its tests, the integration with the helpers from Task 1.

- [ ] **Step 1: Write failing tests in `tests/test_client_stream.py`**

Create `tests/test_client_stream.py`:

```python
"""Tests for AsyncClient.stream() context manager."""

import asyncio
import typing
from http import HTTPStatus

import httpx2
import pytest

from httpware import (
    AsyncClient,
    ClientStatusError,
    NetworkError,
    NotFoundError,
    ServerStatusError,
    ServiceUnavailableError,
    TimeoutError as HttpwareTimeoutError,  # noqa: A004
    TransportError,
)
from httpware.middleware import Middleware, Next


_UNKNOWN_4XX = 418  # I'm a teapot
_UNKNOWN_5XX = 599
_REDIRECT_3XX = 301
_NOT_FOUND = 404
_SERVICE_UNAVAILABLE = 503


def _client(handler: typing.Callable[[httpx2.Request], httpx2.Response]) -> AsyncClient:
    transport = httpx2.MockTransport(handler)
    return AsyncClient(httpx2_client=httpx2.AsyncClient(transport=transport))


async def test_streams_response_body_successfully() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(HTTPStatus.OK, request=request, content=b"chunk1chunk2chunk3")

    client = _client(handler)
    chunks: list[bytes] = []
    async with client.stream("GET", "https://example.test/x") as response:
        assert response.status_code == HTTPStatus.OK
        async for chunk in response.aiter_bytes():
            chunks.append(chunk)
    assert b"".join(chunks) == b"chunk1chunk2chunk3"


async def test_auto_raises_on_4xx_with_body_preread() -> None:
    body = b'{"error": "not found"}'

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(_NOT_FOUND, request=request, content=body)

    client = _client(handler)
    with pytest.raises(NotFoundError) as info:
        async with client.stream("GET", "https://example.test/missing"):
            pytest.fail("should have raised before reaching block body")  # pragma: no cover
    assert info.value.response.status_code == _NOT_FOUND
    assert info.value.response.content == body  # body was pre-read; accessible


async def test_auto_raises_on_5xx_with_body_preread() -> None:
    body = b"degraded"

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(_SERVICE_UNAVAILABLE, request=request, content=body)

    client = _client(handler)
    with pytest.raises(ServiceUnavailableError) as info:
        async with client.stream("GET", "https://example.test/x"):
            pytest.fail("unreachable")  # pragma: no cover
    assert info.value.response.content == body


async def test_auto_raises_unknown_4xx_falls_back_to_client_status_error() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(_UNKNOWN_4XX, request=request)

    client = _client(handler)
    with pytest.raises(ClientStatusError) as info:
        async with client.stream("GET", "https://example.test/x"):
            pytest.fail("unreachable")  # pragma: no cover
    assert type(info.value) is ClientStatusError
    assert info.value.response.status_code == _UNKNOWN_4XX


async def test_auto_raises_unknown_5xx_falls_back_to_server_status_error() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(_UNKNOWN_5XX, request=request)

    client = _client(handler)
    with pytest.raises(ServerStatusError) as info:
        async with client.stream("GET", "https://example.test/x"):
            pytest.fail("unreachable")  # pragma: no cover
    assert type(info.value) is ServerStatusError
    assert info.value.response.status_code == _UNKNOWN_5XX


async def test_3xx_does_not_raise() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(_REDIRECT_3XX, request=request, headers={"location": "/y"})

    client = _client(handler)
    async with client.stream("GET", "https://example.test/x") as response:
        assert response.status_code == _REDIRECT_3XX


async def test_network_error_during_request_maps_to_network_error() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        msg = "connect refused"
        raise httpx2.ConnectError(msg)

    client = _client(handler)
    with pytest.raises(NetworkError, match="connect refused"):
        async with client.stream("GET", "https://example.test/x"):
            pytest.fail("unreachable")  # pragma: no cover


async def test_network_error_during_body_consumption_maps_to_network_error() -> None:
    async def streaming_body() -> typing.AsyncIterator[bytes]:
        yield b"first chunk"
        msg = "read failed mid-stream"
        raise httpx2.ReadError(msg)

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(HTTPStatus.OK, request=request, content=streaming_body())

    client = _client(handler)
    with pytest.raises(NetworkError, match="read failed mid-stream"):
        async with client.stream("GET", "https://example.test/x") as response:
            async for _ in response.aiter_bytes():
                pass


async def test_timeout_during_stream_maps_to_httpware_timeout() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        msg = "read timeout"
        raise httpx2.ReadTimeout(msg)

    client = _client(handler)
    with pytest.raises(HttpwareTimeoutError, match="read timeout"):
        async with client.stream("GET", "https://example.test/x"):
            pytest.fail("unreachable")  # pragma: no cover


async def test_invalid_url_maps_to_bare_transport_error() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        msg = "bad url"
        raise httpx2.InvalidURL(msg)

    client = _client(handler)
    with pytest.raises(TransportError) as info:
        async with client.stream("GET", "https://example.test/x"):
            pytest.fail("unreachable")  # pragma: no cover
    assert not isinstance(info.value, NetworkError)


async def test_cancellation_propagates_cleanly() -> None:
    async def slow_body() -> typing.AsyncIterator[bytes]:
        yield b"first"
        await asyncio.sleep(1.0)
        yield b"second"  # pragma: no cover

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(HTTPStatus.OK, request=request, content=slow_body())

    client = _client(handler)

    async def consume() -> None:
        async with client.stream("GET", "https://example.test/x") as response:
            async for _ in response.aiter_bytes():
                pass

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.01)  # let body consumption begin
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_user_exception_in_block_propagates_unchanged() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(HTTPStatus.OK, request=request, content=b"data")

    client = _client(handler)
    with pytest.raises(ValueError, match="user explosion"):
        async with client.stream("GET", "https://example.test/x"):
            msg = "user explosion"
            raise ValueError(msg)


async def test_bypasses_middleware_chain() -> None:
    """stream() must not invoke any middleware in the chain."""
    invocations = {"n": 0}

    class _RecordingMiddleware:
        async def __call__(self, request: httpx2.Request, next: Next) -> httpx2.Response:  # noqa: A002
            invocations["n"] += 1
            return await next(request)

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(HTTPStatus.OK, request=request, content=b"x")

    transport = httpx2.MockTransport(handler)
    middleware: Middleware = _RecordingMiddleware()
    client = AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=transport),
        middleware=[middleware],
    )

    async with client.stream("GET", "https://example.test/x") as response:
        async for _ in response.aiter_bytes():
            pass

    assert invocations["n"] == 0


async def test_forwards_kwargs_to_httpx2() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(HTTPStatus.OK, request=request, content=b"")

    client = _client(handler)
    async with client.stream(
        "GET",
        "https://example.test/x",
        params={"q": "value"},
        headers={"X-Custom": "1"},
        cookies={"sid": "abc"},
    ) as response:
        async for _ in response.aiter_bytes():
            pass

    request = seen[0]
    assert request.url.params["q"] == "value"
    assert request.headers["x-custom"] == "1"
    assert request.headers["cookie"] == "sid=abc"


async def test_stream_with_content_kwarg() -> None:
    seen: list[bytes] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request.content)
        return httpx2.Response(HTTPStatus.OK, request=request, content=b"")

    client = _client(handler)
    async with client.stream("POST", "https://example.test/upload", content=b"payload") as response:
        async for _ in response.aiter_bytes():
            pass

    assert seen[0] == b"payload"


async def test_stream_with_async_iterable_content() -> None:
    """stream() bypass means async-iterable bodies work without the streaming-body marker mechanism."""
    seen_calls: list[int] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen_calls.append(1)
        return httpx2.Response(HTTPStatus.OK, request=request, content=b"")

    async def streamed_body() -> typing.AsyncIterator[bytes]:
        yield b"chunk1"
        yield b"chunk2"

    client = _client(handler)
    async with client.stream("POST", "https://example.test/upload", content=streamed_body()) as response:
        async for _ in response.aiter_bytes():
            pass

    assert seen_calls == [1]
```

Run: `uv run pytest tests/test_client_stream.py -v`
Expected: all FAIL with `AttributeError: 'AsyncClient' object has no attribute 'stream'`.

- [ ] **Step 2: Implement `AsyncClient.stream()`**

Add this method to `AsyncClient` in `src/httpware/client.py`. Place it AFTER the existing `request()` method (the last per-method definition) and BEFORE `__aenter__`:

```python
@contextlib.asynccontextmanager
async def stream(  # noqa: PLR0913 — mirrors httpx2 per-method signatures
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
    The body is NOT pre-read for 2xx/3xx (streaming preserved); the response
    is closed when the context exits.

    Bypasses the middleware chain (no Retry, no Bulkhead, no user-installed
    middleware) for v1 — see planning/specs/2026-06-05-streaming-design.md.

    Auto-raises StatusError subclasses on 4xx/5xx (NotFoundError,
    ServiceUnavailableError, etc.) — consistent with client.get()/post()/etc.
    On error the response body is pre-read so exc.response.content is
    accessible. You lose the streaming property on errors; rare in practice.

    Maps httpx2 exceptions raised during the request OR body consumption to
    httpware exceptions via _httpx2_exception_mapper.
    """
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
            if HTTPStatus.BAD_REQUEST <= response.status_code < 600:  # noqa: PLR2004 — 600 is the synthetic upper bound for 5xx
                await response.aread()  # pre-read body so exc.response.content works
                _raise_on_status_error(response)
            yield response
```

Note: `_raise_on_status_error` actually doesn't need the wrapping `if` check because it's a no-op for non-error status; you could simplify. But the explicit `if` here makes it obvious that `aread()` only runs on errors. Keep both. Alternatively if simpler:

```python
if HTTPStatus.BAD_REQUEST <= response.status_code < 600:
    await response.aread()
_raise_on_status_error(response)  # raises iff 4xx/5xx
yield response
```

Either form is fine. The explicit version makes the "only pre-read on error" intent obvious; pick that one.

- [ ] **Step 3: Run the stream tests**

```bash
uv run pytest tests/test_client_stream.py -v
```
Expected: all PASS.

- [ ] **Step 4: Lint + full suite**

```bash
just lint && just test
```
Expected: clean, 100% coverage.

- [ ] **Step 5: Stage and commit**

```bash
git add src/httpware/client.py tests/test_client_stream.py
git commit -m "feat(client): AsyncClient.stream() context manager

Adds AsyncClient.stream(method, url, **kwargs) as a
@contextlib.asynccontextmanager method on the client. Mirrors
httpx2.AsyncClient.stream() but auto-raises StatusError subclasses
on 4xx/5xx (consistent with client.get/post/etc.) with body
pre-read so exc.response.content is accessible.

Bypasses the middleware chain (v1 design decision — revisit if user
feedback warrants). Uses the shared _httpx2_exception_mapper and
_raise_on_status_error helpers extracted in the earlier refactor
commit, so dispatch logic stays in lockstep with _terminal.

Body consumption errors during 'async for chunk in response.aiter_bytes()'
propagate through the yield and get mapped to httpware exceptions
consistently."
```

---

## Task 5: Documentation + release notes

**Files:**
- Modify: `README.md`
- Modify: `docs/index.md`
- Modify: `planning/engineering.md`
- Modify: `planning/deferred-work.md`
- Create: `planning/releases/0.5.0.md`

- [ ] **Step 1: Add streaming snippet to README.md**

After the existing "With resilience middleware" subsection and BEFORE the `## Errors` section, insert a new `### Streaming responses` subsection:

```markdown

### Streaming responses

For large responses or server-sent events, stream the body chunk-by-chunk. `stream()` is an async context manager:

```python
from httpware import AsyncClient


async def main() -> None:
    async with AsyncClient(base_url="https://api.example.com") as client:
        async with client.stream("GET", "/big-file") as response:
            async for chunk in response.aiter_bytes():
                process(chunk)
```

`stream()` auto-raises `StatusError` subclasses on 4xx/5xx with the response body pre-read, so `exc.response.content` is accessible from the caught exception.

It does NOT pass through the middleware chain: `Retry`, `Bulkhead`, and any custom middleware are bypassed. (Retry separately refuses to retry any request — stream or non-stream — whose body was an async-iterable, since streams can't replay across attempts.)
```

- [ ] **Step 2: Mirror the addition in `docs/index.md`**

Same content added at the matching position (after the "With resilience middleware" subsection, before the `## Errors` section). Keep the wording verbatim so the README and docs/index.md stay in sync.

- [ ] **Step 3: Update `planning/engineering.md`**

In §1 (Project intent), append one sentence to the first paragraph (after the resilience-suite sentence added in the 0.4 docs sync):

```
 As of 0.5.0, `AsyncClient.stream()` provides a context-manager API for chunked response bodies; it bypasses the middleware chain by design (see planning/specs/2026-06-05-streaming-design.md).
```

In §8 (Remaining roadmap), find the Epic 4 entry:
```
- **Epic 4 — Streaming:** `4-3` `AsyncClient.stream` context manager (forwards to `httpx2.AsyncClient.stream`; no `StreamResponse` type).
```
Replace with:
```
- **Epic 4 — Streaming:** SHIPPED in v0.5 (PR #...): `AsyncClient.stream()` context manager + Retry refuses streamed-body requests. See [`planning/specs/2026-06-05-streaming-design.md`](specs/2026-06-05-streaming-design.md) and [`planning/plans/2026-06-05-streaming-plan.md`](plans/2026-06-05-streaming-plan.md).
```

(Use the actual PR number once the PR is opened — leave a `#…` placeholder if the PR doesn't exist yet; the implementer fills in during finishing-a-development-branch.)

- [ ] **Step 4: Close the two deferred-work items**

Edit `planning/deferred-work.md`. The two items to close:

1. Under `## Open` → `### Retry + streaming bodies (Epic 4 interaction)`: remove this entire entry.

2. Under `## Closed by the v0.2 thin-wrapper pivot (2026-06-03)`: the line `- httpx2.StreamError family escape from the transport's except httpx2.HTTPError (mapping logic relocated to AsyncClient's terminal; revisit with Epic 4 streaming work).` — replace the trailing parenthetical with `; closed by 0.5.0 streaming work — exception mapping in _httpx2_exception_mapper covers the StreamError family via httpx2.NetworkError).`

Then add a NEW section above the "Closed by the v0.2 thin-wrapper pivot" one:

```markdown
## Closed by the 0.5.0 streaming release (2026-06-05)

- **`Retry` refuses streamed-body requests.** When `_request_with_body` is called with an async-iterable `content`/`data`/`files`, the request gets `extensions["httpware.streaming_body"] = True`. `Retry.__call__` reads the marker and re-raises with a PEP-678 note on retryable failures instead of retrying with a consumed iterator. Closes the prior Open entry.
- **`httpx2.StreamError` family escape closed.** The new shared `_httpx2_exception_mapper` catches `httpx2.NetworkError` (which is the parent of `ReadError` / `WriteError` / `CloseError`), so stream-specific exceptions raised during body consumption now map to `httpware.NetworkError` consistently.
```

- [ ] **Step 5: Create `planning/releases/0.5.0.md`**

```markdown
# httpware 0.5.0 — Streaming responses

**0.5.0 is additive. No breaking changes.** Code written against 0.4.0 continues to work unchanged.

This release closes Epic 4 by adding `AsyncClient.stream()` for chunked response bodies, and closes two longstanding deferred-work items along the way.

## New features

- **`AsyncClient.stream(method, url, **kwargs)`** — async context manager that yields an `httpx2.Response` with a non-pre-read body. Consume via `response.aiter_bytes()`, `response.aiter_text()`, `response.aiter_lines()`, or `response.aiter_raw()`. Auto-raises `StatusError` subclasses on 4xx/5xx (with the body pre-read so `exc.response.content` works). Bypasses the middleware chain by design — `Retry`, `Bulkhead`, and user-installed middleware do not see `stream()` calls in v1.
- **`Retry` refuses streamed-body requests.** When you call `client.post(content=async_gen())` (or `data=`, `files=`), the request is marked via `request.extensions["httpware.streaming_body"]`. If `Retry` would otherwise retry on a failure, it re-raises the original exception with a PEP 678 note instead — preventing the "consumed iterator can't replay" footgun.

## Backwards compatibility

Subclassing/extensions preserve every existing catch-block:

- All previously-shipping methods (`get`, `post`, etc.) behave identically.
- The internal refactor that extracted `_httpx2_exception_mapper` from `_terminal` is byte-for-byte equivalent in dispatch behavior. Tests prove this.
- The streaming-body marker (`request.extensions["httpware.streaming_body"]`) only affects requests that genuinely have async-iterable bodies. Existing code passing bytes / dict / files-as-bytes is unaffected.

## Usage

```python
from httpware import AsyncClient


async def main() -> None:
    async with AsyncClient(base_url="https://api.example.com") as client:
        async with client.stream("GET", "/big-file") as response:
            async for chunk in response.aiter_bytes():
                process(chunk)
```

Catch typed status errors on streams the same way as on regular calls:

```python
from httpware import NotFoundError

try:
    async with client.stream("GET", "/maybe-missing") as response:
        ...
except NotFoundError as exc:
    body_text = exc.response.text  # pre-read; accessible
```

## What's still ahead

- Epic 5 (observability hooks + OTel middleware) is unstarted; logging of retry / bulkhead / stream decisions plumbs through then.
- Whether `stream()` should compose with the middleware chain is deferred to real-user feedback. Adding it later is purely additive (`stream(..., apply_middleware: bool = False)` opt-in).

## References

- Spec: [`planning/specs/2026-06-05-streaming-design.md`](../specs/2026-06-05-streaming-design.md)
- Plan: [`planning/plans/2026-06-05-streaming-plan.md`](../plans/2026-06-05-streaming-plan.md)
- Roadmap: [`planning/engineering.md`](../engineering.md) §8
```

- [ ] **Step 6: Lint**

```bash
just lint
```
Expected: clean. (eof-fixer + ruff format may normalize the markdown.)

- [ ] **Step 7: Stage and commit**

```bash
git add README.md docs/index.md planning/engineering.md planning/deferred-work.md planning/releases/0.5.0.md
git commit -m "docs: 0.5.0 release notes + sync user docs with streaming work

- README + docs/index.md: add 'Streaming responses' subsection
- planning/engineering.md §1 + §8: mention stream() in project intent;
  mark Epic 4 SHIPPED in roadmap
- planning/deferred-work.md: close the 'Retry + streaming bodies' open
  item and update the v0.2-pivot StreamError-escape entry; add a new
  'Closed by the 0.5.0 streaming release' section
- planning/releases/0.5.0.md: new release notes"
```

---

## Task 6: Final verification + push

**Files:** none modified; verification only.

- [ ] **Step 1: Full lint**

```bash
just lint-ci
```
Expected: clean.

- [ ] **Step 2: Full test suite**

```bash
just test
```
Expected: ALL tests PASS, coverage = 100%. Test count should be 209 (current) + ~5 marker tests + 2 retry-refuse tests + ~16 stream tests = ~232.

- [ ] **Step 3: Architecture invariants from `CLAUDE.md`**

```bash
grep -rE 'httpx2\._' src/httpware/ || echo "PASS: no httpx2 private API"
grep -rE 'from __future__ import annotations' src/httpware/ || echo "PASS: no __future__ annotations"
grep -rE '\bprint\(' src/httpware/ || echo "PASS: no print()"
grep -rE 'logging\.(basicConfig|getLogger)\(\)' src/httpware/ || echo "PASS: no global logging"
grep -rE '# (type|mypy): ignore' src/httpware/ || echo "PASS: no type/mypy ignore"
```
Each should print PASS.

- [ ] **Step 4: Optional-extras isolation**

`stream()` is pure stdlib — no new optional deps.
```bash
uv run pytest tests/test_optional_extras_isolation.py -v
```
Expected: PASS.

- [ ] **Step 5: mkdocs strict build**

```bash
uv run --with mkdocs --with mkdocs-material mkdocs build --strict 2>&1 | tail -10
rm -rf site/
```
Expected: 0 warnings. (Previous PR closed all nav-warnings; this one only adds content under `index.md`.)

- [ ] **Step 6: Push the branch**

```bash
git push -u origin feat/v0.5-streaming
```

DO NOT open the PR yet — leave that to `finishing-a-development-branch`.

---

## Out of scope for this plan (per the spec)

These items are deliberately deferred. Do NOT do them in this PR:

- **`stream()` going through the middleware chain.** Stays bypassed for v1. Adding `apply_middleware: bool = False` opt-in later is purely additive.
- **`StreamResponse` wrapper type.** Explicit non-goal from the original story wording.
- **`response_model=` decoding parameter for stream().** Doesn't apply.
- **Bulkhead-during-stream integration.** Bulkhead doesn't see stream() calls.
- **Detection of streaming bodies on manually-constructed `httpx2.Request` objects.** Marker only set in `_request_with_body`; manual constructors accept responsibility.
- **Version bump in `pyproject.toml`.** Tag-driven release; bump not required (see prior pattern: 0.4.0 release notes shipped without a pyproject bump).

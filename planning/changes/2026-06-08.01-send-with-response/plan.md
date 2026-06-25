# `send_with_response` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `send_with_response(request, *, response_model) -> tuple[httpx2.Response, T]` to both `AsyncClient` and `Client`, so callers (Link-header pagination being the canonical case) can obtain the raw response and a decoded body in one call routed through the configured `ResponseDecoder`.

**Architecture:** New public method on each client class, mirroring `send`'s seam: `_dispatch(request)` runs the middleware chain (transport/status errors raise untouched), `self._decoder.decode(...)` runs inside a try/except that wraps any exception as `httpware.DecodeError`. Return `(response, decoded)`. No overload — return type is always `tuple[Response, T]`. No change to `send`, the verb methods, decoders, or any existing test.

**Tech Stack:** Python 3.11+, `httpx2`, pydantic 2.x (default decoder; optional extra), `pytest` + `pytest-asyncio` auto mode, `ty` for type checking, `ruff` for lint, `just` task runner.

---

## Spec reference

The validated spec is at `planning/specs/2026-06-08-send-with-response-design.md`. Read it before starting. Decisions locked there and not re-debated here:

- One new method per client class — **no per-verb siblings** (`get_with_response` etc.), **no `request_with_response`**.
- `response_model` is **required** (no default). Body-only callers use `send(..., response_model=)`; response-only callers use `send(request)`.
- **No `@typing.overload` block** — return type is always `tuple[httpx2.Response, T]`.
- **No streaming support.** Decodes `response.content`.
- **Error contract reuses `DecodeError`** from `0.8.1` — no new exception class. `_dispatch` errors (transport/timeout/status) propagate untouched, identical to `send(..., response_model=)`.
- **Target release: `0.8.2`** (patch — purely additive).

## File structure

| Path | Operation | Responsibility |
|---|---|---|
| `src/httpware/client.py` | modify | Add `AsyncClient.send_with_response` immediately after `AsyncClient.send` (current end `:160`); add `Client.send_with_response` immediately after `Client.send` (current end `:880`). |
| `tests/test_client_send_with_response.py` | create | Async tests: success, decode failure, status error, ClientError catches, middleware runs, request URL preserved. |
| `tests/test_client_send_with_response_sync.py` | create | Sync siblings of the async tests. |
| `docs/index.md` | modify | Insert a `### Response metadata + typed body` subsection between line 82 (end of `response_model=` example) and line 84 (`### Streaming responses`). |
| `planning/engineering.md` | modify | Update Seam B contract (line 42) to name `send_with_response` alongside `send` as the two call sites that wrap decoder exceptions. |

**No changes** to: `src/httpware/__init__.py`, `tests/test_public_api.py`, `src/httpware/errors.py`, `src/httpware/decoders/*`, `tests/test_client_typing.py`. `send_with_response` is a method on already-exported classes — no new module-level symbol; the return type is non-conditional so the typing-test file doesn't grow.

## A note on TDD here

This plan follows code-style TDD: each behavior change is exercised by a failing test first, the test is run to confirm it fails for the expected reason (`AttributeError` because the method doesn't exist yet), then the minimal implementation is written, then the test is re-run to confirm it passes, then committed. The docs / engineering.md update ships with a manual review step rather than a failing test.

---

## Task 1: Async tests — write the red-phase tests for `AsyncClient.send_with_response`

**Files:**
- Create: `tests/test_client_send_with_response.py`

- [ ] **Step 1: Create `tests/test_client_send_with_response.py` with the failing tests**

Write the full file:

```python
"""Tests for AsyncClient.send_with_response — atomic (response, decoded) pair."""

from http import HTTPStatus

import httpx2
import pydantic
import pytest

from httpware import AsyncClient, ClientError, DecodeError, NotFoundError
from httpware.middleware import async_before_request


class _User(pydantic.BaseModel):
    id: int
    name: str


def _client_with_payload(
    payload: bytes,
    *,
    status: int = HTTPStatus.OK,
    headers: dict[str, str] | None = None,
    record: list[httpx2.Request] | None = None,
) -> AsyncClient:
    response_headers = {"content-type": "application/json"}
    if headers is not None:
        response_headers.update(headers)

    def handler(request: httpx2.Request) -> httpx2.Response:
        if record is not None:
            record.append(request)
        return httpx2.Response(status, content=payload, headers=response_headers, request=request)

    transport = httpx2.MockTransport(handler)
    return AsyncClient(httpx2_client=httpx2.AsyncClient(transport=transport))


async def test_send_with_response_returns_response_and_decoded() -> None:
    client = _client_with_payload(b'{"id": 1, "name": "ada"}')
    request = client.build_request("GET", "https://example.test/u")
    response, user = await client.send_with_response(request, response_model=_User)
    assert isinstance(response, httpx2.Response)
    assert isinstance(user, _User)
    assert user == _User(id=1, name="ada")
    assert response.content == b'{"id": 1, "name": "ada"}'


async def test_send_with_response_preserves_response_headers() -> None:
    """Pagination callers read Link / X-Total-Count off the returned response."""
    client = _client_with_payload(
        b'{"id": 1, "name": "p"}',
        headers={"link": '<https://example.test/u?page=2>; rel="next"', "x-total-count": "100"},
    )
    request = client.build_request("GET", "https://example.test/u?page=1")
    response, _ = await client.send_with_response(request, response_model=_User)
    assert response.headers.get("link") == '<https://example.test/u?page=2>; rel="next"'
    assert response.headers.get("x-total-count") == "100"


async def test_send_with_response_response_request_url_populated() -> None:
    """Pagination loops do str(response.request.url) to compute the next page."""
    client = _client_with_payload(b'{"id": 1, "name": "p"}')
    request = client.build_request("GET", "https://example.test/u?page=1")
    response, _ = await client.send_with_response(request, response_model=_User)
    assert str(response.request.url) == "https://example.test/u?page=1"


async def test_send_with_response_decode_failure_raises_decode_error() -> None:
    client = _client_with_payload(b"null")
    request = client.build_request("GET", "https://example.test/u")
    with pytest.raises(DecodeError) as exc_info:
        await client.send_with_response(request, response_model=_User)
    exc = exc_info.value
    assert exc.response.status_code == HTTPStatus.OK
    assert exc.model is _User
    assert isinstance(exc.original, pydantic.ValidationError)
    assert exc.__cause__ is exc.original


async def test_send_with_response_malformed_json_raises_decode_error() -> None:
    client = _client_with_payload(b"{not json")
    request = client.build_request("GET", "https://example.test/u")
    with pytest.raises(DecodeError):
        await client.send_with_response(request, response_model=_User)


async def test_send_with_response_decode_error_caught_by_client_error() -> None:
    """The user-facing promise: `except ClientError` catches decode failures."""
    client = _client_with_payload(b"null")
    request = client.build_request("GET", "https://example.test/u")
    with pytest.raises(ClientError) as exc_info:
        await client.send_with_response(request, response_model=_User)
    assert isinstance(exc_info.value, DecodeError)


async def test_send_with_response_status_error_raised_before_decoder_runs() -> None:
    """4xx never produces a DecodeError — terminal raises StatusError first."""
    client = _client_with_payload(b'{"id": 1, "name": "x"}', status=HTTPStatus.NOT_FOUND)
    request = client.build_request("GET", "https://example.test/u")
    with pytest.raises(NotFoundError):
        await client.send_with_response(request, response_model=_User)


async def test_send_with_response_runs_middleware_chain() -> None:
    """User middleware mutates the request; mutation is visible on the wire."""
    recorded: list[httpx2.Request] = []

    async def stamp(request: httpx2.Request) -> httpx2.Request:
        request.headers["x-test"] = "ok"
        return request

    def handler(request: httpx2.Request) -> httpx2.Response:
        recorded.append(request)
        return httpx2.Response(
            HTTPStatus.OK,
            content=b'{"id": 1, "name": "z"}',
            headers={"content-type": "application/json"},
            request=request,
        )

    transport = httpx2.MockTransport(handler)
    client = AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=transport),
        middleware=[async_before_request(stamp)],
    )
    request = client.build_request("GET", "https://example.test/u")
    response, _ = await client.send_with_response(request, response_model=_User)
    assert recorded[0].headers.get("x-test") == "ok"
    assert response.request.headers.get("x-test") == "ok"
```

- [ ] **Step 2: Run the new test file; confirm every test fails with `AttributeError`**

Run: `just test tests/test_client_send_with_response.py -v`
Expected: every test errors with `AttributeError: 'AsyncClient' object has no attribute 'send_with_response'`. This proves the tests are wired correctly and the method genuinely does not exist yet.

- [ ] **Step 3: Commit the red-phase tests**

```bash
git add tests/test_client_send_with_response.py
git commit -m "$(cat <<'EOF'
test(async): red-phase tests for AsyncClient.send_with_response

Tests cover: returns (response, decoded); preserves response headers;
preserves response.request.url; decode failure raises DecodeError with
the right original; malformed JSON raises DecodeError; DecodeError is
caught by ClientError; 4xx raises StatusError (not DecodeError); user
middleware mutation is observable on the wire and on response.request.

All tests currently fail with AttributeError — implementation lands next.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Implement `AsyncClient.send_with_response`

**Files:**
- Modify: `src/httpware/client.py` (insert after current line 160; before `def build_request` at line 162)

- [ ] **Step 1: Add `send_with_response` to `AsyncClient`**

In `src/httpware/client.py`, locate the end of `AsyncClient.send` (the last line of its body is line 160: `raise DecodeError(response=response, model=response_model, original=exc) from exc`). Insert the new method immediately after, before `def build_request` at line 162. The exact insertion: between line 160 and the blank line preceding `def build_request`.

Code to insert (preserve the 4-space indentation; this is a class method):

```python

    async def send_with_response(
        self,
        request: httpx2.Request,
        *,
        response_model: type[T],
    ) -> tuple[httpx2.Response, T]:
        """Send `request` through the middleware chain; return (response, decoded).

        Use this when you need response metadata (headers, status, request URL)
        AND a typed body — most commonly for Link-header pagination. For the
        body-only case, prefer ``send(request, response_model=...)``.

        Not for streaming responses — decodes ``response.content``, which
        requires the body to be fully read. Use ``stream()`` for streaming.
        """
        response = await self._dispatch(request)
        try:
            decoded = self._decoder.decode(response.content, response_model)
        except Exception as exc:
            raise DecodeError(response=response, model=response_model, original=exc) from exc
        return response, decoded
```

(`T` and `DecodeError` are already in scope — `T = typing.TypeVar("T")` on line 24, `from httpware.errors import DecodeError, TransportError` on line 19.)

- [ ] **Step 2: Run the async test file; confirm every test passes**

Run: `just test tests/test_client_send_with_response.py -v`
Expected: all 8 tests pass. If any fail, do not adjust the test — fix the implementation.

- [ ] **Step 3: Lint the touched file**

Run: `just lint`
Expected: pass. `eof-fixer`, `ruff format`, `ruff check`, and `ty check` should all succeed. If `ty` complains about the return-type annotation, double-check that `T` is the module-level `TypeVar` and not shadowed.

- [ ] **Step 4: Commit the async implementation**

```bash
git add src/httpware/client.py
git commit -m "$(cat <<'EOF'
feat(async): add AsyncClient.send_with_response

Returns (response, decoded) atomically — routes the decode through the
configured ResponseDecoder so decoder failures surface as DecodeError,
identical to send(request, response_model=...). Use case: callers who
need response headers (Link, X-Total-Count, ...) alongside a typed
body, most commonly Link-header pagination.

Spec: planning/specs/2026-06-08-send-with-response-design.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Sync tests — write the red-phase tests for `Client.send_with_response`

**Files:**
- Create: `tests/test_client_send_with_response_sync.py`

- [ ] **Step 1: Create `tests/test_client_send_with_response_sync.py` with the failing tests**

Write the full file (structurally identical to the async file but using `Client` / `httpx2.Client` / sync middleware helpers):

```python
"""Tests for Client.send_with_response — atomic (response, decoded) pair (sync)."""

from http import HTTPStatus

import httpx2
import pydantic
import pytest

from httpware import Client, ClientError, DecodeError, NotFoundError
from httpware.middleware import before_request


class _User(pydantic.BaseModel):
    id: int
    name: str


def _client_with_payload(
    payload: bytes,
    *,
    status: int = HTTPStatus.OK,
    headers: dict[str, str] | None = None,
    record: list[httpx2.Request] | None = None,
) -> Client:
    response_headers = {"content-type": "application/json"}
    if headers is not None:
        response_headers.update(headers)

    def handler(request: httpx2.Request) -> httpx2.Response:
        if record is not None:
            record.append(request)
        return httpx2.Response(status, content=payload, headers=response_headers, request=request)

    transport = httpx2.MockTransport(handler)
    return Client(httpx2_client=httpx2.Client(transport=transport))


def test_send_with_response_returns_response_and_decoded() -> None:
    client = _client_with_payload(b'{"id": 1, "name": "ada"}')
    request = client.build_request("GET", "https://example.test/u")
    response, user = client.send_with_response(request, response_model=_User)
    assert isinstance(response, httpx2.Response)
    assert isinstance(user, _User)
    assert user == _User(id=1, name="ada")
    assert response.content == b'{"id": 1, "name": "ada"}'


def test_send_with_response_preserves_response_headers() -> None:
    """Pagination callers read Link / X-Total-Count off the returned response."""
    client = _client_with_payload(
        b'{"id": 1, "name": "p"}',
        headers={"link": '<https://example.test/u?page=2>; rel="next"', "x-total-count": "100"},
    )
    request = client.build_request("GET", "https://example.test/u?page=1")
    response, _ = client.send_with_response(request, response_model=_User)
    assert response.headers.get("link") == '<https://example.test/u?page=2>; rel="next"'
    assert response.headers.get("x-total-count") == "100"


def test_send_with_response_response_request_url_populated() -> None:
    """Pagination loops do str(response.request.url) to compute the next page."""
    client = _client_with_payload(b'{"id": 1, "name": "p"}')
    request = client.build_request("GET", "https://example.test/u?page=1")
    response, _ = client.send_with_response(request, response_model=_User)
    assert str(response.request.url) == "https://example.test/u?page=1"


def test_send_with_response_decode_failure_raises_decode_error() -> None:
    client = _client_with_payload(b"null")
    request = client.build_request("GET", "https://example.test/u")
    with pytest.raises(DecodeError) as exc_info:
        client.send_with_response(request, response_model=_User)
    exc = exc_info.value
    assert exc.response.status_code == HTTPStatus.OK
    assert exc.model is _User
    assert isinstance(exc.original, pydantic.ValidationError)
    assert exc.__cause__ is exc.original


def test_send_with_response_malformed_json_raises_decode_error() -> None:
    client = _client_with_payload(b"{not json")
    request = client.build_request("GET", "https://example.test/u")
    with pytest.raises(DecodeError):
        client.send_with_response(request, response_model=_User)


def test_send_with_response_decode_error_caught_by_client_error() -> None:
    """The user-facing promise: `except ClientError` catches decode failures."""
    client = _client_with_payload(b"null")
    request = client.build_request("GET", "https://example.test/u")
    with pytest.raises(ClientError) as exc_info:
        client.send_with_response(request, response_model=_User)
    assert isinstance(exc_info.value, DecodeError)


def test_send_with_response_status_error_raised_before_decoder_runs() -> None:
    """4xx never produces a DecodeError — terminal raises StatusError first."""
    client = _client_with_payload(b'{"id": 1, "name": "x"}', status=HTTPStatus.NOT_FOUND)
    request = client.build_request("GET", "https://example.test/u")
    with pytest.raises(NotFoundError):
        client.send_with_response(request, response_model=_User)


def test_send_with_response_runs_middleware_chain() -> None:
    """User middleware mutates the request; mutation is visible on the wire."""
    recorded: list[httpx2.Request] = []

    def stamp(request: httpx2.Request) -> httpx2.Request:
        request.headers["x-test"] = "ok"
        return request

    def handler(request: httpx2.Request) -> httpx2.Response:
        recorded.append(request)
        return httpx2.Response(
            HTTPStatus.OK,
            content=b'{"id": 1, "name": "z"}',
            headers={"content-type": "application/json"},
            request=request,
        )

    transport = httpx2.MockTransport(handler)
    client = Client(
        httpx2_client=httpx2.Client(transport=transport),
        middleware=[before_request(stamp)],
    )
    request = client.build_request("GET", "https://example.test/u")
    response, _ = client.send_with_response(request, response_model=_User)
    assert recorded[0].headers.get("x-test") == "ok"
    assert response.request.headers.get("x-test") == "ok"
```

- [ ] **Step 2: Run the new sync test file; confirm every test fails with `AttributeError`**

Run: `just test tests/test_client_send_with_response_sync.py -v`
Expected: every test errors with `AttributeError: 'Client' object has no attribute 'send_with_response'`.

- [ ] **Step 3: Commit the red-phase sync tests**

```bash
git add tests/test_client_send_with_response_sync.py
git commit -m "$(cat <<'EOF'
test(sync): red-phase tests for Client.send_with_response

Sync siblings of the async test file: same eight cases, using
Client / httpx2.Client / before_request. All currently fail with
AttributeError; implementation lands next.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Implement `Client.send_with_response`

**Files:**
- Modify: `src/httpware/client.py` (insert after current line 880; before `def build_request` at line 882)

- [ ] **Step 1: Add `send_with_response` to `Client`**

In `src/httpware/client.py`, locate the end of `Client.send` (the last line of its body is the `raise DecodeError(...) from exc` line — line 880 in the pre-Task-2 file, or line 180 after the async insertion, depending on how you're counting; locate by the `def build_request(self, method: str, ...)` immediately below it on the **sync** class). Insert the new method immediately after `Client.send` and before `def build_request`.

Code to insert (4-space indent, sync — no `async`/`await`):

```python

    def send_with_response(
        self,
        request: httpx2.Request,
        *,
        response_model: type[T],
    ) -> tuple[httpx2.Response, T]:
        """Send `request` through the middleware chain; return (response, decoded).

        Use this when you need response metadata (headers, status, request URL)
        AND a typed body — most commonly for Link-header pagination. For the
        body-only case, prefer ``send(request, response_model=...)``.

        Not for streaming responses — decodes ``response.content``, which
        requires the body to be fully read. Use ``stream()`` for streaming.
        """
        response = self._dispatch(request)
        try:
            decoded = self._decoder.decode(response.content, response_model)
        except Exception as exc:
            raise DecodeError(response=response, model=response_model, original=exc) from exc
        return response, decoded
```

The docstring is intentionally identical to the async sibling — same contract, same caveat. (`T` and `DecodeError` are in scope at module level, same as for `AsyncClient`.)

- [ ] **Step 2: Run the sync test file; confirm every test passes**

Run: `just test tests/test_client_send_with_response_sync.py -v`
Expected: all 8 tests pass.

- [ ] **Step 3: Run the full test suite to catch regressions**

Run: `just test`
Expected: full suite passes with no failures or new warnings. Existing tests should not have moved.

- [ ] **Step 4: Lint**

Run: `just lint`
Expected: pass.

- [ ] **Step 5: Commit the sync implementation**

```bash
git add src/httpware/client.py
git commit -m "$(cat <<'EOF'
feat(sync): add Client.send_with_response

Sync sibling of AsyncClient.send_with_response. Same shape: returns
(response, decoded) atomically and routes the decode through the
configured ResponseDecoder. Identical docstring; sync dispatch path.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Docs update — `docs/index.md` + `planning/engineering.md`

**Files:**
- Modify: `docs/index.md` — insert a `### Response metadata + typed body` subsection between line 82 (end of the `response_model=` example) and line 84 (`### Streaming responses`)
- Modify: `planning/engineering.md` — update Seam B contract on line 42 to name `send_with_response` alongside `send`

- [ ] **Step 1: Add the docs subsection to `docs/index.md`**

In `docs/index.md`, locate the blank line between line 82 (`        user = await client.get("/users/1", response_model=User)`) and line 84 (`### Streaming responses`). Insert the following subsection in that gap (preserve blank lines top and bottom so the surrounding sections render cleanly):

```markdown

### Response metadata + typed body

When you need both the raw `httpx2.Response` (for headers, status, or the
request URL) **and** a typed body, use `send_with_response`. It returns
both atomically and routes the decode through the configured
`ResponseDecoder`, so decoder failures surface as `DecodeError` — caught
by `except httpware.ClientError` like every other failure mode.

Canonical use case: RFC 5988 Link-header pagination.

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
            url = next_link(response.headers.get("link"))   # caller's parser
            params = None                                    # next link carries query
```

For the body-only case, prefer `client.get(..., response_model=...)`.
`send_with_response` is not for streaming responses — use `stream()`.
```

(Note: the inner code fence here is shown for clarity; in the actual `docs/index.md` it lives inside a single outer mkdocs fence. Use the same indentation/fence style as the existing examples in the file.)

- [ ] **Step 2: Build the docs locally; confirm rendering**

Run: `uv run mkdocs build --strict 2>&1 | tail -20`
Expected: build succeeds with no warnings (the `--strict` flag promotes warnings to errors). If a warning appears about a broken anchor or mis-nested heading, fix it.

- [ ] **Step 3: Update `planning/engineering.md` Seam B contract**

Open `planning/engineering.md` and locate line 42 (the `**Contract:**` line in `### Seam B`). The current text reads:

> Any exception raised by `decode` is wrapped by `Client.send` / `AsyncClient.send` into `httpware.DecodeError` ...

Replace that phrase with:

> Any exception raised by `decode` is wrapped by the call sites in `client.py` — `Client.send` / `AsyncClient.send` (when `response_model=` is set) and `Client.send_with_response` / `AsyncClient.send_with_response` — into `httpware.DecodeError` ...

Use the Edit tool with `old_string` = the exact existing phrase (including surrounding context to make it unique) and `new_string` = the replacement.

- [ ] **Step 4: Run the full suite + lint one more time**

Run: `just test && just lint`
Expected: both pass.

- [ ] **Step 5: Commit the docs update**

```bash
git add docs/index.md planning/engineering.md
git commit -m "$(cat <<'EOF'
docs: document send_with_response in index + Seam B contract

docs/index.md: new "Response metadata + typed body" subsection with a
Link-header pagination example; points body-only callers back at
client.get(..., response_model=).

planning/engineering.md: Seam B contract now names send_with_response
alongside send as the two call sites that wrap decoder exceptions.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Final verification + release prep memory note

**Files:**
- No code changes; verification only.
- After release tag, update `~/.claude/projects/-Users-kevinsmith-src-pypi-httpware/memory/MEMORY.md` with a `release_0_8_2_shipped.md` entry (post-merge follow-up, not part of this branch's commits).

- [ ] **Step 1: Run the full test suite with coverage**

Run: `just test-branch`
Expected: all tests pass; branch coverage does not regress on `src/httpware/client.py` (the new method is fully covered by the new tests). If branch coverage drops, the most likely cause is a missing branch test for the decode-error path — re-verify Task 1 / Task 3 `decode_failure` tests actually fire the `except Exception` line.

- [ ] **Step 2: Confirm the public API surface is unchanged**

Run: `just test tests/test_public_api.py -v`
Expected: pass. The expected symbol set should match — we deliberately did not add anything at module scope.

- [ ] **Step 3: Confirm the optional-extras isolation test still passes**

Run: `just test tests/test_optional_extras_isolation.py tests/test_optional_extras_pydantic_missing.py -v`
Expected: pass. The new method does not import pydantic at module top level (only uses it via the already-existing `self._decoder`).

- [ ] **Step 4: Inspect the diff one last time before opening the PR**

Run: `git log --oneline main..HEAD && git diff --stat main..HEAD`
Expected: 5 commits (red async, green async, red sync, green sync, docs). `--stat` should show changes to exactly:
- `src/httpware/client.py` (+~30 LOC)
- `tests/test_client_send_with_response.py` (new, ~130 LOC)
- `tests/test_client_send_with_response_sync.py` (new, ~130 LOC)
- `docs/index.md` (+~25 LOC)
- `planning/engineering.md` (small edit)

No other files. If anything else shows up, stop and investigate.

- [ ] **Step 5: Open the PR**

Use `gh pr create` per the project's existing convention. Title: `feat: add send_with_response method for atomic (response, decoded) pair`. Body should reference the spec and explain the use case (Link-header pagination) briefly. Defer release tagging until the PR merges; tag `0.8.2` at the merge commit per `MEMORY.md` → `release_0_8_1_shipped` precedent.

---

## Self-review notes

**Spec coverage check:**
- Purpose: `send_with_response` returning `tuple[Response, T]` — Task 2 (async impl) + Task 4 (sync impl). ✓
- Architecture / seam (try-around-decode, `_dispatch` outside): Task 2 step 1 code, Task 4 step 1 code. ✓
- Signature (keyword-only `response_model`, no overload): explicitly shown in Task 2/4 step 1. ✓
- Error contract (`DecodeError` reuse, `_dispatch` errors propagate, `except ClientError` catches): Tasks 1/3 cover decode failure, status error, `ClientError` catches. ✓
- Non-goals (no per-verb siblings, no streaming, no `response_model=None`, no `request_with_response`, no new exception class): no task touches these — non-goals are honored by omission. Plan does not introduce any of them. ✓
- Tests table from spec (success, decode failure, status failure, middleware runs, `response.request` populated): Task 1 step 1 + Task 3 step 1 cover all five, plus headers preservation (a near-corollary worth its own test). ✓
- Docs (`docs/index.md` one paragraph, no recipes, no autodoc): Task 5 step 1. ✓
- Release `0.8.2`: Task 6 step 5 defers tagging to post-merge per project precedent. ✓

**Type consistency:** `send_with_response`, `response_model`, `DecodeError(response=, model=, original=)`, `_dispatch`, `_decoder.decode(response.content, response_model)`, `tuple[httpx2.Response, T]` — used identically across Tasks 1–4 and the spec. ✓

**Placeholder scan:** no TBD/TODO. Every step has either concrete code or an exact command with expected output.

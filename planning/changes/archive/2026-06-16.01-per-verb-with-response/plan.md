---
status: shipped
date: 2026-06-16
slug: per-verb-with-response
spec: per-verb-with-response
pr: 68
---

# per-verb-with-response — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps
> use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `get_with_response` … `request_with_response` (6 verbs) to both
`AsyncClient` and `Client`, each returning `(httpx2.Response, T)` with a
required `response_model`.

**Architecture:** Extract the request-building logic from `_request_with_body`
into a shared `_prepare_request`, add a parallel `_request_with_body_with_response`
helper that delegates to `send_with_response`, and add six one-line-delegation
verb methods per client. No overloads (one call shape). Sync mirrors async.

**Tech Stack:** Python 3.11+, `httpx2`, `pytest` (asyncio auto mode), `pydantic`
(test models), `httpx2.MockTransport` for injection.

**Spec:** [`design.md`](./design.md)

**Branch:** `feat/per-verb-with-response`

**Commit strategy:** Per-task commits.

---

### Task 1: Extract `_prepare_request` (behavior-preserving refactor)

Split request-building out of `_request_with_body` on both clients so the plain
and with-response paths can share it. No behavior change — the existing
plain-verb suite is the safety net.

**Files:**
- Modify: `src/httpware/client.py` (`AsyncClient._request_with_body` ~231-269;
  `Client._request_with_body` ~1006-1044)

- [ ] **Step 1: Add `AsyncClient._prepare_request`**

  Insert this method just above `AsyncClient._request_with_body` (after
  `build_request`, ~line 230):

  ```python
  def _prepare_request(  # noqa: PLR0913, C901 — mirrors httpx2 per-method signatures; kwargs-forwarding complexity is structural
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
  ) -> httpx2.Request:
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
      request = self._httpx2_client.build_request(method, url, **kwargs)
      if _is_streaming_body_async(content) or _is_streaming_body_async(data) or _is_streaming_body_async(files):
          request.extensions[STREAMING_BODY_MARKER] = True
      return request
  ```

- [ ] **Step 2: Rewire `AsyncClient._request_with_body` to use it**

  Replace the body of `_request_with_body` (the kwargs-assembly + marker +
  `send` block) with delegation. Drop `C901` from its `# noqa` — the branching
  now lives in `_prepare_request`, so only `PLR0913` (param count) remains:

  ```python
  async def _request_with_body(  # noqa: PLR0913 — mirrors httpx2 per-method signatures
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
      response_model: type[T] | None = None,
  ) -> httpx2.Response | T:
      request = self._prepare_request(
          method, url, params=params, headers=headers, cookies=cookies,
          timeout=timeout, extensions=extensions, json=json, content=content,
          data=data, files=files,
      )
      return await self.send(request, response_model=response_model)
  ```

- [ ] **Step 3: Mirror both edits on `Client`**

  Add `Client._prepare_request` (identical, but the streaming check uses
  `_is_streaming_body_sync` instead of `_is_streaming_body_async`) and rewire
  `Client._request_with_body` to delegate (calling the synchronous `self.send`,
  no `await`).

- [ ] **Step 4: Run the full suite — refactor must be invisible**

  Run: `just test`
  Expected: PASS, same count as before this task (the plain verbs exercise the
  moved code).

- [ ] **Step 5: Lint**

  Run: `just lint`
  Expected: clean. (If ruff flags an unused `C901`, the rewrite already dropped
  it.)

- [ ] **Step 6: Commit**

  ```bash
  git add src/httpware/client.py
  git commit -m "refactor(client): extract _prepare_request from _request_with_body

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 2: Async `*_with_response` siblings

Add the with-response helper and the six async verb methods, test-first.

**Files:**
- Modify: `src/httpware/client.py` (`AsyncClient`)
- Test: `tests/test_client_per_verb_with_response.py` (create)

- [ ] **Step 1: Write the failing tests**

  Create `tests/test_client_per_verb_with_response.py`:

  ```python
  """Per-verb *_with_response siblings on AsyncClient — (response, decoded) pairs."""

  from http import HTTPStatus

  import httpx2
  import pydantic
  import pytest

  from httpware import AsyncClient, DecodeError, MissingDecoderError


  class _User(pydantic.BaseModel):
      id: int
      name: str


  def _echo_client(
      payload: bytes = b'{"id": 1, "name": "ada"}',
      *,
      headers: dict[str, str] | None = None,
  ) -> tuple[AsyncClient, list[httpx2.Request]]:
      recorded: list[httpx2.Request] = []
      response_headers = {"content-type": "application/json"}
      if headers is not None:
          response_headers.update(headers)

      def handler(request: httpx2.Request) -> httpx2.Response:
          recorded.append(request)
          return httpx2.Response(HTTPStatus.OK, content=payload, headers=response_headers, request=request)

      client = AsyncClient(httpx2_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)))
      return client, recorded


  @pytest.mark.parametrize(
      ("verb", "expected_method"),
      [("get", "GET"), ("post", "POST"), ("put", "PUT"), ("patch", "PATCH"), ("delete", "DELETE")],
  )
  async def test_verb_with_response_returns_pair_and_sends_right_method(verb: str, expected_method: str) -> None:
      client, recorded = _echo_client()
      method = getattr(client, f"{verb}_with_response")
      response, user = await method("https://example.test/u", response_model=_User)
      assert isinstance(response, httpx2.Response)
      assert user == _User(id=1, name="ada")
      assert recorded[0].method == expected_method


  async def test_request_with_response_returns_pair() -> None:
      client, recorded = _echo_client()
      response, user = await client.request_with_response("GET", "https://example.test/u", response_model=_User)
      assert isinstance(response, httpx2.Response)
      assert user == _User(id=1, name="ada")
      assert recorded[0].method == "GET"


  async def test_get_with_response_preserves_headers() -> None:
      client, _ = _echo_client(headers={"link": '<https://example.test/u?page=2>; rel="next"'})
      response, _user = await client.get_with_response("https://example.test/u", response_model=_User)
      assert response.headers.get("link") == '<https://example.test/u?page=2>; rel="next"'


  async def test_post_with_response_forwards_json_body() -> None:
      client, recorded = _echo_client()
      await client.post_with_response("https://example.test/u", json={"name": "ada"}, response_model=_User)
      assert recorded[0].content == b'{"name": "ada"}'


  async def test_with_response_decode_failure_raises_decode_error() -> None:
      client, _ = _echo_client(payload=b"null")
      with pytest.raises(DecodeError) as exc_info:
          await client.get_with_response("https://example.test/u", response_model=_User)
      assert exc_info.value.model is _User


  async def test_with_response_missing_decoder_before_http_call() -> None:
      def handler(_: httpx2.Request) -> httpx2.Response:  # pragma: no cover
          pytest.fail("transport should not be invoked when MissingDecoderError fires")

      client = AsyncClient(httpx2_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)), decoders=[])

      class _Foo:
          pass

      with pytest.raises(MissingDecoderError):
          await client.get_with_response("https://example.test/x", response_model=_Foo)
  ```

- [ ] **Step 2: Run the tests to verify they fail**

  Run: `just test tests/test_client_per_verb_with_response.py`
  Expected: FAIL — `AttributeError: 'AsyncClient' object has no attribute 'get_with_response'`.

- [ ] **Step 3: Add `AsyncClient._request_with_body_with_response`**

  Insert directly after `AsyncClient._request_with_body`:

  ```python
  async def _request_with_body_with_response(  # noqa: PLR0913 — mirrors httpx2 per-method signatures
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
      response_model: type[T],
  ) -> tuple[httpx2.Response, T]:
      request = self._prepare_request(
          method, url, params=params, headers=headers, cookies=cookies,
          timeout=timeout, extensions=extensions, json=json, content=content,
          data=data, files=files,
      )
      return await self.send_with_response(request, response_model=response_model)
  ```

- [ ] **Step 4: Add `get_with_response` (no body kwargs)**

  Insert after the plain `get` implementation:

  ```python
  async def get_with_response(
      self,
      url: str,
      *,
      params: typing.Any | None = None,
      headers: typing.Any | None = None,
      cookies: typing.Any | None = None,
      timeout: typing.Any = httpx2.USE_CLIENT_DEFAULT,
      extensions: typing.Any | None = None,
      response_model: type[T],
  ) -> tuple[httpx2.Response, T]:
      """Send a GET request; return (response, decoded body)."""
      return await self._request_with_body_with_response(
          "GET", url, params=params, headers=headers, cookies=cookies,
          timeout=timeout, extensions=extensions, response_model=response_model,
      )
  ```

- [ ] **Step 5: Add `post_with_response` (full body kwargs)**

  Insert after the plain `post` implementation:

  ```python
  async def post_with_response(  # noqa: PLR0913 — mirrors httpx2 per-method signatures
      self,
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
      response_model: type[T],
  ) -> tuple[httpx2.Response, T]:
      """Send a POST request; return (response, decoded body)."""
      return await self._request_with_body_with_response(
          "POST", url, params=params, headers=headers, cookies=cookies,
          timeout=timeout, extensions=extensions, json=json, content=content,
          data=data, files=files, response_model=response_model,
      )
  ```

- [ ] **Step 6: Add `put_with_response`, `patch_with_response`, `delete_with_response`**

  Each is a copy of `post_with_response` (Step 5) — identical signature and body
  — changing only the method name and the verb string passed to the helper:
  `put_with_response` → `"PUT"`, `patch_with_response` → `"PATCH"`,
  `delete_with_response` → `"DELETE"`. Place each after its plain-verb sibling.
  Update each docstring to name the verb.

- [ ] **Step 7: Add `request_with_response` (leading `method` arg)**

  Insert after the plain `request` implementation:

  ```python
  async def request_with_response(  # noqa: PLR0913 — mirrors httpx2 per-method signatures
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
      response_model: type[T],
  ) -> tuple[httpx2.Response, T]:
      """Send a request with an explicit method; return (response, decoded body)."""
      return await self._request_with_body_with_response(
          method, url, params=params, headers=headers, cookies=cookies,
          timeout=timeout, extensions=extensions, json=json, content=content,
          data=data, files=files, response_model=response_model,
      )
  ```

- [ ] **Step 8: Run the tests to verify they pass**

  Run: `just test tests/test_client_per_verb_with_response.py`
  Expected: PASS (all parametrized verbs + request + headers + body + DecodeError
  + MissingDecoderError).

- [ ] **Step 9: Commit**

  ```bash
  git add src/httpware/client.py tests/test_client_per_verb_with_response.py
  git commit -m "feat(client): add async per-verb *_with_response siblings

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 3: Sync `*_with_response` siblings

Mirror Task 2 on `Client`.

**Files:**
- Modify: `src/httpware/client.py` (`Client`)
- Test: `tests/test_client_per_verb_with_response_sync.py` (create)

- [ ] **Step 1: Write the failing tests**

  Create `tests/test_client_per_verb_with_response_sync.py` as a sync copy of the
  Task 2 test file: import `Client` (not `AsyncClient`), build with
  `Client(httpx2_client=httpx2.Client(transport=httpx2.MockTransport(handler)))`,
  drop every `async`/`await`, and call the sync methods. Keep the same test
  names, the `_User` model, the `(verb, expected_method)` parametrization, the
  header/body/DecodeError/MissingDecoderError cases.

- [ ] **Step 2: Run the tests to verify they fail**

  Run: `just test tests/test_client_per_verb_with_response_sync.py`
  Expected: FAIL — `Client` has no `get_with_response`.

- [ ] **Step 3: Add `Client._request_with_body_with_response` + the six siblings**

  Mirror Task 2 Steps 3-7 on `Client`: same signatures, no `async`/`await`, each
  delegating to the synchronous `self.send_with_response`. Place each verb sibling
  after its plain-verb counterpart in `Client`.

- [ ] **Step 4: Run the tests to verify they pass**

  Run: `just test tests/test_client_per_verb_with_response_sync.py`
  Expected: PASS.

- [ ] **Step 5: Full suite + lint**

  Run: `just test && just lint`
  Expected: all green, lint clean.

- [ ] **Step 6: Commit**

  ```bash
  git add src/httpware/client.py tests/test_client_per_verb_with_response_sync.py
  git commit -m "feat(client): add sync per-verb *_with_response siblings

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 4: Typed-return check + docs

Confirm the declared return types via `ty`, and document the new surface.

**Files:**
- Test: `tests/test_client_typing.py` (modify)
- Modify: `docs/recipes/link-header-pagination.md`, `architecture/client.md`

- [ ] **Step 1: Add a typed-usage assertion**

  Append to `tests/test_client_typing.py` (match the file's existing
  `typing.assert_type` / reveal-type style — open it first to mirror the pattern):

  ```python
  async def test_get_with_response_return_type(async_client: AsyncClient) -> None:
      response, user = await async_client.get_with_response("https://e.test/u", response_model=_User)
      typing.assert_type(response, httpx2.Response)
      typing.assert_type(user, _User)
  ```

  Use whatever fixture/model names that file already defines; if it has no
  fixture, build a client inline as in Task 2. The point is that `ty check`
  validates the `tuple[Response, T]` destructuring.

- [ ] **Step 2: Run ty over the typing test**

  Run: `uv run ty check`
  Expected: clean (no `assert_type` mismatch).

- [ ] **Step 3: Update the pagination recipe**

  In `docs/recipes/link-header-pagination.md`, add a short note that
  `get_with_response("/path", response_model=...)` collapses the
  `build_request` + `send_with_response` two-step into one call, with a
  one-line before/after. Keep the existing `send_with_response` example (still
  valid for pre-built requests).

- [ ] **Step 4: Note the siblings in architecture/client.md**

  Add one sentence to `architecture/client.md` where `send_with_response` is
  described: the per-verb `*_with_response` siblings (get/post/put/patch/delete/
  request) are the one-call ergonomic form, `response_model` required, returning
  `(Response, T)`; no `head`/`options` variant.

- [ ] **Step 5: Verify docs build**

  Run: `uvx --with-requirements docs/requirements.txt mkdocs build --strict`
  Expected: clean; then `rm -rf site`.

- [ ] **Step 6: Commit**

  ```bash
  git add tests/test_client_typing.py docs/recipes/link-header-pagination.md architecture/client.md
  git commit -m "docs(client): document per-verb *_with_response siblings

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 5: Version bump, release notes, close deferred item

Cut 0.12.0 and retire the deferred entry this change closes.

**Files:**
- Create: `planning/releases/0.12.0.md`
- Modify: `planning/deferred.md`
- (`pyproject.toml` is NOT touched — version is tag-driven; see Step 1.)

- [ ] **Step 1: Version is tag-driven — do NOT edit `pyproject.toml`**

  Releases are tag-driven: `publish.yml` runs `uv version $GITHUB_REF_NAME`
  from the `v0.12.0` git tag at publish time, and the static `version` field in
  `pyproject.toml` is deliberately kept at the placeholder `"0"` (the 0.11.0
  release commit `c27c163` reset it for exactly this reason). Leave the field at
  `"0"`. The version bump happens via the tag, not this file.

- [ ] **Step 2: Write the release notes**

  Create `planning/releases/0.12.0.md` modeled on `planning/releases/0.11.0.md`:
  minor, additive-only; new methods `get_with_response`, `post_with_response`,
  `put_with_response`, `patch_with_response`, `delete_with_response`,
  `request_with_response` on both `AsyncClient` and `Client`; each requires
  `response_model` and returns `(httpx2.Response, T)`; no `head`/`options`
  variant; no breaking changes.

- [ ] **Step 3: Remove the closed deferred item**

  In `planning/deferred.md`, delete the **"Per-verb-with-response siblings"**
  bullet under "Client API surface" (it is now shipped).

- [ ] **Step 4: Full suite + lint one more time**

  Run: `just test && just lint`
  Expected: all green, clean.

- [ ] **Step 5: Commit**

  ```bash
  git add pyproject.toml planning/releases/0.12.0.md planning/deferred.md
  git commit -m "chore(release): 0.12.0 — per-verb *_with_response siblings

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

## Ship bookkeeping (after merge)

Not a task — done when the PR merges, per the planning convention: set this
bundle's `design.md` + `plan.md` frontmatter to `status: shipped` with the PR
number, move `changes/active/2026-06-16.01-per-verb-with-response/` to
`changes/archive/`, and flip its Index line from Active to Archived.

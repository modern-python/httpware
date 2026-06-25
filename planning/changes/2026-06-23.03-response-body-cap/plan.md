# response-body-cap — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps
> use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace error-only `max_error_body_bytes` with a status-agnostic,
decoded-byte `max_response_body_bytes` cap enforced by a shared streaming
capped-accumulator on both the terminal and `stream()`'s error pre-read.

**Spec:** [`design.md`](./design.md)

**Branch:** `feat/response-body-cap`

**Commit strategy:** Per-task commits. TDD: each behavioral task writes the
failing test first, then the implementation.

---

### Task 1: `ResponseTooLargeError` gains `reason`

**Files:**
- Modify: `src/httpware/errors.py`
- Modify: `tests/test_errors.py` (or the suite that covers `ResponseTooLargeError`)

Make the error status-agnostic-aware with an explicit trip-mode discriminator.
No client wiring yet.

- [ ] **Step 1: Write failing tests**

  Assert `ResponseTooLargeError(status_code=200, limit=10, content_length=None,
  reason="streamed")` constructs, exposes all four fields, and round-trips through
  `pickle` (exercises `__reduce__`). Add a `reason="declared"` case. Assert the
  message text differs sensibly per `reason`. Run: `just test tests/test_errors.py`
  — red.

- [ ] **Step 2: Add the field**

  Add `reason: typing.Literal["declared", "streamed"]` to the class body and
  `__init__` (keyword-only), thread it into the message and `__reduce__` /
  `_reconstruct_response_too_large`. Keep it a non-status `ClientError`. Run:
  `just test tests/test_errors.py` — green.

- [ ] **Step 3: Commit**

  ```bash
  git add src/httpware/errors.py tests/test_errors.py
  git commit -m "feat: add reason discriminator to ResponseTooLargeError

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 2: Pure `_accumulate_capped` core + Hypothesis property test

**Files:**
- Modify: `src/httpware/client.py`
- Create: `tests/test_capped_read_props.py`

The one subtle invariant — chunk-boundary independence — isolated behind a pure
function before any I/O wiring.

- [ ] **Step 1: Write the property test (red)**

  In `tests/test_capped_read_props.py`, use Hypothesis to draw a body (`bytes`)
  and a partition into chunks, plus a `cap >= 1`. Assert: `_accumulate_capped`
  returns `body` byte-for-byte when `len(body) <= cap`, and raises `_CapExceeded`
  when `len(body) > cap` — independent of how the body is split. Annotate test
  args. Run: `just test tests/test_capped_read_props.py` — red (symbols absent).

- [ ] **Step 2: Implement the core**

  Add module-level `class _CapExceeded(Exception)` (carries `read: int`) and
  `def _accumulate_capped(chunks: Iterable[bytes], cap: int) -> bytes` using a
  `bytearray` grown in place, raising `_CapExceeded(read=len(buf))` the moment
  `len(buf) > cap`. Run: `just test tests/test_capped_read_props.py` — green.

- [ ] **Step 3: Commit**

  ```bash
  git add src/httpware/client.py tests/test_capped_read_props.py
  git commit -m "feat: add pure _accumulate_capped core with property test

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 3: `_read_capped` sync/async wrappers + `_safe_extensions`

**Files:**
- Modify: `src/httpware/client.py`
- Modify: `tests/test_client.py` (or a focused `tests/test_capped_read.py`)

Wrap the core with the `Content-Length` early reject and the `Response` rebuild.
Helpers take a `Response`, not a client; they never close the stream.

- [ ] **Step 1: Write failing unit tests**

  Build streaming responses via `MockTransport` + `httpx2.{Async,}Client` and call
  `_read_capped` / `_read_capped_async` directly (or through a thin harness):
  within-cap returns a buffered `Response` with byte-identical `.content`;
  declared `Content-Length > cap` raises `reason="declared"` having read zero;
  chunked over-cap raises `reason="streamed"`; gzip bomb (133 → 100 K) raises
  `reason="streamed"`; rebuilt `Response.extensions` has no `network_stream` but
  keeps `http_version`. Run — red.

- [ ] **Step 2: Implement**

  Add `_safe_extensions(ext)` (copy, preserve `http_version`/`reason_phrase`, drop
  `network_stream`), then `_read_capped` (sync, `iter_bytes`) and
  `_read_capped_async` (async, `aiter_bytes`). Each: parse `Content-Length` via
  `_parse_content_length`, early-reject → `ResponseTooLargeError(reason="declared")`;
  feed the byte iterator to `_accumulate_capped`, `except _CapExceeded` →
  `ResponseTooLargeError(reason="streamed")`; else rebuild
  `httpx2.Response(status_code=…, headers=…, content=…, request=…,
  extensions=_safe_extensions(…), history=…)`. Run — green.

- [ ] **Step 3: Commit**

  ```bash
  git add src/httpware/client.py tests/
  git commit -m "feat: add shared _read_capped streaming accumulator

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 4: Rename param, validate, branch the terminal (both clients)

**Files:**
- Modify: `src/httpware/client.py`
- Modify: `tests/test_client.py`

Swap `max_error_body_bytes` → `max_response_body_bytes` on `AsyncClient` and
`Client`; delete the old name entirely; wire the terminal.

- [ ] **Step 1: Write failing tests**

  For both clients: `ValueError` when `max_response_body_bytes < 1` (test `0` and
  `-1`); a non-streaming `send()` against an over-cap body raises
  `ResponseTooLargeError` (declared and streamed); within-cap `send()` returns
  normally with intact `.content`; `max_response_body_bytes=None` leaves behavior
  unchanged. Run — red.

- [ ] **Step 2: Implement**

  Rename the ctor param + `self._max_*` attr on both clients; add the `>= 1`
  validation raising `ValueError("max_response_body_bytes must be >= 1")`. In
  `_terminal` / sync terminal: branch on `is None` — keep plain `send(request)`
  fast path; else `send(request, stream=True)` inside `try/finally: aclose()`,
  routed through `_read_capped[_async]`. Keep `_raise_on_status_error` after.
  Run — green.

- [ ] **Step 3: Commit**

  ```bash
  git add src/httpware/client.py tests/test_client.py
  git commit -m "feat!: replace max_error_body_bytes with max_response_body_bytes

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 5: Route `stream()` error pre-read through `_read_capped`

**Files:**
- Modify: `src/httpware/client.py`
- Modify: `tests/test_client.py` (streaming cases)

Replace the `Content-Length`-only block + `await response.aread()` in both
`stream()` methods with the shared helper; leave user-driven streaming uncapped.

- [ ] **Step 1: Write failing tests**

  In `stream()`: an over-cap 4xx/5xx error body raises `ResponseTooLargeError`
  (declared and streamed, incl. a chunked/no-`Content-Length` case); a within-cap
  error still raises the `StatusError` with `exc.response.content` populated; a
  user iterating a large **2xx** body is never capped. Sync + async. Run — red.

- [ ] **Step 2: Implement**

  In each `stream()` error branch (`400 <= status < 600`): replace the guard +
  `aread()` with `capped = _read_capped[_async](response, cap, response.request)`
  then `_raise_on_status_error(capped)`. Only when `cap is not None`; otherwise
  keep the existing unbounded `aread()`. Do not touch the success `yield`. Run —
  green.

- [ ] **Step 3: Commit**

  ```bash
  git add src/httpware/client.py tests/test_client.py
  git commit -m "feat: bound stream() error pre-read via _read_capped

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 6: Resilience-interaction tests

**Files:**
- Modify: `tests/` (retry + circuit-breaker suites)

Lock the fall-out behavior so a future refactor can't silently make
`ResponseTooLargeError` retryable or breaker-counting.

- [ ] **Step 1: Write tests (expect green)**

  With a retry middleware wrapping an over-cap response: assert exactly one
  terminal attempt and `ResponseTooLargeError` propagates (not retried). With a
  circuit breaker: assert a cap trip records neither success nor failure and never
  opens the breaker. Assert an over-cap **retryable 5xx** surfaces as
  `ResponseTooLargeError`, not the `StatusError` (cap-wins). Run — green (no prod
  code change expected; if red, the hierarchy assumption broke — stop and
  reconcile with the spec).

- [ ] **Step 2: Commit**

  ```bash
  git add tests/
  git commit -m "test: lock ResponseTooLargeError resilience semantics

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 7: Docs, deferred cleanup, index, release notes

**Files:**
- Modify: `architecture/client.md`, `architecture/errors.md`
- Modify: `planning/deferred.md`
- Modify: `planning/changes/README.md` (generated — via `just index`)
- Create: `planning/releases/<next-version>.md` (if a release is cut)
- Modify: `design.md`/`plan.md` frontmatter (`status: shipped`, `pr`, `outcome`)

Promote conclusions into the living architecture docs and retire the deferred
item.

- [ ] **Step 1: Architecture docs**

  Rewrite `architecture/client.md` "Bounded error bodies" → "Bounded response
  bodies": status-agnostic, decoded-byte, bomb-aware, `Content-Length`
  early-reject-only, `stream()` interaction, `cap is None` fast path, and the
  `.elapsed` caveat. Update the `ResponseTooLargeError` entry in
  `architecture/errors.md` (new `reason`, status-agnostic semantics).

- [ ] **Step 2: Retire the deferred item**

  Remove the "Non-streaming hard response-body cap" bullet from
  `planning/deferred.md`.

- [ ] **Step 3: Regenerate the index**

  ```bash
  just index
  ```

- [ ] **Step 4: Set ship frontmatter + commit**

  Set `status: shipped` + `pr` + `outcome` on both bundle files. Add release
  notes if a version is cut (note the breaking `max_error_body_bytes` removal).

  ```bash
  git add architecture/ planning/
  git commit -m "docs: promote response-body cap into architecture; retire deferred item

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 8: Full verification

- [ ] **Step 1: Lint + full suite**

  ```bash
  just lint && just test
  ```

  Confirm green and coverage preserved. Grep guard:
  `grep -rE 'httpx2\._' src/httpware/` returns nothing;
  `grep -rn 'max_error_body_bytes' src/ architecture/` returns nothing.

- [ ] **Step 2: Open the PR** per `finishing-a-development-branch`.

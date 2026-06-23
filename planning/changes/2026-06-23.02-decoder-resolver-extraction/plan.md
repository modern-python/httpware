---
status: draft
date: 2026-06-23
slug: decoder-resolver-extraction
spec: decoder-resolver-extraction
pr: null
---

# decoder-resolver-extraction — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps
> use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the 4-site decoder resolve/raise/decode/wrap smear behind one
`_DecoderResolver` (+ generic `_BoundDecoder`), with no behaviour change.

**Spec:** [`design.md`](./design.md)

**Branch:** `refactor/decoder-resolver-extraction`

**Commit strategy:** Per-task commits.

---

### Task 1: Add `_DecoderResolver` and rewire both clients

**Files:**
- Create: `src/httpware/decoders/_resolver.py`
- Modify: `src/httpware/client.py`

Existing decoder/client suites are the parity net — do not edit them in this task.

- [ ] **Step 1: Create `decoders/_resolver.py`**

  Add `_BoundDecoder(Generic[T])` (holds decoder + model; `decode(response) -> T`
  wrapping `except Exception` as `DecodeError`) and `_DecoderResolver`
  (`__init__(decoders: tuple[ResponseDecoder, ...])`, `resolve(model: type[T]) ->
  _BoundDecoder[T]` walking `_decoders`, raising `MissingDecoderError(model=…,
  registered_names=tuple(type(d).__name__ for d in self._decoders))` when none
  claims). Import `T` from `httpware.decoders` (the protocol's TypeVar) or define
  locally; import `DecodeError`/`MissingDecoderError` from `httpware.errors`,
  `ResponseDecoder` from `httpware.decoders`.

- [ ] **Step 2: Wire the resolver into both clients**

  In `AsyncClient.__init__` and `Client.__init__`, after `self._decoders = …`,
  add `self._decoder_resolver = _DecoderResolver(self._decoders)`. Keep
  `self._decoders`. Import `_DecoderResolver` from
  `httpware.decoders._resolver`.

- [ ] **Step 3: Replace the four call sites**

  In `AsyncClient.send`, `AsyncClient.send_with_response`, `Client.send`,
  `Client.send_with_response`, replace each resolve/raise/decode/wrap block with
  `bound = self._decoder_resolver.resolve(response_model)` (before
  `self._dispatch(request)`), then `bound.decode(response)` after. Keep the
  `send_with_response` `(response, decoded)` shape. Remove both
  `_dispatch_decoder` methods. `MissingDecoderError`/`DecodeError` imports in
  `client.py` may become unused — drop them if so.

- [ ] **Step 4: Verify parity**

  ```bash
  uv run pytest tests/test_decoders_pydantic.py tests/test_decoders_msgspec.py \
    tests/test_client_decoders_default.py tests/test_client_construction.py \
    tests/test_client_sync.py tests/test_optional_extras_pydantic_missing.py \
    tests/test_client_typing.py --no-cov -q
  ```
  All green, unchanged. If any fail, the extraction drifted — fix the resolver,
  not the tests.

- [ ] **Step 5: Commit**

  ```bash
  git add src/httpware/decoders/_resolver.py src/httpware/client.py
  git commit -m "refactor(decoders): extract _DecoderResolver for Seam B

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 2: Add seam-level resolver tests

**Files:**
- Create: `tests/test_decoder_resolver.py`

Drive `resolve` / `_BoundDecoder.decode` directly with a fake decoder list — no
client, no `MockTransport`.

- [ ] **Step 1: Write the matrix**

  A `FakeDecoder` claiming a set of model types (annotate all args). Cover:
  claiming model → bound whose `.decode(response)` returns the decoded value;
  no claimer → `MissingDecoderError` with `registered_names` matching the fake
  list and order; first-match-wins across two fakes; decode success on good
  bytes; decoder raises → `DecodeError` carrying `response` / `model` /
  `original`; empty decoder tuple → `MissingDecoderError` with `()`.

- [ ] **Step 2: Run**

  ```bash
  uv run pytest tests/test_decoder_resolver.py --no-cov -q
  ```
  All green.

- [ ] **Step 3: Commit**

  ```bash
  git add tests/test_decoder_resolver.py
  git commit -m "test(decoders): cover _DecoderResolver at the seam

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 3: Promote to architecture, lint, full suite

**Files:**
- Modify: `architecture/decoders.md`
- Modify: `planning/changes/2026-06-23.02-decoder-resolver-extraction/design.md` (frontmatter at ship)

- [ ] **Step 1: Promote the living truth**

  In `architecture/decoders.md`, replace the `_dispatch_decoder` references and
  the "`send`/`send_with_response` raise `MissingDecoderError`" framing with the
  `_DecoderResolver` / `_BoundDecoder` description: resolution + pre-flight error
  + decode-wrapping live in the resolver; the clients call `resolve` before
  dispatch and `bound.decode` after. Keep it prose, no frontmatter.

- [ ] **Step 2: Full gate**

  ```bash
  just lint && just test
  ```
  Both clean (100% coverage). Confirm the `httpx2._` and other review-only
  invariants still hold in the diff.

- [ ] **Step 3: Ship frontmatter + commit**

  Set `status: shipped`, `pr`, and `outcome` in `design.md` once the PR number
  exists. Run `just index` to confirm the listing regenerates.

  ```bash
  git add architecture/decoders.md planning/changes/2026-06-23.02-decoder-resolver-extraction/
  git commit -m "docs(decoders): promote _DecoderResolver into architecture truth

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

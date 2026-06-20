---
status: shipped
date: 2026-06-07
slug: decoder-error
spec: decoder-error
pr: 32
---

# DecodeError Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce `httpware.DecodeError` and wrap the two `_decoder.decode(...)` call sites in `Client.send` / `AsyncClient.send` so that any exception raised by a `ResponseDecoder` becomes a `ClientError` subclass — closing the gap where `pydantic.ValidationError` / `msgspec.ValidationError` / `msgspec.DecodeError` would escape `except httpware.ClientError`.

**Architecture:** New `DecodeError(ClientError)` class in `errors.py` with keyword-only init carrying `response: httpx2.Response`, `model: type`, `original: BaseException`, plus `__reduce__` for pickle parity. The wrap happens at Seam B (`Client/AsyncClient ↔ ResponseDecoder`) in `client.py`: both `send` methods grow `try: ... except Exception as exc: raise DecodeError(...) from exc`. Decoder classes (`PydanticDecoder`, `MsgspecDecoder`) are unchanged. The `ResponseDecoder` protocol grows one docstring sentence, no signature change.

**Tech Stack:** Python 3.11+, `httpx2`, pydantic 2.x / msgspec 0.18+ (optional extras), `pytest` + `pytest-asyncio` auto mode, `ty` for type checking, `ruff` for lint, `just` task runner.

---

## Spec reference

The validated spec is at `planning/specs/2026-06-07-decoder-error-design.md`. Read it before starting. Decisions locked there and not re-debated here:

- `DecodeError` is a **direct child of `ClientError`** (sibling of `StatusError`, `TransportError`, etc.) — not under a new intermediate parent.
- The seam wrapper **catches `Exception`**, not `BaseException` — `KeyboardInterrupt` / `SystemExit` / `asyncio.CancelledError` (3.11+) propagate untouched.
- The `ResponseDecoder` protocol stays silent on exceptions; only the docstring grows one sentence.
- `PydanticDecoder` and `MsgspecDecoder` are unchanged.
- Init is keyword-only: `DecodeError(*, response, model, original)`.
- `original` is kept as an attribute even though `__cause__` carries the same reference.
- Message format: `f"failed to decode response into {model.__name__}: {original}"`.
- Target release: **0.8.1** (patch; the leaked exceptions weren't a documented contract).

## File structure

| Path | Operation | Responsibility |
|---|---|---|
| `src/httpware/errors.py` | modify | Add `_reconstruct_decode_error` + `DecodeError` class. |
| `src/httpware/client.py` | modify | Extend errors import; wrap `_decoder.decode(...)` call in both `Client.send` (line ~874) and `AsyncClient.send` (line ~157). |
| `src/httpware/__init__.py` | modify | Re-export `DecodeError`; add to `__all__`. |
| `src/httpware/decoders/__init__.py` | modify | Add one sentence to `ResponseDecoder.decode` docstring. |
| `tests/test_errors.py` | modify | Add construction, chaining, pickle, and inheritance tests for `DecodeError`. |
| `tests/test_client_response_model.py` | modify | **Delete** the obsolete `test_decoder_validation_error_propagates_unwrapped`; add seam-wrap tests (schema mismatch, malformed JSON, `except ClientError` catches) for both sync and async clients. |
| `tests/test_decoders_msgspec.py` | modify | Add one seam-level test that proves wrapping is decoder-agnostic (use `MsgspecDecoder()` through `AsyncClient`). |
| `tests/test_public_api.py` | modify | Add `DecodeError` to the `expected` symbol set. |
| `docs/errors.md` | modify | Add `DecodeError` leaf to the hierarchy diagram; add a `DecodeError` reference subsection. |
| `planning/engineering.md` | modify | Update Seam B contract and the §4 exception contract to mention `DecodeError` and the wrapping. |
| `README.md` | modify | One-line note after the `response_model=` paragraph mentioning `DecodeError`. |

No new files. No file is deleted.

## A note on TDD here

This plan follows code-style TDD: each behavior change is exercised by a failing test first, the test is run to confirm it fails for the expected reason, then the minimal implementation is written, then the test is re-run to confirm it passes, then committed. Docs tasks (errors.md, engineering.md, README) are not TDD-able; they ship with a manual review step.

---

## Task 1: Add `DecodeError` class to `errors.py`

**Files:**
- Test: `tests/test_errors.py` (add cases)
- Modify: `src/httpware/errors.py` (add class + `_reconstruct_decode_error`)

- [ ] **Step 1: Add failing tests to `tests/test_errors.py`**

Append to `tests/test_errors.py`. First extend the `from httpware.errors import (...)` block (currently at lines 9–29) to include `DecodeError` between `ConflictError` and `ForbiddenError` (alphabetical), then append the new tests at the bottom of the file:

```python
import pydantic


class _DecodeErrorModel(pydantic.BaseModel):
    id: int


def _make_ok_response(*, url: str = "https://example.test/x") -> httpx2.Response:
    request = httpx2.Request("GET", url)
    return httpx2.Response(200, content=b'{"id": 1}', request=request)


def test_decode_error_is_client_error() -> None:
    response = _make_ok_response()
    inner = ValueError("bad payload")
    exc = DecodeError(response=response, model=_DecodeErrorModel, original=inner)
    assert isinstance(exc, ClientError)


def test_decode_error_stores_fields() -> None:
    response = _make_ok_response()
    inner = ValueError("bad payload")
    exc = DecodeError(response=response, model=_DecodeErrorModel, original=inner)
    assert exc.response is response
    assert exc.model is _DecodeErrorModel
    assert exc.original is inner


def test_decode_error_summary_includes_model_and_original() -> None:
    response = _make_ok_response()
    inner = ValueError("bad payload")
    exc = DecodeError(response=response, model=_DecodeErrorModel, original=inner)
    summary = str(exc)
    assert "_DecodeErrorModel" in summary
    assert "bad payload" in summary
    assert summary.startswith("failed to decode response into ")


def test_decode_error_rejects_positional_args() -> None:
    response = _make_ok_response()
    inner = ValueError("bad payload")
    with pytest.raises(TypeError):
        DecodeError(response, _DecodeErrorModel, inner)  # type: ignore[misc]


def test_decode_error_chaining_via_raise_from() -> None:
    response = _make_ok_response()
    inner = ValueError("bad payload")
    try:
        try:
            raise inner
        except ValueError as caught:
            raise DecodeError(response=response, model=_DecodeErrorModel, original=caught) from caught
    except DecodeError as exc:
        assert exc.__cause__ is inner
        assert exc.original is inner


def test_decode_error_pickleable() -> None:
    response = _make_ok_response(url="https://example.test/p")
    inner = ValueError("bad payload")
    exc = DecodeError(response=response, model=_DecodeErrorModel, original=inner)
    restored = pickle.loads(pickle.dumps(exc))  # noqa: S301
    assert isinstance(restored, DecodeError)
    assert restored.model is _DecodeErrorModel
    assert isinstance(restored.original, ValueError)
    assert str(restored.original) == "bad payload"
    assert restored.response.status_code == 200  # noqa: PLR2004
```

Then extend the `test_inheritance_tree` function (currently around line 37) by adding one line inside the function:

```python
assert issubclass(DecodeError, ClientError)
```

The `import pydantic` goes at the top of the test file with the other imports (currently `import builtins`, `import pickle`, `import httpx2`, `import pytest`). Add `_DecodeErrorModel` and `_make_ok_response` near the existing `_make_response` helper (around line 32).

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_errors.py -v -k decode_error
```

Expected: `ImportError` from the `from httpware.errors import (..., DecodeError, ...)` line at module load — the test collection phase fails before any test runs. That's fine; it's the "function not defined" equivalent for a missing class.

- [ ] **Step 3: Implement `DecodeError` in `src/httpware/errors.py`**

Append to `src/httpware/errors.py` (after the `BulkheadFullError` block, before the file ends):

```python
def _reconstruct_decode_error(
    cls: "type[DecodeError]",
    response: httpx2.Response,
    model: type,
    original: BaseException,
) -> "DecodeError":
    return cls(response=response, model=model, original=original)


class DecodeError(ClientError):
    """Raised when the active ResponseDecoder failed to decode response.content.

    The HTTP call itself succeeded — status was 2xx/3xx and the transport
    delivered the body intact — but the body could not be parsed into the
    requested response_model. Always chained from the underlying library
    exception via ``raise ... from exc``; that exception is also exposed as
    ``self.original`` for structured handling.
    """

    response: httpx2.Response
    model: type
    original: BaseException

    def __init__(
        self,
        *,
        response: httpx2.Response,
        model: type,
        original: BaseException,
    ) -> None:
        self.response = response
        self.model = model
        self.original = original
        super().__init__(f"failed to decode response into {model.__name__}: {original}")

    def __reduce__(self) -> tuple[Any, ...]:
        return (
            _reconstruct_decode_error,
            (type(self), self.response, self.model, self.original),
        )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_errors.py -v
```

Expected: all decode-error tests pass; pre-existing tests stay green.

- [ ] **Step 5: Run lint and type-check**

```bash
just lint
```

Expected: clean. If `ty` complains about `original: BaseException` field shadowing — it shouldn't, but if it does, the suppression pattern is `# ty: ignore[<rule>]` per `CLAUDE.md`.

- [ ] **Step 6: Commit**

```bash
git add src/httpware/errors.py tests/test_errors.py
git commit -m "$(cat <<'EOF'
errors: add DecodeError for ResponseDecoder failures

DecodeError is a direct child of ClientError carrying the response,
model, and original library exception. Construction-only here; the
client.send wrap follows in the next commit.
EOF
)"
```

---

## Task 2: Re-export `DecodeError` from `httpware/__init__.py`

**Files:**
- Test: `tests/test_public_api.py` (extend `expected` set)
- Modify: `src/httpware/__init__.py`

- [ ] **Step 1: Add failing test**

Edit `tests/test_public_api.py:30–68`. Add `"DecodeError",` to the `expected` set (alphabetical — between `"ConflictError"` and `"ForbiddenError"`):

```python
def test_expected_exports() -> None:
    expected = {
        "AsyncBulkhead",
        "AsyncClient",
        "AsyncMiddleware",
        "AsyncNext",
        "AsyncRetry",
        "BadRequestError",
        "Bulkhead",
        "BulkheadFullError",
        "Client",
        "ClientError",
        "ClientStatusError",
        "ConflictError",
        "DecodeError",
        "ForbiddenError",
        # ... rest unchanged
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_public_api.py -v
```

Expected: `test_expected_exports` fails with `AssertionError: expected exports missing from __all__: {'DecodeError'}`. `test_all_exports_resolve` continues to pass (the `expected` set is checked separately).

- [ ] **Step 3: Add `DecodeError` to `__init__.py`**

Edit `src/httpware/__init__.py:5–25`. The errors-import block currently lists symbols alphabetically. Add `DecodeError` between `ConflictError` and `ForbiddenError`:

```python
from httpware.errors import (
    STATUS_TO_EXCEPTION,
    BadRequestError,
    BulkheadFullError,
    ClientError,
    ClientStatusError,
    ConflictError,
    DecodeError,
    ForbiddenError,
    InternalServerError,
    NetworkError,
    NotFoundError,
    RateLimitedError,
    RetryBudgetExhaustedError,
    ServerStatusError,
    ServiceUnavailableError,
    StatusError,
    TimeoutError,  # noqa: A004
    TransportError,
    UnauthorizedError,
    UnprocessableEntityError,
)
```

Add `"DecodeError",` to `__all__` (line 41+), alphabetically — between `"ConflictError"` and `"ForbiddenError"`:

```python
__all__ = [
    "STATUS_TO_EXCEPTION",
    # ... existing entries ...
    "ConflictError",
    "DecodeError",
    "ForbiddenError",
    # ... rest unchanged
]
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_public_api.py -v
```

Expected: all three public-API tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/httpware/__init__.py tests/test_public_api.py
git commit -m "$(cat <<'EOF'
errors: re-export DecodeError from httpware top-level

Adds DecodeError to httpware.__init__'s errors import block and __all__,
plus the explicit expected-exports test. No behavior change yet.
EOF
)"
```

---

## Task 3: Wrap the decoder call in both `send` methods

**Files:**
- Test: `tests/test_client_response_model.py` (delete obsolete test; add seam-wrap tests)
- Modify: `src/httpware/client.py` (extend errors import; wrap both `send` decoder calls)

- [ ] **Step 1: Delete the obsolete test**

In `tests/test_client_response_model.py`, **delete** the existing test at lines 50–53 in full:

```python
async def test_decoder_validation_error_propagates_unwrapped() -> None:
    client = _client_with_payload(b'{"id": "not-an-int", "name": "x"}')
    with pytest.raises(pydantic.ValidationError):
        await client.get("https://example.test/u", response_model=_User)
```

This test asserts the *previous* (broken) behavior — that `pydantic.ValidationError` escapes unwrapped. It is replaced by the seam-wrap tests below.

- [ ] **Step 2: Add failing seam-wrap tests**

Extend `tests/test_client_response_model.py`. First add the `Client` import to the existing import line (currently `from httpware import AsyncClient, NotFoundError`) and add `DecodeError`:

```python
from httpware import AsyncClient, Client, DecodeError, NotFoundError
```

(`ClientError` belongs at module top-level — do not add it inside a test function with `# noqa: PLC0415`.) Extend the import:

```python
from httpware import AsyncClient, Client, ClientError, DecodeError, NotFoundError
```

Then add a sync mock-transport helper next to the existing `_client_with_payload` (which currently returns `AsyncClient` only):

```python
def _sync_client_with_payload(payload: bytes, content_type: str = "application/json") -> Client:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            HTTPStatus.OK,
            content=payload,
            headers={"content-type": content_type},
            request=request,
        )

    transport = httpx2.MockTransport(handler)
    return Client(httpx2_client=httpx2.Client(transport=transport))
```

Then append the new tests at the end of the file:

```python
async def test_async_schema_mismatch_raises_decode_error() -> None:
    client = _client_with_payload(b"null")
    with pytest.raises(DecodeError) as exc_info:
        await client.get("https://example.test/u", response_model=_User)
    exc = exc_info.value
    assert exc.response.status_code == HTTPStatus.OK
    assert exc.model is _User
    assert isinstance(exc.original, pydantic.ValidationError)
    assert exc.__cause__ is exc.original


async def test_async_malformed_json_raises_decode_error() -> None:
    client = _client_with_payload(b"{not json")
    with pytest.raises(DecodeError) as exc_info:
        await client.get("https://example.test/u", response_model=_User)
    exc = exc_info.value
    assert exc.response.status_code == HTTPStatus.OK
    assert exc.model is _User
    assert isinstance(exc.original, pydantic.ValidationError)


async def test_async_decode_error_caught_by_client_error() -> None:
    """The user-facing promise: `except ClientError` catches decode failures."""
    client = _client_with_payload(b"null")
    try:
        await client.get("https://example.test/u", response_model=_User)
    except ClientError as exc:
        assert isinstance(exc, DecodeError)
    else:
        pytest.fail("expected DecodeError to be raised")


def test_sync_schema_mismatch_raises_decode_error() -> None:
    client = _sync_client_with_payload(b"null")
    with pytest.raises(DecodeError) as exc_info:
        client.get("https://example.test/u", response_model=_User)
    exc = exc_info.value
    assert exc.response.status_code == HTTPStatus.OK
    assert exc.model is _User
    assert isinstance(exc.original, pydantic.ValidationError)


def test_sync_malformed_json_raises_decode_error() -> None:
    client = _sync_client_with_payload(b"{not json")
    with pytest.raises(DecodeError):
        client.get("https://example.test/u", response_model=_User)
```


- [ ] **Step 3: Run tests to verify they fail**

```bash
uv run pytest tests/test_client_response_model.py -v
```

Expected: all five new tests fail with `pydantic.ValidationError` (or `pydantic_core._pydantic_core.ValidationError`) instead of `DecodeError` — because the seam wrap is not yet in place.

- [ ] **Step 4: Extend the errors import in `client.py`**

Edit `src/httpware/client.py:19`. Currently:

```python
from httpware.errors import TransportError
```

Change to:

```python
from httpware.errors import DecodeError, TransportError
```

- [ ] **Step 5: Wrap the async `send` decoder call**

Edit `src/httpware/client.py`. The async `send` method is at line 147; the unguarded decode call is at line 157. Replace:

```python
async def send(
    self,
    request: httpx2.Request,
    *,
    response_model: type[T] | None = None,
) -> httpx2.Response | T:
    """Send `request` through the middleware chain. Decode if `response_model` is set."""
    response = await self._dispatch(request)
    if response_model is None:
        return response
    return self._decoder.decode(response.content, response_model)
```

with:

```python
async def send(
    self,
    request: httpx2.Request,
    *,
    response_model: type[T] | None = None,
) -> httpx2.Response | T:
    """Send `request` through the middleware chain. Decode if `response_model` is set."""
    response = await self._dispatch(request)
    if response_model is None:
        return response
    try:
        return self._decoder.decode(response.content, response_model)
    except Exception as exc:
        raise DecodeError(response=response, model=response_model, original=exc) from exc
```

Critical: `await self._dispatch(request)` stays **outside** the try — transport/status errors are already mapped to `ClientError` subclasses by `_terminal` and should not be re-wrapped as `DecodeError`.

- [ ] **Step 6: Wrap the sync `send` decoder call**

Edit `src/httpware/client.py`. The sync `send` method is at line 864; the unguarded decode call is at line 874. Replace:

```python
def send(
    self,
    request: httpx2.Request,
    *,
    response_model: type[T] | None = None,
) -> httpx2.Response | T:
    """Send `request` through the middleware chain. Decode if `response_model` is set."""
    response = self._dispatch(request)
    if response_model is None:
        return response
    return self._decoder.decode(response.content, response_model)
```

with:

```python
def send(
    self,
    request: httpx2.Request,
    *,
    response_model: type[T] | None = None,
) -> httpx2.Response | T:
    """Send `request` through the middleware chain. Decode if `response_model` is set."""
    response = self._dispatch(request)
    if response_model is None:
        return response
    try:
        return self._decoder.decode(response.content, response_model)
    except Exception as exc:
        raise DecodeError(response=response, model=response_model, original=exc) from exc
```

Same `self._dispatch(request)` outside-the-try rule.

- [ ] **Step 7: Run tests to verify they pass**

```bash
uv run pytest tests/test_client_response_model.py -v
```

Expected: all tests pass (the five new ones plus the surviving original four).

- [ ] **Step 8: Run lint and type-check**

```bash
just lint
```

Expected: clean. If `ruff` flags `except Exception` with `BLE001` (broad-except), the suppression line is `# noqa: BLE001 — decoder-specific exceptions are wrapped as DecodeError at this seam`. Verify by running first; only add the noqa if ruff actually flags it.

- [ ] **Step 9: Commit**

```bash
git add src/httpware/client.py tests/test_client_response_model.py
git commit -m "$(cat <<'EOF'
client: wrap decoder exceptions as DecodeError at seam B

Both Client.send and AsyncClient.send now translate any Exception
raised by the active ResponseDecoder into httpware.DecodeError, so
`except httpware.ClientError` covers the response_model= path
uniformly regardless of which decoder is wired in.

Drops the previous test_decoder_validation_error_propagates_unwrapped
case which encoded the now-fixed leak.
EOF
)"
```

---

## Task 4: Prove the wrap is decoder-agnostic (msgspec seam test)

**Files:**
- Test: `tests/test_decoders_msgspec.py` (append one seam-level test)

- [ ] **Step 1: Add a seam-level msgspec test**

Append to `tests/test_decoders_msgspec.py`. Extend the existing imports:

```python
import httpx2
from http import HTTPStatus

from httpware import AsyncClient, DecodeError
```

Then append the test:

```python
async def test_msgspec_decoder_failures_wrap_as_decode_error_at_seam() -> None:
    """Proves wrapping is decoder-agnostic: switching to MsgspecDecoder still yields DecodeError."""
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(HTTPStatus.OK, content=b"{not json", request=request)

    transport = httpx2.MockTransport(handler)
    client = AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=transport),
        decoder=MsgspecDecoder(),
    )
    with pytest.raises(DecodeError) as exc_info:
        await client.get("https://example.test/x", response_model=_Item)
    exc = exc_info.value
    assert exc.model is _Item
    assert isinstance(exc.original, (msgspec.DecodeError, msgspec.ValidationError))
```

The existing direct-decoder tests (`test_decode_validation_error_propagates`, `test_decode_json_parse_error_propagates`) stay as-is — they test the decoder, not the seam.

- [ ] **Step 2: Run tests to verify they pass**

```bash
uv run pytest tests/test_decoders_msgspec.py -v
```

Expected: all pass. The seam wrap was already added in Task 3; this test only proves it works for a non-default decoder.

- [ ] **Step 3: Run lint and type-check**

```bash
just lint
```

- [ ] **Step 4: Commit**

```bash
git add tests/test_decoders_msgspec.py
git commit -m "$(cat <<'EOF'
tests: prove DecodeError wrap is decoder-agnostic via msgspec

Seam-level test wires MsgspecDecoder into AsyncClient and asserts a
malformed-JSON response still surfaces as httpware.DecodeError with
exc.original carrying the underlying msgspec exception.
EOF
)"
```

---

## Task 5: Update the `ResponseDecoder` protocol docstring

**Files:**
- Modify: `src/httpware/decoders/__init__.py`

- [ ] **Step 1: Extend the docstring**

Edit `src/httpware/decoders/__init__.py:13–15`. Replace:

```python
def decode(self, content: bytes, model: type[T]) -> T:
    """Decode `content` (raw response bytes) into an instance of `model`."""
    ...
```

with:

```python
def decode(self, content: bytes, model: type[T]) -> T:
    """Decode `content` (raw response bytes) into an instance of `model`.

    Any exception raised by `decode` is wrapped by `Client.send` /
    `AsyncClient.send` into `httpware.DecodeError`; implementers do not
    need to raise `DecodeError` directly.
    """
    ...
```

- [ ] **Step 2: Run the full test suite + lint**

```bash
uv run pytest -q
just lint
```

Expected: clean. This is a docstring-only change; nothing else should move.

- [ ] **Step 3: Commit**

```bash
git add src/httpware/decoders/__init__.py
git commit -m "$(cat <<'EOF'
decoders: document the DecodeError seam wrap on ResponseDecoder

One-sentence addition: implementers can raise whatever their backing
library raises; Client.send / AsyncClient.send translate to
httpware.DecodeError at the seam.
EOF
)"
```

---

## Task 6: Update `docs/errors.md`

**Files:**
- Modify: `docs/errors.md`

- [ ] **Step 1: Add `DecodeError` to the hierarchy diagram**

Edit `docs/errors.md:11–30`. Add `DecodeError` as a sibling leaf under `ClientError`, after `BulkheadFullError`:

```text
ClientError                          (catch-all for anything httpware raises)
├── TransportError                   (connection/network/protocol failure pre-response)
│   └── NetworkError                 (transient — safe to retry; covered by AsyncRetry's defaults)
├── TimeoutError                     (also inherits builtins.TimeoutError — except OSError catches it)
├── StatusError                      (got a response but its status was 4xx/5xx)
│   ├── ClientStatusError            (any 4xx — fallback for unknown 4xx codes)
│   │   ├── BadRequestError          (400)
│   │   ├── UnauthorizedError        (401)
│   │   ├── ForbiddenError           (403)
│   │   ├── NotFoundError            (404)
│   │   ├── ConflictError            (409)
│   │   ├── UnprocessableEntityError (422)
│   │   └── RateLimitedError         (429)
│   └── ServerStatusError            (any 5xx — fallback for unknown 5xx codes)
│       ├── InternalServerError     (500)
│       └── ServiceUnavailableError (503)
├── RetryBudgetExhaustedError       (a retry was needed but the budget refused)
├── BulkheadFullError                (acquire_timeout elapsed before a slot opened)
└── DecodeError                      (response_model= decoder failed; HTTP call itself succeeded)
```

- [ ] **Step 2: Add a `DecodeError` reference subsection**

Insert a new subsection between "Resilience-error payloads" (currently line ~109) and "See also" (currently line ~131). New subsection text:

```markdown
## `DecodeError`

`DecodeError` is raised when `response_model=` is set on a request and the active `ResponseDecoder` failed to parse the response body. The HTTP call itself succeeded — status was 2xx/3xx and the transport delivered the body intact — but the body could not be coerced into the requested model. The exception is raised independently of which decoder is in use (`PydanticDecoder`, `MsgspecDecoder`, or a third-party adapter), so `except httpware.ClientError` is sufficient to cover the response-model decode path.

Fields:

- `response: httpx2.Response` — the response whose body failed to decode. Status, headers, and the originating `request` are all available via `exc.response.*`.
- `model: type` — the type that was passed as `response_model=`.
- `original: BaseException` — the underlying library exception (e.g., `pydantic.ValidationError`, `msgspec.ValidationError`, `msgspec.DecodeError`). Also available via `exc.__cause__`.

```python
from httpware import AsyncClient, DecodeError


try:
    user = await client.get("/users/1", response_model=User)
except DecodeError as exc:
    _LOGGER.error(
        "decode failed for %s into %s: %s",
        exc.response.request.url,
        exc.model.__name__,
        exc.original,
    )
    raise
```
```

- [ ] **Step 3: Manual review of the docs**

Open `docs/errors.md` and skim the result. Check:
- Hierarchy diagram is balanced (the `└──` and `├──` characters line up).
- The new section sits between "Resilience-error payloads" and "See also" — not inside either.
- The code block in the new section closes cleanly.

- [ ] **Step 4: Commit**

```bash
git add docs/errors.md
git commit -m "$(cat <<'EOF'
docs: document DecodeError in the errors reference

Adds DecodeError to the exception-tree diagram and a new subsection
covering when it's raised, what fields it carries, and a minimal
except snippet.
EOF
)"
```

---

## Task 7: Update `planning/engineering.md`

**Files:**
- Modify: `planning/engineering.md`

- [ ] **Step 1: Update the Seam B contract**

Edit `planning/engineering.md` Seam B section (currently around lines 39–43). Replace:

```markdown
### Seam B: `AsyncClient ↔ ResponseDecoder`

- **Where:** `src/httpware/client.py` ↔ `src/httpware/decoders/`.
- **Contract:** the decoder is invoked when the caller passes `response_model=`. The protocol is `decode(content: bytes, model: type[T]) -> T`. Decoder errors (`pydantic.ValidationError`, `msgspec.ValidationError`) propagate unwrapped.
- **Rule:** the decoder must operate on raw bytes in a single parse pass. ...
```

with:

```markdown
### Seam B: `Client`/`AsyncClient` ↔ `ResponseDecoder`

- **Where:** `src/httpware/client.py` ↔ `src/httpware/decoders/`.
- **Contract:** the decoder is invoked when the caller passes `response_model=`. The protocol is `decode(content: bytes, model: type[T]) -> T`. Any exception raised by `decode` is wrapped by `Client.send` / `AsyncClient.send` into `httpware.DecodeError` (a `ClientError` subclass carrying `response`, `model`, `original`). Decoder implementers do not need to raise `DecodeError` directly.
- **Rule:** the decoder must operate on raw bytes in a single parse pass. ...
```

(Keep the rest of the Rule paragraph verbatim — only the Contract line changes; the Where line picks up both worlds.)

- [ ] **Step 2: Update §4 exception contract**

Edit the "## 4. Exception contract" section (currently starts at line ~52). After the existing paragraph about `TimeoutError` (line ~66), append:

```markdown
`DecodeError` covers the case where `response_model=` is set, the HTTP call itself succeeded, but the active `ResponseDecoder` raised. The wrap happens at the seam in `Client.send` / `AsyncClient.send` — `except Exception` translates any decoder-side failure into `DecodeError(response=..., model=..., original=...)` with `raise ... from exc` chaining. The `original` attribute exposes the underlying library exception (e.g., `pydantic.ValidationError`, `msgspec.ValidationError`); `__cause__` carries the same reference.
```

- [ ] **Step 3: Commit**

```bash
git add planning/engineering.md
git commit -m "$(cat <<'EOF'
engineering: document DecodeError + seam B wrap

Updates the Seam B contract to spell out the wrap, and adds a
paragraph to the §4 exception contract describing when DecodeError
is raised and what fields it carries.
EOF
)"
```

---

## Task 8: Add a README note

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add the one-line note**

Edit `README.md`. After the line at `README.md:52`:

```markdown
Typed decoding via `response_model=` works in both worlds — requires `pip install httpware[pydantic]`:
```

…insert a new line directly below (above the `from httpware import AsyncClient` block at line 55):

```markdown
Typed decoding via `response_model=` works in both worlds — requires `pip install httpware[pydantic]`. Decode failures (malformed body, schema mismatch) raise `httpware.DecodeError`, a `ClientError` subclass — so `except httpware.ClientError` covers them alongside transport and status errors.
```

(The merge collapses the original sentence and the new one onto a single paragraph; the `from httpware import AsyncClient` example below remains unchanged.)

- [ ] **Step 2: Visual review**

Open `README.md` and confirm:
- The paragraph reads naturally as one sentence flowing into the next.
- No widows / orphan line breaks in markdown.
- The code block below is unaffected.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "$(cat <<'EOF'
docs: note DecodeError in the README response_model paragraph

One-line addition: response_model= decode failures raise
httpware.DecodeError (a ClientError subclass), so the standard
except httpware.ClientError catches them.
EOF
)"
```

---

## Task 9: Final verification

**Files:** none modified. Pure verification.

- [ ] **Step 1: Run the full test suite**

```bash
just test
```

Expected: every test in `tests/` passes; the run reports coverage (100% line coverage is the target — `planning/engineering.md` §6).

- [ ] **Step 2: Run the CI-shape lint**

```bash
just lint-ci
```

Expected: clean. This matches what CI runs; it does **not** auto-fix.

- [ ] **Step 3: Verify the architectural invariants still hold**

```bash
grep -rE 'httpx2\._' src/httpware/
grep -rn 'from __future__ import annotations' src/httpware/
grep -rn 'print(' src/httpware/
```

Expected: each returns zero matches. These are the CI-enforced invariants from `CLAUDE.md`.

- [ ] **Step 4: Verify the public API**

```bash
uv run python -c "import httpware; print(httpware.DecodeError); print(issubclass(httpware.DecodeError, httpware.ClientError))"
```

Expected output:

```text
<class 'httpware.errors.DecodeError'>
True
```

- [ ] **Step 5: Spot-check coverage of the new code**

```bash
uv run pytest tests/test_errors.py tests/test_client_response_model.py tests/test_decoders_msgspec.py tests/test_public_api.py --cov=httpware.errors --cov=httpware.client --cov-report=term-missing
```

Expected: the new `DecodeError` class and the two `try/except` blocks in `client.py` show 100% line coverage. If any line is unhit, add a test before claiming done.

- [ ] **Step 6: Confirm release readiness**

The work is now ready to ship as `0.8.1`. No version bump happens in this plan — release-cutting is a separate manual step per the project's existing convention (bare-semver git tag, no CHANGELOG file, release notes on GitHub Releases).

---
status: shipped
date: 2026-06-10
slug: multi-decoder
spec: multi-decoder
pr: 41
---

# Multi-Decoder Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single-decoder slot on `AsyncClient`/`Client` with a type-dispatched `decoders=[...]` list, remove the 0.3.0 eager-import fail-fast for missing pydantic, and add `MissingDecoderError` (fires before the HTTP call when no registered decoder claims `response_model=`).

**Architecture:** `ResponseDecoder` Protocol gains a `can_decode(model) -> bool` predicate. Both built-in decoders claim broadly — pydantic via `TypeAdapter(model)` probe, msgspec via `msgspec.json.Decoder(model)` probe — each rejects the other library's native type. The client holds `_decoders: tuple[ResponseDecoder, ...]`, resolved at `__init__` from installed extras (pydantic-first when both present) or from explicit `decoders=` kwarg. `send()` and `send_with_response()` run a pre-flight `_dispatch_decoder()` walk before the HTTP call; an empty walk raises `MissingDecoderError`. The kwarg is renamed `decoder=` → `decoders=` (clean cutover; pre-1.0).

**Tech Stack:** Python 3.11+, `httpx2`, pydantic 2.x (optional extra), msgspec (optional extra), `pytest` + `pytest-asyncio` auto mode, `ty` for type checking, `ruff` for lint, `just` task runner.

---

## Spec reference

The validated spec is at `planning/specs/2026-06-09-multi-decoder-design.md`. Read it before starting. Decisions locked there and not re-debated here:

- **Type-dispatched list, not per-call override.** Decoder list is composed at `__init__` and frozen.
- **Broad claim policy, ordering wins.** Each built-in claims everything its library can handle; first decoder in the list wins for shared shapes; native types route correctly because each library rejects the other's native.
- **Pydantic-first default ordering** when both extras installed.
- **Eager dispatch check at `.send()` entry** — `MissingDecoderError` fires before the HTTP request, not after.
- **Clean rename `decoder=` → `decoders=`** with no shim. Pre-1.0; bumps minor to 0.9.0.
- **`MissingDecoderError` carries `(model, registered_names)`** — class-name snapshot, not decoder instances (picklability).
- **`PydanticDecoder.__init__` still raises** `ImportError` when pydantic is missing — only the *default-construction* path stops calling it. Direct `PydanticDecoder()` usage when the extra is missing still errors.
- **No new stdlib `JsonDecoder`.** Out of scope; users with only `response_model=dict` install pydantic or msgspec.

## Sequencing rationale

The 100%-coverage gate (`pyproject.toml:93` — `--cov-fail-under=100`) forces atomic refactors. The two large tasks (Task 4 AsyncClient migration, Task 5 sync Client migration) MUST land in single commits — every existing test that reads `client._decoder` or passes `decoder=` breaks the moment the client is touched.

Phase A (Tasks 1–3) adds new surfaces without touching client behavior. Phase B (Tasks 4–5) wires them in. Phase C (Tasks 6–7) adds dedicated integration test files for the new dispatch surface. Phase D (Tasks 8–9) finishes the docs and engineering note updates.

After each task: run `just lint && just test`. The suite must be green before commit.

---

## Phase A — New surfaces (additive)

### Task 1: Add `can_decode` to Protocol and both built-in decoders

**Files:**
- Modify: `src/httpware/decoders/__init__.py`
- Modify: `src/httpware/decoders/pydantic.py`
- Modify: `src/httpware/decoders/msgspec.py`
- Modify: `tests/test_decoders_pydantic.py` (add `can_decode` table tests)
- Modify: `tests/test_decoders_msgspec.py` (add `can_decode` table tests and cache assertion)

Add the `can_decode(model) -> bool` predicate to the Protocol, with broad claim implementations in both concrete decoders. Add a cached `_get_msgspec_decoder` helper to `MsgspecDecoder` (mirroring pydantic's `_get_adapter`) so `can_decode` and `decode` share construction cost.

- [ ] **Step 1: Write the failing tests for `PydanticDecoder.can_decode`**

Append to `tests/test_decoders_pydantic.py`:

```python
import msgspec


class _Struct(msgspec.Struct):
    id: int
    name: str


def test_pydantic_can_decode_basemodel() -> None:
    assert PydanticDecoder().can_decode(User) is True


def test_pydantic_can_decode_dataclass() -> None:
    assert PydanticDecoder().can_decode(UserDC) is True


def test_pydantic_can_decode_dict() -> None:
    assert PydanticDecoder().can_decode(dict) is True


def test_pydantic_can_decode_list_of_models() -> None:
    assert PydanticDecoder().can_decode(list[User]) is True


def test_pydantic_can_decode_primitive_int() -> None:
    assert PydanticDecoder().can_decode(int) is True


def test_pydantic_can_decode_optional_int() -> None:
    assert PydanticDecoder().can_decode(int | None) is True


def test_pydantic_rejects_msgspec_struct() -> None:
    assert PydanticDecoder().can_decode(_Struct) is False


def test_pydantic_can_decode_uses_cache() -> None:
    _get_adapter.cache_clear()
    decoder = PydanticDecoder()
    decoder.can_decode(User)
    decoder.can_decode(User)
    info = _get_adapter.cache_info()
    assert info.hits >= 1
    assert info.misses == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_decoders_pydantic.py::test_pydantic_can_decode_basemodel -v
```
Expected: FAIL with `AttributeError: 'PydanticDecoder' object has no attribute 'can_decode'`.

- [ ] **Step 3: Add `can_decode` to the Protocol**

Edit `src/httpware/decoders/__init__.py`:

```python
"""ResponseDecoder protocol — the Client/AsyncClient ↔ ResponseDecoder seam (Seam B)."""

from typing import Protocol, TypeVar, runtime_checkable


T = TypeVar("T")


@runtime_checkable
class ResponseDecoder(Protocol):
    """Structural protocol every response-body decoder satisfies."""

    def can_decode(self, model: type) -> bool:
        """Return True iff this decoder claims responsibility for `model`.

        The client walks its `_decoders` tuple in order and picks the first
        decoder whose `can_decode` returns True. Implementations should claim
        every model type they can actually handle — broad is correct, because
        list ordering encodes the caller's preference for shared shapes.
        Native types of another library (e.g. `PydanticDecoder` vs
        `msgspec.Struct`) MUST be rejected.
        """
        ...

    def decode(self, content: bytes, model: type[T]) -> T:
        """Decode `content` (raw response bytes) into an instance of `model`.

        Any exception raised by `decode` is wrapped by `Client.send` /
        `AsyncClient.send` into `httpware.DecodeError`; implementers do not
        need to raise `DecodeError` directly.
        """
        ...


__all__ = ["ResponseDecoder"]
```

- [ ] **Step 4: Implement `PydanticDecoder.can_decode`**

Edit `src/httpware/decoders/pydantic.py`. Leave the existing module docstring as-is for now (it accurately describes the still-live `_default_pydantic_decoder()` path; Task 5 updates the docstring after the helper is deleted). Add a `can_decode` method to the class:

```python
class PydanticDecoder:
    """Decode raw response bytes into `model` via a cached `pydantic.TypeAdapter`."""

    def __init__(self) -> None:
        if not import_checker.is_pydantic_installed:
            raise ImportError(MISSING_DEPENDENCY_MESSAGE)

    def can_decode(self, model: type) -> bool:
        """True iff pydantic can build a schema for `model`.

        Cached via `_get_adapter`; subsequent calls (including `decode`) reuse
        the same `TypeAdapter` instance. Rejects `msgspec.Struct` subclasses —
        pydantic raises `PydanticSchemaGenerationError` (a `TypeError`) when
        building a schema for them.
        """
        try:
            _get_adapter(model)
        except Exception:  # noqa: BLE001 — can_decode is a probe; any failure means no
            return False
        return True

    def decode(self, content: bytes, model: type[T]) -> T:
        """Validate `content` as JSON against `model` in a single parse pass."""
        try:
            adapter = _get_adapter(model)
        except TypeError:
            adapter = TypeAdapter(model)
        return adapter.validate_json(content)
```

The `decode` method body is unchanged from the existing implementation; reproduced here so the engineer can see the file in its entirety after the edit. Only `can_decode` is genuinely new.

- [ ] **Step 5: Run the pydantic tests; verify pass**

```bash
uv run pytest tests/test_decoders_pydantic.py -v
```
Expected: all green, including new `can_decode` tests.

- [ ] **Step 6: Write the failing tests for `MsgspecDecoder.can_decode`**

Append to `tests/test_decoders_msgspec.py`:

```python
import dataclasses
import pydantic
from httpware.decoders.msgspec import MsgspecDecoder, _get_msgspec_decoder


class _PydanticUser(pydantic.BaseModel):
    id: int
    name: str


@dataclasses.dataclass
class _DC:
    id: int
    name: str


def test_msgspec_can_decode_struct() -> None:
    assert MsgspecDecoder().can_decode(_Item) is True


def test_msgspec_can_decode_dataclass() -> None:
    assert MsgspecDecoder().can_decode(_DC) is True


def test_msgspec_can_decode_dict() -> None:
    assert MsgspecDecoder().can_decode(dict) is True


def test_msgspec_can_decode_list_of_structs() -> None:
    assert MsgspecDecoder().can_decode(list[_Item]) is True


def test_msgspec_can_decode_primitive_int() -> None:
    assert MsgspecDecoder().can_decode(int) is True


def test_msgspec_rejects_pydantic_basemodel() -> None:
    assert MsgspecDecoder().can_decode(_PydanticUser) is False


def test_msgspec_can_decode_uses_cache() -> None:
    _get_msgspec_decoder.cache_clear()
    decoder = MsgspecDecoder()
    decoder.can_decode(_Item)
    decoder.can_decode(_Item)
    info = _get_msgspec_decoder.cache_info()
    assert info.hits >= 1
    assert info.misses == 1
```

`_Item` is already defined at the top of `tests/test_decoders_msgspec.py`; reuse it.

- [ ] **Step 7: Run the msgspec tests to verify they fail**

```bash
uv run pytest tests/test_decoders_msgspec.py -k can_decode -v
```
Expected: FAIL with `ImportError: cannot import name '_get_msgspec_decoder'` (because the helper doesn't exist yet).

- [ ] **Step 8: Implement `_get_msgspec_decoder` cache and `MsgspecDecoder.can_decode`**

Rewrite `src/httpware/decoders/msgspec.py`:

```python
"""MsgspecDecoder — opt-in ResponseDecoder backed by a cached msgspec.json.Decoder."""

import functools
from typing import TypeVar

from httpware._internal import import_checker


if import_checker.is_msgspec_installed:
    import msgspec


MISSING_DEPENDENCY_MESSAGE = "MsgspecDecoder requires the 'msgspec' extra. Install with: pip install httpware[msgspec]"

T = TypeVar("T")


@functools.lru_cache(maxsize=1024)
def _get_msgspec_decoder(model: type[T]) -> "msgspec.json.Decoder[T]":
    return msgspec.json.Decoder(model)


class MsgspecDecoder:
    """Decode raw response bytes via a cached `msgspec.json.Decoder(model)`.

    Requires the `msgspec` extra: `pip install httpware[msgspec]`. Importing
    this module without the extra works (the `msgspec` import is guarded by a
    `find_spec` check), but instantiating the decoder raises `ImportError`.
    """

    def __init__(self) -> None:
        if not import_checker.is_msgspec_installed:
            raise ImportError(MISSING_DEPENDENCY_MESSAGE)

    def can_decode(self, model: type) -> bool:
        """True iff msgspec can build a Decoder for `model`.

        Cached via `_get_msgspec_decoder`; subsequent calls reuse the same
        Decoder instance. Rejects `pydantic.BaseModel` subclasses — msgspec
        raises `TypeError` when building a Decoder for them.
        """
        try:
            _get_msgspec_decoder(model)
        except Exception:  # noqa: BLE001 — can_decode is a probe; any failure means no
            return False
        return True

    def decode(self, content: bytes, model: type[T]) -> T:
        """Validate `content` as JSON against `model` in a single parse pass."""
        try:
            decoder = _get_msgspec_decoder(model)
        except TypeError:
            decoder = msgspec.json.Decoder(model)
        return decoder.decode(content)
```

- [ ] **Step 9: Run the full decoder test suite**

```bash
uv run pytest tests/test_decoders_pydantic.py tests/test_decoders_msgspec.py -v
```
Expected: all green.

- [ ] **Step 10: Run lint and full test suite**

```bash
just lint && just test
```
Expected: green; 100% coverage maintained.

- [ ] **Step 11: Commit**

```bash
git add src/httpware/decoders/__init__.py src/httpware/decoders/pydantic.py src/httpware/decoders/msgspec.py tests/test_decoders_pydantic.py tests/test_decoders_msgspec.py
git commit -m "feat(decoders): add can_decode predicate to ResponseDecoder protocol"
```

---

### Task 2: Add `MissingDecoderError` and export it

**Files:**
- Modify: `src/httpware/errors.py`
- Modify: `src/httpware/__init__.py`
- Modify: `tests/test_errors.py`
- Modify: `tests/test_public_api.py`

Add the new exception below `DecodeError` in the hierarchy, export from the top-level package, cover via unit tests.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_errors.py`:

```python
import pickle

from httpware import MissingDecoderError


class _Foo:
    pass


def test_missing_decoder_error_carries_model() -> None:
    exc = MissingDecoderError(model=_Foo, registered_names=())
    assert exc.model is _Foo


def test_missing_decoder_error_carries_registered_names() -> None:
    exc = MissingDecoderError(model=_Foo, registered_names=("PydanticDecoder",))
    assert exc.registered_names == ("PydanticDecoder",)


def test_missing_decoder_error_no_registered_message() -> None:
    exc = MissingDecoderError(model=_Foo, registered_names=())
    msg = str(exc)
    assert "no decoders registered" in msg
    assert "httpware[pydantic]" in msg
    assert "httpware[msgspec]" in msg


def test_missing_decoder_error_single_registered_message() -> None:
    exc = MissingDecoderError(model=_Foo, registered_names=("PydanticDecoder",))
    assert "registered decoders (PydanticDecoder) all rejected" in str(exc)


def test_missing_decoder_error_two_registered_message() -> None:
    exc = MissingDecoderError(
        model=_Foo,
        registered_names=("PydanticDecoder", "MsgspecDecoder"),
    )
    assert "registered decoders (PydanticDecoder + MsgspecDecoder) all rejected" in str(exc)


def test_missing_decoder_error_is_client_error() -> None:
    from httpware import ClientError

    exc = MissingDecoderError(model=_Foo, registered_names=())
    assert isinstance(exc, ClientError)


def test_missing_decoder_error_pickle_roundtrip() -> None:
    exc = MissingDecoderError(
        model=_Foo,
        registered_names=("PydanticDecoder", "MsgspecDecoder"),
    )
    revived = pickle.loads(pickle.dumps(exc))
    assert revived.model is _Foo
    assert revived.registered_names == ("PydanticDecoder", "MsgspecDecoder")
```

Append to `tests/test_public_api.py`:

```python
def test_missing_decoder_error_exported() -> None:
    import httpware

    assert "MissingDecoderError" in httpware.__all__
    assert httpware.MissingDecoderError.__module__ == "httpware.errors"
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_errors.py::test_missing_decoder_error_carries_model -v
```
Expected: FAIL with `ImportError: cannot import name 'MissingDecoderError' from 'httpware'`.

- [ ] **Step 3: Add `MissingDecoderError` to `errors.py`**

Append to `src/httpware/errors.py`:

```python
def _missing_decoder_summary(model: type, registered_names: tuple[str, ...]) -> str:
    if not registered_names:
        hint = (
            "no decoders registered. Install `pip install httpware[pydantic]` "
            "or `pip install httpware[msgspec]`, or pass decoders=[...] explicitly."
        )
    else:
        joined = " + ".join(registered_names)
        hint = (
            f"registered decoders ({joined}) all rejected it. "
            f"Pass a custom decoder via decoders=[...]."
        )
    return f"no decoder for response_model={model!r}: {hint}"


def _reconstruct_missing_decoder(
    cls: "type[MissingDecoderError]",
    model: type,
    registered_names: tuple[str, ...],
) -> "MissingDecoderError":
    return cls(model=model, registered_names=registered_names)


class MissingDecoderError(ClientError):
    """Raised when response_model= is set but no registered decoder claims the model.

    Fires at .send() entry, BEFORE the HTTP call — no point sending a request
    whose response cannot be decoded. Distinct from DecodeError, which means
    the decoder ran and the payload was malformed.
    """

    model: type
    registered_names: tuple[str, ...]

    def __init__(self, *, model: type, registered_names: tuple[str, ...]) -> None:
        self.model = model
        self.registered_names = registered_names
        super().__init__(_missing_decoder_summary(model, registered_names))

    def __reduce__(self) -> tuple[Any, ...]:
        return (_reconstruct_missing_decoder, (type(self), self.model, self.registered_names))
```

- [ ] **Step 4: Export from top-level `httpware`**

Edit `src/httpware/__init__.py`. Add `MissingDecoderError` to the `from httpware.errors import (...)` block (alphabetical position after `InternalServerError`, before `NetworkError`):

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
    MissingDecoderError,
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

Add `"MissingDecoderError"` to `__all__` (alphabetical position after `"InternalServerError"`, before `"Middleware"`):

```python
__all__ = [
    "STATUS_TO_EXCEPTION",
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
    "InternalServerError",
    "Middleware",
    "MissingDecoderError",
    "NetworkError",
    "Next",
    "NotFoundError",
    "RateLimitedError",
    "ResponseDecoder",
    "Retry",
    "RetryBudget",
    "RetryBudgetExhaustedError",
    "ServerStatusError",
    "ServiceUnavailableError",
    "StatusError",
    "TimeoutError",
    "TransportError",
    "UnauthorizedError",
    "UnprocessableEntityError",
    "after_response",
    "async_after_response",
    "async_before_request",
    "async_on_error",
    "before_request",
    "on_error",
]
```

- [ ] **Step 5: Run the error tests**

```bash
uv run pytest tests/test_errors.py tests/test_public_api.py -v
```
Expected: all green.

- [ ] **Step 6: Run lint and full test suite**

```bash
just lint && just test
```
Expected: green; 100% coverage maintained.

- [ ] **Step 7: Commit**

```bash
git add src/httpware/errors.py src/httpware/__init__.py tests/test_errors.py tests/test_public_api.py
git commit -m "feat(errors): add MissingDecoderError raised by future multi-decoder dispatch"
```

---

### Task 3: Add `_build_default_decoders()` helper to `client.py`

**Files:**
- Modify: `src/httpware/client.py`
- Modify: `tests/test_client_construction.py`

Introduce the helper that probes installed extras and returns the default decoder tuple. Not yet wired into either client class — that happens in Tasks 4 and 5. The existing `_default_pydantic_decoder()` stays put alongside it until Task 5.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_client_construction.py`:

```python
from unittest.mock import patch

from httpware.client import _build_default_decoders
from httpware.decoders.pydantic import PydanticDecoder
from httpware.decoders.msgspec import MsgspecDecoder


def test_build_default_decoders_both_extras_installed() -> None:
    result = _build_default_decoders()
    assert len(result) == 2  # noqa: PLR2004
    assert isinstance(result[0], PydanticDecoder)
    assert isinstance(result[1], MsgspecDecoder)


def test_build_default_decoders_pydantic_only() -> None:
    with patch("httpware._internal.import_checker.is_msgspec_installed", False):
        result = _build_default_decoders()
    assert len(result) == 1
    assert isinstance(result[0], PydanticDecoder)


def test_build_default_decoders_msgspec_only() -> None:
    with patch("httpware._internal.import_checker.is_pydantic_installed", False):
        result = _build_default_decoders()
    assert len(result) == 1
    assert isinstance(result[0], MsgspecDecoder)


def test_build_default_decoders_neither_installed() -> None:
    with (
        patch("httpware._internal.import_checker.is_pydantic_installed", False),
        patch("httpware._internal.import_checker.is_msgspec_installed", False),
    ):
        result = _build_default_decoders()
    assert result == ()


def test_build_default_decoders_returns_tuple() -> None:
    result = _build_default_decoders()
    assert isinstance(result, tuple)
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_client_construction.py -k build_default_decoders -v
```
Expected: FAIL with `ImportError: cannot import name '_build_default_decoders' from 'httpware.client'`.

- [ ] **Step 3: Add `_build_default_decoders()` to `client.py`**

Edit `src/httpware/client.py`. After the existing `_default_pydantic_decoder` definition (around line 45), insert the new helper:

```python
def _build_default_decoders() -> tuple[ResponseDecoder, ...]:
    """Construct the default decoder tuple based on installed extras.

    Pydantic-first when both extras are present; either-only when only one is
    installed; empty tuple when neither is installed. Imports the concrete
    decoder modules lazily so missing extras never trip `find_spec`-guarded
    import paths. Called by `AsyncClient.__init__` and `Client.__init__` when
    `decoders=None` (the default).
    """
    decoders: list[ResponseDecoder] = []
    if import_checker.is_pydantic_installed:
        from httpware.decoders.pydantic import PydanticDecoder  # noqa: PLC0415 — lazy by design (Seam C)

        decoders.append(PydanticDecoder())
    if import_checker.is_msgspec_installed:
        from httpware.decoders.msgspec import MsgspecDecoder  # noqa: PLC0415 — lazy by design (Seam C)

        decoders.append(MsgspecDecoder())
    return tuple(decoders)
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
uv run pytest tests/test_client_construction.py -k build_default_decoders -v
```
Expected: all green.

- [ ] **Step 5: Run lint and full test suite**

```bash
just lint && just test
```
Expected: green; 100% coverage maintained (the new helper is fully covered by the four parametrized cases above).

- [ ] **Step 6: Commit**

```bash
git add src/httpware/client.py tests/test_client_construction.py
git commit -m "feat(client): add _build_default_decoders helper for installed-extras probe"
```

---

## Phase B — Wire it into the client

### Task 4: Migrate `AsyncClient` to `decoders=` + dispatch + pre-flight check

**Files:**
- Modify: `src/httpware/client.py` (AsyncClient class only)
- Modify: `tests/test_client_construction.py` (existing `_decoder` / `decoder=` references)
- Modify: `tests/test_client_response_model.py` (if any `decoder=` references)
- Modify: `tests/test_decoders_msgspec.py:66` (`decoder=MsgspecDecoder()` → `decoders=[MsgspecDecoder()]`)
- Modify: `tests/test_optional_extras_pydantic_missing.py` (invert async-client assertions; switch `decoder=` → `decoders=`)

This is the atomic refactor for the async surface. It must be one commit because the 100% coverage gate rejects any half-state. The sync `Client` keeps using `_default_pydantic_decoder()` until Task 5.

- [ ] **Step 1: Inventory the existing call sites that will break**

```bash
grep -n "decoder=\|client._decoder\b\|self\._decoder\b" src/httpware/client.py tests/ | grep -v __pycache__
```

Expected hits (must all be updated in this task for the AsyncClient code paths):
- `src/httpware/client.py:75` — attribute annotation `_decoder: ResponseDecoder`
- `src/httpware/client.py:90` — kwarg `decoder: ResponseDecoder | None = None`
- `src/httpware/client.py:126` — assignment `self._decoder = ... _default_pydantic_decoder()`
- `src/httpware/client.py:158` — `self._decoder.decode(...)` in `send`
- `src/httpware/client.py:179` — `self._decoder.decode(...)` in `send_with_response`
- `tests/test_client_construction.py:53` — `assert isinstance(client._decoder, PydanticDecoder)`
- `tests/test_client_construction.py:61` — `AsyncClient(decoder=_Stub())`
- `tests/test_client_construction.py:62` — `assert isinstance(client._decoder, _Stub)`
- `tests/test_decoders_msgspec.py:66` — `decoder=MsgspecDecoder()`
- `tests/test_optional_extras_pydantic_missing.py` — async-client cases

(Sync `Client` lines `:793`, `:808`, `:844`, `:900`, `:921` and `tests/test_client_sync.py:64,73-74` are deliberately left for Task 5.)

- [ ] **Step 2: Write the failing tests for the new AsyncClient behavior**

Edit `tests/test_client_construction.py`. Replace the existing `test_default_decoder_is_pydantic_decoder` and `test_explicit_decoder_is_honored` with their migrated versions:

```python
def test_default_decoders_includes_pydantic_when_installed() -> None:
    client = AsyncClient()
    assert any(isinstance(d, PydanticDecoder) for d in client._decoders)  # noqa: SLF001


def test_explicit_decoders_is_honored() -> None:
    class _Stub:
        def can_decode(self, model: type) -> bool:  # noqa: ARG002
            return True

        def decode(self, content: bytes, model: type) -> object:  # noqa: ARG002  # pragma: no cover
            return None

    stub = _Stub()
    client = AsyncClient(decoders=[stub])
    assert client._decoders == (stub,)  # noqa: SLF001


def test_empty_decoders_is_honored() -> None:
    client = AsyncClient(decoders=[])
    assert client._decoders == ()  # noqa: SLF001
```

Append a new test for pre-flight `MissingDecoderError`:

```python
async def test_missing_decoder_raised_before_http_call() -> None:
    """response_model with no claiming decoder raises before the transport is invoked."""
    import httpx2
    import pytest
    from httpware import MissingDecoderError

    def handler(_: httpx2.Request) -> httpx2.Response:
        pytest.fail("transport should not be invoked when MissingDecoderError fires")

    transport = httpx2.MockTransport(handler)
    client = AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=transport),
        decoders=[],
    )

    class _Foo:
        pass

    with pytest.raises(MissingDecoderError) as exc_info:
        await client.get("https://example.test/x", response_model=_Foo)
    assert exc_info.value.model is _Foo
    assert exc_info.value.registered_names == ()
```

Edit `tests/test_decoders_msgspec.py`, line 66 region:

```python
    transport = httpx2.MockTransport(handler)
    client = AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=transport),
        decoders=[MsgspecDecoder()],
    )
```

Edit `tests/test_optional_extras_pydantic_missing.py`. Replace the two `*_default_decoder_raises_when_pydantic_missing` tests and the `*_accepts_explicit_decoder_without_pydantic` tests with:

```python
def test_async_client_no_pydantic_constructs_without_raising() -> None:
    """AsyncClient() with pydantic missing must not raise — lazy default policy."""
    with patch("httpware._internal.import_checker.is_pydantic_installed", False):
        client = AsyncClient()
    assert all(not isinstance(d, PydanticDecoder) for d in client._decoders)  # noqa: SLF001


def test_async_client_accepts_explicit_decoders_without_pydantic() -> None:
    """An explicit decoders= list is honored regardless of pydantic install state."""
    fake = _FakeDecoder()
    with patch("httpware._internal.import_checker.is_pydantic_installed", False):
        client = AsyncClient(decoders=[fake])
    assert client._decoders == (fake,)  # noqa: SLF001
```

Update `_FakeDecoder` in that file to satisfy the new Protocol:

```python
class _FakeDecoder:
    """Test stand-in for ResponseDecoder; never called at runtime."""

    def can_decode(self, model: type) -> bool:  # noqa: ARG002
        return True

    def decode(self, content: bytes, model: type) -> object:  # noqa: ARG002 — name pinned by ResponseDecoder protocol
        return model()  # pragma: no cover
```

Leave the sync `Client` cases (`test_sync_client_*`) UNCHANGED — they still exercise the old `_default_pydantic_decoder()` path until Task 5. Same for `test_pydantic_decoder_init_raises_when_pydantic_missing` (it tests `PydanticDecoder()` directly, which still raises).

- [ ] **Step 3: Run the tests to verify they fail**

```bash
uv run pytest tests/test_client_construction.py tests/test_optional_extras_pydantic_missing.py tests/test_decoders_msgspec.py -v
```
Expected: failures referencing `_decoders` attribute missing, `decoders=` kwarg unknown, etc.

- [ ] **Step 4: Refactor `AsyncClient` in `src/httpware/client.py`**

Update imports at top of `client.py` — add `MissingDecoderError`:

```python
from httpware.errors import DecodeError, MissingDecoderError, TransportError
```

Replace the AsyncClient attribute block (currently `client.py:73-77`):

```python
class AsyncClient:
    """Async HTTP client: thin wrapper around httpx2 with typed decoding and middleware."""

    _httpx2_client: httpx2.AsyncClient
    _owns_client: bool
    _decoders: tuple[ResponseDecoder, ...]
    _user_middleware: tuple[AsyncMiddleware, ...]
    _dispatch: AsyncNext
```

Replace the `__init__` signature and body (currently `client.py:79-128`). Change the `decoder` kwarg to `decoders` and the assignment:

```python
    def __init__(  # noqa: PLR0913 — wide constructor is the cost of a single-call API
        self,
        *,
        base_url: str = "",
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
        cookies: dict[str, str] | None = None,
        timeout: httpx2.Timeout | float | None = None,
        limits: httpx2.Limits | None = None,
        auth: httpx2.Auth | None = None,
        httpx2_client: httpx2.AsyncClient | None = None,
        decoders: Sequence[ResponseDecoder] | None = None,
        middleware: Sequence[AsyncMiddleware] = (),
    ) -> None:
        if httpx2_client is not None:
            forwarded = {
                "base_url": base_url,
                "headers": headers,
                "params": params,
                "cookies": cookies,
                "timeout": timeout,
                "limits": limits,
                "auth": auth,
            }
            if any(value not in (None, "") for value in forwarded.values()):
                raise TypeError(_HTTPX2_CLIENT_CONFLICT_MESSAGE)
            self._httpx2_client = httpx2_client
            self._owns_client = False
        else:
            kwargs: dict[str, typing.Any] = {}
            if base_url:
                kwargs["base_url"] = base_url
            if headers is not None:
                kwargs["headers"] = headers
            if params is not None:
                kwargs["params"] = params
            if cookies is not None:
                kwargs["cookies"] = cookies
            if timeout is not None:
                kwargs["timeout"] = timeout
            if limits is not None:
                kwargs["limits"] = limits
            if auth is not None:
                kwargs["auth"] = auth
            self._httpx2_client = httpx2.AsyncClient(**kwargs)
            self._owns_client = True

        self._decoders = tuple(decoders) if decoders is not None else _build_default_decoders()
        self._user_middleware = tuple(middleware)
        self._dispatch = compose_async(self._user_middleware, self._terminal)
```

Add a private dispatcher method on `AsyncClient` (insert immediately before `_terminal`, around `client.py:130`):

```python
    def _dispatch_decoder(self, model: type) -> ResponseDecoder | None:
        """Walk `_decoders` and return the first decoder claiming `model`, or None."""
        for decoder in self._decoders:
            if decoder.can_decode(model):
                return decoder
        return None
```

Rewrite `AsyncClient.send` (currently `client.py:147-160`):

```python
    async def send(
        self,
        request: httpx2.Request,
        *,
        response_model: type[T] | None = None,
    ) -> httpx2.Response | T:
        """Send `request` through the middleware chain. Decode if `response_model` is set."""
        decoder: ResponseDecoder | None = None
        if response_model is not None:
            decoder = self._dispatch_decoder(response_model)
            if decoder is None:
                raise MissingDecoderError(
                    model=response_model,
                    registered_names=tuple(type(d).__name__ for d in self._decoders),
                )

        response = await self._dispatch(request)
        if decoder is None:
            return response
        try:
            return decoder.decode(response.content, response_model)
        except Exception as exc:
            raise DecodeError(response=response, model=response_model, original=exc) from exc
```

Rewrite `AsyncClient.send_with_response` (currently `client.py:162-182`):

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
        decoder = self._dispatch_decoder(response_model)
        if decoder is None:
            raise MissingDecoderError(
                model=response_model,
                registered_names=tuple(type(d).__name__ for d in self._decoders),
            )

        response = await self._dispatch(request)
        try:
            decoded = decoder.decode(response.content, response_model)
        except Exception as exc:
            raise DecodeError(response=response, model=response_model, original=exc) from exc
        return response, decoded
```

- [ ] **Step 5: Run the targeted test files**

```bash
uv run pytest tests/test_client_construction.py tests/test_client_response_model.py tests/test_client_send_with_response.py tests/test_decoders_msgspec.py tests/test_optional_extras_pydantic_missing.py -v
```
Expected: green.

- [ ] **Step 6: Run lint and full test suite**

```bash
just lint && just test
```
Expected: green; 100% coverage maintained.

If coverage drops below 100, the most likely cause is dead branches in `send_with_response` or a missed test for `_dispatch_decoder` returning `None`. The new `test_missing_decoder_raised_before_http_call` covers the `send` path; add a parallel test for `send_with_response` if coverage flags it:

```python
async def test_send_with_response_raises_missing_decoder_before_http_call() -> None:
    import httpx2
    import pytest
    from httpware import MissingDecoderError

    def handler(_: httpx2.Request) -> httpx2.Response:
        pytest.fail("transport should not be invoked when MissingDecoderError fires")

    transport = httpx2.MockTransport(handler)
    client = AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=transport),
        decoders=[],
    )

    class _Foo:
        pass

    request = client.build_request("GET", "https://example.test/x")
    with pytest.raises(MissingDecoderError):
        await client.send_with_response(request, response_model=_Foo)
```

Add this to `tests/test_client_send_with_response.py`.

- [ ] **Step 7: Commit**

```bash
git add src/httpware/client.py tests/test_client_construction.py tests/test_client_response_model.py tests/test_client_send_with_response.py tests/test_decoders_msgspec.py tests/test_optional_extras_pydantic_missing.py
git commit -m "feat(client)!: AsyncClient takes decoders=[...] with type-dispatched routing"
```

The `!` after `feat(client)` flags the breaking surface change for release-notes tooling.

---

### Task 5: Migrate sync `Client` (mirror Task 4) and delete the old default helper

**Files:**
- Modify: `src/httpware/client.py` (sync Client class + delete `_default_pydantic_decoder` and `_DEFAULT_DECODER_MISSING_MESSAGE`)
- Modify: `src/httpware/decoders/pydantic.py` (update module docstring to remove the stale `client.py:_default_pydantic_decoder()` reference)
- Modify: `tests/test_client_sync.py` (existing `_decoder` / `decoder=` references)
- Modify: `tests/test_optional_extras_pydantic_missing.py` (mirror sync invert)
- Modify: `tests/test_client_send_with_response_sync.py` (`MissingDecoderError` sync case)

Now that the AsyncClient is fully migrated, repeat the surgery on the sync class and delete the now-unused `_default_pydantic_decoder`.

- [ ] **Step 1: Write the failing tests**

Edit `tests/test_client_sync.py`. Replace `test_default_decoder_is_pydantic_decoder` and `test_explicit_decoder_is_honored` with their migrated versions:

```python
def test_default_decoders_includes_pydantic_when_installed() -> None:
    client = Client()
    assert any(isinstance(d, PydanticDecoder) for d in client._decoders)  # noqa: SLF001
    client.close()


def test_explicit_decoders_is_honored() -> None:
    class _Stub:
        def can_decode(self, model: type) -> bool:  # noqa: ARG002
            return True

        def decode(self, content: bytes, model: type) -> object:  # noqa: ARG002  # pragma: no cover
            return None

    stub = _Stub()
    client = Client(decoders=[stub])
    assert client._decoders == (stub,)  # noqa: SLF001
    client.close()


def test_empty_decoders_is_honored() -> None:
    client = Client(decoders=[])
    assert client._decoders == ()  # noqa: SLF001
    client.close()


def test_sync_missing_decoder_raised_before_http_call() -> None:
    import httpx2
    import pytest
    from httpware import MissingDecoderError

    def handler(_: httpx2.Request) -> httpx2.Response:
        pytest.fail("transport should not be invoked when MissingDecoderError fires")

    transport = httpx2.MockTransport(handler)
    client = Client(
        httpx2_client=httpx2.Client(transport=transport),
        decoders=[],
    )

    class _Foo:
        pass

    with pytest.raises(MissingDecoderError) as exc_info:
        client.get("https://example.test/x", response_model=_Foo)
    assert exc_info.value.model is _Foo
    assert exc_info.value.registered_names == ()
    client.close()
```

In `tests/test_optional_extras_pydantic_missing.py`, replace the sync-client cases:

```python
def test_sync_client_no_pydantic_constructs_without_raising() -> None:
    """Client() with pydantic missing must not raise — lazy default policy."""
    with patch("httpware._internal.import_checker.is_pydantic_installed", False):
        client = Client()
    assert all(not isinstance(d, PydanticDecoder) for d in client._decoders)  # noqa: SLF001
    client.close()


def test_sync_client_accepts_explicit_decoders_without_pydantic() -> None:
    fake = _FakeDecoder()
    with patch("httpware._internal.import_checker.is_pydantic_installed", False):
        client = Client(decoders=[fake])
    assert client._decoders == (fake,)  # noqa: SLF001
    client.close()
```

Append to `tests/test_client_send_with_response_sync.py`:

```python
def test_sync_send_with_response_raises_missing_decoder_before_http_call() -> None:
    import httpx2
    import pytest
    from httpware import Client, MissingDecoderError

    def handler(_: httpx2.Request) -> httpx2.Response:
        pytest.fail("transport should not be invoked when MissingDecoderError fires")

    transport = httpx2.MockTransport(handler)
    client = Client(
        httpx2_client=httpx2.Client(transport=transport),
        decoders=[],
    )

    class _Foo:
        pass

    request = client.build_request("GET", "https://example.test/x")
    with pytest.raises(MissingDecoderError):
        client.send_with_response(request, response_model=_Foo)
    client.close()
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_client_sync.py tests/test_client_send_with_response_sync.py tests/test_optional_extras_pydantic_missing.py -v
```
Expected: failures referencing `_decoders` and `decoders=` on the sync class.

- [ ] **Step 3: Refactor sync `Client` in `src/httpware/client.py`**

Update the `Client` attribute block (currently `client.py:791-795`):

```python
class Client:
    """Sync HTTP client: thin wrapper around httpx2 with typed decoding and middleware."""

    _httpx2_client: httpx2.Client
    _owns_client: bool
    _decoders: tuple[ResponseDecoder, ...]
    _user_middleware: tuple[Middleware, ...]
    _dispatch: Next
```

Update the `Client.__init__` signature and body (currently `client.py:797-846`):

```python
    def __init__(  # noqa: PLR0913 — wide constructor is the cost of a single-call API
        self,
        *,
        base_url: str = "",
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
        cookies: dict[str, str] | None = None,
        timeout: httpx2.Timeout | float | None = None,
        limits: httpx2.Limits | None = None,
        auth: httpx2.Auth | None = None,
        httpx2_client: httpx2.Client | None = None,
        decoders: Sequence[ResponseDecoder] | None = None,
        middleware: Sequence[Middleware] = (),
    ) -> None:
        if httpx2_client is not None:
            forwarded = {
                "base_url": base_url,
                "headers": headers,
                "params": params,
                "cookies": cookies,
                "timeout": timeout,
                "limits": limits,
                "auth": auth,
            }
            if any(value not in (None, "") for value in forwarded.values()):
                raise TypeError(_HTTPX2_CLIENT_CONFLICT_MESSAGE)
            self._httpx2_client = httpx2_client
            self._owns_client = False
        else:
            kwargs: dict[str, typing.Any] = {}
            if base_url:
                kwargs["base_url"] = base_url
            if headers is not None:
                kwargs["headers"] = headers
            if params is not None:
                kwargs["params"] = params
            if cookies is not None:
                kwargs["cookies"] = cookies
            if timeout is not None:
                kwargs["timeout"] = timeout
            if limits is not None:
                kwargs["limits"] = limits
            if auth is not None:
                kwargs["auth"] = auth
            self._httpx2_client = httpx2.Client(**kwargs)
            self._owns_client = True

        self._decoders = tuple(decoders) if decoders is not None else _build_default_decoders()
        self._user_middleware = tuple(middleware)
        self._dispatch = compose(self._user_middleware, self._terminal)
```

Add `_dispatch_decoder` on `Client` (insert immediately before `_terminal`, around `client.py:848`):

```python
    def _dispatch_decoder(self, model: type) -> ResponseDecoder | None:
        """Walk `_decoders` and return the first decoder claiming `model`, or None."""
        for decoder in self._decoders:
            if decoder.can_decode(model):
                return decoder
        return None
```

Rewrite `Client.send` (currently `client.py:889-902`):

```python
    def send(
        self,
        request: httpx2.Request,
        *,
        response_model: type[T] | None = None,
    ) -> httpx2.Response | T:
        """Send `request` through the middleware chain. Decode if `response_model` is set."""
        decoder: ResponseDecoder | None = None
        if response_model is not None:
            decoder = self._dispatch_decoder(response_model)
            if decoder is None:
                raise MissingDecoderError(
                    model=response_model,
                    registered_names=tuple(type(d).__name__ for d in self._decoders),
                )

        response = self._dispatch(request)
        if decoder is None:
            return response
        try:
            return decoder.decode(response.content, response_model)
        except Exception as exc:
            raise DecodeError(response=response, model=response_model, original=exc) from exc
```

Rewrite `Client.send_with_response` (currently `client.py:904-924`):

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
        decoder = self._dispatch_decoder(response_model)
        if decoder is None:
            raise MissingDecoderError(
                model=response_model,
                registered_names=tuple(type(d).__name__ for d in self._decoders),
            )

        response = self._dispatch(request)
        try:
            decoded = decoder.decode(response.content, response_model)
        except Exception as exc:
            raise DecodeError(response=response, model=response_model, original=exc) from exc
        return response, decoded
```

Delete `_default_pydantic_decoder` and `_DEFAULT_DECODER_MISSING_MESSAGE` (currently `client.py:33-45`). Both are now unused.

- [ ] **Step 4: Update the now-stale docstring in `src/httpware/decoders/pydantic.py`**

The module docstring still references `client.py:_default_pydantic_decoder()`, which this task just deleted. Replace the docstring with:

```python
"""PydanticDecoder — module-level cached TypeAdapter adapter for ResponseDecoder.

Requires the `pydantic` extra: `pip install httpware[pydantic]`. Constructing
`PydanticDecoder()` directly when pydantic is not installed raises ImportError.
The default-decoder path in `client.py:_build_default_decoders()` skips this
class entirely when `is_pydantic_installed` is False, so `AsyncClient()` does
not trip the ImportError when the user is not using `response_model=`.
"""
```

- [ ] **Step 5: Run the sync tests**

```bash
uv run pytest tests/test_client_sync.py tests/test_client_send_with_response_sync.py tests/test_optional_extras_pydantic_missing.py -v
```
Expected: green.

- [ ] **Step 6: Run lint and full test suite**

```bash
just lint && just test
```
Expected: green; 100% coverage maintained.

If coverage drops, the most likely cause is leftover unused code from `_default_pydantic_decoder` deletion. Search the diff:

```bash
git diff src/httpware/client.py | grep -E '^-' | grep -i decoder
```

Confirm nothing references the deleted helper.

- [ ] **Step 7: Commit**

```bash
git add src/httpware/client.py src/httpware/decoders/pydantic.py tests/test_client_sync.py tests/test_client_send_with_response_sync.py tests/test_optional_extras_pydantic_missing.py
git commit -m "feat(client)!: sync Client takes decoders=[...] with type-dispatched routing"
```

---

## Phase C — New integration test files

### Task 6: `tests/test_client_decoders_default.py`

**Files:**
- Create: `tests/test_client_decoders_default.py`

Dedicated coverage of the default-decoder resolution matrix from the spec, exercising both async and sync clients across all extras-installed combinations.

- [ ] **Step 1: Create the test file**

Write `tests/test_client_decoders_default.py`:

```python
"""Default decoder resolution under varying extras-installed states.

Covers the behavior matrix in planning/specs/2026-06-09-multi-decoder-design.md
— `AsyncClient()` / `Client()` resolve `decoders=None` against the
`import_checker` flags at __init__ time.
"""

from unittest.mock import patch

from httpware import AsyncClient, Client
from httpware.decoders.msgspec import MsgspecDecoder
from httpware.decoders.pydantic import PydanticDecoder


def test_async_default_both_extras_installed() -> None:
    client = AsyncClient()
    types = tuple(type(d) for d in client._decoders)  # noqa: SLF001
    assert types == (PydanticDecoder, MsgspecDecoder)


def test_async_default_pydantic_only() -> None:
    with patch("httpware._internal.import_checker.is_msgspec_installed", False):
        client = AsyncClient()
    types = tuple(type(d) for d in client._decoders)  # noqa: SLF001
    assert types == (PydanticDecoder,)


def test_async_default_msgspec_only() -> None:
    with patch("httpware._internal.import_checker.is_pydantic_installed", False):
        client = AsyncClient()
    types = tuple(type(d) for d in client._decoders)  # noqa: SLF001
    assert types == (MsgspecDecoder,)


def test_async_default_neither_installed() -> None:
    with (
        patch("httpware._internal.import_checker.is_pydantic_installed", False),
        patch("httpware._internal.import_checker.is_msgspec_installed", False),
    ):
        client = AsyncClient()
    assert client._decoders == ()  # noqa: SLF001


def test_async_empty_explicit_decoders() -> None:
    client = AsyncClient(decoders=[])
    assert client._decoders == ()  # noqa: SLF001


def test_async_explicit_decoders_skip_default_probe() -> None:
    class _Custom:
        def can_decode(self, model: type) -> bool:  # noqa: ARG002
            return True

        def decode(self, content: bytes, model: type) -> object:  # noqa: ARG002  # pragma: no cover
            return None

    custom = _Custom()
    with (
        patch("httpware._internal.import_checker.is_pydantic_installed", False),
        patch("httpware._internal.import_checker.is_msgspec_installed", False),
    ):
        client = AsyncClient(decoders=[custom])
    assert client._decoders == (custom,)  # noqa: SLF001


def test_sync_default_both_extras_installed() -> None:
    client = Client()
    types = tuple(type(d) for d in client._decoders)  # noqa: SLF001
    assert types == (PydanticDecoder, MsgspecDecoder)
    client.close()


def test_sync_default_pydantic_only() -> None:
    with patch("httpware._internal.import_checker.is_msgspec_installed", False):
        client = Client()
    types = tuple(type(d) for d in client._decoders)  # noqa: SLF001
    assert types == (PydanticDecoder,)
    client.close()


def test_sync_default_msgspec_only() -> None:
    with patch("httpware._internal.import_checker.is_pydantic_installed", False):
        client = Client()
    types = tuple(type(d) for d in client._decoders)  # noqa: SLF001
    assert types == (MsgspecDecoder,)
    client.close()


def test_sync_default_neither_installed() -> None:
    with (
        patch("httpware._internal.import_checker.is_pydantic_installed", False),
        patch("httpware._internal.import_checker.is_msgspec_installed", False),
    ):
        client = Client()
    assert client._decoders == ()  # noqa: SLF001
    client.close()


def test_sync_empty_explicit_decoders() -> None:
    client = Client(decoders=[])
    assert client._decoders == ()  # noqa: SLF001
    client.close()
```

- [ ] **Step 2: Run the new test file**

```bash
uv run pytest tests/test_client_decoders_default.py -v
```
Expected: all green (the runtime is already in place after Tasks 4 and 5).

- [ ] **Step 3: Run lint and full test suite**

```bash
just lint && just test
```
Expected: green; 100% coverage maintained.

- [ ] **Step 4: Commit**

```bash
git add tests/test_client_decoders_default.py
git commit -m "test(client): cover default-decoder resolution matrix for both clients"
```

---

### Task 7: `tests/test_client_dispatch.py`

**Files:**
- Create: `tests/test_client_dispatch.py`

Dedicated coverage of the dispatch routing — which decoder handles which model under varying decoder lists, including the order-flips-shared-shape and native-types-route-correctly cases.

- [ ] **Step 1: Create the test file**

Write `tests/test_client_dispatch.py`:

```python
"""Dispatch routing across multiple registered decoders.

Covers the routing examples in planning/specs/2026-06-09-multi-decoder-design.md
§ Architecture — native types route via their library regardless of order,
shared shapes route to the first decoder in the list.
"""

import dataclasses
from http import HTTPStatus

import httpx2
import msgspec
import pydantic
import pytest

from httpware import AsyncClient, Client, MissingDecoderError
from httpware.decoders.msgspec import MsgspecDecoder
from httpware.decoders.pydantic import PydanticDecoder


class _PydanticUser(pydantic.BaseModel):
    id: int
    name: str


class _MsgspecUser(msgspec.Struct):
    id: int
    name: str


@dataclasses.dataclass
class _DC:
    id: int
    name: str


def _async_client_with_body(payload: bytes, decoders: list) -> AsyncClient:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(HTTPStatus.OK, content=payload, request=request)

    transport = httpx2.MockTransport(handler)
    return AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=transport),
        decoders=decoders,
    )


def _sync_client_with_body(payload: bytes, decoders: list) -> Client:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(HTTPStatus.OK, content=payload, request=request)

    transport = httpx2.MockTransport(handler)
    return Client(
        httpx2_client=httpx2.Client(transport=transport),
        decoders=decoders,
    )


async def test_async_basemodel_routes_to_pydantic() -> None:
    client = _async_client_with_body(
        b'{"id": 1, "name": "Ada"}',
        decoders=[PydanticDecoder(), MsgspecDecoder()],
    )
    result = await client.get("https://example.test/x", response_model=_PydanticUser)
    assert type(result) is _PydanticUser
    assert result.id == 1


async def test_async_struct_routes_to_msgspec() -> None:
    client = _async_client_with_body(
        b'{"id": 1, "name": "Ada"}',
        decoders=[PydanticDecoder(), MsgspecDecoder()],
    )
    result = await client.get("https://example.test/x", response_model=_MsgspecUser)
    assert type(result) is _MsgspecUser
    assert result.id == 1


async def test_async_dict_routes_to_first_decoder() -> None:
    """Shared shape: first decoder in the list wins."""
    pyd = PydanticDecoder()
    msg = MsgspecDecoder()
    client = _async_client_with_body(b'{"a": 1}', decoders=[pyd, msg])
    result = await client.get("https://example.test/x", response_model=dict[str, int])
    assert type(result) is dict
    assert result == {"a": 1}


async def test_async_dict_routes_to_msgspec_when_first() -> None:
    """Reversed list flips routing for shared shapes."""
    client = _async_client_with_body(
        b'{"a": 1}',
        decoders=[MsgspecDecoder(), PydanticDecoder()],
    )
    result = await client.get("https://example.test/x", response_model=dict[str, int])
    assert result == {"a": 1}


async def test_async_dataclass_routes_to_first_decoder() -> None:
    client = _async_client_with_body(
        b'{"id": 1, "name": "Ada"}',
        decoders=[PydanticDecoder(), MsgspecDecoder()],
    )
    result = await client.get("https://example.test/x", response_model=_DC)
    assert type(result) is _DC
    assert result.id == 1


async def test_async_list_of_basemodel_routes_to_pydantic() -> None:
    client = _async_client_with_body(
        b'[{"id": 1, "name": "Ada"}, {"id": 2, "name": "Bo"}]',
        decoders=[PydanticDecoder(), MsgspecDecoder()],
    )
    result = await client.get("https://example.test/x", response_model=list[_PydanticUser])
    assert len(result) == 2  # noqa: PLR2004
    assert all(type(item) is _PydanticUser for item in result)


async def test_async_missing_decoder_with_empty_list() -> None:
    """Empty decoder list and response_model= raises before HTTP call."""

    def handler(_: httpx2.Request) -> httpx2.Response:
        pytest.fail("transport should not be invoked")

    transport = httpx2.MockTransport(handler)
    client = AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=transport),
        decoders=[],
    )
    with pytest.raises(MissingDecoderError) as exc_info:
        await client.get("https://example.test/x", response_model=_PydanticUser)
    assert exc_info.value.registered_names == ()


async def test_async_missing_decoder_when_none_claim() -> None:
    """Registered decoders that all reject the model raise MissingDecoderError."""

    class _Stub:
        def can_decode(self, model: type) -> bool:  # noqa: ARG002
            return False

        def decode(self, content: bytes, model: type) -> object:  # noqa: ARG002  # pragma: no cover
            return None

    def handler(_: httpx2.Request) -> httpx2.Response:
        pytest.fail("transport should not be invoked")

    transport = httpx2.MockTransport(handler)
    client = AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=transport),
        decoders=[_Stub()],
    )
    with pytest.raises(MissingDecoderError) as exc_info:
        await client.get("https://example.test/x", response_model=_PydanticUser)
    assert exc_info.value.registered_names == ("_Stub",)


def test_sync_basemodel_routes_to_pydantic() -> None:
    client = _sync_client_with_body(
        b'{"id": 1, "name": "Ada"}',
        decoders=[PydanticDecoder(), MsgspecDecoder()],
    )
    result = client.get("https://example.test/x", response_model=_PydanticUser)
    assert type(result) is _PydanticUser
    client.close()


def test_sync_struct_routes_to_msgspec() -> None:
    client = _sync_client_with_body(
        b'{"id": 1, "name": "Ada"}',
        decoders=[PydanticDecoder(), MsgspecDecoder()],
    )
    result = client.get("https://example.test/x", response_model=_MsgspecUser)
    assert type(result) is _MsgspecUser
    client.close()


def test_sync_dict_routes_to_first_decoder() -> None:
    client = _sync_client_with_body(
        b'{"a": 1}',
        decoders=[PydanticDecoder(), MsgspecDecoder()],
    )
    result = client.get("https://example.test/x", response_model=dict[str, int])
    assert result == {"a": 1}
    client.close()


def test_sync_dict_routes_to_msgspec_when_first() -> None:
    client = _sync_client_with_body(
        b'{"a": 1}',
        decoders=[MsgspecDecoder(), PydanticDecoder()],
    )
    result = client.get("https://example.test/x", response_model=dict[str, int])
    assert result == {"a": 1}
    client.close()


def test_sync_missing_decoder_with_empty_list() -> None:
    def handler(_: httpx2.Request) -> httpx2.Response:
        pytest.fail("transport should not be invoked")

    transport = httpx2.MockTransport(handler)
    client = Client(
        httpx2_client=httpx2.Client(transport=transport),
        decoders=[],
    )
    with pytest.raises(MissingDecoderError):
        client.get("https://example.test/x", response_model=_PydanticUser)
    client.close()
```

- [ ] **Step 2: Run the new test file**

```bash
uv run pytest tests/test_client_dispatch.py -v
```
Expected: all green.

- [ ] **Step 3: Run lint and full test suite**

```bash
just lint && just test
```
Expected: green; 100% coverage maintained.

- [ ] **Step 4: Commit**

```bash
git add tests/test_client_dispatch.py
git commit -m "test(client): cover type-dispatched decoder routing across both clients"
```

---

## Phase D — Docs and engineering notes

### Task 8: Update `README.md`, `docs/index.md`, and `docs/errors.md`

**Files:**
- Modify: `README.md`
- Modify: `docs/index.md`
- Modify: `docs/errors.md`

User-facing narrative for the new `decoders=` shape and the new `MissingDecoderError`.

- [ ] **Step 1: Update `README.md`**

`README.md:23` currently says:

```markdown
`AsyncClient()` with no `decoder=` argument defaults to constructing a `PydanticDecoder`; that path requires the `pydantic` extra and raises `ImportError` at `AsyncClient.__init__` if it is missing.
```

Replace with:

```markdown
`AsyncClient()` resolves `decoders=None` against installed extras: pydantic if installed (first), msgspec if installed (second), or an empty tuple if neither. `AsyncClient()` never raises on missing extras — failure is deferred to the first `response_model=` call, where `MissingDecoderError` fires *before* the HTTP request if no registered decoder claims the model.
```

Search for any other `decoder=` mentions in `README.md` and rename to `decoders=[...]`:

```bash
grep -n "decoder=" README.md
```

Update each hit to use the plural list form.

- [ ] **Step 2: Update `docs/index.md`**

Current install/quickstart blurb (around the install section):

```markdown
pip install httpware[pydantic]   # PydanticDecoder (the default decoder path)
pip install httpware[msgspec]    # MsgspecDecoder
```

Replace with:

```markdown
pip install httpware[pydantic]   # PydanticDecoder — handles BaseModel + dataclasses + primitives + generics
pip install httpware[msgspec]    # MsgspecDecoder — handles Struct + dataclasses + primitives + generics
pip install httpware[pydantic,msgspec]   # both extras — both decoders register; BaseModel routes to pydantic, Struct to msgspec
```

Find and update any `decoder=` call sites in `docs/index.md`:

```bash
grep -n "decoder=" docs/index.md
```

Replace each with `decoders=[...]`.

Add a short subsection on the dispatch order (insert after the existing "Typed decoding via `response_model=`" subsection):

````markdown
### Decoder dispatch

When `response_model=` is set, the client walks `decoders` in order and picks
the first decoder whose `can_decode(model)` returns `True`. Both built-in
decoders claim broadly within their library; the ordering encodes your
preference for shared shapes (`dict`, `list[Foo]`, dataclasses, primitives):

```python
# pydantic-first (the default when both extras are installed):
# - BaseModel  -> pydantic
# - Struct     -> msgspec
# - dict, list -> pydantic (first in list)
AsyncClient(decoders=[PydanticDecoder(), MsgspecDecoder()])

# msgspec-first — same native routing, but shared shapes go to msgspec:
# - BaseModel  -> pydantic
# - Struct     -> msgspec
# - dict, list -> msgspec
AsyncClient(decoders=[MsgspecDecoder(), PydanticDecoder()])
```

If no registered decoder claims your `response_model`, the call raises
`MissingDecoderError` *before* the HTTP request — see the
[Errors reference](errors.md#missingdecodererror).
````

- [ ] **Step 3: Update `docs/errors.md`**

Find the tree section. The existing entry for `DecodeError` looks like:

```markdown
- **Decode errors** — `DecodeError`, raised when `response_model=` decoding fails (HTTP call itself succeeded).
```

Add a sibling bullet next to it:

```markdown
- **Decode errors** — `DecodeError`, raised when `response_model=` decoding fails (HTTP call itself succeeded). `MissingDecoderError`, raised when no registered decoder claims the `response_model=` type — fires *before* the HTTP call.
```

Then in the per-exception reference body, add a section for `MissingDecoderError` next to the `DecodeError` entry:

```markdown
### `MissingDecoderError`

Raised by `send()` / `send_with_response()` / verb methods when `response_model=` is set but no registered decoder claims the model. Carries:

- `model: type` — the `response_model=` value that wasn't claimed.
- `registered_names: tuple[str, ...]` — class names of the registered decoders that all rejected the model. Empty tuple means no decoders were registered.

Corrective action depends on the message hint:

- `no decoders registered. Install pip install httpware[pydantic] or pip install httpware[msgspec], or pass decoders=[...] explicitly.` — install an extra or pass an explicit decoder list.
- `registered decoders (PydanticDecoder + MsgspecDecoder) all rejected it.` — your `response_model` type is exotic enough that neither built-in claims it. Pass a custom `ResponseDecoder` via `decoders=[...]`.

Unlike `DecodeError`, this error fires *before* the HTTP request — no traffic is sent.
```

- [ ] **Step 4: Verify rendered docs build (if mkdocs is set up locally)**

```bash
ls mkdocs.yml 2>/dev/null && uv run --extra docs mkdocs build --strict 2>&1 | tail -20 || echo "mkdocs not configured locally — skip"
```

If mkdocs builds, check the build output for `WARNING` lines on the new content.

- [ ] **Step 5: Run lint and full test suite**

```bash
just lint && just test
```
Expected: green (no code change in this task).

- [ ] **Step 6: Commit**

```bash
git add README.md docs/index.md docs/errors.md
git commit -m "docs: rewrite decoder narrative for multi-decoder routing"
```

---

### Task 9: Update `planning/engineering.md` Seam B description

**Files:**
- Modify: `planning/engineering.md`

Update the canonical engineering reference so future contributors find the new Seam B contract.

- [ ] **Step 1: Locate the Seam B section**

```bash
grep -n "Seam B" planning/engineering.md
```

The current Seam B description (from the spec preamble) reads:

> Seam B — Client/AsyncClient ↔ ResponseDecoder — called when response_model is provided. Signature: decode(content: bytes, model: type[T]) -> T. Implementations of both send methods call the decoder identically.

- [ ] **Step 2: Replace with the new Seam B description**

Find the matching paragraph (likely in a numbered list near a heading like "Protocol seams" or "Internal seams") and replace it with:

```markdown
2. **Seam B** — `Client`/`AsyncClient` ↔ `ResponseDecoder` list — `_decoders: tuple[ResponseDecoder, ...]` composed at `__init__` and frozen for the client's lifetime. The Protocol exposes two methods:

   - `can_decode(model: type) -> bool` — predicate used at send-time to walk `_decoders` and pick the first claiming decoder. Built-in decoders claim broadly (pydantic via `TypeAdapter(model)` probe, msgspec via `msgspec.json.Decoder(model)` probe); list ordering decides ambiguous shared shapes (dataclass, primitive, generic). Native types of another library MUST be rejected.
   - `decode(content: bytes, model: type[T]) -> T` — the decode itself. Any exception is wrapped as `httpware.DecodeError` at the seam.

   When `response_model=` is set and no decoder claims it, both `send` and `send_with_response` raise `MissingDecoderError` BEFORE the HTTP call. The default `decoders=None` resolves via `client.py:_build_default_decoders()` against installed extras.
```

- [ ] **Step 3: Run lint and full test suite**

```bash
just lint && just test
```
Expected: green (no code change).

- [ ] **Step 4: Commit**

```bash
git add planning/engineering.md
git commit -m "docs(planning): update Seam B for multi-decoder routing"
```

---

## Self-review checklist

After the final commit, verify the implementation against the spec.

- [ ] **Spec coverage:** Every section of `planning/specs/2026-06-09-multi-decoder-design.md` is implemented.
  - Protocol shape (`can_decode`): Task 1.
  - Claim policies (PydanticDecoder, MsgspecDecoder): Task 1.
  - `_dispatch_decoder` on AsyncClient and Client: Tasks 4, 5.
  - `_build_default_decoders` helper: Task 3.
  - Behavior matrix (extras-installed combinations): Tasks 4, 5, 6.
  - Send path with pre-flight `MissingDecoderError`: Tasks 4, 5.
  - `MissingDecoderError` shape (model + registered_names + pickle): Task 2.
  - Public API export: Task 2.
  - Tests new files: Tasks 6, 7.
  - Docs (README + index + errors): Task 8.
  - Engineering doc Seam B: Task 9.
  - `decoder=` → `decoders=` rename: Tasks 4, 5.
  - Deletion of `_default_pydantic_decoder` / `_DEFAULT_DECODER_MISSING_MESSAGE`: Task 5.

- [ ] **No placeholders:** `grep -nE 'TBD|TODO|FIXME|xxx|placeholder' planning/plans/2026-06-09-multi-decoder-plan.md`. Expected: zero hits (the word "fixture" is fine; the words above are not).

- [ ] **Type consistency:** Names used across tasks are stable — `_decoders` (not `_decoder_list`), `_dispatch_decoder` (not `_choose_decoder`), `_build_default_decoders` (not `_default_decoders`), `registered_names` (not `registered`).

- [ ] **Final suite:** `just lint && just test` is green with 100% coverage.

- [ ] **Release notes:** Plan does NOT cover writing release notes — that's a separate ship step. Confirm `planning/releases/0.9.0.md` is created during the release flow, not here.
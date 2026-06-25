---
summary: Shipped 0.9.0 — multi-decoder routing
---

# Spec: multi-decoder routing — `decoders=[...]` with type-dispatched claim policy

**Date:** 2026-06-09
**Topic slug:** `multi-decoder`
**Status:** drafted, awaiting user review
**Target release:** `0.9.0` (minor — breaking surface: `decoder=` → `decoders=`; behavioral: `AsyncClient()` no longer raises on missing pydantic)

## Purpose

Today, `AsyncClient()` / `Client()` constructed without `decoder=` calls `_default_pydantic_decoder()` (`src/httpware/client.py:40`), which raises `ImportError` at `__init__` time if the `pydantic` extra is missing. That fail-fast was the 0.3.0 design choice ([release_0_3_0_shipped] in memory) — at the time it modeled "pydantic is the de-facto default; surface the missing dep early."

Two problems with that choice surfaced on coherence audit:

1. **`pydantic` is documented as an *optional* extra in `pyproject.toml:35`, but `AsyncClient()` with no kwargs makes it mandatory.** Users who never call `.send(..., response_model=...)` — health checks, streaming, raw `response.json()`, HTML responses, webhooks — pay the dependency cost for a feature they don't use. The "optional" framing is misleading.
2. **The client carries a single `_decoder: ResponseDecoder` instance.** A user with mixed model types in one codebase — some endpoints returning `pydantic.BaseModel`, some returning `msgspec.Struct` — has no way to satisfy both. They must pick one decoder and either restrict their model choices or hand-write a dispatching `ResponseDecoder`. The "one decoder per client" invariant isn't justified by anything about HTTP; it's an accident of the original Seam B shape.

This spec replaces the single-decoder slot with a **type-dispatched decoder list** and removes the eager-import fail-fast. After this lands:

- `AsyncClient()` never raises on missing extras. Decoder availability is resolved from installed extras at `__init__`, falling back to `()` if neither is present.
- Users register a list: `AsyncClient(decoders=[PydanticDecoder(), MsgspecDecoder()])`. Each decoder declares which models it claims via a new `can_decode(model)` protocol method. The first decoder whose `can_decode` returns `True` for a given `response_model=` wins.
- A new `MissingDecoderError` (sibling of `DecodeError`, both under `ClientError`) fires *before* the HTTP request when `response_model=Foo` is set and no registered decoder claims `Foo`. Distinct from `DecodeError` (decoder ran, data was bad).

The decoder kwarg is renamed `decoder=` → `decoders=`. Pre-1.0, clean cutover, no shim — consistent with the project's rewrite tradition ([user_prefers_clean_cutover_ordering] in memory).

## Non-goals

- **Per-call decoder override.** Considered and rejected (option C in brainstorm). The decoder list lives on the client and is frozen for its lifetime, mirroring how middleware is composed at `__init__`. Per-call override would split routing logic across two locations and confuse the seam.
- **Auto-detect at every `.send()` call.** The default decoder list is resolved once at `__init__` from `import_checker` flags. `is_pydantic_installed` / `is_msgspec_installed` are evaluated at import time of `_internal/import_checker.py` (`find_spec` calls at module top); the client snapshot reflects whatever was true then. Hot-patching a library post-client-construction is not supported.
- **Stdlib JSON fallback decoder.** No built-in `JsonDecoder` shipping in this spec. Users with `response_model=dict` / `response_model=list[...]` use whichever of pydantic / msgspec is registered; both libraries handle those shapes via their broad claim policy. If neither extra is installed, `MissingDecoderError` fires — install one or pass a custom decoder.
- **Changing how `DecodeError` works.** `DecodeError`'s contract (`response`, `model`, `original`, wraps via `raise ... from exc`) is unchanged. Only the new sibling `MissingDecoderError` is added.
- **Migration shim for `decoder=`.** Pre-1.0; the kwarg is renamed cleanly. Old code raises `TypeError: unexpected keyword argument 'decoder'` at `__init__`. Release notes flag it.

## Architecture

### Protocol shape — Seam B extended

`ResponseDecoder` (`src/httpware/decoders/__init__.py:9`) gains one method:

```python
@runtime_checkable
class ResponseDecoder(Protocol):
    """Structural protocol every response-body decoder satisfies."""

    def can_decode(self, model: type) -> bool:
        """Return True iff this decoder claims responsibility for `model`.

        The client walks its `_decoders` tuple in order and picks the first
        decoder whose `can_decode` returns True. Implementations should claim
        every model type they can actually handle — broad is correct, because
        list ordering encodes the caller's preference for shared shapes
        (dataclass, primitive, parameterized generic, etc.). Native types of
        another library (e.g. PydanticDecoder vs `msgspec.Struct`) MUST be
        rejected.
        """
        ...

    def decode(self, content: bytes, model: type[T]) -> T: ...
```

`can_decode` is required for all decoders — including user-written ones — because the dispatcher walks the protocol method. There is no implicit "catch-all" fallback. Custom decoders that want to claim everything return `True` unconditionally.

### Claim policies — built-in decoders

**`PydanticDecoder.can_decode`** (`src/httpware/decoders/pydantic.py`):

```python
def can_decode(self, model: type) -> bool:
    try:
        _get_adapter(model)  # cached TypeAdapter(model)
    except Exception:
        return False
    return True
```

`_get_adapter` is the existing `@lru_cache`-decorated `TypeAdapter` constructor (`decoders/pydantic.py:28`). `TypeAdapter(model)` raises `pydantic.errors.PydanticSchemaGenerationError` (a `TypeError` subclass) for types pydantic can't build a schema from — most notably `msgspec.Struct`. For everything else (`BaseModel`, dataclass, `TypedDict`, primitive, `list[X]`, `dict[X, Y]`, `Foo | None`, `Annotated[...]`), `TypeAdapter` succeeds.

The probe writes to the cache; the subsequent `decode` call reuses the same cached adapter. Probe and decode share a constant — no double cost.

**`MsgspecDecoder.can_decode`** (`src/httpware/decoders/msgspec.py`):

```python
def can_decode(self, model: type) -> bool:
    try:
        _get_msgspec_decoder(model)  # cached msgspec.json.Decoder(model)
    except (TypeError, msgspec.ValidationError):
        return False
    return True
```

`msgspec.json.Decoder(model)` raises `TypeError` for types msgspec can't build a decoder for — most notably `pydantic.BaseModel`. Succeeds for `Struct`, dataclass, primitive, `list[X]`, `dict[X, Y]`, etc.

A new `_get_msgspec_decoder` module-level helper mirrors pydantic's `_get_adapter`:

```python
@functools.lru_cache(maxsize=1024)
def _get_msgspec_decoder(model: type[T]) -> "msgspec.json.Decoder[T]":
    return msgspec.json.Decoder(model)
```

Existing `MsgspecDecoder.decode` is rewritten to use the cached decoder rather than constructing per-call, matching pydantic's pattern.

### Dispatch — `AsyncClient._dispatch_decoder`

```python
def _dispatch_decoder(self, model: type) -> ResponseDecoder | None:
    """Walk `_decoders` and return the first decoder claiming `model`, or None."""
    for decoder in self._decoders:
        if decoder.can_decode(model):
            return decoder
    return None
```

Called by `send()` (both async and sync) when `response_model is not None`. Returns the matched decoder or `None`. The caller raises `MissingDecoderError` on `None`.

**Dispatch order matters** — the list is the user's preference order. Both built-in decoders claim shared shapes (dataclass, primitive, generic) broadly; the first in the list wins for those. Native types route correctly regardless of order because each library rejects the other's native (pydantic's `TypeAdapter` rejects `Struct`; msgspec's `Decoder` rejects `BaseModel`).

Default order: pydantic before msgspec, when both extras are installed. Consistent with the project's history (pydantic was the original primary).

### Client state — `_decoders` replaces `_decoder`

`AsyncClient` and `Client` attributes (`src/httpware/client.py:75`, `:793`):

```python
# was: _decoder: ResponseDecoder
_decoders: tuple[ResponseDecoder, ...]
```

Init (`src/httpware/client.py:79`, `:797`):

```python
def __init__(
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
    ...
    self._decoders = tuple(decoders) if decoders is not None else _build_default_decoders()
```

`decoders=` is keyword-only and `Sequence[ResponseDecoder] | None`. `None` triggers the default; `()` / `[]` is a valid explicit "no decoders" — see Behavior matrix below.

### Default decoders — `_build_default_decoders()`

Replaces `_default_pydantic_decoder()` (`src/httpware/client.py:40`). Module-level helper:

```python
def _build_default_decoders() -> tuple[ResponseDecoder, ...]:
    decoders: list[ResponseDecoder] = []
    if import_checker.is_pydantic_installed:
        from httpware.decoders.pydantic import PydanticDecoder  # noqa: PLC0415 — lazy by design
        decoders.append(PydanticDecoder())
    if import_checker.is_msgspec_installed:
        from httpware.decoders.msgspec import MsgspecDecoder  # noqa: PLC0415 — lazy by design
        decoders.append(MsgspecDecoder())
    return tuple(decoders)
```

Lazy module imports preserve Seam C (`httpware ↔ optional extras` — `planning/engineering.md`): if `is_pydantic_installed` is False, `httpware.decoders.pydantic` is never imported, and `pydantic` itself never enters `sys.modules` via httpware.

**Behavior matrix:**

| Installed extras | `AsyncClient()` default `_decoders` | `AsyncClient()` raises? | `response_model=BaseModel` | `response_model=Struct` | `response_model=dict` |
|---|---|---|---|---|---|
| pydantic + msgspec | `(PydanticDecoder(), MsgspecDecoder())` | no | pydantic | msgspec | pydantic (first wins) |
| pydantic only | `(PydanticDecoder(),)` | no | pydantic | `MissingDecoderError` | pydantic |
| msgspec only | `(MsgspecDecoder(),)` | no | `MissingDecoderError` | msgspec | msgspec |
| neither | `()` | no | `MissingDecoderError` | `MissingDecoderError` | `MissingDecoderError` |
| neither, no `response_model=` ever | `()` | no | n/a | n/a | n/a — client works fine |

`AsyncClient(decoders=[])` behaves identically to "neither installed" — explicit opt-out is honored; the user is telling the client "I will never use `response_model=`."

## Send path — `.send()` with eager dispatch check

`AsyncClient.send` (`src/httpware/client.py:147`) and `Client.send` (`:889`) gain a pre-flight check. Async form:

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
            raise MissingDecoderError(model=response_model)

    response = await self._dispatch(request)
    if decoder is None:
        return response
    try:
        return decoder.decode(response.content, response_model)
    except Exception as exc:
        raise DecodeError(response=response, model=response_model, original=exc) from exc
```

Key change: `MissingDecoderError` fires **before** `await self._dispatch(request)`. Unlike `DecodeError` (data-dependent, only knowable post-response), `MissingDecoderError` is deterministic in `(response_model, self._decoders)`. Sending a request whose response cannot be decoded wastes a round-trip, may noise up retries / metrics, and gives the user a confusing trace through middleware before the real error surfaces.

`send_with_response` (`client.py:162`, `:904`) gets the same pre-flight check. Both `AsyncClient` and `Client` mirror the change.

The streaming path (`stream()`, `client.py:703`, `:1445`) is **unchanged**. It bypasses decoders entirely; `response_model=` is not a parameter; nothing routes through `_dispatch_decoder`.

## Error contract — `MissingDecoderError`

New sibling of `DecodeError` (`src/httpware/errors.py:226`), both under `ClientError`.

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

The client passes a snapshot of decoder class names at raise time:

```python
raise MissingDecoderError(
    model=response_model,
    registered_names=tuple(type(d).__name__ for d in self._decoders),
)
```

**Why class-name snapshot, not the decoder instances?** Decoder instances may not be picklable in the general case (custom decoders can hold arbitrary state — caches, connections, closures). Keeping exception state to primitives (`type`, `tuple[str, ...]`) mirrors `BulkheadFullError` / `RetryBudgetExhaustedError` config-shape fields and guarantees pickle round-trips. The names are enough for both the user-facing message and structured logging.

**Why not derive the message from `import_checker` flags?** That would produce a wrong hint when the user explicitly registered a custom decoder list (e.g. `decoders=[CustomDecoder()]` with both extras installed but custom decoder rejecting). The message must reflect what's *actually registered on this client*, not what's *installable in the environment*.

**Exception tree placement.** `MissingDecoderError` is added to `__all__` in `src/httpware/__init__.py` next to `DecodeError`. `except ClientError` covers it. `except (DecodeError, MissingDecoderError)` separates the two corrective actions:
- `DecodeError` → fix data shape / model.
- `MissingDecoderError` → install an extra or register a decoder.

## Tests

Project requires 100% line coverage (`pyproject.toml:93` — `--cov-fail-under=100`). Every code path below must be exercised.

### New test files

**`tests/test_client_decoders_default.py`** — default resolution under varying extras state:

| Case | Assertion |
|---|---|
| `AsyncClient()` with both extras installed | `_decoders == (PydanticDecoder(), MsgspecDecoder())` |
| `AsyncClient()` with pydantic only (`is_msgspec_installed` patched False) | `_decoders == (PydanticDecoder(),)` |
| `AsyncClient()` with msgspec only (`is_pydantic_installed` patched False) | `_decoders == (MsgspecDecoder(),)` |
| `AsyncClient()` with both patched False | `_decoders == ()`; no exception raised |
| `AsyncClient(decoders=[])` | `_decoders == ()`; explicit opt-out honored |
| `AsyncClient(decoders=[CustomDecoder()])` | `_decoders == (CustomDecoder(),)`; defaults NOT probed |
| `AsyncClient(decoders=[CustomDecoder()])` with both extras patched False | constructs ok; `import_checker` flags do not gate explicit decoders |
| Sync `Client` mirrors each case | (same six cases above) |

Patching the import flags uses `monkeypatch.setattr(import_checker, "is_pydantic_installed", False)` — the existing test pattern for the otel partial-install spec.

**`tests/test_client_dispatch.py`** — routing across multiple decoders:

| Case | Assertion |
|---|---|
| `response_model=PydanticUser` with `decoders=[PydanticDecoder(), MsgspecDecoder()]` | decoded via pydantic; assert by patching `MsgspecDecoder.decode` to raise — confirms it's never called |
| `response_model=MsgspecUser` (Struct) with `decoders=[PydanticDecoder(), MsgspecDecoder()]` | decoded via msgspec; `PydanticDecoder.can_decode` returned False for Struct |
| `response_model=dict` with `decoders=[PydanticDecoder(), MsgspecDecoder()]` | decoded via pydantic (first wins for shared shapes) |
| `response_model=dict` with `decoders=[MsgspecDecoder(), PydanticDecoder()]` | decoded via msgspec (reversed order flips routing for shared shapes) |
| `response_model=list[PydanticUser]` | pydantic claims (TypeAdapter handles parameterized generics) |
| `response_model=MyDataclass` with both | pydantic claims (first in list) |
| `response_model=Foo` with `decoders=()` | `MissingDecoderError` raised; transport handler NEVER invoked (pre-flight check) |
| `response_model=Foo` where neither decoder claims Foo | `MissingDecoderError` raised; transport handler never invoked |
| Sync `Client` mirrors each case | (same eight cases above) |

The "transport handler never invoked" assertion is the empirical proof that `MissingDecoderError` fires before the HTTP call. Pattern: wire a `httpx2.MockTransport(handler)` where `handler` either `pytest.fail("transport called")` or increments a counter; assert the counter is zero after the raise. Matches the existing `_client_with_payload` helper shape in `tests/test_client_response_model.py:14`.

**`tests/test_errors_missing_decoder.py`** — exception shape and message hints:

| Case | Assertion |
|---|---|
| `MissingDecoderError(model=Foo)` carries `.model is Foo` | direct attribute access |
| `str(exc)` includes `Foo.__name__` and a hint | regex / substring match |
| Hint says "install httpware[pydantic] or httpware[msgspec]" when `registered_names == ()` | substring match |
| Hint says "registered decoders (PydanticDecoder) all rejected it" when `registered_names == ("PydanticDecoder",)` | substring match |
| Hint says "registered decoders (PydanticDecoder + MsgspecDecoder) all rejected it" when both names present | substring match |
| `.registered_names` is the tuple passed at construction | direct attribute access |
| `isinstance(MissingDecoderError(model=Foo), ClientError)` | tree placement check |
| `pickle.loads(pickle.dumps(exc)).model is Foo` and `.registered_names` round-trips | `__reduce__` round-trip |
| `MissingDecoderError` is exported from `httpware` top-level | `from httpware import MissingDecoderError` works |

**`tests/test_decoders_can_decode.py`** — claim policies:

| Decoder | model | Expected | Notes |
|---|---|---|---|
| PydanticDecoder | `class U(BaseModel): ...` | True | native |
| PydanticDecoder | `class U(Struct): ...` | False | TypeAdapter rejects |
| PydanticDecoder | `dict` | True | shared shape |
| PydanticDecoder | `list[int]` | True | parameterized generic |
| PydanticDecoder | `MyDataclass` | True | dataclass via TypeAdapter |
| PydanticDecoder | `int` | True | primitive |
| PydanticDecoder | `Foo \| None` | True | union |
| MsgspecDecoder | `class U(Struct): ...` | True | native |
| MsgspecDecoder | `class U(BaseModel): ...` | False | msgspec Decoder rejects |
| MsgspecDecoder | `dict` | True | shared shape |
| MsgspecDecoder | `list[int]` | True | parameterized generic |
| MsgspecDecoder | `MyDataclass` | True | dataclass via msgspec Decoder |
| MsgspecDecoder | `int` | True | primitive |

Plus: `can_decode` is cached. Construct a `PydanticDecoder`, call `can_decode(BaseModelSubclass)` twice, assert `_get_adapter.cache_info().hits >= 1`. Same for `MsgspecDecoder._get_msgspec_decoder`.

### Existing tests — update / delete

**Delete:**

- Any test asserting `AsyncClient()` raises `ImportError` when pydantic is uninstalled. The 0.3.0 fail-fast is gone. Search: `grep -r "_DEFAULT_DECODER_MISSING_MESSAGE\|_default_pydantic_decoder" tests/`.
- Direct unit tests of `_default_pydantic_decoder()`.

**Update:**

- Every `AsyncClient(decoder=...)` / `Client(decoder=...)` call site becomes `decoders=[...]`. Search: `grep -rn "decoder=" tests/` — expected ~10–20 call sites.
- `tests/decoders/test_pydantic.py` and `tests/decoders/test_msgspec.py`: add `can_decode` table tests; keep existing `decode` tests as-is.

## Docs

Decoder narrative is spread across two existing pages — no new docs page:

- **`docs/index.md`** — the "First request" / install section currently shows `pip install httpware[pydantic]   # PydanticDecoder (the default decoder path)`. Rewrite to:
  1. Frame extras as "install whichever decoder(s) you want; both can coexist."
  2. Replace any `decoder=` call sites with `decoders=[...]`.
  3. Add a short subsection on the `decoders=` list, the dispatch order, and a one-line example showing pydantic + msgspec mixed in the same client.
- **`docs/errors.md`** — the exception-tree page. Add `MissingDecoderError` as a sibling of `DecodeError` in the tree, with one bullet on the corrective action ("install an extra or register a decoder").

A separate "writing a custom `ResponseDecoder`" doc is out of scope for this spec — `ResponseDecoder` is a Protocol, the change to add `can_decode` is documented in release notes and the docstring on the Protocol itself.

`README.md` examples updated wherever they use `decoder=` or imply a single decoder per client. Search: `grep -n "decoder=\|PydanticDecoder\|MsgspecDecoder" README.md`.

No autodoc additions, no benchmarks, no migration guide — consistent with project docs philosophy ([user_docs_philosophy] in memory). Release notes carry the breaking-change call-out, not a dedicated migration page.

## Release impact

**Version:** 0.9.0 (minor — breaking surface change pre-1.0).

**Release notes** in `planning/releases/0.9.0.md`:

- **Breaking — `decoder=` kwarg removed.** Replaced with `decoders: Sequence[ResponseDecoder] | None = None`. Old code (`AsyncClient(decoder=PydanticDecoder())`) raises `TypeError`. Migration: `AsyncClient(decoders=[PydanticDecoder()])`.
- **Breaking — `ResponseDecoder` protocol gains `can_decode(model) -> bool`.** Custom decoder implementations must add the method. Common case: `def can_decode(self, model: type) -> bool: return True`.
- **Behavioral — `AsyncClient()` / `Client()` no longer raise `ImportError` when the `pydantic` extra is missing.** Failure now surfaces only when `response_model=` is used and no decoder claims the model, via the new `MissingDecoderError`.
- **New — mixed pydantic + msgspec models work in a single client.** `AsyncClient(decoders=[PydanticDecoder(), MsgspecDecoder()])`. Default when both extras are installed.
- **New — `MissingDecoderError`** under `ClientError`, exported from `httpware`.

Tag and GitHub Release notes follow the existing bare-semver tag convention ([release_0_1_0_shipped] in memory).

**Engineering doc update** — `planning/engineering.md` Seam B description is updated:

- Old: "Called when `response_model` is provided. Signature: `decode(content: bytes, model: type[T]) -> T`."
- New: "Implementations expose `can_decode(model) -> bool` (dispatch predicate) and `decode(content, model) -> T` (the decode). The client holds a tuple `_decoders` and walks it in order on every `response_model=` use; first matching decoder wins. `MissingDecoderError` fires before the HTTP call when no decoder matches."

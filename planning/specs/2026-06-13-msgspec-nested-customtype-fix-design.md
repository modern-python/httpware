# Spec: Fix `MsgspecDecoder.can_decode` false-positive on nested CustomType

**Date:** 2026-06-13
**Source:** [2026-06-12-delta-audit.md](../audit/2026-06-12-delta-audit.md) — High finding #1 (`src/httpware/decoders/msgspec.py:48`)
**Related:** the top-level `CustomType` rejection landed with multi-decoder routing in 0.9.0; this fixes the nested-container extension of the same quirk.

## Purpose

`MsgspecDecoder.can_decode(model)` must return `True` only for model types msgspec can natively decode end-to-end. Today it returns `True` for parameterized containers whose element type msgspec cannot decode — `list[PUser]`, `dict[str, PUser]`, `Optional[PUser]`, `tuple[PUser, int]`, and any nesting thereof, where `PUser` is a `pydantic.BaseModel` (or any other type that falls back to msgspec's `CustomType`). This bypasses the `MissingDecoderError` pre-flight at the client dispatch seam, so a real HTTP request is sent and then `decode` raises `msgspec.ValidationError` (surfaced as `DecodeError`). The false-positive is cached in the per-instance `_msgspec_decoders` dict, so every subsequent request with that model type repeats the wasted round-trip.

## Root cause

`can_decode` rejects only when the **top-level** `type_info` result is a `CustomType`:

```python
info = msgspec.inspect.type_info(model)
if isinstance(info, msgspec.inspect.CustomType):
    return False
```

For `list[PUser]`, `type_info` returns `ListType(item_type=CustomType(...))` — the top-level node is `ListType`, so the guard passes. `msgspec.json.Decoder(list[PUser])` then **builds successfully** (msgspec defers the `CustomType` to a `dec_hook` that httpware never configures), so the second `try/except` probe also passes and `can_decode` returns `True`.

Empirically confirmed (msgspec 0.21.1):

| model | `type_info` top node | nested CustomType? | `Decoder` builds? | `can_decode` today |
|---|---|---|---|---|
| `PUser` | `CustomType` | — | yes | `False` ✅ |
| `list[PUser]` | `ListType` | `item_type` | yes | `True` ❌ |
| `dict[str, PUser]` | `DictType` | `value_type` | yes | `True` ❌ |
| `Optional[PUser]` | `UnionType` | `types[0]` | yes | `True` ❌ |
| `tuple[PUser, int]` | `TupleType` | `item_types[0]` | yes | `True` ❌ |
| `list[list[PUser]]` | `ListType` | `item_type.item_type` | yes | `True` ❌ |
| `list[Struct]`, `Struct`, `dict[str,int]` | container / `StructType` | none | yes | `True` ✅ |

## Design

Replace the single top-level `isinstance` check with a recursive walk of the `type_info` tree. Reject when **any** node anywhere in the tree is a `CustomType`.

### The walker

A module-level private helper in `src/httpware/decoders/msgspec.py`:

```python
def _contains_custom_type(info: "msgspec.inspect.Type") -> bool:
    """True if `info` is a CustomType or has any nested Type that is.

    Walks generic-container parameterization (list/dict/set/tuple/union element
    types) by visiting any attribute that is itself a `msgspec.inspect.Type` or a
    tuple of them. It deliberately does NOT descend into `StructType`/dataclass
    fields: those expose `fields` as `Field` objects (not `Type`), so the walk
    stops at the boundary of a type msgspec natively owns — which also makes
    recursive struct definitions safe from infinite recursion.
    """
    if isinstance(info, msgspec.inspect.CustomType):
        return True
    for name in dir(info):
        if name.startswith("_"):
            continue
        value = getattr(info, name, None)
        if isinstance(value, msgspec.inspect.Type):
            if _contains_custom_type(value):
                return True
        elif isinstance(value, tuple) and value and all(
            isinstance(item, msgspec.inspect.Type) for item in value
        ):
            if any(_contains_custom_type(item) for item in value):
                return True
    return False
```

**Why generic introspection over per-container-kind code:** enumerating `ListType.item_type`, `DictType.value_type`, `TupleType.item_types`, `UnionType.types`, `SetType.item_type`, `FrozenSetType.item_type` by hand is brittle — a new msgspec container kind would silently re-open the bug. Walking any `Type`-typed attribute covers all current containers, arbitrary nesting, and future kinds with no maintenance.

**Why the Struct boundary is correct and safe:** `StructType.fields` is a tuple of `msgspec.inspect.Field` (not `Type`), so the `all(isinstance(item, Type) ...)` guard skips it. The walker never enters struct/dataclass/TypedDict field types. This is the intended scope — a `Struct` is a type msgspec owns natively; `can_decode` answers "does msgspec own the *container shape*," and per-field pathologies (a Struct with a pydantic-model field) are out of scope for this fix. It also means a self-referential `Struct` (`next: Optional[Node]`) cannot drive infinite recursion through this helper.

### Updated `can_decode`

```python
def can_decode(self, model: type) -> bool:
    """Return True iff msgspec natively understands `model` end-to-end.

    msgspec builds a Decoder for almost any class via a generic CustomType
    fallback; the Decoder constructor does NOT raise on unsupported types
    (e.g. pydantic.BaseModel, or a container parameterized by one). We use
    msgspec.inspect.type_info and reject if a CustomType appears anywhere in
    the type tree, so MissingDecoderError fires before a request is sent.
    """
    try:
        info = msgspec.inspect.type_info(model)
    except Exception:  # noqa: BLE001 — can_decode is a probe; any failure means no
        return False
    if _contains_custom_type(info):
        return False
    try:
        self._get_msgspec_decoder(model)
    except Exception:  # noqa: BLE001 — can_decode is a probe; any failure means no
        return False
    return True
```

The second `try/except` (decoder-build probe) is retained as defense for any non-`CustomType` shape msgspec still refuses to build.

## Scope boundaries

- **In scope:** the recursive `CustomType` rejection only.
- **Out of scope (deferred audit nits, by user decision):** the uncached `type_info` call on every dispatch (perf nit a) and `PydanticDecoder` negative-probe caching (perf nit b). This spec does not touch `pydantic.py` and does not add caching to the `can_decode` hot path.
- **No public-API change:** `can_decode`'s signature and the `ResponseDecoder` protocol are unchanged. Behavior changes only for the previously-mis-accepted nested-CustomType types, which now correctly route to `MissingDecoderError` (or to another registered decoder that claims them — e.g. `PydanticDecoder` claims `list[PUser]`).

## Interaction with multi-decoder routing

Under the default `decoders=[PydanticDecoder(), MsgspecDecoder()]` (pydantic-first), `list[PUser]` already routes to pydantic because pydantic's `can_decode` is consulted first and returns `True`. The bug bites when **only** `MsgspecDecoder` is registered (msgspec-only install, or an explicit `decoders=[MsgspecDecoder()]`): there, `list[PUser]` should raise `MissingDecoderError` at dispatch but instead sends a request and fails at decode. The fix makes the msgspec-only path correct without affecting the pydantic-first default.

## Testing

New tests in `tests/test_decoders_msgspec.py` (the file already defines `_Item` Struct, `_PydanticUser` BaseModel, `_DC` dataclass):

1. **Nested-CustomType rejection** — parametrized over `list[_PydanticUser]`, `dict[str, _PydanticUser]`, `typing.Optional[_PydanticUser]`, `tuple[_PydanticUser, int]`, `list[list[_PydanticUser]]`: each `can_decode(...) is False`.
2. **Valid containers still accepted** — `list[_Item]`, `dict[str, _Item]`, `dict[str, int]`, `list[int]`, `_Item`, `int`: each `can_decode(...) is True` (guards against over-rejection; `test_msgspec_can_decode_list_of_structs` already covers `list[_Item]`, extend the set).
3. **Dispatch-level regression** — a `Client` / `AsyncClient` with `decoders=[MsgspecDecoder()]` and `response_model=list[_PydanticUser]` raises `MissingDecoderError` **without** sending a request. Assert the mock transport's handler was never invoked (a flag the handler flips), proving the pre-flight fires. Both sync and async twins.
4. **Helper unit tests** (optional, if the walker reads better tested directly) — `_contains_custom_type(type_info(list[_PydanticUser])) is True`, `_contains_custom_type(type_info(list[_Item])) is False`.

All four behaviors get sync + async coverage where a client is involved (test #3), per the parity convention.

## Acceptance criteria

1. `MsgspecDecoder().can_decode(list[PUser])` (and the dict/optional/tuple/nested variants) returns `False`.
2. `MsgspecDecoder().can_decode(list[Struct])`, `can_decode(Struct)`, `can_decode(dict[str, int])` still return `True`.
3. A msgspec-only client with `response_model=list[PUser]` raises `MissingDecoderError` before any request is sent (transport handler not invoked).
4. `just lint` and `just test` pass; no `pydantic.py` changes; no public-API or protocol change.
5. The fix ships as a patch release (0.9.1) per the project's patch-for-bugfix convention.

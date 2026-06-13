# httpware delta audit — 2026-06-12 (0.9.0 multi-decoder epic)

**Status:** complete
**Baseline:** 0.8.6 → current HEAD `f8bb0e5`
**Spec:** [planning/specs/2026-06-12-delta-audit-design.md](../specs/2026-06-12-delta-audit-design.md)
**Plan:** [planning/plans/2026-06-12-delta-audit-plan.md](../plans/2026-06-12-delta-audit-plan.md)

## Summary

- Blockers: 0
- High: 2
- Medium: 1
- Low: 3
- Nits: 8

No blockers surfaced in the 0.9.0 multi-decoder delta. The most severe finding is a
tie between two High items, but the one with the broadest user-facing blast radius is
**`src/httpware/decoders/msgspec.py:48` — `MsgspecDecoder.can_decode` returns `True`
for parameterized containers whose element type is a pydantic `BaseModel`** (e.g.
`list[PUser]`): the `CustomType` guard only inspects the top-level `type_info`, so the
pre-flight `MissingDecoderError` check is bypassed, a real HTTP request is sent, and the
false-positive is cached per instance so every subsequent request with that model type
repeats the failure as a `DecodeError`. The companion High is documentation: `CLAUDE.md`
Seam B still describes the pre-0.9.0 single-decoder `decode(content, model)` contract with
no mention of `can_decode`, so an agent implementing a custom decoder from that reference
ships an interface that `AttributeError`s at dispatch.

## Findings

### High

#### MsgspecDecoder.can_decode false-positive for parameterized containers of pydantic BaseModels

`src/httpware/decoders/msgspec.py:48`

The `CustomType` guard in `can_decode` inspects only the top-level `type_info` result.
For `list[PUser]`, `dict[str, PUser]`, `Optional[PUser]`, or `tuple[PUser, int]`,
`type_info` returns `ListType`/`DictType`/`UnionType` (not `CustomType`), so the guard
passes and `msgspec.json.Decoder` builds silently — `can_decode` returns `True`, the
`MissingDecoderError` pre-flight is bypassed, a real request is sent, and `decode` then
raises `ValidationError` (surfaced as `DecodeError`). The false-positive is cached in
`self._msgspec_decoders`, so the failure repeats for every later request of that type.

```python
    def can_decode(self, model: type) -> bool:
        try:
            info = msgspec.inspect.type_info(model)
        except Exception:  # noqa: BLE001 — can_decode is a probe; any failure means no
            return False
        if isinstance(info, msgspec.inspect.CustomType):
            return False
        try:
            self._get_msgspec_decoder(model)
        except Exception:  # noqa: BLE001 — can_decode is a probe; any failure means no
            return False
        return True
```

Verifier consensus: 3/3 (code_reality + reproducer + spec_grounded). Suggested direction:
recurse through parameterized `type_info` nodes and reject when any element is a
`CustomType`, so `MissingDecoderError` fires before a request is sent.

#### CLAUDE.md Seam B description is stale for 0.9.0 (single-decoder contract)

`CLAUDE.md:84`

`CLAUDE.md` line 84 describes Seam B as a single `ResponseDecoder` with only
`decode(content: bytes, model: type[T]) -> T` — no `can_decode`, no list contract, no
pre-flight `MissingDecoderError`. 0.9.0 changed Seam B to a list of decoders dispatched
via `can_decode`, so an agent implementing a decoder from this reference produces an
interface missing `can_decode`. At dispatch the client calls `decoder.can_decode(model)`,
which `AttributeError`s at runtime.

```text
2. **Seam B** — `Client`/`AsyncClient` ↔ `ResponseDecoder` — called when `response_model` is provided. Signature: `decode(content: bytes, model: type[T]) -> T`. Implementations of both `send` methods call the decoder identically.
```

Verifier consensus: 3/3 (code_reality + spec_grounded + spec_grounded). Suggested
direction: rewrite Seam B to describe the `decoders=[...]` list, the `can_decode` dispatch
protocol, and when `MissingDecoderError` fires.

### Medium

#### Shared-shape "first decoder wins" tests cannot distinguish which decoder ran

`tests/test_client_dispatch.py:79`

The four dict-routing tests (async/sync, normal/reversed order) assert only output
equality (`result == {"a": 1}`), but `PydanticDecoder` and `MsgspecDecoder` both decode
`dict[str, int]` to an identical dict. The assertion passes regardless of which decoder
handled the request, so the central ordering invariant of the epic — shared shapes route
to the first decoder in the list — is never actually verified. A regression that always
routed to the second decoder would pass all four tests.

```python
async def test_async_dict_routes_to_first_decoder() -> None:
    """Shared shape: first decoder in the list wins."""
    pyd = PydanticDecoder()
    msg = MsgspecDecoder()
    client = _async_client_with_body(b'{"a": 1}', decoders=[pyd, msg])
    result = await client.get("https://example.test/x", response_model=dict[str, int])
    assert type(result) is dict
    assert result == {"a": 1}
```

Verifier consensus: 2/3 (code_reality + reproducer). Suggested direction: introduce a
recording decoder pair (each appends its name on `decode`) and assert which one ran, so the
ordering invariant is directly observed.

### Low

#### Dataclass routing test name overclaims; assertion can't tell pydantic from msgspec

`tests/test_client_dispatch.py:99`

`test_async_dataclass_routes_to_first_decoder` is named for order significance (both
decoders claim a stdlib dataclass), but its only assertion is `type(result) is _DC`, which
both `PydanticDecoder` and `MsgspecDecoder` satisfy. It does not prove the first decoder
(pydantic) actually ran — the same wrong-reason pass as the dict tests.

```python
async def test_async_dataclass_routes_to_first_decoder() -> None:
    client = _async_client_with_body(
        b'{"id": 1, "name": "Ada"}',
        decoders=[PydanticDecoder(), MsgspecDecoder()],
    )
    result = await client.get("https://example.test/x", response_model=_DC)
    assert type(result) is _DC
    assert result.id == 1
```

Verifier consensus: 2/3 (code_reality + reproducer). Suggested direction: fold into the
recording-decoder fix above so the assertion proves decoder identity, not just result type.

#### docs/index.md decoder dispatch code block uses PydanticDecoder/MsgspecDecoder without imports

`docs/index.md:80`

The "Decoder dispatch" section shows `AsyncClient(decoders=[PydanticDecoder(),
MsgspecDecoder()])` with no import statement. Neither symbol is exported from the top-level
`httpware` namespace — they live at `httpware.decoders.pydantic` and
`httpware.decoders.msgspec`. A reader copying the snippet verbatim gets
`NameError: name 'PydanticDecoder' is not defined`.

```python
# pydantic-first (the default when both extras are installed):
# - BaseModel  -> pydantic
# - Struct     -> msgspec
# - dict, list -> pydantic (first in list)
AsyncClient(decoders=[PydanticDecoder(), MsgspecDecoder()])
```

Verifier consensus: 2/3 (code_reality + reproducer). Suggested direction: add
`from httpware.decoders.pydantic import PydanticDecoder` and
`from httpware.decoders.msgspec import MsgspecDecoder` to the snippet.

#### README.md quickstart typed-decoding note is pydantic-only after 0.9.0 added msgspec parity

`README.md:53`

Line 53 says typed decoding via `response_model=` "requires `pip install
httpware[pydantic]`." After 0.9.0 msgspec also supports typed decoding via
`response_model=`, and the auto-resolved default includes msgspec when pydantic is absent.
A reader who has only msgspec installed will incorrectly conclude they must install
pydantic. The installation section above line 53 was updated; this sentence was missed.

```text
Typed decoding via `response_model=` works in both worlds — requires `pip install httpware[pydantic]`. Decode failures (malformed body, schema mismatch) raise `httpware.DecodeError`, a `ClientError` subclass — so `except httpware.ClientError` covers them alongside transport and status errors.
```

Verifier consensus: 2/3 (spec_grounded + spec_grounded). Suggested direction: reword to
state typed decoding works with either the `pydantic` or `msgspec` extra.

### Nit

#### MsgspecDecoder.can_decode makes an uncached type_info call on every dispatch

`src/httpware/decoders/msgspec.py:48`

`can_decode` runs on every `.send()` and always calls `msgspec.inspect.type_info(model)`
(~6.5 µs) even for already-classified types, while `PydanticDecoder.can_decode` short-
circuits via a cached `dict.get()` (~33 ns). The per-instance `_msgspec_decoders` cache
already holds the result for known types and could short-circuit the probe.

```python
    def can_decode(self, model: type) -> bool:
        try:
            info = msgspec.inspect.type_info(model)
        except Exception:  # noqa: BLE001 — can_decode is a probe; any failure means no
            return False
```

Verifier consensus: 2/3 (code_reality + code_reality). Suggested direction: check the
per-instance cache before the `type_info` probe on the hot path.

#### PydanticDecoder.can_decode does not cache failed probes

`src/httpware/decoders/pydantic.py:50`

When `can_decode` rejects a model (e.g. a `msgspec.Struct`), it calls `TypeAdapter(model)`,
catches `PydanticSchemaGenerationError`, and returns `False` without storing anything. Every
later `.send()` with that model repeats the ~0.03 ms construction instead of an O(1) dict
lookup. Caching negative results (a sentinel in `_adapters`) would avoid it.

```python
    def can_decode(self, model: type) -> bool:
        try:
            self._get_adapter(model)
        except Exception:  # noqa: BLE001 — can_decode is a probe; any failure means no
            return False
        return True
```

Verifier consensus: 2/3 (code_reality + code_reality). Suggested direction: memoize
negative probe results so rejected model types resolve to an O(1) lookup.

#### can_decode() exceptions in custom decoders escape the DecodeError wrap boundary

`src/httpware/client.py:171`

`_dispatch_decoder` calls `can_decode()` on each registered decoder before the
`try/except` that produces `DecodeError`. If a third-party `ResponseDecoder.can_decode()`
raises, the exception escapes `send`/`send_with_response` unwrapped, so `except ClientError`
does not catch it. Both built-in decoders swallow probe exceptions, so this is unreachable
with the bundled adapters, but the protocol contract is silent on the obligation.

```python
    def _dispatch_decoder(self, model: type) -> ResponseDecoder | None:
        """Walk `_decoders` and return the first decoder claiming `model`, or None."""
        for decoder in self._decoders:
            if decoder.can_decode(model):
                return decoder
        return None
```

Verifier consensus: 2/3 (code_reality + code_reality). Suggested direction: document the
no-raise obligation for `can_decode`, or guard the dispatch loop so probe failures map to a
`ClientError` subclass.

#### CLAUDE.md exception-construction rule is ambiguously worded vs the codebase pattern

`src/httpware/errors.py:290`

`CLAUDE.md` says status-keyed errors take a single positional `response` and "Subclasses do
not override `__init__`." The phrase is ambiguous about whether it scopes to all
`ClientError` subclasses or only `StatusError` subclasses. In practice `DecodeError`,
`BulkheadFullError`, `RetryBudgetExhaustedError`, and now `MissingDecoderError` all override
`__init__` with keyword-only args. `engineering.md` §4 correctly scopes the rule to
`StatusError` and its 4xx/5xx subclasses; `CLAUDE.md` does not.

```python
    def __init__(self, *, model: type, registered_names: tuple[str, ...]) -> None:
        self.model = model
        self.registered_names = registered_names
        super().__init__(_missing_decoder_summary(model, registered_names))
```

Verifier consensus: 3/3 (spec_grounded ×3). Suggested direction: scope the `CLAUDE.md` rule
to `StatusError` subclasses, mirroring `engineering.md` §4.

#### Dataclass and list-of-model routing tested only on AsyncClient, no sync Client twin

`tests/test_client_dispatch.py:99`

The sync dispatch suite covers only struct and dict routing; dataclass routing
(`test_async_dataclass_routes_to_first_decoder`) and list-of-`BaseModel` routing
(`test_async_list_of_basemodel_routes_to_pydantic`) have async-only coverage. A sync-only
dispatch regression in those two model shapes would go uncaught.

```python
async def test_async_dataclass_routes_to_first_decoder() -> None:
    client = _async_client_with_body(
        b'{"id": 1, "name": "Ada"}',
        decoders=[PydanticDecoder(), MsgspecDecoder()],
    )
    result = await client.get("https://example.test/x", response_model=_DC)
    assert type(result) is _DC
    assert result.id == 1
```

Verifier consensus: 2/3 (code_reality + reproducer). Suggested direction: add sync `Client`
twins for the dataclass and list-of-model routing tests.

#### docs/errors.md MissingDecoderError hint text does not match the actual exception message

`docs/errors.md:168`

The doc shows two verbatim hint strings readers are expected to match. The first omits
backticks present in the real message (`` `pip install httpware[pydantic]` ``). The second
is truncated — the code produces `. Pass a custom decoder via decoders=[...].` but the doc
ends at `... all rejected it.`. Code that string-matches these hints against `str(exc)`
fails.

```text
- `no decoders registered. Install pip install httpware[pydantic] or pip install httpware[msgspec], or pass decoders=[...] explicitly.` — install an extra or pass an explicit decoder list.
- `registered decoders (PydanticDecoder + MsgspecDecoder) all rejected it.` — your `response_model` type is exotic enough that neither built-in claims it. Pass a custom `ResponseDecoder` via `decoders=[...]`.
```

Verifier consensus: 2/3 (spec_grounded + reproducer). Suggested direction: copy the exact
message strings from `errors.py` into the doc, including backticks and the trailing
sentence.

#### planning/deferred-work.md Open lru_cache entry is resolved by PR #42 but still listed as Open

`planning/deferred-work.md:11`

The Open section lists "`_get_adapter` `lru_cache` is module-global" at
`src/httpware/decoders/pydantic.py:12-14`. PR #42 replaced the module-level
`@functools.lru_cache` with per-instance `_adapters` / `_msgspec_decoders` dicts; lines
12-14 no longer contain an `lru_cache`. The item is closed but still filed under Open, so an
agent scanning deferred-work investigates a non-existent problem.

```text
- **`_get_adapter` `lru_cache` is module-global, not per-decoder instance** — keyed by `model` only; two `PydanticDecoder()` instances with different configurations (none today) would share adapters, and the cache survives across tests unless explicitly cleared. ... (`src/httpware/decoders/pydantic.py:12-14`)
```

Verifier consensus: 2/3 (code_reality + spec_grounded). Suggested direction: move the entry
to a closed/resolved section noting PR #42, or delete it.

#### planning/engineering.md §1 docs URL still points to stale httpware.readthedocs.io

`planning/engineering.md:7`

The §1 historical sentence "the first-cut user-docs surface is live at
`https://httpware.readthedocs.io/`" was not updated when docs moved to GitHub Pages at
`https://httpware.modern-python.org/`. The §8 Epic 6 entry was correctly updated by commit
`3b02a41` but §1 was missed; an agent following the §1 URL reaches the stale RTD site.

```text
As of 0.7.0, the first-cut user-docs surface is live at <https://httpware.readthedocs.io/> (Middleware, Resilience, Errors, Testing guides) and Epic 3 is closed.
```

Verifier consensus: 2/3 (code_reality + spec_grounded). Suggested direction: update the §1
URL to `https://httpware.modern-python.org/`.

## Dimension coverage

- **decoder_routing** — findings survived (1 High, 3 Nit).
- **seam_parity** — findings survived (1 Medium, 1 Low, 1 Nit).
- **new_tests** — covered under seam_parity / decoder_routing test findings above; no
  additional new-tests-only findings survived verification beyond those listed.
- **docs_consistency** — findings survived (1 High, 2 Low, 4 Nit).

## Recategorization notes

No docs_consistency finding was moved to a code dimension: every docs_consistency finding's
verifier reasons place the fix in the DOC (`CLAUDE.md` Seam B, `docs/index.md` imports,
`README.md` note, `CLAUDE.md` exception rule, `docs/errors.md` hints, `deferred-work.md`
entry, `engineering.md` §1 URL). The `CLAUDE.md` Seam B item is High because it misleads a
reasonable reader into shipping a broken interface, but the corrective edit is still to the
document, so it stays in docs_consistency.

## Dropped as duplicates

None. Each of the 14 confirmed findings carries new 0.9.0-delta evidence not recorded in
[`planning/audit/2026-06-07-deep-audit.md`](2026-06-07-deep-audit.md) or
[`planning/deferred-work.md`](../deferred-work.md). The `deferred-work.md` lru_cache entry
appears here only as the *subject* of a finding (new evidence that PR #42 resolved it), not
as a restatement of a still-open item.

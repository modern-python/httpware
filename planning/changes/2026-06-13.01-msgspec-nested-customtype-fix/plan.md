# MsgspecDecoder Nested-CustomType Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `MsgspecDecoder.can_decode` return `False` for parameterized containers whose element type msgspec cannot natively decode (`list[PUser]`, `dict[str, PUser]`, etc.), so the client's `MissingDecoderError` pre-flight fires before a request is sent.

**Architecture:** Replace the top-level-only `isinstance(info, CustomType)` check in `can_decode` with a module-level recursive walker `_contains_custom_type` that rejects when any node anywhere in the `msgspec.inspect.type_info` tree is a `CustomType`. The walk is generic (visits any attribute that is a `Type` or tuple-of-`Type`) so it covers all container kinds and arbitrary nesting, and it stops at `Struct`/dataclass field boundaries automatically (those expose `fields` as `Field`, not `Type`), avoiding over-rejection and recursive-type loops.

**Tech Stack:** Python 3.11+, msgspec (`msgspec.inspect`), pydantic (test fixtures), pytest (`pytest-asyncio` auto mode), httpx2 `MockTransport`.

**Spec:** [planning/specs/2026-06-13-msgspec-nested-customtype-fix-design.md](../specs/2026-06-13-msgspec-nested-customtype-fix-design.md)

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `src/httpware/decoders/msgspec.py` | `MsgspecDecoder` + new `_contains_custom_type` helper | Modify |
| `tests/test_decoders_msgspec.py` | Unit tests for `can_decode` rejection/acceptance | Modify (append tests) |
| `tests/test_client_dispatch.py` | Integration regression: msgspec-only client raises `MissingDecoderError` without a request | Modify (append tests) |
| `planning/releases/0.9.1.md` | Patch release notes | Create |

No new source files. The walker lives beside `MsgspecDecoder` because it is private to that module and changes with it.

---

### Task 1: Recursive CustomType rejection in `can_decode`

**Files:**
- Modify: `src/httpware/decoders/msgspec.py:40-58` (the `can_decode` method) and add a module-level helper
- Test: `tests/test_decoders_msgspec.py` (append after the existing `test_msgspec_rejects_pydantic_basemodel`, ~line 110)

- [ ] **Step 1: Write the failing rejection + acceptance tests**

Append to `tests/test_decoders_msgspec.py`. The file already imports `msgspec`, `pydantic`, `pytest` and defines `_Item` (Struct), `_PydanticUser` (BaseModel), `_DC` (dataclass). Use PEP 604 `| None` for the optional case — the project forbids `from __future__ import annotations` and uses native union syntax, so no `typing` import is needed.

```python
@pytest.mark.parametrize(
    "model",
    [
        list[_PydanticUser],
        dict[str, _PydanticUser],
        _PydanticUser | None,
        tuple[_PydanticUser, int],
        list[list[_PydanticUser]],
        set[_PydanticUser],
    ],
)
def test_msgspec_rejects_containers_of_pydantic_models(model: type) -> None:
    """Nested CustomType (a pydantic model inside a container) must be rejected.

    Before the fix, can_decode inspected only the top-level type_info node, so a
    container parameterized by a BaseModel slipped past and built a decoder via
    the CustomType fallback — bypassing the MissingDecoderError pre-flight.
    """
    assert MsgspecDecoder().can_decode(model) is False


@pytest.mark.parametrize(
    "model",
    [
        _Item,
        list[_Item],
        dict[str, _Item],
        list[list[_Item]],
        dict[str, int],
        list[int],
        int,
    ],
)
def test_msgspec_still_accepts_native_containers(model: type) -> None:
    """Containers parameterized only by msgspec-native types stay accepted.

    Guards against the recursive walker over-rejecting: the walk must stop at
    Struct boundaries (StructType.fields are Field, not Type) and must not flag
    plain builtin element types.
    """
    assert MsgspecDecoder().can_decode(model) is True
```

- [ ] **Step 2: Run the new tests and confirm the rejection set FAILS**

Run: `just test tests/test_decoders_msgspec.py -k "rejects_containers or still_accepts_native"`

Expected: `test_msgspec_rejects_containers_of_pydantic_models` FAILS for every param (each currently returns `True` because the top-level node is a container, not a `CustomType`). `test_msgspec_still_accepts_native_containers` PASSES (those are genuinely accepted today). This proves the rejection tests target the real bug.

- [ ] **Step 3: Add the recursive walker**

In `src/httpware/decoders/msgspec.py`, after the `import msgspec` guard block and the `MISSING_DEPENDENCY_MESSAGE` / `T = TypeVar("T")` lines (before `class MsgspecDecoder`), add:

```python
def _contains_custom_type(info: "msgspec.inspect.Type") -> bool:
    """Return True if `info` is a CustomType or nests one in its parameters.

    Walks generic-container parameterization (list/dict/set/tuple/union element
    types) by visiting any attribute that is itself a `msgspec.inspect.Type` or a
    tuple of them. It deliberately does NOT descend into `StructType`/dataclass
    fields: those expose `fields` as `Field` objects (not `Type`), so the walk
    stops at the boundary of a type msgspec natively owns. That boundary is what
    makes the walk both correct (a Struct is a valid target) and safe against
    infinite recursion on self-referential struct definitions.
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
        elif (
            isinstance(value, tuple)
            and value
            and all(isinstance(item, msgspec.inspect.Type) for item in value)
        ):
            if any(_contains_custom_type(item) for item in value):
                return True
    return False
```

- [ ] **Step 4: Update `can_decode` to use the walker**

Replace the existing `can_decode` method (`src/httpware/decoders/msgspec.py:40-58`) with:

```python
    def can_decode(self, model: type) -> bool:
        """Return True iff msgspec natively understands `model` end-to-end.

        msgspec builds a Decoder for almost any class via a generic CustomType
        fallback; the Decoder constructor does NOT raise on unsupported types
        (e.g. pydantic.BaseModel, or a container parameterized by one). We walk
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

The second `try/except` (decoder-build probe) is kept as defense for any non-`CustomType` shape msgspec still refuses to build.

- [ ] **Step 5: Run the unit tests and confirm all PASS**

Run: `just test tests/test_decoders_msgspec.py`

Expected: PASS — both new parametrized tests green, and every pre-existing `can_decode` test (`test_msgspec_can_decode_struct`, `_dataclass`, `_dict`, `_list_of_structs`, `_primitive_int`, `_rejects_pydantic_basemodel`, `_uses_cache`, the two `patch`-based soft-no tests, `_unhashable_model_falls_back...`) still green — confirming no regression.

- [ ] **Step 6: Commit**

```bash
git add src/httpware/decoders/msgspec.py tests/test_decoders_msgspec.py
git commit -m "fix(decoders): reject nested CustomType in MsgspecDecoder.can_decode

list[PUser], dict[str, PUser], and other containers parameterized by a
pydantic BaseModel (any CustomType-falling element) were wrongly accepted
because can_decode inspected only the top-level type_info node. They now
route to MissingDecoderError before a request is sent.

Closes the High finding in planning/audit/2026-06-12-delta-audit.md.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: Dispatch-level regression (msgspec-only client, no request sent)

**Files:**
- Test: `tests/test_client_dispatch.py` (append at end of file)

This task encodes the user-facing symptom from the spec (acceptance criterion 3): a msgspec-only client asked for `list[_PydanticUser]` must raise `MissingDecoderError` **without** sending a request. The file already imports `AsyncClient, Client, MissingDecoderError`, `MsgspecDecoder`, `httpx2`, `pytest`, `HTTPStatus`, and defines `_PydanticUser`.

- [ ] **Step 1: Write the sync + async regression tests**

Append to `tests/test_client_dispatch.py`. The "transport must not be invoked" pattern (`pytest.fail` inside the handler, `# pragma: no cover`) mirrors the existing `test_async_missing_decoder_when_none_claim`.

```python
async def test_async_msgspec_only_list_of_basemodel_preflight_raises() -> None:
    """msgspec-only client + response_model=list[BaseModel] must raise
    MissingDecoderError before any request is sent (the 0.9.0-delta bug)."""

    def handler(_: httpx2.Request) -> httpx2.Response:  # pragma: no cover
        pytest.fail("transport should not be invoked: pre-flight must reject first")

    transport = httpx2.MockTransport(handler)
    client = AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=transport),
        decoders=[MsgspecDecoder()],
    )
    with pytest.raises(MissingDecoderError):
        await client.get("https://example.test/x", response_model=list[_PydanticUser])


def test_sync_msgspec_only_list_of_basemodel_preflight_raises() -> None:
    """Sync twin of the msgspec-only pre-flight regression."""

    def handler(_: httpx2.Request) -> httpx2.Response:  # pragma: no cover
        pytest.fail("transport should not be invoked: pre-flight must reject first")

    transport = httpx2.MockTransport(handler)
    client = Client(
        httpx2_client=httpx2.Client(transport=transport),
        decoders=[MsgspecDecoder()],
    )
    with pytest.raises(MissingDecoderError):
        client.get("https://example.test/x", response_model=list[_PydanticUser])
```

- [ ] **Step 2: Run the regression tests and confirm PASS**

Run: `just test tests/test_client_dispatch.py -k "msgspec_only_list_of_basemodel"`

Expected: PASS (both). These are green on arrival because Task 1 fixed the root cause — their role is to lock the user-facing contract at the client seam.

- [ ] **Step 3: Confirm the regression genuinely guards the behavior**

Prove the tests would have caught the pre-fix bug by temporarily reverting only the source change:

```bash
git stash push -- src/httpware/decoders/msgspec.py
just test tests/test_client_dispatch.py -k "msgspec_only_list_of_basemodel"
git stash pop
```

Expected: with the fix stashed, both tests FAIL — the handler's `pytest.fail` fires (a request is sent) instead of `MissingDecoderError`. After `git stash pop`, re-running shows PASS again. (If `git stash pop` reports a conflict, resolve by keeping the popped version — it is the fixed `msgspec.py`.)

- [ ] **Step 4: Commit**

```bash
git add tests/test_client_dispatch.py
git commit -m "test(client): regression for msgspec-only nested-CustomType pre-flight

A msgspec-only client asked for list[_PydanticUser] now raises
MissingDecoderError without sending a request. Sync + async twins.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: Full verification and 0.9.1 release notes

**Files:**
- Create: `planning/releases/0.9.1.md`

The project uses bare-semver git tags with hand-written release notes under `planning/releases/`; `pyproject.toml`'s `version` field is not the release source of truth and is **not** bumped here. Tagging/publishing is a manual finishing step, out of scope for this plan.

- [ ] **Step 1: Run the full lint + test suite**

Run: `just lint && just test`

Expected: lint clean (eof-fixer + ruff format + ruff check + ty check all pass — in particular no `BLE001`/`SLF001` surprises from the new helper, which carries its own `# noqa` only where the existing code does), and the full pytest suite green with no regressions.

- [ ] **Step 2: Write the release notes**

Create `planning/releases/0.9.1.md` (match the prose style of `planning/releases/0.8.1.md` — a one-line headline, "The gap", "The fix"):

```markdown
# httpware 0.9.1 — `MsgspecDecoder` stops claiming containers it can't decode

**Patch release with one behavior change.** When `MsgspecDecoder` is the only decoder registered (an msgspec-only install, or an explicit `decoders=[MsgspecDecoder()]`), a `response_model=` of `list[SomePydanticModel]`, `dict[str, SomePydanticModel]`, `SomePydanticModel | None`, or any container parameterized by a type msgspec can't natively decode now raises `MissingDecoderError` *before* a request is sent — instead of sending the request and failing at decode with `DecodeError`.

## The gap

`MsgspecDecoder.can_decode` answers the client's pre-flight question "can you decode this type?" — and on a `False` from every registered decoder, the client raises `MissingDecoderError` without touching the network. msgspec builds a `json.Decoder` for almost any type via a generic `CustomType` fallback, so `can_decode` used `msgspec.inspect.type_info` to detect and reject that fallback. But it inspected only the **top-level** node: `type_info(list[PUser])` is a `ListType` whose `item_type` is the `CustomType`, so the top-level check passed, the decoder built, and `can_decode` returned `True`. The pre-flight was bypassed, a real HTTP request went out, and `decode` then raised a validation error (surfaced as `DecodeError`). The false-positive was cached per instance, so every later request of that shape repeated the wasted round-trip.

Under the default pydantic-first `decoders=[PydanticDecoder(), MsgspecDecoder()]`, this was masked — pydantic claims `list[PUser]` first. The bug only bit msgspec-only configurations.

## The fix

`can_decode` now walks the full `type_info` tree and rejects if a `CustomType` appears **anywhere** in it, via a recursive helper that visits every nested element type (`list`/`dict`/`set`/`tuple`/`Optional`/`Union`, arbitrarily nested). The walk stops at `Struct`/dataclass field boundaries automatically, so genuine msgspec targets like `list[SomeStruct]` stay accepted and self-referential structs can't loop.

No public-API change: the `ResponseDecoder` protocol and `can_decode`'s signature are unchanged. Only the set of types `MsgspecDecoder` claims is corrected.
```

- [ ] **Step 3: Commit**

```bash
git add planning/releases/0.9.1.md
git commit -m "docs(release): draft 0.9.1 notes — msgspec nested-CustomType fix

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

- [ ] **Step 4: Report completion**

Summarize: the fix, the two test layers (unit rejection/acceptance + sync/async dispatch regression), full-suite green, and the drafted 0.9.1 notes. Note that tagging `0.9.1` is the remaining manual step. Then follow `superpowers:finishing-a-development-branch` to decide integration (this work is on `main` consistent with prior patch releases).

---

## Self-Review

**Spec coverage:**
- Recursive `CustomType` rejection + walker design → Task 1, Steps 3–4 (helper + `can_decode`).
- Walker stops at Struct boundary / no over-rejection → Task 1 acceptance test (`test_msgspec_still_accepts_native_containers`).
- Acceptance criterion 1 (reject `list[PUser]` & variants) → Task 1 rejection test.
- Acceptance criterion 2 (still accept `list[Struct]`, `Struct`, `dict[str,int]`) → Task 1 acceptance test.
- Acceptance criterion 3 (msgspec-only client raises `MissingDecoderError`, no request) → Task 2 sync+async tests.
- Acceptance criterion 4 (`just lint` + `just test` pass; no `pydantic.py` change; no API change) → Task 3 Step 1; no task touches `pydantic.py`.
- Acceptance criterion 5 (ships as 0.9.1 patch) → Task 3 release notes (tagging noted as manual).
- "Out of scope: perf nits, no `pydantic.py`" → honored; no caching changes in any task.

**Placeholder scan:** none — every code/command step shows literal content.

**Type/name consistency:** `_contains_custom_type` referenced identically in Steps 3 and 4; test fixtures (`_Item`, `_PydanticUser`, `_DC`) and helpers (`_async_client_with_body`/`_sync_client_with_body` not needed — Task 2 builds clients inline to attach a `pytest.fail` handler, matching the existing `test_async_missing_decoder_when_none_claim` pattern) all match the real files read during planning.

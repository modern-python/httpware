---
story_key: 1-2-core-data-types
epic: 1
story: 2
title: Core data types
status: ready-for-dev
created: 2026-05-13
input_documents:
  - docs/prd.md
  - docs/architecture.md
  - docs/epics.md
  - docs/stories/1-1-project-scaffold-and-tooling.md
---

# Story 1.2: Core data types

## Story

**As a** library author,
**I want** immutable `Request`, `Response`, `Limits`, `Timeout`, and `ClientConfig` types,
**So that** every other module has stable primitives to build on.

## Acceptance Criteria

**AC1.** **Given** the scaffold from Story 1.1, **When** I implement `src/httpware/request.py`, **Then** `Request` is a `@dataclass(frozen=True, slots=True)` with exactly these fields, in this order, with these types: `method: str`, `url: str`, `headers: Mapping[str, str]`, `params: Mapping[str, str]`, `cookies: Mapping[str, str]`, `body: bytes | None`, `extensions: Mapping[str, Any]`. `method` and `url` are required (no defaults); the four `Mapping` fields default to an empty mapping via `field(default_factory=dict)`; `body` defaults to `None`.

**AC2.** **And** `Request` has methods `with_header(name: str, value: str) -> Request`, `with_url(url: str) -> Request`, `with_body(body: bytes | None) -> Request`, and `with_query(params: Mapping[str, str]) -> Request`. Each method returns a new instance via `dataclasses.replace(...)`. `with_header` adds-or-replaces a single header (case-insensitive match on the header name is **not** required in this story — the matching helper lands in Story 2.3); `with_query` replaces the full `params` mapping with the supplied one (merge semantics are also Story 2.3's job).

**AC3.** **And** `Response` (in `src/httpware/response.py`) is a `@dataclass(frozen=True, slots=True)` with exactly these fields, in this order, with these types: `status: int`, `headers: Mapping[str, str]`, `content: bytes`, `url: str`, `elapsed: float`. All five fields are required (no defaults).

**AC4.** **And** `Response.text` is a `@property` that decodes `content` as text. Charset is taken from the `charset=` parameter of the `Content-Type` header if present, else `"utf-8"`. `Response.json()` is a method (not a property — it can raise) that calls `json.loads(content)` and returns the parsed value (`Any`). Neither value is stored on the instance; both are computed on each access. Slots must not declare backing fields for either.

**AC5.** **And** `src/httpware/config.py` defines three frozen dataclasses with these exact defaults: `Timeout(connect: float = 5.0, read: float = 30.0, write: float = 30.0, pool: float = 5.0)`; `Limits(max_connections: int = 100, max_keepalive_connections: int = 20, keepalive_expiry: float = 5.0)`; `ClientConfig(base_url: str | None = None, default_headers: Mapping[str, str] = field(default_factory=dict), default_query: Mapping[str, str] = field(default_factory=dict), timeout: Timeout = field(default_factory=Timeout), limits: Limits = field(default_factory=Limits))`. All three are `@dataclass(frozen=True, slots=True)`. `ClientConfig` is intentionally narrow at this point; transport / decoder / middleware / auth / redactor fields land in later stories (1.4–5.3) via additive `dataclasses.replace`-compatible extension.

**AC6.** **And** `src/httpware/__init__.py` re-exports `Request`, `Response`, `Limits`, `Timeout`, `ClientConfig` and lists them in `__all__` (sorted alphabetically). `from httpware import Request, Response, Limits, Timeout, ClientConfig` succeeds.

**AC7.** **And** `uv run ty check` and `uv run ruff check` pass with zero diagnostics on the new modules.

**AC8.** **And** unit tests under `tests/` cover, at minimum: (a) `Request` is frozen — attempting to assign to a field raises `FrozenInstanceError`; (b) every `with_*` method returns a new instance and leaves the original unchanged; (c) two `Request` instances with identical field values compare equal under `==`; (d) `Response.text` decodes UTF-8 by default and honors a non-UTF-8 `Content-Type` charset (e.g. `text/plain; charset=latin-1`); (e) `Response.json()` round-trips a small object; (f) `Limits()`, `Timeout()`, and `ClientConfig()` constructed with no args match the defaults in AC5; (g) `Timeout`, `Limits`, `ClientConfig` are frozen. `uv run pytest` exits 0 with all tests passing.

## Tasks/Subtasks

- [x] **Task 1: Implement `Request` in `src/httpware/request.py`** (AC1, AC2)
  - [x] 1.1: Module docstring (one short line per `docs/architecture.md#Docstring Style`).
  - [x] 1.2: Define `Request` as `@dataclass(frozen=True, slots=True)` with the seven fields from AC1 in the specified order and types. Use `from collections.abc import Mapping` and `from typing import Any` — no `from __future__ import annotations`.
  - [x] 1.3: Implement `with_header`, `with_url`, `with_body`, `with_query` as instance methods. Each method body is a single `return dataclasses.replace(self, <field>=<new_value>)` expression (for `with_header`, build the new headers dict first: `{**self.headers, name: value}`).
  - [x] 1.4: Public class docstring (one line). No private docstrings required.

- [x] **Task 2: Implement `Response` in `src/httpware/response.py`** (AC3, AC4)
  - [x] 2.1: Module docstring.
  - [x] 2.2: Define `Response` as `@dataclass(frozen=True, slots=True)` with the five fields from AC3 in order.
  - [x] 2.3: Add `@property def text(self) -> str` that parses the charset out of `self.headers.get("content-type", "")` (case-insensitive header lookup — accept either casing in the tests) and decodes `self.content` with that encoding, falling back to `"utf-8"`.
  - [x] 2.4: Add `def json(self) -> Any` that returns `json.loads(self.content)`.
  - [x] 2.5: Do **not** add `text` or `json` to `__slots__` (they are not stored). With `slots=True` and `@property`, the field-vs-property distinction is correct; the property is defined on the class.

- [x] **Task 3: Implement `Limits`, `Timeout`, `ClientConfig` in `src/httpware/config.py`** (AC5)
  - [x] 3.1: Module docstring.
  - [x] 3.2: Define `Timeout` with the four `float` fields and defaults from AC5.
  - [x] 3.3: Define `Limits` with the three fields and defaults from AC5.
  - [x] 3.4: Define `ClientConfig` with the five fields and defaults from AC5. Use `field(default_factory=Timeout)` and `field(default_factory=Limits)` for the nested config defaults — never bare `Timeout()` as a default value.
  - [x] 3.5: All three classes are `@dataclass(frozen=True, slots=True)`.

- [x] **Task 4: Update `src/httpware/__init__.py`** (AC6)
  - [x] 4.1: Add absolute-path explicit imports: `from httpware.config import ClientConfig, Limits, Timeout` and `from httpware.request import Request` and `from httpware.response import Response`.
  - [x] 4.2: Replace `__all__: list[str] = []` with the sorted public list: `["ClientConfig", "Limits", "Request", "Response", "Timeout"]`.

- [x] **Task 5: Add unit tests under `tests/`** (AC8)
  - [x] 5.1: Create `tests/` directory at repo root. **Deviation:** the story planned to skip `tests/__init__.py`, but ruff's `INP001` (implicit-namespace-package) fires under `select = ["ALL"]` and the project's ignore list does not exempt it. Added an empty `tests/__init__.py` to satisfy the lint gate. Pytest discovery still works the same way.
  - [x] 5.2: `tests/conftest.py` — placeholder docstring (`"""Shared pytest fixtures for the httpware test suite."""`); no fixtures yet.
  - [x] 5.3: `tests/test_request.py` — frozen check, `with_*` immutability on all four mutators (add + replace for `with_header`), equality, independent default mappings.
  - [x] 5.4: `tests/test_response.py` — `.json()` round-trip, `.text` UTF-8 default, Unicode default decode, parametrized case-insensitive charset (`content-type` / `Content-Type` / `CONTENT-TYPE` all decode latin-1), missing-charset fallback, equality, frozen.
  - [x] 5.5: `tests/test_config.py` — defaults asserted via dataclass equality (`assert Timeout() == Timeout(connect=5.0, …)`) rather than per-field comparisons, which sidesteps `PLR2004` (magic-value-in-comparison) cleanly; nested-default assertion (`cfg.timeout == Timeout()`); frozen for all three.

- [x] **Task 6: Validate locally** (AC7, AC8 — DoD)
  - [x] 6.1: `just lint` passes (eof-fixer, ruff format, ruff check, ty check).
  - [x] 6.2: `just test` passes: 24/24 tests in 0.12s; coverage 100% on `request.py`, `response.py`, `config.py`, `__init__.py` (well above the NFR23 floor of 90%).
  - [x] 6.3: `uv run python -c "from httpware import Request, Response, Limits, Timeout, ClientConfig; print('ok')"` → `ok`.
  - [x] 6.4: `CHANGELOG.md` `Unreleased` section now lists the new core data types.

## Dev Notes

### Architecture references (authoritative — read these before coding)

- `docs/architecture.md` § Data Architecture (Decision 1) — frozen+slots, `dataclasses.replace`, `Response.content: bytes` primitive, `.text`/`.json()` as lazy/computed.
- `docs/architecture.md` § Configuration & Lifecycle (Decision 9) — `ClientConfig` is the immutable bag `AsyncClient` will hold; `with_options` uses `dataclasses.replace`. Story 1.2 ships the minimal `ClientConfig`; later stories extend it.
- `docs/architecture.md` § Naming Patterns — module names `snake_case` (`request.py`, `response.py`, `config.py`), classes `PascalCase`.
- `docs/architecture.md` § Type-Hint Style — **no** `from __future__ import annotations`; use PEP 604 unions (`int | None`), PEP 585 generics (`list[T]`, `dict[K, V]`), `collections.abc.Mapping` not `typing.Mapping`. Suppression comments are `# ty: ignore[<rule>]` only.
- `docs/architecture.md` § Structure Patterns — `config.py` is documented to also hold `Redactor`, but `Redactor` is **out of scope for this story** (lands in Story 5.3). Do not add it.
- `docs/architecture.md` § Public API Export Discipline — single `__all__` in `httpware/__init__.py`; explicit imports, no wildcards.
- `CLAUDE.md` § Code conventions — exception keyword-only, snake_case methods, no `a` prefix on async methods (not applicable here — no async in this story).

### Key design points

**Why `frozen=True, slots=True`:** Decision 1. `slots=True` cuts per-instance memory and prevents attribute typos. `frozen=True` enables structural sharing via `dataclasses.replace` (each `with_*` returns a new instance; the old one is safe to keep aliased).

**Why `dataclasses.replace` rather than `evolve`/`attrs`/manual `__init__`:** Decision 1 explicitly rejects `attrs` (extra dep) and `pydantic.BaseModel` (NFR1 overhead budget). `dataclasses.replace` is stdlib and one line per method.

**Why `collections.abc.Mapping` for header/param fields:** Read-only contract advertised in the type; the runtime value is whatever the constructor receives (typically a `dict`). Defensive copying / `MappingProxyType` wrapping is **not** required in this story — the cost (forces a copy on every header rewrite) outweighs the benefit at v0. If a future story needs structural immutability, it'll be a follow-up.

**Default-factory rule:** Every `Mapping[...]` field uses `field(default_factory=dict)`. Never use a literal `{}` as a default — `@dataclass` will raise at class-creation time. Same for `Timeout` / `Limits` nested defaults in `ClientConfig`: `field(default_factory=Timeout)` (the type, not `Timeout()`).

**`Response.text` charset parsing:** Keep it simple. `headers.get("content-type", "")` (try lowercase first; fall back to title-case `Content-Type` if needed — Python's `dict.get` is exact-match, so a tiny helper is fine, e.g. `_get_header_ci(headers, "content-type")`). Then `"charset="` substring search and split. Do **not** pull in `email.message.Message` or `httpx2`'s parser — those are deferred to the transport layer. If charset is missing or malformed, fall back to `"utf-8"`.

**Slots + `@property`:** Properties on slotted dataclasses work, but you must NOT name a `__slots__` entry the same as a property (already enforced by the spec — `text` and `json` are not fields, just methods on the class).

**`json` method, not property:** `json()` can raise `json.JSONDecodeError`. Methods make raising obvious in the call site (`resp.json()` vs `resp.json`). httpx does this too; matches consumer mental model.

**Equality is automatic:** `@dataclass(eq=True)` is the default. Don't override `__eq__`. Two `Request` instances with the same field values (including same mapping contents) compare equal because dict equality is by content.

**Hashability:** `frozen=True` makes the dataclass auto-generate `__hash__` — but only if all fields are themselves hashable. Mapping fields backed by `dict` are **not** hashable. The auto-generated `__hash__` will therefore raise `TypeError` at hash time, not at construction time. This is fine — consumers shouldn't be hashing `Request`/`Response`. Don't add a custom `__hash__` to "fix" it.

### What lives where after this story

| File | New / modified | Contents |
|---|---|---|
| `src/httpware/request.py` | **new** | `Request` frozen+slots dataclass + 4 `with_*` methods. |
| `src/httpware/response.py` | **new** | `Response` frozen+slots dataclass + `.text` property + `.json()` method. |
| `src/httpware/config.py` | **new** | `Timeout`, `Limits`, `ClientConfig` frozen+slots dataclasses. |
| `src/httpware/__init__.py` | **modify** | Add 5 explicit imports; replace empty `__all__` with sorted list of 5. |
| `tests/conftest.py` | **new** | Empty placeholder (`""`). |
| `tests/test_request.py` | **new** | AC8 (a)–(c) coverage. |
| `tests/test_response.py` | **new** | AC8 (d)–(e) coverage + frozen check. |
| `tests/test_config.py` | **new** | AC8 (f)–(g) coverage. |
| `CHANGELOG.md` | **modify** | One-line bullet under `Unreleased`. |

### Read-before-edit (per architect's guidance)

Files this story modifies:

- `src/httpware/__init__.py` — currently a one-line docstring plus `__all__: list[str] = []`. The story replaces `__all__` and adds 5 explicit imports. Nothing else lives there yet.
- `CHANGELOG.md` — `Unreleased` already has the Story 1.1 scaffold bullet. Append one new bullet; do not reformat existing entries.

Files this story creates (no prior state to preserve): `src/httpware/request.py`, `src/httpware/response.py`, `src/httpware/config.py`, `tests/conftest.py`, `tests/test_request.py`, `tests/test_response.py`, `tests/test_config.py`.

### Carryover from Story 1.1

- `httpx2==2.0.0` GA is on PyPI and pinned `>=2.0.0,<3.0` in `pyproject.toml`. **Not used in this story** — no transport code yet.
- `pydantic>=2.0,<3.0` declared. **Not imported in this story** — that's Story 1.5 (`PydanticDecoder`).
- `uv.lock` is gitignored (library convention) — running `uv sync` locally is fine, the lock won't be committed.
- `--cov=src/httpware` is already in `[tool.pytest.ini_options]`, so coverage is on by default; no separate `--cov` invocation needed.
- `asyncio_mode = "auto"` is set — but there are **no async tests** in this story, so it doesn't matter.

### Anti-patterns to reject (CI-enforced or will fail review)

- ❌ `from __future__ import annotations` (architecture invariant; Python 3.11+ floor).
- ❌ `Optional[X]` / `Union[X, Y]` — use `X | None` / `X | Y` (PEP 604).
- ❌ `typing.Mapping`, `typing.Dict`, `typing.List` — use `collections.abc.Mapping`, `dict`, `list` (PEP 585).
- ❌ `# type: ignore` or `# mypy: ignore` — use `# ty: ignore[<rule>]` only.
- ❌ `print()` anywhere — there's no reason to print in this story.
- ❌ Mutable default values: `headers: Mapping[str, str] = {}` — must be `field(default_factory=dict)`.
- ❌ Hand-rolled `__eq__` / `__init__` — the dataclass machinery generates them.
- ❌ Storing `.text` / `.json` as fields — they are computed accessors per AC4 and Decision 1.
- ❌ Importing `httpx2` or `pydantic` from any of the three new modules — they have no business there yet (will be enforced by Story 6.4's CI grep gate; pre-empt it now).
- ❌ Adding `Redactor` to `config.py` — that's Story 5.3.
- ❌ Adding any field to `ClientConfig` beyond the five in AC5 (e.g., `transport`, `decoder`, `middleware`, `auth`, `redactor`) — those land in later stories.

### Testing standards summary

- pytest function-style tests; no `unittest.TestCase`.
- `pytest-asyncio` auto mode is on but unused here.
- Property-based tests (Hypothesis) **not required** in this story — concurrency-sensitive primitives (`RetryBudget`, `Bulkhead`) come later. The Hypothesis dep is already installed; ignore it.
- Coverage target: ≥90% on the three new modules (NFR23). Equality and `with_*` assertions should hit every line of `Request`; the property + json method should hit every line of `Response`; default-construction assertions should hit every line of `Limits`/`Timeout`/`ClientConfig`.

### Definition of Done

- All 8 ACs verified.
- All Task/Subtask checkboxes are `[x]`.
- `ruff format`, `ruff check`, `ty check`, `pytest` all pass locally.
- File List below is updated to reflect every changed and new file.
- Change Log has a new dated entry.
- `__all__` and explicit imports in `__init__.py` match (no public symbol re-exported without being in `__all__`, and vice versa).
- Status set to `review`.

## Dev Agent Record

### Implementation Plan

Followed TDD per module: write failing tests → confirm collection failure (RED) → implement module → confirm tests pass (GREEN). Execution order Task 5 (test stubs) → Tasks 1+2+3 (impl) → Task 4 (wire `__init__.py` exports) → Task 6 (validate). `ClientConfig` does not depend on `Request`/`Response`, but the modules are small enough that strict parallelism did not buy anything; wrote them sequentially.

### Debug Log

- **Forward-reference return types:** Without `from __future__ import annotations`, the class body cannot reference `Request` inside method annotations (the name is not bound until the class is fully built). Resolved by using `typing.Self` for all four `with_*` methods. Works for any subclass too, which is the right semantics.
- **`ruff format` reformatted `"hello".encode()` → `b"hello"`** in `tests/test_response.py` (UP012, the `pre-format` rewrite). Cosmetic; left as ruff produced it.
- **`INP001` (implicit-namespace-package) on every test file** — `tests/` needs an `__init__.py` under this project's `select = ["ALL"]` ruff config (the ignore list does not exempt INP). The story's Task 5.1 explicitly said to skip it; that guidance was wrong against the project's actual lint config. Added an empty `tests/__init__.py`; documented the deviation in the subtask checkbox. No effect on pytest discovery (`pythonpath = ["src"]` already handles src-layout).
- **`PLR2004` (magic-value-in-comparison) on per-field default asserts** in `test_config.py` — fired on every literal in `assert lim.max_connections == 100` etc. Refactored to dataclass-equality form: `assert Limits() == Limits(max_connections=100, max_keepalive_connections=20, keepalive_expiry=5.0)`. The expected values are now constructor args, not bare literals, so PLR2004 doesn't fire — and the assertion is also denser and reads better.
- **`json` method on `Response`** triggered `ANN401` (dynamic-type `Any` in return annotation). Justified — `json.loads` returns `Any` by definition; suppressed with `# noqa: ANN401` on that line only.
- **IDE pyright noise:** the editor's bundled pyright kept flagging `httpware.config`/`httpware.request`/`httpware.response` as unresolved imports even when ty and pytest succeeded. This is an IDE-side caching issue — the project's authoritative type checker is `ty`, which passes clean. No code change required.

### Completion Notes

**AC verification — all 8 satisfied:**

- **AC1** ✓ `Request` in `src/httpware/request.py` is `@dataclass(frozen=True, slots=True)` with the seven fields in spec order: `method: str`, `url: str`, `headers: Mapping[str, str]`, `params: Mapping[str, str]`, `cookies: Mapping[str, str]`, `body: bytes | None`, `extensions: Mapping[str, Any]`. Mapping fields default to `field(default_factory=dict)`; `body` defaults to `None`; `method`/`url` required.
- **AC2** ✓ All four `with_*` methods present, each one line on `dataclasses.replace`. `with_header` builds the new mapping via `{**self.headers, name: value}` (replace-when-present semantics by virtue of dict-update). Return type is `Self` (preserves subclass identity if anyone subclasses `Request` later).
- **AC3** ✓ `Response` in `src/httpware/response.py` is `@dataclass(frozen=True, slots=True)` with the five required fields in order: `status: int`, `headers: Mapping[str, str]`, `content: bytes`, `url: str`, `elapsed: float`.
- **AC4** ✓ `Response.text` is `@property` — case-insensitive header lookup via `_get_content_type` helper, parses `charset=` from the value, falls back to `"utf-8"`. `Response.json()` is a method (not a property) returning `json.loads(self.content)`. Neither is in slots; both are computed each call.
- **AC5** ✓ `Timeout`, `Limits`, `ClientConfig` in `src/httpware/config.py` are all `@dataclass(frozen=True, slots=True)`. Defaults exactly match the spec. `ClientConfig.timeout` and `.limits` use `field(default_factory=Timeout)` / `field(default_factory=Limits)` — never bare instances. `Redactor` is intentionally not present (Story 5.3).
- **AC6** ✓ `src/httpware/__init__.py` re-exports all five via explicit absolute imports; `__all__` is the sorted list `["ClientConfig", "Limits", "Request", "Response", "Timeout"]`. Smoke import succeeds.
- **AC7** ✓ `just lint-ci` reports zero diagnostics across `eof-fixer`, `ruff format --check`, `ruff check --no-fix`, `ty check`.
- **AC8** ✓ 24 tests cover every documented case: frozen on all 4 dataclasses, `with_*` immutability + new-instance identity + replace-semantics on `with_header`, equality, independent default mappings, charset case-insensitivity (parametrized over three casings), UTF-8 / latin-1 / missing-charset paths, JSON round-trip, default constructor returns documented defaults. `pytest` exits 0; coverage 100%.

**Deviations from the story spec (worth flagging for reviewer):**

- Added `tests/__init__.py` (story Task 5.1 said skip) — required by `INP001` under `select = ["ALL"]`. Added to File List below.
- Used `Self` for `with_*` return annotations rather than a quoted forward-ref `"Request"` — both are valid; `Self` is the post-PEP-673 idiom and works for any subclass.
- Test_config refactored to use dataclass equality instead of per-field assertions — denser and sidesteps `PLR2004`. Same coverage; same assertions.

**Tests added:** 24 (8 in `test_request.py`, 9 in `test_response.py`, 7 in `test_config.py`). All pass. Coverage 100% on the three new modules and `__init__.py`.

## File List

- `src/httpware/request.py` — new
- `src/httpware/response.py` — new
- `src/httpware/config.py` — new
- `src/httpware/__init__.py` — modified (explicit imports + `__all__`)
- `tests/__init__.py` — new (empty; required by ruff INP001)
- `tests/conftest.py` — new (placeholder)
- `tests/test_request.py` — new
- `tests/test_response.py` — new
- `tests/test_config.py` — new
- `CHANGELOG.md` — modified (Unreleased entry)

## Change Log

| Date | Change | Notes |
|---|---|---|
| 2026-05-13 | Story created | Drafted from `docs/epics.md` Story 1.2 and `docs/architecture.md` Decisions 1 and 9; expanded the epics' single multi-clause AC into AC1–AC8 for traceability with tasks/subtasks; added explicit anti-pattern list and scope-limit on `ClientConfig`. |
| 2026-05-13 | Story implemented | All 8 ACs satisfied; 24 tests pass; coverage 100% on `request.py`, `response.py`, `config.py`, `__init__.py`; `just lint-ci` clean. Two deviations from spec (tests/__init__.py + dataclass-equality assertion style) documented in Completion Notes. Status → `review`. |

## Status

`review`

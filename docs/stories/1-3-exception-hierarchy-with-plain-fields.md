---
story_key: 1-3-exception-hierarchy-with-plain-fields
epic: 1
story: 3
title: Exception hierarchy with plain fields
status: done
created: 2026-05-13
completed: 2026-05-13
input_documents:
  - docs/prd.md
  - docs/architecture.md
  - docs/epics.md
  - docs/stories/1-2-core-data-types.md
---

# Story 1.3: Exception hierarchy with plain fields

## Story

**As a** consumer developer,
**I want** a status-keyed exception hierarchy with plain typed fields,
**So that** I can catch `NotFoundError` etc. without importing `httpx2` and without inspecting transport types.

## Acceptance Criteria

**AC1.** **Given** the `Request`/`Response`/config types from Story 1.2, **When** I implement `src/httpware/errors.py`, **Then** the module defines exactly these classes in this inheritance shape:

- `ClientError(Exception)` — root of the entire `httpware` exception tree
- `TransportError(ClientError)`
- `TimeoutError(ClientError)` — deliberately shadows `builtins.TimeoutError`; see Dev Notes
- `StatusError(ClientError)`
  - `ClientStatusError(StatusError)`
    - `BadRequestError(ClientStatusError)`
    - `UnauthorizedError(ClientStatusError)`
    - `ForbiddenError(ClientStatusError)`
    - `NotFoundError(ClientStatusError)`
    - `ConflictError(ClientStatusError)`
    - `UnprocessableEntityError(ClientStatusError)`
    - `RateLimitedError(ClientStatusError)`
  - `ServerStatusError(StatusError)`
    - `InternalServerError(ServerStatusError)`
    - `ServiceUnavailableError(ServerStatusError)`

**AC2.** **And** `StatusError.__init__` is **keyword-only** (positional arguments raise `TypeError`) and takes exactly these parameters in this order: `status: int`, `body: bytes`, `headers: Mapping[str, str]`, `json: Any | None`, `request_method: str`, `request_url: str`. Each parameter is stored as an instance attribute of the same name and same type. `__init__` calls `super().__init__(...)` with a short summary message (suggested format: `f"{status} {request_method} {request_url}"`) so that `str(exc)` and `repr(Exception)` chaining behave sensibly; the message form is not contractual.

**AC3.** **And** every `StatusError` subclass (the 9 leaves plus `ClientStatusError` and `ServerStatusError`) inherits `StatusError.__init__` unchanged — leaves do **not** override `__init__`. `issubclass(NotFoundError, ClientStatusError) and issubclass(NotFoundError, StatusError) and issubclass(NotFoundError, ClientError)` is true; `issubclass(InternalServerError, ServerStatusError) and issubclass(InternalServerError, StatusError) and issubclass(InternalServerError, ClientError)` is true.

**AC4.** **And** the module defines a module-level `STATUS_TO_EXCEPTION: Mapping[int, type[StatusError]]` with **exactly these entries** (no others):

| status | class |
|---|---|
| 400 | `BadRequestError` |
| 401 | `UnauthorizedError` |
| 403 | `ForbiddenError` |
| 404 | `NotFoundError` |
| 409 | `ConflictError` |
| 422 | `UnprocessableEntityError` |
| 429 | `RateLimitedError` |
| 500 | `InternalServerError` |
| 503 | `ServiceUnavailableError` |

The dict's declared type annotation is `Mapping[int, type[StatusError]]`. The unknown-status fallback rule — 4xx → `ClientStatusError`, 5xx → `ServerStatusError` — is **documented in the module docstring and the `STATUS_TO_EXCEPTION` docstring/comment**; the resolution logic itself is the caller's responsibility (Story 1.4 inlines it at the transport seam). Story 1.3 ships the dict and the fallback **classes**, not a lookup helper.

**AC5.** **And** `__repr__` on any `StatusError` instance returns exactly: `f"<{type(self).__name__} status={self.status} method={self.request_method} url={self.request_url}>"`. The class name comes from `type(self).__name__` (so `NotFoundError(...).__repr__()` starts with `<NotFoundError`, not `<StatusError`). The `__repr__` **never** includes `body`, any header keys, or any header values — verified by a dedicated test. No `__str__` override (the message passed to `super().__init__()` already produces a reasonable `str()`).

**AC6.** **And** `TransportError` and `TimeoutError` are bare subclasses of `ClientError` with **no `__init__` override** in this story — they inherit `Exception.__init__` and accept the standard `*args, **kwargs` shape. They will be constructed at the `Httpx2Transport` seam in Story 1.4; field requirements for those two are deferred to that story's mapping work.

**AC7.** **And** `src/httpware/__init__.py` re-exports — via explicit absolute imports — every new class plus `STATUS_TO_EXCEPTION`, and extends `__all__` so it remains sorted alphabetically and now contains the prior 5 names plus 16 new entries (15 classes + the dict). The full expected sorted list is in Dev Notes → Public API Surface. `from httpware import NotFoundError, STATUS_TO_EXCEPTION, ClientError, StatusError` succeeds.

**AC8.** **And** `uv run ty check`, `uv run ruff format --check`, and `uv run ruff check` all pass with zero diagnostics on the new module and the modified `__init__.py`.

**AC9.** **And** unit tests under `tests/test_errors.py` cover, at minimum:

- (a) Class hierarchy via `issubclass` for every leaf → `ClientStatusError`/`ServerStatusError` → `StatusError` → `ClientError`; plus `TransportError`/`TimeoutError` → `ClientError`.
- (b) `StatusError.__init__` rejects positional arguments: `NotFoundError(404, b"", {}, None, "GET", "/x")` raises `TypeError`.
- (c) All 6 fields are stored on the instance and are equal to the constructor inputs (use a representative leaf like `NotFoundError`).
- (d) `__repr__` exact match for at least two cases: a 4xx leaf (`NotFoundError`, 404, `"GET"`, `"/users/1"`) and a 5xx leaf (`InternalServerError`, 500, `"POST"`, `"/x"`).
- (e) `__repr__` containment negative checks: with a body of `b"secret-token-abc"` and a header `{"Authorization": "Bearer s3cret"}`, `repr(exc)` does **not** contain `"secret-token-abc"`, `"Authorization"`, or `"s3cret"`.
- (f) `STATUS_TO_EXCEPTION` parametrized: assert `STATUS_TO_EXCEPTION[code] is cls` for every (code, cls) in the AC4 table; assert `len(STATUS_TO_EXCEPTION) == 9`.
- (g) Fallback usage: `STATUS_TO_EXCEPTION.get(418, ClientStatusError) is ClientStatusError` and `STATUS_TO_EXCEPTION.get(504, ServerStatusError) is ServerStatusError`.
- (h) `from httpware import …` smoke test: every newly exported symbol importable from the top-level package.

`uv run pytest` exits 0; coverage on `src/httpware/errors.py` is 100%.

## Tasks/Subtasks

- [x] **Task 1: Create `src/httpware/errors.py` skeleton** (AC1)
  - [x] 1.1: Module docstring — one short line: `"""Status-keyed exception hierarchy with plain typed fields."""`. Optional second paragraph documenting the 4xx → `ClientStatusError`, 5xx → `ServerStatusError` fallback rule.
  - [x] 1.2: Imports: `from collections.abc import Mapping`, `from typing import Any`. No `from __future__ import annotations`. No `httpx2` or `pydantic` imports.
  - [x] 1.3: Define `class ClientError(Exception):` with a one-line docstring; no body beyond `pass`/docstring.

- [x] **Task 2: Implement `StatusError` base** (AC2, AC5)
  - [x] 2.1: `class StatusError(ClientError):` with a one-line class docstring naming this as the base for HTTP-status-keyed errors.
  - [x] 2.2: Define `__init__(self, *, status: int, body: bytes, headers: Mapping[str, str], json: Any | None, request_method: str, request_url: str) -> None:` — the bare `*` enforces kwargs-only without naming a stand-in positional. Use `# noqa: A002` if ruff flags the `json` parameter name shadowing the stdlib module (it shouldn't, but be prepared). The `Any` annotation may trigger `ANN401`; suppress narrowly via `# noqa: ANN401` on the same line.
  - [x] 2.3: Body of `__init__`: assign all 6 fields to `self.<name>`, then call `super().__init__(f"{status} {request_method} {request_url}")`. Use plain attribute assignment — `StatusError` is **not** a dataclass (Exception subclasses do not play well with `@dataclass(frozen=True)`).
  - [x] 2.4: Define `def __repr__(self) -> str:` returning exactly `f"<{type(self).__name__} status={self.status} method={self.request_method} url={self.request_url}>"`. Use `type(self).__name__` so subclasses are formatted correctly.
  - [x] 2.5: Do **not** override `__str__`. `Exception.__str__` already returns the message passed to `super().__init__()`.
  - [x] 2.6: Annotate the 6 attributes as class-level type hints (so `ty` sees the types without requiring docstring round-trips):
    ```python
    status: int
    body: bytes
    headers: Mapping[str, str]
    json: Any
    request_method: str
    request_url: str
    ```
    Place them above `__init__` per ruff's preferred ordering. The `json` attribute annotation is `Any` even though the parameter accepts `Any | None` — this avoids `ty` complaining about union-narrowing on access.

- [x] **Task 3: Implement category bases and 9 leaf classes** (AC1, AC3)
  - [x] 3.1: `class ClientStatusError(StatusError):` — one-line docstring "Base for 4xx HTTP status errors."; no body otherwise.
  - [x] 3.2: `class ServerStatusError(StatusError):` — one-line docstring "Base for 5xx HTTP status errors."; no body otherwise.
  - [x] 3.3: Define the 7 client-side leaves as bare subclasses of `ClientStatusError`, each with a one-line docstring naming the status code: `BadRequestError` (400), `UnauthorizedError` (401), `ForbiddenError` (403), `NotFoundError` (404), `ConflictError` (409), `UnprocessableEntityError` (422), `RateLimitedError` (429). Each body is just `pass` or a docstring.
  - [x] 3.4: Define the 2 server-side leaves as bare subclasses of `ServerStatusError`: `InternalServerError` (500), `ServiceUnavailableError` (503). Same shape — docstring only.
  - [x] 3.5: Confirm no leaf overrides `__init__` or `__repr__` — they inherit `StatusError`'s machinery unchanged.

- [x] **Task 4: Define `STATUS_TO_EXCEPTION`** (AC4)
  - [x] 4.1: Place after the leaf classes (forward references would otherwise require strings).
  - [x] 4.2: Declare with explicit annotation: `STATUS_TO_EXCEPTION: Mapping[int, type[StatusError]] = {…}`. Use a plain dict literal as the runtime value; the `Mapping` annotation advertises read-only intent. Do **not** wrap in `types.MappingProxyType` for v0 (extra ceremony, no real benefit — Story 5.3 will revisit immutability if needed).
  - [x] 4.3: Populate with the 9 entries from the AC4 table, in numerical order. Add a single-line comment above the dict noting the fallback rule (unknown 4xx → `ClientStatusError`, unknown 5xx → `ServerStatusError`); do **not** implement the lookup logic in this module.

- [x] **Task 5: Define `TransportError` and `TimeoutError`** (AC6)
  - [x] 5.1: `class TransportError(ClientError):` — one-line docstring "Connection / network / protocol failure raised before a response was received.". Body: `pass` or docstring only.
  - [x] 5.2: `class TimeoutError(ClientError):` — one-line docstring "Client-side timeout (connect / read / write / pool).". Body: `pass` or docstring only. **Comment the deliberate shadow of `builtins.TimeoutError`** (one line) so future readers don't "fix" it.

- [x] **Task 6: Update `src/httpware/__init__.py`** (AC7)
  - [x] 6.1: Add explicit absolute-path imports from `httpware.errors`: all 14 exception classes and `STATUS_TO_EXCEPTION`. Single multi-line `from httpware.errors import (...)` block is fine; alphabetize the imported names for diff-friendliness.
  - [x] 6.2: Replace `__all__` with the final sorted list (21 entries — see Dev Notes → Public API Surface for the canonical order). Verify alphabetical order character-by-character (Python's `sorted()` is case-sensitive, but every symbol here is `PascalCase` or `UPPER_SNAKE` so simple lex order suffices; `STATUS_TO_EXCEPTION` sorts after `S…` classes — see canonical list below).
  - [x] 6.3: Update the module docstring only if needed (no change required — the existing line still applies).

- [x] **Task 7: Write `tests/test_errors.py`** (AC9)
  - [x] 7.1: Imports at top: `pytest`, every exception class under test, `STATUS_TO_EXCEPTION`. Import from `httpware` (top-level), not from `httpware.errors`, to incidentally test AC7's re-export.
  - [x] 7.2: Hierarchy tests (AC9.a): one parametrized test over `[(NotFoundError, ClientStatusError, StatusError, ClientError), (InternalServerError, ServerStatusError, StatusError, ClientError), …]` asserting `issubclass(leaf, parent)` for every intermediate parent in the chain. Include a test asserting `issubclass(TransportError, ClientError)` and `issubclass(TimeoutError, ClientError)`.
  - [x] 7.3: Kwargs-only enforcement (AC9.b): `with pytest.raises(TypeError): NotFoundError(404, b"", {}, None, "GET", "/x")`. Match `TypeError` message loosely (`pytest.raises(TypeError, match="positional")` is too strict — drop the `match=`).
  - [x] 7.4: Field-storage test (AC9.c): construct one `NotFoundError` with all 6 kwargs; assert each `exc.<field> == <input>`. Use a small sample object for `json` (e.g., `{"error": "not found"}`).
  - [x] 7.5: `__repr__` exact-match test (AC9.d): two cases — `NotFoundError` 404/`GET`/`/users/1` → exact string `"<NotFoundError status=404 method=GET url=/users/1>"`; `InternalServerError` 500/`POST`/`/x` → `"<InternalServerError status=500 method=POST url=/x>"`. Build expected strings as f-strings in the test for readability; use `==` not `match=` (we want exact, not regex).
  - [x] 7.6: `__repr__` redaction test (AC9.e): construct `NotFoundError(status=404, body=b"secret-token-abc", headers={"Authorization": "Bearer s3cret"}, json=None, request_method="GET", request_url="/x")`; assert each of `"secret-token-abc"`, `"Authorization"`, `"s3cret"` is **not** in `repr(exc)`. Multi-line assert with three separate `assert "…" not in r` statements reads cleaner than a single chained one.
  - [x] 7.7: `STATUS_TO_EXCEPTION` mapping test (AC9.f): parametrize over the 9 (code, class) pairs; assert `STATUS_TO_EXCEPTION[code] is cls`. Separate assert: `assert len(STATUS_TO_EXCEPTION) == 9` (catches accidental additions).
  - [x] 7.8: Fallback semantics test (AC9.g): `assert STATUS_TO_EXCEPTION.get(418, ClientStatusError) is ClientStatusError` and `assert STATUS_TO_EXCEPTION.get(504, ServerStatusError) is ServerStatusError`. Note: this is *documenting the intended caller idiom*, not testing module logic.
  - [x] 7.9: Re-export smoke test (AC9.h): `from httpware import ClientError, StatusError, NotFoundError, STATUS_TO_EXCEPTION, TransportError, TimeoutError`; assert `NotFoundError is httpware.errors.NotFoundError` (import both forms and compare with `is`).

- [x] **Task 8: Validate locally** (AC8, AC9 — DoD)
  - [x] 8.1: `just lint` passes (eof-fixer, ruff format, ruff check, ty check).
  - [x] 8.2: `just test tests/test_errors.py` passes; full `just test` passes (no regression on the 24 existing tests from Story 1.2); coverage on `errors.py` is 100% (term-missing output shows no uncovered lines).
  - [x] 8.3: `uv run python -c "from httpware import ClientError, StatusError, NotFoundError, STATUS_TO_EXCEPTION; print('ok')"` → `ok`.
  - [x] 8.4: `CHANGELOG.md` `Unreleased` → `Added`: one new bullet — e.g., `Status-keyed exception hierarchy with plain typed fields: ClientError, TransportError, TimeoutError, StatusError, ClientStatusError/ServerStatusError bases, 9 leaf classes (BadRequestError … ServiceUnavailableError), STATUS_TO_EXCEPTION lookup dict (Story 1.3).` — append below the existing Story 1.2 bullet, do not reformat existing entries.
  - [x] 8.5: Set the `status:` front-matter and the trailing `## Status` block to `review`. Update the File List below to reflect the actually-changed files.

### Review Findings (2026-05-13)

Adversarial code review (Blind Hunter + Edge Case Hunter + Acceptance Auditor). Acceptance Auditor verdict: **PASS** — all 9 ACs satisfied, anti-patterns clean, 100% coverage on `errors.py`. The following items surfaced from the Blind / Edge Case layers and need decisions or follow-up.

**Decisions resolved → patched:**

- [x] [Review][Decision→Patch] **Pickling broken — Dev Notes intent contradicted.** Resolution: added `_reconstruct_status_error` module-level helper and `StatusError.__reduce__` returning `(callable, (cls, status, body, dict(headers), json, method, url))`. New tests cover `pickle.dumps`/`pickle.loads` and `copy.deepcopy` round-trips with full field/`repr`/`str` equality. _Source: blind+edge_
- [x] [Review][Decision→Patch] **URL credentials leak in `__repr__` and `str(exc)`.** Resolution: added `_strip_userinfo` helper using `urllib.parse.urlsplit`/`urlunsplit`. `__repr__` and the summary message passed to `Exception.__init__` both run the URL through it, dropping `user:pass@` while preserving scheme, host, port, path, query. Tests cover credential redaction in `repr`/`str`, port preservation, and `@`-in-path no-op. Query-string secrets remain untouched (documented in module docstring; deferred to Story 5.3 `Redactor`). _Source: blind+edge_
- [x] [Review][Decision→Patch] **`httpware.TimeoutError` does NOT catch `builtins.TimeoutError` / asyncio timeouts.** Resolution: revisited Decision 3 — `TimeoutError` now multi-inherits `(ClientError, builtins.TimeoutError)`. `except builtins.TimeoutError` (asyncio.wait_for's form) and `except OSError` now catch httpware-raised timeouts; a bare `builtins.TimeoutError()` is NOT a `httpware.TimeoutError` (one-way relationship). Two new tests lock both directions. CHANGELOG calls out the architecture Decision 3 revisit. _Source: blind+edge_
- [x] [Review][Decision→Patch] **Fallback idiom misclassifies 1xx/2xx/3xx.** Resolution: module docstring and the comment above `STATUS_TO_EXCEPTION` now explicitly state the fallback assumes `400 <= status < 600` and that callers must guard non-error codes (1xx/2xx/3xx) before consulting the dict. Story 1.4 inherits this contract. _Source: edge_
- [x] [Review][Decision→Dismiss] **`headers: Mapping[str, str]` cannot represent multi-valued `Set-Cookie`.** Resolution: accept the v0 contract; revisit only on real consumer complaint. No code change. _Source: edge_
- [x] [Review][Decision→Patch] **Mutable headers/dict aliasing.** Resolution: `__init__` now wraps headers in `MappingProxyType(dict(headers))`. Two new tests cover defensive-copy semantics (caller mutation does not leak) and read-only semantics (`exc.headers[k] = v` raises `TypeError`). _Source: blind_
- [x] [Review][Decision→Patch] **Spec self-contradicts: canonical `__all__` order vs RUF022.** Resolution: updated Dev Notes → Public API Surface to publish the RUF022-shipped order (ALL-CAPS first) and documented why (CI is the gate, not `sorted()`). _Source: auditor_

**Patches applied:**

- [x] [Review][Patch] Added `__reduce__` to `StatusError` + pickle/deepcopy round-trip tests. [`src/httpware/errors.py:121-133`, `tests/test_errors.py:250-291`]
- [x] [Review][Patch] Strip userinfo in `__repr__` and `Exception.__init__` summary message + redaction/port/`@`-in-path tests. [`src/httpware/errors.py:25-38, 113, 117-120`, `tests/test_errors.py:172-217`]
- [x] [Review][Patch] Multi-inherit `TimeoutError(ClientError, builtins.TimeoutError)` + isinstance tests in both directions + CHANGELOG note on Decision 3 revisit. [`src/httpware/errors.py:69-79`, `tests/test_errors.py:56-66`, `CHANGELOG.md`]
- [x] [Review][Patch] Module docstring + `STATUS_TO_EXCEPTION` comment scoped fallback to `400 <= status < 600`. [`src/httpware/errors.py:1-16, 174-178`]
- [x] [Review][Patch] Defensive headers copy via `MappingProxyType(dict(headers))` + caller-mutation and read-only tests. [`src/httpware/errors.py:111`, `tests/test_errors.py:106-136`]
- [x] [Review][Patch] Updated Dev Notes canonical `__all__` to RUF022-shipped order. [story file]
- [x] [Review][Patch] Added test for missing-field kwargs rejection (`test_status_error_rejects_missing_kwarg`). [`tests/test_errors.py:74-76`]
- [x] [Review][Patch] Added direct-construction tests for `StatusError`, `ClientStatusError`, `ServerStatusError` (the fallback path Story 1.4 will rely on). [`tests/test_errors.py:220-248`]
- [x] [Review][Patch] Added docstring note in `StatusError.__init__` warning subclasses to call `super().__init__(...)` and documenting the headers defensive copy. [`src/httpware/errors.py:100-107`]

**Deferred (out of Story 1.3 scope — see `docs/deferred-work.md`):**

- [x] [Review][Defer] `request_method` / `request_url` CRLF / log-injection — transport seam should validate before crafting the request. [`errors.py:55,58`] — deferred to Story 1.4 review.
- [x] [Review][Defer] Header case-folding / case-sensitivity contract — transport seam concern; how `httpx2.Headers` maps to `Mapping[str, str]`. [`errors.py:33`] — deferred to Story 1.4.
- [x] [Review][Defer] `request_method` casing normalization — transport seam concern; `repr` echoes `"get"` as-is. [`errors.py:35`] — deferred to Story 1.4.

**Dismissed as noise / handled / out of charter (15 items):** STATUS_TO_EXCEPTION 408/502/504 omissions (anti-pattern); `MappingProxyType` wrapping (anti-pattern); `ClientError` root name (architecture-mandated); `<Name …>` repr style (AC5-mandated exact format); identity-equality on exceptions (standard behavior); status range / field type runtime validation (anti-pattern, "type checker is the gate"); `# noqa: A001` vs `A004` codes (both correct); `json: Any` vs `Any | None` annotation asymmetry (Dev Notes-documented); `json` parameter / attribute name (architecture-mandated); `len(STATUS_TO_EXCEPTION) == len(_STATUS_MAPPING)` tautology (deliberate strengthening per completion notes); 400–599 key-range assertion (paranoia); CHANGELOG "9 leaf classes" phrasing (accurate — 9 leaves + 6 bases = 15 classes); subclass attribute shadowing (normal Python); `__str__` not tested (spec says message form non-contractual); `from httpware import *` not tested (named-import test (h) already covers the re-export contract).

## Dev Notes

### Architecture references (authoritative — read these before coding)

- `docs/architecture.md` § **Decision 3 — Exception mapping at the seam** (lines 214–223). Story 1.3 ships the **destination** of the mapping (the classes + the dict); the **mapping itself** (httpx2 → httpware) is Story 1.4. Do not import `httpx2` from `errors.py`.
- `docs/architecture.md` § **Exception Construction** (lines 480–499). Authoritative source for: kwargs-only, mandatory 6 fields, `__repr__` format, no bare `Exception` raises. Treat this section as the literal spec.
- `docs/architecture.md` § **Pattern Examples — exception construction with keyword args** (lines 575–597). Shows the caller idiom Story 1.4 will use; informative but not part of this story.
- `docs/prd.md` **FR36–FR40** (lines 630–634). FR37 names every class the AC1 hierarchy must include; FR39 requires plain-typed fields on every exception; FR40 (CancelledError propagation) is out of scope for this story — it lives in the middleware/resilience modules.
- `docs/prd.md` **NFR7–NFR8** (lines 662–663). Default-redacted-header allowlist and "no body in default emissions". The Story 1.3 `__repr__` satisfies NFR8 by never including body or headers; full `Redactor` integration is Story 5.3.
- `docs/epics.md` Story 1.3 (lines 304–319) — authoritative AC source.
- `CLAUDE.md` § Code conventions — exception keyword-only, snake_case methods, `# ty: ignore[…]` only.
- `docs/stories/1-2-core-data-types.md` — same project conventions; this story follows the identical authoring style and test structure (function-style pytest, parametrize for combinatorial assertions, dataclass-equality form where useful).

### Key design points

**`ClientError` is the root.** A consumer who wants to catch every framework-raised error writes `except httpware.ClientError`. This includes `TransportError`, `TimeoutError`, and every `StatusError` leaf. Place `ClientError` at the top of `errors.py`.

**`StatusError.__init__` is keyword-only.** Use a bare-`*` separator: `def __init__(self, *, status, body, …)`. Do **not** use `KW_ONLY` from `dataclasses` — `StatusError` is not a dataclass (Exception + `@dataclass(frozen=True)` is a footgun on Python 3.11 because Exception's own `__init__` writes to `self.args`, which a frozen dataclass forbids; the failure mode is non-obvious). Plain attribute assignment in `__init__` is clearer and dodges the whole problem.

**Why no dataclass for exceptions.** Exceptions need to be raise-able and `pickle`-able and to interact with `__cause__` / `__context__` cleanly. Frozen dataclasses interfere with all three. A 10-line hand-written `__init__` plus `__repr__` is simpler than fighting the dataclass machinery — and it's what every major Python library does for typed-field exceptions (httpx, anthropic, openai-python).

**`json` parameter name.** Yes, it shadows the stdlib `json` module locally in the `__init__` signature. The architecture mandates this name (line 495) and the PRD (FR39) reinforces it. If ruff's `A002` (builtin-argument-shadowing) fires, suppress on the function-def line: `# noqa: A002`. Don't rename to `json_` or `body_json`.

**`Any` annotation for `json`.** The field can hold any JSON-decoded value (dict, list, str, int, float, bool, None) — there's no narrower type. `# noqa: ANN401` may be needed at the parameter-annotation site (matches the precedent set by `Response.json()` in Story 1.2). Storage annotation is `Any` (not `Any | None`) so attribute access doesn't require narrowing — `None` is a valid `Any` value.

**`__repr__` precise format.** The exact string is `<ExceptionClass status=NNN method=GET url=...>` — note: no quotes around the URL, no comma-after-elements, single space between key=value pairs. The architecture's line 497 is the contract. Test it with `==`, not regex.

**Why `__repr__` cannot include body/headers.** NFR8 ("no body in default emissions") combined with NFR7 (redaction allowlist) means a raw `body` in `repr` would leak secrets in tracebacks, log lines, and Sentry payloads. The user can still inspect `e.body` / `e.headers` deliberately — which Story 5.3's `Redactor` will guard at emission points. For Story 1.3, the safe path is: `repr` is minimal; raw attributes remain accessible.

**`TimeoutError` shadows `builtins.TimeoutError`.** Inside `httpware/errors.py` and downstream `from httpware import TimeoutError` consumers, the name resolves to `httpware.errors.TimeoutError`, not the builtin (which is `OSError`-based). This is **deliberate** — Decision 3 demands one client-facing timeout type, and forcing users to write `httpware.TimeoutError` everywhere defeats the ergonomics goal. Add a one-line comment in `errors.py` ("Deliberately shadows builtins.TimeoutError; see Decision 3.") so future readers do not "fix" it. The shadowing is local to the module and to consumer imports; it does not affect `asyncio.TimeoutError` (which `asyncio` raises internally and re-imports from `builtins` in 3.11+).

**`TransportError`/`TimeoutError` are bare in this story.** The Story 1.3 AC does not specify required fields for them. Story 1.4 (Httpx2Transport) constructs them at the mapping seam and will decide the constructor shape there. **Do not** add a `request_method` / `request_url` / `__init__` to them in this story — that's premature design and breaks the YAGNI rule. The story explicitly defers this (AC6).

**`STATUS_TO_EXCEPTION` is a plain dict, annotated `Mapping`.** The annotation advertises read-only contract; the runtime value is mutable but no caller mutates it (and Story 5.3 won't either). Skip `MappingProxyType` — the wrapping cost and import noise outweigh the benefit, and the architecture doesn't ask for it.

**Fallback logic lives at the call site.** The architecture pattern example (line 581) inlines:
```python
exc_class = STATUS_TO_EXCEPTION.get(
    resp.status_code,
    ClientStatusError if resp.status_code < 500 else ServerStatusError,
)
```
Story 1.4 will write that line inside `Httpx2Transport.__call__`. **Do not** add a `lookup_status_exception(status: int) -> type[StatusError]` helper to `errors.py` in this story — the AC4 wording ("documented in the module docstring") explicitly puts the fallback rule in prose, not code. A helper would be reasonable in a refactor later; not now.

**No bare `Exception` raises anywhere.** This is a global rule (architecture line 499). The errors module itself does not `raise`; it only declares classes. The rule applies to dev code that uses these classes.

### Public API Surface (canonical `__all__` after this story)

After Story 1.3, `httpware/__init__.py` must re-export exactly these 21 symbols in the order ruff's `RUF022` produces (ALL-CAPS / `UPPER_SNAKE` constants first, then mixed-case classes alphabetically). RUF022 is the CI gate, not Python's `sorted()` — they disagree on uppercase/lowercase ordering.

```python
__all__ = [
    "STATUS_TO_EXCEPTION",
    "BadRequestError",
    "ClientConfig",
    "ClientError",
    "ClientStatusError",
    "ConflictError",
    "ForbiddenError",
    "InternalServerError",
    "Limits",
    "NotFoundError",
    "RateLimitedError",
    "Request",
    "Response",
    "ServerStatusError",
    "ServiceUnavailableError",
    "StatusError",
    "Timeout",
    "TimeoutError",
    "TransportError",
    "UnauthorizedError",
    "UnprocessableEntityError",
]
```

That's 21 entries: 5 from Story 1.2 (`ClientConfig`, `Limits`, `Request`, `Response`, `Timeout`) + 15 new exception classes + 1 new dict (`STATUS_TO_EXCEPTION`). The CI gate is `ruff check`; trust RUF022's order. (Earlier drafts of this story used `sorted()`'s order, which puts `STATUS_TO_EXCEPTION` between `Response` and `ServerStatusError` — that order fails CI. The list above is the shipped order.)

### What lives where after this story

| File | New / modified | Contents |
|---|---|---|
| `src/httpware/errors.py` | **new** | `ClientError` root; `TransportError`/`TimeoutError` bare subclasses; `StatusError` with kwargs-only 6-field `__init__` and `__repr__`; `ClientStatusError`/`ServerStatusError` category bases; 9 leaf classes (`BadRequestError` … `ServiceUnavailableError`); `STATUS_TO_EXCEPTION` dict. |
| `src/httpware/__init__.py` | **modify** | Add `from httpware.errors import (...)` block (15 classes + `STATUS_TO_EXCEPTION`); replace `__all__` with the 21-entry sorted list. |
| `tests/test_errors.py` | **new** | All of AC9 (a)–(h). |
| `CHANGELOG.md` | **modify** | Append one bullet under `Unreleased` → `Added`. |

### Read-before-edit (per architect's guidance)

Files this story modifies (read current state before editing):

- `src/httpware/__init__.py` — currently 8 lines: module docstring, three `from httpware.<mod> import …` lines for the Story 1.2 types, blank line, `__all__ = [...]` with the 5 Story 1.2 entries. The story replaces `__all__` (now 21 entries) and adds one more `from httpware.errors import (...)` block above the existing imports (alphabetical by submodule: `config`, `errors`, `request`, `response`).
- `CHANGELOG.md` — `Unreleased` → `Added` already has bullets for Stories 1.1 and 1.2. Append one new bullet at the end of the `Added` list; do not reformat or reorder existing entries.

Files this story creates (no prior state to preserve): `src/httpware/errors.py`, `tests/test_errors.py`.

### Carryover from Story 1.2

- `from __future__ import annotations` is **forbidden** (architecture invariant; CI gate). Use `Self` (PEP 673) for any return type that references the class — though in this story, no class returns an instance of itself, so `Self` is not needed.
- `tests/__init__.py` already exists (empty; satisfies ruff `INP001`). Do not delete it; do not require a `tests/__init__.py` in this story's task list.
- `--cov=src/httpware` is in `[tool.pytest.ini_options]`; coverage runs by default.
- `asyncio_mode = "auto"` is set. **No async tests in this story** — no transport, no middleware, no client. Pure synchronous class definition + tests.
- `pythonpath = ["src"]` is set; src-layout imports work without further fuss.

### Anti-patterns to reject (will fail review or CI)

- ❌ `from __future__ import annotations`.
- ❌ `import httpx2` / `from httpx2 import …` anywhere in `errors.py`. The mapping seam is Story 1.4's job in `transports/httpx2.py`.
- ❌ `@dataclass(frozen=True)` on `StatusError` or any exception class — incompatible with `Exception.__init__`'s `args`-mutation.
- ❌ Positional `StatusError(404, b"", {}, None, "GET", "/x")` construction — must be kwargs-only.
- ❌ Including `body` or `headers` (raw bytes or any header key/value) in `__repr__`. NFR8.
- ❌ Adding `__init__` to `TransportError` or `TimeoutError` in this story (deferred to Story 1.4 — AC6).
- ❌ Adding a `lookup_status_exception(status)` helper, a `from_status()` classmethod, a `to_dict()` method, or any other utility beyond what AC1–AC7 mandate. **Scope discipline.**
- ❌ `Optional[X]` / `Union[X, Y]` — use `X | None` / `X | Y`.
- ❌ `typing.Mapping`, `typing.Dict` — use `collections.abc.Mapping`, `dict`.
- ❌ `# type: ignore`, `# mypy: ignore`, or bare `# noqa` (without a rule code).
- ❌ `print()` anywhere.
- ❌ Renaming the `json` parameter to `json_` or `body_json` to avoid `A002` — suppress instead.
- ❌ Wrapping `STATUS_TO_EXCEPTION` in `types.MappingProxyType`.
- ❌ Adding entries to `STATUS_TO_EXCEPTION` beyond the 9 listed (e.g., 402, 405, 406, 410, 502, 504) — those resolve to the fallback bases by design.
- ❌ Overriding `__init__` or `__repr__` on any leaf class — they inherit from `StatusError` cleanly.

### Testing standards summary

- pytest function-style tests; no `unittest.TestCase`.
- Parametrize combinatorial assertions (hierarchy, status-to-class mapping) — keeps the test file dense and readable.
- `pytest.raises(TypeError)` for the kwargs-only check; **no `match=` regex** (the message is interpreter-specific).
- Use `is` not `==` when comparing class objects: `STATUS_TO_EXCEPTION[404] is NotFoundError`.
- Coverage target: 100% on `errors.py` (the module is ~30 lines and every line is reachable from these tests). Coverage on `__init__.py` should remain 100% after the new imports.
- No Hypothesis tests in this story (no concurrency, no property-based invariants to check).
- No async tests in this story.

### Definition of Done

- All 9 ACs verified (each AC mapped to at least one test in `tests/test_errors.py`, or to a check in `just lint`).
- All Task/Subtask checkboxes are `[x]`.
- `ruff format`, `ruff check`, `ty check`, `pytest` all pass locally with zero diagnostics.
- File List below is updated to reflect every changed and new file.
- Change Log has a new dated entry.
- `httpware/__init__.py`'s `__all__` and explicit imports are in lockstep (every entry in `__all__` is imported; every imported symbol is in `__all__`).
- Front-matter `status:` and trailing `## Status` are both set to `review`.

### Open questions / things to flag for reviewer

- **`STATUS_TO_EXCEPTION` in `__all__`** — Story 1.3 AC7 says "`__all__` lists every exception", which arguably excludes the dict. This story exports it anyway because the architecture (line 533, "Single source of truth: `httpware/__init__.py` defines `__all__` listing every public symbol") treats `__all__` as the full public surface. If the reviewer prefers it left out of `__all__` (importable but not re-advertised), drop the `"STATUS_TO_EXCEPTION"` entry and the `Public API Surface` list shrinks to 20 entries. Flag for review.
- **Parent class of `TransportError` and `TimeoutError`** — the AC lists them without explicit parens. This story interprets them as `(ClientError)` because (a) `except httpware.ClientError` should catch every framework error and (b) FR36 ("framework raises `httpware`-owned exceptions only") is the strongest single signal. If the reviewer prefers them rooted elsewhere (e.g., `(Exception)` directly), it's a one-character change per class. Flag for review.
- **`StatusError` message form** — AC2 says "calls `super().__init__(...)` with a short summary message"; the suggested form `f"{status} {request_method} {request_url}"` is not contractual. If the reviewer prefers e.g. `f"{request_method} {request_url} -> {status}"` or no message at all, change the one line.

## Change Log

| Date | Change | Notes |
|---|---|---|
| 2026-05-13 | Story created | Drafted from `docs/epics.md` Story 1.3 and `docs/architecture.md` Decision 3 + Exception Construction section; expanded the epic's single multi-clause AC into AC1–AC9 for traceability with tasks; added canonical `__all__` list, anti-pattern catalog, three explicit open questions for reviewer. |
| 2026-05-13 | Story implemented | All 9 ACs satisfied; 29 new tests in `tests/test_errors.py` (56 total project-wide, all pass); coverage 100% on `errors.py` (and 100% retained on the 4 prior modules); `just lint-ci` clean. Four minor deviations from spec (RUF022 `__all__` order, unused A002 suppression removed, added PLR0913, len-against-parametrize) documented in Completion Notes. Status → `review`. |

## Dev Agent Record

### Implementation Plan

Followed TDD per the story Task order: wrote `tests/test_errors.py` first to lock in AC9 (a)–(h), confirmed `ModuleNotFoundError` on collection (RED), then implemented `src/httpware/errors.py` with `ClientError` root → `TransportError`/`TimeoutError` bare subclasses → `StatusError` with kwargs-only 6-field `__init__` and `__repr__` → `ClientStatusError`/`ServerStatusError` bases → 9 leaf classes → `STATUS_TO_EXCEPTION` dict. Wired `src/httpware/__init__.py` last — added the `from httpware.errors import (...)` block and rebuilt `__all__` to the 21-symbol surface. Validated with `just lint-ci` and full `pytest` regression at each step.

### Debug Log

- **`ruff format` collapsed `__repr__` body** from a 3-line f-string concatenation into a single-line f-string. Cosmetic; left as ruff produced it.
- **`A004` (import-shadowing-builtin) fired on `TimeoutError`** in both `src/httpware/__init__.py` and `tests/test_errors.py`. Suppressed with `# noqa: A004` on the import line, per architecture Decision 3 (deliberate shadow of `builtins.TimeoutError`).
- **`A002` (builtin-argument-shadowing) on `json` parameter** in `StatusError.__init__` did **not** fire — `json` is a stdlib module, not a builtin, so A002's scope doesn't catch it. The pre-emptive `# noqa: A002` from the story file flagged as `RUF100` (unused noqa); removed it.
- **`PLR0913` (too-many-arguments)** fired on `StatusError.__init__` because the kwargs-only `*` separator does not exempt the parameters from the count. Suppressed with `# noqa: PLR0913` on the `def` line — the 6 fields are mandated by the spec and not negotiable.
- **`PLR2004` (magic-value-in-comparison) on `assert exc.status == 404`** in field-storage test — refactored to extract inputs to local variables (`status = 404`; `assert exc.status == status`); same coverage, no literals in comparisons.
- **`PLR2004` on `assert len(STATUS_TO_EXCEPTION) == 9`** — replaced with `assert len(STATUS_TO_EXCEPTION) == len(_STATUS_MAPPING)`. This is stronger than the original: any drift between the dict and the parametrize table now fails the test.
- **`ty` complained about positional construction** in `test_status_error_rejects_positional_args` — the call deliberately raises `TypeError` at runtime, so `ty`'s static check (`missing-argument` and `too-many-positional-arguments`) needs both rule codes suppressed: `# ty: ignore[missing-argument, too-many-positional-arguments]`.
- **`RUF022` sorted `__all__`** with `STATUS_TO_EXCEPTION` first (ALL-CAPS constants ahead of mixed-case classes), which differs from the spec's canonical list that placed it between `Response` and `ServerStatusError`. Per the spec's own guidance ("If sorted() produces a different order than what's written above, trust sorted() and update the file"), accepted ruff's ordering — CI is authoritative.
- **IDE pyright noise:** the editor's bundled pyright kept flagging `httpware.errors` as unresolved. Same caching issue documented in Story 1.2's Debug Log — `ty` and `pytest` both pass clean. No code change.

### Completion Notes

**AC verification — all 9 satisfied:**

- **AC1** ✓ `src/httpware/errors.py` defines the exact 15-class hierarchy: `ClientError` root; `TransportError`/`TimeoutError` direct subclasses; `StatusError` with `ClientStatusError`/`ServerStatusError` category bases and 9 leaves (`BadRequestError`/`UnauthorizedError`/`ForbiddenError`/`NotFoundError`/`ConflictError`/`UnprocessableEntityError`/`RateLimitedError` under client; `InternalServerError`/`ServiceUnavailableError` under server).
- **AC2** ✓ `StatusError.__init__` uses a bare-`*` to enforce kwargs-only. Six fields stored in spec order via plain `self.<name>` assignment, then `super().__init__(f"{status} {request_method} {request_url}")`.
- **AC3** ✓ All 9 leaves plus `ClientStatusError`/`ServerStatusError` are bare subclasses (docstring only); no `__init__` or `__repr__` overrides. Verified by `test_leaf_inherits_full_chain` parametrized over 9 leaves.
- **AC4** ✓ `STATUS_TO_EXCEPTION: Mapping[int, type[StatusError]]` declared with the explicit annotation; plain dict literal; 9 entries exactly matching the AC4 table. Fallback rule documented in the module docstring; no lookup helper added (deferred to Story 1.4's transport seam).
- **AC5** ✓ `__repr__` returns `f"<{type(self).__name__} status=... method=... url=...>"` — uses `type(self).__name__` so leaves render their own class name. `test_repr_format_4xx_leaf` and `test_repr_format_5xx_leaf` lock the exact strings; `test_repr_does_not_leak_body_or_headers` asserts NFR8 (body/header content cannot appear in `repr`).
- **AC6** ✓ `TransportError` and `TimeoutError` are bare `(ClientError)` subclasses — no `__init__` override. Story 1.4 will construct them at the `Httpx2Transport` seam.
- **AC7** ✓ `src/httpware/__init__.py` re-exports all 15 new classes plus `STATUS_TO_EXCEPTION` via an explicit absolute-path `from httpware.errors import (...)` block; `__all__` has all 21 symbols sorted per `ruff` RUF022 (ALL-CAPS first).
- **AC8** ✓ `just lint-ci` reports zero diagnostics across eof-fixer / `ruff format --check` / `ruff check --no-fix` / `ty check`.
- **AC9** ✓ `tests/test_errors.py` covers (a) hierarchy parametrized over 9 leaves + `TransportError`/`TimeoutError`, (b) kwargs-only `TypeError`, (c) 6-field storage, (d) `__repr__` exact match for 4xx and 5xx leaves, (e) redaction (body / "Authorization" / value all absent from `repr`), (f) parametrized status-to-class mapping over the 9 entries plus length assertion against the parametrize list, (g) fallback `.get(...)` semantics for both 4xx and 5xx, (h) re-export `is`-identity from `httpware` top-level vs `httpware.errors`. 29 new tests added; 56/56 total pass; coverage 100% on `errors.py` (and 100% retained on the rest).

**Deviations from the story spec (worth flagging for reviewer):**

- `__all__` is sorted by ruff RUF022 with `STATUS_TO_EXCEPTION` first (ALL-CAPS constants ahead of mixed-case class names), not in the order documented in Dev Notes → Public API Surface. The spec itself authorized trusting `sorted()` if it differs; this story trusts ruff's RUF022 since it's the CI gate.
- `# noqa: A002` removed from the `json` parameter line — ruff did not actually flag it (A002 doesn't target stdlib-module names), so the pre-emptive suppression was unused (RUF100). The story file flagged this as a possibility ("Use `# noqa: A002` if ruff flags... it shouldn't, but be prepared").
- Added `# noqa: PLR0913` on `StatusError.__init__` — not in the story file's anti-pattern list, but unavoidable: kwargs-only `*` does not exempt parameters from the argument count.
- `test_status_to_exception_has_only_nine_entries` asserts `== len(_STATUS_MAPPING)` rather than `== 9`. The spec called for catching "accidental additions" — comparing against the parametrize list makes that test self-reinforcing.

**Tests added:** 29 (in `tests/test_errors.py`). All pass. Coverage 100% on `errors.py`; 100% retained on the 4 prior modules.

## File List

- `src/httpware/errors.py` — new
- `src/httpware/__init__.py` — modified (added `from httpware.errors import (...)` block; `__all__` expanded from 5 to 21 entries)
- `tests/test_errors.py` — new
- `CHANGELOG.md` — modified (one new bullet under `Unreleased` → `Added`)

## Status

`done`

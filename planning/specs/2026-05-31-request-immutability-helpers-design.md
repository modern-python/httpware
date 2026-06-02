# Request / Response immutability helper expansion (design)

- **Date:** 2026-05-31
- **Status:** approved, ready for plan
- **Scope:** Story 2-3 (third story of Epic 2). Extends the existing `with_*` helper grid on `Request` and adds the missing helpers on `Response`. Out of scope: auth coercion (2-4), AsyncClient wiring (2-5), streaming (Epic 4).
- **Roadmap pointer:** `docs/dev/engineering.md` §8 "Epic 2 — Compose request-handling logic via middleware".

## Why

Middleware (Story 2-1) and the phase decorators (Story 2-2) now exist. The remaining gap before middleware-driven request rewriting is ergonomic: `Request` currently exposes `with_header`, `with_url`, `with_body`, `with_query` (Story 1-2), but no plural `with_headers`, no `with_cookie`/`with_cookies`, no `with_extension`/`with_extensions`. `Response` has no `with_*` helpers at all. Middleware authors can technically work around the gaps via `dataclasses.replace`, but the framework should ship the ergonomic API directly.

The archived epic spec (`docs/archive/epics.md` Story 2.3) calls for `with_headers` on `Request`, plus `with_headers` and `with_status` on `Response`. `docs/dev/engineering.md` §8 broadens the scope to include `with_cookie` and `with_extension`. This spec adopts the broader scope.

## Decisions

| Decision | Choice |
| --- | --- |
| Scope | Pragmatic — archive's list plus cookies and extensions. 5 new on `Request`, 2 new on `Response`. |
| Naming convention | `with_X(name, value)` singular → set/replace one entry. `with_Xs(items)` plural → merge `items` into collection; incoming keys override existing. |
| `with_query` legacy semantics | Untouched. Still REPLACES all params. Asymmetric with `with_headers` (which merges); the asymmetry is justified by usage patterns (see rationale below). |
| Merge implementation | `{**existing, **incoming}` for all plural merges. Naive dict merge, no case normalization, no validation. |
| Existing `with_header` etc. | Untouched. No signature changes, no semantic changes. |
| Validation | None. Value objects don't enforce protocol semantics; `with_status(99)` is allowed. |
| Short-circuit on empty input | None. `with_headers({})` allocates a fresh instance via `dataclasses.replace`. Micro-cost not worth the conditional. |
| Case-insensitive header keys | Out of scope. Existing v0 contract assumes lowercase ASCII keys; the broader case-insensitive `Mapping[str, str]` redesign is in `deferred-work.md`. |
| `StreamResponse.with_*` | Out of scope. Designed in Story 4-1 alongside the streaming type itself. |
| `__all__` updates | None. `Request` and `Response` are already exported; their methods come along. |

### Rationale for `with_query` REPLACE vs `with_headers` MERGE

Three points map the asymmetry to real differences in how the two collections are used:

1. **Common operation differs.** Headers are *added on top* of an already-large set (5–20+ entries, most owned by the framework — `Content-Type`, `Accept`, `User-Agent`, auth, transport encoding). Middleware adds trace IDs / signatures without disturbing them. Query params are *constructed* from a small user-owned set (0–5 items) — pagination cursors, search filters, etc. Easier to rebuild wholesale than to merge.
2. **HTTP semantics.** Repeated headers carry meaning (`Set-Cookie`, `Via`, `Link`). Silent loss via REPLACE would break correctness. Query strings have no analogous protocol-level repetition semantics; replacement is safe.
3. **Singular escape hatches exist for headers, not query.** `with_header(name, value)` covers "set one." If `with_headers` also REPLACED, middleware would write `with_headers({**req.headers, "x-trace": "abc"})` everywhere — clumsy. For query params, REPLACE is the common path; the rarer "add one without losing the rest" can be expressed when needed.

## File structure

**Modified files:**

```
src/httpware/request.py       # add 5 helpers (~20 lines added)
src/httpware/response.py      # add 2 helpers (~10 lines added) + Self import
tests/test_request.py         # append 10 new tests
tests/test_response.py        # append 4 new tests
CHANGELOG.md                  # append Story 2.3 bullet under [Unreleased] / ### Added
```

**Files not touched:** every other source/test file. Purely additive.

## Request helpers — implementation

Append to `src/httpware/request.py`, after the existing `with_query` method:

```python
def with_headers(self, headers: Mapping[str, str]) -> Self:
    """Return a copy with the given headers merged in (incoming keys override existing)."""
    return dataclasses.replace(self, headers={**self.headers, **headers})

def with_cookie(self, name: str, value: str) -> Self:
    """Return a copy with the given cookie added or replaced."""
    return dataclasses.replace(self, cookies={**self.cookies, name: value})

def with_cookies(self, cookies: Mapping[str, str]) -> Self:
    """Return a copy with the given cookies merged in (incoming keys override existing)."""
    return dataclasses.replace(self, cookies={**self.cookies, **cookies})

def with_extension(self, name: str, value: Any) -> Self:  # noqa: ANN401
    """Return a copy with the given extension entry added or replaced."""
    return dataclasses.replace(self, extensions={**self.extensions, name: value})

def with_extensions(self, extensions: Mapping[str, Any]) -> Self:
    """Return a copy with the given extensions merged in (incoming keys override existing)."""
    return dataclasses.replace(self, extensions={**self.extensions, **extensions})
```

No new imports needed — `dataclasses`, `Mapping`, `Any`, `Self` are already imported at the top of the file.

## Response helpers — implementation

Append to `src/httpware/response.py`, after the existing `json` method. Two import additions:

1. The class needs `Self`: change `from typing import Any` to `from typing import Any, Self`.
2. The class needs `dataclasses.replace`: add a top-level `import dataclasses` line (alongside the existing `from dataclasses import dataclass`). This matches the pattern in `src/httpware/request.py`, which has both `import dataclasses` and `from dataclasses import dataclass, field`.

```python
def with_headers(self, headers: Mapping[str, str]) -> Self:
    """Return a copy with the given headers merged in (incoming keys override existing)."""
    return dataclasses.replace(self, headers={**self.headers, **headers})

def with_status(self, status: int) -> Self:
    """Return a copy with the given status code."""
    return dataclasses.replace(self, status=status)
```

The two new helpers go on `Response`, not on `StreamResponse`.

## Testing

### `tests/test_request.py` — 10 new tests

| Test | Verifies |
| --- | --- |
| `test_with_headers_merges_new_headers` | `req.with_headers({"a": "1"})` adds the entry; `req.headers` unchanged. |
| `test_with_headers_overrides_existing_key` | Incoming key replaces existing value. |
| `test_with_headers_preserves_other_keys` | Existing keys not in the incoming mapping survive. |
| `test_with_headers_empty_mapping_returns_distinct_copy` | `with_headers({})` returns a new instance equal-but-not-identical to the original. |
| `test_with_cookie_adds_single_cookie` | `with_cookie("session", "abc")` adds; original `cookies` unchanged. |
| `test_with_cookie_replaces_existing_cookie` | Setting an existing cookie name replaces the value. |
| `test_with_cookies_merges_new_cookies` | Plural merges; incoming overrides. |
| `test_with_extension_adds_single_entry` | `with_extension("timeout", 5.0)` adds to extensions. |
| `test_with_extensions_merges_new_entries` | Plural merges. |
| `test_with_extension_accepts_any_value_type` | Extensions accept `int`, `dict`, custom object instance — `Any`-typed. |

### `tests/test_response.py` — 4 new tests

| Test | Verifies |
| --- | --- |
| `test_with_headers_merges_new_headers` | `resp.with_headers({"x-trace": "abc"})` adds; original unchanged. |
| `test_with_headers_overrides_existing_key` | Merge override semantics. |
| `test_with_status_replaces_status` | `resp.with_status(503)` replaces status; other fields unchanged. |
| `test_with_status_accepts_arbitrary_int` | `with_status(99)` works without validation. |

### Cross-cutting test patterns

Each test follows the same template: construct a baseline `Request` / `Response`, call the helper, assert the returned instance has the expected change, assert the original is unchanged, assert the returned instance is a distinct object (`returned is not original`).

No new fixtures, no async tests, no transport interaction.

**Coverage expectation:** 100% line coverage on the seven new helper bodies. Each helper is one line; each test exercises one helper.

## Constraints and invariants

- **No `httpx2` import.** Neither modified file imports `httpx2`.
- **No `from __future__ import annotations`.** PEP 604/585 syntax is native.
- **No `print()`, no `logging.basicConfig`.** Value-object helpers do no logging.
- **No `# type: ignore`.** `# noqa: ANN401` on `with_extension`'s `value: Any` parameter is the only suppression; intentional and matches `Response.json`'s existing pattern.
- **Existing helpers untouched.** `with_header`, `with_url`, `with_body`, `with_query` keep their current signatures and semantics.

## Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| `ty` flags `dict[str, str]` (the literal merged dict) as not assignable to `Mapping[str, str]` field. | `dict` is a `Mapping`; ty should accept the assignment. If it doesn't, cast at the assignment site with `Mapping[str, str]` annotation — but no cast expected. Story 1-2's existing `with_header` uses the same pattern (`{**self.headers, name: value}`) and passes ty cleanly. |
| Caller mixes `"X-Trace"` and `"x-trace"` keys via `with_headers`. | Documented v0 limitation; the merged dict will have both. Same behavior as the existing `with_header` and tracked in `planning/deferred-work.md` under the broader case-insensitive Mapping work. Don't try to fix here. |
| Future call sites expect `with_headers` to REPLACE rather than MERGE. | Docstring is explicit ("merged in"). The phase decorators in Story 2-2 already follow this convention implicitly (e.g., `@after_response` rebuilds `Response(...)` rather than calling a non-existent helper). Anyone reading the docstring will see the semantics. |
| `Self` import on `Response` triggers ruff `I001` (import-sorting). | The import line `from typing import Any, Self` is alphabetic. ruff format will resolve any ordering. |

## Definition of done

- `src/httpware/request.py` exports 5 new helpers: `with_headers`, `with_cookie`, `with_cookies`, `with_extension`, `with_extensions`.
- `src/httpware/response.py` exports 2 new helpers: `with_headers`, `with_status`, and imports `Self` from `typing`.
- `tests/test_request.py` contains 10 new tests; all pass.
- `tests/test_response.py` contains 4 new tests; all pass.
- `CHANGELOG.md` has a Story 2.3 bullet under `[Unreleased]` / `### Added`.
- `just test` shows the increment from baseline; 100% line coverage on the new helpers.
- `just lint-ci` clean.
- `tests/test_no_httpx2_leakage.py` still passes.
- Story 2-3 lands as a single PR off `main` via the branch `story/2-3-request-immutability-helpers`.

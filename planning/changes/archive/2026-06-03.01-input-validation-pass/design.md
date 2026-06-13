---
status: shipped
date: 2026-06-03
slug: input-validation-pass
supersedes: null
superseded_by: null
pr: 19
outcome: 'Input-validation hardening'
---

# Input-validation pass (design)

- **Date:** 2026-06-03
- **Status:** draft, awaiting user review
- **Scope:** Five small validation/parser fixes accumulated in `planning/deferred-work.md` from the Story-1-2 review. All five are v0-contract gaps in the value-object layer (`Request`, `Response`, `Timeout`, `Limits`, `ClientConfig`). Bundled as one PR because each is small and they share the same review surface (the four frozen dataclasses + one parser function + their existing test files). No CI invariants change. The header/cookie/URL/mapping validation is a strict tightening — code that previously silently accepted garbage now raises; no public API surface change.
- **Roadmap pointer:** none — this is v0-contract hardening, not an Epic item. Same shape as the project-hygiene-tidy PR that just shipped (`2026-06-02-project-hygiene-tidy-design.md`): one focused PR before Epic 3 (resilience middleware) starts.

## Why

The five items target a single architectural seam: the immutable value objects (`Request`, `Timeout`, `Limits`, `ClientConfig`) accept inputs at construction without enforcing their stated contracts. Today, garbage propagates silently — empty URLs reach the transport, `\r\n` in headers reaches httpx2's wire encoder, negative timeouts get passed through to `httpx2.Timeout` where the error message is less actionable. The fix in every case is the same shape: add `__post_init__` to the frozen dataclass and raise `ValueError`/`TypeError` at the seam.

One item (charset parser robustness) is structurally different — it's a parser bug, not a validation gap — but it lives in the same `response.py` file and ships in the same PR for review cohesion.

Items 2-5 share an architectural decision: validation lives in `__post_init__` on the frozen dataclass, NOT in the `with_*` mutator methods. Two consequences:

1. Single source of truth. Direct construction (`Request(headers={...})`), copy-via-replace (`req.with_header(...)`), and deserialization paths all converge on the same validator. No "which path validates?" question.
2. `with_*` methods get validation for free with zero per-method code, because every `with_*` uses `dataclasses.replace`, which triggers `__post_init__` on the new instance.

The cost: every `with_*` re-validates the full (post-merge) state, not just the incremental change. For typical Request shapes (≤10 headers, ≤5 query params), this is microseconds. If profiling later shows it matters, optimize then.

### 1. Charset parser robustness (`src/httpware/response.py:20-25`)

Current parser:

```python
def _parse_charset(content_type: str) -> str | None:
    for raw in content_type.split(";"):
        part = raw.strip()
        if part.lower().startswith(_CHARSET_PREFIX):
            return part[len(_CHARSET_PREFIX) :].strip().strip('"').strip("'")
    return None
```

The deferred-work entry listed four concerns. Walking each against the actual code:

- **Inner whitespace inside a quoted value** (`charset=" utf-8 "`) — this IS a bug. After stripping the outer quotes, the inner spaces survive, and `bytes.decode(" utf-8 ")` raises `LookupError`. The `Response.text` property then falls back to UTF-8, which masks the parse failure but produces mojibake if the actual charset isn't UTF-8. `Response.json()` (after the recently-shipped charset fix) inherits this and similarly mis-decodes.
- **Substring false-positives** (`boundary=charset=foo`) — NOT a bug. The `split(";")` first, then `startswith("charset=")` already prevents this; `boundary=…` doesn't start with `charset=` after the split.
- **Mismatched quotes** (`charset="utf-8'`) — NOT a bug. Sequential `.strip('"').strip("'")` handles asymmetric quoting.
- **Multi-charset directives** (`charset=utf-8; charset=iso-8859-1`) — Current code returns the first match. Servers shouldn't send multiple; RFC-compliant behavior is to use the first/canonical value. Keep as-is.

Fix is one extra `.strip()` after the quote-stripping chain to consume any whitespace that was sitting inside the quotes:

```python
def _parse_charset(content_type: str) -> str | None:
    for raw in content_type.split(";"):
        part = raw.strip()
        if part.lower().startswith(_CHARSET_PREFIX):
            return part[len(_CHARSET_PREFIX) :].strip().strip('"').strip("'").strip()
    return None
```

### 2. Header + cookie name/value validation (`src/httpware/request.py`)

Per the "minimal" strictness choice agreed in brainstorming: reject what's actively dangerous or broken, don't enforce full RFC 9110 token grammar (let httpx2 surface the weird-but-technically-allowed cases downstream).

Rules:

- Name and value must both be `str` (catches runtime `None` and other type-system bypasses).
- Both must be non-empty (HTTP forbids empty header/cookie names; empty values are nonsensical for the values we're shipping).
- Neither may contain `\r` or `\n` (the injection vector).

Single helper, applied to both header and cookie items:

```python
def _validate_header_or_cookie(name: str, value: str, *, kind: str) -> None:
    if not isinstance(name, str) or not isinstance(value, str):
        msg = f"{kind} name and value must be str"
        raise TypeError(msg)
    if not name or not value:
        msg = f"{kind} name and value must be non-empty"
        raise ValueError(msg)
    if any(c in name or c in value for c in ("\r", "\n")):
        msg = f"{kind} name and value must not contain CR or LF"
        raise ValueError(msg)
```

Called from `Request.__post_init__`:

```python
for name, value in self.headers.items():
    _validate_header_or_cookie(name, value, kind="header")
for name, value in self.cookies.items():
    _validate_header_or_cookie(name, value, kind="cookie")
```

Cookies included alongside headers because the same injection vector exists at the cookie boundary (`with_cookie("name", "value\r\nSet-Cookie: evil=…")`). Same rules, parallel call.

### 3. URL non-empty check + `base_url` normalization

**`Request.url`** — in `Request.__post_init__`:

```python
if not isinstance(self.url, str):
    msg = "url must be str"
    raise TypeError(msg)
if not self.url:
    msg = "url must be non-empty"
    raise ValueError(msg)
```

URL **format** validation is deliberately not added — httpx2's `InvalidURL` (mapped to our `TransportError`) handles that at send time, and we don't want two parsers disagreeing. The empty-string case is the "you forgot to set it" failure, which deserves to fail at construction.

**`ClientConfig.base_url`** — in `ClientConfig.__post_init__`:

```python
if self.base_url is not None:
    if not isinstance(self.base_url, str) or not self.base_url:
        msg = "base_url must be a non-empty string or None"
        raise ValueError(msg)
    object.__setattr__(self, "base_url", self.base_url.rstrip("/"))
```

(`object.__setattr__` is the standard pattern for mutating a frozen dataclass field inside `__post_init__`.)

After this lands, the stored `base_url` is canonical (no trailing slash). The existing `AsyncClient._resolve_url` at `src/httpware/client.py:122` does `base.rstrip("/")` redundantly — remove it for DRY (one source of truth for "what does the stored base_url look like").

### 4. Mapping-field validation (`Request.__post_init__`)

`with_query(None)` was the entry-point bug; the underlying gap is broader. None of the four `Mapping` fields on `Request` (`headers`, `params`, `cookies`, `extensions`) currently check that they're actually mappings. A runtime `None` (or a list, or any non-mapping) bypasses type-checking and breaks later at iteration time with a confusing `AttributeError`.

Single loop in `Request.__post_init__`:

```python
for field_name in ("headers", "params", "cookies", "extensions"):
    field_value = getattr(self, field_name)
    if not isinstance(field_value, Mapping):
        msg = f"{field_name} must be a Mapping (got {type(field_value).__name__})"
        raise TypeError(msg)
```

This naturally catches `with_query(None)`, `with_headers(None)`, `with_extensions(None)`, etc., because `dataclasses.replace(self, params=None)` triggers `__post_init__` which then raises. No per-method validation needed.

### 5. `Timeout` / `Limits` negative-value validation (`src/httpware/config.py`)

`Timeout.__post_init__`:

```python
for attr in ("connect", "read", "write", "pool"):
    value = getattr(self, attr)
    if value < 0:
        msg = f"Timeout.{attr} must be non-negative (got {value})"
        raise ValueError(msg)
```

Zero is allowed — valid sentinel for "fail immediately on this phase."

`Limits.__post_init__`:

```python
if self.max_connections < 0:
    msg = f"max_connections must be non-negative (got {self.max_connections})"
    raise ValueError(msg)
if self.max_keepalive_connections < 0:
    msg = f"max_keepalive_connections must be non-negative (got {self.max_keepalive_connections})"
    raise ValueError(msg)
if self.keepalive_expiry < 0:
    msg = f"keepalive_expiry must be non-negative (got {self.keepalive_expiry})"
    raise ValueError(msg)
```

httpx2 may have its own opinions about `max_connections=0` (typically interpreted as "no limit"); our contract is just "non-negative" — downstream gets the final say on zero semantics.

## Decisions

| Decision | Choice |
| --- | --- |
| Validation placement | `__post_init__` on the frozen dataclass. Single source of truth; `with_*` methods inherit validation via `dataclasses.replace`. |
| Exception type for bad values | `ValueError`. Matches existing pattern (`raise ValueError(msg)` in `transports/httpx2.py:81`). |
| Exception type for wrong runtime types | `TypeError`. Distinct from value errors; signals "you bypassed the type system." |
| Header strictness | Minimal: reject CR/LF, non-`str`, empty. NOT full RFC 9110 token validation — let httpx2 surface the weird-but-technically-allowed cases. |
| Cookie validation | Same rules as headers, parallel call. Closes the same injection vector. |
| URL format validation | Deferred to httpx2 (`InvalidURL` → `TransportError` mapping). Only the empty-string case is validated at construction. |
| `base_url` normalization | Strip trailing slash at `ClientConfig.__post_init__`; remove the now-redundant `rstrip("/")` in `AsyncClient._resolve_url`. |
| `Timeout` / `Limits` zero values | Allowed. Negative is the bug case. |
| Charset parser fix | One extra `.strip()` after quote-stripping. The other "concerns" from the deferred entry don't actually fire on the current code; documented in the Why section. |
| Multi-`charset=` directives | Keep current behavior (return first match). RFC-compliant; not worth changing. |
| Bundle vs split PR | One PR. All five items touch the value-object layer (`request.py`, `response.py`, `config.py`) and their corresponding test files; splitting adds five rebases for no review-quality gain. |
| Closing deferred-work entries | Yes — remove the five closed entries from `planning/deferred-work.md` Story 1-2 section in the same PR. |

## File structure

**Modified files:**

- `src/httpware/request.py` — add `__post_init__` to `Request`; add module-private `_validate_header_or_cookie` helper. Validates URL, headers, cookies, and all four Mapping fields.
- `src/httpware/response.py` — one-line fix in `_parse_charset` (extra `.strip()`).
- `src/httpware/config.py` — add `__post_init__` to `Timeout`, `Limits`, and `ClientConfig`. `ClientConfig` validates and normalizes `base_url`; the others validate negative values.
- `src/httpware/client.py` — remove the now-redundant `base.rstrip("/")` in `_resolve_url` (line 122). One-line change.
- `tests/test_request.py` — add tests for empty URL, non-Mapping fields, bad header/cookie name/value.
- `tests/test_response.py` — add one test for the charset whitespace-in-quotes case.
- `tests/test_config.py` — add tests for negative Timeout/Limits fields and `base_url` validation/normalization.
- `planning/deferred-work.md` — remove the five closed entries from the Story 1-2 section.

**New files:** none.

**Deleted files:** none.

## Verification

- `just lint-ci` exits 0. The `__post_init__` additions don't trigger any new ruff/ty rules (verified mentally; ruff has no opinion about empty `__post_init__` bodies, and ty is fine with `object.__setattr__` inside one).
- `just test` exits 0. New tests pass; existing tests continue to pass.
- Specifically: no existing test fixture should construct a `Request` with an empty URL, an empty/CRLF-containing header value, or a non-mapping field. Verify during implementation by running the suite after each `__post_init__` is added; any pre-existing test that now fails should be inspected for whether it was relying on the silent-acceptance behavior (and corrected if so).
- `Response.text` with `Content-Type: application/json; charset=" utf-8 "` no longer falls back to UTF-8; instead returns the correctly-decoded string.
- Manual: `grep -E 'Charset parser|Header name/value|URL validation|with_query|Timeout.*Limits.*negative' planning/deferred-work.md` returns empty after the deferred-work cleanup task lands.

## Out of scope

- **Full RFC 9110 header token validation.** Per the brainstorming "minimal" choice.
- **URL format validation.** Deferred to httpx2's `InvalidURL`.
- **Header CRLF redaction at transport-side.** That's the `Redactor` middleware (Story 5.3, still deferred). This spec adds construction-side validation; the Redactor adds defense-in-depth at the wire layer. Complementary, not overlapping.
- **`max_connections=0` semantic check.** Whether 0 means "unlimited" or "no connections" is httpx2's concern.
- **Other Story 1-2 deferred items not in this bundle:** multi-valued query params (type widening), streaming/async-iterable request bodies (Story 4.1), `@final` to prevent subclassing. Each is a different shape of change.
- **Per-request `extensions` allowlist.** Deferred to Epic 3 timeout middleware.

## Risks

- **Existing test fixtures may construct `Request` with empty URLs or non-Mapping fields.** Mitigation: run `just test` after each `__post_init__` lands; inspect any pre-existing failures. The likely-affected files are `tests/test_request.py`, `tests/test_client_methods.py`, and `tests/test_middleware.py` (those construct Requests with various shapes). Implementation step verifies before commit.
- **`object.__setattr__` inside `__post_init__` of a frozen dataclass is mildly unidiomatic.** It's the standard escape hatch for this exact case (frozen + need to normalize a field on construction), and Python's `dataclasses` documentation explicitly sanctions it. No type-checker should flag it; verify ruff/ty stay silent.
- **Validation cost on every `dataclasses.replace`.** Each `with_*` revalidates the full state. For typical Request shapes (≤10 headers, ≤5 query params, ≤5 cookies), this is microseconds — negligible. Documented in the Why section so a future reader knows the choice was deliberate.
- **Strictness is a breaking change for buggy callers.** Code that previously silently accepted an empty URL or a `\r\n`-bearing header now raises. Acceptable at v0.1.x; documented as part of the PR description so anyone upgrading sees the contract tightening.
- **Charset fix may surface a previously-masked bug elsewhere.** If a test or production caller was relying on the mojibake-via-UTF-8-fallback path (intentionally or by accident), the fix changes their observable behavior. Highly unlikely — the fix returns a CORRECT decoded string instead of a wrong one — but worth verifying that `Response.text` and `Response.json()` tests don't depend on the old broken behavior.

## Related work

- `planning/deferred-work.md` — source of all five items; gets edited (five entries removed) as part of this PR.
- `2026-06-02-project-hygiene-tidy-design.md` — the previous v0-hardening PR. Same shape: bundled config/code fixes that close deferred-work entries; not Epic-tagged.
- Story 5.3 Redactor middleware — the transport-side complement to item 2's construction-side header CRLF validation. Still deferred; this PR doesn't block it.

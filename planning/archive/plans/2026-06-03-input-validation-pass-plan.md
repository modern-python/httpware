# Input-validation pass implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land five v0-contract input-validation fixes in one PR: charset parser inner-whitespace bug; `Request.__post_init__` with URL, header/cookie, and mapping-field validation; `Timeout`/`Limits` negative-value guards; `ClientConfig.base_url` validation + normalization; deferred-work cleanup.

**Architecture:** Six atomic-commit tasks executed in dependency order. Each validation task is a TDD cycle (failing test → `__post_init__` implementation → green). All validation lives in `__post_init__` on the affected frozen dataclasses; `with_*` methods inherit validation via `dataclasses.replace`. Exception types: `ValueError` for invalid values, `TypeError` for wrong runtime types. The `base_url` normalization in Task 4 also removes a redundant `rstrip("/")` from `AsyncClient._resolve_url` (DRY — once the stored value is canonical, downstream doesn't re-normalize).

**Tech Stack:** Python 3.11+ frozen dataclasses with `__post_init__`, `object.__setattr__` for in-`__post_init__` field normalization, `pytest` (no Hypothesis — reserved for concurrency-sensitive code per CLAUDE.md).

---

## Pre-flight

Plan assumes a clean working tree at the spec's commit (`2026-06-03-input-validation-pass-design.md` already on `main`). Verify:

```bash
git status              # clean
git log -1 --oneline    # should show the spec commit
```

The spec lives at `planning/specs/2026-06-03-input-validation-pass-design.md` — read it once if you haven't.

Establish the baseline:

```bash
just lint-ci
just test
```

Both must exit 0 before starting. Note the test count for sanity-checking later (should be 296 from the prior hygiene PR).

Create a feature branch for this work:

```bash
git checkout -b chore/input-validation-pass
```

---

### Task 1: Charset parser inner-whitespace fix

**Goal:** Fix the `_parse_charset` helper in `response.py` so that `Content-Type: application/json; charset=" utf-8 "` (with whitespace inside the quotes) decodes correctly. Currently the inner whitespace survives the quote-stripping and `bytes.decode(" utf-8 ")` raises `LookupError`, causing `Response.text` to silently fall back to UTF-8 (mojibake if the actual charset differs).

**Files:**
- Test: `tests/test_response.py` (add one test function)
- Modify: `src/httpware/response.py:20-25` (the `_parse_charset` function)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_response.py`, placed near the existing `test_response_text_honors_explicit_charset` tests (somewhere in the charset-related test cluster — typically around lines 25–65):

```python
def test_response_text_strips_inner_whitespace_in_quoted_charset() -> None:
    body = "café".encode("iso-8859-1")
    resp = Response(
        status=HTTPStatus.OK,
        headers={"content-type": 'text/plain; charset=" iso-8859-1 "'},
        content=body,
        url="/",
        elapsed=0.0,
    )
    assert resp.text == "café"
```

(Uses `HTTPStatus.OK` because `from http import HTTPStatus` is already imported in this file from the prior hygiene PR.)

- [ ] **Step 2: Run test to verify it fails**

```bash
just test tests/test_response.py::test_response_text_strips_inner_whitespace_in_quoted_charset -v
```

Expected: FAIL. `_parse_charset` returns `" iso-8859-1 "` (with leading/trailing space), `bytes.decode(" iso-8859-1 ")` raises `LookupError`, the existing fallback at `response.py:47-48` returns `self.content.decode("utf-8")` which produces mojibake (`b'caf\xe9'` is invalid UTF-8 → also raises). Exact error may be `UnicodeDecodeError` rather than an assertion failure; either way the test fails.

- [ ] **Step 3: Read current `_parse_charset`**

```bash
sed -n '20,25p' src/httpware/response.py
```

Expected:

```python
def _parse_charset(content_type: str) -> str | None:
    for raw in content_type.split(";"):
        part = raw.strip()
        if part.lower().startswith(_CHARSET_PREFIX):
            return part[len(_CHARSET_PREFIX) :].strip().strip('"').strip("'")
    return None
```

- [ ] **Step 4: Apply the fix**

Replace the `return` line in `_parse_charset` with one that adds a final `.strip()` after the quote-stripping chain:

```python
def _parse_charset(content_type: str) -> str | None:
    for raw in content_type.split(";"):
        part = raw.strip()
        if part.lower().startswith(_CHARSET_PREFIX):
            return part[len(_CHARSET_PREFIX) :].strip().strip('"').strip("'").strip()
    return None
```

- [ ] **Step 5: Run the test to verify it passes**

```bash
just test tests/test_response.py::test_response_text_strips_inner_whitespace_in_quoted_charset -v
```

Expected: PASS.

- [ ] **Step 6: Run full test suite + lint**

```bash
just test
just lint-ci
```

Both exit 0.

- [ ] **Step 7: Commit**

```bash
git add src/httpware/response.py tests/test_response.py
git commit -m "$(cat <<'EOF'
fix: charset parser strips inner whitespace from quoted values

Adds one final .strip() after the quote-stripping chain in
_parse_charset so that Content-Type: ...; charset=" utf-8 " decodes
correctly instead of falling back through LookupError -> mojibake.

The other "concerns" listed in the deferred-work entry (substring
false-positives, mismatched quotes, multi-charset directives) do not
actually fire on the current code, per the spec's analysis.

Closes deferred-work entry: "Charset parser robustness".

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: `Request.__post_init__` (URL + header/cookie + mapping validation)

**Goal:** Add `__post_init__` to `Request` that validates: (a) `url` is a non-empty `str`; (b) every header and cookie name/value is a non-empty `str` with no `\r` or `\n`; (c) `headers`, `params`, `cookies`, `extensions` are each a `Mapping`. Adds a module-private `_validate_header_or_cookie` helper.

**Files:**
- Test: `tests/test_request.py` (add ~8 new test functions for the new validation rules)
- Modify: `src/httpware/request.py` (add `__post_init__` + helper)

**Important context:** Adding `__post_init__` to a frozen dataclass is idiomatic — no special handling required. The new `__post_init__` runs on every direct construction AND on every `dataclasses.replace` call (which is what every `with_*` method uses), so validation is inherited for free by `with_url`, `with_header`, `with_headers`, `with_cookie`, `with_cookies`, `with_query`, `with_extension`, and `with_extensions`.

- [ ] **Step 1: Write all failing tests at once**

Add the following tests to `tests/test_request.py`. Place them in a logical cluster — group by validation rule, roughly after the existing `with_*` tests.

```python
def test_request_rejects_empty_url() -> None:
    with pytest.raises(ValueError, match="url must be non-empty"):
        Request(method="GET", url="")


def test_request_rejects_non_str_url() -> None:
    with pytest.raises(TypeError, match="url must be str"):
        Request(method="GET", url=None)  # ty: ignore[invalid-argument-type]


def test_with_url_rejects_empty() -> None:
    r = Request(method="GET", url="/")
    with pytest.raises(ValueError, match="url must be non-empty"):
        r.with_url("")


def test_request_rejects_header_with_crlf_in_value() -> None:
    with pytest.raises(ValueError, match="header name and value must not contain CR or LF"):
        Request(method="GET", url="/", headers={"X-Trace": "value\r\nInjected: yes"})


def test_request_rejects_header_with_crlf_in_name() -> None:
    with pytest.raises(ValueError, match="header name and value must not contain CR or LF"):
        Request(method="GET", url="/", headers={"X-Bad\r\nInjected": "value"})


def test_request_rejects_empty_header_name() -> None:
    with pytest.raises(ValueError, match="header name and value must be non-empty"):
        Request(method="GET", url="/", headers={"": "value"})


def test_request_rejects_empty_header_value() -> None:
    with pytest.raises(ValueError, match="header name and value must be non-empty"):
        Request(method="GET", url="/", headers={"X-Trace": ""})


def test_request_rejects_non_str_header_value() -> None:
    with pytest.raises(TypeError, match="header name and value must be str"):
        Request(method="GET", url="/", headers={"X-Trace": None})  # ty: ignore[invalid-argument-type]


def test_request_rejects_cookie_with_crlf() -> None:
    with pytest.raises(ValueError, match="cookie name and value must not contain CR or LF"):
        Request(method="GET", url="/", cookies={"session": "abc\r\nSet-Cookie: evil"})


def test_request_rejects_empty_cookie_value() -> None:
    with pytest.raises(ValueError, match="cookie name and value must be non-empty"):
        Request(method="GET", url="/", cookies={"session": ""})


def test_with_header_rejects_crlf() -> None:
    r = Request(method="GET", url="/")
    with pytest.raises(ValueError, match="header name and value must not contain CR or LF"):
        r.with_header("X-Trace", "value\r\n")


def test_with_cookie_rejects_crlf() -> None:
    r = Request(method="GET", url="/")
    with pytest.raises(ValueError, match="cookie name and value must not contain CR or LF"):
        r.with_cookie("session", "abc\r\n")


@pytest.mark.parametrize("field_name", ["headers", "params", "cookies", "extensions"])
def test_request_rejects_none_mapping_field(field_name: str) -> None:
    with pytest.raises(TypeError, match=f"{field_name} must be a Mapping"):
        Request(method="GET", url="/", **{field_name: None})  # ty: ignore[invalid-argument-type]


@pytest.mark.parametrize("field_name", ["headers", "params", "cookies", "extensions"])
def test_request_rejects_list_mapping_field(field_name: str) -> None:
    with pytest.raises(TypeError, match=f"{field_name} must be a Mapping"):
        Request(method="GET", url="/", **{field_name: []})  # ty: ignore[invalid-argument-type]


def test_with_query_none_raises() -> None:
    r = Request(method="GET", url="/")
    with pytest.raises(TypeError, match="params must be a Mapping"):
        r.with_query(None)  # ty: ignore[invalid-argument-type]
```

- [ ] **Step 2: Run tests to verify they all fail**

```bash
just test tests/test_request.py -v 2>&1 | tail -30
```

Expected: the ~15 new tests all FAIL (the validation doesn't exist yet). Pre-existing tests continue to PASS.

If you see fewer than 15 FAILs, double-check Step 1 — some tests may not have been added.

- [ ] **Step 3: Read current `request.py`**

```bash
cat src/httpware/request.py
```

Understand the existing structure — `Request` is a `@dataclass(frozen=True, slots=True)` with no `__post_init__` yet.

- [ ] **Step 4: Add the helper + `__post_init__`**

Edit `src/httpware/request.py`. Add a module-private validator near the top of the file (after imports, before the `@dataclass` decorator):

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

Then add `__post_init__` to the `Request` class, immediately after the field declarations (before the existing `def with_header(...)`):

```python
    def __post_init__(self) -> None:
        if not isinstance(self.url, str):
            msg = "url must be str"
            raise TypeError(msg)
        if not self.url:
            msg = "url must be non-empty"
            raise ValueError(msg)
        for field_name in ("headers", "params", "cookies", "extensions"):
            field_value = getattr(self, field_name)
            if not isinstance(field_value, Mapping):
                msg = f"{field_name} must be a Mapping (got {type(field_value).__name__})"
                raise TypeError(msg)
        for name, value in self.headers.items():
            _validate_header_or_cookie(name, value, kind="header")
        for name, value in self.cookies.items():
            _validate_header_or_cookie(name, value, kind="cookie")
```

- [ ] **Step 5: Run tests to verify they all pass**

```bash
just test tests/test_request.py -v 2>&1 | tail -20
```

Expected: all tests in `test_request.py` pass (the ~15 new ones plus all pre-existing).

If any pre-existing test now fails, inspect — it likely relied on the silent-acceptance behavior. The pre-flight grep should have caught these, but verify.

- [ ] **Step 6: Run full test suite + lint**

```bash
just test
just lint-ci
```

Both exit 0.

Specifically watch for: tests in `tests/test_client_methods.py`, `tests/test_middleware.py`, `tests/test_transports_*.py` that construct Requests. The pre-flight scan suggested none of them construct bad Requests, but the full-suite run is the authoritative check.

- [ ] **Step 7: Commit**

```bash
git add src/httpware/request.py tests/test_request.py
git commit -m "$(cat <<'EOF'
fix: validate Request fields in __post_init__

Adds Request.__post_init__ that validates:
- url is a non-empty str
- headers, params, cookies, extensions are each a Mapping
- header and cookie names/values are non-empty str, no CR or LF

with_* methods inherit validation via dataclasses.replace; no
per-method code needed. Header validation is minimal per spec
(reject CR/LF, non-str, empty); full RFC 9110 token validation is
out of scope.

Closes deferred-work entries: "Header name/value validation",
"URL validation" (Request.url part), "with_query(None) handling".

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: `Timeout` + `Limits` negative-value validation

**Goal:** Add `__post_init__` to `Timeout` and `Limits` in `config.py` that raises `ValueError` on negative field values. Zero is permitted.

**Files:**
- Test: `tests/test_config.py` (add ~8 parametrized test cases)
- Modify: `src/httpware/config.py` (add two `__post_init__` methods)

- [ ] **Step 1: Write failing tests**

Add to `tests/test_config.py`, alongside the existing `Timeout`/`Limits` tests:

```python
@pytest.mark.parametrize("field", ["connect", "read", "write", "pool"])
def test_timeout_rejects_negative(field: str) -> None:
    with pytest.raises(ValueError, match=f"Timeout.{field} must be non-negative"):
        Timeout(**{field: -1.0})


def test_timeout_accepts_zero() -> None:
    # Zero is a valid sentinel (fail immediately on this phase).
    Timeout(connect=0.0, read=0.0, write=0.0, pool=0.0)


@pytest.mark.parametrize("field", ["max_connections", "max_keepalive_connections"])
def test_limits_rejects_negative_int(field: str) -> None:
    with pytest.raises(ValueError, match=f"{field} must be non-negative"):
        Limits(**{field: -1})


def test_limits_rejects_negative_keepalive_expiry() -> None:
    with pytest.raises(ValueError, match="keepalive_expiry must be non-negative"):
        Limits(keepalive_expiry=-0.5)


def test_limits_accepts_zero() -> None:
    Limits(max_connections=0, max_keepalive_connections=0, keepalive_expiry=0.0)
```

If `pytest` is not already imported at the top of `tests/test_config.py`, add `import pytest`.

- [ ] **Step 2: Run tests to verify they fail**

```bash
just test tests/test_config.py -v 2>&1 | tail -20
```

Expected: the new `_rejects_negative` tests FAIL (no validation yet). The `_accepts_zero` tests pass (current code already accepts zero). Pre-existing tests still pass.

- [ ] **Step 3: Add `__post_init__` to `Timeout` and `Limits`**

Edit `src/httpware/config.py`. Add `__post_init__` to the `Timeout` class (after the field declarations, before the next class):

```python
    def __post_init__(self) -> None:
        for attr in ("connect", "read", "write", "pool"):
            value = getattr(self, attr)
            if value < 0:
                msg = f"Timeout.{attr} must be non-negative (got {value})"
                raise ValueError(msg)
```

Add `__post_init__` to the `Limits` class:

```python
    def __post_init__(self) -> None:
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

- [ ] **Step 4: Run tests to verify they pass**

```bash
just test tests/test_config.py -v 2>&1 | tail -20
```

Expected: all `test_config.py` tests pass.

- [ ] **Step 5: Run full test suite + lint**

```bash
just test
just lint-ci
```

Both exit 0.

- [ ] **Step 6: Commit**

```bash
git add src/httpware/config.py tests/test_config.py
git commit -m "$(cat <<'EOF'
fix: validate Timeout/Limits negatives in __post_init__

Both dataclasses now raise ValueError on construction if any field
is negative. Zero is permitted (Timeout zero = fail-immediately
sentinel; Limits zero = downstream's call on what it means, typically
"no limit").

Closes deferred-work entry: "Timeout / Limits negative-value
validation".

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: `ClientConfig.base_url` validation + normalization (+ remove redundant `rstrip` in `client.py`)

**Goal:** Add `__post_init__` to `ClientConfig` that validates `base_url` (when not `None`) is a non-empty `str` and normalizes it by stripping a trailing slash. Then remove the now-redundant `base.rstrip("/")` in `AsyncClient._resolve_url` since the stored value is canonical.

**Files:**
- Test: `tests/test_config.py` (add ~4 new test functions)
- Test: `tests/test_client_methods.py` (verify existing `base_url` behavior still works — no new test needed unless existing coverage is thin)
- Modify: `src/httpware/config.py` (add `ClientConfig.__post_init__`)
- Modify: `src/httpware/client.py:122` (remove `.rstrip("/")`)

- [ ] **Step 1: Write failing tests**

Add to `tests/test_config.py`:

```python
def test_client_config_strips_trailing_slash_from_base_url() -> None:
    cfg = ClientConfig(base_url="https://api.example.com/")
    assert cfg.base_url == "https://api.example.com"


def test_client_config_leaves_base_url_without_trailing_slash() -> None:
    cfg = ClientConfig(base_url="https://api.example.com")
    assert cfg.base_url == "https://api.example.com"


def test_client_config_strips_multiple_trailing_slashes() -> None:
    cfg = ClientConfig(base_url="https://api.example.com///")
    assert cfg.base_url == "https://api.example.com"


def test_client_config_allows_none_base_url() -> None:
    cfg = ClientConfig(base_url=None)
    assert cfg.base_url is None


def test_client_config_rejects_empty_base_url() -> None:
    with pytest.raises(ValueError, match="base_url must be a non-empty string or None"):
        ClientConfig(base_url="")


def test_client_config_rejects_non_str_base_url() -> None:
    with pytest.raises(ValueError, match="base_url must be a non-empty string or None"):
        ClientConfig(base_url=123)  # ty: ignore[invalid-argument-type]
```

Make sure `ClientConfig` is imported at the top of `test_config.py` (check via `grep -n 'ClientConfig' tests/test_config.py`; if not imported, add `from httpware.config import ClientConfig, Limits, Timeout` or extend the existing imports).

- [ ] **Step 2: Run tests to verify they fail**

```bash
just test tests/test_config.py -v 2>&1 | tail -20
```

Expected: the new `base_url` tests FAIL (no validation/normalization yet). The non-str rejection test may already raise something else (e.g., `AttributeError` later) — either way, the new tests fail.

- [ ] **Step 3: Add `ClientConfig.__post_init__`**

Edit `src/httpware/config.py`. Add `__post_init__` to the `ClientConfig` class:

```python
    def __post_init__(self) -> None:
        if self.base_url is not None:
            if not isinstance(self.base_url, str) or not self.base_url:
                msg = "base_url must be a non-empty string or None"
                raise ValueError(msg)
            object.__setattr__(self, "base_url", self.base_url.rstrip("/"))
```

`object.__setattr__` is the standard pattern for mutating a frozen dataclass field inside `__post_init__`. Python's `dataclasses` documentation explicitly sanctions this.

- [ ] **Step 4: Run `test_config.py` to verify it passes**

```bash
just test tests/test_config.py -v 2>&1 | tail -20
```

Expected: all `test_config.py` tests pass, including the new `base_url` ones.

- [ ] **Step 5: Remove the redundant `rstrip` in `client.py`**

Read the current `_resolve_url`:

```bash
sed -n '116,123p' src/httpware/client.py
```

Expected:

```python
    def _resolve_url(self, path: str) -> str:
        if path.startswith(("http://", "https://")):
            return path
        base = self._config.base_url
        if base is None:
            return path
        return f"{base.rstrip('/')}/{path.lstrip('/')}"
```

Replace the last `return` line so that `base` is used directly (no `rstrip` call — the stored value is now canonical):

```python
        return f"{base}/{path.lstrip('/')}"
```

The full method should read:

```python
    def _resolve_url(self, path: str) -> str:
        if path.startswith(("http://", "https://")):
            return path
        base = self._config.base_url
        if base is None:
            return path
        return f"{base}/{path.lstrip('/')}"
```

- [ ] **Step 6: Run client-method tests to verify URL resolution still works**

```bash
just test tests/test_client_methods.py -v 2>&1 | tail -10
```

Expected: all pass. The existing tests cover both `base_url="https://api.example.com"` and `base_url="https://api.example.com/"` shapes; both should now produce the same resolved URL (`https://api.example.com/<path>`).

- [ ] **Step 7: Run full test suite + lint**

```bash
just test
just lint-ci
```

Both exit 0.

- [ ] **Step 8: Commit**

```bash
git add src/httpware/config.py src/httpware/client.py tests/test_config.py
git commit -m "$(cat <<'EOF'
refactor: validate and normalize ClientConfig.base_url in __post_init__

ClientConfig.__post_init__ now:
- rejects empty string / non-str base_url with ValueError
- strips trailing slash so the stored value is canonical

AsyncClient._resolve_url no longer does its own rstrip("/") on
base_url since the stored value is already canonical (DRY: one
source of truth for what a stored base_url looks like).

Closes deferred-work entry: "URL validation" (base_url normalization
part; the Request.url non-empty check shipped in the prior Request
__post_init__ commit).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Update `planning/deferred-work.md`

**Goal:** Remove the five entries this PR closes from the Story 1-2 section.

**Files:**
- Modify: `planning/deferred-work.md`

**Entries to remove (all in the "Deferred from: code review of story-1-2 (2026-05-13)" section):**

1. `**Charset parser robustness**` — closed by Task 1.
2. `**Header name/value validation**` — closed by Task 2 (headers + cookies).
3. `**URL validation**` — closed by Task 2 (`Request.url` non-empty) + Task 4 (`base_url` normalization).
4. `**`with_query(None)` handling**` — closed by Task 2 (Mapping-field validation).
5. `**`Timeout` / `Limits` negative-value validation**` — closed by Task 3.

The remaining Story 1-2 bullets (multi-valued query params, streaming request bodies, `@final` to prevent subclassing) stay — they're different shapes of change, explicitly out of scope.

- [ ] **Step 1: Read the current Story 1-2 section**

```bash
grep -n -A 50 "code review of story-1-2 (2026-05-13)" planning/deferred-work.md
```

Confirm the five removal targets are present.

- [ ] **Step 2: Delete each of the five bullets**

Edit `planning/deferred-work.md` and remove these five bullet items from the Story 1-2 section (preserving the section header and the bullets that remain — multi-valued query params, streaming bodies, `@final`):

- Charset parser robustness bullet (the one starting `- **Charset parser robustness**`)
- Header name/value validation bullet (starting `- **Header name/value validation**`)
- URL validation bullet (starting `- **URL validation**`)
- `with_query(None)` handling bullet (starting `- **`with_query(None)` handling**`)
- `Timeout` / `Limits` negative-value validation bullet (starting `- **`Timeout` / `Limits` negative-value validation**`)

- [ ] **Step 3: Verify removals**

```bash
grep -E 'Charset parser|Header name/value|URL validation|with_query|Timeout.*Limits.*negative' planning/deferred-work.md
```

Expected: empty output.

- [ ] **Step 4: Verify remaining Story 1-2 bullets are intact**

```bash
grep -n 'Multi-valued query params\|Streaming.*async-iterable\|@final to prevent subclassing' planning/deferred-work.md
```

Expected: three matches, all in the Story 1-2 section.

- [ ] **Step 5: Run lint to confirm no formatting issues**

```bash
just lint-ci
```

Expected: exits 0 (eof-fixer is happy; ruff has no opinion on markdown).

- [ ] **Step 6: Commit**

```bash
git add planning/deferred-work.md
git commit -m "$(cat <<'EOF'
docs: close deferred-work entries resolved by input-validation pass

Removes five Story 1-2 entries closed by this PR: charset parser
robustness, header name/value validation, URL validation, with_query
(None) handling, Timeout/Limits negative-value validation.

The remaining Story 1-2 entries (multi-valued query params, streaming
request bodies, @final subclassing) stay open — they're different
shapes of change, explicitly out of scope for this pass.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: Final verification

**Goal:** Confirm the branch is internally consistent and PR-ready.

- [ ] **Step 1: Full lint + test**

```bash
just lint-ci && just test
```

Both exit 0. Test count should be 296 + new tests from Tasks 1-4 (roughly 30 new tests; expect somewhere around 326).

- [ ] **Step 2: Confirm `Request.__post_init__` validation rules**

Quick sanity check that the validation catches the specified inputs:

```bash
just test tests/test_request.py -k "rejects" -v 2>&1 | tail -20
```

Expected: all `*_rejects_*` tests in `test_request.py` pass.

- [ ] **Step 3: Confirm closed deferred-work entries are gone**

```bash
grep -E 'Charset parser|Header name/value|URL validation|with_query|Timeout.*Limits.*negative' planning/deferred-work.md
```

Expected: empty output.

- [ ] **Step 4: Confirm no regression in pre-existing tests**

```bash
just test tests/test_client_methods.py tests/test_middleware.py tests/test_transports_httpx2.py 2>&1 | tail -5
```

Expected: all pass. These files have the most Request construction; if any broke from the new validation, this catches it.

- [ ] **Step 5: Review commit log**

```bash
git log --oneline main..HEAD
```

(Or `origin/main..HEAD` if `main` hasn't been synced.)

Expected: five commits, newest first:

```
<hash> docs: close deferred-work entries resolved by input-validation pass
<hash> refactor: validate and normalize ClientConfig.base_url in __post_init__
<hash> fix: validate Timeout/Limits negatives in __post_init__
<hash> fix: validate Request fields in __post_init__
<hash> fix: charset parser strips inner whitespace from quoted values
```

- [ ] **Step 6: PR readiness check**

```bash
git diff --stat main
```

Expected ~5-7 files touched:

- `src/httpware/request.py`
- `src/httpware/response.py`
- `src/httpware/config.py`
- `src/httpware/client.py`
- `tests/test_request.py`
- `tests/test_config.py`
- `tests/test_response.py`
- `planning/deferred-work.md`

If any file outside this list shows up, investigate before pushing.

---

## After completion

Branch is ready to push and PR. Suggested PR title:

> `chore: input-validation pass — Request/Timeout/Limits/ClientConfig __post_init__ guards + charset parser fix`

PR description should reference the spec at `planning/specs/2026-06-03-input-validation-pass-design.md` and list the closed deferred-work entries.

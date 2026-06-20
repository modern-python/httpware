---
status: shipped
date: 2026-05-31
slug: shipped-work-review
summary: 0.1.0-era review of shipped stories
supersedes: null
superseded_by: null
pr: 7
outcome: '0.1.0-era review of shipped stories'
---

# Retrospective code review — stories 1-1 through 1-5

- **Date:** 2026-05-31
- **Reviewer:** opus subagent under superpowers:requesting-code-review
- **Scope:** src/httpware/ + tests/ + pyproject.toml + Justfile + .github/, current HEAD (114361b)
- **Base:** empty tree (4b825dc)

## Strengths

- **Invariants hold.** All five grep checks in `CLAUDE.md` §44–53 pass: zero `httpx2` imports outside `src/httpware/transports/httpx2.py`, zero `httpx2._` private refs, zero `from __future__ import annotations`, zero `print()` / `logging.basicConfig()` / unnamed `getLogger()`, zero `# type: ignore`. The CI-enforceable surface is clean.
- **Seam 4 mapping is well-ordered.** `transports/httpx2.py:125-130` catches `TimeoutException` (an `HTTPError` subclass) *before* the broader `HTTPError` clause, and explicitly enumerates `InvalidURL` / `CookieConflict` (verified non-subclasses of `HTTPError`). The mapping is exhaustive over the documented surface.
- **Exception construction is keyword-only and defensively copied.** `errors.py:88-113` uses bare `*` and wraps headers in `MappingProxyType(dict(headers))`; `test_status_error_rejects_positional_args` + `test_headers_are_defensively_copied` + `test_headers_are_read_only` lock the contract.
- **Pickle/deepcopy round-trip is real.** `__reduce__` + the `_reconstruct_status_error` helper avoid the standard `BaseException.__reduce__` foot-gun (positional args vs keyword-only `__init__`). Tested at `test_errors.py:283-318`.
- **Userinfo redaction is defense-in-depth at the right layer.** `_strip_userinfo` lives on `StatusError.__repr__` / `__str__` only — keeps the raw `request_url` field intact for the Redactor (Story 5.3) per the docstring at `errors.py:10-15`.
- **Lazy client init is concurrency-safe.** `Httpx2Transport._get_client` (`transports/httpx2.py:87-107`) uses an `asyncio.Lock` and a double-checked `self._client is None` inside the `async with` block; `test_concurrent_first_calls_initialize_client_once` exercises the race.

## Findings — triaged

### Refactor now

(none)

### Defer

- **[D-1] `PydanticDecoder.decode` `TypeError` fallback is unreachable through normal usage** — `src/httpware/decoders/pydantic.py:22-26`
  - The `except TypeError` branch only triggers when `_get_adapter(model)` raises during `lru_cache` lookup, which requires `model` to be unhashable. Every concrete `type[T]` is hashable; only synthetic / monkey-patched constructs (as the test does via `patch(..., side_effect=TypeError)`) hit it. The fallback exists "in case `Annotated[...]` metadata is unhashable", but `Annotated` itself hashes by content. Adds branch surface and a test-only path.
  - Why deferring: cost is one extra branch; removing it would require a separate proof that no real `type[T]` produces `TypeError` at cache-lookup time, and the safer course is to revisit in Story 1.6 when `msgspec` introduces a second decoder and the protocol-level invariants get re-examined.

- **[D-2] `_get_adapter` `lru_cache` is module-global, not per-decoder instance** — `src/httpware/decoders/pydantic.py:12-14`
  - The cache is keyed by `model` only, so two `PydanticDecoder()` instances with different configurations (none today, but `mode="strict"` etc. land later) would share adapters. Also: cache survives across tests unless cleared (the test file uses an autouse fixture).
  - Why deferring: `PydanticDecoder` has no per-instance config today and the test suite already handles isolation via `cache_clear()`. Revisit when/if a configurable `PydanticDecoder(mode=..., strict=...)` story lands.

- **[D-3] `extensions=dict(request.extensions)` forwards opaque user payloads to httpx2 verbatim** — `src/httpware/transports/httpx2.py:121`
  - `httpx2` interprets specific keys in `extensions` (e.g. `timeout`, `sni_hostname`). A typo or unknown key silently bypasses our timeout/limits config. No validation, no allowlist.
  - Why deferring: middleware (Epic 2) and per-request timeout (Story 3.1) will own the extensions contract surface; introducing an allowlist now risks blocking legitimate forward-compat uses.

- **[D-4] `Response.json()` swallows no exceptions and has no charset support** — `src/httpware/response.py:49-51`
  - `json.loads(self.content)` raises `json.JSONDecodeError` raw to callers and ignores any declared charset (`text` honors it). Inconsistent with `_try_decode_json` in the transport which never raises.
  - Why deferring: `Response.json()` is a convenience method; raising on malformed JSON is arguably correct (callers can `try/except`). The two-pass concern only matters for `response_model` paths, which go through `ResponseDecoder` and never touch this method. Revisit once `AsyncClient` lands (Story 1.7) and the call sites become observable.

### Discard

- **`response.headers` collapses multi-valued headers (`Set-Cookie`, `Via`, `Link`) to last value** — already in `planning/deferred-work.md` under story-1-4 (2026-05-13). Documented v0 contract on `Httpx2Transport` docstring lines 62-67.
- **`StatusError.body: bytes` retains full response body unboundedly** — already in deferred-work under story-1-4 (2026-05-14).
- **`httpx2.StreamError` family escapes the seam (`RuntimeError` subclasses)** — already in deferred-work under story-1-4 (2026-05-14); verified `StreamError.__mro__ == [StreamError, RuntimeError, Exception, BaseException, object]`.
- **Concurrent `aclose()` ↔ `__call__` race** — already in deferred-work under story-1-4 (2026-05-14). The `asyncio.Lock` only guards init, not lifecycle.
- **CRLF / log-injection on headers and URLs** — already in deferred-work (story-1-4 2026-05-14 + story-1-4 2026-05-13); Redactor (Story 5.3) owns it.
- **Userinfo persists in `StatusError.request_url` field (only stripped in `__repr__`/`__str__`)** — already in deferred-work under story-1-4 (2026-05-14); intentional per `errors.py:10-15`.
- **Unpinned `ruff` with `select=["ALL"]`** — already in deferred-work under story-1-1 (2026-05-13).
- **No `[test]` extra; CI uses `--all-extras`** — already in deferred-work under story-1-1 (2026-05-13).
- **`uv_build>=0.11,<0.12` narrow pin** — already in deferred-work under story-1-1.
- **Python 3.14 wheel availability risk** — already in deferred-work under story-1-1.
- **Codecov upload fails on fork PRs** — already in deferred-work under story-1-1.
- **`just publish` lacks env-var validation** — already in deferred-work under story-1-1.
- **`Request.with_url("")`, `with_query(None)`, header CRLF/None accepted** — covered by story-1-2 deferred-work block (Redactor / Story 2.3 territory).
- **`Timeout` / `Limits` negative value validation** — already in deferred-work under story-1-2.
- **`Multi-valued query params (Mapping[str, str])`** — already in deferred-work under story-1-2.
- **Streaming request bodies (`body: bytes | None` only)** — already in deferred-work under story-1-2.
- **Charset parser corner cases (quoted whitespace, multi-charset, substring false-positives)** — already in deferred-work under story-1-2.
- **`Response.json()` charset honoring** — covered by D-4 above; the broader item is also in deferred-work under story-1-2.
- **`@final` to prevent subclassing of value types** — already in deferred-work under story-1-2.
- **`PLR2004` per-file-ignores instead of inline `# noqa`** — already in deferred-work under story-1-5 (2026-05-14).
- **CHANGELOG bullet leaks `_get_adapter` implementation detail** — already in deferred-work under story-1-5.
- **Empty/malformed payload tests for the pydantic decoder** — already in deferred-work under story-1-5.
- **`@runtime_checkable` `isinstance` µs-cost** — already in deferred-work under story-1-5; matters only at Story 1.7.
- **`StatusError` not using `dataclass`** — considered; rejected. Exception subclasses with dataclass decorators break pickling and add a `__init_subclass__` cost. The hand-written `__init__` + `__reduce__` is the right call here.
- **`Response` doesn't expose `raise_for_status()`** — considered; rejected. The transport raises status errors *during* `__call__`; a 2xx `Response` cannot be in an error state, so the method would always be a no-op. Architecturally cleaner without it.
- **`test_transports_httpx2.py` uses `httpx2.MockTransport` directly instead of `RecordedTransport`** — considered; rejected. `RecordedTransport` is Story 1.8 (per `engineering.md` §6). Until it ships, `MockTransport` is the pragmatic choice.
- **`elapsed >= 0.0` is tautological in `test_success_path_returns_response`** — considered; rejected. `time.monotonic()` is non-decreasing so the assertion verifies the `start`/`end` ordering wasn't reversed. Cheap sanity.
- **Coverage config is line-only (no `--cov-branch` in default `addopts`)** — discarded. `test-branch` recipe in `Justfile:22-23` exists for explicit branch runs; this matches the "100% line coverage is the floor" stance in `engineering.md` §6.
- **`Response.text` `LookupError` fallback to `utf-8` could double-decode** — rejected on reread. The `try`/`except LookupError` wraps only the `decode()` call; the fallback path constructs a fresh `decode("utf-8")`. No double decode.
- **`pyproject.toml` declares `niquests` extra but no decoder/transport module imports it** — considered; rejected as nit. The extra is reserved for a future transport (per the `all` aggregate), causing no current harm.

## Already-deferred items observed

All ten "Discard" entries marked "already in deferred-work" were verified present in `planning/deferred-work.md` and are still real on the current HEAD. No re-raising; they remain accurate.

## Assessment

**Refactor-now count:** 0
**Defer count:** 4
**Discard count:** 25 (24 duplicates of existing deferred items + 5 rejected on consideration; one — D-4 — overlaps with an existing entry but is restated because the call-path concern is fresh)

**Recommendation:** No refactor needed — go straight to Epic 2. The four D-items can be appended to `planning/deferred-work.md` under a new "Deferred from: retrospective review (2026-05-31)" section in a follow-up commit, but none of them block middleware work. The architectural invariants are intact, the seams are clean, the exception contract is locked, and tests exercise the documented behavior (not implementation detail). The only structurally noteworthy observation is that the `_get_adapter` `TypeError` fallback in `decoders/pydantic.py` is test-driven rather than path-driven — worth keeping in mind when Story 1.6 reviews the `ResponseDecoder` protocol surface.

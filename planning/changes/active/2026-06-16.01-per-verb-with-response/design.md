---
status: draft
date: 2026-06-16
slug: per-verb-with-response
supersedes: null
superseded_by: null
pr: null
outcome: null
---

# Design: Per-verb `*_with_response` siblings

## Summary

Add `get_with_response`, `post_with_response`, `put_with_response`,
`patch_with_response`, `delete_with_response`, and `request_with_response` to
both `AsyncClient` and `Client`. Each takes a **required** `response_model` and
returns `tuple[httpx2.Response, T]` — the per-verb ergonomic form of the
existing `send_with_response`, for the "I need response metadata *and* a typed
body" case without the `build_request(...)` + `send_with_response(...)`
two-step. Additive, no breaking change; ships as 0.12.0.

## Motivation

`send_with_response` (shipped 0.8.2) covers the headers-plus-typed-body case —
Link-header pagination, ETag / rate-limit-header reads alongside a decoded
payload. But it forces a two-call shape:

```python
request = client.build_request("GET", "/users", params={"page": 2})
response, users = await client.send_with_response(request, response_model=list[User])
```

The plain verbs (`get`, `post`, …) already collapse `build_request` + `send`
into one call. There is no one-call form for the *with-response* path, so the
common "GET a page, read its `Link` header, decode its body" flow is wordier
than the body-only flow it sits beside. This was parked in
[`deferred.md`](../../deferred.md) under "Per-verb-with-response siblings"
pending concrete demand; the revisit trigger is now met.

The deferred note estimated "~400 LOC of overload boilerplate per side." That
estimate assumed each sibling needs the same 3-overload block the plain verbs
carry. It does not — see Design §1.

## Non-goals

- **No `head`/`options` siblings.** HEAD bodies are empty by definition;
  OPTIONS bodies are rarely decoded. `request_with_response("HEAD", ...)` is the
  escape hatch if ever needed.
- **No streaming variant.** `*_with_response` decodes `response.content`, which
  requires a fully-read body — same constraint as `send_with_response`. Use
  `stream()` for streaming.
- **No new top-level exports.** These are methods on existing classes; nothing
  joins `httpware.__all__`.
- **No change to `send_with_response` itself.** The siblings delegate to it.

## Design

### 1. No overloads — one call shape per sibling

The plain verbs carry three signatures each (two `@typing.overload` stubs for
`response_model: None → Response` and `response_model: type[T] → T`, plus the
implementation) because they have two return shapes. `send_with_response` has
**one** shape: `response_model` is required and the return is always
`tuple[Response, T]`. It is a single concrete method, no overloads — and the
verb siblings mirror that. Each sibling is one method: a body-kwargs signature
plus a one-line delegation (~15-25 lines), not a 3-overload block.

### 2. Extract `_prepare_request`, add a parallel with-response helper

`AsyncClient._request_with_body` (and its sync twin) currently inlines two
concerns: assembling the non-`None` kwargs dict + setting `STREAMING_BODY_MARKER`,
then calling `self.send(...)`. Split the first concern out so both paths share
it:

```python
def _prepare_request(self, method, url, *, params=None, headers=None,
                     cookies=None, timeout=USE_CLIENT_DEFAULT, extensions=None,
                     json=None, content=None, data=None, files=None) -> httpx2.Request:
    # kwargs-dict assembly + streaming-body marker (moved verbatim from
    # _request_with_body); returns the built httpx2.Request.

async def _request_with_body(self, method, url, *, ..., response_model=None):
    request = self._prepare_request(method, url, ...)
    return await self.send(request, response_model=response_model)

async def _request_with_body_with_response(self, method, url, *, ..., response_model: type[T]):
    request = self._prepare_request(method, url, ...)
    return await self.send_with_response(request, response_model=response_model)
```

The six verb siblings delegate to `_request_with_body_with_response` exactly as
the plain verbs delegate to `_request_with_body`. `_prepare_request` takes the
full body-kwarg superset; `get_with_response` simply does not pass the body
kwargs (mirroring plain `get`).

### 3. Sibling signatures

Each mirrors its plain verb's kwargs, with `response_model` promoted to required
keyword-only and the return type changed:

| Sibling | Kwargs (beyond `response_model`) | Returns |
|---|---|---|
| `get_with_response(url, *, ...)` | params, headers, cookies, timeout, extensions | `tuple[Response, T]` |
| `post_with_response(url, *, ...)` | …+ json, content, data, files | `tuple[Response, T]` |
| `put_with_response(url, *, ...)` | …+ json, content, data, files | `tuple[Response, T]` |
| `patch_with_response(url, *, ...)` | …+ json, content, data, files | `tuple[Response, T]` |
| `delete_with_response(url, *, ...)` | …+ json, content, data, files | `tuple[Response, T]` |
| `request_with_response(method, url, *, ...)` | …+ json, content, data, files | `tuple[Response, T]` |

`response_model: type[T]` is required (no default). Reuse the existing
`# noqa: PLR0913 — mirrors httpx2 per-method signatures` justification on the
wide-signature methods. Docstrings follow the plain verbs ("Send a GET request;
return (response, decoded).").

### 4. Inherited behavior (free via delegation)

Because every sibling bottoms out at `send_with_response`, it inherits without
new code:

- `MissingDecoderError` raised **before** the HTTP call when no decoder claims
  the model.
- `DecodeError` wrapping a decoder failure on a malformed body.
- `STREAMING_BODY_MARKER` handling for streaming request bodies (set in
  `_prepare_request`).

No new error paths are introduced.

### 5. Sync parity

`Client` gains the identical six siblings + the same helper split, sync flavor.
Sync and async surfaces stay at parity (an architecture invariant).

## Testing

- **Per-verb parity, async + sync** (12 verb × client combinations): each
  sibling returns a `(response, decoded)` tuple where `response` is the
  `httpx2.Response` (headers reachable, e.g. a seeded `Link` header) and the
  second element is the decoded model instance. Inject via `httpx2.MockTransport`
  per the testing convention.
- **Pre-flight `MissingDecoderError`:** calling a sibling with a model no
  decoder claims raises before the transport is hit (assert the mock saw zero
  requests).
- **`DecodeError` on bad payload:** a sibling against a malformed body raises
  `DecodeError` carrying `response`/`model`/`original`.
- **Typed-usage check:** one test (or a `ty`-checked usage) confirming the
  declared return is `tuple[Response, Model]` — no overloads to exercise, just
  the concrete return.
- `just test` green; `just lint` clean.

## Risk

- **Surface duplication drift (low × medium).** Six near-identical methods per
  side invite copy-paste errors (a wrong verb string, a dropped kwarg). The
  `_prepare_request` + `_request_with_body_with_response` extraction confines the
  logic to one place; the verb methods are pure delegation, and per-verb tests
  catch a wrong method string. The `_request_with_body` refactor is behavior-
  preserving and covered by the existing plain-verb suite.
- **`_prepare_request` regression (low × high).** Moving the kwargs/marker logic
  could subtly change request construction. Mitigated by running the full
  existing suite before adding siblings — the plain verbs exercise the moved
  code unchanged.

## Out of scope

`head_with_response` / `options_with_response`; a streaming with-response
variant; any change to `send`, `send_with_response`, or the decoder seam.

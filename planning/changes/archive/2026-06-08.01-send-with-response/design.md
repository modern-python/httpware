---
status: shipped
date: 2026-06-08
slug: send-with-response
supersedes: null
superseded_by: null
pr: 33
outcome: 'Shipped 0.8.2 — send_with_response'
---

# Spec: `send_with_response` — atomic (raw response, decoded body) pair

**Date:** 2026-06-08
**Topic slug:** `send-with-response`
**Status:** drafted, awaiting user review
**Target release:** `0.8.2` (patch — purely additive; no deprecations, no contract changes)

## Purpose

`httpware`'s `send(request, response_model=M)` overload returns a decoded `M` and discards the `httpx2.Response`. That's the right default — most callers want a typed body and nothing else. But a real class of callers needs **both**: the decoded body *and* the raw response (headers, status, request URL). The canonical case is RFC 5988 Link-header pagination, where the response body deserializes into a page model and the `Link` header drives the next request.

Today these callers fall back to raw `send(request)` and re-decode `response.content` by hand. semvertag's `list_tags` is the live example:

```python
response = self.http.send(self.http.build_request("GET", url, params=params))
items = _validate_tag_list(response)     # manual decode helper
```

The manual decode bypasses the configured `ResponseDecoder` (pydantic vs. msgspec swappability is wasted), and the decoder library's exceptions leak past `except httpware.ClientError` — the same hole `DecodeError` closed in `0.8.1` for the `send(..., response_model=)` path, now re-opened at the call site.

This spec adds one method per client class:

```python
def send_with_response(
    self, request: httpx2.Request, *, response_model: type[T],
) -> tuple[httpx2.Response, T]: ...
```

After this lands, the canonical pagination shape becomes:

```python
response, page = client.send_with_response(
    client.build_request("GET", url, params=params),
    response_model=PageModel,
)
next_url = _next_page_url(response, current_url=str(response.request.url))
```

The decoded body comes through the active `ResponseDecoder`. Decoder exceptions wrap as `DecodeError` (same seam, same shape as `send`). Status errors raise as `StatusError` subclasses (same terminal, same shape as `send`). `except httpware.ClientError` catches every failure mode.

## Non-goals

- **No per-verb siblings** (`get_with_response`, `post_with_response`, ...). Callers who need response metadata go through `build_request` + `send_with_response`. The `build_request` step is one line, costs nothing at runtime, and is already the pattern semvertag uses for pagination. Adding eight overloaded methods per client class (~400 LOC, mostly boilerplate) for a use case that asks for headers — which is rarely paired with body construction (`json=`, `data=`, `files=`) — would not pull its weight. Recorded in deferred-work post-merge; revisit if a concrete consumer demand surfaces.
- **No `request_with_response`** (high-level kwargs-forwarding variant with `method`/`url`/`json`/...). Same reasoning as the per-verb siblings — covered by `build_request` + `send_with_response`.
- **No `response_model=None` overload** returning `(Response, None)`. That's a second way to do `send(request)` and confuses the method's purpose. `response_model` is required, no default.
- **No streaming support.** `send_with_response` reads `response.content`, which requires the body to be fully buffered. `stream()` / `astream()` is a separate path that bypasses the middleware chain and yields a body-not-yet-read response — pairing it with `response_model=` is incoherent. Matches the existing `send(..., response_model=)` constraint.
- **No `@typing.overload` block.** The return type is always `tuple[httpx2.Response, T]` regardless of inputs. The overloaded form `send` uses exists to flip the return type based on whether `response_model=` is set; `send_with_response` has no such conditional.
- **No change to `send`, the verb methods, `ResponseDecoder`, `PydanticDecoder`, `MsgspecDecoder`, or any existing test.** Purely additive.
- **No new exception class.** `DecodeError` from `0.8.1` already has the right shape (`response`, `model`, `original`). Reuse, don't extend.
- **No deprecation pass.** No previously-public API is being changed or removed.

## Architecture

### The seam

`send_with_response` lands at the same internal seam as `send`: between the middleware-composed `_dispatch` call (which produces an `httpx2.Response`) and `self._decoder.decode(...)` (which produces a typed `T`). The only difference from `send` is what the method returns — both values, instead of one.

```text
                    ┌──────────────────────────────┐
                    │   client.send_with_response  │
                    └──────────────┬───────────────┘
                                   │
            ┌──────────────────────┴──────────────────────┐
            │                                             │
   self._dispatch(request)               self._decoder.decode(content, model)
   ── raises StatusError                 ── raises *anything* on failure
      / TransportError / etc.               → wrapped as DecodeError
   ── (NOT wrapped by this method)          (Seam 3, per decoder-error spec)
            │                                             │
            └──────────────────────┬──────────────────────┘
                                   │
                          return (response, decoded)
```

This is the same seam shape as `send(..., response_model=)` (`src/httpware/client.py:147` async, `:867` sync). The try/except wraps only the decode call; `_dispatch` failures propagate untouched because `_terminal` (`client.py:130` async, `:826` sync) already maps them through `_httpx2_exception_mapper` and `_raise_on_status_error`.

### Placement

`send_with_response` lives directly under `send` in both classes:

- `AsyncClient.send_with_response` — inserted between `AsyncClient.send` (ends at `client.py:160`) and `AsyncClient.build_request` (starts at `client.py:162`).
- `Client.send_with_response` — inserted between `Client.send` (ends at `client.py:880`) and `Client.build_request` (starts at `client.py:882`).

Placement matters for IDE autocomplete (callers typing `client.send` see both methods adjacent) and for stack-trace readability (`send_with_response` shows up by name, not as `send` with a flag).

### Signature

**`AsyncClient.send_with_response`:**

```python
async def send_with_response(
    self,
    request: httpx2.Request,
    *,
    response_model: type[T],
) -> tuple[httpx2.Response, T]:
    """Send `request` through the middleware chain; return (response, decoded).

    Use this when you need response metadata (headers, status, request URL)
    AND a typed body — most commonly for Link-header pagination. For the
    body-only case, prefer ``send(request, response_model=...)``.

    Not for streaming responses — decodes ``response.content``, which requires
    the body to be fully read. Use ``stream()`` for streaming.
    """
    response = await self._dispatch(request)
    try:
        decoded = self._decoder.decode(response.content, response_model)
    except Exception as exc:
        raise DecodeError(response=response, model=response_model, original=exc) from exc
    return response, decoded
```

**`Client.send_with_response`:** structurally identical, drops the `async`/`await` and uses `self._dispatch(request)` synchronously. The docstring is the same.

`response_model: type[T]` is keyword-only and has no default — callers who don't want a decoded body should use `send(request)` instead. The `*` separator is consistent with every other method on these classes (no positional `response_model` anywhere in the codebase).

No `@typing.overload` block — the return type is always `tuple[httpx2.Response, T]`, so there is nothing to overload.

### Why a separate method, not an overload on `send`

The proposal-stage alternative was `send(request, *, response_model=M, with_response=True) -> tuple[Response, T]`. Rejected:

- `send` today has exactly two overloads, each with a clean single-value return (`Response` or `T`). Adding a third flag-driven conditional return mixes shape with mode — readers have to look up what `with_response=True` does to understand the signature.
- `send_with_response` shows up by name in stack traces, IDE autocomplete, and grep results. `send` called with a flag does not.
- The cost is one additional public name. The benefit is type-signature clarity that scales to every future reader of `send`.

The trade-off: callers who want headers + a typed body from a verb method (`client.get(url, response_model=M)` style) have to drop down to `build_request` + `send_with_response`. That's acceptable because the headers-and-body case is rarely paired with body construction kwargs (`json=`, `data=`, `files=`) — it's almost always pagination over a GET. One extra line at the call site is a fair price for keeping `get`/`post`/etc. simple.

## Error contract

Identical to `send(..., response_model=)`. Three failure modes:

1. **Transport / timeout failure** during `_dispatch`. `_terminal` maps the underlying `httpx2.HTTPError` to a `TransportError` / `TimeoutError` / `NetworkError` subclass via `_httpx2_exception_mapper`. Propagates untouched out of `send_with_response`.
2. **Status error** during `_dispatch`. `_terminal` calls `_raise_on_status_error(response)` for 4xx/5xx and raises a `StatusError` subclass (`NotFoundError`, `ServiceUnavailableError`, etc.). Propagates untouched.
3. **Decode failure** after `_dispatch` returns a 2xx/3xx response. The decoder raises some library-specific exception (`pydantic.ValidationError`, `msgspec.DecodeError`, ...) — the `except Exception` block wraps it in `DecodeError(response=, model=, original=)` and re-raises via `raise ... from exc`.

All three are subclasses of `ClientError`. `except httpware.ClientError` is the catch-all, exactly as advertised.

The reuse of `DecodeError` is deliberate. `DecodeError.response` carries the same `httpx2.Response` the caller would have received on the success path — there is no information loss compared to `send(..., response_model=)`. A consumer can already do:

```python
try:
    response, page = client.send_with_response(req, response_model=Page)
except DecodeError as exc:
    headers = exc.response.headers   # same response as the success path
    ...
```

No new exception class. No `PayloadError` parent. YAGNI.

## Tests

Two new test files mirroring the existing sync/async split:

- `tests/test_client_send_with_response.py` — async, parallels `test_client_response_model.py`'s structure
- `tests/test_client_send_with_response_sync.py` — sync, parallels `test_client_sync.py`'s structure

Each file covers:

| Case | Assertion |
|---|---|
| Success — 2xx, valid body | Returns `(response, decoded)`; `response` is an `httpx2.Response`; `decoded` is an instance of `response_model`; `response.content` is unchanged. |
| Decode failure — 2xx, malformed body | Raises `DecodeError`; `exc.response` is the same response; `exc.model is response_model`; `exc.original` is the underlying decoder exception (`pydantic.ValidationError` / `msgspec.DecodeError`). `except httpware.ClientError` catches it. |
| Status failure — 4xx | Raises the matching `StatusError` subclass (e.g., `NotFoundError`). `DecodeError` is *not* raised. |
| Middleware chain runs | A user middleware that mutates `request.headers["x-test"]` runs before transport; the value is observable in the recorded request on the mock transport. |
| `response.request` populated | `response.request` is the (post-middleware) request, suitable for `str(response.request.url)` in pagination loops. |

Test fixtures reuse the existing `mock_transport` / `RecordedTransport` patterns from `tests/`. No new decoder fixtures — the existing pydantic ones cover the decode-failure path.

Total: ~10 test functions per file, ~150 LOC across both. No changes to existing tests.

## Docs

One addition to `docs/index.md`, immediately after the existing `send` section in the Client reference. ~15 lines:

```markdown
### `send_with_response`

When you need both the raw `httpx2.Response` (for headers, status, or
request URL) **and** a typed body, use `send_with_response`. It returns
both atomically and routes the decode through the configured
`ResponseDecoder`, so decoder failures surface as `DecodeError` — caught
by `except httpware.ClientError` like every other failure mode.

Canonical use case: Link-header pagination.

    response, page = client.send_with_response(
        client.build_request("GET", url, params={"page": 1}),
        response_model=PageModel,
    )
    next_url = _next_page_url(response.headers.get("link"))

For the body-only case, prefer `send(request, response_model=...)`.
`send_with_response` is not for streaming responses — use `stream()`.
```

No new page under `docs/recipes/`. No autodoc additions. No benchmarks. Matches the documented project docs philosophy (`MEMORY.md` → `user_docs_philosophy.md`).

## Release

**`0.8.2` — patch.**

- Production code: ~30 LOC across both `AsyncClient` and `Client`.
- Tests: ~150 LOC across two new test files.
- Docs: ~15 lines added to `docs/index.md`.
- Public surface change: one new method per client class. No removals, no deprecations, no behavior changes on existing methods.
- Tag → publish workflow: same as `0.8.1`. Bare-semver tag, GitHub Release notes, no `CHANGELOG.md`.

Semver justification: a `0.x` minor would be defensible too (new public API), but the project's recent pattern (`0.8.1`'s `DecodeError` addition was a patch) sets the precedent — additive surface in a defect-adjacent context releases as a patch. Calling it `0.8.2` keeps that consistency.

## Out of scope, recorded for later

- **Per-verb siblings** (`get_with_response`, etc.) — if a concrete httpware consumer beyond semvertag's `list_tags` surfaces a need, revisit. Until then, file under `planning/deferred-work.md` post-merge.
- **Pagination helper** (`paginate_links(client, request, response_model=...) -> Iterator[T]`) — tempting because Link-header pagination is the dominant `send_with_response` use case, but a generic pagination helper has to make choices (RFC 5988 only? cursor-style? page-number style?) that belong in the consuming library, not in `httpware`. Out of scope for the foreseeable future.

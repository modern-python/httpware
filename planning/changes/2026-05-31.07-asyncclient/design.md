---
summary: Shipped in 0.1.0; rewritten by the v0.2 pivot *(superseded by thin-httpx2-wrapper)*
---

# AsyncClient (design)

- **Date:** 2026-05-31
- **Status:** approved, ready for plan
- **Scope:** Story 1-7 (seventh story of Epic 1). Ships the main public surface: `AsyncClient` with HTTP method shortcuts, typed `response_model` overloads, per-call overrides, lifecycle management, and `with_options`. Wires middleware via `compose()` (Story 2-1) since that story already landed. Out of scope: `auth=` parameter (Story 2-4), `data=`/`files=` body params (follow-up), transport reference-counting (deferred), streaming (Epic 4), observability (Epic 5), `RecordedTransport` (Story 1-8).
- **Roadmap pointer:** `docs/dev/engineering.md` §8 "Epic 1 — Make typed HTTP requests with sensible defaults".

## Why

`AsyncClient` is the v0.1.0 entry point of httpware. Stories 1-2 through 1-6 built the substrate (data types, exceptions, transport, decoders); stories 2-1 through 2-3 built the middleware infrastructure. Story 1-7 stitches them into a single ergonomic class: construct it, issue HTTP requests with optional typed responses, close it.

The pragmatic scope decision: wire middleware now since `compose()` exists, but defer `auth=` to Story 2-4 (which has its own coercion-rule design surface), defer the more complex body params (`data`/`files`), and skip transport reference-counting in favor of a simpler "original owns lifecycle" model. This keeps Story 1-7 tractable while shipping a useful client.

## Decisions

| Decision | Choice |
| --- | --- |
| Scope | Pragmatic — middleware wired, no `auth=`, no transport ref-counting, body params limited to `json` and `content`. |
| Module location | `src/httpware/client.py` (top-level module). |
| Construction | Keyword-only `__init__`; sensible defaults (`Httpx2Transport`, `PydanticDecoder`, empty middleware). |
| `from_url` | Thin classmethod factory: `return cls(base_url=base_url, **kwargs)`. |
| `timeout` polymorphism | `Timeout \| float \| None` — bare `float` coerces to `Timeout(connect=x, read=x, write=x, pool=x)`; `None` → default `Timeout()`. |
| `middleware` type | `Sequence[Middleware]` (matches `compose`'s signature; accepts tuples). |
| `ClientConfig` extension | Add `decoder: ResponseDecoder` and `middleware: tuple[Middleware, ...]` fields with defaults. Backwards-compatible. |
| URL join | httpx-style prefix join: `base_url` is treated as a literal prefix with slash normalization; absolute URLs pass through. |
| Body params | `json` (stdlib `json.dumps(...).encode()`, auto-sets `Content-Type: application/json`) and `content` (raw bytes). Passing both raises `TypeError`. |
| Default merging | Per-call `headers`/`params` override per-client defaults via `{**default, **per_call}`. No client-level cookie jar; per-call only. |
| Response decoding | `response_model is None` → returns `Response`. `response_model: type[T]` → returns `self._config.decoder.decode(response.content, response_model)`. |
| Typed overloads | Two `@overload` declarations per HTTP method (None-response_model vs typed-response_model). 8 methods × 2 overloads = 16 stubs. `ty` validates via `tests/test_client_typing.py`. |
| HTTP methods | `get`, `post`, `put`, `patch`, `delete`, `head`, `options`, `request` (8 total). `request` adds a leading `method` positional parameter. |
| Lifecycle | `__aenter__` returns `self`. `__aexit__` calls `transport.aclose()` only if `_owns_transport=True`. |
| `with_options` | Keyword-only allowlist (`base_url`, `default_headers`, `default_query`, `timeout`, `decoder`, `middleware`). Returns a new `AsyncClient` with `_owns_transport=False` sharing the same transport. `limits` and `transport` are not allowed (would require swapping transports). |
| Transport lifecycle model | Simple: the original `AsyncClient` owns the transport. Views from `with_options` do not. No ref-counting. View `__aexit__` is a no-op. |
| Integration tests against external hosts | Not included. Archived AC mentions `httpbingo.org`; deferred to an opt-in `@pytest.mark.integration` test for a follow-up. |

## File structure

**New files:**
- `src/httpware/client.py` — `AsyncClient` class and supporting internals.
- `tests/test_client_construction.py` — defaults, `from_url`, param validation.
- `tests/test_client_methods.py` — 8 HTTP methods build correct Requests; default merging; URL resolution.
- `tests/test_client_response_model.py` — decoder invocation; `response_model is None` returns raw `Response`.
- `tests/test_client_typing.py` — `ty`-checked file verifying overload return types.
- `tests/test_client_lifecycle.py` — `async with`, view no-op on close, double-close safety.
- `tests/test_client_middleware_wiring.py` — middleware actually runs; `with_options(middleware=...)` re-composes.

**Modified files:**
- `src/httpware/config.py` — extend `ClientConfig` with `decoder` and `middleware` fields.
- `src/httpware/__init__.py` — export `AsyncClient` at package root.
- `CHANGELOG.md` — Story 1.7 bullet.

**Files NOT touched:**
- `src/httpware/request.py`, `response.py`, `errors.py`, `decoders/*`, `middleware/*`, `_internal/*`, `transports/*`.
- `pyproject.toml`.

## Construction

```python
class AsyncClient:
    """Async HTTP client with typed response decoding and middleware composition."""

    _config: ClientConfig
    _transport: Transport
    _dispatch: Next
    _owns_transport: bool

    def __init__(
        self,
        *,
        base_url: str | None = None,
        default_headers: Mapping[str, str] | None = None,
        default_query: Mapping[str, str] | None = None,
        timeout: Timeout | float | None = None,
        limits: Limits | None = None,
        transport: Transport | None = None,
        decoder: ResponseDecoder | None = None,
        middleware: Sequence[Middleware] | None = None,
    ) -> None:
        normalized_timeout = _normalize_timeout(timeout)
        resolved_limits = limits or Limits()
        resolved_transport = transport or Httpx2Transport(
            limits=resolved_limits, timeout=normalized_timeout
        )
        resolved_decoder = decoder or PydanticDecoder()
        resolved_middleware = tuple(middleware) if middleware is not None else ()

        self._config = ClientConfig(
            base_url=base_url,
            default_headers=dict(default_headers or {}),
            default_query=dict(default_query or {}),
            timeout=normalized_timeout,
            limits=resolved_limits,
            decoder=resolved_decoder,
            middleware=resolved_middleware,
        )
        self._transport = resolved_transport
        self._dispatch = compose(resolved_middleware, resolved_transport)
        self._owns_transport = True

    @classmethod
    def from_url(cls, base_url: str, **kwargs: Any) -> "AsyncClient":
        """Construct an AsyncClient with a base URL prefix."""
        return cls(base_url=base_url, **kwargs)
```

`_normalize_timeout`:

```python
def _normalize_timeout(value: Timeout | float | None) -> Timeout:
    if value is None:
        return Timeout()
    if isinstance(value, Timeout):
        return value
    return Timeout(connect=value, read=value, write=value, pool=value)
```

`ClientConfig` is extended:

```python
@dataclass(frozen=True, slots=True)
class ClientConfig:
    base_url: str | None = None
    default_headers: Mapping[str, str] = field(default_factory=dict)
    default_query: Mapping[str, str] = field(default_factory=dict)
    timeout: Timeout = field(default_factory=Timeout)
    limits: Limits = field(default_factory=Limits)
    decoder: ResponseDecoder = field(default_factory=PydanticDecoder)
    middleware: tuple[Middleware, ...] = ()
```

Existing tests for `ClientConfig` (Story 1-2) keep passing because the new fields have defaults. Note that `field(default_factory=PydanticDecoder)` introduces a constructor-time dependency from `config.py` on `decoders/pydantic.py`. Acceptable — pydantic is a hard dep.

## URL resolution and request building

```python
def _resolve_url(self, path: str) -> str:
    if path.startswith(("http://", "https://")):
        return path
    base = self._config.base_url
    if base is None:
        return path
    return f"{base.rstrip('/')}/{path.lstrip('/')}"


def _build_request(
    self,
    method: str,
    path: str,
    *,
    headers: Mapping[str, str] | None,
    params: Mapping[str, str] | None,
    cookies: Mapping[str, str] | None,
    timeout: Timeout | float | None,
    body: bytes | None,
    content_type: str | None,
) -> Request:
    merged_headers: dict[str, str] = {**self._config.default_headers, **(headers or {})}
    if content_type is not None and "content-type" not in {k.lower() for k in merged_headers}:
        merged_headers["content-type"] = content_type
    merged_params: dict[str, str] = {**self._config.default_query, **(params or {})}
    extensions: dict[str, Any] = {}
    if timeout is not None:
        extensions["timeout"] = _normalize_timeout(timeout)
    return Request(
        method=method,
        url=self._resolve_url(path),
        headers=merged_headers,
        params=merged_params,
        cookies=dict(cookies or {}),
        body=body,
        extensions=extensions,
    )
```

Body builder:

```python
def _build_body(
    json_value: Any | None, content: bytes | None
) -> tuple[bytes | None, str | None]:
    if json_value is not None and content is not None:
        raise TypeError("pass either `json` or `content`, not both")
    if json_value is not None:
        return json.dumps(json_value).encode("utf-8"), "application/json"
    return content, None
```

## HTTP methods and overloads

Each method follows this shape (worked example: `get`):

```python
@overload
async def get(
    self,
    path: str,
    *,
    headers: Mapping[str, str] | None = None,
    params: Mapping[str, str] | None = None,
    cookies: Mapping[str, str] | None = None,
    timeout: Timeout | float | None = None,
    response_model: None = None,
) -> Response: ...

@overload
async def get(
    self,
    path: str,
    *,
    headers: Mapping[str, str] | None = None,
    params: Mapping[str, str] | None = None,
    cookies: Mapping[str, str] | None = None,
    timeout: Timeout | float | None = None,
    response_model: type[T],
) -> T: ...

async def get(
    self,
    path: str,
    *,
    headers: Mapping[str, str] | None = None,
    params: Mapping[str, str] | None = None,
    cookies: Mapping[str, str] | None = None,
    timeout: Timeout | float | None = None,
    response_model: type[T] | None = None,
) -> Response | T:
    return await self._send(
        "GET", path,
        headers=headers, params=params, cookies=cookies, timeout=timeout,
        body=None, content_type=None,
        response_model=response_model,
    )
```

**Variations by method:**

- `head`, `options`, `delete` — same signature as `get` (no body params, `body=None`).
- `post`, `put`, `patch` — add `json: Any | None = None` and `content: bytes | None = None` keyword-only params; body resolution via `_build_body`.
- `request` — adds a required `method: str` positional parameter as the first arg.

**Shared `_send` helper:**

```python
async def _send(
    self,
    method: str,
    path: str,
    *,
    headers, params, cookies, timeout, body, content_type,
    response_model,
):
    request = self._build_request(
        method, path,
        headers=headers, params=params, cookies=cookies, timeout=timeout,
        body=body, content_type=content_type,
    )
    response = await self._dispatch(request)
    if response_model is None:
        return response
    return self._config.decoder.decode(response.content, response_model)
```

**Code volume estimate:** 8 methods × (2 overloads + 1 body) ≈ 24 declarations + the runtime helpers. `client.py` total ≈ 350 lines (heavy with type signatures).

## Lifecycle and `with_options`

```python
async def __aenter__(self) -> "AsyncClient":
    return self

async def __aexit__(self, exc_type, exc, tb) -> None:
    if self._owns_transport:
        await self._transport.aclose()
```

The transport's lazy `httpx2.AsyncClient` initialization (Story 1-4) handles the first-request case; entering the context manager does NOT eagerly create the underlying client.

```python
def with_options(
    self,
    *,
    base_url: str | None = ...,
    default_headers: Mapping[str, str] | None = ...,
    default_query: Mapping[str, str] | None = ...,
    timeout: Timeout | float | None = ...,
    decoder: ResponseDecoder | None = ...,
    middleware: Sequence[Middleware] | None = ...,
) -> "AsyncClient":
    """Return a new AsyncClient sharing the same transport with overridden config.

    The returned client is a "view": it does NOT own the transport lifecycle.
    Closing it via `async with` is a no-op. The original client should be the
    one inside the outermost `async with` block.
    """
    ...
```

**Sentinel pattern:** since `None` is a valid value for several overrides (e.g., `default_headers=None` could mean "remove all defaults"), the implementation uses a sentinel object `_UNSET` and checks `if param is _UNSET:` to distinguish "not overridden" from "explicitly set to None". Standard pattern in Python libraries.

Implementation:

```python
_UNSET: Any = object()


def with_options(
    self,
    *,
    base_url: str | None = _UNSET,
    default_headers: Mapping[str, str] | None = _UNSET,
    default_query: Mapping[str, str] | None = _UNSET,
    timeout: Timeout | float | None = _UNSET,
    decoder: ResponseDecoder | None = _UNSET,
    middleware: Sequence[Middleware] | None = _UNSET,
) -> "AsyncClient":
    changes: dict[str, Any] = {}
    if base_url is not _UNSET:
        changes["base_url"] = base_url
    if default_headers is not _UNSET:
        changes["default_headers"] = dict(default_headers or {})
    if default_query is not _UNSET:
        changes["default_query"] = dict(default_query or {})
    if timeout is not _UNSET:
        changes["timeout"] = _normalize_timeout(timeout)
    if decoder is not _UNSET:
        changes["decoder"] = decoder or PydanticDecoder()
    if middleware is not _UNSET:
        changes["middleware"] = tuple(middleware) if middleware is not None else ()

    new_config = dataclasses.replace(self._config, **changes)
    return AsyncClient._from_view(new_config, self._transport)


@classmethod
def _from_view(cls, config: ClientConfig, transport: Transport) -> "AsyncClient":
    """Construct a view sharing an existing transport. Bypasses __init__."""
    client = cls.__new__(cls)
    client._config = config
    client._transport = transport
    client._dispatch = compose(config.middleware, transport)
    client._owns_transport = False
    return client
```

**Behavioral notes carried into docstrings:**

- Views (returned by `with_options`) do not manage transport lifecycle.
- A view's `__aexit__` is intentionally a no-op.
- If a user opens a view in `async with view:` and the original is still open, that's fine — the transport stays alive (the original closes it).
- If a user opens a view in `async with view:` and the original has already closed, the transport is closed and any request from the view will fail. The user is responsible for ordering.
- Closing the original client a second time (via two separate `async with` blocks, or by calling `aclose()` explicitly) is safe: `Httpx2Transport.aclose` is idempotent.
- `with_options(limits=...)` and `with_options(transport=...)` are not accepted (omitted from the parameter list). Construct a fresh `AsyncClient` for those.

## Testing

### `tests/test_client_construction.py`

- `test_init_defaults_provide_transport_and_decoder` — `AsyncClient()` produces a client with `Httpx2Transport`/`PydanticDecoder`.
- `test_init_accepts_explicit_transport` — passing `transport=` skips the default.
- `test_init_accepts_explicit_decoder` — passing `decoder=` skips the default.
- `test_init_accepts_explicit_middleware` — list of middleware accepted; stored as tuple.
- `test_init_normalizes_float_timeout` — `timeout=5.0` becomes `Timeout(5.0, 5.0, 5.0, 5.0)`.
- `test_init_keeps_timeout_instance` — `timeout=Timeout(connect=1)` preserved.
- `test_init_normalizes_none_timeout` — `timeout=None` becomes default `Timeout()`.
- `test_from_url_classmethod` — `AsyncClient.from_url("https://api.example.com")` sets `base_url`.
- `test_constructor_is_side_effect_free` — no transport I/O (the transport's lazy init guard means no `httpx2.AsyncClient()` either).

### `tests/test_client_methods.py`

Uses a `_RecordingTransport` fake (local to the file) that captures the last `Request` and returns a canned `Response`.

- `test_get_builds_request_with_method_and_url` — verifies `Request(method="GET", url="...")`.
- `test_post_with_json_serializes_and_sets_content_type` — `json={"a": 1}` becomes `b'{"a":1}'` and `Content-Type: application/json`.
- `test_post_with_content_preserves_bytes_unchanged` — `content=b"raw"` → `Request.body == b"raw"`, no Content-Type added.
- `test_post_json_and_content_raises_typeerror` — `json=` AND `content=` together raises.
- `test_default_headers_merged_with_per_call_headers` — defaults present, per-call wins on conflicts.
- `test_default_query_merged_with_per_call_params` — same for query.
- `test_per_call_headers_with_explicit_content_type_skips_auto_injection` — `Content-Type` set in `headers=` is not overridden by the `json=` auto-injection.
- `test_absolute_url_bypasses_base_url` — `client.get("https://other.com/foo")` produces request URL = the absolute URL.
- `test_relative_path_joins_with_base_url` — `base_url="https://api/v1"` + `get("/users")` → `"https://api/v1/users"`.
- `test_relative_path_without_leading_slash_joins_same_way` — `get("users")` → same result.
- One test per remaining HTTP method (`head`, `options`, `delete`, `put`, `patch`, `request`) verifying the method string in the produced `Request`.

### `tests/test_client_response_model.py`

- `test_response_model_none_returns_raw_response` — `await client.get(url)` returns a `Response` object.
- `test_response_model_invokes_decoder` — passing `response_model=Foo` invokes `self._config.decoder.decode(content, Foo)`; returns the decoded instance.
- `test_response_model_uses_supplied_decoder` — passing `decoder=MockDecoder()` at construction routes through it.

### `tests/test_client_typing.py`

A `ty`-checked file with statements that fail type-check if the overload is wrong. Example:

```python
from httpware import AsyncClient, Response
from pydantic import BaseModel


class _Item(BaseModel):
    name: str


async def _check_overloads(client: AsyncClient) -> None:
    resp: Response = await client.get("/foo")
    item: _Item = await client.get("/foo", response_model=_Item)
    # If the overload is wrong, ty would reject the type-narrowed assignments.
    assert resp is not None
    assert item is not None
```

`just lint-ci` already runs `ty check` over the repo; this file is included automatically.

### `tests/test_client_lifecycle.py`

- `test_async_with_calls_aclose_on_exit` — uses a `_TrackingTransport` that records `aclose()` calls; `async with client:` ends with one call.
- `test_view_async_with_does_not_close_transport` — `async with view:` ends with zero `aclose()` calls on the underlying transport.
- `test_double_close_is_safe` — entering the context manager twice (in separate blocks) doesn't raise.
- `test_aenter_returns_self` — `async with client as c: assert c is client`.

### `tests/test_client_middleware_wiring.py`

- `test_middleware_runs_per_request` — pass `middleware=[recorder]`; one client request invokes `recorder` once.
- `test_with_options_recomposes_middleware` — `client.with_options(middleware=[other])` produces a view whose chain runs `other`, not the parent's `recorder`.
- `test_with_options_inherits_middleware_when_unset` — `client.with_options(timeout=10)` keeps the parent's middleware chain.

**Test count:** ~38 tests across the six files. Coverage target: 100% line coverage on `src/httpware/client.py`.

### Test fixtures

`_RecordingTransport`, `_TrackingTransport`, etc. are file-local. They satisfy the `Transport` protocol (the `# pragma: no cover` pattern from prior stories applies to `stream` and `aclose` stubs that aren't exercised).

Story 1-8 (`RecordedTransport`) will replace these in a future refactor; this spec doesn't depend on 1-8 shipping first.

## Constraints and invariants

- **No `httpx2` import in `client.py`.** The default-transport path goes through `from httpware.transports.httpx2 import Httpx2Transport` (the only seam allowed). The existing `tests/test_no_httpx2_leakage.py` catches regressions.
- **No `from __future__ import annotations`.** Native PEP 604/585.
- **No `print()`, no `logging.basicConfig`.**
- **No `# type: ignore`.** `# ty: ignore[<rule>]` only with documented reason; expected to be unused in this story.
- **No `# noqa: PLC0415`** on in-function imports (memory: project preference).
- **Existing CI invariants** (`tests/test_no_httpx2_leakage.py`, `tests/test_optional_extras_isolation.py`) continue to pass.

## Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| `ty` rejects the `@overload` declarations because of subtle signature mismatch. | The overloads are mechanical; if `ty` complains, the implementer adjusts at task time. Worked-example pattern in Section "HTTP methods and overloads" is taken from typeshed and httpx's own stubs. |
| The `_UNSET` sentinel leaks into reprs or error messages. | `_UNSET` is a private module-level constant; never appears in user-facing output. The `with_options` method body resolves it before storing anything in `ClientConfig`. |
| `ClientConfig` carrying `decoder` and `middleware` couples the config dataclass to those concepts (was previously pure transport config). | Accepted. The alternative (separate config types per concern) adds friction without value at this scale. |
| `_resolve_url` slash-normalization is wrong for some edge case (multiple slashes mid-URL, trailing slash on path). | The rule (`f"{base.rstrip('/')}/{path.lstrip('/')}"`) covers the common cases. Edge cases (e.g., `path="//foo"`) are user errors and are not normalized further. Documented in the docstring. |
| Views are confusing — users expect `async with view:` to clean up. | Docstrings on both `AsyncClient.__aexit__` and `with_options` explain the model clearly. The simpler-than-Decision-9 lifecycle is a documented tradeoff; ref-counting can be added later without breaking the public API. |
| The `_from_view` constructor uses `cls.__new__(cls)` and bypasses `__init__`, which can surprise subclasses. | `AsyncClient` is not designed for subclassing in v0. Subclasses that override `__init__` will break. Acceptable for v0; documented. |
| `tests/test_client_typing.py` runs `ty check` as part of `just lint-ci`, but isn't a runtime pytest test. | Add a one-line runtime test inside the file (`def test_typing_module_imports_cleanly`) that simply imports the typed names. Coverage will show the file is reachable; `ty` does the real work. |
| Decoder error during `decode()` masks a successful response. | `decode` raises `pydantic.ValidationError` / `msgspec.ValidationError` per Stories 1-5 and 1-6. AsyncClient does not catch — caller sees the validation error with the original content available on the (already-returned-but-not-yet-decoded) response. Documented. |

## Definition of done

- `src/httpware/client.py` exists with `AsyncClient`, `_normalize_timeout`, `_build_body`, `_UNSET`, and `_from_view`.
- `src/httpware/config.py` extends `ClientConfig` with `decoder` and `middleware` fields.
- `src/httpware/__init__.py` exports `AsyncClient` at the package root and adds it to `__all__` in alphabetic position.
- All six test files exist with the test list above; ~38 tests; all pass.
- `tests/test_client_typing.py` includes the `ty`-checked overload-validation file.
- `just test` shows the increment from the post-1-6 baseline of 208 → ~246 passed, 1 deselected, 100% line coverage on `client.py` and the extended `ClientConfig`.
- `just lint-ci` clean.
- `tests/test_no_httpx2_leakage.py` still passes.
- `tests/test_optional_extras_isolation.py` still passes.
- CHANGELOG bullet under `[Unreleased]` / `### Added` describes the public surface plus the out-of-scope items (auth, data/files, ref-counting, streaming, observability).
- Story 1-7 lands as a single PR off `main` via the branch `story/1-7-asyncclient`.

# Phase-shortcut decorators (design)

- **Date:** 2026-05-31
- **Status:** approved, ready for plan
- **Scope:** Story 2-2 (second story of Epic 2). Defines `@before_request`, `@after_response`, and `@on_error` decorators that wrap simple async user functions into `Middleware`-conforming instances. Out of scope: AsyncClient wiring (2-5), `Request.with_*` helpers beyond what exists (2-3), auth coercion (2-4).
- **Roadmap pointer:** `docs/engineering.md` §8 "Epic 2 — Compose request-handling logic via middleware".

## Why

Most middleware does one thing — stamp a request, log a response, recover from an error. Forcing every consumer to author a full `Middleware` class for those cases is friction. The phase-shortcut decorators wrap the common patterns: one async function in, one `Middleware` instance out, ready to drop into the chain.

The shape is decided by the archived epic spec (`docs/archive/epics.md` Epic 2 → Story 2.2). This spec ports that design forward with three small choices that the archive left open: naming consistency, file location, and implementation shape.

## Decisions

| Decision | Choice |
| --- | --- |
| Decorator names | `@before_request`, `@after_response`, `@on_error`. Matches the archived epic spec. `before/after` for phases that fire around a successful response; `on_error` for the event-driven error case. |
| Location | All three live in `src/httpware/middleware/__init__.py` alongside `Middleware` and `Next`. The file grows from ~30 to ~95 lines, all on the same seam. |
| Implementation shape | Each decorator factory defines a private class (e.g., `_BeforeRequestMiddleware`) inside its body, instantiates it, returns the instance. Per-phase classes keep `__call__` bodies single-purpose and give each decorated middleware a distinct `__repr__`. |
| User-function sync/async | Async only. The user writes `async def f(...) -> ...`; sync wrappers are the user's responsibility. |
| `@on_error` callback type | `Callable[[Request, Exception], Awaitable[Response | None]]`. Archive said `BaseException`; that was misleading since the chain only catches `Exception`. `Exception` is the accurate type. |
| `@on_error` exception scope | Catches `Exception`, not `BaseException`. `asyncio.CancelledError` (and `SystemExit`, `KeyboardInterrupt`) propagate untouched. |
| `@on_error` return contract | If the handler returns a `Response`, that Response is returned to the caller. If it returns `None`, the original exception is re-raised (bare `raise` to preserve traceback). |
| `BaseExceptionGroup` carve-out | None. PEP 654 `ExceptionGroup` is a subclass of `Exception` and is caught like any other. Users carve out groups themselves if needed. |
| Public exports | `before_request`, `after_response`, `on_error` exported from `httpware.middleware` and re-exported at `httpware`. Matches the existing `Middleware` / `Next` re-export pattern. |
| Roadmap doc fix | Bundled in: `docs/engineering.md` §8 says `(@on_request, @on_response, @on_error)`. Rewrite to `(@before_request, @after_response, @on_error)` to match the spec. |
| Scope | Strict — no AsyncClient wiring, no extra `Request` helpers, no auth coercion. Those land in stories 2-3 through 2-5. |

## File structure

**Modified files:**

```
src/httpware/middleware/__init__.py    # add 3 decorator factories + 3 private classes (~65 lines added)
src/httpware/__init__.py               # re-export 3 names; extend __all__
docs/engineering.md                    # fix §8 line 142 decorator names
CHANGELOG.md                           # add Story 2.2 bullet under [Unreleased] / ### Added
tests/test_middleware.py               # 10 new tests appended (14 → 24)
```

**Files not touched:** every other source file. Story 2-2 is purely additive on top of Story 2-1.

## Public surface

`from httpware.middleware import before_request, after_response, on_error` (and re-exported at `httpware.*`).

```python
def before_request(
    f: Callable[[Request], Awaitable[Request]],
) -> Middleware: ...


def after_response(
    f: Callable[[Request, Response], Awaitable[Response]],
) -> Middleware: ...


def on_error(
    f: Callable[[Request, Exception], Awaitable[Response | None]],
) -> Middleware: ...
```

All three are **sync factories** — called once when decorating, returning a `Middleware` instance. The user function is async.

Usage:

```python
from httpware.middleware import before_request, after_response, on_error

@before_request
async def add_trace_id(request: Request) -> Request:
    return request.with_header("x-trace-id", uuid4().hex)

@after_response
async def log_response(request: Request, response: Response) -> Response:
    logger.info("%s %s -> %s", request.method, request.url, response.status)
    return response

@on_error
async def fallback(request: Request, exc: Exception) -> Response | None:
    if isinstance(exc, SomeTransientError):
        return cached_response_for(request)
    return None  # re-raise

client = AsyncClient(middleware=[add_trace_id, log_response, fallback], ...)
```

## Implementation

Append to `src/httpware/middleware/__init__.py` after the existing `Middleware` Protocol:

```python
def before_request(f: Callable[[Request], Awaitable[Request]]) -> Middleware:
    """Wrap an async request transform into a Middleware.

    The decorated function receives the incoming Request and returns a
    (possibly modified) Request, which is then forwarded down the chain.
    """

    class _BeforeRequestMiddleware:
        async def __call__(self, request: Request, next: Next) -> Response:  # noqa: A002
            return await next(await f(request))

        def __repr__(self) -> str:
            return f"<before_request({f.__qualname__})>"

    return _BeforeRequestMiddleware()


def after_response(f: Callable[[Request, Response], Awaitable[Response]]) -> Middleware:
    """Wrap an async response transform into a Middleware.

    The decorated function receives the original Request and the Response
    returned by the chain, and returns a (possibly modified) Response.
    """

    class _AfterResponseMiddleware:
        async def __call__(self, request: Request, next: Next) -> Response:  # noqa: A002
            response = await next(request)
            return await f(request, response)

        def __repr__(self) -> str:
            return f"<after_response({f.__qualname__})>"

    return _AfterResponseMiddleware()


def on_error(f: Callable[[Request, Exception], Awaitable[Response | None]]) -> Middleware:
    """Wrap an async error handler into a Middleware.

    Catches Exception (not BaseException, so asyncio.CancelledError
    propagates). If the handler returns a Response, that Response is
    returned to the caller. If the handler returns None, the original
    exception is re-raised.
    """

    class _OnErrorMiddleware:
        async def __call__(self, request: Request, next: Next) -> Response:  # noqa: A002
            try:
                return await next(request)
            except Exception as exc:
                result = await f(request, exc)
                if result is None:
                    raise
                return result

        def __repr__(self) -> str:
            return f"<on_error({f.__qualname__})>"

    return _OnErrorMiddleware()
```

Update `__all__` in the same file from `["Middleware", "Next"]` to:

```python
__all__ = ["Middleware", "Next", "after_response", "before_request", "on_error"]
```

Update `src/httpware/__init__.py`:
- Change the import line `from httpware.middleware import Middleware, Next` to `from httpware.middleware import Middleware, Next, after_response, before_request, on_error`.
- Insert `"after_response"`, `"before_request"`, `"on_error"` into the `__all__` list. The existing `__all__` is sorted by ASCII order (uppercase < lowercase), so lowercase entries sort to the end of the list — append the three new names after the existing final entry `"UnprocessableEntityError"`, in alphabetic order: `"after_response"`, then `"before_request"`, then `"on_error"`.

Update `docs/engineering.md` §8 line ~142:
- From: `**2-2** Phase shortcut decorators (\`@on_request\`, \`@on_response\`, \`@on_error\`).`
- To: `**2-2** Phase shortcut decorators (\`@before_request\`, \`@after_response\`, \`@on_error\`).`

Update `CHANGELOG.md`. New bullet under `[Unreleased]` / `### Added`:

```markdown
- Phase-shortcut decorators `@before_request`, `@after_response`, `@on_error` for lifecycle hooks without authoring a full `Middleware` class. `@on_error` catches `Exception` only (so `asyncio.CancelledError` propagates); its handler may return a `Response` to recover or `None` to re-raise (Story 2.2).
```

## Notes on the implementation

- **Each decorator returns an instance, not a class.** The decorated name binds to one specific `Middleware` instance ready to drop into a chain. Calling `before_request(f)` a second time produces a distinct instance over the same `f`.
- **`__repr__` uses `f.__qualname__`** so `repr(add_trace_id)` is `<before_request(add_trace_id)>`, not the default `<_BeforeRequestMiddleware object at 0x...>`. Makes a chain print cleanly in logs.
- **Bare `raise` inside `except Exception as exc:`** preserves the original exception type, value, and traceback. No `raise exc` (which would clobber the traceback) or `raise X from exc` (which would chain).
- **`CancelledError` flows past `except Exception:` untouched.** That's the load-bearing property; the `test_on_error_does_not_catch_cancelled_error` test pins it.
- **`f` is captured by closure on the inner class.** Each decorator instance owns one `f`; no shared state, no late-binding hazards.
- **No `# ty: ignore` expected.** If `ty` flags the `Callable[..., Awaitable[...]]` annotations or the class-as-return-Middleware structural check, the fallback is to type-narrow with an explicit cast — but should not be needed.

## Testing

Append to `tests/test_middleware.py`. The file already has the `_OkTransport`, `_make_request`, and `compose` fixtures from Story 2-1 — reuse them.

Approximate test list:

| Test | Verifies |
| --- | --- |
| `test_before_request_transforms_request` | `@before_request` user fn mutates request via `with_header`; downstream chain sees the mutation. |
| `test_after_response_transforms_response` | `@after_response` user fn rebuilds Response with extra header; caller sees the modification. |
| `test_on_error_returns_response_swallows_exception` | Transport raises; `@on_error` returns a synthesized Response; caller gets that Response, no exception. |
| `test_on_error_returns_none_reraises` | Transport raises; `@on_error` returns `None`; original exception bubbles to the caller. |
| `test_on_error_does_not_catch_cancelled_error` | Inner middleware raises `asyncio.CancelledError`; `@on_error` handler is NOT invoked; `CancelledError` propagates. |
| `test_on_error_handler_receives_correct_exception_instance` | Handler's `exc` parameter is the same instance the transport raised (identity check). |
| `test_decorators_satisfy_middleware_protocol` | `isinstance(before_request(f), Middleware)` and same for the other two. |
| `test_decorated_middlewares_compose_in_chain` | Mix `@before_request`, `@after_response`, and a plain class middleware in one `compose()`; ordering correctness. |
| `test_repr_shows_original_function_name` | `repr(before_request(my_func))` contains `"before_request"` and `"my_func"`. |
| `test_decorators_reexported_at_package_root` | `from httpware import before_request, after_response, on_error` works. |

Ten new tests. Total `tests/test_middleware.py` grows from 14 to 24.

**Coverage expectation:** 100% line coverage on the three new decorator factories and their inner classes. The Protocol method body `...` already excluded by the existing pattern.

**No `respx`, no mocking the transport.** Use the existing `_OkTransport` and a small `_FailingTransport` defined locally in the new test block.

## Constraints and invariants

- **No `httpx2` import.** None of the modified files import `httpx2`.
- **No `from __future__ import annotations`.** PEP 604/585 syntax is native.
- **No `print()`, no `logging.basicConfig`.** Decorators are pure transforms; emission belongs in observability (Epic 5).
- **No `# type: ignore`.** Use `# ty: ignore[<rule>]` if a suppression is strictly needed; none expected.
- **`# noqa: A002` on `next` parameter** stays consistent with Story 2-1's protocol body.

## Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| `ty` complains that the inner class doesn't satisfy `Middleware` because its `__call__` is bound on an instance. | The Story 2-1 `Middleware` Protocol takes `self, request, next`. Inner classes use the same signature. If `ty` still rejects on structural grounds, fall back to explicit subclassing of `Middleware` (it's a runtime-checkable Protocol, so `class _BeforeRequestMiddleware(Middleware):` is legal). Decided at implementation time. |
| User decorates a sync function. | The type signature forces async. If ruff/`ty` doesn't catch it at import time, a sync function would return a `Request` directly (not awaitable), and the `await f(request)` inside the decorator would raise `TypeError: object Request can't be used in 'await' expression` at runtime. Acceptable — the error is loud and immediate. |
| `@on_error` handler itself raises. | The handler's exception escapes naturally (no catch-and-suppress in the decorator). Replaces the original exception in the traceback chain by Python's implicit `__context__` link. Documented behavior of `try/except` in Python; no special handling. |
| `BaseExceptionGroup` surprises a user who expected groups to bypass `@on_error`. | The decorator's docstring says "Catches Exception"; `BaseExceptionGroup` is an `Exception`. Users who need to special-case groups (e.g., to re-raise a CancelledError-bearing group) carve it out inside their handler. Not the framework's job to second-guess. |

## Definition of done

- `src/httpware/middleware/__init__.py` exports `before_request`, `after_response`, `on_error` in addition to the existing `Middleware` and `Next`.
- `src/httpware/__init__.py` re-exports the three new names and adds them to `__all__`.
- `docs/engineering.md` §8 line 142 reflects the corrected decorator names.
- `CHANGELOG.md` has a Story 2.2 bullet under `[Unreleased]` / `### Added`.
- `tests/test_middleware.py` contains 10 new tests; all 24 tests pass.
- `just test` shows the increment from baseline; 100% line coverage on the new code.
- `just lint-ci` clean.
- `tests/test_no_httpx2_leakage.py` still passes.
- Story 2-2 lands as a single PR off `main` via the branch `story/2-2-phase-shortcut-decorators`.

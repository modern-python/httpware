---
summary: Shipped 0.8.0 — sync Client + Async* rename
---

# Spec: Sync `Client` + httpx2-aligned `Async*` rename

**Date:** 2026-06-07
**Topic slug:** `sync-client`
**Status:** drafted, awaiting user review
**Target release:** TBD — either `0.8.0` (continued 0.x iteration) or `1.0.0` (graduate alpha). Decide at release time. The work itself is the same.

## Purpose

Add a sync `Client` to `httpware` with full parity to the existing `AsyncClient`: typed response decoding, middleware chain, status-keyed error tree, `Retry` + `Bulkhead` resilience, and `stream()` context manager. Sync users (CLI tools, scripts, Django sync views, Jupyter, codebases with no event loop) get the same primitives without standing up an `asyncio` runtime.

To align with `httpx2`'s naming convention — which httpware visibly wraps — the existing async surface is renamed to use the `Async*` prefix. Sync becomes the unprefixed default; async carries the prefix. This is a breaking rename for every public async middleware class and phase decorator.

`attempt_timeout=` is removed from `Retry` in both worlds. The keyword was an `asyncio.timeout`-based whole-attempt wall-clock bound that has no clean sync equivalent and is already covered, for I/O-bound cases, by `httpx2`'s own per-phase timeout. Users who genuinely need a whole-attempt structured cancellation can compose their own timeout middleware in a few lines — the framework does not need to own this.

## Non-goals

- **No cross-world `Bulkhead` sharing in v1.** `Bulkhead` (sync) owns a `threading.Semaphore`; `AsyncBulkhead` owns an `asyncio.Semaphore`. A single Bulkhead instance cannot be shared between a `Client` and an `AsyncClient` — that would require a third primitive bridging the two scheduling models. Documented as a known limitation; revisit only if a real cross-world cap use case emerges.
- **No automatic API equivalence test harness.** The two worlds are kept in sync by code review and a parallel test suite; we do not build a test that reflects on both classes to assert method-name parity. The asymmetry surface is small (eight HTTP methods plus lifecycle/streaming) and is enforced by direct test files per world.
- **No `aio`/`asyncio` subpackage namespace.** Earlier in design we considered moving async into a parallel `httpware.async_` subpackage with `httpware.sync` for sync. We chose against it: httpx (httpware's parent) uses the flat-namespace + `Async*` prefix convention, and matching that minimizes surprise for users coming from httpx. Symmetric subpackages are uncommon in the Python ecosystem; the closest libraries (httpx, psycopg, openai, anthropic) all keep both worlds at top level.
- **No backward-compatibility shims.** `Middleware`, `Retry`, `Bulkhead`, `Next`, `before_request`, `after_response`, `on_error` get renamed outright. No deprecation aliases, no `__getattr__` redirects. The project is still in 0.x; the user has stated no production users to date.
- **No restoration of `attempt_timeout` in either world.** Existing async code using `Retry(attempt_timeout=…)` must remove the kwarg and rely on `httpx2.Timeout` (or compose a custom timeout middleware).
- **No new shared `Bulkhead` subclass.** The two `Bulkhead` classes live side-by-side, share the name within their respective subpackage, and have no common ancestor.

## Architecture

### Public import surface

```python
# Clients (both at top level — matches httpx convention)
from httpware import Client, AsyncClient

# Middleware — sync default (unprefixed)
from httpware import Middleware, Next, Retry, Bulkhead
from httpware import before_request, after_response, on_error

# Middleware — async (Async* prefix on classes, async_ prefix on decorators)
from httpware import AsyncMiddleware, AsyncNext, AsyncRetry, AsyncBulkhead
from httpware import async_before_request, async_after_response, async_on_error

# Shared (no world distinction)
from httpware import (
    RetryBudget,
    ResponseDecoder,
    StatusError, ClientStatusError, ServerStatusError,
    NotFoundError, BadRequestError, UnauthorizedError, ForbiddenError,
    ConflictError, UnprocessableEntityError, RateLimitedError,
    InternalServerError, ServiceUnavailableError,
    NetworkError, TimeoutError, TransportError,
    BulkheadFullError, RetryBudgetExhaustedError,
    ClientError,
    STATUS_TO_EXCEPTION,
)
```

### Internal directory layout

```text
src/httpware/
├── __init__.py                          # public exports + __all__ (both worlds at top level)
├── client.py                            # Client (sync) + AsyncClient (async) in one file
├── errors.py                            # SHARED — unchanged
├── decoders/                            # SHARED — unchanged
│   ├── __init__.py                      # ResponseDecoder protocol
│   ├── pydantic.py
│   └── msgspec.py
├── _internal/
│   ├── import_checker.py                # SHARED — unchanged
│   ├── observability.py                 # SHARED — _emit_event (already sync)
│   ├── status.py                        # NEW — _raise_on_status_error, _is_streaming_body_async,
│   │                                    #   _is_streaming_body_sync, STREAMING_BODY_MARKER
│   └── exception_mapping.py             # NEW — map_httpx2_exception (pure function used by both terminals)
├── middleware/
│   ├── __init__.py                      # Middleware + AsyncMiddleware, Next + AsyncNext, decorators (sync + async_*)
│   ├── chain.py                         # compose (sync) + compose_async — both in one module
│   └── resilience/
│       ├── __init__.py                  # re-exports both worlds' Retry/Bulkhead + RetryBudget
│       ├── retry.py                     # Retry + AsyncRetry in one file
│       ├── bulkhead.py                  # Bulkhead + AsyncBulkhead in one file
│       ├── budget.py                    # SHARED RetryBudget — adds threading.Lock
│       └── _backoff.py                  # SHARED — unchanged
└── py.typed
```

**Layout principle (mirrored from httpx):** each concept's sync and async classes live in the same file. `client.py` contains both `Client` and `AsyncClient`; `middleware/resilience/retry.py` contains both `Retry` and `AsyncRetry`; etc. The pair-per-file model keeps related code visually adjacent and grep-friendly. Helpers extracted to `_internal/` are shared by both terminals.

### Protocol seams (engineering.md §3 update)

Seam A grows a sync mirror. The terminal call (`httpx2.AsyncClient.send` for async, `httpx2.Client.send` for sync) is the only thing that differs; exception mapping and status-error dispatch are shared via `_internal/exception_mapping.py` and `_internal/status.py`.

The engineering.md "Seam A: AsyncClient ↔ Middleware" entry becomes "Seam A: Client/AsyncClient ↔ Middleware/AsyncMiddleware." Seams B (decoders) and C (optional extras) are unchanged.

## Breaking-change inventory

This PR pair is breaking. Every line below is also a release-note bullet.

| Old (0.7.0) | New |
|---|---|
| `httpware.Middleware` (async) | `httpware.AsyncMiddleware` |
| `httpware.Next` (async type alias) | `httpware.AsyncNext` |
| `httpware.Retry` (async class) | `httpware.AsyncRetry` |
| `httpware.Bulkhead` (async class) | `httpware.AsyncBulkhead` |
| `httpware.before_request` (async decorator) | `httpware.async_before_request` |
| `httpware.after_response` (async decorator) | `httpware.async_after_response` |
| `httpware.on_error` (async decorator) | `httpware.async_on_error` |
| `Retry(attempt_timeout=…)` / `AsyncRetry(attempt_timeout=…)` | **removed** — use `httpx2`'s `timeout=` per request, or `httpx2.Timeout` on the client |

New additions (not breaking, but spelled out for the release notes):

- `httpware.Client` — sync HTTP client.
- `httpware.Middleware`, `httpware.Next`, `httpware.Retry`, `httpware.Bulkhead` — sync middleware surface (these names *previously* meant the async classes; their referents change).
- `httpware.before_request` / `after_response` / `on_error` — sync phase decorators (also a name-referent change from the async versions).
- `RetryBudget` is now thread-safe via an internal `threading.Lock`. The async API is unchanged; the cost is invisible (CPython uncontended-lock overhead is ~50–100 ns, far below HTTP latency).

The sync-vs-async rename is a 1:1 mechanical change. A single regex-and-import rewrite handles ~all existing async users:

```text
^from httpware import (.*)Middleware  →  from httpware import \1AsyncMiddleware
^from httpware import (.*)Retry       →  from httpware import \1AsyncRetry
…etc
```

## PR sequencing and release strategy

**Two PRs, one release.**

- **PR 1: structural rename.** Moves the existing async API to its renamed positions (`Middleware → AsyncMiddleware`, etc.), drops `attempt_timeout`, updates all internal call sites, all tests, and all docs (`docs/middleware.md`, `docs/resilience.md`, `docs/errors.md`, `docs/testing.md`, README). Pure mechanical migration; zero new functionality. Merges to `main` but does **not** trigger a release.
- **PR 2: add sync.** Lands `Client`, sync `Middleware`/`Retry`/`Bulkhead`/`Next`, sync decorators, `_internal/status.py`, `_internal/exception_mapping.py`, the `threading.Lock` on `RetryBudget`, and the sync test suite. Updates docs to show both worlds. Merges to `main`.
- **Then:** cut one release (`0.8.0` or `1.0.0`) bundling both PRs. Users see a single migration in one set of release notes, not two.

Rationale: each PR has one clear theme and is reviewable independently. Users see one cutover. Matches the project's "single structural PR before substantive follow-up work, never bundle" preference applied at the release-tagging boundary.

The version decision (`0.8.0` vs `1.0.0`) is deliberately left open. `1.0.0` is the right semver signal for a feature this substantial *if* we judge the API to be settled after this work. `0.8.0` keeps the freedom to make further breaking changes. Decide at release time, in the release-notes draft.

## Sync middleware semantics

### `Middleware` protocol and `Next` type

```python
# middleware/__init__.py — both protocols coexist
Next:      TypeAlias = Callable[[httpx2.Request], httpx2.Response]
AsyncNext: TypeAlias = Callable[[httpx2.Request], Awaitable[httpx2.Response]]

@runtime_checkable
class Middleware(Protocol):
    """Structural protocol every sync middleware satisfies."""

    def __call__(self, request: httpx2.Request, next: Next) -> httpx2.Response:
        """Process `request`; call `next(request)` to forward, or synthesize a Response."""
        ...

@runtime_checkable
class AsyncMiddleware(Protocol):
    """Structural protocol every async middleware satisfies."""

    async def __call__(self, request: httpx2.Request, next: AsyncNext) -> httpx2.Response:
        ...
```

### `compose`

Two functions, same module:

```python
def compose(middleware: Sequence[Middleware], terminal: Next) -> Next: ...
def compose_async(middleware: Sequence[AsyncMiddleware], terminal: AsyncNext) -> AsyncNext: ...
```

Both implement the same `dispatch = terminal` then `for layer in reversed(middleware): dispatch = _wrap(layer, dispatch)` algorithm. The bodies of `_wrap` differ only by `async` keywords.

### Phase decorators

```python
def before_request(f: Callable[[httpx2.Request], httpx2.Request]) -> Middleware:
    """Wrap a sync request transform into a sync Middleware."""

def after_response(f: Callable[[httpx2.Request, httpx2.Response], httpx2.Response]) -> Middleware: ...

def on_error(f: Callable[[httpx2.Request, Exception], httpx2.Response | None]) -> Middleware: ...

def async_before_request(f: Callable[[httpx2.Request], Awaitable[httpx2.Request]]) -> AsyncMiddleware: ...
def async_after_response(f: Callable[[httpx2.Request, httpx2.Response], Awaitable[httpx2.Response]]) -> AsyncMiddleware: ...
def async_on_error(f: Callable[[httpx2.Request, Exception], Awaitable[httpx2.Response | None]]) -> AsyncMiddleware: ...
```

Same `_BeforeRequestMiddleware`/`_AfterResponseMiddleware`/`_OnErrorMiddleware` inner-class pattern. Same `__repr__` format (`<before_request(qualname)>` / `<async_before_request(qualname)>`).

## Sync `Retry`

```python
class Retry:
    """Sync retry middleware. See module docstring for default policy."""

    def __init__(
        self,
        *,
        max_attempts: int = 3,
        base_delay: float = 0.1,
        max_delay: float = 5.0,
        retry_status_codes: frozenset[int] = DEFAULT_RETRY_STATUS_CODES,
        retry_methods: frozenset[str] = DEFAULT_IDEMPOTENT_METHODS,
        respect_retry_after: bool = True,
        budget: RetryBudget | None = None,
        _sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        ...
        self.budget = budget if budget is not None else RetryBudget()
        self._sleep = _sleep

    def __call__(self, request: httpx2.Request, next: Next) -> httpx2.Response:
        # Algorithm identical to AsyncRetry — deposit per attempt, status/network/timeout
        # categorization, idempotent-method gate, streaming-body refusal via marker,
        # Retry-After parsing, full-jitter backoff, budget gate before each retry,
        # PEP-678 add_note on giving up. Only structural differences from AsyncRetry:
        #   - `next(request)` instead of `await next(request)`
        #   - `self._sleep(delay)` instead of `await self._sleep(delay)`
        #   - no `attempt_timeout` / no `asyncio.timeout` block
        #   - no `builtins.TimeoutError` re-wrap (no asyncio.timeout source)
```

Constants `DEFAULT_RETRY_STATUS_CODES` and `DEFAULT_IDEMPOTENT_METHODS` are module-level in `retry.py` and shared between both classes. The `_LOGGER` is the same `logging.getLogger("httpware.retry")` — both worlds emit to the same channel.

`_parse_retry_after` is shared (it is already a pure function — no async).

## Sync `Bulkhead`

```python
class Bulkhead:
    """Concurrency limiter backed by threading.Semaphore."""

    def __init__(
        self,
        *,
        max_concurrent: int,
        acquire_timeout: float | None = 1.0,
    ) -> None:
        if max_concurrent < 1:
            raise ValueError(_MAX_CONCURRENT_INVALID)
        if acquire_timeout is not None and acquire_timeout < 0:
            raise ValueError(_ACQUIRE_TIMEOUT_INVALID)
        self._max_concurrent = max_concurrent
        self._acquire_timeout = acquire_timeout
        self._sem = threading.Semaphore(max_concurrent)

    def __call__(self, request: httpx2.Request, next: Next) -> httpx2.Response:
        acquired = self._sem.acquire(timeout=self._acquire_timeout)
        if not acquired:
            _emit_event(_LOGGER, "bulkhead.rejected", level=logging.WARNING, ...)
            raise BulkheadFullError(
                max_concurrent=self._max_concurrent,
                acquire_timeout=self._acquire_timeout,
            )
        try:
            return next(request)
        finally:
            self._sem.release()
```

Notes:
- `threading.Semaphore.acquire(timeout=None)` blocks until acquired; `acquire(timeout=0)` is non-blocking (returns False if no slot). Both edge cases match the async `AsyncBulkhead` contract.
- Validation messages reuse the same constants as `AsyncBulkhead` (`_MAX_CONCURRENT_INVALID`, `_ACQUIRE_TIMEOUT_INVALID`).
- A `Bulkhead` instance is **per-world**: passing it to an `AsyncClient` middleware list will fail at composition time (type mismatch — async chain expects `AsyncMiddleware`, this is a `Middleware`). Same in reverse. The docs flag this clearly.

## Shared `RetryBudget` thread safety

The current `RetryBudget` says in its module docstring: *"No locking: asyncio runs coroutines cooperatively on a single thread, so deque mutations between await points are atomic with respect to other coroutines on the same event loop. Cross-thread use is out of scope."*

Sync users routinely share a `Client` (and therefore a `Retry` and its `RetryBudget`) across threads — e.g., a `ThreadPoolExecutor` issuing requests, a multi-worker Django app. Without locking, `_purge` interleaved with `deposit` corrupts the deque.

We wrap mutations in a `threading.Lock`. One class, both worlds:

```python
import threading
from collections import deque

class RetryBudget:
    """Token-bucket retry budget — thread-safe and asyncio-safe.

    Both AsyncRetry and Retry use this class; a single instance is safe to
    share across threads, across coroutines on one event loop, and across
    (sync Client, async AsyncClient) pairs in the same process.
    """

    def __init__(self, *, ttl: float = 10.0, min_retries_per_sec: float = 10.0,
                 percent_can_retry: float = 0.2,
                 _now: Callable[[], float] = time.monotonic) -> None:
        ...
        self._lock = threading.Lock()
        self._deposits: deque[float] = deque()
        self._withdrawn: deque[float] = deque()

    def deposit(self) -> None:
        now = self._now()
        with self._lock:
            self._purge(now)
            self._deposits.append(now)

    def try_withdraw(self) -> bool:
        now = self._now()
        with self._lock:
            self._purge(now)
            floor = int(self._min_retries_per_sec * self._ttl)
            ceiling = int(len(self._deposits) * self._percent_can_retry) + floor
            if len(self._withdrawn) >= ceiling:
                return False
            self._withdrawn.append(now)
            return True

    def _purge(self, now: float) -> None:
        # caller holds self._lock
        ...
```

Cost: CPython uncontended `threading.Lock.acquire()` is ~50–100 ns. A single HTTP request is at least three orders of magnitude slower. The overhead is invisible in any realistic workload.

Module docstring is updated accordingly. Existing async tests continue to pass with no changes. New tests (see Testing) cover concurrent deposit/withdraw from multiple threads.

## Sync `Client`

### Constructor

```python
class Client:
    """Sync HTTP client: thin wrapper around httpx2 with typed decoding and middleware."""

    _httpx2_client: httpx2.Client
    _owns_client: bool
    _decoder: ResponseDecoder
    _user_middleware: tuple[Middleware, ...]
    _dispatch: Next

    def __init__(
        self,
        *,
        base_url: str = "",
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
        cookies: dict[str, str] | None = None,
        timeout: httpx2.Timeout | float | None = None,
        limits: httpx2.Limits | None = None,
        auth: httpx2.Auth | None = None,
        httpx2_client: httpx2.Client | None = None,
        decoder: ResponseDecoder | None = None,
        middleware: Sequence[Middleware] = (),
    ) -> None:
        # Mirror AsyncClient's constructor exactly:
        #   - same conflict check when httpx2_client= is combined with any of
        #     the forwarded kwargs (TypeError with same message format)
        #   - same kwarg-compaction pattern for the not-injected case
        #   - same _owns_client flag
        #   - same _default_pydantic_decoder() lazy factory (shared)
        #   - same compose(middleware, self._terminal) chain freeze
```

The forwarded-kwarg conflict-check message is shared with `AsyncClient` via a module-level constant (`_HTTPX2_CLIENT_CONFLICT_MESSAGE`) that names `httpx2_client` and the list of forwarded kwargs — the message body does not mention "async."

### Terminal and exception mapping

The httpx2-error catch block is extracted to a shared pure function:

```python
# _internal/exception_mapping.py
def map_httpx2_exception(exc: BaseException) -> NetworkError | TimeoutError | TransportError:
    """Map an httpx2 exception to its httpware equivalent. Pure function.

    Used by both Client._terminal and AsyncClient._terminal, and by both stream()
    methods. Clause ordering: TimeoutException → InvalidURL/CookieConflict →
    NetworkError → HTTPError (subclass before parent so the right type wins)."""
    if isinstance(exc, httpx2.TimeoutException):
        return TimeoutError(str(exc))
    if isinstance(exc, (httpx2.InvalidURL, httpx2.CookieConflict)):
        return TransportError(str(exc))
    if isinstance(exc, httpx2.NetworkError):
        return NetworkError(str(exc))
    if isinstance(exc, httpx2.HTTPError):
        return TransportError(str(exc))
    return TransportError(str(exc))  # pragma: no cover — defensive default
```

Both terminals call it inside their own try/except. The async terminal keeps using its existing `_httpx2_exception_mapper` `@asynccontextmanager` (now delegating to `map_httpx2_exception`); the sync terminal uses a sibling `@contextmanager` or inlines the catch.

Sync terminal:

```python
def _terminal(self, request: httpx2.Request) -> httpx2.Response:
    try:
        response = self._httpx2_client.send(request)
    except httpx2.HTTPError as exc:
        raise map_httpx2_exception(exc) from exc
    except RuntimeError as exc:
        if "closed" in str(exc):
            raise TransportError(str(exc)) from exc
        raise
    _raise_on_status_error(response)
    return response
```

`_raise_on_status_error` is moved from `client.py` to `_internal/status.py` and shared. It is already sync.

### HTTP methods

For each of `get`, `post`, `put`, `patch`, `delete`, `head`, `options`, `request`, `send`: produce a sync sibling with the same overload pattern (`response_model=None` → `httpx2.Response`, `response_model=type[T]` → `T`), the same kwarg pass-through, and the same `_request_with_body` collapse. `build_request` delegates to `self._httpx2_client.build_request`.

The two classes do not share a base class — each method exists explicitly on each class. Inheritance would require either (a) inheriting from a shared `_BaseClient` whose methods are abstract and reimplemented on both sides (no actual sharing) or (b) a metaclass that generates the async variant from the sync source (unasync-style). Both add complexity for no gain when the per-method bodies are 1–10 lines each. Explicit duplication wins on readability.

### Streaming body marker

The marker `STREAMING_BODY_MARKER = "httpware.streaming_body"` moves to `_internal/status.py`. Two predicates live alongside it:

```python
# _internal/status.py
STREAMING_BODY_MARKER = "httpware.streaming_body"

def _is_streaming_body_async(value: object) -> bool:
    """True if value is an async-iterable body that can't be safely replayed for retry."""
    if value is None:
        return False
    if isinstance(value, (bytes, bytearray, memoryview, str, dict)):
        return False
    return hasattr(value, "__aiter__")

def _is_streaming_body_sync(value: object) -> bool:
    """True if value is a sync iterable body that can't be safely replayed for retry."""
    if value is None:
        return False
    if isinstance(value, (bytes, bytearray, memoryview, str, dict, list, tuple)):
        return False
    return hasattr(value, "__iter__")
```

Sync's safe-list adds `list` and `tuple` because they are replayable iterables and common in sync code. Async's safe-list does not need them because async-iterable bodies are typically generators, not lists.

`Client._request_with_body` applies `_is_streaming_body_sync` to `content`/`data`/`files` and sets `request.extensions[STREAMING_BODY_MARKER] = True` when any is a generator. Sync `Retry` reads the marker the same way `AsyncRetry` does and refuses to retry (same PEP-678 add_note text, same event emission).

### `Client.stream()`

```python
@contextlib.contextmanager
def stream(
    self,
    method: str,
    url: str,
    *,
    params: typing.Any | None = None,
    headers: typing.Any | None = None,
    cookies: typing.Any | None = None,
    timeout: typing.Any = httpx2.USE_CLIENT_DEFAULT,
    extensions: typing.Any | None = None,
    json: typing.Any | None = None,
    content: typing.Any | None = None,
    data: typing.Any | None = None,
    files: typing.Any | None = None,
) -> Iterator[httpx2.Response]:
    """Stream an HTTP response. Bypasses the middleware chain.

    Yields an httpx2.Response; consume via response.iter_bytes(), iter_text(),
    iter_lines(), or iter_raw(). The body is NOT pre-read for 2xx/3xx (streaming
    preserved); the response is closed when the context exits. On 4xx/5xx the
    body is pre-read so exc.response.content is accessible.

    Bypasses the middleware chain (no Retry, no Bulkhead, no user-installed
    middleware) — matches AsyncClient.stream() behavior.

    Maps httpx2 exceptions raised during the request OR body consumption to
    httpware exceptions via map_httpx2_exception."""
```

Same v1 caveat as `AsyncClient.stream()`: bypasses the middleware chain. Future enhancement (if user feedback warrants) can wire `stream()` through the chain in both worlds simultaneously.

Behavior reference (same shape as `AsyncClient.stream` in the streaming spec, mapped to sync iterators):

| Situation | Behavior |
|-----------|----------|
| 2xx/3xx response | Yields `httpx2.Response`; user consumes via `iter_bytes()` etc. (streaming preserved) |
| 4xx/5xx response | Pre-reads body, raises `StatusError` subclass. `exc.response.content` available |
| Network error during initial request | `NetworkError` from `__enter__` |
| Network error mid-stream | `NetworkError` from the `for` loop in user code |
| Timeout during request or body consumption | `TimeoutError` |
| `InvalidURL` / `CookieConflict` | bare `TransportError` (not `NetworkError`) |
| User exception inside `with` block | propagates unchanged; httpx2 cm cleans up |

### Lifecycle

```python
def __enter__(self) -> typing.Self:
    return self

def __exit__(
    self,
    exc_type: type[BaseException] | None,
    exc: BaseException | None,
    tb: object,
) -> None:
    if self._owns_client and not self._httpx2_client.is_closed:
        self._httpx2_client.close()

def close(self) -> None:
    """Close the underlying httpx2 client if we own it. Idempotent.

    Use this when the client is not managed by `with` (e.g., wired into a
    DI container's lifecycle). Mirrors AsyncClient.aclose()."""
    if self._owns_client and not self._httpx2_client.is_closed:
        self._httpx2_client.close()
```

`close()` is the sync counterpart of `aclose()`. `aclose()` remains on `AsyncClient` (and matches `httpx2.AsyncClient.aclose`); `close()` matches `httpx2.Client.close`. The CLAUDE.md rule "No `a` prefix on async methods (match `httpx2`); `aclose()` is the sole exception" extends naturally: `close()` (sync) and `aclose()` (async) are the documented pair.

### Thread safety summary

A single `Client` instance is safe to share across threads:
- `httpx2.Client.send` is thread-safe (httpx2 uses an internal connection pool with its own locking).
- Middleware-chain dispatch (`self._dispatch(request)`) is a function call — no shared state mutation.
- `RetryBudget` is locked.
- `Bulkhead`'s `threading.Semaphore` is thread-safe by definition.
- `PydanticDecoder` (the lazy default) is thread-safe — its `TypeAdapter` cache uses `functools.lru_cache` which is thread-safe on CPython.
- `MsgspecDecoder` is thread-safe — `msgspec.json.decode` is.

Cross-thread sharing of a single `Client` is the canonical sync use case (web framework worker pool, `ThreadPoolExecutor` over a batch of API calls).

## Testing

Per `planning/engineering.md §6`. Coverage target remains 100% line coverage.

### PR 1 (rename) — existing tests update

All existing test files referencing `Middleware`, `Next`, `Retry`, `Bulkhead`, `before_request`, `after_response`, `on_error` get the `Async`/`async_` prefix update. Tests for `Retry(attempt_timeout=…)` are removed (the kwarg is gone). No behavior changes.

### PR 2 (sync) — new test files

The async test suite has a clear shape (`tests/test_client.py`, `tests/test_retry.py`, `tests/test_bulkhead.py`, `tests/test_client_stream.py`, property tests, etc.). The sync suite mirrors this structure:

- **`tests/test_client_sync.py`** — mirror of `test_client.py` for `Client`. Covers: HTTP method dispatch, response_model decoding (both Pydantic and msgspec extras), middleware-chain composition, exception mapping (TimeoutException → TimeoutError etc.), httpx2-client injection + conflict check, lifecycle (`with`, `close`, idempotent close).
- **`tests/test_retry_sync.py`** — mirror of `test_retry.py` for sync `Retry`. Covers: max-attempts gate, idempotent-method gate, status-code retry, Retry-After parsing (HTTP-date + integer-seconds), full-jitter backoff, budget gate, streaming-body refusal, PEP-678 add_note on giving up. The `_sleep` injection point becomes `time.sleep` and is mocked in tests.
- **`tests/test_bulkhead_sync.py`** — mirror of `test_bulkhead.py`. Covers: concurrent acquire under cap, acquire-timeout rejection, fast-fail at `acquire_timeout=0`, validation errors, release on exception, release on cancellation (KeyboardInterrupt during a held slot).
- **`tests/test_retry_budget_threadsafety.py`** — new file. Uses Hypothesis or a hand-rolled threaded harness to spawn N threads doing `deposit()`/`try_withdraw()` concurrently. Asserts no exception is raised and that the final `_deposits`/`_withdrawn` lengths are consistent with the number of operations issued. Named `test_*_props.py` if implemented via Hypothesis (per engineering.md §6).
- **`tests/test_client_stream_sync.py`** — mirror of `test_client_stream.py`. Covers: successful streaming, 4xx/5xx auto-raise with pre-read body, network error mid-stream, middleware-chain bypass, kwarg forwarding, sync-iterable content kwarg.
- **`tests/test_sync_middleware.py`** — mirror of the existing async middleware tests. Covers: `compose` ordering (first item is outermost), `before_request`/`after_response`/`on_error` decorators, runtime-checkable protocol.

`tests/test_optional_extras_isolation.py` is unchanged — neither pydantic nor msgspec is imported by the sync addition.

`tests/test_threading_with_shared_budget.py` (new, light) — spawns one `Client` and one `AsyncClient` sharing the same `RetryBudget`, hammers both, asserts no corruption. Demonstrates the cross-world sharing claim.

### Documentation tests

`docs/` examples added in PR 2 are scanned by the existing mkdocs build; no separate doctest runner is added.

## Documentation updates

PR 1 (rename):

- `docs/middleware.md` — every code snippet uses `AsyncMiddleware`, `AsyncNext`, `async_before_request`, etc. Section reorgs: none; just renames.
- `docs/resilience.md` — `Retry` → `AsyncRetry`, `Bulkhead` → `AsyncBulkhead`. Remove the `attempt_timeout` row from the parameter table and add a paragraph pointing users at `httpx2.Timeout` for whole-attempt bounds.
- `docs/errors.md` — no rename impact; verify imports.
- `docs/testing.md` — example `MockTransport` usage updated to use `AsyncClient`.
- `README.md` — quickstart imports updated.
- `planning/engineering.md` — §1 mentions the rename and `attempt_timeout` removal; §3 Seam A renamed.

PR 2 (sync):

- `docs/middleware.md` — adds a sibling section showing the sync `Middleware` protocol and sync decorators. The conceptual material (when to write middleware, ordering, request-id worked example) is shared between the two worlds; only the code snippets fork.
- `docs/resilience.md` — adds sibling sections for sync `Retry` and `Bulkhead`. Documents the per-world `Bulkhead` constraint.
- `docs/errors.md` — adds a note that the exception tree is shared.
- `docs/testing.md` — adds a sync example using `httpx2.MockTransport` injected via `httpx2_client=httpx2.Client(transport=...)`.
- `docs/index.md` — quickstart shows both `Client` and `AsyncClient` side by side.
- `README.md` — same.
- `planning/engineering.md` — §1 mentions the sync addition; §5 module layout updated; §3 Seam A entry mentions both worlds.

A new file `planning/releases/0.8.0.md` (or `1.0.0.md`) drafts release notes covering both PRs.

## Open questions deferred to implementation

- **Version number** (`0.8.0` vs `1.0.0`): decide at release time, in the release-notes draft.
- **`compose` vs `compose_async` naming inside `middleware/chain.py`**: alternative is `compose` (sync, unprefixed default) and `acompose` or `compose_async`. Spec uses `compose` + `compose_async`; implementer may swap if convention emerges.
- **Whether to extract the per-method overload pattern into a code-gen helper**: probably not — the explicit overload signatures are the public contract surface and read better verbatim.
- **Whether `_internal/exception_mapping.py` should be exposed as a public utility**: no for v1. Keep private; revisit if user feedback shows demand.
- **Decoder `default_decoder` behaviour for sync**: `Client._default_decoder` reuses the same `_default_pydantic_decoder()` factory as `AsyncClient` (it does not need to be async). Confirm during implementation.

## References

- `planning/engineering.md` §1 (project intent), §3 (protocol seams), §5 (module layout), §8 (roadmap)
- `planning/archive/specs/2026-06-05-streaming-design.md` — async `stream()` design; the sync `stream()` mirrors this
- `planning/archive/specs/2026-06-05-retry-and-retry-budget-design.md` — async `Retry` + `RetryBudget` design; the sync versions mirror this (minus `attempt_timeout`)
- `planning/archive/specs/2026-06-05-bulkhead-design.md` — async `Bulkhead` design; sync `Bulkhead` mirrors this with `threading.Semaphore`
- `httpx` documentation — naming-convention reference (`Client` + `AsyncClient` at top level)
- `websockets` documentation — ecosystem precedent for async-primary + sync-secondary (the inverse of what we chose, considered and rejected)

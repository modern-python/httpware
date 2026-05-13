---
title: "Product Brief Distillate: httpware"
type: llm-distillate
source: "product-brief-httpware.md"
created: "2026-05-11"
updated: "2026-05-12"
purpose: "Token-efficient context for downstream PRD creation"
---

# httpware — Detail Pack

Dense reference for downstream PRD / architecture work. Each bullet is self-contained.

## Strategic context

### httpx → httpx2 transition (as of 2026-05-12)

**Resolved on 2026-05-11: Pydantic Services forked `encode/httpx` to `pydantic/httpx2`, restored issues/discussions, released v2.0.0b1 the same day.**

Historical context (the conditions that led to the fork):

- `encode/httpx` 0.28.1 shipped 2024-12-06 — 17 months without a release.
- `encode/httpx` issue tracker was disabled (`has_issues: false` via GitHub API).
- Last commit to `encode/httpx` `master`: 2026-02-23. Recent commits cosmetic (typos, docs, dependabot, third-party-list updates). One substantive change in 12 months: "Drop Python 3.8 support" (2025-06).
- **Discussion #3784 (2026-02-27)**, lead maintainer `lovelydinosaur`: *"I've closed off access to issues and discussions. I don't want to continue allowing an online environment with such an absurdly skewed gender representation. I find it intensely unwelcoming, and it's not reflective of the type of working environments I value."* — verbatim.
- Maintained fork `httpxyz` appeared 2026-03-25 from one frustrated user; never gained traction.
- **OpenAI and Anthropic SDKs pinned `httpx<1.0`** during the stalled period and have not migrated.

Current state of `pydantic/httpx2` (verified 2026-05-12):

- Repo created **2026-05-11**, owned by `pydantic` org.
- License: BSD-3-Clause (inherited from httpx).
- Issues **enabled**; 165 open at fork time.
- Latest release: **v2.0.0 GA, 2026-05-12** (initial v2.0.0b1 was published the same day as the fork, 2026-05-11; GA followed the next day).
- README: *"Pydantic Services is picking up stewardship under the HTTPX2 name so that users have a reliably maintained path forward — including timely security updates for a library that sits in the critical path of so many production systems."*
- Lead maintainer post-fork: **Marcelo Trylesinski (Kludex)** — FastAPI core team member.
- Original contributors (lovelydinosaur, florimondmanca, karpetrosyan, sethmlarson, cdeler, etc.) carried over via fork history.
- Same API as httpx 0.28 — drop-in for most consumers; httpx2 is httpx with stewardship, not a redesign.
- **Implication for httpware:** the "strategic risk" framing in the brief reflected the pre-fork situation. Post-fork, the project is driven by architectural debt in `base-client` and the gap in Python's resilience ecosystem, not by httpx maintenance concerns.

### niquests evaluation

- Repo: `jawah/niquests`. ~2,313 stars. Last push 2026-05-10. v3.18.8 released 2026-05-10.
- Maintainer: **Ahmed R. TAHRI ("Ousret")** dominant. Other recent contributors (Bartosz Magiera, Julien Brayere, Tatsh) are drive-by. **Bus factor ~1.**
- HTTP/1.1 + HTTP/2 + HTTP/3 + WebSocket + SSE by default. No extras required for HTTP/2.
- API is requests-compatible (sync-first); async via `AsyncSession` with `aget`/`apost`.
- Multiplexing is opt-in: `Session(multiplexed=True)`.
- Niquests' own benchmark: 1000 GETs to httpbingo.org — niquests 0.551s, aiohttp 1.351s, httpx 2.087s. Self-published, directional only.
- Mocking story: **`niquests-mock` is 3 stars**, single tiny project (`0x12th/niquests-mock`). Provides a `respx_mock` API alias but mature ecosystem does not exist. respx does NOT work with niquests.
- **Conclusion**: technically strong, fails the "wide community" bar.

### Other candidates evaluated and rejected

- **aiosonic**: solo (Johanderson Mogollon), no mocking ecosystem, sub-1k stars. Fail.
- **httpcore (direct)**: same encode-org cadence problem, too low-level, no first-class mocking. Fail.
- **urllib3 v2 + anyio**: not actually async at protocol level — would require threadpool. Fail constraint.
- **tornado.httpclient**: tornado-flavored, no respx equivalent, heavy dependency. Fail.
- **httpxyz**: 1 maintainer, brand new. Fail.

### Trigger and motivation (from maintainer)

- **General strategic concern**, not a specific CVE or hard deadline.
- The lovelydinosaur situation reinforces but did not trigger the work.
- Audience for the brief: maintainer + several teams using `base-client` in work projects (community-of-python is a real internal-multi-team library).

## Current `base-client` surface (what's leaking and what hurts)

- **Repo**: `community-of-python/base-client`. ~702 LOC total, 13 Python files.
- **Public surface that leaks httpx types** (file: `base_client/base_client.py`):
  - `BaseClient.client: httpx.AsyncClient` — public dataclass field. Examples reach into it directly.
  - `BaseClient.send(request: httpx.Request) -> httpx.Response`
  - `BaseClient.prepare_request(...) -> httpx.Request`
  - `BaseClient.validate_response(response: httpx.Response) -> None`
- **Private httpx imports** (CRITICAL coupling):
  - `from httpx._client import USE_CLIENT_DEFAULT, UseClientDefault` (line 7)
  - `from httpx._types import CookieTypes, HeaderTypes, QueryParamTypes, RequestContent, RequestData, RequestExtensions, RequestFiles, TimeoutTypes` (lines 8–17)
- **Error classes hold `httpx.Response`** (`base_client/errors.py`): `HttpStatusError`, `HttpClientError`, `HttpServerError` — all carry `response: httpx.Response` field.
- **`response_to_model`** (`base_client/response.py`): loose utility, takes `httpx.Response`, calls `response.json()`, builds `pydantic.TypeAdapter` **per call** (performance footgun documented by pydantic).
- **Tests assert against 19 specific httpx exception types** via `respx.mock(side_effect=...)`: RequestError, TransportError, ConnectTimeout, ReadTimeout, WriteTimeout, PoolTimeout, NetworkError, ConnectError, ReadError, WriteError, CloseError, ProtocolError, LocalProtocolError, RemoteProtocolError, ProxyError, UnsupportedProtocol, DecodingError, TooManyRedirects, HTTPError, plus a few more.
- **Examples use** `httpx.Timeout(1)` (1-second total timeout — too aggressive for any real API), `httpx.codes.is_server_error()`, `is_client_error()`, `is_success()`.
- **Dependencies**: `httpx` (no version pin), `pydantic`, `multidict`, `circuit-breaker-box`. Dev: `respx`, `pytest`, `pytest-asyncio`, `mypy`, `ruff`.
- **Tooling**: mypy strict, ruff (select=ALL, line-length=120), pytest with `asyncio_mode="auto"`. Python 3.10+ (CI tests 3.10–3.13).

## `circuit-breaker-box` bug inventory (verified by source read)

For the future-iteration circuit-breaker design — these are the failure modes to avoid:

| # | Issue | Location | Severity |
|---|---|---|---|
| 1 | No Half-Open state — recovery is TTL-only; all in-flight requests stampede on TTL expiry | `circuit_breaker_base.py:6-18`, `circuit_breaker_in_memory.py:18-21` | Critical |
| 2 | First failure not counted in `Retrier` — only attempts ≥2 increment the counter | `retrier.py:50-51` (`if attempt.retry_state.attempt_number > 1`) | Critical |
| 3 | Redis `EXPIRE` called on every increment — refreshes TTL on each failure so breaker never auto-recovers under sustained load | `circuit_breaker_redis.py:42-43` | Critical |
| 4 | Non-atomic increment in async memory backend — read-then-write straddles `await` | `circuit_breaker_in_memory.py:23-29` | High |
| 5 | Off-by-one in availability check — `failures_count <= max_failure_count` allows one more failure than configured | `circuit_breaker_in_memory.py:33`, `circuit_breaker_redis.py:57` | Medium |
| 6 | No response-based failure detection — only exceptions count; 5xx fast-returns invisible | `retrier.py` (no result hook) | High |
| 7 | No slow-call detection — 30s successful response doesn't trip | architectural | Medium |
| 8 | Redis backend doesn't fail open — Redis outage propagates `RedisConnectionError` to callers | `circuit_breaker_redis.py:28-67` | High |
| 9 | TTL refresh in cachetools in-memory path — same root cause as #3 | `circuit_breaker_in_memory.py:25, 28` | High |
| 10 | No state-transition hooks / events / counters | `circuit_breaker_base.py` | Medium |

- Library is 2-state (Closed/Open), not 3-state. Implements a per-host failure-counting TTL ban, not a faithful circuit breaker.
- Repo maintainer profile: NikitaKozlovtcev (14 commits) + lesnik512 (5). Last release ~9 months stale.

## API design patterns to adopt (from cross-language survey)

### Stainless skeleton (openai-python, anthropic-sdk-python)

- **Private `_client`**, never exposed. Lazy default `httpx.AsyncClient`; user can inject via `http_client=` kwarg.
- **Resource pattern**: each endpoint group is a class holding a back-pointer to the base client. Endpoint methods call `self._post("/path", body=..., options=..., cast_to=Model)`.
- **`cast_to`/`response_model` kwarg** is the typed-response mechanism. Single call site, `TypeVar` carries the type through.
- **`with_options(**overrides) -> Self`** returns a new client sharing the pool but with new defaults. Steal verbatim.
- **`NotGiven` sentinel** (`not_given`) distinct from `None`, because JSON `null` vs "omit the field" must be representable.
- **`.with_raw_response.create(...)`** returns `APIResponse[T]` (lets users see headers/status; `.parse()` to get the model).
- **`.with_streaming_response.create(...)`** returns a context manager that never buffers the body.
- **`extra_headers=`, `extra_query=`, `extra_body=`** escape hatches on every endpoint method.
- **Two parallel class hierarchies** (`SyncAPIClient` / `AsyncAPIClient`). No `asyncify` magic; literally separate code paths. v1.0 of httpware ships async-only — defer sync hierarchy entirely.
- **Stainless deliberately rejects middleware** — retries are hand-rolled in the request loop. httpware breaks with this — middleware is the framework's extension axis.

### Exception hierarchy (single tier, plain fields)

```
ClientError (base, never raised)
├─ TransportError       (network/DNS/TLS)
├─ TimeoutError
└─ StatusError                  (any non-2xx)
   ├─ ClientStatusError (4xx) ─ BadRequest, Unauthorized, Forbidden, NotFound,
   │                            Conflict, UnprocessableEntity, RateLimited
   └─ ServerStatusError (5xx) ─ InternalServerError, ServiceUnavailable
```

- Each exception carries **plain fields**: `status: int`, `body: bytes`, `headers: Mapping[str, str]`, `json: Any | None`, `request_method: str`, `request_url: str`.
- **No `httpx2.Response` attached.** Tests assert on `error.status` and `error.json["code"]`, never on transport exception types.
- Mapping from transport exceptions happens at the seam (in `Httpx2Transport`).

### Middleware (onion model + phase shortcuts)

Canonical interface:

```python
class Middleware(Protocol):
    async def __call__(self, req: Request, next: Next) -> Response: ...
```

- Phase shortcut helpers wrap user functions into a `Middleware`: `@before_request`, `@after_response`, `@on_error`.
- Composition order (outer → inner): `Observability → RetryBudget → Retry → [extension slot] → Bulkhead → Timeout → Transport`.
- Rationale for ordering:
  - Observability outermost: must see rejections too.
  - RetryBudget outside Retry: budget gates whether retry happens at all.
  - Retry outside [extension slot]: each retry attempt is a fresh check at the extension point (where a CB would sit).
  - Bulkhead inside the extension slot: tripped CB rejects without touching the semaphore.
  - Timeout innermost: per-attempt deadline.
- **Cross-language inspiration**: OkHttp `Interceptor.intercept(Chain)`, reqwest-middleware (Rust), ky hooks (TS — phases: `beforeRequest`, `beforeRetry`, `afterResponse`, `beforeError`).

### Auth flow

```python
client = Client(auth="static-key")                          # string
client = Client(auth=lambda: get_fresh_token())             # callable for short-lived tokens
client = Client(auth=MyOAuthMiddleware(...))                # full middleware
```

- Type the kwarg as `str | Callable[[], str] | Middleware`. Coerce internally.

### Streaming

```python
async with client.stream("GET", "/events") as resp:
    async for line in resp.iter_lines():
        process(line)
```

- Mirror httpx2 public API exactly (muscle memory transfers; same as httpx), but `resp` type is `httpware.Response`, not `httpx2.Response`.
- Context manager guarantees pool return on exit, even if user code raises.

## Anti-patterns (do not do these)

1. Returning the underlying transport response (`hvac` returns `requests.Response` — every caller writes ad-hoc parsing).
2. Importing from private modules (current `base-client` does this; brittle to minor versions).
3. Exposing the HTTP client as a public field (`BaseClient.client`).
4. A single God exception with N subclasses tied to httpx exception types.
5. Two-step `prepare_request` → `send` as the public API.
6. Decorator-based endpoint definitions (Refit-in-Python attempts like `uplink`, `apiwrappers` — mypy can't follow them).
7. `response_to_model` as a loose utility outside the response object.
8. Sync facade via `nest_asyncio` / `asgiref.async_to_sync`.
9. Middleware that mutates a shared dict (Flask `before_request` idiom). Request objects must be immutable — each middleware returns a new one.
10. Auto-deserializing every response without opt-out. `response_model=` is explicit; default returns raw wrapped response.

## Performance specifics

### Pool / timeout / limits defaults

- **`Limits` defaults**: `max_connections=100, max_keepalive_connections=20, keepalive_expiry=5.0` (matches httpx/httpx2 defaults; document that high-concurrency services need 1000/100 like OpenAI/Anthropic).
- **`Timeout` defaults**: `Timeout(connect=5.0, read=30.0, write=30.0, pool=5.0)` — split-value defaults. **Never `Timeout(1)`** (current base-client examples are dangerous).
- **OpenAI/Anthropic SDK reference**: `Limits(max_connections=1000, max_keepalive_connections=100)`, `Timeout(timeout=600, connect=5.0)` — 10-min read for LLM streams.
- Critical rule: if users wrap calls in `asyncio.Semaphore(N)`, then `N ≤ max_connections` or they get `PoolTimeout` instead of clean queueing.

### Response validation

- **Cache `TypeAdapter`** per `response_model` (module-level `functools.lru_cache`). Pydantic docs explicit: "Creating a TypeAdapter for a given type comes with some non-trivial overhead... it is recommended to create a TypeAdapter for a given type just once and reuse it."
- **Use `validate_json(response.content)`** instead of `validate_python(response.json())` — one parse pass instead of two. ~2× faster end-to-end.
- **Numbers**:
  - `orjson` decode: ~3-6× faster than stdlib `json`.
  - `msgspec.json.decode(buf, type=MyStruct)`: ~3-4× faster than orjson alone (parse+validate single pass).
  - `msgspec` vs `pydantic v2` decode-and-validate: msgspec ~12× faster.
  - Pydantic v1 → msgspec: ~85× faster.
- For typical 5KB payloads, parsing is sub-ms and dominated by network. For high-throughput (>1k req/s) or large responses (>100KB), JSON parsing becomes a real CPU bottleneck.

### Connection lifecycle

- **Single shared client per event loop**, created at startup, closed at shutdown. Per-request clients re-do TCP+TLS handshakes (1-3 RTT) and discard keepalive sockets.
- **Connection pools are bound to an event loop** — not shareable across loops. `@lru_cache`'d async clients break under `asyncio.run()` patterns.
- `BaseClient.from_url(base_url, timeout=..., limits=..., **kwargs)` factory helper builds sensible default `AsyncClient`.
- Add `__aenter__`/`__aexit__` that delegate to underlying client (ergonomics, no semantic change).

### Async HTTP footguns

- **Blocking DNS**: both httpx and niquests use `asyncio.getaddrinfo` (ThreadPoolExecutor wrapper around blocking `getaddrinfo`). Saturated default executor (32 threads) → DNS stalls. CPython issue #112169. Niquests has configurable resolver (DoH/DoT/DoQ).
- **SSL GIL contention**: CPython `SSLSocket.read` does GIL round-trip per 16KB TLS record (issue 37355). Bites above ~10k req/s. Mitigations: HTTP/2 (fewer handshakes), persistent connections, uvloop.
- **`asyncio.gather` exceeding pool size**: 500 requests at 100-connection pool → `PoolTimeout`. Expose `client.gather(requests, max_concurrency=N)` using `TaskGroup` on 3.11+.
- **`asyncio.CancelledError`** should NOT count as a failure (caller-initiated abort, not upstream problem). Excluded from breaker failure classification.
- **Don't touch `.text`/`.content`/`.json()` in framework hot path** — current `base-client` does this in DEBUG log path, breaks streaming and leaks body to logs. Bug to avoid.

### HTTP/2 reality check

- httpx: HTTP/2 opt-in extra (`pip install httpx[http2]` + `AsyncClient(http2=True)`). h2+httpcore overhead is real; httpx HTTP/2 sometimes slower than HTTP/1.1 for small payloads.
- niquests: HTTP/2 + HTTP/3 by default, multiplexing opt-in via `Session(multiplexed=True)`.
- Wins are 30-50% for many-small-requests-same-host workloads with ≥10ms RTT. Don't enable by default; expose as opt-in.
- Open question: no public benchmark found for "wrapped httpx with HTTP/2 vs HTTP/1.1 on small JSON workload at 50-200 concurrency."

## Circuit-breaker reference design (deferred to post-v1.0)

For when the in-house breaker eventually ships:

- **States**: 3-state (Closed, Open, Half-Open) + admin `Disabled` flag.
- **Trip condition**: count-based sliding window (ring buffer of last N call outcomes), `failure_rate_threshold` over a `minimum_calls` floor (e.g., 0.5 over 20 calls in a window of 100). Optional `slow_call_duration_threshold` promotes slow successes to "failures."
- **Recovery**: half-open admits up to `half_open_max_calls` (default 5). Close when all N succeed; reopen on first failure. **`break_duration` with full jitter applied automatically** (`uniform(0.5, 1.5) * break_duration`) — cheapest correctness win, almost no Python lib defaults this.
- **Granularity**: per-host by default (matches current `base-client`), accept `key: Callable[[Request], str]` for per-route.
- **Failure classification**: 5xx + connection/timeout/network errors = failure. 4xx = success (configurable). `asyncio.CancelledError` = excluded. User-supplied `failure_predicate` overrides.
- **Atomicity**: `asyncio.Lock` per-key, lazily created. Read-modify-write of counts always inside the lock, never across `await`.
- **Backends**: in-memory default; pluggable `Storage` protocol; Redis storage **fails open** on backend errors (current circuit-breaker-box doesn't — fail-closed bug).
- **Hooks**: `on_state_change(key, from_state, to_state)`, `on_call_rejected(key)`, `on_call_recorded(key, outcome)`.
- **Estimated size**: ~400 LOC (likely 600-800 realistic with proper tests).
- **Composition with retry**: breaker check happens **per-attempt inside retry loop**, not around the whole loop. Resilience4j/Polly ordering.

## Retry / retry-budget design (in v1.0)

### Retry

- Default: full-jitter exponential backoff, base 0.5s, max 8s, max attempts 3 (matches OpenAI/Anthropic SDK defaults — those use `delay * jitter, jitter ∈ [0.75, 1.25]`).
- **Only retry idempotent methods by default** (GET/HEAD/PUT/DELETE). POST requires explicit opt-in (idempotency-key pattern, see Stripe).
- Classifier: connection errors (always retry), 429 (retry with `Retry-After`/`retry-after-ms` honored), 5xx (retry except 501), 4xx (never retry).
- Use `tenacity.AsyncRetrying` rather than `Retrying` in async paths.
- Anti-pattern: `tenacity.wait_fixed(1)` — fixed waits cause synchronized thundering-herd retry storms.

### Retry budget (Finagle pattern — the differentiator)

- Token-bucket admission control. Default: `min_per_sec=10, ratio=0.2, ttl=10s` (Finagle defaults).
- Caps total retries-per-second across the whole client. A flapping endpoint can't trigger retries from every concurrent call.
- **Single biggest production-readiness gap in Python today.** No Python lib ships this.

## Test mocking design (`RecordedTransport`)

### Primary path

```python
import pytest
from httpware import AsyncClient, RecordedTransport, Response

@pytest.fixture
def fake_transport() -> RecordedTransport:
    return RecordedTransport({
        ("GET", "/users/1"): Response(status=200, json={"id": 1, "name": "ada"}),
        ("GET", "/users/2"): Response(status=404, json={"detail": "not found"}),
    })

async def test_get_user_ok(fake_transport):
    client = AsyncClient(base_url="https://x", transport=fake_transport)
    user = await client.get("/users/1", response_model=User)
    assert user.name == "ada"
    assert fake_transport.calls[0].url.path == "/users/1"
```

### Layers of mocking support (in order of preference)

1. **`RecordedTransport`** — primary. Zero httpx knowledge in tests.
2. **Middleware injection** — mount a "respond from fixture" middleware that short-circuits before reaching the network.
3. **respx pass-through** — default transport is httpx-backed, respx still works. Documented but not encouraged.

### Tests in v1.0 must cover (replacing current `base-client` test patterns)

- Mock 200 + JSON body
- Mock 4xx (assert specific exception, e.g., `NotFoundError`)
- Mock 5xx (retry behavior, RetryBudget exhaustion)
- Mock connection error (TransportError raised)
- Mock timeout (TimeoutError raised)
- Streaming response (chunk iteration, early close)
- Pool exhaustion (Bulkhead behavior)

## Concrete API sketch

### Construction

```python
from httpware import AsyncClient

client = AsyncClient(
    base_url="https://api.example.com",
    default_headers={"User-Agent": "myapp/1.0"},
    timeout=10.0,                                # or Timeout(connect=5, read=30, ...)
    retries=3,
    auth="bearer-token-here",                    # or callable, or Middleware
    middleware=[TracingMiddleware()],
    response_decoder=PydanticDecoder(),          # or MsgspecDecoder, or custom
)
```

### Simple GET

```python
resp = await client.get("/healthz")
assert resp.status == 200
print(resp.text)
```

### Typed response (primary path)

```python
from pydantic import BaseModel

class User(BaseModel):
    id: int
    name: str

user = await client.get("/users/1", response_model=User)
users = await client.get("/users", response_model=list[User])
```

### Error handling

```python
from httpware import RateLimitedError, ServerStatusError

try:
    user = await client.get("/users/999", response_model=User)
except RateLimitedError as e:
    retry_after = float(e.headers.get("retry-after", "1"))
except ServerStatusError as e:
    log.warning("upstream %s: %s", e.status, e.json)
    raise
```

### Custom middleware (onion)

```python
from httpware import Middleware, Next, Request, Response

class SignRequestMiddleware:
    def __init__(self, secret: str) -> None:
        self._secret = secret

    async def __call__(self, req: Request, next: Next) -> Response:
        req = req.with_header("X-Signature", hmac_sign(req.body, self._secret))
        return await next(req)
```

### Phase-shortcut middleware

```python
from httpware import before_request, after_response

@before_request
async def add_correlation_id(req: Request) -> Request:
    return req.with_header("X-Correlation-ID", contextvars_get_id())

@after_response
async def log_slow_responses(req: Request, resp: Response) -> Response:
    if resp.elapsed > 1.0:
        log.warning("slow request %s %s: %.2fs", req.method, req.url, resp.elapsed)
    return resp
```

### Sub-client (ky.extend-style)

```python
users_api = client.with_options(
    base_url=str(client.base_url) + "/users",
    default_headers={"X-Service": "users"},
)
```

### Backend swap (the design payoff)

```python
from httpware.transports.niquests import NiquestsTransport
client = AsyncClient(base_url="...", transport=NiquestsTransport())
```

### Streaming

```python
async with client.stream("GET", "/events") as resp:
    assert resp.status == 200
    async for line in resp.iter_lines():
        process(line)
```

## Scope signals (from user, throughout conversation)

- **Decoupled flavor**: (a) single backend, swappable internally. NOT (b) pluggable backends à la SQLAlchemy dialects.
- **Initial backend**: `httpx2 >=2.0.0, <3.0` (Pydantic Services stewardship line; same API as httpx 0.28, drop-in). Updated 2026-05-13 after httpx2 v2.0.0 GA shipped (2026-05-12); original decision was "stay on httpx 0.28," now obsolete. No swap to niquests in v1.0.
- **Trigger**: general strategic concern.
- **Audience**: maintainer + several teams in `modern-python` / `community-of-python`. Library is public on PyPI.
- **base-client fate**: deprecated. New library supersedes it; consumers migrate when they want; no automated migration shim.
- **New library scope**: same use case as base-client (HTTP client framework for service clients). Broader scope is an open question, not promised.
- **Name**: `httpware`. Org: `github.com/modern-python`.
- **Strong architecture/redesign**: in scope. Public API redesign is wanted, not just internal cleanup.
- **Circuit breaker**: explicitly dropped from v1.0, but design must accommodate plug-in via middleware extension slot.
- **Validator pluggability**: explicitly requested. `ResponseDecoder` protocol.

## Rejected approaches

- **Stay on httpx, abstract it out, defer the swap.** Considered as "Framing 1 — Decouple first, decide later." Initially adopted, then upgraded to greenfield rebuild.
- **Migrate to niquests immediately.** Rejected: bus-factor-1, weak mocking ecosystem, fails community constraint.
- **Pluggable backends (multiple transports shipped simultaneously, user-selected).** Rejected: ~2-3× the work, harder to test, not needed for the use case. Kept as single-backend-swappable-internally.
- **Continue maintaining `base-client` and fix in place.** Rejected: too much breaking-change surface (httpx leakage everywhere, including private-API usage), redesign is wanted independently.
- **Fork httpx into a community-maintained variant.** Considered as a "strategic alternative" during the brief phase but not chosen. **Update 2026-05-12:** Pydantic Services actually did this — released `pydantic/httpx2` on 2026-05-11. We're now adopting it as the default backend rather than forking ourselves.
- **Contribute upstream to niquests to grow its maintainer pool.** Considered by review; not chosen. Brief doesn't address.
- **Depend on `purgatory` or `pybreaker` for the circuit breaker in v1.0.** Considered. Decision: drop CB entirely from v1.0, design middleware extension point so a future plug-in (likely `purgatory`-wrapping) works cleanly.
- **Add sustainability/governance section (named maintainers, hours, succession plan).** Deferred ("too early for this").
- **Sync API in v1.0.** Excluded. Decision point not "permanent vs. post-v1.0" — leaning post-v1.0 if ever.
- **Decorator-based endpoint definitions (Refit-style).** Rejected: Python codegen is fragile, IDE autocomplete breaks.
- **`asyncify`/`asgiref.async_to_sync` style sync facade over async.** Rejected: threading bugs, breaks signal handling, kills uvloop.

## Open questions / deferred decisions

- **Sustainability story** — explicit named maintainers, hours/week, succession policy. Deferred per maintainer ("too early"). Worth revisiting before v1.0 cut.
- **Governance** — license (probably MIT or Apache-2.0), CONTRIBUTING.md, CLA/DCO, release-cadence commitment, CVE disclosure channel. Not specified in brief.
- **Migration cost quantification** — how many `base-client` consumers actually exist, how many lines of consumer code touch httpx types. Currently described qualitatively. Worth a `grep` across known consumers.
- **Scope: same as base-client vs. broader.** Maintainer flagged as open. Specifically: should the new library address SSE / WebSocket use cases? Auth-flow library territory (OAuth refresh, SigV4 signing)?
- **HTTP/2 default decision.** No public benchmark for "wrapped httpx HTTP/2 vs HTTP/1.1 on small JSON, 50-200 concurrency." Default off; document the toggle. Worth measuring on real workload before flipping.
- **`circuit-breaker-box` deprecation.** With base-client deprecated, what's the path for the breaker lib itself? Archive? Hand off? Fix the bugs? Not addressed in brief.
- **OpenAPI codegen story.** Explicitly out of v1.0. Open question whether `httpware` ships a generator target later (would be a powerful distribution vector — opportunity reviewer flagged).
- **FastAPI/Litestar partnership.** Mentioned by opportunity reviewer as the single largest adoption lever. Not in brief. Worth raising in PRD.
- **OpenTelemetry semantic-convention specifics.** Brief commits to OTel. PRD should pin specific spans/attributes/metric names (`http.client.request.duration`, etc.).
- **Public benchmark suite.** Skeptic reviewer suggested publishing latency overhead, throughput, memory vs raw httpx2 + tenacity, on every release. Cheap insurance against "this framework is slow" accusations. Not in brief.
- **Reversibility / sunset plan.** What happens at 6 months if external adoption misses the ≥3-projects target. Not stated.

## References (for downstream verification)

- httpx state: `gh api repos/encode/httpx`, `gh api repos/encode/httpx/commits`, `gh api repos/encode/httpx/discussions/3784`
- niquests state: `gh api repos/jawah/niquests`
- circuit-breaker-box source: `github.com/community-of-python/circuit-breaker-box` (commit `e1cb058`)
- Cross-language design references: openai/openai-python (`src/openai/_base_client.py`), anthropics/anthropic-sdk-python, stripe/stripe-python (`stripe/_http_client.py`), encode/httpx (`httpx/_client.py`, `httpx/_transports/`), sindresorhus/ky, mardiros/purgatory, danielfm/pybreaker, sony/gobreaker, Polly (.NET), resilience4j (JVM)
- Performance refs: Pydantic Performance docs (TypeAdapter caching), msgspec benchmarks (jcristharif.com/msgspec/benchmarks.html), AWS Builders Library (jitter/backoff), CPython issues #112169 (DNS) and #37355 (SSL GIL)
- Finagle retry budget: `github.com/twitter/finagle/blob/develop/finagle-core/src/main/scala/com/twitter/finagle/service/RetryBudget.scala`

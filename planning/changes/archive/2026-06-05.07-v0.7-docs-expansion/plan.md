---
status: shipped
date: 2026-06-05
slug: v0.7-docs-expansion
spec: v0.7-docs-expansion
pr: 28
---

# v0.7 docs expansion (Resilience + Errors + Testing + OTel wiring) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stack 9 docs-only commits onto the open PR #28 branch so 0.7.0 ships with a complete first-cut user-docs surface — `docs/resilience.md`, `docs/errors.md`, `docs/testing.md`, and an "OpenTelemetry wiring" section appended to `docs/middleware.md` — plus the nav, index, engineering, release-notes, and PR-description touchups that tie everything together.

**Architecture:** Docs-only PR. Three new markdown pages (~380 lines combined), one ~30-line append to an existing page, four small textual edits to existing files (`mkdocs.yml` nav, `docs/index.md` Where-to-go-next, `planning/engineering.md` §8, `planning/releases/0.7.0.md` rewrite), one `gh pr edit` to update PR #28. Zero source code changes. Verification: `mkdocs build --strict` + link scan + the existing test/lint suites as no-op confirmation.

**Tech Stack:** Markdown, mkdocs-material (strict build), `gh` CLI. No source code.

**Target branch:** `feat/v0.7-middleware-docs` — the branch with PR #28 open. **Do NOT create a new branch.** The new commits stack on top of the existing 6 plus the two spec commits.

**Source spec:** [`planning/specs/2026-06-05-v0.7-docs-expansion-design.md`](../specs/2026-06-05-v0.7-docs-expansion-design.md). Read its "Deliverable" section for the page-by-page rationale (why this nav order, why OTel is a section not a page, why the Request-ID example sits where it does).

---

## File structure

**New files:**
- `docs/resilience.md` — Retry / RetryBudget / Bulkhead reference (~180 lines)
- `docs/errors.md` — exception tree, status-mapping, catching strategies (~120 lines)
- `docs/testing.md` — `httpx2.MockTransport` injection pattern (~80 lines)

**Modified files:**
- `docs/middleware.md` — append "Wiring OpenTelemetry" section
- `mkdocs.yml` — three new nav entries
- `docs/index.md` — three new "Where to go next" bullets + 1 amended bullet
- `planning/engineering.md` §8 — append a sub-bullet to Epic 3's "Shipped in v0.7" line
- `planning/releases/0.7.0.md` — rewrite (title + body)
- PR #28 title + body — via `gh pr edit` after the new commits push

**Commit cadence:** one commit per task. Per-task commits keep history reviewable and make a per-page revert trivial if needed.

---

## Task 1: Append "Wiring OpenTelemetry" section to `docs/middleware.md`

**Why first:** the index.md Where-to-go-next change (Task 6) references "and OpenTelemetry wiring" in the Middleware-guide bullet, so the section it points to has to exist first.

**Files:**
- Modify: `docs/middleware.md`

- [ ] **Step 1: Insert the new section**

In `docs/middleware.md`, find this anchor (the start of the existing "See also" section near the end of the file):
```markdown
## See also

- **`planning/engineering.md` §3 (Seam A)** — the formal protocol contract and why the chain is frozen at construction.
```

Insert this new section IMMEDIATELY BEFORE that `## See also` heading (so the new section is sandwiched between "When NOT to write a middleware" and "See also"):

````markdown
## Wiring OpenTelemetry

`httpware[otel]` only ships `opentelemetry-api`. To make the observability events emitted by `Retry` and `Bulkhead` visible, you also need:

- An **SDK** (`opentelemetry-sdk`) to actually collect spans
- An **HTTP instrumentor** (`opentelemetry-instrumentation-httpx`) so each HTTP call creates a span — `httpware`'s events attach to that span via `trace.get_current_span().add_event(...)`

Minimal setup (console exporter for development):

```python
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

trace.set_tracer_provider(TracerProvider())
trace.get_tracer_provider().add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
HTTPXClientInstrumentor().instrument()
```

After this runs, every `httpware` HTTP call gets an `HTTP <method>` span from the instrumentor, and Retry/Bulkhead observability events appear as span events on it (no extra configuration needed in `httpware` itself — the events fire whenever an active span is present).

For production, swap `ConsoleSpanExporter` for your OTLP/Jaeger/Zipkin exporter. See the [OpenTelemetry Python docs](https://opentelemetry.io/docs/languages/python/) for the full SDK setup.

````

- [ ] **Step 2: Verify mkdocs strict build is still clean**

```bash
uv run --with mkdocs --with mkdocs-material mkdocs build --strict 2>&1 | tail -10
rm -rf site/
```
Expected: `Documentation built in <time>` with no warnings. The new external link to `opentelemetry.io` is external; mkdocs strict doesn't validate external URLs.

- [ ] **Step 3: Commit**

```bash
git add docs/middleware.md
git commit -m "docs(middleware): add 'Wiring OpenTelemetry' section

httpware[otel] only ships opentelemetry-api; to make Retry/Bulkhead
observability events visible users also need an SDK + the
opentelemetry-instrumentation-httpx instrumentor (so each HTTP call
has an active span our events can attach to).

Section sits between 'When NOT to write a middleware' and 'See also'.
Minimal console-exporter setup for dev; pointer to OTel Python docs
for production exporter wiring."
```

---

## Task 2: Create `docs/resilience.md`

**Files:**
- Create: `docs/resilience.md`

- [ ] **Step 1: Create the file with the full content below**

````markdown
# Resilience reference

`httpware` ships three resilience primitives under `httpware.middleware.resilience`, all composable through the standard [Middleware](middleware.md) chain:

- **`Retry`** — automatic retry of transient failures with full-jitter exponential backoff
- **`RetryBudget`** — Finagle-style token bucket that bounds the global retry rate to prevent retry storms when downstreams degrade
- **`Bulkhead`** — concurrency limiter via `asyncio.Semaphore` with bounded acquire-wait

The canonical composition is `middleware=[Bulkhead(...), Retry()]` — `Bulkhead` outside `Retry` so one slot covers all retry attempts of a single call. Reach for the [Middleware guide](middleware.md) when you want to write your own resilience policy.

## `Retry`

```python
from httpware.middleware.resilience import Retry
```

| Parameter | Default | Effect |
|---|---|---|
| `max_attempts` | `3` | Total tries (including the first). `1` disables retries entirely; `<1` raises `ValueError`. |
| `base_delay` | `0.1` (s) | Floor for the full-jitter exponential backoff. |
| `max_delay` | `5.0` (s) | Ceiling for backoff. |
| `attempt_timeout` | `None` | If set, each individual attempt is wrapped in `asyncio.timeout(attempt_timeout)`. |
| `retry_status_codes` | `frozenset({408, 429, 502, 503, 504})` | Status codes considered retryable. |
| `retry_methods` | `frozenset({"GET", "HEAD", "OPTIONS", "PUT", "DELETE"})` | Idempotent methods only by default. POST excluded; pass an explicit frozenset including `"POST"` to retry it. |
| `respect_retry_after` | `True` | When the response carries a `Retry-After` header on a retryable status, sleep for the header value (clamped to `max_delay`) instead of the jittered backoff. |
| `budget` | `RetryBudget()` (default-configured) | The token bucket. Pass a shared `RetryBudget` instance to apply one budget across multiple clients. |

### Retry-After parsing

`Retry-After` is parsed as either:
- **Integer seconds** — `Retry-After: 30` → sleep 30s (clamped to `max_delay`)
- **HTTP-date** (RFC 5322) — `Retry-After: Wed, 21 Oct 2026 07:28:00 GMT` → sleep until that absolute time (clamped to `max_delay`, floored at 0)

Negative integer values are clamped to 0. Malformed values are ignored, falling back to the jittered backoff.

### Streaming-body refusal

If the request body was an async-iterable, `Retry` refuses to retry — the iterator is consumed after the first attempt and can't replay. The original exception is re-raised with a PEP 678 note:

```
httpware: not retrying — request body is a stream that cannot replay across attempts
```

The same refusal note is added at the non-idempotent early-exit sites (when streaming combines with a non-idempotent method). The observability event `httpware.retry` `retry.streaming_refused` fires only at the retryable-failure-path site — see [Observability](index.md#observability).

### Exhaustion behavior

On exhaustion, `Retry` re-raises the *last* exception observed (e.g., `ServiceUnavailableError`, `NetworkError`), preserving the original class so `except ServiceUnavailableError` still catches it. A PEP 678 note is added: `httpware: gave up after N attempts`.

If exhaustion is caused by the budget refusing a retry (not by `max_attempts`), the raised exception is `RetryBudgetExhaustedError` instead, with `last_response` / `last_exception` / `attempts` fields populated. See [Errors reference](errors.md).

## `RetryBudget`

```python
from httpware.middleware.resilience import RetryBudget
```

A Finagle-style token bucket bounding retry rate. Each request deposits a token; each retry attempts to withdraw one. Available retries are bounded by `percent_can_retry` of recent deposits, plus a `min_retries_per_sec * ttl` floor.

| Parameter | Default | Effect |
|---|---|---|
| `ttl` | `10.0` (s) | Sliding window over which deposits and withdrawals count. |
| `min_retries_per_sec` | `10.0` | Absolute floor — at least this many retries/sec are permitted regardless of deposit rate. |
| `percent_can_retry` | `0.2` | Fraction of recent deposits that can convert to retries (above the floor). |

### The token-bucket formula

```
ceiling = int(len(deposits_in_window) * percent_can_retry) + int(min_retries_per_sec * ttl)
```

A withdrawal fails when `len(withdrawn_in_window) >= ceiling`.

### Why a floor matters

If the deposit rate is zero (no traffic yet), the percent term is zero — without the floor, the very first retry would be refused. The floor lets small-traffic clients still retry on isolated failures; high-traffic clients are dominated by the percent term and the floor becomes irrelevant.

### Sharing across clients

Pass the same `RetryBudget` instance to multiple `AsyncClient`s when they hit the same downstream — one joint budget covers them all:

```python
import asyncio

from httpware import AsyncClient
from httpware.middleware.resilience import Retry, RetryBudget


shared = RetryBudget()


async def main() -> None:
    async with (
        AsyncClient(base_url="https://api.example.com", middleware=[Retry(budget=shared)]) as users,
        AsyncClient(base_url="https://api.example.com", middleware=[Retry(budget=shared)]) as orders,
    ):
        await asyncio.gather(users.get("/users/1"), orders.get("/orders/1"))
```

### Single-thread assumption

`RetryBudget` is asyncio-aware — deque mutations between await points are atomic on a single event loop. Cross-thread use is out of scope; if you need that, wrap calls in a lock yourself.

## `Bulkhead`

```python
from httpware.middleware.resilience import Bulkhead
```

Concurrency limiter via `asyncio.Semaphore`. Acquires a slot before each request (bounded by `acquire_timeout`); releases on success, exception, AND cancellation.

| Parameter | Default | Effect |
|---|---|---|
| `max_concurrent` | **REQUIRED** | Maximum in-flight requests. `<1` raises `ValueError`. No default — the right cap depends on downstream capacity and SLA. |
| `acquire_timeout` | `1.0` (s) | How long to wait for a slot before raising `BulkheadFullError`. `None` waits forever; `0` fails fast. `<0` raises `ValueError`. |

### Slot release contract

The slot is released in a `try/finally` around `await next(request)`, so all three exit paths release deterministically:
- **Success** — slot released after the response returns
- **Exception** — slot released before the exception propagates
- **Cancellation** — slot released as the `CancelledError` propagates

The slot cannot leak.

### Sharing across clients

Same pattern as `RetryBudget`. One instance, many clients:

```python
shared_bulkhead = Bulkhead(max_concurrent=10)

async with (
    AsyncClient(base_url="https://api.example.com", middleware=[shared_bulkhead, Retry()]) as a,
    AsyncClient(base_url="https://api.example.com", middleware=[shared_bulkhead, Retry()]) as b,
):
    ...  # combined in-flight across a + b is capped at 10
```

### Rejection

When `acquire_timeout` elapses without a slot opening, `Bulkhead` raises `BulkheadFullError` (carries the configured `max_concurrent` and `acquire_timeout` for caller logging). See [Errors reference](errors.md). The `httpware.bulkhead` `bulkhead.rejected` observability event fires at the same site — see [Observability](index.md#observability).

## Composition

The canonical ordering is `middleware=[Bulkhead, Retry]` — `Bulkhead` outermost so one slot covers all retry attempts of a single call:

```python
from httpware import AsyncClient
from httpware.middleware.resilience import Bulkhead, Retry


async def main() -> None:
    async with AsyncClient(
        base_url="https://api.example.com",
        middleware=[
            Bulkhead(max_concurrent=10),
            Retry(),
        ],
    ) as client:
        await client.get("/users/1")
```

Flipping the order (`[Retry, Bulkhead]`) means each retry attempt grabs a fresh slot — defeating the bulkhead under load. Don't do that.

Cross-cutting middleware that emit per-call state (e.g., the Request-ID middleware in the [Middleware guide](middleware.md)) should sit outside `Retry` for the same reason — so all attempts of one call share one ID rather than getting a fresh ID per attempt.

## See also

- **[Middleware guide](middleware.md)** — write your own resilience middleware against the same protocol `Retry` and `Bulkhead` use.
- **[Errors reference](errors.md)** — `RetryBudgetExhaustedError`, `BulkheadFullError`, and the broader exception tree.
- **[Observability](index.md#observability)** — the four operational events these middleware emit.
- **`planning/engineering.md` §3** — the formal Middleware/Seam-A contract.
````

- [ ] **Step 2: Verify mkdocs strict build is clean**

```bash
uv run --with mkdocs --with mkdocs-material mkdocs build --strict 2>&1 | tail -10
rm -rf site/
```
Expected: `Documentation built in <time>` with no warnings. Note: `resilience.md` is not yet in the nav (Task 5 adds it), but mkdocs in strict mode still indexes ALL `.md` files under `docs_dir` and warns about orphans. **If the build complains about `resilience.md` being unreferenced**, that's expected — proceed to commit anyway; Task 5 will add the nav entry and re-verify. Document the warning in your DONE report if it appears.

(In practice mkdocs-material treats orphans as info-level, not warning, so strict mode passes — but flag it if you see otherwise.)

- [ ] **Step 3: Commit**

```bash
git add docs/resilience.md
git commit -m "docs(resilience): write Retry/RetryBudget/Bulkhead reference

New docs/resilience.md (~190 lines) — full parameter tables, defaults,
Retry-After parsing rules, streaming-body refusal contract, exhaustion
behavior, the token-bucket formula + why-the-floor-matters note,
budget/bulkhead sharing across clients, composition guidance, and
cross-references to Middleware guide, Errors reference, and the
Observability section.

No new built-in middleware. Documents what already shipped through
v0.4 (Retry/RetryBudget/Bulkhead) and v0.6 (the observability events
each emits)."
```

---

## Task 3: Create `docs/errors.md`

**Files:**
- Create: `docs/errors.md`

- [ ] **Step 1: Create the file with the full content below**

````markdown
# Errors reference

`httpware` raises typed exceptions automatically — everything inherits `ClientError`, and HTTP responses with 4xx/5xx status raise status-keyed `StatusError` subclasses without you having to call `response.raise_for_status()`.

For the resilience-specific errors (`RetryBudgetExhaustedError`, `BulkheadFullError`) see the [Resilience reference](resilience.md).

## The exception tree

```
ClientError                          (catch-all for anything httpware raises)
├── TransportError                   (connection/network/protocol failure pre-response)
│   └── NetworkError                 (transient — safe to retry; covered by Retry's defaults)
├── TimeoutError                     (also inherits builtins.TimeoutError — except OSError catches it)
├── StatusError                      (got a response but its status was 4xx/5xx)
│   ├── ClientStatusError            (any 4xx — fallback for unknown 4xx codes)
│   │   ├── BadRequestError          (400)
│   │   ├── UnauthorizedError        (401)
│   │   ├── ForbiddenError           (403)
│   │   ├── NotFoundError            (404)
│   │   ├── ConflictError            (409)
│   │   ├── UnprocessableEntityError (422)
│   │   └── RateLimitedError         (429)
│   └── ServerStatusError            (any 5xx — fallback for unknown 5xx codes)
│       ├── InternalServerError     (500)
│       └── ServiceUnavailableError (503)
├── RetryBudgetExhaustedError       (a retry was needed but the budget refused)
└── BulkheadFullError                (acquire_timeout elapsed before a slot opened)
```

## Status-to-exception mapping

| Status | Exception class |
|---|---|
| 400 | `BadRequestError` |
| 401 | `UnauthorizedError` |
| 403 | `ForbiddenError` |
| 404 | `NotFoundError` |
| 409 | `ConflictError` |
| 422 | `UnprocessableEntityError` |
| 429 | `RateLimitedError` |
| 500 | `InternalServerError` |
| 503 | `ServiceUnavailableError` |
| other 4xx | `ClientStatusError` (fallback) |
| other 5xx | `ServerStatusError` (fallback) |

The fallback assumes `400 ≤ status < 600`. Statuses outside that range don't raise (they return the response as-is).

## Catching strategies

```python
from httpware import (
    AsyncClient,
    ClientError,
    StatusError,
    NetworkError,
    TimeoutError,
    NotFoundError,
    RetryBudgetExhaustedError,
    BulkheadFullError,
)


async def fetch(client: AsyncClient, user_id: int) -> dict | None:
    try:
        return await client.get(f"/users/{user_id}", response_model=dict)
    except NotFoundError:
        # Specific status — most precise. Convert to None as the "absent" sentinel.
        return None
    except StatusError as exc:
        # Got a response, but its status was 4xx/5xx and not one we handle specifically.
        # exc.response.* is available — headers, content, request, etc.
        _LOGGER.warning("upstream returned %s for %s", exc.response.status_code, exc.response.request.url)
        raise
    except NetworkError:
        # Transient transport failure. Already retried by the default Retry middleware
        # (if installed) when the method was idempotent. Seeing this means retries
        # exhausted or the method was non-idempotent.
        raise
    except (RetryBudgetExhaustedError, BulkheadFullError) as exc:
        # Resilience refusal — backpressure signal. Back off the caller.
        _LOGGER.error("resilience refused: %s", exc)
        raise
    except ClientError:
        # Catch-all for anything else httpware raised.
        raise
```

`TimeoutError` is doubly-inherited: `except builtins.TimeoutError` and `except OSError` both catch it (matches what `asyncio.wait_for` raises). This lets stdlib-style timeout handling Just Work.

## `exc.response.*` access pattern

For any `StatusError` subclass, the raw `httpx2.Response` is on `exc.response`:

```python
exc.response.status_code     # 404
exc.response.headers          # httpx2.Headers — case-insensitive
exc.response.content          # raw bytes
exc.response.text             # decoded body
exc.response.json()           # parsed JSON (raises if not JSON)
exc.response.request          # the failing httpx2.Request
exc.response.request.url      # the failing URL (httpx2.URL)
exc.response.request.method   # the HTTP method
```

**Security note:** `__repr__` and the exception's summary message strip `user:pass@` userinfo from the URL to avoid leaking credentials in tracebacks. **Query-string secrets are NOT stripped** — keep secrets out of query strings.

## Resilience-error payloads

`RetryBudgetExhaustedError` carries:
- `last_response: httpx2.Response | None` — the last response observed before the budget refused (None if all failures were transport-level)
- `last_exception: BaseException | None` — the last exception observed before the budget refused
- `attempts: int` — number of attempts already completed

`BulkheadFullError` carries:
- `max_concurrent: int` — the configured cap
- `acquire_timeout: float | None` — the configured timeout

Use these for caller-side logging / alerting:

```python
except RetryBudgetExhaustedError as exc:
    _LOGGER.error(
        "budget exhausted after %d attempts; last_status=%s",
        exc.attempts,
        exc.last_response.status_code if exc.last_response is not None else None,
    )
```

## See also

- **[Resilience reference](resilience.md)** — `Retry`, `RetryBudget`, `Bulkhead` parameter tables.
- **[Middleware guide](middleware.md)** — the `@on_error` decorator can translate exceptions into responses.
- **`planning/engineering.md` §4** — the formal exception contract.
````

- [ ] **Step 2: Verify mkdocs strict build is clean**

```bash
uv run --with mkdocs --with mkdocs-material mkdocs build --strict 2>&1 | tail -10
rm -rf site/
```
Expected: `Documentation built in <time>`. Same orphan-page caveat as Task 2.

- [ ] **Step 3: Commit**

```bash
git add docs/errors.md
git commit -m "docs(errors): write exception tree and catching strategies reference

New docs/errors.md (~130 lines) — full StatusError hierarchy as an
ASCII tree, status-to-exception mapping table, practical catching
patterns (specific status -> StatusError -> NetworkError -> resilience
errors -> ClientError catch-all), exc.response.* access pattern with
the userinfo-stripping security note, and the payloads on
RetryBudgetExhaustedError / BulkheadFullError for caller-side logging.

No new exception classes. Documents what already shipped through
v0.4 (resilience errors) and v0.2 (status-keyed tree)."
```

---

## Task 4: Create `docs/testing.md`

**Files:**
- Create: `docs/testing.md`

- [ ] **Step 1: Create the file with the full content below**

````markdown
# Testing guide

`httpware`'s test seam is `httpx2`. Pass any `httpx2.AsyncClient` (including one built on `httpx2.MockTransport`) to `AsyncClient(httpx2_client=...)` — the middleware chain still runs end-to-end, only the wire is mocked. No special test mode, no monkey-patching, no `respx`.

## The basic pattern

```python
from http import HTTPStatus

import httpx2

from httpware import AsyncClient


def handler(request: httpx2.Request) -> httpx2.Response:
    return httpx2.Response(HTTPStatus.OK, json={"id": 1, "name": "Alice"})


async def test_get_user() -> None:
    transport = httpx2.MockTransport(handler)
    async with AsyncClient(httpx2_client=httpx2.AsyncClient(transport=transport)) as client:
        response = await client.get("https://api.example.test/users/1")
    assert response.status_code == HTTPStatus.OK
    assert response.json()["name"] == "Alice"
```

The handler can be sync or async; `httpx2.MockTransport` supports both. The test above uses a sync handler.

If you use `pytest-asyncio` in auto-mode (`asyncio_mode = "auto"` under `[tool.pytest.ini_options]`), async test functions don't need the `@pytest.mark.asyncio` decorator.

## Recording / stateful handlers

For tests that need to vary the response by call count or assert on the requests that came in, use a handler with instance state:

```python
class _ResponseSequence:
    """Returns each status in order; records every request received."""

    def __init__(self, statuses: list[int]) -> None:
        self._statuses = list(statuses)
        self.calls: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.calls.append(request)
        status = self._statuses.pop(0) if self._statuses else HTTPStatus.OK
        return httpx2.Response(status, request=request)


async def test_retry_succeeds_after_503() -> None:
    handler = _ResponseSequence([HTTPStatus.SERVICE_UNAVAILABLE, HTTPStatus.OK])
    transport = httpx2.MockTransport(handler)
    async with AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=transport),
        middleware=[Retry(base_delay=0.001, max_delay=0.002)],
    ) as client:
        response = await client.get("https://example.test/x")
    assert response.status_code == HTTPStatus.OK
    assert len(handler.calls) == 2  # initial + 1 retry
```

The `base_delay`/`max_delay` are set tiny so the test runs instantly — no need for `freezegun` or sleep injection in most cases.

## Testing your custom middleware

Compose your middleware with the mock transport to exercise the chain end-to-end:

```python
async def test_my_middleware_adds_header() -> None:
    handler = _ResponseSequence([HTTPStatus.OK])
    async with AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
        middleware=[MyHeaderMiddleware()],
    ) as client:
        await client.get("https://example.test/x")
    assert handler.calls[0].headers["X-My-Header"] == "expected-value"
```

For middleware with state-keeping (counters, circuit-breaker state), assert on instance attributes after running the call.

## Why not `respx`?

`httpware` deliberately uses `httpx2.MockTransport` instead of `respx` for its own tests. `MockTransport` is the public test seam in `httpx` — supported by the maintainers, stable across versions, lives in the public API surface. `respx` patches private internals and has historically broken across `httpx` major versions. Stick with `MockTransport` unless you have a specific reason not to.

## See also

- **[Middleware guide](middleware.md)** — write the middleware you're testing.
- **[Resilience reference](resilience.md)** — testing `Retry`/`Bulkhead` configurations.
- **`planning/engineering.md` §6** — the project's own testing patterns (Hypothesis property-based tests, `pytest-asyncio` auto-mode, the `RecordedTransport`-was-removed history).
````

- [ ] **Step 2: Verify mkdocs strict build is clean**

```bash
uv run --with mkdocs --with mkdocs-material mkdocs build --strict 2>&1 | tail -10
rm -rf site/
```
Expected: `Documentation built in <time>`. Same orphan caveat.

- [ ] **Step 3: Commit**

```bash
git add docs/testing.md
git commit -m "docs(testing): write mock-transport injection pattern guide

New docs/testing.md (~90 lines) — the httpx2.MockTransport pattern
that the project's own tests use; instance-state handler for
stateful responses (response sequences, request recording); composing
custom middleware with the mock transport for end-to-end tests; brief
'why not respx' note pointing at the private-internals risk.

No code changes. Documents the test pattern that has been in tests/
since v0.2 but never user-facing."
```

---

## Task 5: Update `mkdocs.yml` nav

**Files:**
- Modify: `mkdocs.yml`

- [ ] **Step 1: Replace the nav block**

The current `mkdocs.yml` nav (after the prior 0.7 commits) reads:
```yaml
nav:
  - Quick-Start: index.md
  - Middleware: middleware.md
  - Development:
      - Contributing: dev/contributing.md
```

Replace with:
```yaml
nav:
  - Quick-Start: index.md
  - Resilience: resilience.md
  - Middleware: middleware.md
  - Errors: errors.md
  - Testing: testing.md
  - Development:
      - Contributing: dev/contributing.md
```

Order rationale: Resilience precedes Middleware because most users will *use* the built-ins (`Retry`, `Bulkhead`) before they *write* their own. Errors and Testing follow as reference + setup-friction pages.

- [ ] **Step 2: Verify mkdocs strict build is clean**

```bash
uv run --with mkdocs --with mkdocs-material mkdocs build --strict 2>&1 | tail -10
rm -rf site/
```
Expected: `Documentation built in <time>` with no warnings. All three new pages now have nav entries — any orphan warnings from Tasks 2-4 disappear.

- [ ] **Step 3: Commit**

```bash
git add mkdocs.yml
git commit -m "docs(nav): add Resilience / Errors / Testing pages to mkdocs nav

Six top-level entries after this:
  Quick-Start, Resilience, Middleware, Errors, Testing, Development

Resilience precedes Middleware because most users reach for the
built-in Retry/Bulkhead before writing their own. Errors and Testing
follow as reference + setup-friction pages."
```

---

## Task 6: Update `docs/index.md` "Where to go next" + amend Middleware bullet

**Files:**
- Modify: `docs/index.md`

The prior 0.7 commit `61306fc` added a Middleware-guide bullet as the first entry in "Where to go next". This task adds three more bullets and extends the existing Middleware bullet with `and OpenTelemetry wiring` (since Task 1 added that section).

- [ ] **Step 1: Replace the "Where to go next" block**

Find this current block (around L107-L112):
```markdown
## Where to go next

- **[Middleware guide](middleware.md)** — write your own middleware. Covers the Middleware Protocol, the phase decorators, and a worked Request-ID propagation example.
- **[Engineering Notes](https://github.com/modern-python/httpware/blob/main/planning/engineering.md)** — design invariants, the three protocol seams, exception contract, module layout, testing patterns, optional-extras pattern. Lives in the repo at `planning/engineering.md`.
- **[Contributing](dev/contributing.md)** — setup, conventions, workflow.
- **[Release notes](https://github.com/modern-python/httpware/releases)** — per-version changelogs.
```

Replace with:
```markdown
## Where to go next

- **[Resilience reference](resilience.md)** — every parameter on `Retry`, `RetryBudget`, and `Bulkhead`; the retry-rule matrix; Retry-After parsing; budget sharing.
- **[Middleware guide](middleware.md)** — write your own middleware. Covers the Middleware Protocol, the phase decorators, a worked Request-ID propagation example, and OpenTelemetry wiring.
- **[Errors reference](errors.md)** — the full exception tree, catching strategies, `exc.response.*` access pattern.
- **[Testing guide](testing.md)** — mock-transport injection pattern for testing code that uses `httpware`.
- **[Engineering Notes](https://github.com/modern-python/httpware/blob/main/planning/engineering.md)** — design invariants, the three protocol seams, exception contract, module layout, testing patterns, optional-extras pattern. Lives in the repo at `planning/engineering.md`.
- **[Contributing](dev/contributing.md)** — setup, conventions, workflow.
- **[Release notes](https://github.com/modern-python/httpware/releases)** — per-version changelogs.
```

Three new bullets at the top (Resilience, Errors, Testing), the existing Middleware bullet amended with `and OpenTelemetry wiring`, the Engineering/Contributing/Release-notes bullets unchanged.

- [ ] **Step 2: Verify mkdocs strict build is clean**

```bash
uv run --with mkdocs --with mkdocs-material mkdocs build --strict 2>&1 | tail -10
rm -rf site/
```
Expected: clean. All four internal links resolve (resilience.md, middleware.md, errors.md, testing.md).

- [ ] **Step 3: Commit**

```bash
git add docs/index.md
git commit -m "docs(index): expand Where-to-go-next with Resilience / Errors / Testing

Three new bullets (Resilience reference, Errors reference, Testing
guide), plus an addendum to the existing Middleware bullet noting the
new OpenTelemetry wiring section. Engineering / Contributing /
Release-notes bullets unchanged."
```

---

## Task 7: Update `planning/engineering.md` §8 — enrich Epic 3 SHIPPED note

**Files:**
- Modify: `planning/engineering.md`

The prior 0.7 commit `07ac068` recorded `3-6` as shipped in v0.7 and marked Epic 3 closed. This task adds a sub-bullet noting that v0.7 also bundles the rest of the first-cut user docs surface.

- [ ] **Step 1: Insert a new sub-bullet under the existing Epic 3 "Shipped in v0.7" line**

Find the current Epic 3 block (around L131-L135):
```markdown
- **Epic 3 — Resilience:**
  - **Shipped in v0.4 slice 1:** `Retry` middleware + Finagle-style `RetryBudget` token bucket + `attempt_timeout=` parameter (folded-in 3-1). See [`planning/specs/2026-06-05-retry-and-retry-budget-design.md`](specs/2026-06-05-retry-and-retry-budget-design.md) and [`planning/plans/2026-06-05-retry-and-retry-budget-plan.md`](plans/2026-06-05-retry-and-retry-budget-plan.md).
  - **Shipped in v0.4 slice 2:** `Bulkhead` middleware (concurrency limiter via `asyncio.Semaphore` with bounded acquire wait). See [`planning/specs/2026-06-05-bulkhead-design.md`](specs/2026-06-05-bulkhead-design.md) and [`planning/plans/2026-06-05-bulkhead-plan.md`](plans/2026-06-05-bulkhead-plan.md).
  - **Shipped in v0.7:** `3-6` extension-slot docs — [`docs/middleware.md`](../docs/middleware.md). Covers the Middleware Protocol, phase decorators, a Request-ID worked example, and "when NOT to write a middleware." See [`planning/specs/2026-06-05-extension-slot-docs-design.md`](specs/2026-06-05-extension-slot-docs-design.md) and [`planning/plans/2026-06-05-extension-slot-docs-plan.md`](plans/2026-06-05-extension-slot-docs-plan.md).
  - **Epic 3 closed.**
```

Insert this new sub-bullet between the existing "Shipped in v0.7" line and the "Epic 3 closed." line:
```markdown
  - **v0.7 also bundles** the rest of the first-cut user docs surface — [`docs/resilience.md`](../docs/resilience.md) (Retry/RetryBudget/Bulkhead reference), [`docs/errors.md`](../docs/errors.md) (exception tree + catching strategies), [`docs/testing.md`](../docs/testing.md) (mock-transport injection pattern) — plus an "OpenTelemetry wiring" section appended to `docs/middleware.md`. See [`planning/specs/2026-06-05-v0.7-docs-expansion-design.md`](specs/2026-06-05-v0.7-docs-expansion-design.md) and [`planning/plans/2026-06-05-v0.7-docs-expansion-plan.md`](plans/2026-06-05-v0.7-docs-expansion-plan.md).
```

So the Epic 3 block becomes a six-line list — the two v0.4 slices, the v0.7 extension-slot-docs line, the new v0.7-also-bundles line, and the "Epic 3 closed." closer.

- [ ] **Step 2: Commit**

```bash
git add planning/engineering.md
git commit -m "docs(engineering): note v0.7 also bundled the rest of user-docs surface

Adds a sub-bullet under Epic 3's existing 'Shipped in v0.7' line
calling out docs/resilience.md, docs/errors.md, docs/testing.md, and
the OpenTelemetry-wiring section appended to docs/middleware.md. Links
to the expansion spec and plan."
```

---

## Task 8: Rewrite `planning/releases/0.7.0.md`

**Files:**
- Modify: `planning/releases/0.7.0.md` (full rewrite)

The prior 0.7 commit `b0aac27` wrote the release notes scoped to just the Middleware guide. This task rewrites them to cover the expanded scope. The GitHub Release will be created from this file after merge, so the new content must stand alone as user-facing release notes.

- [ ] **Step 1: Replace the entire file contents**

Overwrite `planning/releases/0.7.0.md` with this content:

````markdown
# httpware 0.7.0 — First-cut user docs (docs-only)

**0.7.0 is a docs-only release. No API changes.** Code written against 0.6.0 continues to work unchanged.

This release ships the first-cut user-facing documentation surface — every shipped feature through 0.6 now has a user-facing reference page, and the two highest-friction adoption recipes (test-mocking and OpenTelemetry wiring) are concrete. Epic 3 (Resilience) closes with this release.

## What's new

Four new docs deliverables on the docs site:

- **[`docs/middleware.md`](../../docs/middleware.md)** — write your own middleware against `httpware.middleware.Middleware` and `Next`. Covers the protocol, the phase decorators (`@before_request`, `@after_response`, `@on_error`), a worked `RequestIdMiddleware` example, a "when NOT to write a middleware" section, **and an "OpenTelemetry wiring" section** with a minimal SDK + `opentelemetry-instrumentation-httpx` setup that makes the 0.6.0 Retry/Bulkhead observability events visible as span events.
- **[`docs/resilience.md`](../../docs/resilience.md)** — deep-dive reference for `Retry`, `RetryBudget`, and `Bulkhead`: every parameter with its default and effect, the retry-rule matrix (status codes × methods), Retry-After parsing, streaming-body refusal contract, the token-bucket formula, why the floor matters, budget/bulkhead sharing across clients, and composition guidance.
- **[`docs/errors.md`](../../docs/errors.md)** — the full `StatusError` hierarchy as an ASCII tree, the status-to-exception mapping table, practical catching strategies (specific status → `StatusError` → `NetworkError` → resilience errors → `ClientError` catch-all), the `exc.response.*` access pattern with the userinfo-stripping security note, and the payloads on `RetryBudgetExhaustedError` / `BulkheadFullError` for caller-side logging.
- **[`docs/testing.md`](../../docs/testing.md)** — the `httpx2.MockTransport` injection pattern via `AsyncClient(httpx2_client=...)`. Recording/stateful handlers, testing custom middleware end-to-end, brief "why not respx" note pointing at the private-internals risk.

Plus discovery: three new mkdocs nav entries (Resilience, Errors, Testing), four new bullets in `docs/index.md` "Where to go next", and engineering notes updated.

## What's not in this release

- **No source code changes.** The Middleware protocol, phase decorators, resilience primitives, exception tree, and test-transport seam all already existed; this release documents them.
- **No new built-in middleware.** No CircuitBreaker, no RateLimiter, no auth helpers.
- **No API autodoc** (e.g., mkdocstrings). Hand-written user docs only.
- **No benchmarks page, no migration guide, no speculative cookbook recipes.** Reference pages for shipped features + concrete adoption recipes only.
- **No mkdocs publish workflow / docs-site infrastructure.** That's Epic 6 (story `6-2`); this release just keeps `mkdocs build --strict` green.

## Epic 3 closed

Epic 3 (Resilience) has shipped end-to-end:
- v0.4 slice 1 — `Retry` + `RetryBudget` + `attempt_timeout=`
- v0.4 slice 2 — `Bulkhead`
- v0.7 — `3-6` extension-slot docs + the rest of the first-cut user-docs surface

Remaining roadmap is Epic 6 (ship v1.0): `6-2` docs site infrastructure (mkdocs publishing, hand-written content only — no autodoc), and `6-5` release flow (Trusted Publishers + Sigstore).

## References

- Middleware spec: [`planning/specs/2026-06-05-extension-slot-docs-design.md`](../specs/2026-06-05-extension-slot-docs-design.md)
- Docs-expansion spec: [`planning/specs/2026-06-05-v0.7-docs-expansion-design.md`](../specs/2026-06-05-v0.7-docs-expansion-design.md)
- Middleware plan: [`planning/plans/2026-06-05-extension-slot-docs-plan.md`](../plans/2026-06-05-extension-slot-docs-plan.md)
- Docs-expansion plan: [`planning/plans/2026-06-05-v0.7-docs-expansion-plan.md`](../plans/2026-06-05-v0.7-docs-expansion-plan.md)
- Roadmap: [`planning/engineering.md`](../engineering.md) §8
````

- [ ] **Step 2: Commit**

```bash
git add planning/releases/0.7.0.md
git commit -m "docs(release): rewrite 0.7.0 notes for expanded docs scope

The prior release notes covered just the Middleware guide. This
rewrite covers the full first-cut user-docs surface that 0.7 actually
ships:
- docs/middleware.md (incl. new OTel-wiring section)
- docs/resilience.md (Retry/RetryBudget/Bulkhead reference)
- docs/errors.md (exception tree + catching strategies)
- docs/testing.md (mock-transport pattern)

Title changes from 'Middleware extension guide' to 'First-cut user
docs'. 'What's not in this release' enriched with the autodoc /
benchmarks / migration-guide / cookbook out-of-scope items per the
project's docs philosophy."
```

---

## Task 9: Final verification + push + update PR #28

**Files:** none modified by edits; only verification + remote updates.

- [ ] **Step 1: Lint-ci (sanity)**

```bash
just lint-ci
```
Expected: clean. No source code changes, so this is a pure no-op confirmation.

- [ ] **Step 2: Full test suite (sanity)**

```bash
just test
```
Expected: 251 passed, 100% coverage. No source code changes, so identical to the prior run.

- [ ] **Step 3: mkdocs strict build**

```bash
uv run --with mkdocs --with mkdocs-material mkdocs build --strict 2>&1 | tail -20
rm -rf site/
```
Expected: `Documentation built in <time>` with zero warnings. Every internal link in the new pages must resolve. The red `×` lines from mkdocs-material are plugin self-notices, not strict-build failures — the pass signal is `Documentation built in <time>`.

- [ ] **Step 4: Cross-reference scan**

```bash
grep -nE '\]\(' docs/resilience.md docs/errors.md docs/testing.md docs/middleware.md
```

Expected: every link target is either:
- A docs-internal anchor (e.g., `middleware.md`, `index.md#observability`, `errors.md`) — already verified by mkdocs strict
- A clearly-external URL (`opentelemetry.io/...`)
- A repo path used as prose reference (`planning/engineering.md`) — not a link target

If a link points to a missing anchor (e.g., `middleware.md#nonexistent`), mkdocs strict would have caught it in Step 3.

- [ ] **Step 5: Architecture invariants (sanity)**

```bash
grep -rE 'httpx2\._' src/httpware/ || echo "PASS: no httpx2 private API"
grep -rE 'from __future__ import annotations' src/httpware/ || echo "PASS: no __future__ annotations"
grep -rE '\bprint\(' src/httpware/ || echo "PASS: no print()"
grep -rE 'logging\.(basicConfig|getLogger)\(\)' src/httpware/ || echo "PASS: no global logging"
grep -rE '# (type|mypy): ignore' src/httpware/ || echo "PASS: no type/mypy ignore"
```
Each should print PASS. (Docs-only — no source files touched.)

- [ ] **Step 6: Push the new commits**

```bash
git push origin feat/v0.7-middleware-docs
```

Expected: 8 new commits pushed (Tasks 1-8). PR #28 picks them up automatically.

- [ ] **Step 7: Update PR #28 title + body**

```bash
gh pr edit 28 --title "feat(v0.7): first-cut user docs — Middleware + Resilience + Errors + Testing (closes Epic 3)" --body "$(cat <<'EOF'
## Summary

Closes Epic 3 (Resilience). Ships the first-cut user-facing documentation surface — every shipped feature through 0.6 now has a user-facing reference page, and the two highest-friction adoption recipes (test-mocking and OpenTelemetry wiring) are concrete.

- **New `docs/middleware.md`** — write your own middleware against the protocol. Covers the protocol, the phase decorators, a worked Request-ID propagation example, a "when NOT to write a middleware" section, **and an OpenTelemetry wiring section** (SDK + opentelemetry-instrumentation-httpx setup).
- **New `docs/resilience.md`** — Retry/RetryBudget/Bulkhead parameter tables + retry-rule matrix + Retry-After parsing + streaming-body refusal contract + token-bucket formula + budget sharing + composition guidance.
- **New `docs/errors.md`** — full StatusError tree + status-to-exception mapping + catching strategies + exc.response.* access pattern + resilience-error payloads.
- **New `docs/testing.md`** — \`httpx2.MockTransport\` injection pattern + recording handlers + testing custom middleware + why not respx.
- **Discovery:** mkdocs nav (3 new entries), \`docs/index.md\` Where-to-go-next (3 new bullets + 1 amended), \`planning/engineering.md\` §8 (v0.7 SHIPPED note enriched), \`planning/releases/0.7.0.md\` rewritten to cover the expanded scope.
- **Docs-only:** zero source files modified. The protocol, decorators, resilience primitives, exception tree, and test-transport seam all already existed (shipped through v0.6); this release documents them.

Specs: [extension-slot](planning/specs/2026-06-05-extension-slot-docs-design.md), [docs expansion](planning/specs/2026-06-05-v0.7-docs-expansion-design.md)
Plans: [extension-slot](planning/plans/2026-06-05-extension-slot-docs-plan.md), [docs expansion](planning/plans/2026-06-05-v0.7-docs-expansion-plan.md)
Release notes: [planning/releases/0.7.0.md](planning/releases/0.7.0.md)

## Test Plan

- [x] \`just lint-ci\` — clean (no source files changed)
- [x] \`just test\` — 251 passed, 100% coverage (no source files changed)
- [x] \`mkdocs build --strict\` — clean across all 4 new/edited pages + nav + index touchups
- [x] Architecture invariants — no \`httpx2._\`, no \`__future__\` annotations, no \`print()\`, no global logging, no \`# type:\`/\`# mypy:\` ignores
- [ ] Reviewer: spot-check the Retry-After / streaming-refusal / token-bucket-formula sections of \`docs/resilience.md\` against the actual implementation behavior (most likely place for doc drift)
- [ ] Reviewer: confirm the OpenTelemetry wiring snippet actually produces visible span events with a real \`opentelemetry-sdk\` install — the minimal example claims so but isn't gated by any test
- [ ] Reviewer: nav order — Resilience precedes Middleware (use built-ins before write your own). Comment if you think Middleware should come first

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)" 2>&1 | tail -3
```

Expected: PR title + body updated; URL printed.

---

## Out of scope for this plan (per the spec)

These items are deliberately deferred or retired. Do NOT do them in this PR:

- **No source code changes.** Zero `src/` files modified. The protocol + decorators + resilience primitives + exception tree all already exist; this PR documents them.
- **No new built-in middleware.** No CircuitBreaker, no RateLimiter.
- **No API autodoc / mkdocstrings.** Per the user-docs-philosophy memory.
- **No benchmarks page, no migration guide, no speculative cookbook recipes.** Per the same memory.
- **No dedicated `docs/tracing.md` page.** The OTel wire-up rides as a section of `docs/middleware.md` (Task 1).
- **No mkdocs publish workflow / docs-site infrastructure.** Epic 6 story `6-2`.
- **No version bump in `pyproject.toml`.** Tag-driven (`uv version $GITHUB_REF_NAME` overwrites at build).
- **No CLAUDE.md changes.**
- **No new branch.** All 8 new commits stack on top of the existing 6 + 2 spec commits on `feat/v0.7-middleware-docs`.

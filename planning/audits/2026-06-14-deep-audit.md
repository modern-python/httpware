# httpware deep audit — 2026-06-14

**Status:** complete
**Method:** ten adversarial finders fanned out across the codebase → every candidate run through a 3-lens verify panel (code_reality, reproducer, spec_grounded) → only candidates surviving ≥2/3 lenses kept → single synthesis pass for triage, dedup, and report.

## Summary

35 confirmed findings survived verification (33 distinct after dedup; two pydantic-import duplicates and two `middleware/__init__` `__all__` duplicates were folded). Severity applied strictly: a missing test or a duplicated-but-not-yet-diverged block is not a bug, and a defect reachable only under a non-default knob is capped at low.

- Blockers: 0
- High: 1
- Medium: 4
- Low: 14
- Nits: 14

**Headline:** `architecture/extras.md` asserts that the pydantic extra is imported behind an `is_<extra>_installed` guard *inside* `decoders/pydantic.py` "never at package top level" — but `pydantic.py:13` does `from pydantic import TypeAdapter` unconditionally at module top, so the documented isolation invariant (and its grep self-check) is false, and in a real no-pydantic environment the friendly `ImportError` guard is dead code, replaced by a bare `ModuleNotFoundError`.

**Not covered:** no dynamic/runtime execution, fuzzing, or live-network testing was performed — all findings are static (source/test/doc reading plus single-call reproducer reasoning). Performance findings were uniformly refuted as micro-optimizations with no observable defect, so this pass yields no actionable performance work. No dependency-CVE / supply-chain scan was run beyond version-constraint inspection; no type-checker or linter was executed as part of the audit.

## Findings

### High

#### `architecture/extras.md` claims the pydantic import is guarded inside `decoders/pydantic.py`, but it is unguarded at module top
*(accuracy / architecture_docs — verified)*

`architecture/extras.md:22`

The doc states the extra is imported "**inside** that module behind an `is_<extra>_installed` guard … never at package top level," and offers a grep self-check that "returns exactly one indented line." In reality `decoders/pydantic.py:13` imports `TypeAdapter` unconditionally at module top, the line is not indented, and isolation is actually achieved by a lazy import in `client.py`'s `_build_default_decoders()`. The documented invariant and its verification command are both wrong; only the msgspec sibling matches the description.

```
The `import` of the extra happens **inside** that module behind an `is_<extra>_installed` guard
from `_internal/import_checker.py` — never at package top level. … `grep -rnE 'from pydantic|import
pydantic' src/httpware/ | grep -v import_checker` returns exactly one indented line (the guarded
import in `decoders/pydantic.py`).
```

Panel 2/3: spec_grounded, spec_grounded. Suggested direction: reconcile the doc with reality — either describe the actual lazy-import-in-`client.py` isolation mechanism for pydantic, or treat the asymmetry as the source defect (see the two Medium pydantic-import findings below) and document a single consistent pattern.

### Medium

#### `decoders/pydantic.py` has an unguarded module-level pydantic import; the `__init__` fallback is dead code without the extra
*(optional_extras / correctness — verified)*

`src/httpware/decoders/pydantic.py:13`

Line 13 runs `from pydantic import TypeAdapter` unconditionally, so `import httpware.decoders.pydantic` (or `from … import PydanticDecoder`) raises `ModuleNotFoundError` at module-load time when pydantic is absent — before the friendly `ImportError(MISSING_DEPENDENCY_MESSAGE)` guard in `PydanticDecoder.__init__` can ever run. The guard only fires in the synthetic case where pydantic is installed but `is_pydantic_installed` is monkeypatched False. `decoders/msgspec.py` does this correctly with a module-level `if import_checker.is_msgspec_installed: import msgspec`. *(Folds two confirmed findings — the optional_extras "unguarded import" and the correctness "guard unreachable" — into one; same file:line, same root cause.)*

```python
from pydantic import TypeAdapter

from httpware._internal import import_checker
    ...
    def __init__(self) -> None:
        if not import_checker.is_pydantic_installed:
            raise ImportError(MISSING_DEPENDENCY_MESSAGE)
```

Panel 3/3: code_reality, reproducer, spec_grounded. Suggested direction: mirror the msgspec module-level conditional-import pattern so the module imports cleanly without the extra and the `__init__` guard becomes the real fail-fast path; this also fixes the High doc finding above.

#### No response body size limit before deserialization — attacker-controlled server can drive unbounded allocation
*(deserialization-safety / security — verified)*

`src/httpware/client.py:180`

When `response_model` is provided, `send()` / `send_with_response()` (sync and async) read `response.content` — buffering the whole body — then hand the raw bytes to the decoder. There is no upper bound; httpx2 imposes no default max body size either. An attacker-controlled server can return an arbitrarily large body and force memory allocation proportional to it before any decode begins.

```python
response = await self._dispatch(request)
try:
    return decoder.decode(response.content, response_model)
```

Panel 2/3: code_reality, code_reality. Suggested direction: consider an opt-in max-decode-size guard at the decode seam (Seam B) that checks `Content-Length` / accumulated bytes before buffering, raising a typed `ClientError`; document that the streaming API does not help here because decode requires `.content`.

#### `tests/test_error_mapping_terminal.py` covers AsyncClient only; the sync `Client._terminal` status-raising path has no parallel suite
*(test-coverage / tests — verified)*

`tests/test_error_mapping_terminal.py:1`

All 11 tests are `async def` against `AsyncClient`. The sync `Client._terminal` (`client.py:884`) calls the same `_raise_on_status_error`, but no suite exercises unknown-4xx→`ClientStatusError`, unknown-5xx→`ServerStatusError`, 3xx non-raise, or transport-exception mapping on the sync terminal; `test_client_sync.py` has a single 404 test and zero fallback-class tests. The invariants are unproven on the sync surface.

```
"""Tests for the AsyncClient internal terminal's exception mapping."""
```

Panel 2/3: code_reality, reproducer. Suggested direction: add sync mirrors using `Client(httpx2_client=httpx2.Client(transport=...))` covering the unknown-4xx/5xx fallback classes and the 3xx non-raise. *(Note: this is the broadest of several sync-parity test gaps; the narrower ones are bucketed Low/Nit below.)*

#### `architecture/client.md` streaming section omits `Client.stream()` — documents only `AsyncClient.stream()`
*(accuracy / architecture_docs — verified)*

`architecture/client.md:17`

The doc says "`AsyncClient.stream()` provides a context-manager API … It bypasses the middleware chain by design," but `client.py:1496-1551` defines `Client.stream()` with identical chain-bypass semantics (its own docstring says "matches AsyncClient.stream() behavior"). A reader consulting the architecture doc would conclude the sync client has no streaming surface.

```
AsyncClient.stream() provides a context-manager API for chunked response bodies. It bypasses the
middleware chain by design.
```

Panel 3/3: code_reality, spec_grounded, spec_grounded. Suggested direction: add `Client.stream()` to the streaming section as the sync peer, noting both bypass the chain.

### Low

#### RetryBudget token withdrawn before the `Retry-After > max_delay` give-up check (sync and async)
*(correctness — verified)*

`src/httpware/middleware/resilience/retry.py:162`

In both `AsyncRetry.__call__` (line 162) and `Retry.__call__` (line 300), `budget.try_withdraw()` debits a token *before* the `retry_after > self.max_delay` guard (line 187 / 325). When a server's `Retry-After` exceeds `max_delay`, the middleware re-raises without retrying, yet a token has already been spent — a sustained `Retry-After`-flood drains shared-budget capacity in proportion to request rate, suppressing retries for unrelated well-behaved requests. Reachable only when `respect_retry_after` is on and a server sends an over-large header.

```python
if not self.budget.try_withdraw():
    ...
    raise RetryBudgetExhaustedError(...) from last_exc
...
if retry_after is not None and retry_after > self.max_delay:
    ...
    raise last_exc
```

Panel 2/3: code_reality, reproducer. Suggested direction: evaluate the `Retry-After > max_delay` give-up condition before withdrawing from the budget; mirror in both classes.

#### `RetryBudget`'s `threading.Lock` can block the asyncio event-loop thread when shared sync↔async
*(concurrency — verified)*

`src/httpware/middleware/resilience/budget.py:54`

`deposit()` and `try_withdraw()` unconditionally acquire a `threading.Lock`. When one budget is shared by a sync `Client` (on a thread-pool thread) and an `AsyncClient` (on the loop thread), a sync thread holding the lock blocks the event-loop thread's acquisition, stalling all coroutines for the lock-hold duration. The docstring advertises "asyncio-safe" without qualifying that "safe" means no corruption, not non-blocking.

```
Thread-safe and asyncio-safe: all mutations go through a threading.Lock.
A single RetryBudget instance is safe to share across threads, across
coroutines on one event loop, and across (sync Client, AsyncClient) pairs
in the same process.
```

Panel 2/3: code_reality, spec_grounded. Suggested direction: qualify the docstring's "asyncio-safe" claim to clarify the blocking caveat, and/or keep the critical section minimal; a real fix is out of scope for a thin lock.

#### `_parse_retry_after` swallows `ValueError` but not `OverflowError` — a crafted header crashes the retry loop
*(untrusted-response / error_contract — verified)*

`src/httpware/middleware/resilience/retry.py:60`

A `Retry-After` value of 309–4300 decimal digits makes `float(int(value))` raise `OverflowError`, which is not caught by `except ValueError`. The exception propagates unhandled through both `AsyncRetry` and `Retry`, surfacing to the caller as an unexpected crash instead of being treated as a malformed header.

```python
return max(0.0, float(int(value)))  # clamp: negative integers are malformed servers
    except ValueError:
        pass
```

Panel 2/3: code_reality, reproducer. Suggested direction: broaden the guard to `except (ValueError, OverflowError)` so any unparseable header degrades to "no Retry-After hint."

#### Query-string secrets are logged unredacted in all resilience-middleware observability events
*(secret-leakage / security — verified)*

`src/httpware/middleware/resilience/retry.py:155`

Every resilience middleware emits `"url": str(request.url)` into log records and OTel span events. `str(request.url)` includes the full query string, so tokens embedded as query params (`?api_key=…`) are written to logs and telemetry across retry.py (lines 136/155/171/274/293/309), bulkhead.py (117/173), circuit_breaker.py (193), timeout.py (72). `errors.py` documents this gap for tracebacks, but the middleware applies no redaction.

```python
attributes={
    "method": request.method,
    "url": str(request.url),
```

Panel 2/3: code_reality, reproducer. Suggested direction: introduce a shared `_redact_url_for_logs` helper (strip userinfo *and* query string) and route all middleware `url` attributes through it.

#### Query-string credentials survive `_strip_userinfo` and appear verbatim in `StatusError.__str__`/`__repr__`
*(secret-leakage / security — verified)*

`src/httpware/errors.py:7`

The module docstring admits "Query-string secrets are NOT stripped here." Consequently `str(exc)`/`repr(exc)` for any `StatusError` include the full URL with query string, so `?access_token=…` / `?api_key=…` tokens land in exception messages, log lines, Sentry reports, and the notes `AsyncRetry` adds via `last_exc.add_note(...)`.

```
Query-string secrets are NOT stripped here.
```

Panel 2/3: code_reality, reproducer. Suggested direction: extend the `_strip_userinfo` sanitizer (or add a sibling) to redact known-sensitive query parameters before composing the error summary; coordinate with the middleware redaction helper above.

#### `StatusError.response.request` carries full request headers (`Authorization`, `Cookie`) reachable from any handler
*(secret-leakage / security — verified)*

`src/httpware/errors.py:70`

`StatusError` stores the whole `httpx2.Response`, which references the `httpx2.Request` and its outgoing headers. Any handler that logs or serializes a caught `StatusError` (e.g. `exc.response.request.headers`) exposes `Authorization`/`Cookie`/`Proxy-Authorization`; `__repr__` redacts only URL userinfo, not headers. This is a documented trust-boundary item rather than a bug, but downstream error handlers must be aware.

```python
def _summary(self) -> str:
    method = self.response.request.method
    url = _strip_userinfo(str(self.response.request.url))
    return f"{self.response.status_code} {method} {url}"
```

Panel 2/3: code_reality, reproducer. Suggested direction: add an explicit "secrets reachable via `exc.response.request`" callout to `architecture/errors.md` so handler authors redact before logging.

#### `stream()` pre-reads the full error body unconditionally on 4xx/5xx
*(deserialization-safety / security — verified)*

`src/httpware/client.py:788`

In both `AsyncClient.stream()` and `Client.stream()`, a 4xx/5xx status triggers a full `response.aread()` / `response.read()` so `exc.response.content` is populated — with no size limit. A 500 with a 1 GB body buffers 1 GB unconditionally, even though the caller asked for streaming.

```python
if HTTPStatus.BAD_REQUEST <= response.status_code < 600:
    await response.aread()  # pre-read body so exc.response.content works
    _raise_on_status_error(response)
```

Panel 2/3: code_reality, code_reality. Suggested direction: bound the error-body pre-read (or make it opt-in), so a hostile error body cannot defeat the streaming memory profile.

#### `middleware/__init__.py` defines no `__all__`, leaking 9+ unintended star-import symbols and breaking subpackage symmetry
*(public_api — verified)*

`src/httpware/middleware/__init__.py:1`

With no `__all__`, `from httpware.middleware import *` re-exports `Awaitable`, `Callable`, `Protocol`, `TypeAlias`, `runtime_checkable`, the third-party `httpx2`, and the internal `chain`/`resilience` submodules — none of them intended surface. The sibling `resilience/__init__.py` and `decoders/__init__.py` both define `__all__`, making `middleware` the inconsistent case. *(Folds two confirmed findings — the star-import leak and the subpackage-inconsistency observation — into one; same file:line.)*

```
Public middleware namespace: ['AsyncMiddleware', 'AsyncNext', 'Awaitable', 'Callable', 'Middleware',
'Next', 'Protocol', 'TypeAlias', 'after_response', 'async_after_response', 'async_before_request',
'async_on_error', 'before_request', 'chain', 'httpx2', 'on_error', 'resilience', 'runtime_checkable']
```

Panel 2/3: code_reality, reproducer. Suggested direction: add an explicit `__all__` listing the ten public middleware names, bringing the subpackage in line with its siblings.

#### `test_retry_props.py` is described as testing "retry interleaving" but contains no concurrent tasks
*(concurrency / tests — verified)*

`tests/test_retry_props.py:1`

The discover map labels the file "Hypothesis property-based tests for retry interleaving," yet every test issues one sequential request per example — no `gather`, `create_task`, or threads — and the budget-interaction tests are even synchronous. No test exercises two concurrent retries racing on a shared `RetryBudget`.

```python
async def test_total_attempts_never_exceeds_max_attempts(
    max_attempts: int,
    status: int,
    method: str,
) -> None:
    ...
    await client.request(method, "https://example.test/x")
```

Panel 2/3: code_reality, spec_grounded. Suggested direction: either add a genuinely interleaved property/concurrency test for shared-budget retries, or correct the discover-map description to "sequential retry-policy bounds."

#### `test_bulkhead_sync_props.py` uses a hard `time.sleep(0.005)` to synchronize thread startup — flaky on slow CI
*(concurrency / tests — verified)*

`tests/test_bulkhead_sync_props.py:96`

The test submits up to 4 holder tasks to a thread pool, then sleeps 5 ms assuming all holder threads have started *and* acquired their semaphore slots. Thread-startup overhead on loaded CI can exceed 5 ms, leaving a slot free so the expected `BulkheadFullError` is not raised; Hypothesis re-runs this many times per session, compounding the risk.

```python
holders = [pool.submit(client.get, f"https://example.test/hold-{i}") for i in range(max_concurrent)]
time.sleep(0.005)
for i in range(extra_requests):
    with pytest.raises(BulkheadFullError):
        client.get(f"https://example.test/extra-{i}")
```

Panel 2/3: code_reality, reproducer. Suggested direction: replace the fixed sleep with a deterministic barrier (e.g. a `threading.Barrier` or per-holder "acquired" event) so the test waits on actual slot acquisition. *(Note: the async sibling using `asyncio.sleep` was refuted — the event loop drains ready callbacks deterministically — so only the sync thread-pool variant is flaky.)*

#### No test asserts `StatusError` leaf subclasses do not override `__init__`
*(test-coverage / tests — verified)*

`tests/test_errors.py:46`

CLAUDE.md and `architecture/errors.md` mandate that all `StatusError` subclasses must not override `__init__`; this is enforced only by review. No test checks `'__init__' not in cls.__dict__` for any of the nine leaves, so a future subclass that adds an `__init__` would pass the whole suite.

```python
def test_inheritance_tree() -> None:
    ...
    for exc in (
        BadRequestError,
        UnauthorizedError,
        ForbiddenError,
        ForbiddenError,
        ConflictError,
        UnprocessableEntityError,
        RateLimitedError,
    ):
        assert issubclass(exc, ClientStatusError), exc
```

Panel 3/3: code_reality, reproducer, spec_grounded. Suggested direction: add a parametrized test over all nine leaves asserting `'__init__' not in cls.__dict__`.

#### No test exercises `TimeoutError` as a CircuitBreaker failure trigger (async or sync)
*(coverage_gap / tests — verified)*

`tests/test_circuit_breaker.py:158`

`circuit_breaker.py` counts both `NetworkError` and `TimeoutError` as failures (`except (NetworkError, TimeoutError)`). The tests cover `NetworkError` tripping the breaker (via `ConnectError`) but never a `TimeoutError` driving the counter and opening the circuit; the same gap exists in `test_circuit_breaker_sync.py`. A regression that stopped counting timeouts would pass.

```python
except (NetworkError, TimeoutError):
    self._state.on_failure(role, request)
    raise
```

Panel 2/3: code_reality, reproducer. Suggested direction: add a test where the handler raises `httpx2.ReadTimeout`, `failure_threshold=2`, asserting two such requests open the circuit; mirror on the sync side.

#### `architecture/client.md` attributes the `httpx2.Client.send` call to `Client.send` instead of `Client._terminal`
*(accuracy / architecture_docs — verified)*

`architecture/client.md:7`

The doc says "`Client.send` calls `httpx2.Client.send`, `AsyncClient.send` calls `httpx2.AsyncClient.send`." But `Client.send` calls `self._dispatch` (the composed middleware chain); it is `Client._terminal` that calls `self._httpx2_client.send`. The statement misattributes the terminal httpx2 call to the public `.send()`.

```
The same terminal lifecycle holds in both worlds — `Client.send` calls `httpx2.Client.send`,
`AsyncClient.send` calls `httpx2.AsyncClient.send`.
```

Panel 2/3: code_reality, spec_grounded. Suggested direction: attribute the `httpx2` send to `_terminal` and note that `.send()` enters the chain first.

### Nits

#### `full_jitter_delay` raises `OverflowError` for `attempt_index >= 1024` despite a docstring claiming saturation to `inf`
*(correctness — verified)*

`src/httpware/middleware/resilience/_backoff.py:25`

The docstring claims `2.0 ** attempt_index` "saturates to `math.inf`" for `attempt_index >= 1024` so `min` clamps to `max_delay`; in fact Python's float `**` raises `OverflowError` at `2.0 ** 1024`, so the clamp never fires and the call crashes. Reachable only when `max_attempts >= 1026` with every attempt failing — practically unreachable, but the docstring is factually wrong.

```python
ceiling = min(max_delay, base_delay * (2.0**attempt_index))
return _random_uniform(0.0, ceiling)
```

Panel 2/3: code_reality, reproducer. Suggested direction: correct the docstring, and clamp `attempt_index` (or wrap the exponentiation) so the documented saturation behavior actually holds.

#### `_is_streaming_body_async` does not detect sync iterables, while `_is_streaming_body_sync` does
*(correctness — verified)*

`src/httpware/_internal/status.py:32`

The async detector only checks `__aiter__`; the sync detector excludes replayable types then checks `__iter__`. A sync generator passed to `AsyncClient` is not marked non-replayable, so `AsyncRetry`'s replay guard is absent — correctness is preserved only because httpx2 itself raises a `RuntimeError` for sync bodies on an async client. The async invariant rests on an undocumented httpx2 detail.

```python
def _is_streaming_body_async(value: object) -> bool:
    ...
    return hasattr(value, "__aiter__")


def _is_streaming_body_sync(value: object) -> bool:
    ...
    return hasattr(value, "__iter__")
```

Panel 2/2: code_reality, code_reality. Suggested direction: document the reliance on httpx2's sync-on-async guard, or symmetrize the async detector to also mark sync iterables non-replayable.

#### `_strip_userinfo` produces a malformed `http:///path` URL when the netloc has credentials but no hostname
*(correctness — verified)*

`src/httpware/errors.py:29`

For `http://user:pass@/path`, `parts.hostname` is `None`, so `netloc` becomes `''` and `urlunsplit` yields the triple-slash `http:///path`. Credentials are still stripped (no security regression), but the sanitized URL in error messages and `__repr__` is malformed — and these are exactly the URLs the function exists to sanitize.

```python
hostname = parts.hostname or ""
...
netloc = hostname
if parts.port is not None:
    netloc = f"{netloc}:{parts.port}"
return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
```

Panel 2/3: code_reality, reproducer. Suggested direction: when hostname is empty, preserve the original (already credential-free) authority shape rather than emitting a triple-slash URL.

#### `errors.py` module docstring attributes the auto-raise rule to `AsyncClient` only, omitting three other raise sites
*(correctness / architecture_docs — verified)*

`src/httpware/errors.py:3`

The docstring says "Auto-raise rule lives at AsyncClient's internal terminal." There are four raise sites: `AsyncClient._terminal`, `Client._terminal`, `AsyncClient.stream()`, and `Client.stream()`. A reader consulting it to find where status errors originate would miss three of four.

```
Auto-raise rule lives at AsyncClient's internal terminal (see client.py).
```

Panel 2/3: code_reality, reproducer. Suggested direction: list all four raise sites (or say "both clients' terminals and both `stream()` methods").

#### `trust_env=True` by default — httpware silently honors `HTTP_PROXY`/`HTTPS_PROXY`
*(inherited-httpx2-surface / security — verified)*

`src/httpware/client.py:130`

When httpware builds its own httpx2 client it does not set `trust_env=False`, so httpx2's default reads proxy env vars and routes traffic accordingly. In a compromised environment this can silently route all traffic through an attacker proxy; callers injecting their own `httpx2_client` can disable it, but there is no httpware-level control or doc callout.

```python
self._httpx2_client = httpx2.AsyncClient(**kwargs)
```

Panel 2/2: code_reality, code_reality. Suggested direction: add a documentation callout that proxy/TLS env trust is inherited from httpx2 and how to opt out via injection.

#### `decoders/msgspec.py` `_contains_custom_type` has unguarded runtime `msgspec.*` references that would `NameError` if called when msgspec is absent
*(correctness — verified)*

`src/httpware/decoders/msgspec.py:29`

When `is_msgspec_installed` is False the module-level `import msgspec` is skipped, leaving `msgspec` undefined. `_contains_custom_type` then uses bare `msgspec.inspect.CustomType`/`Type` at runtime, so direct invocation (or post-load flag patching) raises `NameError` instead of a friendly `ImportError`. The `__init__` guard blocks normal instantiation but not direct calls to this module-level function.

```python
if isinstance(info, msgspec.inspect.CustomType):
    return True
...
if isinstance(value, msgspec.inspect.Type):
```

Panel 2/3: code_reality, reproducer. Suggested direction: gate `_contains_custom_type` behind the installed flag, or treat it as private-and-unreachable-without-the-extra and document that.

#### `test_threading_with_shared_budget.py`'s exact deposit-count assertion embeds a no-purge assumption as a comment
*(concurrency / tests — verified)*

`tests/test_threading_with_shared_budget.py:78`

The test asserts `len(budget._deposits) == expected_deposits`, relying on a comment ("TTL is 60.0 so no purge fires during the sub-second runtime") rather than an assertion. Shortening the TTL or a slow machine would trigger `_purge`, dropping the count and producing a false failure that masks correct behavior.

```python
expected_deposits = (_N_SYNC_THREADS * _N_OPS_PER_THREAD) + _N_ASYNC_TASKS
assert len(budget._deposits) == expected_deposits, f"expected {expected_deposits} deposits, got {len(budget._deposits)}"
```

Panel 2/3: code_reality, reproducer. Suggested direction: pin the injected clock so no real time elapses, making the no-purge assumption an enforced invariant rather than a fragile comment.

#### `ForbiddenError` (403), `ConflictError` (409), `UnprocessableEntityError` (422) are never instantiated in tests
*(test-coverage / tests — verified)*

`tests/test_errors.py:126`

`test_per_status_subclasses_construct` exercises only 6 of 9 `STATUS_TO_EXCEPTION` entries (400/401/404/429/500/503). The three omitted classes appear only in inheritance/table checks — none is constructed, none has `.response` or `str()` verified.

```python
@pytest.mark.parametrize(("status", "expected"), [
    (400, BadRequestError), (401, UnauthorizedError), (404, NotFoundError),
    (429, RateLimitedError), (500, InternalServerError), (503, ServiceUnavailableError),
])
def test_per_status_subclasses_construct(status: int, expected: type[StatusError]) -> None:
```

Panel 2/3: code_reality, reproducer. Suggested direction: add `(403, ForbiddenError)`, `(409, ConflictError)`, `(422, UnprocessableEntityError)` to the parametrize list.

#### No test for `full_jitter_delay` with `attempt_index >= 1024` — the documented overflow-safety path
*(coverage_gap / tests — verified)*

`tests/test_backoff.py:1`

The `_backoff.py` docstring specifically calls out the `attempt_index >= 1024` saturation edge, but tests cover only `attempt_index` 0 and 10. The documented (and, per the Nit above, actually broken) overflow path has no test, so a regression to integer exponentiation would go uncaught.

```
Uses ``2.0 **`` … so that ``attempt_index >= 1024`` saturates to ``math.inf`` and ``min`` clamps
to ``max_delay`` — ``2 ** 1024`` would raise ``OverflowError``
```

Panel 2/3: code_reality, reproducer. Suggested direction: add a large-`attempt_index` test asserting a finite clamped delay — which will also surface the `OverflowError` correctness Nit above.

#### `test_observability` no-active-span test has no assertion — passes for the wrong reason
*(mock_transport_fidelity / tests — verified)*

`tests/test_observability.py:85`

`test_emit_event_works_when_otel_installed_but_no_active_span` calls `_emit_event(...)` with no mock and no assertion ("the absence of an exception IS the assertion"). It would pass even if `_emit_event` became a no-op; it does not capture the log record to confirm the log-only fallback fired.

```python
def test_emit_event_works_when_otel_installed_but_no_active_span() -> None:
    ...
    # No assertion needed — the absence of an exception IS the assertion.
```

Panel 2/3: code_reality, reproducer. Suggested direction: assert via `caplog` that the expected log record (level + event name) was emitted.

#### No sync-overload typing test for `Client` — `test_client_typing.py` covers `AsyncClient` only
*(coverage_gap / tests — verified)*

`tests/test_client_typing.py:1`

All four overload tests (get/send × with/without model) exercise only `AsyncClient`. The sync `Client` has identical overload signatures and similar dispatch; a regression in sync overload resolution would not be caught.

```
"""Static-typing tests for AsyncClient overloads.
...
from httpware import AsyncClient
```

Panel 2/2: code_reality, code_reality. Suggested direction: add sync equivalents (`client.get(...) → httpx2.Response`, `client.get(..., response_model=_User) → _User`, and the `send` pair).

#### No sync counterpart to `test_status_error_raised_before_decoder_runs` / `test_async_decode_error_caught_by_client_error`
*(coverage_gap / tests — verified)*

`tests/test_client_response_model.py:63`

The async tests confirm a 4xx raises a `StatusError` (not `DecodeError`) before decode, and that `DecodeError` is-a `ClientError` at integration level. The sync client has the schema-mismatch/malformed-JSON tests but no sync mirror for the status-before-decode ordering or the `DecodeError`-is-`ClientError` integration check.

```python
async def test_status_error_raised_before_decoder_runs() -> None:
    ...
async def test_async_decode_error_caught_by_client_error() -> None:
    # (no sync counterpart for either)
```

Panel 2/3: code_reality, reproducer. Suggested direction: add `test_sync_status_error_raised_before_decoder_runs` and `test_sync_decode_error_caught_by_client_error`.

#### No test exercises the `httpx2.CookieConflict` mapping branch in `map_httpx2_exception`
*(coverage_gap / tests — verified)*

`tests/test_error_mapping_terminal.py:95`

`map_httpx2_exception` maps `(httpx2.InvalidURL, httpx2.CookieConflict) → TransportError`. Tests cover `InvalidURL` but not `CookieConflict`; a refactor that moved `CookieConflict` to `NetworkError` would go uncaught.

```python
if isinstance(exc, (httpx2.InvalidURL, httpx2.CookieConflict)):
    return TransportError(str(exc))
```

Panel 2/3: code_reality, reproducer. Suggested direction: add a test asserting a handler raising `httpx2.CookieConflict` surfaces `TransportError`, not `NetworkError`.

#### Docs use submodule import paths for symbols already in `httpware.__all__`, creating dual canonical paths
*(public_api / architecture_docs — verified)*

`docs/middleware.md:41`

Several examples import middleware symbols via the submodule path (`from httpware.middleware import AsyncNext`, `from httpware.errors import NetworkError`) even though all are in `httpware.__all__`. Affected: middleware.md lines 41/67/155 and recipes/phase-decorator-patterns.md lines 17/46/86/130. Two equally documented paths leave readers unsure which is canonical.

```
from httpware.middleware import async_before_request, async_after_response, async_on_error
from httpware.middleware import AsyncNext
from httpware.middleware import Next
```

Panel 2/3: code_reality, spec_grounded. Suggested direction: standardize docs on the root `from httpware import X` path for any symbol in the root `__all__`.

#### `architecture/extras.md` shows the pydantic constraint without its upper bound, mismatching `pyproject.toml`
*(accuracy / architecture_docs — verified)*

`architecture/extras.md:18`

The doc snippet shows `pydantic = ["pydantic>=2"]`, but `pyproject.toml` pins `pydantic = ["pydantic>=2.0,<3.0"]`. The illustrative snippet drops the `<3.0` ceiling.

```
pydantic = ["pydantic>=2"]
msgspec = ["msgspec>=0.18"]
```

Panel 2/3: code_reality, spec_grounded. Suggested direction: sync the snippet to the real constraint, or mark it explicitly as abbreviated.

## Negative results (verified correct)

Investigated and refuted (did not survive the panel), or invariants the finders checked and found holding:

- **CircuitBreaker `_consecutive_successes` across OPEN→HALF_OPEN→OPEN** — `_open()` unconditionally resets the counter on every path back to OPEN; existing `test_success_threshold_probe_failure_mid_streak_reopens` proves it. No accumulation bug.
- **`RecursionError` from deeply nested JSON (msgspec)** — refuted on a factual error: `RecursionError` *is* an `Exception` subclass, so the `except Exception` decode guard catches it and wraps it as `DecodeError`. No raw propagation.
- **`Retry-After` far-future date form** — the `retry_after > max_delay` guard caps it at the default `max_delay=5.0`; the only "sleep for years" path requires a self-inflicted `max_delay=1e12`. Behaves to spec.
- **`PydanticDecoder.decode` TypeError→fresh `TypeAdapter` per call** — unreachable: `can_decode()` already returns False for unhashable models, so decode is never dispatched for them. The fallback branch is dead in normal flow.
- **`StatusError.response` bare annotation / `__reduce__`** — the pickle round-trip uses `cls(response)`, which runs `__init__`; the AttributeError scenario requires a third-party lib to bypass `__init__`, not evidenced anywhere.
- **`AsyncBulkhead`/`AsyncCircuitBreaker` unguarded fast-path read of `self._loop`** — pointer reads are atomic on real architectures; the worst free-threaded outcome is a harmless extra lock acquisition corrected by the in-lock double-check. No torn-value bug.
- **`AsyncBulkhead` semaphore created before a running loop** — safe under Python 3.10+ (binds on first await); the proposed break requires deliberate private `_sem.acquire()` bypassing `__call__`/`_check_loop`. The semaphore also has its own cross-loop guard.
- **Async `test_bulkhead_props` `asyncio.sleep(0.005)` startup sync** — deterministic, not flaky: the event loop drains all ready holder callbacks (which have no `await` before `sem.acquire()`) before the timer fires.
- **`_raise_on_status_error` `>= 600` silent passthrough** — intentional (inline `noqa` documents the synthetic 600 upper bound); no realistic middleware synthesizes 6xx.
- **Sync vs async `BulkheadFullError` `__cause__` difference, and divergent test-timeout constants** — both raise `BulkheadFullError` with correct fields; `__cause__` is not a documented contract, and the larger sync test timeout is intentional jitter headroom.
- **Performance findings (uniformly refuted as micro-optimizations with no observable defect):** the empty-kwargs dict in `_request_with_body`; the `tuple(...)` allocation on the `MissingDecoderError` error path; the O(n) `_dispatch_decoder` linear scan (per the documented first-match contract); the per-request coroutine allocation in `chain.py` (composition is folded once at construction); the in-lock `int(...)` floor and the `{**attributes, ...}` copy in `_emit_event` (the copy is deliberate to avoid mutating the OTel `attributes` dict); the double-checked-locking `_check_loop`; the sync CircuitBreaker's two lock round-trips per request (the documented thread-safety mechanism); `dir(info)` in `_contains_custom_type` (cached, compact node types). One finder's "floor + `self._now()` inside the lock" claim was factually wrong — `self._now()` is sampled before the lock.
- **Sync/async duplication, no divergence yet (maintainability, not bugs):** `_httpx2_exception_mapper` vs `_sync`; `_dispatch_decoder` in both clients; the send/`send_with_response` decode-and-wrap block ×4; the `_request_with_body` kwargs block; `_check_loop` in bulkhead vs circuit_breaker; `can_decode` memoization in both decoders; the `_owns_client` lifecycle guard ×4; the `__init__` httpx2-construction/conflict-dict block; the `AsyncRetry`/`Retry` bodies (the differing AssertionError class-name prefixes are correct and the guards are `# pragma: no cover` unreachable). None produces wrong output today.
- **`_reconstruct_*` pickle helpers** — all five non-status reconstructors and their `__reduce__` methods are consistently shaped; `MissingDecoderError` matches its siblings. No inconsistency.
- **`msgspec.py` module-level conditional import "not truly lazy"** — refuted: import caching means the conditional fires once on first import, not per `AsyncClient()`; the docstring makes no lazy-import promise.
- **Several "missing sync property test" parity gaps** (`test_retry_sync_props.py`, sync CircuitBreaker/Retry props, sync `test_error_mapping_terminal`) — real absences, but the sync wrappers delegate to the same shared state machines / mappers, so a mirror test would pass rather than expose a defect; treated as coverage observations, not confirmed bugs. (The one broad sync-terminal status-raising gap that *does* touch distinct fallback assertions was kept as the Medium above.)
- **`test_budget_props` "double-counts" / vacuous-zero** — no double-count exists; `permitted == expected_ceiling` is sound for non-zero ceilings; only the zero-ceiling example is vacuous.
- **Public-API guards** — `test_no_removed_symbols_leaked` is a "was-removed, don't re-add" regression denylist (correctly excludes never-exported `MsgspecDecoder`); the post-0.8.0 sync-rename names verifiably resolve to sync objects (`iscoroutinefunction` is False). `httpware.decoders.T` is a free method-level TypeVar, correctly absent from `__all__`.
- **`test_client_decoders_default.py` msgspec-only resolution** — already covered (the finder misread the file: `test_async_default_msgspec_only` / `test_sync_default_msgspec_only` exist).
- **`Retry(max_attempts=0)` validation untested** — false: both `test_retry.py` and `test_retry_sync.py` assert `ValueError` on `max_attempts=0`.
- **MockTransport sync-callable "fidelity" concern** — MockTransport's `handle_async_request` is itself async and supports async handlers; cancellation-in-flight is already covered by `test_cancellation_propagates_cleanly`.
- **`errors.md` `asyncio.wait_for` / `builtins.TimeoutError` wording** — correct: the doc describes the *catch* form user code uses, and `httpware.TimeoutError` does inherit from `builtins.TimeoutError`. Finder misread.
- **Optional-extras isolation / pydantic-missing test scoping** — the patch-flag tests do guard `MISSING_DEPENDENCY_MESSAGE` and the `__init__` `ImportError`; the uncovered cold-import path is degenerate. (The genuine doc/source asymmetry it gestures at is captured by the High + Medium pydantic findings.)
- **`httpware` not forwarding `verify`/`follow_redirects`/`cert`** — deliberate thin-wrapper design; unknown kwargs raise `TypeError` immediately (no silent misconfiguration), and injection is the documented escape hatch.
- **msgspec/opentelemetry version floors without ceilings** — dependency-hygiene notes, not reproducible bugs; no published release currently breaks the adapters.
- **`StatusError.__init__` / `_dispatch_decoder` missing-docstring observations** — `D1`/missing-docstring is explicitly ignored by project convention; the class docstring already states the `__init__` contract.

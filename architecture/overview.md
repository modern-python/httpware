# Overview

`httpware` is a thin opinionated wrapper around `httpx2`. It re-exports `httpx2.Request` and `httpx2.Response` as the public request/response surface and adds three things on top: typed response decoding (via a `ResponseDecoder` protocol; pydantic and msgspec are both opt-in extras), a middleware chain composed at client construction, and a status-keyed exception tree raised automatically on 4xx and 5xx.

`httpx2` is part of the public surface. Exposing `httpx2.Request`/`httpx2.Response` is the design — `httpware` does not own a full abstraction over the underlying HTTP client.

## Architectural invariants

These are non-negotiable, but **enforcement varies — do not assume CI will catch a violation.** Machine-checked: `print()` (ruff `T201`) and a blanket `# type: ignore` (ruff `PGH003`). Partially checked: the `httpx2._` ban — ruff `SLF001` flags private *attribute* access (`httpx2._foo`) but not a *used* private import (`from httpx2._internal import …`). Review-only: the future-import and global-logging bans, and `# type: ignore[<code>]` vs `# ty: ignore[<code>]`. The "why" exists so future contributors can judge edge cases instead of blindly following the rule.

- **No `httpx2._` private API.** *Why:* private symbols can change between patch releases. We accept the public-API surface as the contract. *Check:* `grep -rE 'httpx2\._' src/httpware/` should return zero matches — run in review; it is not wired into CI.
- **No `from __future__ import annotations`.** *Why:* Python 3.11+ floor. PEP 604/585 syntax is native; the future-import would only add noise and inconsistency.
- **No `print()`.** *Why:* ruff-enforced. Libraries log; they do not print to stdout. Stray prints leak into consumer applications.
- **No global logging config.** *Why:* `logging.basicConfig()` from a library mutates the consumer's logging tree. We only acquire `logging.getLogger("httpware")` or namespaced child loggers and let consumers configure handlers.
- **Type suppressions use `# ty: ignore[<rule>]`.** *Why:* this project uses `ty`, not `mypy`. `# type: ignore` is silently accepted by `ty` but ambiguous; `# ty: ignore[<rule>]` is checked and rule-specific.

## Module layout

```text
src/httpware/
├── __init__.py            # public exports (both worlds at top level)
├── py.typed
├── client.py              # Client (sync) + AsyncClient (async)
├── errors.py              # status-keyed exception tree (shared)
├── middleware/
│   ├── __init__.py        # Middleware + AsyncMiddleware, Next + AsyncNext, decorators
│   ├── chain.py           # compose + compose_async
│   └── resilience/
│       ├── __init__.py    # re-exports both worlds + RetryBudget
│       ├── bulkhead.py    # Bulkhead + AsyncBulkhead
│       ├── budget.py      # RetryBudget (thread-safe; shared)
│       ├── retry.py       # Retry + AsyncRetry
│       ├── timeout.py     # AsyncTimeout
│       ├── circuit_breaker.py  # CircuitBreaker + AsyncCircuitBreaker
│       ├── _backoff.py    # full-jitter helper (shared)
│       └── _event_loop_guard.py  # single-event-loop guard (shared: AsyncBulkhead + AsyncCircuitBreaker)
├── decoders/              # shared (ResponseDecoder + adapters)
└── _internal/
    ├── body_cap.py            # max_response_body_bytes: validate, read-capped (sync+async)
    ├── exception_mapping.py   # map_httpx2_exception + context-manager wrappers (shared)
    ├── import_checker.py      # is_*_installed flags
    ├── observability.py       # _emit_event
    └── status.py              # _raise_on_status_error, _is_streaming_body_*, STREAMING_BODY_MARKER
```

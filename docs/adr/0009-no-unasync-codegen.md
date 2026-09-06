# Sync/async parity is hand-maintained; no unasync codegen

**Decision:** `Client` and `AsyncClient` stay two hand-written classes. Generating one from the
other (unasync-style source transformation at build or lint time) is rejected.

The duplication is real and visible: two clients, two of each verb, two of each resilience
middleware. Codegen is the standard answer and it does not fit here. It buys a build step, a
generated file that is either committed and reviewable-but-lying or uncommitted and absent from
tracebacks, and a rule that every future contributor must learn before editing the one file that
is allowed to be edited — for a repo whose tooling is otherwise just `ruff`, `ty` and `pytest`.

It also aims at the wrong half of the cost. The duplication that hurts is logic, and each round of
extraction has removed it without codegen: `_RetryPolicy`, `_CircuitBreakerState`, the request
assembly helpers, `_read_capped`, `_event_loop_guard`, and the shared `RetryBudget` are each
written once and driven by both worlds. What remains duplicated is the `await`/non-`await` shell —
structurally different code that a transformer would have to be told about anyway, and where the
two worlds legitimately diverge (`AsyncTimeout` has no sync sibling; sync `Bulkhead` is a
`threading.Semaphore` and cannot share an instance with `AsyncBulkhead`).

Parity is instead enforced where a divergence would actually be silent:
`tests/test_client_parity.py` compares the two public surfaces name by name and parameter by
parameter.

**Revisit trigger:** shell duplication growing back to the point where a new feature means editing
two files with no shared logic object between them — i.e. an extraction that fails, not one that
has not been attempted.

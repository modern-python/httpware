---
summary: Closed 11 [deep-audit](audits/2026-06-14-deep-audit.md) test-quality findings: sync-terminal + CookieConflict coverage, the `StatusError.__init__` invariant, missing status constructions, sync mirrors, typing overloads, a deterministic bulkhead barrier, a pinned budget clock, an observability assertion, and the `TimeoutError` circuit trigger.
---

# Change: Deep-audit test-quality findings

**Lane:** test-only sweep; spec is the [2026-06-14 deep audit](../../../audits/2026-06-14-deep-audit.md).

## Goal

Close the confirmed test-quality findings: assertion gaps, missing coverage,
sync/async test parity, and two flaky/fragile tests. No production code changes.

## Findings

- **M3** — sync `Client._terminal` status-raising has no parallel suite (`test_error_mapping_terminal` is async-only).
- **L9** — `test_retry_props` docstring claims "retry interleaving" but is sequential → correct the description (concurrency is covered by `test_threading_with_shared_budget`).
- **L10** — `test_bulkhead_sync_props` uses a fixed `time.sleep(0.005)` → replace with a deterministic barrier.
- **L11** — no test asserts `StatusError` leaves don't override `__init__` → parametrized check over the nine leaves.
- **L12** — no test exercises `TimeoutError` tripping the CircuitBreaker (async + sync).
- **Nit7** — `test_threading_with_shared_budget` exact deposit count rests on a comment → pin the clock.
- **Nit8** — `ForbiddenError`/`ConflictError`/`UnprocessableEntityError` never constructed → add to the per-status parametrize.
- **Nit10** — `test_emit_event_works_when_otel_installed_but_no_active_span` has no assertion → assert via caplog.
- **Nit11** — no sync-overload typing test for `Client` → mirror `test_client_typing`.
- **Nit12** — no sync counterpart to status-before-decoder / DecodeError-is-ClientError.
- **Nit13** — no test for the `httpx2.CookieConflict → TransportError` mapping branch.

(Nit9 — large-`attempt_index` backoff test — already landed in PR #64.)

## Verification

- [ ] Each addition is TDD-meaningful (asserts the property, not a vacuous pass).
- [ ] L10/Nit7 are deterministic (no real sleeps / wall-clock assumptions).
- [ ] `just test` 100% coverage; `just lint` clean.

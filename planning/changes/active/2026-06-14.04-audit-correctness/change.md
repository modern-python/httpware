---
status: draft
date: 2026-06-14
slug: audit-correctness
supersedes: null
superseded_by: null
pr: null
outcome: null
---

# Change: Deep-audit correctness + public-API fixes

**Lane:** full-ish, but the spec is the [2026-06-14 deep audit](../../../audits/2026-06-14-deep-audit.md)
(each finding carries root cause + suggested direction), so this bundle is a
plan-light TDD sweep of the confirmed code-level findings.

## Goal

Close the confirmed **correctness** and **public-API** findings from the deep
audit that #62/#63 did not already cover.

## Fixes

| # | Finding | File | Fix |
|---|---------|------|-----|
| L1 | RetryBudget token withdrawn before `Retry-After > max_delay` give-up | `retry.py` | evaluate the give-up guard *before* `budget.try_withdraw()`, in both `AsyncRetry` and `Retry` |
| L3 | `_parse_retry_after` `OverflowError` on huge digit string crashes the loop | `retry.py` | broaden guard to `except (ValueError, OverflowError)` |
| Nit1 | `full_jitter_delay` raises `OverflowError` at `attempt_index >= 1024` despite docstring claiming saturation | `_backoff.py` | clamp the exponent (or guard the `**`) so the documented `inf`-saturation/`max_delay` clamp actually holds; fix the docstring to match |
| Nit3 | `_strip_userinfo` emits malformed `http:///path` when authority has creds but no host | `_internal/redaction.py` | when hostname is empty, preserve the original credential-free authority shape instead of a triple-slash URL |
| Nit6 | `_contains_custom_type` uses bare `msgspec.*` at runtime → `NameError` if msgspec absent | `decoders/msgspec.py` | gate behind `is_msgspec_installed` (raise the friendly `ImportError`) so a direct call without the extra fails cleanly |
| Nit2 | `_is_streaming_body_async` doesn't mark sync iterables non-replayable (async invariant rests on an undocumented httpx2 detail) | `_internal/status.py` | symmetrize the async detector to also treat sync iterables as streaming bodies, so the replay guard is explicit rather than relying on httpx2 |
| L2 | `RetryBudget` docstring claims "asyncio-safe" without the blocking caveat | `resilience/budget.py` | qualify the docstring: the `threading.Lock` is correctness-safe but can briefly block the loop thread when shared sync↔async |
| L8 | `middleware/__init__.py` has no `__all__`, leaking 9+ star-import symbols | `middleware/__init__.py` | add an explicit `__all__` of the ten public names (matches sibling subpackages) |

## Verification

- [ ] Each fix lands TDD-first (failing test → fix → green); reproducers from the audit drive the tests.
- [ ] Sync/async parity for L1 (both `Retry` and `AsyncRetry`).
- [ ] `just test` — 100% coverage; `just lint` — clean.
- [ ] Grep guard: no new `httpx2._`.

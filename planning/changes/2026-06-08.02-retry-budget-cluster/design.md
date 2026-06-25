---
summary: Shipped 0.8.3 — 7 RetryBudget findings
---

# Spec: Retry/Budget cluster — close 7 audit findings (0.8.3)

**Date:** 2026-06-08
**Topic slug:** `retry-budget-cluster`
**Branch:** `fix/retry-budget-cluster`
**Target release:** `0.8.3` — patch (bug fixes, no API additions)
**Status:** drafted, awaiting user review

## Purpose

Close the seven audit-flagged retry-and-budget findings the [deep audit](../audit/2026-06-07-deep-audit.md) identified as the second cross-cutting theme — five `RetryBudget` cluster findings (one of which already shipped: the docs/resilience.md "Single-thread assumption" High landed in `a801572`) plus two adjacent retry-surface nits the user opted in for this PR. The remaining six findings are:

| # | Severity | File | Headline |
|---|---|---|---|
| 1 | Low | `src/httpware/middleware/resilience/retry.py:105` (async) + `:236` (sync) | `deposit()` fires per attempt instead of per original request |
| 2 | Low | `src/httpware/middleware/resilience/retry.py:189` (async) + `:320` (sync) | `Retry-After` silently capped to `max_delay` |
| 3 | Low | `src/httpware/middleware/resilience/budget.py:67` | Ceiling truncates rather than rounds (`int(...)`) |
| 4 | Low | `tests/test_budget_props.py:52` | Property test mirrors the same buggy formula |
| 5 | Nit | `tests/test_retry_props.py:60` | Property tests use a budget that cannot be exhausted |
| 6 | Nit | `src/httpware/middleware/resilience/retry.py:111` (async) + `:242`/`:249` (sync) | Streaming-body refusal note attached on wrong branch |
| 7 | Nit | `src/httpware/client.py:135` (async) + `:852` (sync) | `RuntimeError → TransportError` uses brittle substring match on "closed" |

Items 1, 2, 3 reinforce each other — Chunk 4's High noted that the code defects and the doc/test weaknesses form one cluster. Item 4 is the test that should have caught item 3 but didn't (uses the same buggy `int(...)` formula as production). Item 5 leaves the budget-exhaustion path unexercised by property tests.

## Non-goals

- **No API additions.** No new public classes, methods, or kwargs. No `respect_retry_after_ceiling=` config. No new exception types.
- **No semver minor bump.** This is a patch release; behavioral changes are bug fixes against documented contracts.
- **No documentation rewrites beyond what the fixes require.** Resilience.md gets minimal touch-ups for the new behaviors; no full doc refresh.
- **No follow-up audit findings deferred.** Every RetryBudget-flagged finding the user opted in for ships here. The remaining open Low/Nit items (sync `Bulkhead` Hypothesis-property gap, `test_expected_exports` one-directional, optional-extras edges, etc.) stay open and may ship in a later PR.
- **No `Retry` constructor signature changes.** `respect_retry_after: bool = True` stays — the new give-up behavior is unconditional when the header value exceeds `max_delay`.
- **No deprecation period.** Project is 0.x; user has stated no production deployments. Behavioral changes ship straight in.

## Architecture

### Branch + commit structure

Single feature branch `fix/retry-budget-cluster` off `main`. Sequenced commits, one per logical change:

1. `fix(budget): math.ceil for ceiling` — finding #3 + #4 paired (production fix + test rewrite that no longer mirrors the formula)
2. `fix(retry): hoist deposit() above the attempt loop` — finding #1 (both async + sync)
3. `feat(retry): give up when Retry-After exceeds max_delay` — finding #2 (both async + sync); behavioral change, includes docstring update + retry.md note
4. `test(retry): property test for budget-exhaustion path` — finding #5
5. `fix(retry): scope streaming-body refusal note correctly` — finding #6
6. `fix(client): map RuntimeError → TransportError via is_closed, not substring` — finding #7
7. `docs(release): draft 0.8.3 notes` — release notes file

Each commit includes the targeted tests that exercise the new behavior and references the audit finding in the message. After merge to `main`, the user tags `0.8.3` from the merge SHA following the project's bare-semver tag convention ([memory: release-0-1-0-shipped](../../.claude/projects/-Users-kevinsmith-src-pypi-httpware/memory/release_0_1_0_shipped.md)).

### PR + release notes

After all commits land on the branch:
- Open PR against `main` with title `fix(retry-budget): close 7 audit findings (0.8.3)`.
- PR body summarizes the 7 findings closed, behavioral impact, audit linkage.
- Release notes drafted at `planning/releases/0.8.3.md` — mirrors the 0.8.1 file's structure (TL;DR + the change-by-change breakdown). Two-section: "Fixes" (mostly invisible) + "Behavioral changes you should know about" (the deposit-hoist semantics shift + Retry-After give-up).

## Per-finding change list

### Finding #1 — `deposit()` per-request (lines 105, 236)

**Current behavior:** `self.budget.deposit()` lives inside the per-attempt `for attempt in range(self.max_attempts):` loop. A request that retries twice deposits three tokens but withdraws two; the budget's deposits-to-withdrawals ratio is inflated by ~`(attempts-1)/attempts`, letting through more retries than `percent_can_retry` should permit.

**Change:** hoist `self.budget.deposit()` to immediately precede the loop:

```python
self.budget.deposit()
for attempt in range(self.max_attempts):
    is_last = attempt + 1 >= self.max_attempts
    try:
        return await next(request)
    except StatusError as exc:
        ...
```

Same hoist in the sync class around line 236.

**Behavioral impact:** users with retry traffic see the budget refuse retries earlier than before. The exact effect depends on `percent_can_retry` and average retry depth — for `percent_can_retry=0.2` and average 1 retry per request, withdrawals/deposits goes from `(1)/(2) = 0.5` to `(1)/(1) = 1.0` per request, so the budget hits ceiling sooner. **This is the documented contract**; the existing behavior was the bug.

### Finding #2 — Retry-After exceeds max_delay → give up (lines 189, 320)

**Current behavior:** `delay = min(retry_after, self.max_delay)` silently clamps. If server says wait 120s and `max_delay=5.0`, the client retries after 5s — almost certainly hitting the same 503/429 and burning an attempt.

**Change:** when `retry_after > self.max_delay`, do NOT sleep-and-retry; instead, raise the last observed `StatusError` with a PEP 678 note explaining the give-up. Same in sync class. The non-retry-after path (jittered backoff, line 192-195 / 322-326) is unchanged.

New retry.py code shape (async):

```python
if retry_after is not None:
    if retry_after > self.max_delay:
        if last_exc is not None:
            last_exc.add_note(
                _RETRY_AFTER_EXCEEDS_MAX_DELAY_NOTE.format(
                    retry_after=retry_after, max_delay=self.max_delay,
                ),
            )
            raise last_exc
        # Should not reach here under normal flow (retry_after requires last_response)
        delay = self.max_delay
    else:
        delay = retry_after
else:
    delay = full_jitter_delay(...)
```

Add module constant near the existing constants:

```python
_RETRY_AFTER_EXCEEDS_MAX_DELAY_NOTE = (
    "httpware: Retry-After ({retry_after}s) exceeded max_delay ({max_delay}s); giving up"
)
```

**Behavioral impact:** the rare case where Retry-After > max_delay now surfaces as the original StatusError (e.g., `ServiceUnavailableError`) with an explanatory PEP 678 note rather than triggering a likely-failing retry. Users who want the old behavior should set `max_delay` high enough to accommodate the server's hints, or set `respect_retry_after=False`. Doc this in the existing `respect_retry_after` description in resilience.md.

### Finding #3 — Ceiling math.ceil (budget.py:67)

**Current behavior:** `ceiling = int(len(self._deposits) * self._percent_can_retry) + floor` — truncates. For `len(_deposits)=4` and `percent_can_retry=0.2`, the term is `int(0.8) = 0`; combined with a `floor=0` (no `min_retries_per_sec` floor), zero retries are permitted even though the configured percentage says the first retry should be allowed at 5 deposits.

**Change:**

```python
import math
# ...
ceiling = math.ceil(len(self._deposits) * self._percent_can_retry) + floor
```

Add `import math` to budget.py imports (currently lacks it).

**Behavioral impact:** users with `min_retries_per_sec=0.0` and low traffic now reach the configured percentage threshold one deposit sooner. Combined with finding #1's deposit hoist (deposits per-request not per-attempt), users see fewer retries than before in low-traffic scenarios — but the new ratio MATCHES the documented `percent_can_retry`. The previous behavior was strictly under-permissive (rounding down).

### Finding #4 — Budget property test independent ceiling (test_budget_props.py:52)

**Current test:**

```python
ceiling = int(deposits * percent) + floor
# ...
assert permitted <= ceiling
```

The test computes its expected bound with the same `int(...)` truncation as production. The Finding #3 fix changes production to `math.ceil`; if the test still uses `int(...)`, the assertion `permitted <= ceiling` would become tighter than reality (production permits 1 more in some cases) — false failures.

**Change:** compute the new (fixed) expected ceiling using `math.ceil`. Tighten the assertion to a range so the test discriminates between the two roundings:

```python
import math
expected_ceiling = math.ceil(deposits * percent) + floor
# permitted must equal the post-fix ceiling exactly (production now matches the test's math)
assert permitted == expected_ceiling
```

(`assert permitted == expected_ceiling` only works once production is also `math.ceil` — this commit pairs with finding #3 in commit 1 of the branch.)

### Finding #5 — Retry property suite that exhausts the budget (test_retry_props.py)

**Current state:** every `AsyncRetry` constructed in `test_retry_props.py` uses `RetryBudget(ttl=60.0, min_retries_per_sec=1000.0)` — floor of 60,000 retries permitted unconditionally. The budget can never be exhausted in the search space.

**Change:** add a new property test, **without removing the existing one**:

```python
@given(
    max_attempts=st.integers(min_value=2, max_value=4),
    deposits=st.integers(min_value=1, max_value=20),
    percent=st.floats(min_value=0.0, max_value=0.5, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=50, deadline=None)
async def test_budget_exhaustion_raises_retry_budget_exhausted_error(
    max_attempts: int,
    deposits: int,
    percent: float,
) -> None:
    """When the budget is exhausted, the next retry raises RetryBudgetExhaustedError."""
    budget = RetryBudget(ttl=60.0, min_retries_per_sec=0.0, percent_can_retry=percent)
    # Pre-deposit (does NOT permit withdrawal — only deposits count toward ceiling)
    for _ in range(deposits):
        budget.deposit()
    # Drain the permitted ceiling by raw withdrawals (mock the budget caller path)
    import math
    ceiling = math.ceil(deposits * percent)
    for _ in range(ceiling):
        assert budget.try_withdraw()
    # The next withdrawal must fail
    assert not budget.try_withdraw()
```

This is a property test on `RetryBudget` itself, not `AsyncRetry`. It complements the existing retry property tests without disturbing them.

### Finding #6 — Streaming-body refusal note (retry.py:111 + 242 + 249)

**Current:**

```python
except StatusError as exc:
    retryable_status = exc.response.status_code in self.retry_status_codes
    if not method_eligible or not retryable_status:
        if retryable_status and request.extensions.get(STREAMING_BODY_MARKER):
            exc.add_note(_STREAMING_BODY_REFUSAL_NOTE)
        raise
```

When `method_eligible=False` (e.g., POST not in `retry_methods`), the streaming-body note is added anyway — telling the user "stream cannot replay" when the real reason is method ineligibility.

**Change:** scope the note correctly. Only attach it when the streaming marker is the actual blocker (method IS eligible, status IS retryable, but body cannot replay). The cleanest version: drop the misleading branch entirely, and let the streaming-refusal happen at a single dedicated check earlier in the retry decision tree (the existing `STREAMING_BODY_REFUSAL_NOTE` site at the eligible-but-streaming path stays).

After investigation in the implementation phase: if no other site exists, add a check before the early-return that attaches the note ONLY when the streaming marker is the blocker. Concrete shape:

```python
except StatusError as exc:
    retryable_status = exc.response.status_code in self.retry_status_codes
    if not method_eligible or not retryable_status:
        raise
    if request.extensions.get(STREAMING_BODY_MARKER):
        exc.add_note(_STREAMING_BODY_REFUSAL_NOTE)
        raise
    last_exc = exc
    last_response = exc.response
```

Same pattern at the sync class lines 242 + 249 (the `NetworkError`/`TimeoutError` arm at 249 has the same shape).

### Finding #7 — `RuntimeError → TransportError` via `is_closed`

**Current (client.py:134-135 async, 852-853 sync):**

```python
except RuntimeError as exc:
    if "closed" in str(exc):
        raise TransportError(str(exc)) from exc
    raise
```

**Change:** check `self._httpx2_client.is_closed` instead of inspecting the exception message. `is_closed` is already used elsewhere in `client.py` (lines 774, 784, 870, 880 — proven public API).

```python
except RuntimeError as exc:
    if self._httpx2_client.is_closed:
        raise TransportError(str(exc)) from exc
    raise
```

**Behavioral impact:** any `RuntimeError` raised by httpx2 when the client is closed is now mapped to `TransportError` regardless of message wording. Any `RuntimeError` from other sources (caller mistakes, plugin bugs) propagates as-is — previously, if its message contained "closed", it would have been mis-classified.

## Behavioral impact summary

For the release-notes section:

- **Fewer retries permitted under load.** Finding #1 hoists `deposit()` to fire once per call, not once per attempt. Combined with finding #3's `math.ceil` ceiling, the budget now permits exactly the documented `percent_can_retry` rate. Users with finely-tuned percent settings should re-validate against their target retry rate.
- **`Retry-After > max_delay` now raises instead of silently retrying.** A `ServiceUnavailableError` (or whatever the underlying status error is) with a PEP 678 note `httpware: Retry-After (Ns) exceeded max_delay (Ms); giving up` replaces the previous wrong-but-not-broken retry. Set `max_delay` higher or `respect_retry_after=False` to opt out.
- **`RuntimeError → TransportError` mapping is now message-independent.** Driven by `httpx2.Client.is_closed`. Robust against httpx2 message rewording.
- **Streaming-body refusal note is now precisely targeted.** Only attached when streaming IS the blocker — not when the method was simply ineligible.

## Documentation

- `docs/resilience.md`: extend the `respect_retry_after` description with one sentence on the new give-up behavior when the header exceeds `max_delay`. No other doc changes.
- `planning/releases/0.8.3.md`: new file. Mirrors the 0.8.1 structure (title-line headline, "Patch release with..." TL;DR, per-finding sections, "Behavioral changes" callout).

## Verification

After each commit:

```bash
just lint-ci
uv run pytest -x --no-cov -q
```

Full test suite must pass after every commit.

Behavioral verification per finding:

- Finding #1: existing `test_retry_budget_threadsafety` + `test_threading_with_shared_budget` should continue to pass (they count deposits exactly); a new unit test in `test_retry.py` asserts `budget.deposit()` is called exactly once per `dispatch` call regardless of attempts.
- Finding #2: new tests in `test_retry.py` covering (a) `retry_after <= max_delay` → retries (existing behavior), (b) `retry_after > max_delay` → raises the underlying StatusError with the new PEP 678 note. Mirror in `test_retry_sync.py`.
- Finding #3: the rewritten `test_try_withdraw_never_exceeds_theoretical_bound` (now using `math.ceil`) is the primary regression guard.
- Finding #5: the new budget-exhaustion property test is the test for itself.
- Finding #6: a new test_retry.py case for "POST with streaming body that gets 503" — should raise `MethodNotAllowedRetryError` (or whatever — the existing StatusError class) WITHOUT the streaming-body note. Plus a case for "GET with streaming body that gets 503" — should raise WITH the note.
- Finding #7: a test injecting an `httpx2.MockTransport` that raises a custom `RuntimeError` whose message does NOT contain "closed" — should propagate as `RuntimeError`. Combined with one case where the underlying client is closed (forcing `is_closed=True`) — should map to `TransportError`.

## Open questions

None deferred. All behavioral choices are made (Retry-After: give up with PEP 678 note; deposit: hoist; ceiling: `math.ceil`).

## Acceptance criteria

1. Six fix commits + one release-notes commit land on branch `fix/retry-budget-cluster`.
2. `just lint-ci` and `uv run pytest` are both green after every commit and after the last.
3. New tests cover every finding's behavioral change.
4. `planning/releases/0.8.3.md` exists and structurally mirrors `planning/releases/0.8.1.md`.
5. PR opened against `main` with title `fix(retry-budget): close 7 audit findings (0.8.3)` and a body that summarizes each finding closed and the behavioral changes.
6. After user approval + merge + tag, [memory: release_0_8_3_shipped](../../.claude/projects/-Users-kevinsmith-src-pypi-httpware/memory/) is added.

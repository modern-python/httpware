---
status: shipped
date: 2026-06-08
slug: retry-budget-cluster
spec: retry-budget-cluster
pr: 34
---

# Retry/Budget Cluster Implementation Plan (0.8.3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land 7 commits on branch `fix/retry-budget-cluster` that close 7 audit findings (3 RetryBudget code fixes + 2 retry nits + 2 chunk-3 test rewrites), draft release notes for 0.8.3, and open a PR against `main`.

**Architecture:** TDD per task: write the failing test (or rewrite an existing test that pins the old buggy behavior), confirm it fails, fix production, confirm pass. Behavioral changes land in `src/httpware/middleware/resilience/{budget.py, retry.py}` and `src/httpware/client.py`; test rewrites land in `tests/test_budget_props.py`, `tests/test_retry_props.py`, `tests/test_retry.py`, `tests/test_retry_sync.py`, and `tests/test_client_lifecycle.py`. Release notes follow the `0.8.1` file shape.

**Tech Stack:** Python 3.11+, `httpx2`, `pytest`, `Hypothesis` (existing); `math` module is added to `budget.py`. No new dependencies.

---

## Spec reference

`planning/specs/2026-06-08-retry-budget-cluster-design.md`. Decisions locked there (not re-debated): 7 commits in order; deposit per-request hoist; ceiling `math.ceil`; Retry-After > max_delay raises underlying `StatusError` with PEP 678 note `httpware: Retry-After (Ns) exceeded max_delay (Ms); giving up`; streaming-note moves into the eligible-and-retryable branch only; `RuntimeError → TransportError` keyed on `self._httpx2_client.is_closed`.

## File structure

```
src/httpware/middleware/resilience/budget.py        # Task 1 (math.ceil)
src/httpware/middleware/resilience/retry.py         # Tasks 2, 3, 5 (async + sync classes)
src/httpware/client.py                              # Task 6
tests/test_budget_props.py                          # Task 1 (rewrite property)
tests/test_retry_props.py                           # Task 4 (new exhaustion test)
tests/test_retry.py                                 # Tasks 2, 3, 5 (async)
tests/test_retry_sync.py                            # Tasks 2, 3, 5 (sync mirror)
tests/test_client_lifecycle.py                      # Task 6 (closed-client mapping)
tests/test_client_sync.py                           # Task 6 (sync mirror)
docs/resilience.md                                  # Task 3 (one-sentence note)
planning/releases/0.8.3.md                          # Task 7 (new file)
```

No new source files. No file deletions. Branch is already created (`fix/retry-budget-cluster`); spec already committed.

## Pre-existing test that will break in Task 3 (heads-up)

`tests/test_retry.py:289` — `test_retry_after_capped_at_max_delay()` currently asserts the OLD silent-cap behavior (`sleeper.calls == [2.5]`). Task 3 REWRITES this test in place to assert the new give-up behavior. No mirror exists in `test_retry_sync.py`; Task 3 adds one.

---

## Task 1: Ceiling uses `math.ceil`; budget property test no longer mirrors the formula

**Files:**
- Modify: `src/httpware/middleware/resilience/budget.py`
- Modify: `tests/test_budget_props.py`

Closes audit findings #3 (`budget.py:67`) + #4 (`test_budget_props.py:52`).

- [ ] **Step 1: Rewrite the property test to no longer use `int(...)`**

Edit `tests/test_budget_props.py`. Add `import math` to imports. Replace the `test_try_withdraw_never_exceeds_theoretical_bound` body so the expected ceiling uses `math.ceil` and the assertion equates `permitted` with that value (after this commit lands, the test holds exactly — both the test and production use the same rounding).

Replace lines 52-69 (the body of the test starting `def test_try_withdraw_never_exceeds_theoretical_bound`) with:

```python
def test_try_withdraw_never_exceeds_theoretical_bound(
    ttl: float,
    min_rps: float,
    percent: float,
    deposits: int,
) -> None:
    clock = _Clock()
    budget = _budget(ttl=ttl, min_retries_per_sec=min_rps, percent_can_retry=percent, now=clock.now)
    for _ in range(deposits):
        budget.deposit()
    floor = int(min_rps * ttl)
    expected_ceiling = math.ceil(deposits * percent) + floor
    permitted = 0
    # Try up to expected_ceiling + 10 times to confirm the cap holds exactly.
    for _ in range(expected_ceiling + 10):
        if budget.try_withdraw():
            permitted += 1
    assert permitted == expected_ceiling
```

Also add `import math` to the imports block at the top:

```python
import math
from collections.abc import Callable
```

(keep `from collections.abc import Callable` exactly where it is; `import math` goes immediately above it.)

- [ ] **Step 2: Run the rewritten property test — confirm it FAILS against current production**

```bash
uv run pytest tests/test_budget_props.py::test_try_withdraw_never_exceeds_theoretical_bound -x --no-cov -q
```

Expected: FAIL. The new test asserts `permitted == math.ceil(deposits * percent) + floor`; production still uses `int(...)` so for fractional percent values, `permitted` will be one less than `expected_ceiling` for some Hypothesis-generated inputs. The Hypothesis-found counterexample should look like `deposits=1, percent=0.2` or similar — `math.ceil(0.2)=1` but `int(0.2)=0`, so production permits 0 and the test expects 1.

- [ ] **Step 3: Fix production — use `math.ceil` in the ceiling computation**

Edit `src/httpware/middleware/resilience/budget.py`. Add `import math` to imports (currently absent). Replace line 67's `ceiling = int(len(self._deposits) * self._percent_can_retry) + floor` with `math.ceil`.

Add to imports (after `import threading`):

```python
import math
import threading
import time
```

(Order: keep alphabetical — `math` before `threading`.)

Replace `try_withdraw`'s ceiling line. The full method should read:

```python
def try_withdraw(self) -> bool:
    """Atomically attempt to spend one retry token.

    Returns True if a retry is permitted, False if the budget is exhausted.
    Never blocks.
    """
    now = self._now()
    with self._lock:
        self._purge(now)
        floor = int(self._min_retries_per_sec * self._ttl)
        ceiling = math.ceil(len(self._deposits) * self._percent_can_retry) + floor
        if len(self._withdrawn) >= ceiling:
            return False
        self._withdrawn.append(now)
        return True
```

(Only the `ceiling = ...` line changes. Floor stays `int(...)` because `min_retries_per_sec * ttl` represents an absolute floor — fractional rounding doesn't apply.)

- [ ] **Step 4: Re-run the property test — confirm it PASSES**

```bash
uv run pytest tests/test_budget_props.py -x --no-cov -q
```

Expected: all property tests pass (the rewritten one + the two unchanged ones).

- [ ] **Step 5: Run the full retry test suite**

```bash
uv run pytest tests/test_retry.py tests/test_retry_sync.py tests/test_budget.py tests/test_budget_props.py tests/test_retry_props.py -x --no-cov -q
```

Expected: all pass. `test_budget.py` is non-property tests; verify nothing else regressed.

- [ ] **Step 6: Lint**

```bash
just lint-ci
```

Expected: green.

- [ ] **Step 7: Commit**

```bash
git add src/httpware/middleware/resilience/budget.py tests/test_budget_props.py
git commit -m "$(cat <<'EOF'
fix(budget): ceiling uses math.ceil, not int truncation

`RetryBudget.try_withdraw`'s ceiling computed `int(deposits * percent) + floor`,
truncating so 4 deposits at percent_can_retry=0.2 yielded `int(0.8) = 0` —
the configured percentage was never reached at deposit counts below
`1/percent_can_retry`. Replace with math.ceil so the threshold is hit at the
first deposit-count where it is mathematically expressible.

The Hypothesis property test mirrored the same int() formula, so it could
not detect the off-by-one. Rewrite it to use math.ceil for the expected
ceiling and tighten `permitted <= ceiling` to `permitted == ceiling` so it
discriminates between the two roundings going forward.

Closes audit Low findings (budget.py:67 truncation, test_budget_props.py:52
formula-mirror) from planning/audit/2026-06-07-deep-audit.md.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `deposit()` hoists to per-request (one call per `__call__`, not per attempt)

**Files:**
- Modify: `src/httpware/middleware/resilience/retry.py` (both `AsyncRetry.__call__` and `Retry.__call__`)
- Modify: `tests/test_retry.py` (new assertion test)
- Modify: `tests/test_retry_sync.py` (sync mirror)

Closes audit finding #1.

- [ ] **Step 1: Write the failing test for `AsyncRetry`**

Edit `tests/test_retry.py`. Append (after the existing tests, before any `__main__` block — there isn't one; just append to file):

```python
class _CountingBudget(RetryBudget):
    """RetryBudget that counts deposit() calls."""

    def __init__(self) -> None:
        super().__init__()
        self.deposit_calls = 0

    def deposit(self) -> None:
        self.deposit_calls += 1
        super().deposit()


async def test_deposit_fires_once_per_call_not_per_attempt() -> None:
    """deposit() must be called exactly once per AsyncRetry.__call__, regardless of attempts."""
    sleeper = _SleepRecorder()
    handler = _ResponseSequence([HTTPStatus.SERVICE_UNAVAILABLE, HTTPStatus.SERVICE_UNAVAILABLE, HTTPStatus.OK])
    budget = _CountingBudget()
    client = _client(
        handler,
        retry=AsyncRetry(_sleep=sleeper, base_delay=0.001, max_delay=0.002, max_attempts=3, budget=budget),
    )
    response = await client.get("https://example.test/x")
    assert response.status_code == HTTPStatus.OK
    assert handler.calls == 3
    assert budget.deposit_calls == 1, f"expected 1 deposit per request, got {budget.deposit_calls}"
```

- [ ] **Step 2: Run the test — confirm it FAILS (current production deposits 3 times)**

```bash
uv run pytest tests/test_retry.py::test_deposit_fires_once_per_call_not_per_attempt -x --no-cov -q
```

Expected: FAIL with `AssertionError: expected 1 deposit per request, got 3`.

- [ ] **Step 3: Fix `AsyncRetry.__call__` — hoist `self.budget.deposit()` above the loop**

Edit `src/httpware/middleware/resilience/retry.py`. In `AsyncRetry.__call__` (around line 97-105), move the deposit() call above the `for attempt in range(...)` loop. The change:

old_string:
```python
        for attempt in range(self.max_attempts):
            is_last = attempt + 1 >= self.max_attempts
            self.budget.deposit()
            try:
                return await next(request)
```

new_string:
```python
        self.budget.deposit()
        for attempt in range(self.max_attempts):
            is_last = attempt + 1 >= self.max_attempts
            try:
                return await next(request)
```

- [ ] **Step 4: Run the test — confirm it PASSES**

```bash
uv run pytest tests/test_retry.py::test_deposit_fires_once_per_call_not_per_attempt -x --no-cov -q
```

Expected: PASS.

- [ ] **Step 5: Add the sync mirror to `tests/test_retry_sync.py`**

Read `tests/test_retry_sync.py` to confirm the import block + helper pattern (likely uses `Retry` instead of `AsyncRetry` and synchronous test functions). Append the sync equivalent:

```python
class _CountingBudget(RetryBudget):
    """RetryBudget that counts deposit() calls."""

    def __init__(self) -> None:
        super().__init__()
        self.deposit_calls = 0

    def deposit(self) -> None:
        self.deposit_calls += 1
        super().deposit()


def test_deposit_fires_once_per_call_not_per_attempt() -> None:
    """deposit() must be called exactly once per Retry.__call__, regardless of attempts."""
    sleeper = _SleepRecorder()  # sync sleep recorder; use whatever name the file already has
    handler = _ResponseSequence([HTTPStatus.SERVICE_UNAVAILABLE, HTTPStatus.SERVICE_UNAVAILABLE, HTTPStatus.OK])
    budget = _CountingBudget()
    client = _client(
        handler,
        retry=Retry(_sleep=sleeper, base_delay=0.001, max_delay=0.002, max_attempts=3, budget=budget),
    )
    response = client.get("https://example.test/x")
    assert response.status_code == HTTPStatus.OK
    assert handler.calls == 3
    assert budget.deposit_calls == 1, f"expected 1 deposit per request, got {budget.deposit_calls}"
```

Read the file first; if the sleeper class or helper has a different name (e.g. `_SleepRecorderSync`), use the existing name. The shape is the same as the async test.

- [ ] **Step 6: Run the sync test — confirm it FAILS**

```bash
uv run pytest tests/test_retry_sync.py::test_deposit_fires_once_per_call_not_per_attempt -x --no-cov -q
```

Expected: FAIL with the same `expected 1 ... got 3`.

- [ ] **Step 7: Fix `Retry.__call__` (the sync class) — same hoist**

In `src/httpware/middleware/resilience/retry.py` around line 234-236:

old_string:
```python
        for attempt in range(self.max_attempts):
            is_last = attempt + 1 >= self.max_attempts
            self.budget.deposit()
            try:
                return next(request)
```

new_string:
```python
        self.budget.deposit()
        for attempt in range(self.max_attempts):
            is_last = attempt + 1 >= self.max_attempts
            try:
                return next(request)
```

- [ ] **Step 8: Run sync test — PASS**

```bash
uv run pytest tests/test_retry_sync.py::test_deposit_fires_once_per_call_not_per_attempt -x --no-cov -q
```

Expected: PASS.

- [ ] **Step 9: Run full retry + budget test suites**

```bash
uv run pytest tests/test_retry.py tests/test_retry_sync.py tests/test_budget.py tests/test_budget_props.py tests/test_retry_props.py tests/test_retry_budget_threadsafety.py tests/test_threading_with_shared_budget.py -x --no-cov -q
```

Expected: all pass. The threading tests count deposits; verify they still hold (they call dispatch directly, not through retry — so they count exactly).

- [ ] **Step 10: Lint + commit**

```bash
just lint-ci
git add src/httpware/middleware/resilience/retry.py tests/test_retry.py tests/test_retry_sync.py
git commit -m "$(cat <<'EOF'
fix(retry): hoist deposit() to per-request, not per-attempt

`AsyncRetry.__call__` and `Retry.__call__` deposited a token inside the
per-attempt for-loop. A request that retried twice contributed three
deposits and two withdrawals — inflating the budget's deposits-to-
withdrawals ratio by `(attempts-1)/attempts` and letting through more
retries than `percent_can_retry` should permit.

Move `self.budget.deposit()` immediately above the loop in both worlds so
the Finagle contract holds: deposits count original requests; withdrawals
count retries.

Behavioral impact: tighter retry pacing under load — users with active
retry traffic see the budget refuse retries earlier than before. This is
the documented contract; the previous behavior was the bug.

Closes audit Low finding (retry.py:105 + :236) from
planning/audit/2026-06-07-deep-audit.md.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `Retry-After > max_delay` raises with PEP 678 note (give up, don't silently cap)

**Files:**
- Modify: `src/httpware/middleware/resilience/retry.py` (constants + AsyncRetry + Retry)
- Modify: `tests/test_retry.py` (REWRITE existing capped test + ADD new give-up test)
- Modify: `tests/test_retry_sync.py` (ADD sync mirror tests)
- Modify: `docs/resilience.md` (extend `respect_retry_after` description)

Closes audit finding #2.

- [ ] **Step 1: REWRITE the existing `test_retry_after_capped_at_max_delay` (around line 289 of tests/test_retry.py) — it currently asserts the old silent-cap behavior**

Replace the test wholesale:

```python
async def test_retry_after_exceeding_max_delay_raises_with_note() -> None:
    """When Retry-After > max_delay, give up — don't silently retry after a too-short delay."""
    sleeper = _SleepRecorder()
    handler = _ResponseSequenceWithHeaders(
        [
            (HTTPStatus.SERVICE_UNAVAILABLE, {"Retry-After": "9999"}),
            (HTTPStatus.OK, {}),  # never reached
        ]
    )
    client = _client(handler, retry=AsyncRetry(_sleep=sleeper, base_delay=0.01, max_delay=2.5))
    with pytest.raises(ServiceUnavailableError) as exc_info:
        await client.get("https://example.test/x")
    notes = getattr(exc_info.value, "__notes__", [])
    assert any("Retry-After" in n and "exceeded max_delay" in n for n in notes), (
        f"expected give-up note in __notes__; got {notes!r}"
    )
    assert sleeper.calls == []  # no sleep before give-up
    assert handler.calls == 1   # original attempt only; no retry
```

- [ ] **Step 2: ADD a new test confirming `Retry-After <= max_delay` STILL retries**

(This duplicates the existing `test_retry_after_seconds_overrides_backoff` but specifically pins the equal-to-max-delay edge case so the give-up boundary is asserted both ways.)

Add immediately after the rewritten test:

```python
async def test_retry_after_equal_to_max_delay_still_retries() -> None:
    """Boundary: Retry-After exactly equal to max_delay sleeps and retries — does not give up."""
    sleeper = _SleepRecorder()
    handler = _ResponseSequenceWithHeaders(
        [
            (HTTPStatus.SERVICE_UNAVAILABLE, {"Retry-After": "2"}),
            (HTTPStatus.OK, {}),
        ]
    )
    client = _client(handler, retry=AsyncRetry(_sleep=sleeper, base_delay=0.01, max_delay=2.0))
    await client.get("https://example.test/x")
    assert sleeper.calls == [2.0]
    assert handler.calls == 2
```

- [ ] **Step 3: Run the rewritten test — confirm it FAILS (current production sleeps and retries)**

```bash
uv run pytest tests/test_retry.py::test_retry_after_exceeding_max_delay_raises_with_note -x --no-cov -q
```

Expected: FAIL — current production silently caps Retry-After at max_delay and retries; `ServiceUnavailableError` is not raised because the second response is 200.

- [ ] **Step 4: Add the module constant + give-up logic to `AsyncRetry`**

Edit `src/httpware/middleware/resilience/retry.py`. Add the constant near line 49 (next to `_STREAMING_BODY_REFUSAL_NOTE`):

```python
_MAX_ATTEMPTS_INVALID = "max_attempts must be >= 1"
_STREAMING_BODY_REFUSAL_NOTE = "httpware: not retrying — request body is a stream that cannot replay across attempts"
_RETRY_AFTER_EXCEEDS_MAX_DELAY_NOTE = (
    "httpware: Retry-After ({retry_after}s) exceeded max_delay ({max_delay}s); giving up"
)
```

Replace the AsyncRetry's `if retry_after is not None: delay = min(retry_after, self.max_delay)` block (around line 188-189) with the give-up branch:

old_string:
```python
            if retry_after is not None:
                delay = min(retry_after, self.max_delay)
            else:
                delay = full_jitter_delay(
                    attempt,
                    base_delay=self.base_delay,
                    max_delay=self.max_delay,
                )
            await self._sleep(delay)
```

new_string:
```python
            if retry_after is not None and retry_after > self.max_delay:
                if last_exc is None:  # pragma: no cover — retry_after requires last_response which requires last_exc
                    msg = "AsyncRetry: retry_after path reached with no last_exc"
                    raise AssertionError(msg)
                last_exc.add_note(
                    _RETRY_AFTER_EXCEEDS_MAX_DELAY_NOTE.format(
                        retry_after=retry_after, max_delay=self.max_delay,
                    ),
                )
                raise last_exc
            if retry_after is not None:
                delay = retry_after
            else:
                delay = full_jitter_delay(
                    attempt,
                    base_delay=self.base_delay,
                    max_delay=self.max_delay,
                )
            await self._sleep(delay)
```

- [ ] **Step 5: Run the give-up test — confirm it PASSES**

```bash
uv run pytest tests/test_retry.py::test_retry_after_exceeding_max_delay_raises_with_note tests/test_retry.py::test_retry_after_equal_to_max_delay_still_retries -x --no-cov -q
```

Expected: both PASS.

- [ ] **Step 6: Run the full async retry suite — confirm no other test broke**

```bash
uv run pytest tests/test_retry.py -x --no-cov -q
```

Expected: all pass. (Notable existing tests to watch: `test_retry_after_seconds_overrides_backoff`, `test_retry_after_http_date_overrides_backoff`. Both use Retry-After values less than or equal to max_delay, so they should be unaffected.)

- [ ] **Step 7: Apply the SAME give-up logic to `Retry.__call__` (the sync class)**

In `src/httpware/middleware/resilience/retry.py` around lines 319-327:

old_string:
```python
            if retry_after is not None:
                delay = min(retry_after, self.max_delay)
            else:
                delay = full_jitter_delay(
                    attempt,
                    base_delay=self.base_delay,
                    max_delay=self.max_delay,
                )
            self._sleep(delay)
```

new_string:
```python
            if retry_after is not None and retry_after > self.max_delay:
                if last_exc is None:  # pragma: no cover — retry_after requires last_response which requires last_exc
                    msg = "Retry: retry_after path reached with no last_exc"
                    raise AssertionError(msg)
                last_exc.add_note(
                    _RETRY_AFTER_EXCEEDS_MAX_DELAY_NOTE.format(
                        retry_after=retry_after, max_delay=self.max_delay,
                    ),
                )
                raise last_exc
            if retry_after is not None:
                delay = retry_after
            else:
                delay = full_jitter_delay(
                    attempt,
                    base_delay=self.base_delay,
                    max_delay=self.max_delay,
                )
            self._sleep(delay)
```

- [ ] **Step 8: Add the sync test mirrors to `tests/test_retry_sync.py`**

Append (use whichever helper-class names the sync file uses; structure matches the async tests):

```python
def test_retry_after_exceeding_max_delay_raises_with_note() -> None:
    """When Retry-After > max_delay, give up — don't silently retry after a too-short delay."""
    sleeper = _SleepRecorder()
    handler = _ResponseSequenceWithHeaders(
        [
            (HTTPStatus.SERVICE_UNAVAILABLE, {"Retry-After": "9999"}),
            (HTTPStatus.OK, {}),
        ]
    )
    client = _client(handler, retry=Retry(_sleep=sleeper, base_delay=0.01, max_delay=2.5))
    with pytest.raises(ServiceUnavailableError) as exc_info:
        client.get("https://example.test/x")
    notes = getattr(exc_info.value, "__notes__", [])
    assert any("Retry-After" in n and "exceeded max_delay" in n for n in notes)
    assert sleeper.calls == []
    assert handler.calls == 1


def test_retry_after_equal_to_max_delay_still_retries() -> None:
    sleeper = _SleepRecorder()
    handler = _ResponseSequenceWithHeaders(
        [
            (HTTPStatus.SERVICE_UNAVAILABLE, {"Retry-After": "2"}),
            (HTTPStatus.OK, {}),
        ]
    )
    client = _client(handler, retry=Retry(_sleep=sleeper, base_delay=0.01, max_delay=2.0))
    client.get("https://example.test/x")
    assert sleeper.calls == [2.0]
    assert handler.calls == 2
```

Read `tests/test_retry_sync.py` first to confirm the import block already has `ServiceUnavailableError` and `Retry` and that `_ResponseSequenceWithHeaders` exists with the same shape. Add any missing imports.

- [ ] **Step 9: Run sync tests — both PASS**

```bash
uv run pytest tests/test_retry_sync.py::test_retry_after_exceeding_max_delay_raises_with_note tests/test_retry_sync.py::test_retry_after_equal_to_max_delay_still_retries -x --no-cov -q
```

Expected: both PASS.

- [ ] **Step 10: Update `docs/resilience.md` — extend the `respect_retry_after` row's description**

Find the parameter table for `AsyncRetry` (around the `| respect_retry_after | ... |` row, near line 24 — look for the row labeled `respect_retry_after`). The current cell reads roughly:

```
| `respect_retry_after` | `True` | When the response carries a `Retry-After` header on a retryable status, sleep for the header value (clamped to `max_delay`) instead of the jittered backoff. |
```

Replace it with:

```
| `respect_retry_after` | `True` | When the response carries a `Retry-After` header on a retryable status, sleep for the header value instead of the jittered backoff. If the header value exceeds `max_delay`, AsyncRetry gives up and re-raises the underlying `StatusError` with a PEP 678 note `httpware: Retry-After (Ns) exceeded max_delay (Ms); giving up`. Set `max_delay` higher (or `respect_retry_after=False`) to opt out. |
```

If the same row exists in the sync `Retry` parameter table further down the file, update it identically (substitute "AsyncRetry" → "Retry" where the text says it).

- [ ] **Step 11: Full retry + budget suite + lint**

```bash
uv run pytest tests/test_retry.py tests/test_retry_sync.py tests/test_budget.py tests/test_budget_props.py tests/test_retry_props.py -x --no-cov -q
just lint-ci
```

Expected: all green.

- [ ] **Step 12: Commit**

```bash
git add src/httpware/middleware/resilience/retry.py tests/test_retry.py tests/test_retry_sync.py docs/resilience.md
git commit -m "$(cat <<'EOF'
feat(retry): give up when Retry-After exceeds max_delay

Previously when `respect_retry_after=True` and the server sent
`Retry-After: 120` while the client had `max_delay=5`, AsyncRetry/Retry
silently clamped to 5s and retried — almost certainly hitting the same
503/429 and burning an attempt. The option name implied the header was
honored.

New behavior: when the header value exceeds max_delay, re-raise the last
observed StatusError with a PEP 678 note
`httpware: Retry-After (Ns) exceeded max_delay (Ms); giving up`. Same
treatment in both AsyncRetry and Retry. `respect_retry_after=False` and
raising `max_delay` to accommodate the header are the opt-outs.

Replaces the existing `test_retry_after_capped_at_max_delay` (which
pinned the old silent-cap) with two tests: the give-up assertion at
Retry-After > max_delay, and the boundary case at Retry-After == max_delay
which still retries. Sync mirrors added.

docs/resilience.md's respect_retry_after row describes the new give-up
behavior.

Closes audit Low finding (retry.py:189 + :320) from
planning/audit/2026-06-07-deep-audit.md.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Add property test for the budget-exhaustion path

**Files:**
- Modify: `tests/test_retry_props.py` (new test)

Closes audit Nit finding #5.

- [ ] **Step 1: Read the existing `test_retry_props.py` imports + helpers**

```bash
head -60 tests/test_retry_props.py
```

Confirm: `import math` is or isn't present; `RetryBudget` is imported. Add any missing imports in Step 2.

- [ ] **Step 2: Append the new property test**

At the end of `tests/test_retry_props.py`:

```python
@given(
    deposits=st.integers(min_value=1, max_value=20),
    percent=st.floats(
        min_value=0.0, max_value=0.5, allow_nan=False, allow_infinity=False,
    ),
)
@settings(max_examples=50, deadline=None)
def test_budget_exhaustion_is_reachable_and_deterministic(
    deposits: int,
    percent: float,
) -> None:
    """When floor=0 and a finite percent is set, the budget MUST refuse withdrawals after exactly ceiling permits."""
    import math

    budget = RetryBudget(ttl=60.0, min_retries_per_sec=0.0, percent_can_retry=percent)
    for _ in range(deposits):
        budget.deposit()
    expected_ceiling = math.ceil(deposits * percent)
    permitted = 0
    for _ in range(expected_ceiling):
        assert budget.try_withdraw(), f"budget refused early at permit {permitted}/{expected_ceiling}"
        permitted += 1
    # The (ceiling + 1)-th withdrawal MUST fail.
    assert not budget.try_withdraw()
```

If `import math` is missing at the top of the file, hoist it from the function to the module top. (Per the user's memory `user_dislikes_plc0415_noqa_in_tests`, top-level imports are preferred.) Make the change before committing.

- [ ] **Step 3: Run the new test**

```bash
uv run pytest tests/test_retry_props.py::test_budget_exhaustion_is_reachable_and_deterministic -x --no-cov -q
```

Expected: PASS. (Production already supports this path correctly via the math.ceil fix landed in Task 1.)

- [ ] **Step 4: Lint + commit**

```bash
just lint-ci
git add tests/test_retry_props.py
git commit -m "$(cat <<'EOF'
test(retry-props): property test for the budget-exhaustion path

The existing AsyncRetry property tests build budgets with
`min_retries_per_sec=1000.0` — floor of 60_000 retries permitted
unconditionally — so the budget-exhaustion path is never exercised by
Hypothesis. Add a focused property test on RetryBudget directly that
configures `min_retries_per_sec=0.0` and asserts: exactly ceiling
permits succeed, then the next one fails.

Pairs with the math.ceil fix in commit 1 of this branch — the same
ceiling formula is now the regression guard for both production and tests.

Closes audit Nit finding (test_retry_props.py:60) from
planning/audit/2026-06-07-deep-audit.md.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Streaming-body refusal note attached only when streaming IS the blocker

**Files:**
- Modify: `src/httpware/middleware/resilience/retry.py` (AsyncRetry + Retry)
- Modify: `tests/test_retry.py` (async)
- Modify: `tests/test_retry_sync.py` (sync mirror)

Closes audit Nit finding #6.

- [ ] **Step 1: Read the existing streaming-body test patterns**

```bash
grep -n 'STREAMING\|streaming\|_STREAMING' tests/test_retry.py | head -20
```

Confirm helper for marking a request as streaming exists (e.g. `_make_streaming_request`). The test will need it.

- [ ] **Step 2: Write the failing test — POST with streaming body on a 503 should raise WITHOUT the streaming-body note (since the blocker is method ineligibility, not streaming)**

Append to `tests/test_retry.py`:

```python
async def test_method_ineligible_with_streaming_body_does_not_attach_streaming_note() -> None:
    """A POST with a streaming body that gets a 503 raises ServiceUnavailableError without the streaming-note.

    The blocker is method ineligibility (POST not in retry_methods by default), not the streaming body.
    The previous code attached the streaming-note here, misleadingly suggesting the stream was the blocker.
    """
    sleeper = _SleepRecorder()
    handler = _ResponseSequence([HTTPStatus.SERVICE_UNAVAILABLE])

    async def _streaming_body() -> typing.AsyncIterator[bytes]:  # noqa: RUF029 — async iterator pattern
        yield b"chunk"

    transport = httpx2.MockTransport(handler)
    async with AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=transport),
        middleware=[AsyncRetry(_sleep=sleeper, base_delay=0.01, max_delay=0.02)],
    ) as client:
        request = client.build_request("POST", "https://example.test/x", content=_streaming_body())
        with pytest.raises(ServiceUnavailableError) as exc_info:
            await client.send(request)
    notes = getattr(exc_info.value, "__notes__", [])
    assert not any("stream that cannot replay" in n for n in notes), (
        f"streaming-note was incorrectly attached when method ineligibility was the blocker: {notes!r}"
    )
    assert sleeper.calls == []  # no retry
```

- [ ] **Step 3: Verify there is ALSO a test confirming the streaming-note IS attached when streaming IS the blocker (GET + 503 + streaming body)**

```bash
grep -n 'streaming.*not retrying\|STREAMING_BODY_REFUSAL\|stream that cannot replay' tests/test_retry.py | head -10
```

If a test like `test_streaming_body_refused_on_retryable_status` exists for GET + retryable status, the note-correctness assertion is already covered. If not, ADD this test next to the negative one:

```python
async def test_eligible_method_with_streaming_body_does_attach_streaming_note() -> None:
    """A GET with a streaming body that gets a 503 raises WITH the streaming-note (the body IS the blocker)."""
    sleeper = _SleepRecorder()
    handler = _ResponseSequence([HTTPStatus.SERVICE_UNAVAILABLE])

    async def _streaming_body() -> typing.AsyncIterator[bytes]:  # noqa: RUF029
        yield b"chunk"

    transport = httpx2.MockTransport(handler)
    async with AsyncClient(
        httpx2_client=httpx2.AsyncClient(transport=transport),
        middleware=[AsyncRetry(_sleep=sleeper, base_delay=0.01, max_delay=0.02)],
    ) as client:
        # GET with a body is unusual but used here to isolate the streaming-as-blocker case
        # from method ineligibility; the test asserts streaming is what blocks retry.
        request = client.build_request("GET", "https://example.test/x", content=_streaming_body())
        with pytest.raises(ServiceUnavailableError) as exc_info:
            await client.send(request)
    notes = getattr(exc_info.value, "__notes__", [])
    assert any("stream that cannot replay" in n for n in notes), (
        f"streaming-note was missing when streaming was the actual blocker: {notes!r}"
    )
```

(Only add this second test if no existing one covers the positive case.)

- [ ] **Step 4: Run the negative test — confirm it FAILS**

```bash
uv run pytest tests/test_retry.py::test_method_ineligible_with_streaming_body_does_not_attach_streaming_note -x --no-cov -q
```

Expected: FAIL — current production attaches the note in this case.

- [ ] **Step 5: Fix `AsyncRetry.__call__` — scope the note to the right branch**

In `src/httpware/middleware/resilience/retry.py`, replace the StatusError except clause that currently misroutes the note. The async class has it around lines 108-115:

old_string:
```python
            except StatusError as exc:
                retryable_status = exc.response.status_code in self.retry_status_codes
                if not method_eligible or not retryable_status:
                    if retryable_status and request.extensions.get(STREAMING_BODY_MARKER):
                        exc.add_note(_STREAMING_BODY_REFUSAL_NOTE)
                    raise
                last_exc = exc
                last_response = exc.response
```

new_string:
```python
            except StatusError as exc:
                retryable_status = exc.response.status_code in self.retry_status_codes
                if not method_eligible or not retryable_status:
                    raise
                last_exc = exc
                last_response = exc.response
```

(Drop the misleading inner `if retryable_status and ... STREAMING_BODY_MARKER: add_note`. The note still fires correctly at the `# ---- retryable failure path` block below — lines 125-141 — where streaming IS the actual blocker.)

Also clean the parallel `(NetworkError, TimeoutError)` arm at lines 116-122:

old_string:
```python
            except (NetworkError, TimeoutError) as exc:
                if not method_eligible:
                    if request.extensions.get(STREAMING_BODY_MARKER):
                        exc.add_note(_STREAMING_BODY_REFUSAL_NOTE)
                    raise
                last_exc = exc
                last_response = None
```

new_string:
```python
            except (NetworkError, TimeoutError) as exc:
                if not method_eligible:
                    raise
                last_exc = exc
                last_response = None
```

- [ ] **Step 6: Run async tests — both PASS**

```bash
uv run pytest tests/test_retry.py::test_method_ineligible_with_streaming_body_does_not_attach_streaming_note tests/test_retry.py::test_eligible_method_with_streaming_body_does_attach_streaming_note -x --no-cov -q
```

Expected: both PASS. Then run the full async retry suite to confirm no regressions:

```bash
uv run pytest tests/test_retry.py -x --no-cov -q
```

Expected: all pass.

- [ ] **Step 7: Apply the same scoping fix in `Retry.__call__` (sync, lines 239-253)**

old_string (sync StatusError branch):
```python
            except StatusError as exc:
                retryable_status = exc.response.status_code in self.retry_status_codes
                if not method_eligible or not retryable_status:
                    if retryable_status and request.extensions.get(STREAMING_BODY_MARKER):
                        exc.add_note(_STREAMING_BODY_REFUSAL_NOTE)
                    raise
                last_exc = exc
                last_response = exc.response
```

new_string:
```python
            except StatusError as exc:
                retryable_status = exc.response.status_code in self.retry_status_codes
                if not method_eligible or not retryable_status:
                    raise
                last_exc = exc
                last_response = exc.response
```

old_string (sync NetworkError/TimeoutError branch):
```python
            except (NetworkError, TimeoutError) as exc:
                if not method_eligible:
                    if request.extensions.get(STREAMING_BODY_MARKER):
                        exc.add_note(_STREAMING_BODY_REFUSAL_NOTE)
                    raise
                last_exc = exc
                last_response = None
```

new_string:
```python
            except (NetworkError, TimeoutError) as exc:
                if not method_eligible:
                    raise
                last_exc = exc
                last_response = None
```

- [ ] **Step 8: Add the sync mirror tests to `tests/test_retry_sync.py`**

Mirror the two test functions from Steps 2 + 3 in sync form (drop `async`, use `Client` instead of `AsyncClient`, use sync body iterator if applicable). The sync streaming body is `typing.Iterator[bytes]` instead of `AsyncIterator`. Read the sync file's existing patterns first.

- [ ] **Step 9: Full retry suite + lint**

```bash
uv run pytest tests/test_retry.py tests/test_retry_sync.py -x --no-cov -q
just lint-ci
```

Expected: green.

- [ ] **Step 10: Commit**

```bash
git add src/httpware/middleware/resilience/retry.py tests/test_retry.py tests/test_retry_sync.py
git commit -m "$(cat <<'EOF'
fix(retry): scope streaming-body refusal note to its actual blocker site

The early-out branch for method ineligibility AND non-retryable status
also attached the streaming-body refusal note whenever `retryable_status
and request.extensions.get(STREAMING_BODY_MARKER)` — telling users their
stream couldn't replay when the actual reason for not retrying was method
exclusion (e.g. POST not in retry_methods). The same misrouting existed
on the NetworkError/TimeoutError arm.

Drop the misleading add_note() inside the early-out branches in both
AsyncRetry and Retry. The note still fires at the existing dedicated
streaming-refusal site (the `# ---- retryable failure path` block) where
streaming is the actual blocker.

Tests pin both directions: POST + streaming + 503 → ServiceUnavailableError
WITHOUT the note; GET + streaming + 503 → with the note.

Closes audit Nit finding (retry.py:111 + :242/:249) from
planning/audit/2026-06-07-deep-audit.md.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: `RuntimeError → TransportError` via `is_closed` check (not substring)

**Files:**
- Modify: `src/httpware/client.py` (async `_terminal` + sync `_terminal`)
- Modify: `tests/test_client_lifecycle.py` (async tests for the new branch)
- Modify: `tests/test_client_sync.py` (sync mirror)

Closes audit Nit finding #7.

- [ ] **Step 1: Write the failing test (async)**

Append to `tests/test_client_lifecycle.py`:

```python
async def test_runtimeerror_unrelated_to_close_propagates_unchanged() -> None:
    """A RuntimeError NOT caused by client closure must propagate as-is, not get mapped to TransportError."""
    msg = "downstream proxy hiccup — closed connection reset by peer"  # contains "closed" substring but client is open

    def _handler(_request: httpx2.Request) -> httpx2.Response:
        raise RuntimeError(msg)

    transport = httpx2.MockTransport(_handler)
    async with AsyncClient(httpx2_client=httpx2.AsyncClient(transport=transport)) as client:
        with pytest.raises(RuntimeError) as exc_info:
            await client.get("https://example.test/x")
        assert not isinstance(exc_info.value, TransportError)  # must NOT have been mapped


async def test_runtimeerror_after_aclose_maps_to_transporterror() -> None:
    """After aclose(), sending raises a RuntimeError that should map to TransportError via is_closed."""
    transport = httpx2.MockTransport(lambda req: httpx2.Response(HTTPStatus.OK, request=req))
    client = AsyncClient(httpx2_client=httpx2.AsyncClient(transport=transport))
    await client.aclose()
    with pytest.raises(TransportError):
        await client.get("https://example.test/x")
```

If the test file lacks `from httpware.errors import TransportError` or `from http import HTTPStatus`, add them.

- [ ] **Step 2: Run the negative test — confirm it FAILS**

```bash
uv run pytest tests/test_client_lifecycle.py::test_runtimeerror_unrelated_to_close_propagates_unchanged -x --no-cov -q
```

Expected: FAIL — the message contains "closed" so current production maps to `TransportError` even though the client is still open.

The second test should already pass against the current code (when client is closed, httpx2 raises a RuntimeError that contains "closed"), but verify after the fix that BOTH still pass.

- [ ] **Step 3: Fix async `_terminal`**

Edit `src/httpware/client.py` around lines 130-139:

old_string:
```python
    async def _terminal(self, request: httpx2.Request) -> httpx2.Response:
        try:
            async with _httpx2_exception_mapper():
                response = await self._httpx2_client.send(request)
        except RuntimeError as exc:
            if "closed" in str(exc):
                raise TransportError(str(exc)) from exc
            raise
        _raise_on_status_error(response)
        return response
```

new_string:
```python
    async def _terminal(self, request: httpx2.Request) -> httpx2.Response:
        try:
            async with _httpx2_exception_mapper():
                response = await self._httpx2_client.send(request)
        except RuntimeError as exc:
            if self._httpx2_client.is_closed:
                raise TransportError(str(exc)) from exc
            raise
        _raise_on_status_error(response)
        return response
```

- [ ] **Step 4: Run the async tests — both PASS**

```bash
uv run pytest tests/test_client_lifecycle.py::test_runtimeerror_unrelated_to_close_propagates_unchanged tests/test_client_lifecycle.py::test_runtimeerror_after_aclose_maps_to_transporterror -x --no-cov -q
```

Expected: both PASS.

- [ ] **Step 5: Apply the same fix to sync `_terminal` (client.py around lines 848-857)**

old_string:
```python
    def _terminal(self, request: httpx2.Request) -> httpx2.Response:
        try:
            with _httpx2_exception_mapper_sync():
                response = self._httpx2_client.send(request)
        except RuntimeError as exc:
            if "closed" in str(exc):
                raise TransportError(str(exc)) from exc
            raise
        _raise_on_status_error(response)
        return response
```

new_string:
```python
    def _terminal(self, request: httpx2.Request) -> httpx2.Response:
        try:
            with _httpx2_exception_mapper_sync():
                response = self._httpx2_client.send(request)
        except RuntimeError as exc:
            if self._httpx2_client.is_closed:
                raise TransportError(str(exc)) from exc
            raise
        _raise_on_status_error(response)
        return response
```

- [ ] **Step 6: Add sync mirror tests to `tests/test_client_sync.py`**

Mirror the two async tests, dropping `async` / `aclose()` for `close()` and `AsyncClient` for `Client`. Read the existing sync lifecycle test patterns first.

- [ ] **Step 7: Full client + lifecycle test suite + lint**

```bash
uv run pytest tests/test_client_lifecycle.py tests/test_client_sync.py tests/test_client_methods.py -x --no-cov -q
just lint-ci
```

Expected: green.

- [ ] **Step 8: Commit**

```bash
git add src/httpware/client.py tests/test_client_lifecycle.py tests/test_client_sync.py
git commit -m "$(cat <<'EOF'
fix(client): map RuntimeError → TransportError via is_closed, not substring

Both AsyncClient._terminal and Client._terminal mapped RuntimeError to
TransportError by checking `"closed" in str(exc)`. This conflates two
unrelated conditions: any RuntimeError whose message happens to contain
"closed" (from any transport layer, plugin, or future httpx2 wording
change) was mis-classified as TransportError; conversely, if httpx2 reworded
its closed-client error to "shut down" or "disposed", the mapping would
silently break.

Replace with `self._httpx2_client.is_closed` — the same public attribute
already used elsewhere in client.py for the borrowed-client teardown
guards (lines 774, 784, 870, 880). Message-independent.

Tests pin both directions: RuntimeError raised while the client is open
propagates as-is; RuntimeError raised after close (real httpx2 case) maps
to TransportError.

Closes audit Nit finding (client.py:135 + :852) from
planning/audit/2026-06-07-deep-audit.md.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Draft release notes for 0.8.3 + open PR

**Files:**
- Create: `planning/releases/0.8.3.md`

- [ ] **Step 1: Read the 0.8.1 release-notes file to mirror its shape**

```bash
cat planning/releases/0.8.1.md
```

Note the structure: title (`# httpware X.Y.Z — <headline>`), "Patch release with..." TL;DR, sections per change, a "Behavioral changes" callout.

- [ ] **Step 2: Write `planning/releases/0.8.3.md`**

Create with this exact content:

```markdown
# httpware 0.8.3 — RetryBudget cluster + retry/client robustness

**Patch release with three behavioral changes you should know about.** All driven by the [deep audit](../audit/2026-06-07-deep-audit.md); collectively close 7 audit findings (3 RetryBudget, 2 retry-surface nits, 2 chunk-3 test rewrites).

## TL;DR

- **`RetryBudget` deposits once per request, not once per attempt.** Tighter retry pacing under load — matches the documented Finagle contract.
- **`RetryBudget` ceiling uses `math.ceil`, not `int(...)` truncation.** No more silent off-by-one against the configured `percent_can_retry`.
- **`Retry-After > max_delay` now raises** the underlying `StatusError` with a PEP 678 note rather than silently capping the sleep at `max_delay` (and retrying into the same error).
- **`RuntimeError → TransportError` mapping** now keys on `httpx2.Client.is_closed`, not substring-matching "closed" in the exception message.
- **Streaming-body refusal note** is now scoped to where streaming is actually the blocker (not attached to method-ineligible refusals).

## The behavioral changes

### `RetryBudget.deposit()` per request, not per attempt

The Finagle retry-budget contract is `withdrawals / deposits <= percent_can_retry` where the denominator counts original requests. `AsyncRetry` and `Retry` previously deposited a token inside the per-attempt loop, so a request that retried twice contributed three deposits and two withdrawals — inflating the ratio by `(attempts-1)/attempts` and letting through more retries than `percent_can_retry` allowed.

Now `deposit()` is hoisted above the attempt loop and runs exactly once per `__call__`. Users with active retry traffic will see the budget refuse retries earlier than before. This is the documented contract; the previous behavior was the bug.

If you were tuning `percent_can_retry` against the pre-0.8.3 behavior, re-validate your target retry rate.

### `RetryBudget` ceiling: `math.ceil` instead of `int(...)`

`try_withdraw`'s ceiling computed `int(deposits * percent) + floor`, truncating fractional values. For `deposits=4` and `percent_can_retry=0.2`, the term was `int(0.8) = 0` — with a `floor=0`, no retries were permitted even though the configured percentage says the first retry should be allowed at 5 deposits.

`math.ceil` makes the threshold honor the configured percentage at the first deposit-count where it is mathematically expressible. The previous behavior was strictly under-permissive; users with `min_retries_per_sec > 0` were insulated by the floor, but `min_retries_per_sec=0.0` configurations saw the off-by-one.

### `Retry-After > max_delay` raises instead of silently capping

Previously when a server sent `Retry-After: 120` and the client had `max_delay=5.0`, `AsyncRetry`/`Retry` clamped to 5s and retried — almost certainly hitting the same 503 or 429 and burning an attempt while violating the server's hint.

Now: when the parsed `Retry-After` exceeds `max_delay`, `AsyncRetry`/`Retry` re-raises the underlying `StatusError` (e.g. `ServiceUnavailableError`) with a PEP 678 note:

```text
httpware: Retry-After (120s) exceeded max_delay (5.0s); giving up
```

If you want to keep retrying despite the gap, raise `max_delay` to accommodate the server's hint, or set `respect_retry_after=False` to drop back to jittered backoff.

### `RuntimeError → TransportError` via `is_closed`

Both `AsyncClient._terminal` and `Client._terminal` mapped `RuntimeError` to `TransportError` by substring-matching `"closed" in str(exc)`. Two failure modes: any unrelated `RuntimeError` whose message happened to contain "closed" was mis-classified as `TransportError`; conversely, an httpx2 wording change (e.g. "shut down") would silently break the mapping.

Now the check is `self._httpx2_client.is_closed` — message-independent. Same attribute already used elsewhere in `client.py` for borrowed-client teardown guards.

### Streaming-body refusal note scoped correctly

The early-out branch for method ineligibility OR non-retryable status also attached the streaming-body refusal note whenever `retryable_status and STREAMING_BODY_MARKER` — misleadingly suggesting the stream was the blocker when the actual reason was method exclusion (e.g. `POST` not in `retry_methods`).

The note now fires only at the dedicated streaming-refusal site, where streaming IS the blocker. The diagnostic is precise instead of misleading.

## Fixes that aren't user-visible

- The `RetryBudget` Hypothesis property test (`tests/test_budget_props.py`) used to compute its expected ceiling with the same `int(...)` formula as production, so it couldn't detect the off-by-one. Now uses `math.ceil` and asserts equality.
- A new property test on `RetryBudget` (`tests/test_retry_props.py::test_budget_exhaustion_is_reachable_and_deterministic`) exercises the budget-exhaustion path that the existing retry property tests left uncovered.

## Audit findings closed

7 of the 35 audit findings from [`planning/audit/2026-06-07-deep-audit.md`](../audit/2026-06-07-deep-audit.md) — the entire RetryBudget cross-cutting cluster plus 2 adjacent retry-surface nits. The audit's Summary header is unchanged; this is the work, not the audit itself.

## Upgrade

```bash
uv add httpware==0.8.3
# or
pip install -U 'httpware==0.8.3'
```

No import changes; no API surface changes; constructor signatures unchanged.
```

- [ ] **Step 3: Lint**

```bash
just lint-ci
```

Expected: green (eof-fixer may make a tiny trailing-newline fix; that's fine).

- [ ] **Step 4: Commit**

```bash
git add planning/releases/0.8.3.md
git commit -m "$(cat <<'EOF'
docs(release): draft 0.8.3 notes — RetryBudget cluster + retry/client robustness

Three behavioral changes (deposit per-request, ceiling math.ceil,
Retry-After give-up), one mapping cleanup (RuntimeError → TransportError
via is_closed), one diagnostic fix (streaming-note scoping), plus two
non-user-visible test improvements. Closes 7 audit findings.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 5: Push the branch + open the PR**

```bash
git push -u origin fix/retry-budget-cluster
```

```bash
gh pr create --base main --head fix/retry-budget-cluster --title "fix(retry-budget): close 7 audit findings (0.8.3)" --body "$(cat <<'EOF'
## Summary

Closes 7 of the 35 deep-audit findings — the RetryBudget cross-cutting cluster plus 2 adjacent retry-surface nits. See [`planning/specs/2026-06-08-retry-budget-cluster-design.md`](planning/specs/2026-06-08-retry-budget-cluster-design.md) for the design and [`planning/releases/0.8.3.md`](planning/releases/0.8.3.md) for the user-facing release notes.

## Behavioral changes (read these)

- **`RetryBudget` deposits once per request, not per attempt.** Tighter retry pacing under load.
- **`RetryBudget` ceiling uses `math.ceil`.** No more silent off-by-one against `percent_can_retry`.
- **`Retry-After > max_delay` raises with a PEP 678 note** instead of silently capping.
- **`RuntimeError → TransportError` via `is_closed`.** Message-independent mapping.
- **Streaming-body refusal note** scoped to where streaming is actually the blocker.

## Audit findings closed

| # | Severity | File:line | Closed by commit |
|---|---|---|---|
| 1 | Low | `retry.py:105` + `:236` | deposit() hoist |
| 2 | Low | `retry.py:189` + `:320` | Retry-After give-up |
| 3 | Low | `budget.py:67` | math.ceil ceiling |
| 4 | Low | `test_budget_props.py:52` | test rewrite (paired with #3) |
| 5 | Nit | `test_retry_props.py:60` | budget-exhaustion property test |
| 6 | Nit | `retry.py:111` + `:242`/`:249` | streaming-note scoping |
| 7 | Nit | `client.py:135` + `:852` | is_closed check |

## Test plan

- [x] All retry + budget tests pass (`just test`) — verified after each commit
- [x] `just lint-ci` green — verified after each commit
- [ ] Reviewer manually scans the per-commit messages for any behavioral surprise

## Release

Tag `0.8.3` from the merge SHA after this PR lands.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Verify the PR URL is returned. Report it to the user.

- [ ] **Step 6: Final verification**

```bash
git log --oneline -8
gh pr view --json url,state,title
```

Expected: 7 fix commits + spec commit on the branch (excluding the spec commit which already landed in the previous turn); PR open and pointing to main.

---

## Self-review notes

- **Spec coverage:** Every audit finding referenced in the spec's per-finding change list has a numbered task (#1→T1, #2→T2 wait — let me re-check the mapping). Spec finding #1 = T2 (deposit hoist); #2 = T3 (Retry-After give-up); #3 = T1 (math.ceil); #4 = T1 (test rewrite, paired with #3); #5 = T4 (budget-exhaustion property); #6 = T5 (streaming-note); #7 = T6 (is_closed). T7 is release notes + PR. All seven findings covered.
- **Placeholder scan:** All before/after code blocks are verbatim with surrounding context. Test code is complete (no "similar to" or "add appropriate"). Commit-message HEREDOCs are filled in.
- **Type/name consistency:** `_RETRY_AFTER_EXCEEDS_MAX_DELAY_NOTE` introduced in T3 is used consistently. `_CountingBudget` introduced in T2 is used in both async + sync test additions with the same shape. `is_closed` is the same attribute name in both T6 async + sync fixes.
- **TDD ordering:** Every task that touches production code has a failing-test step before the fix. T1 tightens the assertion (`<=` → `==`) so the rewritten test fails against the unfixed production. T2-T6 each follow red-green-commit.
- **Test parity:** Every async test addition has a corresponding sync mirror step. Where sync helper names may differ (`_SleepRecorder` vs `_SleepRecorderSync`, etc.), the step explicitly says "read the file first to confirm".
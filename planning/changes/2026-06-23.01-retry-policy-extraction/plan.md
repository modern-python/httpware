# retry-policy-extraction — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps
> use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the duplicated retry decision logic into a stateless
`_RetryPolicy`, shrinking `AsyncRetry`/`Retry` to thin loop drivers with no
behaviour change.

**Spec:** [`design.md`](./design.md)

**Branch:** `refactor/retry-policy-extraction`

**Commit strategy:** Per-task commits.

---

### Task 1: Extract `_RetryPolicy` and thin the wrappers

**Files:**
- Modify: `src/httpware/middleware/resilience/retry.py`

Introduce the decision module; both wrappers drive it. Existing suites are the
parity net — do not edit them in this task.

- [ ] **Step 1: Add the catch-surface constant**

  Add `_RETRYABLE_EXCEPTIONS = (StatusError, NetworkError, TimeoutError)` at
  module level (near the other module constants).

- [ ] **Step 2: Add `_RetryPolicy`**

  New private class holding `max_attempts`, `base_delay`, `max_delay`,
  `retry_status_codes`, `retry_methods`, `respect_retry_after`, `budget`.
  Move the `max_attempts < 1` → `ValueError` validation here. Add:

  ```python
  def decide(self, *, attempt: int, request: httpx2.Request, exc: BaseException) -> float
  ```

  Port the decision logic verbatim from `AsyncRetry.__call__` (lines ~108-206):
  classification (derive `last_response` from `isinstance(exc, StatusError)`,
  method-eligibility, status-set), streaming-refusal, exhaustion, Retry-After
  vs `max_delay`, budget `try_withdraw`, delay choice. Keep every `_emit_event`
  call, note string, and `RetryBudgetExhaustedError(... ) from exc` exactly as
  today. Terminal cases `raise`; the retry case `return delay`.

- [ ] **Step 3: Rewrite `AsyncRetry`**

  `__init__` keeps its signature; build `self._policy = _RetryPolicy(...)`, set
  `self.budget = self._policy.budget` and `self._sleep = _sleep`. Drop the six
  config attributes. Replace `__call__` body with the thin loop (deposit →
  `for attempt in range(self._policy.max_attempts)` → try/`await next` →
  `except _RETRYABLE_EXCEPTIONS as exc: delay = self._policy.decide(...)` →
  `await self._sleep(delay)`). Remove the now-unneeded
  `# noqa: C901, PLR0912, PLR0915` from `__call__`.

- [ ] **Step 4: Rewrite `Retry`**

  Identical to Step 3 but `next(request)` and `self._sleep(delay)`. Both
  wrappers share the one `_RetryPolicy`/`_RETRYABLE_EXCEPTIONS`.

- [ ] **Step 5: Verify parity**

  ```bash
  just test tests/test_retry.py tests/test_retry_sync.py tests/test_retry_props.py \
    tests/test_retry_budget_threadsafety.py tests/test_threading_with_shared_budget.py
  ```
  All green, unchanged. If any fail, the extraction drifted — fix the policy,
  not the tests.

- [ ] **Step 6: Commit**

  ```bash
  git add src/httpware/middleware/resilience/retry.py
  git commit -m "refactor(retry): extract stateless _RetryPolicy decision module

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 2: Add seam-level policy tests

**Files:**
- Create: `tests/test_retry_policy.py`

Drive `decide` directly across the decision matrix — no client, no
`MockTransport`.

- [ ] **Step 1: Write the matrix**

  Cover: retryable status / network / timeout → returns delay within
  `0 ≤ delay ≤ max_delay`; non-retryable status → re-raises original;
  non-eligible method → re-raises original; streaming-body (`STREAMING_BODY_MARKER`
  set) → raises with refusal note; exhaustion (last attempt) → raises with
  "gave up after N" note; Retry-After > `max_delay` → raises with note;
  Retry-After ≤ `max_delay` → returns that exact value; budget refusal →
  `RetryBudgetExhaustedError` with populated fields and `__cause__` set.
  Annotate all test args. Build `httpx2.Request`/`StatusError` fixtures
  directly; inject a zero/stingy `RetryBudget` for the refusal case.

- [ ] **Step 2: Run**

  ```bash
  just test tests/test_retry_policy.py
  ```
  All green.

- [ ] **Step 3: Commit**

  ```bash
  git add tests/test_retry_policy.py
  git commit -m "test(retry): cover _RetryPolicy.decide at the seam

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 3: Promote to architecture, lint, full suite

**Files:**
- Modify: `architecture/resilience.md`
- Modify: `planning/changes/2026-06-23.01-retry-policy-extraction/design.md` (frontmatter at ship)

- [ ] **Step 1: Promote the living truth**

  In `architecture/resilience.md`, document `_RetryPolicy` as the shared
  decision module behind `AsyncRetry`/`Retry`, mirroring how the doc already
  frames `_CircuitBreakerState`. Keep it prose, no frontmatter.

- [ ] **Step 2: Full gate**

  ```bash
  just lint && just test
  ```
  Both clean. Confirm the `httpx2._` and other review-only invariants still
  hold in the diff.

- [ ] **Step 3: Ship frontmatter + commit**

  Set `status: shipped`, `pr`, and `outcome` in `design.md` once the PR number
  exists. Run `just index` to confirm the listing regenerates.

  ```bash
  git add architecture/resilience.md planning/changes/2026-06-23.01-retry-policy-extraction/
  git commit -m "docs(resilience): promote _RetryPolicy into architecture truth

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

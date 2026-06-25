# circuit-breaker-rate-mode — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps
> use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in time-based failure-rate trip mode to
`AsyncCircuitBreaker` / `CircuitBreaker`; classic consecutive-failure stays the
default and unchanged.

**Architecture:** A new `_RollingWindow` (time-bucketed success/failure counters)
lives beside the existing lock-free `_CircuitBreakerState`. Three new
constructor params (`failure_rate_threshold`, `window_seconds`, `minimum_calls`)
select and configure rate mode. The mode changes only the CLOSED→OPEN decision;
half-open recovery, event names, and concurrency model are unchanged. All logic
sits in `_CircuitBreakerState`, so both wrappers reach parity for free.

**Tech Stack:** Python 3.11+, `httpx2`, `pytest` (asyncio auto mode), Hypothesis
for the window-recorder property test, `time.monotonic` (injected as `_now` in
tests).

**Spec:** [`design.md`](./design.md)

**Branch:** `feat/circuit-breaker-rate-mode`

**Commit strategy:** Per-task commits.

---

### Task 1: `_RollingWindow` time-bucketed recorder

A standalone, fully-tested data structure before any breaker wiring. This is the
riskiest piece (slot math / eviction), so it gets unit tests + a Hypothesis prop
in isolation.

**Files:**
- Modify: `src/httpware/middleware/resilience/circuit_breaker.py`
- Test: `tests/test_rolling_window.py` (create)

- [ ] **Step 1: Write the failing unit tests**

  Create `tests/test_rolling_window.py`:

  ```python
  """Unit tests for the time-bucketed _RollingWindow used by rate-mode CircuitBreaker."""

  from httpware.middleware.resilience.circuit_breaker import _RollingWindow


  def test_counts_within_window() -> None:
      w = _RollingWindow(window_seconds=10.0)
      w.record(0.0, failed=True)
      w.record(1.0, failed=True)
      w.record(2.0, failed=False)
      total, failures = w.totals(2.0)
      assert (total, failures) == (3, 2)


  def test_empty_window_is_zero() -> None:
      w = _RollingWindow(window_seconds=10.0)
      assert w.totals(0.0) == (0, 0)


  def test_stale_buckets_evicted_by_time() -> None:
      w = _RollingWindow(window_seconds=10.0)
      w.record(0.0, failed=True)
      w.record(0.5, failed=True)
      # advance a full window past those records
      w.record(11.0, failed=False)
      total, failures = w.totals(11.0)
      assert (total, failures) == (1, 0)


  def test_totals_excludes_stale_without_new_write() -> None:
      w = _RollingWindow(window_seconds=10.0)
      w.record(0.0, failed=True)
      # no write after the window elapses — totals() alone must drop the stale bucket
      assert w.totals(20.0) == (0, 0)


  def test_clear_resets_everything() -> None:
      w = _RollingWindow(window_seconds=10.0)
      w.record(0.0, failed=True)
      w.record(1.0, failed=False)
      w.clear()
      assert w.totals(1.0) == (0, 0)
  ```

- [ ] **Step 2: Run to verify failure**

  Run: `just test tests/test_rolling_window.py`
  Expected: FAIL — `ImportError: cannot import name '_RollingWindow'`.

- [ ] **Step 3: Implement `_RollingWindow` + the bucket constant**

  In `src/httpware/middleware/resilience/circuit_breaker.py`, add the constant
  near the other module constants (after `_DEFAULT_FAILURE_STATUS_CODES`):

  ```python
  _BUCKET_COUNT = 10
  ```

  Add the class above `class _CircuitBreakerState:`:

  ```python
  class _RollingWindow:
      """Time-bucketed success/failure counters over a rolling window.

      `window_seconds` is split into `_BUCKET_COUNT` buckets. Each bucket holds
      [successes, failures] tagged with the integer time-slot it represents; a
      bucket whose slot is stale is reset on write, and `totals` filters to the
      live slot range so data older than the window never counts. Every method is
      synchronous and reads `now` from its caller (so the breaker's critical
      section owns the clock read).
      """

      def __init__(self, window_seconds: float) -> None:
          self._bucket_width = window_seconds / _BUCKET_COUNT
          self._slot = [-1] * _BUCKET_COUNT
          self._success = [0] * _BUCKET_COUNT
          self._failure = [0] * _BUCKET_COUNT

      def _current_slot(self, now: float) -> int:
          return int(now // self._bucket_width)

      def record(self, now: float, *, failed: bool) -> None:
          slot = self._current_slot(now)
          index = slot % _BUCKET_COUNT
          if self._slot[index] != slot:  # bucket reused for a new slot — evict
              self._slot[index] = slot
              self._success[index] = 0
              self._failure[index] = 0
          if failed:
              self._failure[index] += 1
          else:
              self._success[index] += 1

      def totals(self, now: float) -> tuple[int, int]:
          """Return (total, failures) across buckets still inside the window at `now`."""
          slot = self._current_slot(now)
          oldest = slot - _BUCKET_COUNT + 1
          total = 0
          failures = 0
          for i in range(_BUCKET_COUNT):
              if oldest <= self._slot[i] <= slot:
                  total += self._success[i] + self._failure[i]
                  failures += self._failure[i]
          return total, failures

      def clear(self) -> None:
          self._slot = [-1] * _BUCKET_COUNT
          self._success = [0] * _BUCKET_COUNT
          self._failure = [0] * _BUCKET_COUNT
  ```

- [ ] **Step 4: Run to verify pass**

  Run: `just test tests/test_rolling_window.py`
  Expected: PASS (5 tests).

- [ ] **Step 5: Add a Hypothesis property test**

  Append to `tests/test_rolling_window.py`:

  ```python
  from hypothesis import given, settings
  from hypothesis import strategies as st


  @given(
      events=st.lists(
          st.tuples(st.floats(min_value=0.0, max_value=1000.0), st.booleans()),
          min_size=1,
          max_size=200,
      ),
  )
  @settings(max_examples=100, deadline=None)
  def test_totals_never_exceed_live_events(events: list[tuple[float, bool]]) -> None:
      """totals() at the final time never counts more than the events inside the live window."""
      window_seconds = 10.0
      w = _RollingWindow(window_seconds=window_seconds)
      ordered = sorted(events, key=lambda e: e[0])
      for now, failed in ordered:
          w.record(now, failed=failed)
      final = ordered[-1][0]
      bucket_width = window_seconds / 10
      live_cutoff_slot = int(final // bucket_width) - 10 + 1
      expected_live = [(t, f) for (t, f) in ordered if int(t // bucket_width) >= live_cutoff_slot]
      total, failures = w.totals(final)
      assert total <= len(expected_live)
      assert failures <= sum(1 for _, f in expected_live if f)
      assert 0 <= failures <= total
  ```

- [ ] **Step 6: Run the props + full suite + lint**

  Run: `just test tests/test_rolling_window.py && just lint`
  Expected: PASS; lint clean.

- [ ] **Step 7: Commit**

  ```bash
  git add src/httpware/middleware/resilience/circuit_breaker.py tests/test_rolling_window.py
  git commit -m "feat(circuit-breaker): add time-bucketed _RollingWindow recorder

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 2: Rate-mode config params + validation

Thread the three new params through `_CircuitBreakerState` and both wrappers,
with validation. No trip-behavior change yet — rate mode is configured but the
CLOSED decision still uses the classic counter (wired in Task 3).

**Files:**
- Modify: `src/httpware/middleware/resilience/circuit_breaker.py`
- Test: `tests/test_circuit_breaker.py` (add validation tests)

- [ ] **Step 1: Write failing validation tests**

  Append to `tests/test_circuit_breaker.py`:

  ```python
  import pytest as _pytest

  from httpware.middleware.resilience.circuit_breaker import (
      _FAILURE_RATE_THRESHOLD_INVALID,
      _MINIMUM_CALLS_INVALID,
      _WINDOW_SECONDS_INVALID,
  )


  @_pytest.mark.parametrize("bad", [0.0, -0.1, 1.5])
  def test_rate_threshold_out_of_range_raises(bad: float) -> None:
      with _pytest.raises(ValueError, match=_FAILURE_RATE_THRESHOLD_INVALID):
          AsyncCircuitBreaker(failure_rate_threshold=bad)


  def test_non_positive_window_seconds_raises() -> None:
      with _pytest.raises(ValueError, match=_WINDOW_SECONDS_INVALID):
          AsyncCircuitBreaker(failure_rate_threshold=0.5, window_seconds=0.0)


  def test_minimum_calls_below_one_raises() -> None:
      with _pytest.raises(ValueError, match=_MINIMUM_CALLS_INVALID):
          AsyncCircuitBreaker(failure_rate_threshold=0.5, minimum_calls=0)


  def test_classic_mode_is_default_when_rate_threshold_none() -> None:
      breaker = AsyncCircuitBreaker()  # no failure_rate_threshold
      assert breaker._state._rate_mode is False
  ```

- [ ] **Step 2: Run to verify failure**

  Run: `just test tests/test_circuit_breaker.py -k "rate_threshold or window_seconds or minimum_calls or classic_mode_is_default"`
  Expected: FAIL — import error for the new message constants / unexpected kwargs.

- [ ] **Step 3: Add message constants**

  In `circuit_breaker.py`, after the existing `_SUCCESS_THRESHOLD_INVALID`:

  ```python
  _FAILURE_RATE_THRESHOLD_INVALID = "failure_rate_threshold must be in (0, 1]"
  _WINDOW_SECONDS_INVALID = "window_seconds must be > 0"
  _MINIMUM_CALLS_INVALID = "minimum_calls must be >= 1"
  ```

- [ ] **Step 4: Extend `_CircuitBreakerState.__init__`**

  Add the three params (after `failure_status_codes`, before `now`) and validate
  + store them. Set `_rate_mode` and build the window only in rate mode:

  ```python
      def __init__(
          self,
          *,
          failure_threshold: int,
          reset_timeout: float,
          success_threshold: int,
          failure_status_codes: Collection[int] | None,
          failure_rate_threshold: float | None,
          window_seconds: float,
          minimum_calls: int,
          now: Callable[[], float],
      ) -> None:
          if failure_threshold < 1:
              raise ValueError(_FAILURE_THRESHOLD_INVALID)
          if reset_timeout < 0:
              raise ValueError(_RESET_TIMEOUT_INVALID)
          if success_threshold < 1:
              raise ValueError(_SUCCESS_THRESHOLD_INVALID)
          if failure_rate_threshold is not None and not (0.0 < failure_rate_threshold <= 1.0):
              raise ValueError(_FAILURE_RATE_THRESHOLD_INVALID)
          if window_seconds <= 0:
              raise ValueError(_WINDOW_SECONDS_INVALID)
          if minimum_calls < 1:
              raise ValueError(_MINIMUM_CALLS_INVALID)
          self._failure_threshold = failure_threshold
          self._reset_timeout = reset_timeout
          self._success_threshold = success_threshold
          self._failure_status_codes = (
              frozenset(failure_status_codes) if failure_status_codes is not None else _DEFAULT_FAILURE_STATUS_CODES
          )
          self._failure_rate_threshold = failure_rate_threshold
          self._minimum_calls = minimum_calls
          self._rate_mode = failure_rate_threshold is not None
          self._window = _RollingWindow(window_seconds) if self._rate_mode else None
          self._window_seconds = window_seconds
          self._now = now
          self._state = _CircuitState.CLOSED
          self._consecutive_failures = 0
          self._consecutive_successes = 0
          self._opened_at = 0.0
          self._probe_in_flight = False
  ```

- [ ] **Step 5: Thread the params through both wrappers**

  In BOTH `AsyncCircuitBreaker.__init__` and `CircuitBreaker.__init__`, add the
  three params to the signature (after `failure_status_codes`, before `_now`)
  and forward them to `_CircuitBreakerState(...)`:

  ```python
          failure_rate_threshold: float | None = None,
          window_seconds: float = 30.0,
          minimum_calls: int = 20,
  ```

  and in the `_CircuitBreakerState(...)` call add:

  ```python
              failure_rate_threshold=failure_rate_threshold,
              window_seconds=window_seconds,
              minimum_calls=minimum_calls,
  ```

- [ ] **Step 6: Run validation tests + full suite**

  Run: `just test tests/test_circuit_breaker.py`
  Expected: PASS (new validation tests + all existing breaker tests unchanged).
  Then `just test` (full suite) — expect green.

- [ ] **Step 7: Commit**

  ```bash
  git add src/httpware/middleware/resilience/circuit_breaker.py tests/test_circuit_breaker.py
  git commit -m "feat(circuit-breaker): thread rate-mode config + validation

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 3: Rate-mode trip integration (CLOSED decision + window clear on close)

Wire rate mode into the state machine: record outcomes into the window while
CLOSED and open on rate; clear the window when the circuit closes. Async + sync
behavior tests.

**Files:**
- Modify: `src/httpware/middleware/resilience/circuit_breaker.py`
- Test: `tests/test_circuit_breaker.py`, `tests/test_circuit_breaker_sync.py`

- [ ] **Step 1: Write failing behavior tests (async)**

  Append to `tests/test_circuit_breaker.py`. These reuse the file's existing
  `_Clock`, `_StatusSequence`, `_client`, and error imports:

  ```python
  async def test_rate_mode_trips_on_partial_failure() -> None:
      """Alternating 50% failures trip rate mode (classic never would)."""
      clock = _Clock()
      breaker = AsyncCircuitBreaker(
          failure_rate_threshold=0.5, window_seconds=100.0, minimum_calls=10, _now=clock
      )
      # alternate 500 / 200 for 10 calls → 5 failures / 10 = 0.5
      handler = _StatusSequence([500, 200, 500, 200, 500, 200, 500, 200, 500, 200])
      client = _client(handler, breaker=breaker)
      for _ in range(10):
          try:
              await client.get("https://example.test/x")
          except InternalServerError:
              pass
      # next call is rejected — circuit opened on the rate
      with pytest.raises(CircuitOpenError):
          await client.get("https://example.test/x")


  async def test_rate_mode_does_not_trip_below_minimum_calls() -> None:
      clock = _Clock()
      breaker = AsyncCircuitBreaker(
          failure_rate_threshold=0.5, window_seconds=100.0, minimum_calls=10, _now=clock
      )
      handler = _StatusSequence([500, 500, 500])  # 3 failures, below floor of 10
      client = _client(handler, breaker=breaker)
      for _ in range(3):
          with pytest.raises(InternalServerError):
              await client.get("https://example.test/x")
      # still closed — under the volume floor
      handler_ok = _StatusSequence([200])
      client_ok = _client(handler_ok, breaker=breaker)
      assert (await client_ok.get("https://example.test/x")).status_code == HTTPStatus.OK


  async def test_rate_mode_evicts_old_failures() -> None:
      clock = _Clock()
      breaker = AsyncCircuitBreaker(
          failure_rate_threshold=0.5, window_seconds=10.0, minimum_calls=4, _now=clock
      )
      fail = _client(_StatusSequence([500, 500, 500, 500, 500, 500, 500, 500]), breaker=breaker)
      # 3 failures early in the window
      for _ in range(3):
          with pytest.raises(InternalServerError):
              await fail.get("https://example.test/x")
      clock.advance(20.0)  # push them fully out of the 10s window
      # one fresh failure: live window now has 1 failure / 1 total, but total < minimum_calls
      with pytest.raises(InternalServerError):
          await fail.get("https://example.test/x")
      ok = _client(_StatusSequence([200]), breaker=breaker)
      assert (await ok.get("https://example.test/x")).status_code == HTTPStatus.OK
  ```

- [ ] **Step 2: Run to verify failure**

  Run: `just test tests/test_circuit_breaker.py -k "rate_mode_trips or rate_mode_does_not_trip or rate_mode_evicts"`
  Expected: FAIL — the breaker does not yet open on rate (no CircuitOpenError raised).

- [ ] **Step 3: Add the rate-record helper + open-on-rate transition**

  In `_CircuitBreakerState`, refactor `_open` to share an `_enter_open` core and
  add `_record_outcome` + `_open_rate`. Replace the existing `_open` method with:

  ```python
      def _enter_open(self, request: httpx2.Request, attributes: dict[str, typing.Any]) -> None:
          self._state = _CircuitState.OPEN
          self._opened_at = self._now()
          self._consecutive_failures = 0
          self._consecutive_successes = 0
          self._emit(request, "circuit.opened", logging.WARNING, "circuit opened — failure threshold reached", attributes)

      def _open(self, request: httpx2.Request, *, failures: int) -> None:
          self._enter_open(request, {"failure_threshold": self._failure_threshold, "failures": failures})

      def _open_rate(self, request: httpx2.Request, *, total: int, failures: int) -> None:
          self._enter_open(
              request,
              {
                  "failure_rate": failures / total,
                  "failure_rate_threshold": self._failure_rate_threshold,
                  "window_seconds": self._window_seconds,
                  "observed_calls": total,
              },
          )

      def _record_outcome(self, request: httpx2.Request, *, failed: bool) -> None:
          now = self._now()
          self._window.record(now, failed=failed)  # _window is non-None in rate mode
          total, failures = self._window.totals(now)
          if total >= self._minimum_calls and failures / total >= self._failure_rate_threshold:
              self._open_rate(request, total=total, failures=failures)
  ```

  NOTE: `self._window` is `_RollingWindow | None`; it is only accessed inside
  `_record_outcome`, which only runs in rate mode (guarded by `_rate_mode` at the
  call sites in Step 4). Add `# ty: ignore[possibly-unbound-attribute]` on the
  `self._window.record(...)` / `self._window.totals(...)` lines ONLY if `ty`
  flags the `| None`; otherwise leave them. (Run `just lint` to find out.)

- [ ] **Step 4: Route CLOSED outcomes through the window in rate mode**

  Update `on_success` and `on_failure` so the CLOSED branch chooses by mode, and
  clear the window when the circuit closes:

  ```python
      def on_success(self, role: str, request: httpx2.Request) -> None:
          if role == _ROLE_PROBE:
              self._probe_in_flight = False
          if self._state is _CircuitState.CLOSED:
              if self._rate_mode:
                  self._record_outcome(request, failed=False)
              else:
                  self._consecutive_failures = 0
          elif self._state is _CircuitState.HALF_OPEN:
              self._consecutive_successes += 1
              if self._consecutive_successes >= self._success_threshold:
                  self._state = _CircuitState.CLOSED
                  self._consecutive_failures = 0
                  self._consecutive_successes = 0
                  if self._rate_mode:
                      self._window.clear()  # fresh slate on recovery
                  self._emit(request, "circuit.closed", logging.INFO, "circuit closed — service recovered", {})

      def on_failure(self, role: str, request: httpx2.Request) -> None:
          if role == _ROLE_PROBE:
              self._probe_in_flight = False
          if self._state is _CircuitState.CLOSED:
              if self._rate_mode:
                  self._record_outcome(request, failed=True)
              else:
                  self._consecutive_failures += 1
                  if self._consecutive_failures >= self._failure_threshold:
                      self._open(request, failures=self._consecutive_failures)
          elif self._state is _CircuitState.HALF_OPEN:
              self._open(request, failures=1)  # 1 = the single probe failure that re-opened the circuit
  ```

- [ ] **Step 5: Run async behavior tests**

  Run: `just test tests/test_circuit_breaker.py`
  Expected: PASS (new rate tests + all classic tests unchanged).

- [ ] **Step 6: Add + run sync mirror tests**

  Read `tests/test_circuit_breaker_sync.py` to match its `_Clock`/client helpers,
  then append sync mirrors of the three Step-1 tests (no `async`/`await`,
  `CircuitBreaker` + sync `Client`). Run:
  `just test tests/test_circuit_breaker_sync.py`
  Expected: PASS. (Rate logic lives in the shared state, so the sync wrapper
  needs no extra code — only the param threading from Task 2 Step 5.)

- [ ] **Step 7: Full suite + lint**

  Run: `just test && just lint`
  Expected: all green, lint clean.

- [ ] **Step 8: Commit**

  ```bash
  git add src/httpware/middleware/resilience/circuit_breaker.py tests/test_circuit_breaker.py tests/test_circuit_breaker_sync.py
  git commit -m "feat(circuit-breaker): rate-over-window trip mode

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 4: Rate-mode observability assertion

Lock in the `circuit.opened` rate attributes with a test (the implementation
already emits them via `_open_rate` from Task 3 — this task proves it).

`_emit_event` (see `tests/test_observability.py`) exposes the event name on the
log record as `record.event` and each attribute as a direct record attribute
(e.g. `record.failure_rate_threshold`), so we assert via `caplog.records`. `ty`
flags these dynamic attributes — suppress with `# ty: ignore[unresolved-attribute]`
exactly as `test_observability.py` does.

**Files:**
- Test: `tests/test_circuit_breaker.py` (add — it already has `_Clock`,
  `_StatusSequence`, `_client`, `logging`, and the error imports)

- [ ] **Step 1: Write the failing test**

  Append to `tests/test_circuit_breaker.py`:

  ```python
  async def test_rate_mode_open_event_carries_rate_attributes(caplog: pytest.LogCaptureFixture) -> None:
      """circuit.opened in rate mode carries rate attributes, not the classic ones."""
      clock = _Clock()
      breaker = AsyncCircuitBreaker(
          failure_rate_threshold=0.5, window_seconds=100.0, minimum_calls=4, _now=clock
      )
      # 2 failures then 2 successes → total 4 (meets minimum_calls), rate 2/4 = 0.5 → opens
      client = _client(_StatusSequence([500, 500, 200, 200]), breaker=breaker)
      with caplog.at_level(logging.WARNING, logger="httpware.circuit_breaker"):
          for _ in range(2):
              with pytest.raises(InternalServerError):
                  await client.get("https://example.test/x")
          for _ in range(2):
              await client.get("https://example.test/x")
      opened = [r for r in caplog.records if r.event == "circuit.opened"]  # ty: ignore[unresolved-attribute]
      assert opened, "expected a circuit.opened record"
      rec = opened[-1]
      assert rec.failure_rate_threshold == 0.5  # ty: ignore[unresolved-attribute]
      assert rec.observed_calls >= 4  # ty: ignore[unresolved-attribute]
      assert hasattr(rec, "failure_rate")
      assert not hasattr(rec, "failure_threshold")  # classic attribute absent in rate mode
  ```

  NOTE: `_StatusSequence` returns 200 once its list is exhausted, so a single
  shared `client` serves all four calls; the breaker instance carries the state.

- [ ] **Step 2: Run to verify it passes (impl already emits these)**

  Run: `just test tests/test_circuit_breaker.py::test_rate_mode_open_event_carries_rate_attributes`
  Expected: PASS — `_open_rate` (Task 3) already emits these attributes. If it
  FAILS on attribute access, fix the test to match the real record surface
  (compare against `tests/test_observability.py`), not the implementation.

- [ ] **Step 3: Full suite + lint**

  Run: `just test && just lint`
  Expected: green, clean.

- [ ] **Step 4: Commit**

  ```bash
  git add tests/test_circuit_breaker.py
  git commit -m "test(circuit-breaker): assert rate-mode circuit.opened attributes

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 5: Docs + release notes (0.13.0)

Document rate mode and cut the release notes. Version is **tag-driven** — do NOT
edit `pyproject.toml` (the static `version` field stays at the placeholder `"0"`;
`publish.yml` runs `uv version` from the `0.13.0` tag at release).

**Files:**
- Modify: `architecture/resilience.md`, `docs/resilience.md`
- Create: `planning/releases/0.13.0.md`

- [ ] **Step 1: Update architecture/resilience.md**

  Read the `## CircuitBreaker + AsyncTimeout` section and add a paragraph: the
  opt-in time-based rate mode — set `failure_rate_threshold` (0–1] to switch from
  classic consecutive-failure to "open when the failure rate over a rolling
  `window_seconds` (default 30s) meets the threshold, once `minimum_calls`
  (default 20) outcomes are observed". Note: classic stays the default;
  `failure_threshold` is ignored in rate mode; half-open recovery and event names
  are identical; `circuit.opened` carries rate attributes in rate mode. No
  frontmatter (living prose).

- [ ] **Step 2: Update docs/resilience.md**

  Read the circuit-breaker section of `docs/resilience.md` and add a short
  user-facing subsection with a code example:

  ```python
  from httpware import AsyncClient
  from httpware.middleware.resilience.circuit_breaker import AsyncCircuitBreaker

  breaker = AsyncCircuitBreaker(
      failure_rate_threshold=0.5,  # open at ≥50% failures
      window_seconds=30.0,         # over a rolling 30s window
      minimum_calls=20,            # but only once 20+ calls are observed
  )
  ```

  Explain when to prefer rate mode (partial/intermittent degradation a
  consecutive-failure breaker misses) and that classic is the default. Match the
  page's existing voice and fence style.

- [ ] **Step 3: Write the release notes**

  Read `planning/releases/0.12.0.md` for voice/structure. Create
  `planning/releases/0.13.0.md`: minor, additive-only; the opt-in time-based
  failure-rate trip mode on `AsyncCircuitBreaker` / `CircuitBreaker`
  (`failure_rate_threshold` + `window_seconds` + `minimum_calls`); classic stays
  default and unchanged; same event names with rate attributes on
  `circuit.opened`; no head/options-style scope creep; explicitly note count-based
  windows / slow-call axis / manual control remain deferred. Include a usage code
  block. Leave a `## Shipped via` line referencing the PR (number filled at PR
  time).

- [ ] **Step 4: Verify docs build + full gate**

  Run: `uvx --with-requirements docs/requirements.txt mkdocs build --strict`
  Expected: clean; then `rm -rf site`.
  Run: `just test && just lint` — green, clean.

- [ ] **Step 5: Commit**

  ```bash
  git add architecture/resilience.md docs/resilience.md planning/releases/0.13.0.md
  git commit -m "docs(circuit-breaker): document rate mode; 0.13.0 release notes

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

## Ship bookkeeping (after merge)

Per the planning convention: set this bundle's `design.md` + `plan.md`
frontmatter to `status: shipped` with the PR number, move
`changes/active/2026-06-16.02-circuit-breaker-rate-mode/` to `changes/`,
flip its Index line from Active to Archived, and remove the now-closed
"CircuitBreaker v2" item from `planning/deferred.md` (or trim it to just the
still-deferred parts: count-based windows, manual control + state, slow-call
axis). Release 0.13.0 by creating the `0.13.0` GitHub release (tag-driven publish).

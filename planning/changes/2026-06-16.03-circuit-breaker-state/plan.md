# circuit-breaker-state — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps
> use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose the circuit breaker's state via a public `CircuitState` enum
and a read-only `state` property on `AsyncCircuitBreaker` / `CircuitBreaker`.

**Architecture:** Promote the existing private `_CircuitState` enum to public
`CircuitState`, export it (resilience package + top-level `httpware`), and add a
pure read-only `state` property to the shared `_CircuitBreakerState` and both
wrappers. No behavior change; raw stored-state read (no clock, no lock).

**Tech Stack:** Python 3.11+, `httpx2`, `pytest` (asyncio auto mode), injected
`_now` clock for deterministic state tests.

**Spec:** [`design.md`](./design.md)

**Branch:** `feat/circuit-breaker-state`

**Commit strategy:** Per-task commits.

---

### Task 1: Promote `CircuitState`, add the `state` property, export it

**Files:**
- Modify: `src/httpware/middleware/resilience/circuit_breaker.py`
- Modify: `src/httpware/middleware/resilience/__init__.py`
- Modify: `src/httpware/__init__.py`
- Test: `tests/test_circuit_breaker.py`, `tests/test_circuit_breaker_sync.py`, `tests/test_public_api.py`

- [ ] **Step 1: Write the failing tests (async behavior + public API)**

  Append to `tests/test_circuit_breaker.py` (reuses `_Clock`, `_StatusSequence`, `_client`, `InternalServerError`, `CircuitOpenError`, `HTTPStatus`, `pytest`; add `CircuitState` to the existing `from httpware...` import or import it via `from httpware import CircuitState`):

  ```python
  from httpware import CircuitState


  async def test_state_closed_open_and_raw_read_caveat() -> None:
      clock = _Clock()
      breaker = AsyncCircuitBreaker(failure_threshold=2, reset_timeout=10.0, success_threshold=1, _now=clock)
      assert breaker.state is CircuitState.CLOSED
      client = _client(_StatusSequence([500, 500]), breaker=breaker)
      for _ in range(2):
          with pytest.raises(InternalServerError):
              await client.get("https://example.test/x")
      assert breaker.state is CircuitState.OPEN
      # raw-read caveat: reset_timeout elapses but NO request is made → still OPEN
      clock.advance(10.0)
      assert breaker.state is CircuitState.OPEN
      # the next request is admitted as the probe and (success_threshold=1) closes the circuit
      ok = _client(_StatusSequence([200]), breaker=breaker)
      assert (await ok.get("https://example.test/x")).status_code == HTTPStatus.OK
      assert breaker.state is CircuitState.CLOSED


  async def test_state_half_open_while_probing() -> None:
      clock = _Clock()
      breaker = AsyncCircuitBreaker(failure_threshold=1, reset_timeout=5.0, success_threshold=2, _now=clock)
      fail = _client(_StatusSequence([500]), breaker=breaker)
      with pytest.raises(InternalServerError):
          await fail.get("https://example.test/x")
      assert breaker.state is CircuitState.OPEN
      clock.advance(5.0)
      ok = _client(_StatusSequence([200, 200]), breaker=breaker)
      await ok.get("https://example.test/x")  # admitted as probe; 1 success, needs 2 → HALF_OPEN
      assert breaker.state is CircuitState.HALF_OPEN
      await ok.get("https://example.test/x")  # 2nd consecutive success → CLOSED
      assert breaker.state is CircuitState.CLOSED
  ```

  Add to `tests/test_public_api.py`: insert `"CircuitState",` into the `expected` set in `test_expected_exports`, keeping alphabetical order — it sorts after `"CircuitOpenError"` and before `"Client"` (`CircuitState` < `Client` because `Circ` < `Cli`). Then add a focused test:

  ```python
  def test_circuit_state_exported() -> None:
      from httpware import CircuitState
      from httpware.middleware.resilience import CircuitState as ResilienceCircuitState

      assert CircuitState is ResilienceCircuitState
      assert {m.value for m in CircuitState} == {"closed", "open", "half_open"}
  ```

- [ ] **Step 2: Run to verify failure**

  Run: `just test tests/test_circuit_breaker.py -k state && just test tests/test_public_api.py -k circuit_state`
  Expected: FAIL — `ImportError: cannot import name 'CircuitState'` / `AttributeError: ... has no attribute 'state'`.

- [ ] **Step 3: Promote the enum**

  In `src/httpware/middleware/resilience/circuit_breaker.py`, rename the class `_CircuitState` to `CircuitState` and update EVERY reference (there are ~11: the class def plus `_CircuitState.CLOSED` / `.OPEN` / `.HALF_OPEN` usages in `admit`, `on_success`, `on_failure`, `_enter_open`, and `__init__`). Keep the `str` values unchanged:

  ```python
  class CircuitState(enum.Enum):
      CLOSED = "closed"
      OPEN = "open"
      HALF_OPEN = "half_open"
  ```

  After editing, confirm zero stragglers: `grep -n "_CircuitState" src/httpware/middleware/resilience/circuit_breaker.py` must return nothing.

- [ ] **Step 4: Add the `state` property to `_CircuitBreakerState` and both wrappers**

  On `_CircuitBreakerState` (the stored state lives in `self._state: CircuitState`), add:

  ```python
      @property
      def state(self) -> CircuitState:
          """The circuit's current stored state (raw read; no lazy OPEN→HALF_OPEN transition)."""
          return self._state
  ```

  On BOTH `AsyncCircuitBreaker` and `CircuitBreaker`, add (the wrapper holds the breaker-state object in `self._state`):

  ```python
      @property
      def state(self) -> CircuitState:
          """Current circuit state — CLOSED, OPEN, or HALF_OPEN. Read-only, side-effect-free."""
          return self._state.state
  ```

  NOTE: in the wrappers, `self._state` is the `_CircuitBreakerState` instance, so `self._state.state` reads its new property. Do not take the lock for this read.

- [ ] **Step 5: Export `CircuitState`**

  In `src/httpware/middleware/resilience/__init__.py`: add `CircuitState` to the `from httpware.middleware.resilience.circuit_breaker import ...` line (it currently imports `AsyncCircuitBreaker, CircuitBreaker`) and add `"CircuitState"` to `__all__` (keep alphabetical — between `"Bulkhead"`/`"CircuitBreaker"` ordering: it sorts after `CircuitBreaker`? No — `CircuitBreaker` < `CircuitState` alphabetically, so `"CircuitState"` goes right after `"CircuitBreaker"`).

  In `src/httpware/__init__.py`: add `CircuitState` to the `from httpware.middleware.resilience import (...)` block and add `"CircuitState"` to `__all__` (right after `"CircuitBreaker"`, before `"CircuitOpenError"` — confirm alphabetical: CircuitBreaker, CircuitOpenError, CircuitState → actually `CircuitOpenError` < `CircuitState` since 'O' < 'S'; place `"CircuitState"` AFTER `"CircuitOpenError"`).

- [ ] **Step 6: Run the async + public-API tests**

  Run: `just test tests/test_circuit_breaker.py tests/test_public_api.py`
  Expected: PASS (new state tests + export tests + all existing breaker/public-api tests).

- [ ] **Step 7: Add the sync mirror tests**

  Read `tests/test_circuit_breaker_sync.py` for its `_Clock`/client helpers + imports, then append sync mirrors of the two Step-1 behavior tests (no `async`/`await`, `CircuitBreaker` + sync client helper, `from httpware import CircuitState`). Same assertions and structure.

  Run: `just test tests/test_circuit_breaker_sync.py`
  Expected: PASS. (The `state` property on `CircuitBreaker` delegates to the shared `_CircuitBreakerState`, so no extra production code beyond Step 4.)

- [ ] **Step 8: Full suite + lint**

  Run: `just test && just lint`
  Expected: all green, 100% coverage, lint clean. (`ty` will confirm the enum rename left no dangling `_CircuitState` reference.)

- [ ] **Step 9: Commit**

  ```bash
  git add src/httpware/middleware/resilience/circuit_breaker.py src/httpware/middleware/resilience/__init__.py src/httpware/__init__.py tests/test_circuit_breaker.py tests/test_circuit_breaker_sync.py tests/test_public_api.py
  git commit -m "feat(circuit-breaker): public CircuitState enum + read-only state property

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 2: Docs + release notes (0.14.0)

Version is **tag-driven** — do NOT edit `pyproject.toml` (the field stays `"0"`; the release workflow runs `uv version` from the `0.14.0` tag).

**Files:**
- Modify: `architecture/resilience.md`, `docs/resilience.md`
- Create: `planning/releases/0.14.0.md`

- [ ] **Step 1: Update architecture/resilience.md**

  In the `## CircuitBreaker + AsyncTimeout` section, add a sentence: both breakers expose a read-only `state` property returning a public `CircuitState` enum (`CLOSED`/`OPEN`/`HALF_OPEN`) for health checks and introspection. Note it is a raw read of the stored state — because the OPEN→HALF_OPEN transition is lazy (on the next request after `reset_timeout`), `state` reports `OPEN` until a request is actually admitted as the probe; it never triggers the transition. No frontmatter (living prose).

- [ ] **Step 2: Update docs/resilience.md**

  Add a short subsection (after the rate-mode subsection, before Sharing) showing the property with a health-check framing:

  ```python
  from httpware import CircuitState
  from httpware.middleware.resilience import AsyncCircuitBreaker

  breaker = AsyncCircuitBreaker(failure_threshold=5)
  # ... later, in a health/readiness handler:
  if breaker.state is CircuitState.OPEN:
      ...  # report the dependency as degraded
  ```

  Explain it's read-only and reflects the stored state (with the lazy-transition caveat: `OPEN` persists until the next request after `reset_timeout`). Match the page's voice and the `from httpware.middleware.resilience import ...` import style used elsewhere on the page.

- [ ] **Step 3: Write the release notes**

  Read `planning/releases/0.13.0.md` for voice/structure. Create `planning/releases/0.14.0.md`: minor, additive-only, no breaking changes. Cover: new public `CircuitState` enum + read-only `state` property on both `AsyncCircuitBreaker` and `CircuitBreaker`; raw stored-state semantics (lazy-transition caveat); use case (health/readiness checks, dashboards, tests). Note manual control (`force_open`/`force_closed`) remains deferred. Usage code block. End with `## Shipped via` line `PR #XX — read-only circuit-breaker state introspection.` (literal `#XX` placeholder; filled at PR time). American spelling, single spaces after periods.

- [ ] **Step 4: Verify docs build + full gate**

  Run: `uvx --with-requirements docs/requirements.txt mkdocs build --strict`
  Expected: clean (the Material 2.0 banner is unrelated). Then `rm -rf site`.
  Run: `just test && just lint` — green, 100% coverage, clean.

- [ ] **Step 5: Commit**

  ```bash
  git add architecture/resilience.md docs/resilience.md planning/releases/0.14.0.md
  git commit -m "docs(circuit-breaker): document state introspection; 0.14.0 release notes

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

## Ship bookkeeping (after merge)

Per the planning convention: set this bundle's `design.md` + `plan.md` to
`status: shipped` with the PR number, fill the `## Shipped via` PR number in the
release notes, move `changes/active/2026-06-16.03-circuit-breaker-state/` to
`changes/`, flip its Index line from Active to Archived, and update the
deferred CircuitBreaker entry — drop the read-only `state` half (now shipped),
leaving only manual control (`force_open`/`force_closed`). Release 0.14.0 by
creating the `0.14.0` GitHub release (tag-driven publish).

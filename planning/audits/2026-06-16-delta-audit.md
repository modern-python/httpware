# httpware delta audit — 2026-06-16

**Status:** complete
**Scope:** the four changes shipped since the 2026-06-14 deep audit (baseline `9297ced`): the custom-decoder guide (#67), per-verb `*_with_response` siblings + the `_prepare_request` refactor (#68, 0.12.0), the time-based rate-mode circuit breaker (#69, 0.13.0), and read-only circuit-breaker `state` + the public `CircuitState` enum (#70, 0.14.0).
**Method:** five adversarial finders fanned out across dimensions — correctness/edge-cases, concurrency, public-API/consistency, docs-accuracy, test-quality — each instructed to refute its own candidates and report only survivors. Single synthesis pass (this report); the controller re-verified the one substantive finding against source.

## Summary

A clean delta. Four of five dimensions produced **zero** confirmed findings: every correctness, concurrency, public-API, and docs-accuracy candidate was refuted against the actual code. The only residue is in test coverage.

- Blockers: 0
- High: 0
- Medium: 0
- Low: 2
- Nits: 1

**Headline:** there is no headline defect. The accumulated 0.12–0.14 surface (per-verb siblings, rate-mode breaker, `state` introspection) is correct, concurrency-safe under the documented model, API-consistent and sync/async-symmetric, and its docs match the code — including the rate-mode defaults, the `(0,1]` range, the `failure_threshold`-ignored / both-set-precedence notes, and the raw-read `state` caveat. The two Low findings are a missing rate-mode test path and a minor observability-attribute inconsistency on one re-open path.

**Not covered:** static analysis only (source/test/doc reading + reproducer reasoning + targeted `ty`/import checks). No fuzzing, live-network, or dependency-CVE scan. The full suite (704 tests, 100% line coverage) and `ty`/`ruff` were green throughout — line coverage is total, so the test-quality finder targeted *semantic* gaps.

## Findings

### Low

#### 1. Rate-mode HALF_OPEN probe-failure re-open emits classic `circuit.opened` attributes
*(consistency / observability — verified against source)*

`src/httpware/middleware/resilience/circuit_breaker.py` — `on_failure`, HALF_OPEN branch (`self._open(request, failures=1)`)

When a circuit is in HALF_OPEN, a single probe failure re-opens it via `_open(request, failures=1)` — the *classic* opener, which emits `circuit.opened` with `{failure_threshold, failures}` and the message `"circuit opened — failure threshold reached"`. This path is shared across modes, so a **rate-mode** breaker that re-opens from a failed probe emits classic-shaped attributes rather than the rate shape (`failure_rate`/`failure_rate_threshold`/`window_seconds`/`observed_calls`) it emits when it first trips from CLOSED. An observability consumer keying off `circuit.opened` attributes sees an inconsistent attribute set from the same breaker depending on which transition opened it, and `failure_threshold` — documented as *ignored* in rate mode — appears in the event.

Capped at Low: reachable only under the non-default rate knob, affects event *attributes* only (no control-flow effect — the re-open itself is correct), and half-open recovery is documented as mode-independent, so this is arguably acceptable. **Suggested direction:** either (a) document that a probe-failure re-open always carries the probe-failure attribute shape regardless of mode, or (b) emit a transition-specific attribute set for the half-open re-open (e.g. a `reason: "probe_failed"` attribute) so the event is self-describing in both modes. Not a functional bug.

Note: the window is *not* cleared on this re-open (only on HALF_OPEN→CLOSED). That is harmless — while OPEN/HALF_OPEN no outcomes are recorded, and the window is cleared when the circuit eventually closes (confirmed by the correctness finder).

#### 2. No rate-mode probe-failure re-open test
*(test coverage — verified)*

`tests/test_circuit_breaker.py` / `tests/test_circuit_breaker_sync.py` (rate-mode section)

Every rate-mode recovery test drives HALF_OPEN→CLOSED through a *successful* probe. No rate-mode test exercises a probe *failure* re-opening the circuit. The classic equivalent (`test_probe_failure_reopens_circuit`) exists but runs in consecutive-failure mode, so it never touches the rate-mode opener selection or the window. A regression in the rate-mode re-open path (the very behavior in finding 1) would pass the suite. Line coverage is 100% because the classic tests already cover the shared `_open` line — this is a *semantic* gap. **Suggested direction:** add a rate-mode test (async + sync) that opens via rate, advances past `reset_timeout`, fails the probe, and asserts the circuit re-opens; assert whatever attribute behavior finding 1 settles on.

### Nits

#### 3. `_RollingWindow` Hypothesis oracle shares the slot formula with the implementation
*(test quality)*

`tests/test_rolling_window.py` — `test_totals_match_live_events`

The property's `expected_live` oracle recomputes `int(t // bucket_width)` and the live-cutoff with the same arithmetic as `_RollingWindow`, so a systematic off-by-one in the window-boundary formula would be replicated in the oracle and the property would still pass. Largely neutralized: the example tests (`test_counts_within_window`, `test_stale_buckets_evicted_by_time`) pin the boundary with hand-computed literals the implementation can't co-vary with, and the property still exercises bucket-collision/eviction interleavings. Nit only.

## Refuted (recorded so the reasoning is auditable)

- **Correctness:** `_prepare_request` is byte-equivalent to the old inline logic (kwargs order, marker, sync/async streaming-detector split all preserved); all 12 verb delegations use the correct verb string and kwarg subset; rate trip math has no division-by-zero (guarded by `minimum_calls >= 1`); `_RollingWindow` slot aliasing is sound (live window spans exactly `_BUCKET_COUNT` slots → no live-bucket collision mod 10); `state` is a pure read.
- **Concurrency:** no `await` anywhere in the async transition chain (`_record_outcome`→`_open_rate`→`_enter_open`→`_emit`→`_emit_event` all sync); `_now()` read once inside the critical section; sync rate path fully under `self._lock`; lock-free `state` read is a single atomic enum-reference load (no tear).
- **Public API:** `*_with_response` correctly overload-free (single return shape), `response_model` required, exact sync/async parity; new breaker params identical on both wrappers; `CircuitState` is one object exported from both `__all__`s, alphabetical; `ty` clean.
- **Docs accuracy:** every load-bearing claim across `docs/decoders.md`, `docs/resilience.md`, the pagination recipe, and the three `architecture/` files verified against source — defaults, ranges, precedence, the raw-read caveat, import paths, and the CSV example all match and run.

## Remediation

Findings 1 + 2 are naturally one small change: add the rate-mode probe-failure re-open test (sync + async) and, in the same pass, settle finding 1 (document-as-intended or add a self-describing re-open attribute). Lightweight lane. Finding 3 is a Nit — optional.

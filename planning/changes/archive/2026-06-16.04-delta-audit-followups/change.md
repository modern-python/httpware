---
status: shipped
date: 2026-06-16
slug: delta-audit-followups
supersedes: null
superseded_by: null
pr: 71
outcome: Closed the 2026-06-16 delta-audit Low findings — rate-mode probe-failure re-open test (async+sync) + document-as-intended note. No source behavior change.
---

# Change: Close the 2026-06-16 delta-audit Low findings

**Lane:** lightweight — tests + a one-paragraph doc clarification, no source
behavior change, no public-API change.

Closes the actionable findings from the
[2026-06-16 delta audit](../../../audits/2026-06-16-delta-audit.md), which gave
the 0.12–0.14 change cluster a clean bill (0 Blocker/High/Medium) with two Low
items and a Nit.

## Goal

Lock and document the one behavioral subtlety the audit surfaced: a rate-mode
circuit that re-opens from a **failed HALF_OPEN probe** emits `circuit.opened`
with the *classic* `failure_threshold`/`failures` attributes (not the rate
shape), because the half-open re-open path is shared and calls the classic
`_open`. Per the audit's resolution (Option 1 — **document as intended**): a
probe-failure re-open is a distinct event from a trip, so the classic shape is
correct in both modes. No code behavior changes.

## Approach

- **Low #1 (observability, document-as-intended):** append a sentence to the
  CircuitBreaker section of `architecture/resilience.md` stating that the
  rate-flavored `circuit.opened` fires only on the initial trip from CLOSED, and
  that a HALF_OPEN probe-failure re-open carries the classic
  `failure_threshold`/`failures` (`failures = 1`) attributes and message in
  *both* modes — intentional, event-name is the stable contract.
- **Low #2 (test gap):** add `test_rate_mode_probe_failure_reopens_with_classic_attributes`
  (async + sync mirror) — trip via rate, advance past `reset_timeout`, fail the
  probe, assert the circuit re-opens AND the re-open `circuit.opened` carries the
  classic shape (`failures == 1`, has `failure_threshold`, NOT `failure_rate`).
  This locks the Low #1 behavior so a regression can't pass silently.
- **Nit #3 (Hypothesis oracle coupling):** not actioned — already neutralized by
  the hand-computed example tests; recorded in the audit as a Nit.

No `pyproject.toml` change; no release required (tests + doc clarification only,
no user-facing functionality or API change). The audit report itself is added
under `planning/audits/`.

## Files

- `planning/audits/2026-06-16-delta-audit.md` — the findings report (added).
- `architecture/resilience.md` — the document-as-intended paragraph.
- `tests/test_circuit_breaker.py` — async probe-failure re-open test.
- `tests/test_circuit_breaker_sync.py` — sync mirror.

## Verification

- [x] Both new tests fail-safe (assert the actual emitted attribute set) and pass:
      `just test ...::test_rate_mode_probe_failure_reopens_with_classic_attributes`.
- [x] `just test` — 706 passed, 100% coverage.
- [x] `just lint` — clean.
- [x] No source behavior change (only tests + docs).

# Retry + Retry Budget

A transient blip should be retried — but a *sustained* outage retried blindly turns
one failure into a retry storm that amplifies the outage. httpware retries with
full-jitter backoff, and a **budget** caps the share of traffic spent on retries so
a dead backend can't be amplified.

<div class="hw-demo" id="retry-demo"></div>

<p>That was <b>one</b> client. The real danger of blind retries shows up at scale — when <b>many</b> clients retry the same outage at once.</p>

<div class="hw-demo" id="retry-herd"></div>

<script>
document.addEventListener('DOMContentLoaded', function () {
  HttpwareDemo.mount('#retry-demo', {
  scenarios: [
    { id: 'blip', label: 'Brief blip (recovers)', dur: 12.5,
      fault: (now, rnd) => (now >= 2.0 && now < 2.4)
        ? { ok: false, ms: 0.05, label: 'blip' } : { ok: true, ms: 0.05 },
      chainB: { retry: { maxAttempts: 3, baseDelay: 0.1, maxDelay: 5.0 },
                budget: { ttl: 10.0, minRetriesPerSec: 10.0, percentCanRetry: 0.2 } } },
    { id: 'sustained', label: 'Sustained outage', dur: 12.5,
      fault: (now) => (now >= 2.0 && now < 9.0)
        ? { ok: false, ms: 0.05, label: 'DOWN' } : { ok: true, ms: 0.05 },
      chainB: { retry: { maxAttempts: 3, baseDelay: 0.1, maxDelay: 5.0 },
                budget: { ttl: 10.0, minRetriesPerSec: 10.0, percentCanRetry: 0.2 } } },
  ],
  buildStops: (scenario) => scenario.id === 'sustained' ? [
    { when: (s) => s.now >= 1.2, spot: ['ifA', 'ifB'], title: 'A backend blip appears',
      body: 'Both clients hit the same transient errors. Watch how each responds.' },
    { when: (s) => s.now >= 2.4, spot: ['ifB'], title: 'httpware retries the blip',
      body: 'The plain client surfaces the error immediately. httpware retries with backoff — most of these recover on attempt 2 or 3, invisibly to the caller.' },
    { when: (s) => s.mw.budgetExhausted, spot: ['ifB'], title: 'The budget refuses to amplify',
      body: 'On a SUSTAINED outage, blind retries would multiply load. The budget is spent — httpware STOPS retrying and fails fast, protecting the dying backend instead of hammering it.' },
    { when: (s) => s.now >= 10.0, spot: ['ifA', 'ifB'], title: 'Blip: recovered. Outage: contained',
      body: 'Retry rescues transient errors without turning a real outage into a storm. That cap is the whole reason the budget exists.' },
  ] : [
    { when: (s) => s.now >= 1.2, spot: ['badWrapA', 'badWrapB'], title: 'A backend blip appears',
      body: 'Both clients are about to hit the same transient errors. Keep your eye on the ✗ failed counts — they start equal at zero.' },
    { when: (s) => s.now >= 2.4, spot: ['badWrapA', 'badWrapB'], title: 'Plain surfaces every error; httpware retries',
      body: 'The plain client surfaces each error straight to the caller — its ✗ is climbing. httpware retries with backoff, so most of these recover on attempt 2 or 3 and its ✗ barely moves.' },
    { when: (s) => s.now >= 10.0, spot: ['badWrapA', 'badWrapB'], title: 'Blip over — mind the ✗ gap',
      body: 'The backend healed. Compare the ✗ failed counts: the plain client surfaced far more failures than httpware. That gap is exactly what retry buys you on a transient blip.' },
  ],
  });

  HttpwareDemo.mountHerd('#retry-herd', {
    clients: 20,
    scenario: { id: 'storm', dur: 12.5,
      fault: (now) => (now >= 2.0 && now < 9.0)
        ? { ok: false, ms: 0.05, label: 'DOWN' } : { ok: true, ms: 0.05 } },
    retry: { maxAttempts: 3, baseDelay: 0.1, maxDelay: 5.0 },
    budget: { ttl: 10.0, minRetriesPerSec: 10.0, percentCanRetry: 0.2 },
    buildStops: (sim) => [
      { when: (s) => s.revealed >= Math.round(2.2 / sim.dt), spot: ['naiveStrip', 'hwStrip'],
        title: 'The outage hits both herds',
        body: 'Twenty naive clients and twenty httpware clients face the same sustained outage. Every failed request wants to retry. Watch what each herd does to the backend call-rate.' },
      { when: (s) => s.revealed >= Math.round(4.0 / sim.dt), spot: ['naiveStrip'],
        title: 'Naive: synchronized spikes',
        body: 'All twenty naive clients back off the SAME fixed delay, so a batch that fails together retries together — the failures never spread out. Tall spikes with dead gaps between: the retry storm hammering a backend that is already down.' },
      { when: (s) => s.revealed >= Math.round(6.5 / sim.dt), spot: ['hwStrip'],
        title: 'httpware: a near-flat rate',
        body: 'Full jitter scatters each client’s retries across the window instead of stacking them, and each client’s own budget + max_attempts cap how much it can add — so the aggregate holds at a low, steady few-times-baseline instead of exploding.' },
      { when: (s) => s.revealed >= sim.buckets - 1, spot: ['naiveMult', 'hwMult'],
        title: 'Peak load: the whole point',
        body: 'The naive herd peaked at about 70× the healthy load — and keeps climbing the longer the outage runs, because its retries are unbounded. httpware peaked at about 3×: at this client count, that ceiling comes from each client’s own max_attempts=3 cap (jitter just spreads the retries flat instead of stacking them). The per-client budget is what holds the line as the herd grows even larger. Same outage, same client count — a flat rate also leaves the backend room to recover.' },
    ],
  });
});
</script>

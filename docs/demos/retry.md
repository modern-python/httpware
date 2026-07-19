# Retry + Retry Budget

A transient blip should be retried — but a *sustained* outage retried blindly turns
one failure into a retry storm that amplifies the outage. httpware retries with
full-jitter backoff, and a **budget** caps the share of traffic spent on retries so
a dead backend can't be amplified.

<div class="hw-demo" id="retry-demo"></div>

<p>That was <b>one</b> client recovering from a blip. The real danger of blind retries shows up at <b>scale</b> — when many clients hit a real outage at once.</p>

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
  ],
  buildStops: () => [
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
    intro: 'Retry rescues a transient blip (above) — but it can’t fix an <i>outage</i>: retried or not, the caller sees the same failures. There the danger isn’t caller failures, it’s <b>amplification</b>. A real backend rarely dies cleanly — it <b>flaps</b>: fails, recovers, fails again. These strips show <b>backend call-rate over time</b> for twenty clients through three dips. Press play and watch the shape.',
    scenario: { id: 'storm', dur: 12.5,
      fault: (now) => {
        const down = (now >= 2.0 && now < 4.0) || (now >= 5.5 && now < 7.5) || (now >= 9.0 && now < 11.0);
        return down ? { ok: false, ms: 0.05, label: 'DOWN' } : { ok: true, ms: 0.05 };
      } },
    retry: { maxAttempts: 3, baseDelay: 0.1, maxDelay: 5.0 },
    budget: { ttl: 10.0, minRetriesPerSec: 10.0, percentCanRetry: 0.2 },
    buildStops: (sim) => [
      { when: (s) => s.revealed >= Math.round(2.2 / sim.dt), spot: ['naiveStrip', 'hwStrip'],
        title: 'A flapping backend',
        body: 'The backend drops, recovers, drops again — three dips (shaded). Every failed request wants to retry. Watch what each herd does to the backend call-rate through the dips.' },
      { when: (s) => s.revealed >= Math.round(4.6 / sim.dt), spot: ['naiveStrip'],
        title: 'Naive: a surge on every dip',
        body: 'On each dip, twenty clients retry unbounded — the load piles up into a surge that keeps climbing until the backend recovers, then clears. Three dips, three spikes, with recovery gaps between: the retry storm hitting a backend every time it tries to come back.' },
      { when: (s) => s.revealed >= Math.round(8.2 / sim.dt), spot: ['hwStrip'],
        title: 'httpware: flat through every dip',
        body: 'Full jitter spreads each client’s retries out, and each client’s own max_attempts=3 cap (with its per-client budget as the guarantee at higher volume) limits how much it can add — so httpware holds a low, steady few-times-baseline through every dip instead of spiking.' },
      { when: (s) => s.revealed >= sim.buckets - 1, spot: ['naiveMult', 'hwMult'],
        title: 'Peak load: the whole point',
        body: 'On its worst dip the naive herd spiked to about 18× the healthy load; httpware never exceeded about 3×, capped by each client’s max_attempts. That flat rate is exactly what lets the backend recover in the gaps — instead of being knocked back down by a retry surge every time it heals.' },
    ],
  });
});
</script>

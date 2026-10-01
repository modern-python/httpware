# Retry and retry budget

A transient blip should be retried, but blindly retrying a sustained outage multiplies
the load on a backend that is already failing. httpware retries with full-jitter
backoff, and a budget caps the share of traffic spent on retries.

<div class="hw-demo" id="retry-demo"></div>

<p>That was one client recovering from a blip. Blind retries do the most harm at scale, when many clients hit a real outage at once.</p>

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
    { when: (s) => s.now >= 1.2, spot: ['badWrapA', 'badWrapB'], title: 'A backend blip is coming',
      body: 'Both clients are about to hit the same transient errors. Watch the ✗ failed counts, which both start at zero.' },
    { when: (s) => s.now >= 2.4, spot: ['badWrapA', 'badWrapB'], title: 'Plain surfaces every error; httpware retries',
      body: 'The plain client passes each error to the caller, so its ✗ count climbs. httpware retries with backoff, most calls succeed on attempt 2 or 3, and its ✗ count barely moves.' },
    { when: (s) => s.now >= 10.0, spot: ['badWrapA', 'badWrapB'], title: 'Blip over: compare the ✗ counts',
      body: 'The backend has recovered. The plain client surfaced far more failures than httpware; the difference is what retry saves on a transient blip.' },
  ],
  });

  HttpwareDemo.mountHerd('#retry-herd', {
    clients: 20,
    intro: 'Retry recovers a transient blip, as above, but not an <i>outage</i>: retried or not, the caller sees the same failures. During an outage the risk is <b>amplification</b>. Real backends rarely fail cleanly; they <b>flap</b>, failing, recovering and failing again. These strips show the <b>backend call rate over time</b> for twenty clients through three dips. Press play and watch the shape.',
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
        body: 'The backend goes down, recovers, and goes down again: three dips, shaded. Every failed request wants a retry. Watch what each group of clients does to the backend call rate during the dips.' },
      { when: (s) => s.revealed >= Math.round(4.6 / sim.dt), spot: ['naiveStrip'],
        title: 'Naive: a surge on every dip',
        body: 'On each dip, twenty clients retry without limit, and the load keeps climbing until the backend recovers. Three dips give three spikes, each hitting the backend just as it tries to come back.' },
      { when: (s) => s.revealed >= Math.round(8.2 / sim.dt), spot: ['hwStrip'],
        title: 'httpware: flat through every dip',
        body: 'Full jitter spreads out the retries of each client, and max_attempts=3 limits how much each client can add, with the per-client budget as the backstop at higher volume. httpware stays at a low, steady few times the baseline through every dip.' },
      { when: (s) => s.revealed >= sim.buckets - 1, spot: ['naiveMult', 'hwMult'],
        title: 'Peak load',
        body: 'At its worst dip the naive group reached about 18× the healthy load; httpware stayed under about 3×, held there by max_attempts. With the load that low, the backend can recover in the gaps instead of being knocked down again by a retry surge.' },
    ],
  });
});
</script>

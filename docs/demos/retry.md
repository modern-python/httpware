# Retry + Retry Budget

A transient blip should be retried — but a *sustained* outage retried blindly turns
one failure into a retry storm that amplifies the outage. httpware retries with
full-jitter backoff, and a **budget** caps the share of traffic spent on retries so
a dead backend can't be amplified.

<div class="hw-demo" id="retry-demo"></div>

<script>
HttpwareDemo.mount('#retry-demo', {
  scenarios: [
    { id: 'blip', label: 'Brief blip (recovers)', dur: 12.5,
      fault: (now, rnd) => (now >= 2.0 && now < 3.2)
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
    { when: (s) => s.now >= 1.2, spot: ['ifA', 'ifB'], title: 'A backend blip appears',
      body: 'Both clients hit the same transient errors. Watch how each responds.' },
    { when: (s) => s.now >= 2.4, spot: ['ifB'], title: 'httpware retries the blip',
      body: 'The plain client surfaces the error immediately. httpware retries with backoff — most of these recover on attempt 2 or 3, invisibly to the caller.' },
    { when: (s) => s.now >= 10.0, spot: ['ifA', 'ifB'], title: 'Blip: recovered',
      body: 'The backend healed and so did both clients — but compare the ✗ counts: httpware surfaced far fewer failures to the caller. That is what retry buys you on a transient blip.' },
  ],
});
</script>

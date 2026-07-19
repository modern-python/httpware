# Timeout (total deadline)

`httpx2`'s per-call timeouts bound a single request — but a retry loop with backoff
can still run for many seconds in total. `AsyncTimeout` bounds the **whole** operation,
including every retry and every backoff sleep, so one call can't blow your latency SLA.

<div class="hw-demo" id="to-demo"></div>

<script>
document.addEventListener('DOMContentLoaded', function () {
  HttpwareDemo.mount('#to-demo', {
  scenarios: [
    { id: 'brownout', label: 'Slow brownout under retry', dur: 12.5,
      fault: (now, rnd) => (now >= 2.0 && now < 9.0)
        ? (rnd() < 0.7 ? { ok: false, ms: 0.8, label: 'erroring' } : { ok: true, ms: 0.8 })
        : { ok: true, ms: 0.05 },
      chainB: { retry: { maxAttempts: 3, baseDelay: 0.1, maxDelay: 5.0 },
                budget: { ttl: 10.0, minRetriesPerSec: 10.0, percentCanRetry: 0.2 },
                timeout: { timeout: 2.0 } } },
  ],
  buildStops: () => [
    { when: (s) => s.now >= 1.2, spot: ['ifB', 'elapsedB'], title: 'Retry helps... but costs time',
      body: 'httpware retries the brownout. Each retry + backoff adds latency. Watch the elapsed clock on in-flight requests.' },
    { when: (s) => s.now >= 3.0, spot: ['latA', 'elapsedB'], title: 'Unbounded retry = unbounded latency',
      body: 'Without a total deadline, a request can churn through every retry and backoff — total wall-clock climbs past any SLA (see the plain lane p99).' },
    { when: (s) => s.mw.timedOut > 0, spot: ['elapsedB'], title: 'The deadline fires',
      body: 'AsyncTimeout caps the WHOLE operation at 2s. A request that would keep retrying past the deadline is cut off with a bounded TimeoutError — predictable latency, always.' },
    { when: (s) => s.now >= 10.0, spot: ['latA', 'elapsedB'], title: 'Bounded tail latency',
      body: 'Retry rescues what it can within budget; the timeout guarantees the tail. Together they bound both failure and latency.' },
  ],
  });
});
</script>

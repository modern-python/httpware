# Full stack: combining the patterns

Real clients combine these patterns, in the recommended order
`AsyncCircuitBreaker -> AsyncTimeout -> AsyncBulkhead -> AsyncRetry -> terminal`.
Here both clients go through an incident in three phases, and each layer handles a
different phase.

<div class="hw-demo" id="fs-demo"></div>

<script>
document.addEventListener('DOMContentLoaded', function () {
  HttpwareDemo.mount('#fs-demo', {
  scenarios: [
    { id: 'incident', label: 'Multi-phase incident', dur: 16.0,
      fault: (now, rnd) => {
        if (now >= 2.0 && now < 5.0) return rnd() < 0.6
          ? { ok: false, ms: 0.6, label: 'brownout' } : { ok: true, ms: 0.6 };
        if (now >= 5.0 && now < 8.0) return { ok: true, ms: 4.0, label: 'latency spike' };
        if (now >= 8.0 && now < 12.0) return { ok: false, ms: 0.3, label: 'hard down' };
        return { ok: true, ms: 0.05 };
      },
      chainB: { circuitBreaker: { failureThreshold: 5, resetTimeout: 2.0, successThreshold: 1 },
                timeout: { timeout: 2.0 },
                bulkhead: { maxConcurrent: 10, acquireTimeout: 0 },
                retry: { maxAttempts: 3, baseDelay: 0.1, maxDelay: 5.0 },
                budget: { ttl: 10.0, minRetriesPerSec: 10.0, percentCanRetry: 0.2 } } },
  ],
  macroStrip: true,
  stageLabel: (now) => now < 2 ? 'healthy'
    : now < 5 ? 'phase 1: brownout'
    : now < 8 ? 'phase 2: latency spike'
    : now < 12 ? 'phase 3: hard down' : 'recovered',
  buildStops: () => [
    { when: (s) => s.now >= 2.4, spot: ['ifB'], title: 'Phase 1: brownout',
      body: 'Retry recovers many of the transient errors, and the budget stops it from adding much load.' },
    { when: (s) => s.now >= 5.4, spot: ['poolB', 'elapsedB'], title: 'Phase 2: latency spike',
      body: 'The bulkhead caps concurrency so the slow upstream cannot exhaust the client, and the timeout ends each operation after 2s.' },
    { when: (s) => s.mw.cb && s.mw.cb.state === 'OPEN', spot: ['brkB'], title: 'Timeouts open the breaker',
      body: 'The breaker sits before the timeout, so each expired deadline counts as a failure. After five in a row the circuit opens, and new calls fail at once instead of waiting 2s on the slow upstream.' },
    { when: (s) => s.now >= 8.5, spot: ['brkB'], title: 'Phase 3: hard down',
      body: 'The circuit stays open through the outage, because each half-open probe fails and reopens it. It sits before the retry layer, so it rejects whole retry sequences and counts one outcome per sequence, not per attempt.' },
    { when: (s) => s.now >= 13.5, spot: ['ifA', 'latA', 'ifB', 'latB'], title: 'Full stack vs none',
      body: 'The plain client fails through every phase. In the httpware client, each layer handles the phase it is built for.' },
  ],
  });
});
</script>

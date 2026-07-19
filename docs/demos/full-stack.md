# Full stack: composing the patterns

Real clients don't use one pattern — they compose. The recommended order is
`AsyncTimeout -> AsyncCircuitBreaker -> AsyncBulkhead -> AsyncRetry -> terminal`.
Here a nasty multi-phase incident hits both clients; watch the layers interlock.

<div class="hw-demo" id="fs-demo"></div>

<script>
document.addEventListener('DOMContentLoaded', function () {
  HttpwareDemo.mount('#fs-demo', {
  scenarios: [
    { id: 'incident', label: 'Multi-phase incident', dur: 16.0,
      fault: (now, rnd) => {
        if (now >= 2.0 && now < 5.0) return { ok: true, ms: 4.0, label: 'latency spike' };
        if (now >= 5.0 && now < 8.0) return rnd() < 0.6
          ? { ok: false, ms: 0.6, label: 'brownout' } : { ok: true, ms: 0.6 };
        if (now >= 8.0 && now < 12.0) return { ok: false, ms: 0.3, label: 'hard down' };
        return { ok: true, ms: 0.05 };
      },
      chainB: { timeout: { timeout: 2.0 },
                circuitBreaker: { failureThreshold: 5, resetTimeout: 2.0, successThreshold: 1 },
                bulkhead: { maxConcurrent: 10, acquireTimeout: 0 },
                retry: { maxAttempts: 3, baseDelay: 0.1, maxDelay: 5.0 },
                budget: { ttl: 10.0, minRetriesPerSec: 10.0, percentCanRetry: 0.2 } } },
  ],
  buildStops: () => [
    { when: (s) => s.now >= 2.4, spot: ['poolB', 'elapsedB'], title: 'Phase 1 — latency spike',
      body: 'Bulkhead caps concurrency so the slow phase can’t exhaust the client; timeout bounds each operation at 2s.' },
    { when: (s) => s.now >= 5.4, spot: ['ifB'], title: 'Phase 2 — brownout',
      body: 'Retry (within budget) recovers many of the transient errors; the budget keeps it from amplifying.' },
    { when: (s) => s.mw.cb && s.mw.cb.state === 'OPEN', spot: ['brkB'], title: 'Phase 3 — hard down',
      body: 'Consecutive failures trip the breaker OUTSIDE the retry loop, so it short-circuits the whole retry sequence — one outcome per exhausted sequence, not per attempt.' },
    { when: (s) => s.now >= 13.5, spot: ['ifA', 'latA', 'ifB', 'latB'], title: 'The whole stack vs nothing',
      body: 'Plain client: cascading meltdown across every phase. httpware: each layer absorbs the phase it’s built for. That is why they compose.' },
  ],
  });
});
</script>

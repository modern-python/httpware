# Bulkhead

One slow dependency can stall a whole client: workers block on the slow calls and fast
calls wait behind them. A bulkhead caps how many calls to that dependency run at once,
and calls over the cap fail fast with `BulkheadFullError` instead of queueing.

<div class="hw-demo" id="bh-demo"></div>

<script>
document.addEventListener('DOMContentLoaded', function () {
  HttpwareDemo.mount('#bh-demo', {
  scenarios: [
    { id: 'slow', label: 'Dependency turns slow', dur: 12.5,
      fault: (now) => (now >= 2.0 && now < 9.0)
        ? { ok: true, ms: 5.0, label: 'slow (5s)' } : { ok: true, ms: 0.05 },
      chainB: { bulkhead: { maxConcurrent: 8, acquireTimeout: 0 } } },
  ],
  buildStops: () => [
    { when: (s) => s.now >= 1.2, spot: ['ifA', 'poolB'], title: 'Fast calls, healthy pool',
      body: 'Both clients are healthy. The httpware client has a bulkhead that allows at most 8 calls to this dependency at once.' },
    { when: (s) => s.now >= 2.4, spot: ['ifA'], title: 'The dependency turns slow (5s)',
      body: 'Every call now takes 5s. The plain client has no cap, so its in-flight count keeps climbing as workers block.' },
    { when: (s) => s.mw.rejected > 0, spot: ['poolB'], title: 'The bulkhead is full',
      body: 'The httpware pool fills to 8 and admits no more. Further calls fail fast instead of piling up, so the client can still serve other work.' },
    { when: (s) => s.now >= 6.0, spot: ['ifA', 'poolB'], title: 'Bounded vs unbounded',
      body: 'The plain client has no limit on in-flight calls, and the whole client slows down. httpware stays at the pool size, and only calls to this dependency are affected.' },
  ],
  });
});
</script>

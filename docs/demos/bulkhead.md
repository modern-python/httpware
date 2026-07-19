# Bulkhead

One slow dependency can sink a whole client: if every worker blocks on the slow call,
fast calls starve behind them. A bulkhead caps concurrency to that dependency — excess
calls fail fast with `BulkheadFullError` instead of piling up and exhausting the client.

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
      body: 'Both clients are humming. The httpware client has a bulkhead: at most 8 calls to this dependency at once.' },
    { when: (s) => s.now >= 2.4, spot: ['ifA'], title: 'The dependency turns slow (5s)',
      body: 'Every call now takes 5s. The plain client has no cap — watch in-flight climb without limit as workers block.' },
    { when: (s) => s.mw.rejected > 0, spot: ['poolB'], title: 'The bulkhead holds the line',
      body: 'The httpware pool fills to 8 and STOPS admitting more — excess calls fail fast instead of piling up. The client stays responsive for everything else.' },
    { when: (s) => s.now >= 6.0, spot: ['ifA', 'poolB'], title: 'Bounded vs unbounded',
      body: 'Plain client: in-flight unbounded, whole client degraded. httpware: in-flight pinned at the pool size, blast radius contained to this one dependency.' },
  ],
  });
});
</script>

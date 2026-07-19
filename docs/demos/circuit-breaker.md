# Circuit Breaker

When a backend goes down, a client without a breaker keeps sending every request
into a slow timeout, piling up in-flight work until it exhausts itself. The breaker
trips after repeated failures and **fast-fails** instead — keeping the client healthy
and probing for recovery.

<div class="hw-demo" id="cb-demo"></div>

<script>
document.addEventListener('DOMContentLoaded', function () {
  HttpwareDemo.mount('#cb-demo', {
  scenarios: [
    { id: 'down', label: 'Backend goes down', dur: 12.5,
      fault: (now) => (now >= 2.0 && now < 8.0)
        ? { ok: false, ms: 3.0, label: 'DOWN' } : { ok: true, ms: 0.04 },
      chainB: { circuitBreaker: { failureThreshold: 5, resetTimeout: 2.0, successThreshold: 1 } } },
    { id: 'brownout', label: 'Brownout (40% errors)', dur: 12.5,
      fault: (now, rnd) => (now >= 2.0 && now < 9.0)
        ? (rnd() < 0.4 ? { ok: false, ms: 3.0, label: 'erroring' } : { ok: true, ms: 0.04 })
        : { ok: true, ms: 0.04 },
      chainB: { circuitBreaker: { failureThreshold: 5, resetTimeout: 2.0, successThreshold: 1 } } },
  ],
  buildStops: () => [
    { when: (s) => s.now >= 1.2, spot: ['ifA', 'ifB'], title: 'Two clients, one backend',
      body: 'Both are healthy — in-flight near zero on each. The backend is about to die. Keep your eye on these two in-flight counters.' },
    { when: (s) => s.now >= 2.35, spot: ['ifA'], title: 'Backend just went DOWN',
      body: 'Every request now hangs ~3s then fails. This plain client keeps sending — watch this number start to climb.' },
    { when: (s) => s.mw.state === 'OPEN', spot: ['brkB', 'ifB'], title: 'The breaker tripped OPEN',
      body: '5 failures in a row -> circuit OPEN. It now fast-fails instantly; its in-flight stays flat while the plain client keeps piling up.' },
    { when: (s) => s.now >= 5.6, spot: ['ifA', 'latA', 'ifB', 'latB'], title: 'The gap — this is the point',
      body: 'Plain client: in-flight high AND p99 blown to 12s — drowning. Protected client: in-flight flat, p99 still 40ms. Same outage, two outcomes.' },
    { when: (s) => s.mw.recovered, spot: ['brkB'], title: 'Recovery via one probe',
      body: 'Backend is back. The breaker admits exactly ONE probe, sees success, and closes — no thundering herd.' },
  ],
  });
});
</script>

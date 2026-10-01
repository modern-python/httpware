# Circuit breaker

When a backend goes down, a client without a breaker keeps sending requests that hang
until they time out, and in-flight work piles up. A circuit breaker opens after repeated
failures and fails fast instead, then lets a probe through to check for recovery.

<div class="hw-demo" id="cb-demo"></div>

<script>
document.addEventListener('DOMContentLoaded', function () {
  HttpwareDemo.mount('#cb-demo', {
  ring: 'reset',
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
      body: 'Both are healthy, with almost nothing in flight. The backend is about to fail; watch these two in-flight counters.' },
    { when: (s) => s.now >= 2.35, spot: ['ifA'], title: 'The backend is down',
      body: 'Every request now hangs for about 3s and then fails. The plain client keeps sending, so its in-flight count starts to climb.' },
    { when: (s) => s.mw.state === 'OPEN', spot: ['brkB', 'ifB'], title: 'The breaker opens',
      body: 'Five failures in a row open the circuit. Requests now fail immediately, so in-flight stays flat while the plain client keeps piling up.' },
    { when: (s) => s.now >= 5.6, spot: ['ifA', 'latA', 'ifB', 'latB'], title: 'Plain vs protected',
      body: 'The plain client has a pile of requests in flight and a p99 of 12s. The protected client has a flat in-flight count and a p99 of 40ms.' },
    { when: (s) => s.mw.recovered, spot: ['brkB'], title: 'Recovery through one probe',
      body: 'The backend is back. The breaker lets one probe through, sees it succeed, and closes, instead of releasing all the waiting traffic at once.' },
  ],
  });
});
</script>

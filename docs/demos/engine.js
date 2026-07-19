/* httpware resilience demos — shared engine.
 *
 * FIDELITY: these models mirror httpware's real semantics. The source of truth
 * for every default is architecture/resilience.md. Behavioral constants below
 * match the library; TIME constants marked (demo) are compressed so an outage
 * fits a ~12s watchable timeline — semantics (ordering, thresholds, accounting)
 * are unchanged. Keep this block the single place to check for drift.
 *
 * CircuitBreaker note: OPEN-state landing results are no-ops — real httpware's
 * on_failure/on_success only count outcomes in CLOSED (and the HALF_OPEN probe).
 */
window.HttpwareDemo = (function () {
  const REAL = {
    circuitBreaker: { failureThreshold: 5, resetTimeout: 30.0, successThreshold: 1,
                      windowSeconds: 30.0, minimumCalls: 20 }, // resetTimeout->2s (demo)
    retry: { maxAttempts: 3, baseDelay: 0.1, maxDelay: 5.0 },
    retryBudget: { ttl: 10.0, minRetriesPerSec: 10.0, percentCanRetry: 0.2 },
    bulkhead: { acquireTimeout: 1.0 }, // max_concurrent has no default
    timeout: {},
  };
  const TICK = 170, ADV = 11; // ms per tick; dot advance %/tick
  const RPS = 12; // simulated requests/sec — cosmetic pacing, not a fidelity constant
  // Fixed seed: every run/replay traces the identical fault timeline. Picked (not
  // arbitrary) because it is one of the minority of seeds where a 40%-probability
  // brownout still produces 5 consecutive landed failures within its window — most
  // seeds never trip the breaker at all, which would strand the guided tour before
  // its OPEN-state stop.
  const SEED = 103;

  // Thundering-herd sim knobs. dt = bucket width (s); reqInterval = per-client
  // request spacing (s) so N clients emit a steady baseline; maxNaive is a pure
  // safety cap on the unbounded naive retry loop (an outage can't outlast dur).
  const HERD = { dt: 0.35, reqInterval: 0.5, maxNaive: 5000 };

  // seeded PRNG so both lanes face the identical fault timeline
  function mulberry(a) { return function () { a |= 0; a = a + 0x6D2B79F5 | 0;
    let t = Math.imul(a ^ a >>> 15, 1 | a); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
    return ((t ^ t >>> 14) >>> 0) / 4294967296; }; }

  // ---- pattern models (faithful) ----
  // OPEN-state landing results are no-ops — real httpware's on_failure/on_success
  // only count outcomes in CLOSED (and the HALF_OPEN probe); a pre-trip in-flight
  // request that lands after the circuit has already opened must not touch
  // fails/openedAt, or a draining backlog keeps re-arming the reset clock.
  function makeCircuitBreaker(cfg) {
    const T = cfg.failureThreshold, R = cfg.resetTimeout, S = cfg.successThreshold;
    // `recovered` is a read-only observability flag (no effect on allow/res logic):
    // it flips true exactly when the circuit genuinely reaches CLOSED via a
    // successful probe, so callers can gate on real recovery instead of a guessed
    // timestamp — compressed demo timing can push recovery later than expected.
    return { state: 'CLOSED', fails: 0, succ: 0, openedAt: 0, probe: false, recovered: false,
      allow(now) {
        if (this.state === 'OPEN') {
          if (now - this.openedAt >= R) { this.state = 'HALF_OPEN'; this.probe = false; }
          else return false;
        }
        if (this.state === 'HALF_OPEN') { if (this.probe) return false; this.probe = true; return true; }
        return true;
      },
      res(ok, now) {
        if (this.state === 'HALF_OPEN') { this.probe = false;
          if (ok) { this.succ++; if (this.succ >= S) { this.state = 'CLOSED'; this.fails = 0; this.succ = 0; this.recovered = true; } }
          else { this.state = 'OPEN'; this.openedAt = now; this.fails = 1; this.succ = 0; }
          return;
        }
        if (this.state === 'OPEN') return; // late-landing in-flight result: no-op (matches on_failure/on_success)
        if (ok) this.fails = 0;
        else { this.fails++; if (this.fails >= T) { this.state = 'OPEN'; this.openedAt = now; } }
      } };
  }

  // Finagle-style token bucket: caps retries to a fraction of traffic, with a floor.
  // Byte-faithful port of budget.py's RetryBudget: both deposits AND withdrawals are
  // timestamp windows purged by ttl (so spent capacity ages out and recovers over
  // time, not a permanent ratchet); ceiling = ceil(deposits * pct) + floor (floor =
  // int(minRetriesPerSec * ttl)); withdraw permitted while withdrawn.length < ceiling.
  function makeRetryBudget(cfg) {
    const ttl = cfg.ttl, floor = Math.floor(cfg.minRetriesPerSec * ttl), pct = cfg.percentCanRetry;
    let deposits = [], withdrawn = []; // timestamps within the [now - ttl, now] window
    function purge(now) { const cut = now - ttl;
      deposits = deposits.filter((t) => t >= cut); withdrawn = withdrawn.filter((t) => t >= cut); }
    return {
      deposit(now) { purge(now); deposits.push(now); },
      tryWithdraw(now) { purge(now);
        const ceiling = Math.ceil(deposits.length * pct) + floor;
        if (withdrawn.length >= ceiling) return false;
        withdrawn.push(now); return true; },
    };
  }

  // Semaphore concurrency limiter (bulkhead.py). Admits up to maxConcurrent in-flight;
  // a request that can't get a slot within acquireTimeout fails fast (BulkheadFullError).
  // The demo models the common case acquireTimeout->0 (reject immediately when full) —
  // real httpware's default is acquireTimeout=1.0 (bounded wait), not modeled here.
  function makeBulkhead(cfg) {
    return { max: cfg.maxConcurrent, inUse: 0,
      tryAcquire() { if (this.inUse < this.max) { this.inUse++; return true; } return false; },
      release() { if (this.inUse > 0) this.inUse--; } };
  }

  // AsyncTimeout bounds the WHOLE operation (all retry attempts + backoff sleeps),
  // not a single call — so a lane-B pend entry carries one deadline set at the
  // first attempt and clamps every subsequent (re)push to it. A landing whose
  // projected time would cross the deadline is cut short here and marked
  // timedOut so the caller resolves it as a TimeoutError failure, never a retry.
  function clampToDeadline(tick, landTicks, deadline) {
    const land = tick + landTicks;
    if (deadline === Infinity || land * TICK / 1000 <= deadline) return { land, timedOut: false };
    return { land: Math.max(tick + 1, Math.round(deadline * 1000 / TICK)), timedOut: true };
  }

  const prefersReduced = window.matchMedia &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  const MW_LABELS = { circuitBreaker: 'CircuitBreaker', retry: 'Retry', budget: 'RetryBudget', bulkhead: 'Bulkhead', timeout: 'Timeout' };

  function esc(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
  }

  function chainLabel(chainB) {
    const keys = chainB ? Object.keys(chainB) : [];
    return keys.length ? keys.map((k) => MW_LABELS[k] || k).join(' + ') : 'no protection';
  }

  // Human-readable "what's actually protecting lane B" note, cross-checked against REAL.
  function describeChain(chainB) {
    if (!chainB || !Object.keys(chainB).length) return 'no middleware';
    const parts = [];
    if (chainB.circuitBreaker) {
      const c = chainB.circuitBreaker, r = REAL.circuitBreaker;
      const resetNote = c.resetTimeout !== r.resetTimeout
        ? `reset_timeout=${c.resetTimeout}s (demo; real default ${r.resetTimeout}s)`
        : `reset_timeout=${c.resetTimeout}s`;
      parts.push(`CircuitBreaker(failure_threshold=${c.failureThreshold}, ${resetNote}, success_threshold=${c.successThreshold})`);
    }
    if (chainB.retry) {
      const t = chainB.retry;
      parts.push(`Retry(max_attempts=${t.maxAttempts}, base_delay=${t.baseDelay}s, max_delay=${t.maxDelay}s)`);
    }
    if (chainB.budget) {
      const b = chainB.budget;
      parts.push(`RetryBudget(ttl=${b.ttl}s, min_retries_per_sec=${b.minRetriesPerSec}, percent_can_retry=${b.percentCanRetry})`);
    }
    return parts.join(', ');
  }

  function formatMs(ms) {
    return ms >= 1 ? `${ms}s` : `${Math.round(ms * 1000)}ms`;
  }

  // Sample the fault function (worst-case rnd, so probabilistic branches always fire)
  // to find the outage window for the decorative timeline bar. Cosmetic only — it
  // never drives the sim; per-request outcomes always come from a real fault() call.
  function computeOutageWindow(scenario) {
    const steps = 200;
    const worstRnd = () => 0;
    let from = null, to = null, label = '';
    let sawDown = false, sawSlow = false;
    for (let i = 0; i <= steps; i++) {
      const t = (scenario.dur * i) / steps;
      const f = scenario.fault(t, worstRnd);
      // High-latency-but-ok samples are stress too (matches the `slow` threshold
      // updateUI already uses) — otherwise a latency-spike phase (ok:true, high ms)
      // is invisible on this bar even though it's exactly the kind of backend
      // trouble the guided tour calls out (e.g. full-stack's phase 1).
      const down = !f.ok;
      const slow = f.ok && f.ms >= 1.0;
      if (down || slow) {
        if (from === null) from = t;
        to = t;
        if (down) sawDown = true;
        if (slow) sawSlow = true;
        if (!label) label = down ? (f.label || 'DOWN') : (f.label || 'degraded');
      }
    }
    if (from === null) return null;
    // A window that mixes down and slow phases (e.g. full-stack's multi-phase
    // incident) can't be summed up by one phase's label without misleading about
    // the other — fall back to a generic label. Decorative only, never drives the sim.
    if (sawDown && sawSlow) label = 'degraded';
    return { from, to: Math.min(scenario.dur, to + scenario.dur / steps), label };
  }

  // ---- shared guided-tour driver: spotlight cutout + side-placed coach ----
  // Extracted from mount() so a second mount mode (herd) reuses one implementation.
  // `els` supplies the tour DOM (dimT/dimB/dimL/dimR/ring/coach/cArrow/cStep/
  // cTitle/cBody/cGo). Behavior is identical to the previous inline closures.
  function makeTour(els) {
    // 4 dim panels leave a bright hole over the union of target rects.
    function spotlight(nodes) {
      const rs = nodes.map((n) => n.getBoundingClientRect());
      const pad = 6;
      const x0 = Math.min(...rs.map((r) => r.left)) - pad, y0 = Math.min(...rs.map((r) => r.top)) - pad;
      const x1 = Math.max(...rs.map((r) => r.right)) + pad, y1 = Math.max(...rs.map((r) => r.bottom)) + pad;
      const W = window.innerWidth, H = window.innerHeight;
      const set = (node, l, t, w, h) => {
        node.style.left = l + 'px'; node.style.top = t + 'px';
        node.style.width = Math.max(0, w) + 'px'; node.style.height = Math.max(0, h) + 'px';
        node.classList.add('show');
      };
      set(els.dimT, 0, 0, W, y0);
      set(els.dimB, 0, y1, W, H - y1);
      set(els.dimL, 0, y0, x0, y1 - y0);
      set(els.dimR, x1, y0, W - x1, y1 - y0);
      els.ring.style.left = x0 + 'px'; els.ring.style.top = y0 + 'px';
      els.ring.style.width = (x1 - x0) + 'px'; els.ring.style.height = (y1 - y0) + 'px';
      els.ring.classList.add('show');
      return { x0, y0, x1, y1 };
    }
    function hideSpot() {
      [els.dimT, els.dimB, els.dimL, els.dimR, els.ring].forEach((n) => n.classList.remove('show'));
    }
    function placeCoach(hole) {
      const c = els.coach;
      c.classList.add('show');
      const cw = c.offsetWidth, ch = c.offsetHeight, gap = 16;
      const W = window.innerWidth, H = window.innerHeight, cy = (hole.y0 + hole.y1) / 2, cx = (hole.x0 + hole.x1) / 2;
      const room = { right: W - hole.x1, left: hole.x0, bottom: H - hole.y1, top: hole.y0 };
      let side, left, top;
      if (room.right >= cw + gap) { side = 'right'; left = hole.x1 + gap; top = cy - ch / 2; }
      else if (room.left >= cw + gap) { side = 'left'; left = hole.x0 - gap - cw; top = cy - ch / 2; }
      else if (room.bottom >= ch + gap) { side = 'bottom'; top = hole.y1 + gap; left = cx - cw / 2; }
      else { side = 'top'; top = hole.y0 - gap - ch; left = cx - cw / 2; }
      left = Math.min(Math.max(10, left), W - cw - 10);
      top = Math.min(Math.max(10, top), H - ch - 10);
      c.style.left = left + 'px'; c.style.top = top + 'px';
      const a = els.cArrow;
      a.style.transform = 'rotate(45deg)';
      if (side === 'right') { a.style.left = '-7px'; a.style.top = (cy - top - 6) + 'px'; a.style.borderTop = 'none'; a.style.borderRight = 'none'; a.style.borderLeft = '1px solid var(--hw-line)'; a.style.borderBottom = '1px solid var(--hw-line)'; }
      else if (side === 'left') { a.style.left = (cw - 7) + 'px'; a.style.top = (cy - top - 6) + 'px'; a.style.borderBottom = 'none'; a.style.borderLeft = 'none'; a.style.borderTop = '1px solid var(--hw-line)'; a.style.borderRight = '1px solid var(--hw-line)'; }
      else if (side === 'bottom') { a.style.top = '-7px'; a.style.left = (cx - left - 6) + 'px'; a.style.borderBottom = 'none'; a.style.borderRight = 'none'; }
      else { a.style.top = (ch - 7) + 'px'; a.style.left = (cx - left - 6) + 'px'; a.style.borderTop = 'none'; a.style.borderLeft = 'none'; }
    }
    let onContinue = null;
    els.cGo.addEventListener('click', () => {
      els.coach.classList.remove('show'); hideSpot();
      if (onContinue) onContinue();
    });
    return {
      show(stop, stepIdx, total, spotLookup) {
        const nodes = stop.spot.map((key) => spotLookup[key]).filter(Boolean);
        const hole = spotlight(nodes);
        els.cStep.textContent = `Step ${stepIdx + 1} of ${total}`;
        els.cTitle.textContent = stop.title;
        els.cBody.textContent = stop.body;
        placeCoach(hole);
      },
      hideAll() { els.coach.classList.remove('show'); hideSpot(); },
      setContinue(fn) { onContinue = fn; },
    };
  }

  // ---- thundering-herd simulation (faithful; reuses the real RetryBudget model) ----
  // N independent clients hit ONE backend through a sustained outage. Every backend
  // attempt (initial + each retry) is counted into a per-bucket series for each lane.
  //   naive: FIXED backoff, NO jitter, UNBOUNDED retries -> same-bucket failures retry
  //          into the same later bucket => synchronized spikes with dead gaps.
  //   httpware: FULL-JITTER backoff + per-client RetryBudget + maxAttempts cap ->
  //          retry timing decorrelates into a near-constant rate; the budget and the
  //          attempt cap bound amplification. The budget is PER CLIENT, never shared.
  // Arrivals are phase-staggered (not synchronized): the clustering that follows is
  // caused by the retry policy, not by synchronized arrivals.
  function simulateHerd(scenario, opts) {
    const N = opts.clients, cfg = opts.retry, budgetCfg = opts.budget;
    const dur = scenario.dur, dt = HERD.dt, ri = HERD.reqInterval;
    const buckets = Math.ceil(dur / dt);
    const naive = new Array(buckets).fill(0);
    const hw = new Array(buckets).fill(0);
    const bkt = (t) => Math.min(buckets - 1, Math.max(0, Math.floor(t / dt)));
    const rnd = mulberry(SEED); // one deterministic stream drives jitter + any probabilistic fault
    for (let c = 0; c < N; c++) {
      const phase = (c / N) * ri; // spread arrivals across a request interval
      // naive: unbounded fixed-backoff retries, no jitter
      for (let t0 = phase; t0 < dur; t0 += ri) {
        let t = t0, guard = 0;
        while (t < dur) {
          naive[bkt(t)]++;
          const f = scenario.fault(t, rnd);
          if (f.ok) break;
          t += cfg.baseDelay; // fixed, no jitter, no attempt cap
          if (++guard > HERD.maxNaive) break;
        }
      }
      // httpware: full jitter + per-client budget + maxAttempts
      const budget = makeRetryBudget(budgetCfg);
      for (let t0 = phase; t0 < dur; t0 += ri) {
        let t = t0, attempt = 0;
        budget.deposit(t);           // deposit once per operation (matches terminal)
        hw[bkt(t)]++;
        let f = scenario.fault(t, rnd);
        while (!f.ok && (attempt + 1) < cfg.maxAttempts && budget.tryWithdraw(t)) {
          const backoff = rnd() * Math.min(cfg.maxDelay, cfg.baseDelay * Math.pow(2, attempt));
          t += backoff;
          if (t >= dur) break;
          attempt++;
          hw[bkt(t)]++;
          f = scenario.fault(t, rnd);
        }
      }
    }
    const baseline = N * (dt / ri); // healthy backend calls per bucket
    const stat = (arr) => {
      const peak = arr.reduce((m, v) => Math.max(m, v), 0);
      const total = arr.reduce((a, b) => a + b, 0);
      return { series: arr, peak, total, mult: baseline > 0 ? peak / baseline : 0 };
    };
    return { naive: stat(naive), hw: stat(hw), buckets, dt, baseline,
      outage: computeOutageWindow(scenario) };
  }

  // Render a call-rate strip as an SVG of vertical bars into `el`. Buckets [0,
  // revealUpTo) are drawn (progressive reveal during playback). peakScale is shared
  // across both strips so their heights are comparable and httpware's flatness reads
  // honestly against naive's spikes. viewBox is unitless; CSS sizes the strip.
  function renderRateStrip(el, series, revealUpTo, opts) {
    const n = series.length, W = 100, H = 100, bw = W / n;
    const scale = opts.peakScale > 0 ? H / opts.peakScale : 0;
    let body = '';
    if (opts.outage) {
      const ox = (opts.outage.from / opts.dur) * W;
      const ow = ((opts.outage.to - opts.outage.from) / opts.dur) * W;
      body += `<rect x="${ox.toFixed(2)}" y="0" width="${ow.toFixed(2)}" height="${H}" class="herd-band"/>`;
    }
    const upto = Math.min(revealUpTo, n);
    for (let i = 0; i < upto; i++) {
      const h = Math.min(H, series[i] * scale);
      if (h <= 0) continue;
      body += `<rect x="${(i * bw).toFixed(2)}" y="${(H - h).toFixed(2)}" width="${Math.max(0.5, bw - 0.3).toFixed(2)}" height="${h.toFixed(2)}" class="${opts.cls}"/>`;
    }
    const by = H - Math.min(H, opts.baseline * scale);
    body += `<line x1="0" y1="${by.toFixed(2)}" x2="${W}" y2="${by.toFixed(2)}" class="herd-baseline"/>`;
    el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" class="herd-svg">${body}</svg>`;
  }

  // CSS-driven conic countdown ring overlaid on an element. fraction 0..1 is the
  // ELAPSED share of the wait; 0 or >=1 clears it. No per-frame DOM churn — sets a
  // custom property the ::after conic-gradient reads.
  function renderCountdownRing(el, fraction) {
    if (!el) return;
    const f = Math.max(0, Math.min(1, fraction));
    if (f <= 0 || f >= 1) { el.classList.remove('counting'); el.style.removeProperty('--hw-ring'); return; }
    el.classList.add('counting');
    el.style.setProperty('--hw-ring', (f * 360).toFixed(0) + 'deg');
  }

  function herdTemplate(config) {
    const title = config.title || 'Now scale it to 20 clients';
    const intro = config.intro || 'One client retrying a blip is invisible. Twenty clients retrying a ' +
      '<b>sustained</b> outage is a traffic weapon — unless their retries are spread out and capped. ' +
      'These strips show <b>backend call-rate over time</b>. Press play and watch the shape.';
    return `
<div class="hw-wrap herd-wrap">
  <h2>${esc(title)}</h2>
  <p class="intro">${intro}</p>
  <div class="ctl">
    <button type="button" class="play" data-el="hplay">&#9654; Run the storm</button>
    <button type="button" class="play ghost" data-el="hreplay">&#8635; Replay</button>
  </div>

  <div class="herd-lane">
    <h3>20 naive clients <span class="badge bad">fixed backoff, no jitter, unbounded</span></h3>
    <div class="herd-strip" data-el="naiveStrip"></div>
    <div class="score">
      <span class="stat" data-el="naiveMult"><span class="k">peak load</span> <span class="fail-big" data-el="naiveMultN">1&times;</span></span>
      <span class="stat" data-el="naiveTotal"><span class="k">calls sent</span> <span class="big" data-el="naiveTotalN">0</span></span>
    </div>
  </div>

  <div class="herd-lane">
    <h3>20 httpware clients <span class="badge ok">full jitter + per-client budget</span></h3>
    <div class="herd-strip" data-el="hwStrip"></div>
    <div class="score">
      <span class="stat" data-el="hwMult"><span class="k">peak load</span> <span class="fail-big" data-el="hwMultN">1&times;</span></span>
      <span class="stat" data-el="hwTotal"><span class="k">calls sent</span> <span class="big" data-el="hwTotalN">0</span></span>
    </div>
  </div>

  <p class="note">Faithful model: each httpware client owns its RetryBudget (never shared). Jitter flattens the visible spikes; the budget + max_attempts cap what a longer storm could do.</p>
</div>

<div class="dim" data-el="dimT"></div><div class="dim" data-el="dimB"></div>
<div class="dim" data-el="dimL"></div><div class="dim" data-el="dimR"></div>
<div class="ring" data-el="ring"></div>
<div class="coach" data-el="coach">
  <div class="c-arrow" data-el="cArrow"></div>
  <div class="step" data-el="cStep">Step 1 of 1</div>
  <h4 data-el="cTitle"></h4><p data-el="cBody"></p>
  <button type="button" class="go" data-el="cGo">Continue &#9654;</button>
</div>`;
  }

  function mountHerd(selector, config) {
    const container = document.querySelector(selector);
    if (!container) return;
    container.classList.add('hw-demo');
    container.innerHTML = herdTemplate(config);
    const $ = (k) => container.querySelector('[data-el="' + k + '"]');
    const els = {
      hplay: $('hplay'), hreplay: $('hreplay'),
      naiveStrip: $('naiveStrip'), hwStrip: $('hwStrip'),
      naiveMult: $('naiveMult'), naiveMultN: $('naiveMultN'), naiveTotal: $('naiveTotal'), naiveTotalN: $('naiveTotalN'),
      hwMult: $('hwMult'), hwMultN: $('hwMultN'), hwTotal: $('hwTotal'), hwTotalN: $('hwTotalN'),
      dimT: $('dimT'), dimB: $('dimB'), dimL: $('dimL'), dimR: $('dimR'), ring: $('ring'),
      coach: $('coach'), cArrow: $('cArrow'), cStep: $('cStep'), cTitle: $('cTitle'), cBody: $('cBody'), cGo: $('cGo'),
    };
    const SPOT = { naiveMult: els.naiveMult, hwMult: els.hwMult, naiveTotal: els.naiveTotal,
      hwTotal: els.hwTotal, naiveStrip: els.naiveStrip, hwStrip: els.hwStrip };
    const tour = makeTour(els);

    let timer = null, paused = false, reveal = 0, stopIdx = 0, STOPS = [];
    const scenario = config.scenario;
    let sim = null;

    function paint() {
      const peakScale = Math.max(sim.naive.peak, sim.hw.peak, 1);
      const stripOpts = (cls) => ({ peakScale, baseline: sim.baseline, outage: sim.outage, dur: scenario.dur, cls });
      renderRateStrip(els.naiveStrip, sim.naive.series, reveal, stripOpts('herd-bar-naive'));
      renderRateStrip(els.hwStrip, sim.hw.series, reveal, stripOpts('herd-bar-hw'));
      // running peak/total over revealed buckets so the numbers climb with the bars
      const upto = Math.min(reveal, sim.buckets);
      const runPeak = (arr) => arr.slice(0, upto).reduce((m, v) => Math.max(m, v), 0);
      const runTot = (arr) => arr.slice(0, upto).reduce((a, b) => a + b, 0);
      const nm = sim.baseline > 0 ? runPeak(sim.naive.series) / sim.baseline : 0;
      const hm = sim.baseline > 0 ? runPeak(sim.hw.series) / sim.baseline : 0;
      els.naiveMultN.textContent = nm.toFixed(1) + '×';
      els.hwMultN.textContent = hm.toFixed(1) + '×';
      els.naiveTotalN.textContent = String(runTot(sim.naive.series));
      els.hwTotalN.textContent = String(runTot(sim.hw.series));
      // httpware is bounded by max_attempts, not a hard multiplier cap — it settles
      // near ~3x for this scenario, never near naive's unbounded ~70x. Thresholds
      // reflect that measured gap, not the placeholder "<=2x is good" assumption.
      els.naiveMultN.style.color = nm > 5 ? 'var(--hw-bad)' : '';
      els.hwMultN.style.color = hm <= 4 ? 'var(--hw-ok)' : '';
    }

    function reset() {
      clearInterval(timer); reveal = 0; stopIdx = 0; paused = false;
      sim = simulateHerd(scenario, { clients: config.clients, retry: config.retry, budget: config.budget });
      STOPS = config.buildStops(sim);
      tour.hideAll();
      paint();
    }
    tour.setContinue(() => { paused = false; stopIdx++; });

    function run() {
      reset();
      timer = setInterval(() => {
        if (paused) return;
        const state = { bucket: reveal, revealed: reveal, sim,
          naiveShown: sim.naive.series.slice(0, reveal).reduce((a, b) => a + b, 0),
          hwShown: sim.hw.series.slice(0, reveal).reduce((a, b) => a + b, 0) };
        if (stopIdx < STOPS.length && STOPS[stopIdx].when(state)) {
          paused = true; tour.show(STOPS[stopIdx], stopIdx, STOPS.length, SPOT); return;
        }
        reveal++;
        paint();
        if (reveal > sim.buckets) clearInterval(timer);
      }, TICK);
    }
    els.hplay.addEventListener('click', run);
    els.hreplay.addEventListener('click', run);
    reset(); // first paint shows the empty strips + baseline, ready to play
  }

  function template(config) {
    const scenarioBtns = config.scenarios.map((sc) =>
      `<button type="button" class="scenario-btn" data-scenario="${esc(sc.id)}">${esc(sc.label)}</button>`
    ).join('');
    const title = config.title || 'Guided walk-through';
    const intro = config.intro || 'The animation <b>freezes</b> at each beat and the callout appears in the ' +
      'empty space <b>beside</b> what you should watch (never on top of it), with an arrow pointing at it.';
    return `
<div class="hw-wrap">
  <h2>${esc(title)}</h2>
  <p class="intro">${intro}</p>

  <div class="ctl">
    <div class="scenarios" data-el="scenarios">${scenarioBtns}</div>
    <button type="button" class="play" data-el="play" disabled>&#9654; Start the walk-through</button>
    <button type="button" class="play ghost" data-el="replay">&#8635; Replay</button>
  </div>
  <div class="scen" data-el="scenLabel">Pick a scenario above.</div>

  <div class="timeline" data-el="timeline">
    <div class="outage" data-el="outage" style="display:none"><span data-el="outageLabel"></span></div>
    <div class="playhead" data-el="playhead"></div>
  </div>

  <div class="lane" data-el="laneA">
    <h3>Plain client <span class="badge" data-el="badgeA">no protection</span></h3>
    <div class="laneflow">
      <div class="box">client</div><div class="arrow"></div>
      <div class="box" data-el="srvA">server &#10003;</div>
    </div>
    <div class="track" data-el="trackA"></div>
    <div class="score">
      <span class="stat"><span class="k">in-flight</span> <span class="inflight-big" data-el="ifA">0</span></span>
      <span class="k">&#10003; <span data-el="okA">0</span></span>
      <span class="stat" data-el="badWrapA"><span class="k">&#10007; failed</span> <span class="fail-big" data-el="badA">0</span></span>
      <span class="stat"><span class="k">p99</span> <span class="big" data-el="latA">40ms</span></span>
    </div>
  </div>

  <div class="lane" data-el="laneB">
    <h3>httpware client <span class="badge" data-el="badgeB">CircuitBreaker</span></h3>
    <div class="laneflow">
      <div class="box">client</div><div class="arrow"></div>
      <div class="box" data-el="brkB">&mdash;</div><div class="arrow"></div>
      <div class="box" data-el="srvB">server &#10003;</div>
    </div>
    <div class="track" data-el="trackB"></div>
    <div class="score">
      <span class="stat"><span class="k">in-flight</span> <span class="inflight-big" data-el="ifB">0</span></span>
      <span class="k">&#10003; <span data-el="okB">0</span></span>
      <span class="stat" data-el="badWrapB"><span class="k">&#10007; failed</span> <span class="fail-big" data-el="badB">0</span></span>
      <span class="k">&#9211; fast-failed <span data-el="rejB">0</span></span>
      <span class="stat" data-el="poolWrap" style="display:none"><span class="k">pool</span> <span class="big" data-el="poolB">&mdash;</span></span>
      <span class="stat" data-el="elapsedWrap" style="display:none"><span class="k">elapsed</span> <span class="big" data-el="elapsedB">&mdash;</span></span>
      <span class="stat"><span class="k">p99</span> <span class="big" data-el="latB">40ms</span></span>
    </div>
  </div>

  <p class="note" data-el="note">Faithful model of httpware, not httpware running in your browser. Pick a scenario above to begin.</p>

  <div class="macro" data-el="macroWrap" style="display:none">
    <div class="macro-head"><span class="k">backend call-rate</span> &mdash; <span data-el="macroStage">healthy</span></div>
    <div class="herd-strip" data-el="macroStrip"></div>
  </div>
</div>

<div class="dim" data-el="dimT"></div><div class="dim" data-el="dimB"></div>
<div class="dim" data-el="dimL"></div><div class="dim" data-el="dimR"></div>
<div class="ring" data-el="ring"></div>
<div class="coach" data-el="coach">
  <div class="c-arrow" data-el="cArrow"></div>
  <div class="step" data-el="cStep">Step 1 of 1</div>
  <h4 data-el="cTitle"></h4><p data-el="cBody"></p>
  <button type="button" class="go" data-el="cGo">Continue &#9654;</button>
</div>`;
  }

  function mount(selector, config) {
    const container = document.querySelector(selector);
    if (!container) return;
    container.classList.add('hw-demo');
    container.innerHTML = template(config);

    const $ = (key) => container.querySelector('[data-el="' + key + '"]');
    const els = {
      scenarios: $('scenarios'), play: $('play'), replay: $('replay'), scenLabel: $('scenLabel'),
      timeline: $('timeline'), outage: $('outage'), outageLabel: $('outageLabel'), playhead: $('playhead'),
      laneA: $('laneA'), badgeA: $('badgeA'), srvA: $('srvA'), trackA: $('trackA'),
      ifA: $('ifA'), okA: $('okA'), badA: $('badA'), badWrapA: $('badWrapA'), latA: $('latA'),
      laneB: $('laneB'), badgeB: $('badgeB'), srvB: $('srvB'), trackB: $('trackB'), brkB: $('brkB'),
      ifB: $('ifB'), okB: $('okB'), badB: $('badB'), badWrapB: $('badWrapB'), rejB: $('rejB'), latB: $('latB'),
      poolWrap: $('poolWrap'), poolB: $('poolB'),
      elapsedWrap: $('elapsedWrap'), elapsedB: $('elapsedB'),
      note: $('note'),
      macroWrap: $('macroWrap'), macroStrip: $('macroStrip'), macroStage: $('macroStage'),
      dimT: $('dimT'), dimB: $('dimB'), dimL: $('dimL'), dimR: $('dimR'), ring: $('ring'),
      coach: $('coach'), cArrow: $('cArrow'), cStep: $('cStep'), cTitle: $('cTitle'), cBody: $('cBody'), cGo: $('cGo'),
    };
    const ELS = { ifA: els.ifA, latA: els.latA, badWrapA: els.badWrapA, ifB: els.ifB, latB: els.latB, badWrapB: els.badWrapB, brkB: els.brkB, poolB: els.poolB, elapsedB: els.elapsedB };
    const tour = makeTour(els);
    tour.setContinue(() => { paused = false; stopIdx++; });
    function showStop(s) {
      paused = true;
      tour.show(s, stopIdx, STOPS.length, ELS);
    }

    // Built fresh inside run() from the selected scenario (STOPS is never read before a
    // scenario is played, so it's safe to leave empty until then) — pages with one
    // shared stop list across scenarios (buildStops ignoring its arg) keep working
    // unchanged. Must NOT call config.buildStops() here at mount time: retry.md's
    // buildStops dereferences its scenario argument, so calling it with no scenario
    // selected yet would throw and abort mount() before the Play/scenario listeners
    // are wired up.
    let STOPS = [];

    let timer = null, paused = false, tick = 0, stopIdx = 0;
    let dotsA = [], dotsB = [];
    let A = { ok: 0, bad: 0, if: 0, pend: [] };
    let B = { ok: 0, bad: 0, rej: 0, if: 0, pend: [] };
    let brk = null;
    let macroSeries = []; // lane-B backend calls per tick, for config.macroStrip
    let bulk = null;
    let retryCfg = null, budget = null, budgetExhausted = false;
    let tmoCfg = null, timedOutCount = 0;
    let rnd = mulberry(SEED);
    let selectedScenario = null;

    function spawnDot(arr, track, kind) {
      const node = document.createElement('div');
      node.className = 'dot ' + kind;
      track.appendChild(node);
      if (prefersReduced) {
        node.style.transition = 'none';
        node.style.left = '96%';
        setTimeout(() => node.remove(), 200);
        return;
      }
      arr.push({ node, x: 0 });
    }
    function advDots(arr) {
      if (prefersReduced) return;
      for (let i = arr.length - 1; i >= 0; i--) {
        const d = arr[i];
        d.x += ADV;
        if (d.x >= 96) { d.node.style.opacity = '0'; setTimeout(() => d.node.remove(), 200); arr.splice(i, 1); }
        else d.node.style.left = d.x + '%';
      }
    }

    function setupOutageBar(scenario) {
      const win = computeOutageWindow(scenario);
      if (win) {
        els.outage.style.display = '';
        els.outage.style.left = (win.from / scenario.dur * 100) + '%';
        els.outage.style.width = ((win.to - win.from) / scenario.dur * 100) + '%';
        els.outageLabel.textContent = 'backend ' + win.label;
      } else {
        els.outage.style.display = 'none';
      }
    }

    function resetVisual() {
      clearInterval(timer);
      els.trackA.innerHTML = ''; els.trackB.innerHTML = '';
      dotsA = []; dotsB = [];
      tick = 0; stopIdx = 0; paused = false;
      A = { ok: 0, bad: 0, if: 0, pend: [] };
      B = { ok: 0, bad: 0, rej: 0, if: 0, pend: [] };
      els.ifA.textContent = '0'; els.okA.textContent = '0'; els.badA.textContent = '0';
      els.ifB.textContent = '0'; els.okB.textContent = '0'; els.badB.textContent = '0'; els.rejB.textContent = '0';
      els.latA.textContent = '40ms'; els.latB.textContent = '40ms';
      [els.latA, els.latB, els.ifA, els.ifB, els.badA, els.badB].forEach((n) => { n.style.color = ''; });
      // Flow-diagram boxes reflect the selected scenario's CHAIN config, not the runtime
      // middleware objects (which aren't constructed until run()). Otherwise the breaker
      // box reads "no breaker" on a circuit-breaker page until the first Play.
      const cfgB = selectedScenario ? selectedScenario.chainB : {};
      els.brkB.className = 'box'; els.brkB.textContent = cfgB.circuitBreaker ? 'breaker CLOSED' : 'no breaker';
      els.brkB.classList.remove('counting'); els.brkB.style.removeProperty('--hw-ring');
      els.elapsedB.classList.remove('counting'); els.elapsedB.style.removeProperty('--hw-ring');
      els.poolWrap.style.display = cfgB.bulkhead ? '' : 'none';
      els.poolB.textContent = cfgB.bulkhead ? ('0/' + cfgB.bulkhead.maxConcurrent) : '—';
      els.elapsedWrap.style.display = cfgB.timeout ? '' : 'none';
      els.elapsedB.textContent = cfgB.timeout ? ('0.0s / ' + cfgB.timeout.timeout.toFixed(1) + 's') : '—';
      els.macroWrap.style.display = (selectedScenario && config.macroStrip) ? '' : 'none';
      els.srvA.className = 'box'; els.srvA.textContent = 'server ✓';
      els.srvB.className = 'box'; els.srvB.textContent = 'server ✓';
      els.laneA.className = 'lane'; els.laneB.className = 'lane';
      els.playhead.style.left = '0%';
      els.badgeA.className = 'badge'; els.badgeA.textContent = 'no protection';
      els.badgeB.className = 'badge'; els.badgeB.textContent = selectedScenario ? chainLabel(selectedScenario.chainB) : 'CircuitBreaker';
      tour.hideAll();
    }

    function updateUI(now, lastFault) {
      els.ifA.textContent = A.if; els.okA.textContent = A.ok; els.badA.textContent = A.bad;
      els.ifB.textContent = B.if; els.okB.textContent = B.ok; els.badB.textContent = B.bad; els.rejB.textContent = B.rej;
      els.ifA.style.color = A.if > 10 ? 'var(--hw-bad)' : '';
      els.ifB.style.color = B.if <= 6 ? 'var(--hw-ok)' : '';
      els.badA.style.color = A.bad > 0 ? 'var(--hw-bad)' : '';
      els.badB.style.color = B.bad > 0 ? 'var(--hw-bad)' : '';
      if (bulk) els.poolB.textContent = bulk.inUse + '/' + bulk.max;
      let maxElapsed = 0;
      if (tmoCfg) {
        maxElapsed = B.pend.reduce((m, p) => Math.max(m, now - p.start), 0);
        els.elapsedB.textContent = maxElapsed.toFixed(1) + 's / ' + tmoCfg.timeout.toFixed(1) + 's';
      }
      // "Stress" covers two distinct fault shapes: outright failure (down) and a
      // high-latency-but-ok fault (slow, e.g. bulkhead.md's 5s dependency) — both must
      // read as backend trouble even though only `down` implies an error response.
      const down = !!(lastFault && !lastFault.ok);
      const slow = !!(lastFault && lastFault.ok && lastFault.ms >= 1.0);
      const stressed = down || slow;
      // latA is the plain client's p99: reflect the ACTUAL in-flight latency tail, not
      // the last request. In a brownout (mixed fast successes + slow failures) the last
      // sample flickers, so a last-request p99 drops to 40ms whenever the last request
      // was a fast success — contradicting the "p99 blown" narration while slow requests
      // are still piled up in flight. The in-flight max is stable and honest.
      const aTailMs = A.pend.length ? A.pend.reduce((m, p) => Math.max(m, p.ms), 0) : 0.04;
      const plainStress = aTailMs >= 1.0 || A.if > 4;
      els.latA.textContent = plainStress ? (A.if > 4 ? '12s+' : formatMs(aTailMs)) : '40ms';
      els.latA.style.color = plainStress ? 'var(--hw-bad)' : '';
      // On timeout pages, AsyncTimeout bounds every lane-B attempt at the deadline —
      // p99 must reflect that ACTUAL bounded latency, not the constant 40ms, or it
      // visually contradicts elapsedB as it climbs toward the same deadline. Pages
      // with no timeout configured keep the untouched 40ms constant.
      els.latB.textContent = tmoCfg ? formatMs(Math.min(maxElapsed, tmoCfg.timeout)) : '40ms';
      els.latB.style.color = (down && brk && brk.state === 'OPEN') ? 'var(--hw-ok)' : '';
      const st = brk ? brk.state : 'CLOSED';
      els.brkB.className = 'box ' + (st === 'OPEN' ? 'open' : st === 'HALF_OPEN' ? 'half' : '');
      els.brkB.textContent = brk ? ('breaker ' + st) : 'no breaker';
      els.srvA.className = 'box' + (stressed ? ' down' : '');
      els.srvA.textContent = down ? ('server ✗' + (lastFault.label ? ' ' + lastFault.label : ''))
        : slow ? ('server ' + (lastFault.label || 'slow')) : 'server ✓';
      els.srvB.className = 'box' + (stressed ? ' down' : '');
      els.srvB.textContent = down ? 'server ✗' : slow ? 'server slow' : 'server ✓';
      els.laneA.classList.toggle('hot', plainStress && A.if > 8);
      els.laneB.classList.toggle('safe', st === 'CLOSED' && !stressed);
      els.badgeA.className = 'badge' + (plainStress ? ' bad' : '');
      els.badgeA.textContent = plainStress ? 'drowning' : 'no protection';
      const okBadge = st === 'CLOSED' && brk && !stressed;
      els.badgeB.className = 'badge ' + (st === 'OPEN' ? 'warn' : okBadge ? 'ok' : '');
      els.badgeB.textContent = st === 'OPEN' ? 'fast-failing' : st === 'HALF_OPEN' ? 'probing' : chainLabel(selectedScenario.chainB);
      // countdown ring (config.ring): show the multi-second wait this page is about.
      if (config.ring === 'deadline' && tmoCfg) {
        renderCountdownRing(els.elapsedB, maxElapsed / tmoCfg.timeout);
      } else if (config.ring === 'reset' && brk && brk.state === 'OPEN') {
        const R = selectedScenario.chainB.circuitBreaker.resetTimeout;
        renderCountdownRing(els.brkB, (now - brk.openedAt) / R);
      } else if (config.ring === 'reset') {
        renderCountdownRing(els.brkB, 0); // clear once the breaker leaves OPEN
      }
    }

    function run() {
      if (!selectedScenario) return;
      const scenario = selectedScenario;
      STOPS = config.buildStops(scenario);
      brk = scenario.chainB && scenario.chainB.circuitBreaker
        ? makeCircuitBreaker(scenario.chainB.circuitBreaker) : null;
      bulk = scenario.chainB && scenario.chainB.bulkhead
        ? makeBulkhead(scenario.chainB.bulkhead) : null;
      retryCfg = scenario.chainB && scenario.chainB.retry ? scenario.chainB.retry : null;
      // retry.py: Retry(budget=None) defaults to RetryBudget() — a retry config with no
      // explicit budget must still retry (real defaults), never silently go unbudgeted.
      budget = retryCfg
        ? makeRetryBudget(scenario.chainB.budget || REAL.retryBudget)
        : null;
      budgetExhausted = false;
      tmoCfg = scenario.chainB && scenario.chainB.timeout ? scenario.chainB.timeout : null;
      timedOutCount = 0;
      rnd = mulberry(SEED);
      resetVisual();
      macroSeries = new Array(Math.ceil(scenario.dur * 1000 / TICK) + 2).fill(0);
      if (config.macroStrip) els.macroWrap.style.display = '';

      timer = setInterval(() => {
        if (paused) return;
        const now = tick * TICK / 1000;
        const mw = { state: brk ? brk.state : 'CLOSED', recovered: brk ? brk.recovered : false,
          budgetExhausted, rejected: B.rej, cb: brk, timedOut: timedOutCount };
        const state = { now, A, B, mw };
        if (stopIdx < STOPS.length && STOPS[stopIdx].when(state)) { showStop(STOPS[stopIdx]); return; }

        advDots(dotsA); advDots(dotsB);
        els.playhead.style.left = (Math.min(now, scenario.dur) / scenario.dur * 100) + '%';

        for (const L of [A, B]) {
          for (let i = L.pend.length - 1; i >= 0; i--) {
            if (L.pend[i].land <= tick) {
              const p = L.pend[i]; L.pend.splice(i, 1);
              let retried = false;
              // AsyncTimeout bounds the WHOLE operation (outermost: timeout ->
              // circuitBreaker -> bulkhead -> retry -> terminal). An entry clamped
              // to its deadline (see clampToDeadline) lands as a TimeoutError
              // failure here, regardless of what the untimed outcome would have
              // been, and is never retried.
              if (L === B && p.timedOut) {
                timedOutCount++;
              // Retry decision happens at landing time: a failed lane-B attempt gets
              // one more shot if maxAttempts allows it AND the budget grants a token;
              // otherwise (or with no budget at all) it counts as a final failure.
              } else if (L === B && retryCfg && !p.ok && (p.attempt + 1) < retryCfg.maxAttempts) {
                if (budget && budget.tryWithdraw(now)) {
                  const nextAttempt = p.attempt + 1;
                  // Full-jitter backoff (demo seconds); the retry is a NEW attempt
                  // against the backend, so its outcome is sampled at the later time.
                  const backoffSec = rnd() * Math.min(retryCfg.maxDelay, retryCfg.baseDelay * Math.pow(2, p.attempt));
                  const f2 = scenario.fault(now + backoffSec, rnd);
                  const landTicks = Math.max(1, Math.round((backoffSec + f2.ms) * 1000 / TICK));
                  // Composition order is timeout -> circuitBreaker -> bulkhead -> retry ->
                  // terminal: the bulkhead sits OUTSIDE retry, so one slot is acquired
                  // once and held for the WHOLE operation (all attempts), released only
                  // when the operation finally lands. Carry `bh` forward on every retry
                  // push, or a retried request leaks its slot forever. The deadline (and
                  // start) is likewise carried forward unchanged — it bounds the WHOLE
                  // operation, set once at the first attempt, not reset per retry — and
                  // clamped again here in case the backoff + this attempt would cross it.
                  const { land, timedOut } = clampToDeadline(tick, landTicks, p.deadline);
                  L.pend.push({ land, ok: f2.ok, attempt: nextAttempt, bh: p.bh, start: p.start, deadline: p.deadline, timedOut });
                  spawnDot(dotsB, els.trackB, f2.ok ? 'ok' : 'bad');
                  retried = true;
                  if (config.macroStrip) macroSeries[tick]++;
                } else if (budget) {
                  budgetExhausted = true;
                }
              }
              // Release the bulkhead slot only once the attempt truly finishes (not on
              // a retry re-push) — `p.bh` marks entries that actually acquired a slot,
              // so a null/absent bulkhead or a rejected (never-pushed) request is a no-op.
              // Breaker records ONCE per fully-exhausted retry sequence (not per attempt):
              // brk.res is called here, only on the terminal (non-retried) landing. A
              // timed-out entry is an outer-timeout cancellation: AsyncTimeout is
              // OUTERMOST, so the inner breaker's `except BaseException` clause does see
              // the CancelledError (it releases the in-flight probe slot) but does not
              // count it as a success/failure outcome — only the outer TimeoutError
              // surfaces to the caller.
              if (!retried) {
                L.if--;
                if (L === B && p.timedOut) { L.bad++; }
                else { if (L === B && brk) brk.res(p.ok, now); if (p.ok) L.ok++; else L.bad++; }
                if (L === B && bulk && p.bh) bulk.release();
              }
            }
          }
        }

        const n = Math.round(RPS * TICK / 1000);
        let lastFault = null;
        for (let i = 0; i < n; i++) {
          const f = scenario.fault(now, rnd);
          lastFault = f;
          const landTicks = Math.max(1, Math.round(f.ms * 1000 / TICK));
          A.if++; A.pend.push({ land: tick + landTicks, ok: f.ok, attempt: 0, ms: f.ms });
          spawnDot(dotsA, els.trackA, f.ok ? 'ok' : 'bad');
          if (brk && !brk.allow(now)) {
            B.rej++; spawnDot(dotsB, els.trackB, 'rej');
          } else if (bulk && !bulk.tryAcquire()) {
            // Pool is full: fail fast (BulkheadFullError) rather than queue — the
            // demo's acquireTimeout=0 choice (see makeBulkhead).
            B.rej++; spawnDot(dotsB, els.trackB, 'rej');
          } else {
            if (budget) budget.deposit(now);
            // Total deadline set once at the first attempt (Infinity when no
            // AsyncTimeout is configured, so the clamp below is always a no-op).
            const deadline = tmoCfg ? now + tmoCfg.timeout : Infinity;
            const { land, timedOut } = clampToDeadline(tick, landTicks, deadline);
            B.if++; B.pend.push({ land, ok: f.ok, attempt: 0, bh: !!bulk, start: now, deadline, timedOut });
            spawnDot(dotsB, els.trackB, f.ok ? 'ok' : 'bad');
            if (config.macroStrip) macroSeries[tick]++;
          }
        }
        updateUI(now, lastFault);
        if (config.macroStrip) {
          const peak = macroSeries.reduce((m, v) => Math.max(m, v), 0) || 1;
          renderRateStrip(els.macroStrip, macroSeries, tick + 1,
            { peakScale: peak, baseline: 0, outage: null, dur: scenario.dur * 1000 / TICK, cls: 'herd-bar-hw' });
          els.macroStage.textContent = config.stageLabel ? config.stageLabel(now) : '';
        }
        tick++;
        if (now >= scenario.dur) clearInterval(timer);
      }, TICK);
    }

    els.scenarios.querySelectorAll('.scenario-btn').forEach((btn) => {
      btn.addEventListener('click', () => {
        els.scenarios.querySelectorAll('.scenario-btn').forEach((b) => b.classList.remove('active'));
        btn.classList.add('active');
        selectedScenario = config.scenarios.find((s) => s.id === btn.dataset.scenario);
        els.play.disabled = false;
        els.scenLabel.textContent = 'Scenario: ' + selectedScenario.label;
        els.note.textContent = "Faithful model of httpware's " + describeChain(selectedScenario.chainB) +
          ' — not httpware running in your browser.';
        brk = null; bulk = null; retryCfg = null; budget = null; budgetExhausted = false;
        tmoCfg = null; timedOutCount = 0;
        setupOutageBar(selectedScenario);
        resetVisual();
      });
    });
    els.play.addEventListener('click', run);
    els.replay.addEventListener('click', run);
    // Auto-select the first scenario so first paint shows a coherent ready-to-play
    // state (correct flow-diagram boxes, Play enabled) instead of bare "—" placeholders.
    const firstScenarioBtn = els.scenarios.querySelector('.scenario-btn');
    if (firstScenarioBtn) firstScenarioBtn.click();
  }

  return { mount, mountHerd, _models: { makeCircuitBreaker, makeRetryBudget, makeBulkhead, simulateHerd },
    _render: { renderRateStrip }, _util: { mulberry }, REAL, TICK, ADV };
})();

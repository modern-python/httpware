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
    for (let i = 0; i <= steps; i++) {
      const t = (scenario.dur * i) / steps;
      const f = scenario.fault(t, worstRnd);
      if (!f.ok) {
        if (from === null) from = t;
        to = t;
        if (!label) label = f.label || 'DOWN';
      }
    }
    if (from === null) return null;
    return { from, to: Math.min(scenario.dur, to + scenario.dur / steps), label };
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
      <span class="k">&#10007; <span data-el="badA">0</span></span>
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
      <span class="k">&#10007; <span data-el="badB">0</span></span>
      <span class="k">&#9211; fast-failed <span data-el="rejB">0</span></span>
      <span class="stat" data-el="poolWrap"><span class="k">pool</span> <span class="big" data-el="poolB">&mdash;</span></span>
      <span class="stat"><span class="k">p99</span> <span class="big" data-el="latB">40ms</span></span>
    </div>
  </div>

  <p class="note" data-el="note">Faithful model of httpware, not httpware running in your browser. Pick a scenario above to begin.</p>
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
      ifA: $('ifA'), okA: $('okA'), badA: $('badA'), latA: $('latA'),
      laneB: $('laneB'), badgeB: $('badgeB'), srvB: $('srvB'), trackB: $('trackB'), brkB: $('brkB'),
      ifB: $('ifB'), okB: $('okB'), badB: $('badB'), rejB: $('rejB'), latB: $('latB'),
      poolWrap: $('poolWrap'), poolB: $('poolB'),
      note: $('note'),
      dimT: $('dimT'), dimB: $('dimB'), dimL: $('dimL'), dimR: $('dimR'), ring: $('ring'),
      coach: $('coach'), cArrow: $('cArrow'), cStep: $('cStep'), cTitle: $('cTitle'), cBody: $('cBody'), cGo: $('cGo'),
    };
    const ELS = { ifA: els.ifA, latA: els.latA, ifB: els.ifB, latB: els.latB, brkB: els.brkB, poolB: els.poolB };

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
    let bulk = null;
    let retryCfg = null, budget = null, budgetExhausted = false;
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

    // ---- spotlight: 4 dim panels leave a bright hole over the union of targets ----
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

    // ---- place coach on the side with the most room; arrow points at target ----
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

    function showStop(s) {
      paused = true;
      const nodes = s.spot.map((key) => ELS[key]).filter(Boolean);
      const hole = spotlight(nodes);
      els.cStep.textContent = `Step ${stopIdx + 1} of ${STOPS.length}`;
      els.cTitle.textContent = s.title;
      els.cBody.textContent = s.body;
      placeCoach(hole);
    }
    els.cGo.addEventListener('click', () => {
      els.coach.classList.remove('show');
      hideSpot();
      paused = false;
      stopIdx++;
    });

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
      [els.latA, els.latB, els.ifA, els.ifB].forEach((n) => { n.style.color = ''; });
      els.brkB.className = 'box'; els.brkB.textContent = brk ? 'breaker CLOSED' : 'no breaker';
      els.poolWrap.style.display = bulk ? '' : 'none';
      els.poolB.textContent = bulk ? (bulk.inUse + '/' + bulk.max) : '—';
      els.srvA.className = 'box'; els.srvA.textContent = 'server ✓';
      els.srvB.className = 'box'; els.srvB.textContent = 'server ✓';
      els.laneA.className = 'lane'; els.laneB.className = 'lane';
      els.playhead.style.left = '0%';
      els.badgeA.className = 'badge'; els.badgeA.textContent = 'no protection';
      els.badgeB.className = 'badge'; els.badgeB.textContent = selectedScenario ? chainLabel(selectedScenario.chainB) : 'CircuitBreaker';
      els.coach.classList.remove('show'); hideSpot();
    }

    function updateUI(now, lastFault) {
      els.ifA.textContent = A.if; els.okA.textContent = A.ok; els.badA.textContent = A.bad;
      els.ifB.textContent = B.if; els.okB.textContent = B.ok; els.badB.textContent = B.bad; els.rejB.textContent = B.rej;
      els.ifA.style.color = A.if > 10 ? 'var(--hw-bad)' : '';
      els.ifB.style.color = B.if <= 6 ? 'var(--hw-ok)' : '';
      if (bulk) els.poolB.textContent = bulk.inUse + '/' + bulk.max;
      // "Stress" covers two distinct fault shapes: outright failure (down) and a
      // high-latency-but-ok fault (slow, e.g. bulkhead.md's 5s dependency) — both must
      // read as backend trouble even though only `down` implies an error response.
      const down = !!(lastFault && !lastFault.ok);
      const slow = !!(lastFault && lastFault.ok && lastFault.ms >= 1.0);
      const stressed = down || slow;
      els.latA.textContent = stressed ? (A.if > 4 ? '12s+' : formatMs(lastFault.ms)) : '40ms';
      els.latA.style.color = stressed ? 'var(--hw-bad)' : '';
      els.latB.textContent = '40ms';
      els.latB.style.color = (down && brk && brk.state === 'OPEN') ? 'var(--hw-ok)' : '';
      const st = brk ? brk.state : 'CLOSED';
      els.brkB.className = 'box ' + (st === 'OPEN' ? 'open' : st === 'HALF_OPEN' ? 'half' : '');
      els.brkB.textContent = brk ? ('breaker ' + st) : 'no breaker';
      els.srvA.className = 'box' + (stressed ? ' down' : '');
      els.srvA.textContent = down ? ('server ✗' + (lastFault.label ? ' ' + lastFault.label : ''))
        : slow ? ('server ' + (lastFault.label || 'slow')) : 'server ✓';
      els.srvB.className = 'box' + (stressed ? ' down' : '');
      els.srvB.textContent = down ? 'server ✗' : slow ? 'server slow' : 'server ✓';
      els.laneA.classList.toggle('hot', stressed && A.if > 8);
      els.laneB.classList.toggle('safe', st === 'CLOSED' && !stressed);
      els.badgeA.className = 'badge' + (stressed ? ' bad' : '');
      els.badgeA.textContent = stressed ? 'drowning' : 'no protection';
      const okBadge = st === 'CLOSED' && brk && !stressed;
      els.badgeB.className = 'badge ' + (st === 'OPEN' ? 'warn' : okBadge ? 'ok' : '');
      els.badgeB.textContent = st === 'OPEN' ? 'fast-failing' : st === 'HALF_OPEN' ? 'probing' : chainLabel(selectedScenario.chainB);
    }

    function run() {
      if (!selectedScenario) return;
      const scenario = selectedScenario;
      STOPS = config.buildStops(scenario);
      resetVisual();
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
      rnd = mulberry(SEED);
      els.brkB.textContent = brk ? 'breaker CLOSED' : 'no breaker';
      els.poolWrap.style.display = bulk ? '' : 'none';
      els.poolB.textContent = bulk ? (bulk.inUse + '/' + bulk.max) : '—';

      timer = setInterval(() => {
        if (paused) return;
        const now = tick * TICK / 1000;
        const mw = { state: brk ? brk.state : 'CLOSED', recovered: brk ? brk.recovered : false,
          budgetExhausted, rejected: B.rej, cb: brk };
        const state = { now, A, B, mw };
        if (stopIdx < STOPS.length && STOPS[stopIdx].when(state)) { showStop(STOPS[stopIdx]); return; }

        advDots(dotsA); advDots(dotsB);
        els.playhead.style.left = (Math.min(now, scenario.dur) / scenario.dur * 100) + '%';

        for (const L of [A, B]) {
          for (let i = L.pend.length - 1; i >= 0; i--) {
            if (L.pend[i].land <= tick) {
              const p = L.pend[i]; L.pend.splice(i, 1);
              if (L === B && brk) brk.res(p.ok, now);
              let retried = false;
              // Retry decision happens at landing time: a failed lane-B attempt gets
              // one more shot if maxAttempts allows it AND the budget grants a token;
              // otherwise (or with no budget at all) it counts as a final failure.
              if (L === B && retryCfg && !p.ok && (p.attempt + 1) < retryCfg.maxAttempts) {
                if (budget && budget.tryWithdraw(now)) {
                  const nextAttempt = p.attempt + 1;
                  // Full-jitter backoff (demo seconds); the retry is a NEW attempt
                  // against the backend, so its outcome is sampled at the later time.
                  const backoffSec = rnd() * Math.min(retryCfg.maxDelay, retryCfg.baseDelay * Math.pow(2, p.attempt));
                  const f2 = scenario.fault(now + backoffSec, rnd);
                  const landTicks = Math.max(1, Math.round((backoffSec + f2.ms) * 1000 / TICK));
                  L.pend.push({ land: tick + landTicks, ok: f2.ok, attempt: nextAttempt });
                  spawnDot(dotsB, els.trackB, f2.ok ? 'ok' : 'bad');
                  retried = true;
                } else if (budget) {
                  budgetExhausted = true;
                }
              }
              // Release the bulkhead slot only once the attempt truly finishes (not on
              // a retry re-push) — `p.bh` marks entries that actually acquired a slot,
              // so a null/absent bulkhead or a rejected (never-pushed) request is a no-op.
              if (!retried) { L.if--; if (p.ok) L.ok++; else L.bad++;
                if (L === B && bulk && p.bh) bulk.release(); }
            }
          }
        }

        const n = Math.round(RPS * TICK / 1000);
        let lastFault = null;
        for (let i = 0; i < n; i++) {
          const f = scenario.fault(now, rnd);
          lastFault = f;
          const landTicks = Math.max(1, Math.round(f.ms * 1000 / TICK));
          A.if++; A.pend.push({ land: tick + landTicks, ok: f.ok, attempt: 0 });
          spawnDot(dotsA, els.trackA, f.ok ? 'ok' : 'bad');
          if (brk && !brk.allow(now)) {
            B.rej++; spawnDot(dotsB, els.trackB, 'rej');
          } else if (bulk && !bulk.tryAcquire()) {
            // Pool is full: fail fast (BulkheadFullError) rather than queue — the
            // demo's acquireTimeout=0 choice (see makeBulkhead).
            B.rej++; spawnDot(dotsB, els.trackB, 'rej');
          } else {
            if (budget) budget.deposit(now);
            B.if++; B.pend.push({ land: tick + landTicks, ok: f.ok, attempt: 0, bh: !!bulk });
            spawnDot(dotsB, els.trackB, f.ok ? 'ok' : 'bad');
          }
        }
        updateUI(now, lastFault);
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
        setupOutageBar(selectedScenario);
        resetVisual();
      });
    });
    els.play.addEventListener('click', run);
    els.replay.addEventListener('click', run);
  }

  return { mount, _models: { makeCircuitBreaker, makeRetryBudget, makeBulkhead }, _util: { mulberry }, REAL, TICK, ADV };
})();

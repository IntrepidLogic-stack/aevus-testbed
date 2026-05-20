/**
 * Aevus Dashboard — Latency Widget
 *
 * Live ticker for the two P-008 patent-relevant latencies:
 *   • detection_latency_ms  — physical condition → alarm fired
 *   • rca_latency_ms        — alarm fired → AI root cause narrative
 *
 * Polls /api/v1/metrics/latency every 5s, renders rolling p95 + count
 * as compact tickers with target-threshold pass/fail status.
 *
 * This is the patent-demo evidence surface — the live numbers projected
 * on screen during a board / advisory walkthrough alongside the actual
 * alarm flow in the main console.
 *
 * Brand-compliant per CLAUDE.md:
 *   • Manrope for label text, JetBrains Mono for numerics
 *   • Status color tokens (good ≥ target, warn ≤ 2× target, bad above)
 *   • Inline SVG icons only
 *   • WCAG-AA contrast on the dark surface
 *
 * Sidecar — no changes to Aevus_Console.html. Activation is a single
 * <script> tag.
 */

(function () {
  'use strict';

  const DEFAULT_CONFIG = {
    apiBase: window.AEVUS_API_URL || `${window.location.protocol}//${window.location.host}`,
    apiKey: window.AEVUS_API_KEY || '',
    pollIntervalMs: 5000,
    // Where to mount in the DOM. Default = fixed top-right corner.
    // Pass a CSS selector via window.AEVUS_LATENCY_MOUNT_SELECTOR to
    // embed it inside an existing dashboard section instead.
    mountSelector: window.AEVUS_LATENCY_MOUNT_SELECTOR || null,
  };
  const config = Object.assign({}, DEFAULT_CONFIG, window.AEVUS_LATENCY_CONFIG || {});

  const STYLE = `
    #aevus-latency-widget {
      position: ${config.mountSelector ? 'static' : 'fixed'};
      ${config.mountSelector ? '' : 'top: 24px; right: 24px;'}
      background: #161E33;             /* --bg-card */
      border: 1px solid rgba(6,182,212,0.2);
      border-radius: 10px;
      box-shadow: 0 8px 24px rgba(0,0,0,0.35);
      color: #E5E7EB;
      font-family: 'Manrope', system-ui, sans-serif;
      font-size: 12px;
      padding: 12px 14px;
      min-width: 280px;
      z-index: 9990;
    }
    #aevus-latency-widget .aevus-lw-header {
      display: flex;
      align-items: center;
      gap: 8px;
      margin-bottom: 10px;
      padding-bottom: 8px;
      border-bottom: 1px solid rgba(255,255,255,0.06);
    }
    #aevus-latency-widget .aevus-lw-title {
      font-weight: 600;
      font-size: 10px;
      letter-spacing: 0.1em;
      text-transform: uppercase;
      color: #06B6D4;                  /* --accent */
      flex: 1;
    }
    #aevus-latency-widget .aevus-lw-dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: #A78BFA;             /* unknown */
      transition: background 0.3s;
    }
    #aevus-latency-widget .aevus-lw-dot.live { background: #10D478; }
    #aevus-latency-widget .aevus-lw-dot.stale { background: #FBBF24; }
    #aevus-latency-widget .aevus-lw-dot.error { background: #EF4444; }
    #aevus-latency-widget .aevus-lw-row {
      display: grid;
      grid-template-columns: 1fr auto;
      align-items: baseline;
      gap: 10px;
      margin-bottom: 6px;
    }
    #aevus-latency-widget .aevus-lw-label {
      color: #9CA3AF;
      font-size: 11px;
    }
    #aevus-latency-widget .aevus-lw-value {
      font-family: 'JetBrains Mono', ui-monospace, monospace;
      font-size: 16px;
      font-weight: 600;
      letter-spacing: 0.02em;
    }
    #aevus-latency-widget .aevus-lw-value.good { color: #10D478; }
    #aevus-latency-widget .aevus-lw-value.warn { color: #FBBF24; }
    #aevus-latency-widget .aevus-lw-value.bad { color: #EF4444; }
    #aevus-latency-widget .aevus-lw-value.empty { color: #6B7280; }
    #aevus-latency-widget .aevus-lw-sub {
      grid-column: 1 / -1;
      font-family: 'JetBrains Mono', ui-monospace, monospace;
      font-size: 10px;
      color: #6B7280;
      margin-top: -2px;
      letter-spacing: 0.02em;
    }
    #aevus-latency-widget .aevus-lw-footer {
      margin-top: 6px;
      padding-top: 8px;
      border-top: 1px solid rgba(255,255,255,0.04);
      font-size: 10px;
      color: #6B7280;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
    #aevus-latency-widget .aevus-lw-reset {
      background: transparent;
      border: 1px solid rgba(255,255,255,0.1);
      color: #9CA3AF;
      font-family: inherit;
      font-size: 10px;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      padding: 3px 8px;
      border-radius: 4px;
      cursor: pointer;
    }
    #aevus-latency-widget .aevus-lw-reset:hover { color: #E5E7EB; border-color: rgba(255,255,255,0.25); }
  `;

  function mount() {
    if (document.getElementById('aevus-latency-widget')) return;

    const style = document.createElement('style');
    style.id = 'aevus-latency-widget-style';
    style.textContent = STYLE;
    document.head.appendChild(style);

    const el = document.createElement('div');
    el.id = 'aevus-latency-widget';
    el.setAttribute('role', 'status');
    el.setAttribute('aria-live', 'polite');
    el.innerHTML = `
      <div class="aevus-lw-header">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
             stroke="#06B6D4" stroke-width="1.8" stroke-linecap="round"
             stroke-linejoin="round" aria-hidden="true">
          <circle cx="12" cy="12" r="9"></circle>
          <path d="M12 7 v5 l3 2"></path>
        </svg>
        <div class="aevus-lw-title">Latency · P95</div>
        <div class="aevus-lw-dot" aria-label="connection status"></div>
      </div>
      <div class="aevus-lw-row" data-row="detection">
        <span class="aevus-lw-label">Event → Alarm</span>
        <span class="aevus-lw-value empty" data-value="detection">—</span>
        <span class="aevus-lw-sub" data-sub="detection">target ≤ 500 ms · 0 samples</span>
      </div>
      <div class="aevus-lw-row" data-row="rca">
        <span class="aevus-lw-label">Alarm → AI Root Cause</span>
        <span class="aevus-lw-value empty" data-value="rca">—</span>
        <span class="aevus-lw-sub" data-sub="rca">target ≤ 3.0 s · 0 samples</span>
      </div>
      <div class="aevus-lw-footer">
        <span data-stamp>updated —</span>
        <button class="aevus-lw-reset" type="button" aria-label="Reset histograms">Reset</button>
      </div>
    `;

    if (config.mountSelector) {
      const host = document.querySelector(config.mountSelector);
      if (host) {
        host.appendChild(el);
      } else {
        console.warn(`[Aevus Latency] mount selector '${config.mountSelector}' not found, falling back to fixed position`);
        document.body.appendChild(el);
      }
    } else {
      document.body.appendChild(el);
    }

    el.querySelector('.aevus-lw-reset').addEventListener('click', resetHistograms);
  }

  // ── Polling ─────────────────────────────────────────────────────────
  let pollTimer = null;
  let lastSuccessTs = 0;

  async function fetchSnapshot() {
    const url = `${config.apiBase}/api/v1/metrics/latency`;
    const headers = config.apiKey ? { 'X-API-Key': config.apiKey } : {};
    const resp = await fetch(url, { headers, cache: 'no-store' });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    return await resp.json();
  }

  async function resetHistograms() {
    const url = `${config.apiBase}/api/v1/metrics/latency/reset`;
    const headers = config.apiKey ? { 'X-API-Key': config.apiKey } : {};
    try {
      await fetch(url, { method: 'POST', headers });
      tick();   // immediate re-render with the zeroed state
    } catch (e) {
      console.warn('[Aevus Latency] reset failed:', e);
    }
  }

  function formatLatency(ms) {
    if (ms == null || ms === 0) return '—';
    if (ms >= 1000) return (ms / 1000).toFixed(2) + ' s';
    return Math.round(ms) + ' ms';
  }

  function classifyAgainstTarget(value, target) {
    if (value == null || value === 0) return 'empty';
    if (value <= target) return 'good';
    if (value <= target * 2) return 'warn';
    return 'bad';
  }

  function render(snapshot) {
    mount();
    const el = document.getElementById('aevus-latency-widget');
    if (!el) return;

    const detection = snapshot.histograms?.detection_latency_ms || {};
    const rca = snapshot.histograms?.rca_latency_ms || {};

    // Detection — target 500ms.
    const detValueEl = el.querySelector('[data-value="detection"]');
    const detSubEl   = el.querySelector('[data-sub="detection"]');
    detValueEl.textContent = formatLatency(detection.p95_ms);
    detValueEl.className = 'aevus-lw-value ' + classifyAgainstTarget(detection.p95_ms, 500);
    detSubEl.textContent =
      `target ≤ 500 ms · ${detection.count || 0} samples` +
      (detection.count > 0 ? ` · med ${formatLatency(detection.p50_ms)}` : '');

    // RCA — target 3000ms.
    const rcaValueEl = el.querySelector('[data-value="rca"]');
    const rcaSubEl   = el.querySelector('[data-sub="rca"]');
    rcaValueEl.textContent = formatLatency(rca.p95_ms);
    rcaValueEl.className = 'aevus-lw-value ' + classifyAgainstTarget(rca.p95_ms, 3000);
    rcaSubEl.textContent =
      `target ≤ 3.0 s · ${rca.count || 0} samples` +
      (rca.count > 0 ? ` · med ${formatLatency(rca.p50_ms)}` : '');

    el.querySelector('[data-stamp]').textContent =
      'updated ' + new Date().toLocaleTimeString([], { hour12: false });

    const dot = el.querySelector('.aevus-lw-dot');
    dot.classList.remove('stale', 'error');
    dot.classList.add('live');
    lastSuccessTs = Date.now();
  }

  function markStale(err) {
    mount();
    const el = document.getElementById('aevus-latency-widget');
    if (!el) return;
    const dot = el.querySelector('.aevus-lw-dot');
    dot.classList.remove('live');
    // Within 30s of last success = stale (yellow); after = error (red).
    const ageMs = Date.now() - lastSuccessTs;
    if (lastSuccessTs > 0 && ageMs < 30_000) {
      dot.classList.add('stale');
      dot.classList.remove('error');
    } else {
      dot.classList.add('error');
      dot.classList.remove('stale');
    }
    if (err) console.warn('[Aevus Latency] poll failed:', err.message || err);
  }

  async function tick() {
    try {
      const snap = await fetchSnapshot();
      render(snap);
    } catch (e) {
      markStale(e);
    }
  }

  function start() {
    mount();
    tick();
    pollTimer = setInterval(tick, config.pollIntervalMs);
  }

  function stop() {
    clearInterval(pollTimer);
    pollTimer = null;
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }

  // Public API for manual control + console testing.
  window.AEVUS_LATENCY = { tick, start, stop, render, resetHistograms };
})();

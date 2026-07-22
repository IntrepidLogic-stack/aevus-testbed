/**
 * Aevus HPHMI component module — P1 (Restyle Spec v1.0)
 * ─────────────────────────────────────────────────────────────────────
 * Canonical BandBar component + post-render transforms that replace
 * radial "score donut" gauges with band indicators.
 *
 * Why an overlay module: api-client.js is a minified bundle; the
 * established pattern for evolving this dashboard is unminified overlay
 * modules (see rad-hover-live.js). New components live here; renderers
 * in the bundle get transformed after they paint.
 *
 * HPHMI rationale (spec §5.1): a radial spends ~50x the ink of the number
 * it decorates and encodes no scale. A BandBar shows position-relative-
 * to-normal-band pre-cognitively: track, shaded normal band, limit ticks,
 * pointer. Normal state is gray; color appears only when abnormal.
 *
 * Shared band scale (spec Law 9, backend truth): 80-100 good / 50-79
 * degrading / <50 critical — matches health_score.py. Pearls stay 60/30
 * until the backend remap lands (docs/HANDOFF_PEARL_BAND_UNIFICATION.md).
 */
(function () {
  'use strict';

  var BANDS = { good: 80, warn: 50 };  // unified scale edges (score space)

  // ── styles ───────────────────────────────────────────────────────────
  var CSS = [
    '.hphmi-bandbar { display:flex; flex-direction:column; gap:6px; min-width:140px; }',
    '.hphmi-bandbar-head { display:flex; align-items:baseline; justify-content:space-between; gap:10px; }',
    '.hphmi-bandbar-label { font-size:10px; letter-spacing:1.2px; text-transform:uppercase; color:var(--text-muted); font-weight:600; font-family:var(--font-body); }',
    '.hphmi-bandbar-value { font-family:var(--font-mono); font-size:15px; font-weight:600; color:#C7CFD6; font-variant-numeric:tabular-nums; }',
    '.hphmi-bandbar-value .unit { font-size:10px; color:var(--text-muted); font-weight:400; margin-left:3px; }',
    '.hphmi-bandbar-track { position:relative; height:8px; background:#171B1F; border-radius:2px; }',
    '.hphmi-bandbar-band { position:absolute; top:0; bottom:0; background:#333D46; border-radius:2px; }',
    '.hphmi-bandbar-tick { position:absolute; top:-2px; bottom:-2px; width:1.8px; background:#5A646E; }',
    '.hphmi-bandbar-tick[data-alarm="warn"] { background:#FBBF24; }',
    '.hphmi-bandbar-tick[data-alarm="bad"]  { background:#EF4444; }',
    '.hphmi-bandbar-pointer { position:absolute; top:-3px; width:2px; height:14px; background:#E8ECEF; border-radius:1px; transition:left 0.4s ease; }',
    '.hphmi-bandbar-caption { font-size:9px; color:var(--text-muted); font-family:var(--font-mono); }',
    /* out-of-band states: pointer takes the band color it violated */
    '.hphmi-bandbar[data-state="warn"] .hphmi-bandbar-pointer { background:#FBBF24; }',
    '.hphmi-bandbar[data-state="bad"]  .hphmi-bandbar-pointer { background:#EF4444; }',
    '.hphmi-bandbar[data-state="warn"] .hphmi-bandbar-value   { color:#FBBF24; }',
    '.hphmi-bandbar[data-state="bad"]  .hphmi-bandbar-value   { color:#EF4444; }',
    /* stale: hatch + hollow pointer (spec Law 5) */
    '.hphmi-bandbar[data-stale="1"] .hphmi-bandbar-track { opacity:0.55; background:repeating-linear-gradient(45deg,#171B1F,#171B1F 4px,#232A31 4px,#232A31 8px); }',
    '.hphmi-bandbar[data-stale="1"] .hphmi-bandbar-pointer { background:transparent; border:1px solid #8A949E; }'
  ].join('\n');

  function injectStyles() {
    if (document.getElementById('hphmi-styles')) return;
    var el = document.createElement('style');
    el.id = 'hphmi-styles';
    el.textContent = CSS;
    document.head.appendChild(el);
  }

  // ── canonical component ──────────────────────────────────────────────
  /**
   * bandBar(opts) → HTML string
   *  value        number (required)
   *  min,max      scale, default 0..100
   *  bandLo/bandHi normal-band edges (defaults: unified 80..100)
   *  ticks        [{at, alarm?: 'warn'|'bad'}]
   *  label, unit, caption, stale
   * State derives from the band: inside → normal; below bandLo → 'warn';
   * below warnTick (if any 'bad' tick) → 'bad'.
   */
  function bandBar(opts) {
    var min = opts.min != null ? opts.min : 0;
    var max = opts.max != null ? opts.max : 100;
    var bandLo = opts.bandLo != null ? opts.bandLo : BANDS.good;
    var bandHi = opts.bandHi != null ? opts.bandHi : max;
    var v = Math.max(min, Math.min(max, opts.value));
    var pct = function (x) { return ((x - min) / (max - min) * 100).toFixed(1) + '%'; };

    var state = 'normal';
    if (v < bandLo || v > bandHi) state = 'warn';
    (opts.ticks || []).forEach(function (t) {
      if (t.alarm === 'bad' && ((t.at <= bandLo && v < t.at) || (t.at >= bandHi && v > t.at))) state = 'bad';
    });

    var ticksHtml = (opts.ticks || []).map(function (t) {
      return '<div class="hphmi-bandbar-tick" data-alarm="' + (t.alarm || '') +
             '" style="left:' + pct(t.at) + ';"></div>';
    }).join('');

    return '<div class="hphmi-bandbar" data-state="' + state + '"' +
      (opts.stale ? ' data-stale="1"' : '') + '>' +
      '<div class="hphmi-bandbar-head">' +
        (opts.label ? '<span class="hphmi-bandbar-label">' + opts.label + '</span>' : '') +
        '<span class="hphmi-bandbar-value">' + opts.value +
          (opts.unit ? '<span class="unit">' + opts.unit + '</span>' : '') + '</span>' +
      '</div>' +
      '<div class="hphmi-bandbar-track">' +
        '<div class="hphmi-bandbar-band" style="left:' + pct(bandLo) + ';right:' + (100 - parseFloat(pct(bandHi))).toFixed(1) + '%;"></div>' +
        ticksHtml +
        '<div class="hphmi-bandbar-pointer" style="left:' + pct(v) + ';"></div>' +
      '</div>' +
      (opts.caption ? '<div class="hphmi-bandbar-caption">' + opts.caption + '</div>' : '') +
      '</div>';
  }

  // ── transform: radial score donuts → BandBars ────────────────────────
  // Targets: an <svg> whose gauge circle has stroke-dasharray, r ≥ 40,
  // and whose text reads "N/100" (score gauges only — charts untouched).
  function transformRadials(root) {
    var svgs = (root || document).querySelectorAll('svg');
    for (var i = 0; i < svgs.length; i++) {
      var svg = svgs[i];
      if (svg.__hphmiDone) continue;
      var circle = svg.querySelector('circle[stroke-dasharray]');
      if (!circle) continue;
      var r = parseFloat(circle.getAttribute('r') || '0');
      if (r < 40) continue;
      var m = (svg.textContent || '').trim().match(/^(\d{1,3})\s*\/\s*100\b/);
      if (!m) continue;
      var score = parseInt(m[1], 10);
      svg.__hphmiDone = true;

      // No label on the bar: the host card already carries its own title
      // (rendering it again doubles the label — observed with DISPATCH
      // SAFETY). The bar contributes value + band anatomy only.
      var wrap = document.createElement('div');
      wrap.style.cssText = 'padding:8px 4px;min-width:150px;';
      wrap.innerHTML = bandBar({
        value: score, unit: '/100',
        ticks: [{ at: BANDS.warn, alarm: 'bad' }, { at: BANDS.good }],
        stale: !!svg.closest('[data-stale="1"]')
      });
      svg.parentElement.replaceChild(wrap, svg);
    }
  }

  // ── transform: operator view carries zero currency strings ───────────
  // Spec Law + role table (§6): dollars are a Manager-view goal hierarchy;
  // operators comprehend in process variables. Pure-currency leaf values
  // blank to "—"; rows labeled FINANCIAL hide. Reversible by switching
  // roles (values re-render from the bundle on next paint).
  function purgeFinancials() {
    var role = (window.aevusRole || (function () {
      try { return localStorage.getItem('aevus-role'); } catch (e) { return null; }
    })() || '').toLowerCase();
    if (role && role !== 'operator') return;

    var leaves = document.querySelectorAll('div,span,td');
    for (var i = 0; i < leaves.length; i++) {
      var el = leaves[i];
      if (el.children.length !== 0 || el.__hphmiFin) continue;
      var t = (el.textContent || '').trim();
      if (/^[-+]?\$[\d,]+(\.\d+)?[KMk]?(\s*\/\s*(yr|mo|day))?$/.test(t)) {
        el.__hphmiFin = true;
        el.textContent = '—';
        el.title = 'Financial impact — available in Manager view';
      } else if (t === 'FINANCIAL' && el.parentElement && !el.parentElement.__hphmiFin) {
        el.parentElement.__hphmiFin = true;
        el.parentElement.style.display = 'none';
      }
    }
  }

  // ── observer: transforms re-apply as the bundle re-renders ───────────
  var scheduled = false;
  function schedule() {
    if (scheduled) return;
    scheduled = true;
    requestAnimationFrame(function () {
      scheduled = false;
      try { transformRadials(); } catch (e) { /* never break the page */ }
      try { purgeFinancials(); } catch (e) { /* never break the page */ }
    });
  }

  function start() {
    injectStyles();
    schedule();
    new MutationObserver(schedule).observe(document.body, { childList: true, subtree: true });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }

  window.AevusHPHMI = { bandBar: bandBar, transformRadials: transformRadials, BANDS: BANDS };
})();

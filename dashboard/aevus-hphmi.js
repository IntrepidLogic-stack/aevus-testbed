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
    el.textContent = CSS + '\n' + STRIP_CSS + '\n' + L2_CSS;
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

  // ── L1 scan strip: area tiles + alarm priority strip (spec §6) ───────
  // The 3-second scan needs one configural gestalt, not a grid of
  // abstractions: four tiles in process order, each the worst-of its
  // member assets, plus shape-coded alarm counts. Every tile is a door.
  // Data: window._aevusAssets/_aevusAlarms (published by the bundle's
  // 10s interval — see P1-4 exposure).
  var AREAS = [
    { key: 'wellhead',  label: 'WELLHEAD / SEP',  match: /^(WELL|SEP|REF-CWRU)/i, door: '#unit-wellhead' },
    { key: 'compress',  label: 'COMPRESSION',      match: /^(CMP|RTU)/i,               door: '#unit-compress' },
    { key: 'tank',      label: 'TANK / METERING',  match: /^(TNK|MET|EFM|REF-MORRIS)/i, door: '#unit-tank' },
    { key: 'comms',     label: 'COMMS PATH',       match: /^(RAD|RTR|SW|WAN|EDGE|SHOP)/i, door: '#unit-comms' }
  ];
  var PRIO = [
    { key: 'critical', glyph: '■', color: '#FF4136', n: 1 },
    { key: 'high',     glyph: '▲', color: '#FF851B', n: 2 },
    { key: 'warning',  glyph: '●', color: '#FFDC00', n: 3 },
    { key: 'medium',   glyph: '●', color: '#FFDC00', n: 3 },
    { key: 'low',      glyph: '◇', color: '#E6E6FA', n: 4 }
  ];

  var STRIP_CSS = [
    '#hphmi-l1-strip { display:flex; gap:10px; align-items:stretch; flex-wrap:wrap; margin:10px 0 14px; }',
    '.hphmi-tile { flex:1; min-width:150px; background:var(--bg-card); border:1px solid var(--border); border-radius:4px; padding:10px 12px; cursor:pointer; display:flex; flex-direction:column; gap:6px; }',
    '.hphmi-tile:hover { border-color:var(--accent); }',
    '.hphmi-tile-head { display:flex; align-items:center; justify-content:space-between; gap:8px; }',
    '.hphmi-tile-label { font-size:9px; letter-spacing:1.2px; color:var(--text-muted); font-weight:600; }',
    '.hphmi-tile-state { font-family:var(--font-mono); font-size:10px; font-weight:700; color:#8A949E; }',
    '.hphmi-tile[data-band="warn"] .hphmi-tile-state { color:#FBBF24; }',
    '.hphmi-tile[data-band="bad"]  .hphmi-tile-state { color:#EF4444; }',
    '.hphmi-tile[data-band="bad"] { border-left:3px solid #EF4444; }',
    '.hphmi-tile[data-band="warn"] { border-left:3px solid #FBBF24; }',
    '.hphmi-tile-sub { font-size:10px; color:var(--text-muted); font-family:var(--font-mono); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }',
    '.hphmi-alarmstrip { display:flex; align-items:center; gap:8px; padding:0 4px; }',
    '.hphmi-alarmchip { display:inline-flex; align-items:center; gap:4px; font-family:var(--font-mono); font-size:11px; font-weight:700; padding:2px 8px; border-radius:2px; cursor:pointer; border:1px solid var(--border); color:var(--text-muted); }',
    '.hphmi-alarmchip[data-active="1"][data-p="1"] { background:#FF4136; color:#14181C; border-color:#FF4136; }',
    '.hphmi-alarmchip[data-active="1"][data-p="2"] { background:#FF851B; color:#14181C; border-color:#FF851B; }',
    '.hphmi-alarmchip[data-active="1"][data-p="3"] { background:#FFDC00; color:#14181C; border-color:#FFDC00; }'
  ].join('\n');

  function worstBand(assets, alarms) {
    // worst-of: any unresolved critical alarm → bad; health <50 → bad;
    // unresolved warning/high or health <80 or stale → warn; else normal.
    var band = 'normal';
    var stale = window._staleAssetIds || [];
    for (var i = 0; i < assets.length; i++) {
      var h = assets[i].health;
      if (h != null && h < BANDS.warn) return 'bad';
      if ((h != null && h < BANDS.good) || stale.indexOf(assets[i].id) >= 0) band = 'warn';
    }
    for (var j = 0; j < alarms.length; j++) {
      if (alarms[j].status === 'resolved') continue;
      if (alarms[j].severity === 'critical') return 'bad';
      band = 'warn';
    }
    return band;
  }

  function renderL1Strip() {
    var page = document.querySelector('section[data-page="overview"]');
    var banner = document.getElementById('situation-banner');
    if (!page || !banner || !banner.parentElement) return;
    var assets = window._aevusAssets || [];
    var alarms = window._aevusAlarms || [];
    if (!assets.length && !alarms.length) return;

    var host = document.getElementById('hphmi-l1-strip');
    if (!host) {
      host = document.createElement('div');
      host.id = 'hphmi-l1-strip';
      banner.parentElement.insertBefore(host, banner.nextSibling);
    }

    var tiles = AREAS.map(function (a) {
      var members = assets.filter(function (t) { return a.match.test(t.id || ''); });
      var mAlarms = alarms.filter(function (al) { return a.match.test(al.asset_id || ''); });
      var band = worstBand(members, mAlarms);
      var top = mAlarms.filter(function (al) { return al.status !== 'resolved'; })
        .sort(function (p, q) { return (p.severity === 'critical' ? 0 : 1) - (q.severity === 'critical' ? 0 : 1); })[0];
      var stale = (window._staleAssetIds || []).filter(function (id) { return a.match.test(id); }).length;
      var sub = top ? ((top.asset_id || '') + ' · ' + (top.alarm || top.message || '')) :
                stale ? (stale + ' stale source' + (stale > 1 ? 's' : '')) :
                (members.length ? members.length + ' assets · quiet' : 'no assets');
      var state = band === 'bad' ? 'ABN' : band === 'warn' ? 'WATCH' : 'OK';
      return '<div class="hphmi-tile" data-band="' + band + '" onclick="window.location.hash=\'' + a.door + '\'">' +
        '<div class="hphmi-tile-head"><span class="hphmi-tile-label">' + a.label + '</span>' +
        '<span class="hphmi-tile-state">' + state + '</span></div>' +
        '<div class="hphmi-tile-sub">' + sub + '</div></div>';
    }).join('');

    var counts = { 1: 0, 2: 0, 3: 0, 4: 0 };
    alarms.forEach(function (al) {
      if (al.status === 'resolved') return;
      var p = PRIO.find(function (pp) { return pp.key === al.severity; });
      counts[p ? p.n : 4]++;
    });
    var strip = '<div class="hphmi-alarmstrip">' + [1, 2, 3].map(function (n) {
      var g = n === 1 ? '■' : n === 2 ? '▲' : '●';
      return '<span class="hphmi-alarmchip" data-p="' + n + '" data-active="' + (counts[n] > 0 ? 1 : 0) +
        '" onclick="window.location.hash=\'#alarms\'">' + g + ' ' + n + ' · ' + counts[n] + '</span>';
    }).join('') + '</div>';

    // Only touch the DOM on change — this runs inside the observer cycle,
    // and an unconditional innerHTML write would re-trigger it every frame.
    var html = tiles + strip;
    if (host.__lastHtml !== html) {
      host.__lastHtml = html;
      host.innerHTML = html;
    }
  }

  // ── trend-to-limit sampler (spec Law 6) ──────────────────────────────
  // Rolling per-asset health history; a sustained downward slope earns a
  // projection caption on the matching tile: "→ 50 in ~Nm". History
  // without projection leaves Level-3 SA to the operator's arithmetic.
  var HIST = {};        // asset id → [{t, v}]
  var HORIZON = 8;      // samples kept (~80s demo / real cadence varies)
  function sampleTrends() {
    var assets = window._aevusAssets || [];
    var now = Date.now();
    assets.forEach(function (a) {
      if (a.health == null) return;
      var h = (HIST[a.id] = HIST[a.id] || []);
      h.push({ t: now, v: a.health });
      if (h.length > HORIZON) h.shift();
    });
    // annotate tiles
    AREAS.forEach(function (area) {
      var worst = null;
      Object.keys(HIST).forEach(function (id) {
        if (!area.match.test(id) || HIST[id].length < 4) return;
        var h = HIST[id], n = h.length;
        var slope = (h[n - 1].v - h[0].v) / ((h[n - 1].t - h[0].t) / 60000); // per minute
        if (slope < -0.05) {
          var target = h[n - 1].v > BANDS.good ? BANDS.good : BANDS.warn;
          var mins = Math.round((h[n - 1].v - target) / -slope);
          if (mins > 0 && mins < 720 && (!worst || mins < worst.mins)) worst = { id: id, mins: mins, target: target };
        }
      });
      if (worst) {
        var tile = document.querySelector('.hphmi-tile[data-band] .hphmi-tile-label');
        var tiles = document.querySelectorAll('.hphmi-tile');
        for (var i = 0; i < tiles.length; i++) {
          if (tiles[i].textContent.indexOf(area.label) >= 0) {
            var sub = tiles[i].querySelector('.hphmi-tile-sub');
            if (sub) sub.textContent = worst.id + ' → ' + worst.target + ' in ~' + worst.mins + 'm';
            break;
          }
        }
      }
    });
  }
  setInterval(sampleTrends, 10000);

  // ── L2 unit operating displays (spec §6 — the missing layer) ─────────
  // Hash routes #unit-wellhead / #unit-compress / #unit-tank / #unit-comms.
  // Between the everything-overview and raw tables there was nowhere to
  // work an upset; these pages are where operators live during one.
  // Content: unit-scoped alarms (AlarmRow-lite), member-asset BandBars
  // from live vitals when present, and the serving path fragment. The
  // area tiles' doors land here.
  var L2_CSS = [
    '#hphmi-l2 { padding:0 4px; }',
    '.hphmi-l2-head { display:flex; align-items:center; justify-content:space-between; margin:6px 0 14px; }',
    '.hphmi-l2-title { font-size:20px; font-weight:700; color:var(--text-primary); font-family:var(--font-heading); letter-spacing:0.5px; }',
    '.hphmi-l2-back { font-size:11px; color:var(--accent); cursor:pointer; font-family:var(--font-mono); }',
    '.hphmi-l2-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(220px,1fr)); gap:12px; margin-bottom:16px; }',
    '.hphmi-l2-card { background:var(--bg-card); border:1px solid var(--border); border-radius:4px; padding:12px 14px; }',
    '.hphmi-l2-card-title { font-size:10px; letter-spacing:1.2px; color:var(--text-muted); font-weight:600; margin-bottom:8px; }',
    '.hphmi-l2-alarms { margin-top:4px; }',
    '.hphmi-l2-alarm { display:flex; align-items:center; gap:10px; padding:8px 10px; border-bottom:1px solid var(--border); font-size:12px; }',
    '.hphmi-l2-alarm:last-child { border-bottom:none; }',
    '.hphmi-l2-alarm .chip { font-family:var(--font-mono); font-size:10px; font-weight:700; padding:1px 7px; border-radius:2px; }',
    '.hphmi-l2-alarm[data-p="critical"] .chip { background:#FF4136; color:#14181C; }',
    '.hphmi-l2-alarm[data-p="high"] .chip { background:#FF851B; color:#14181C; }',
    '.hphmi-l2-alarm[data-p="warning"] .chip, .hphmi-l2-alarm[data-p="medium"] .chip { background:#FFDC00; color:#14181C; }',
    '.hphmi-l2-alarm .hint { color:var(--text-muted); font-size:10px; }',
    '.hphmi-l2-empty { color:var(--text-muted); font-size:12px; padding:14px 4px; font-family:var(--font-mono); }'
  ].join('\n');

  function vitalBandBar(v) {
    // A vital renders as a BandBar when numeric; band edges derive from
    // its status: good → centered band around current; warn/bad shift the
    // pointer out-of-band. Real limits come with the backend's threshold
    // registry — until then bands are status-faithful, not fabricated
    // numbers presented as engineering limits (Law 4: no invented basis).
    var raw = parseFloat(v.raw_value != null ? v.raw_value : v.value);
    if (isNaN(raw)) return '';
    var span = Math.max(Math.abs(raw) * 0.5, 1);
    var lo = raw - span, hi = raw + span;
    var bandLo, bandHi;
    if (v.status === 'warn') { bandLo = lo + span * 1.3; bandHi = hi; }
    else if (v.status === 'bad') { bandLo = lo + span * 1.7; bandHi = hi; }
    else { bandLo = lo + span * 0.4; bandHi = hi - span * 0.4; }
    return bandBar({
      value: raw, min: lo, max: hi, bandLo: bandLo, bandHi: bandHi,
      label: (v.label || '').toUpperCase(), unit: v.unit || '',
      caption: v.status === 'warn' || v.status === 'bad' ? 'outside normal band' : ''
    });
  }

  function renderL2(areaKey) {
    var area = null;
    for (var i = 0; i < AREAS.length; i++) if (AREAS[i].key === areaKey) area = AREAS[i];
    if (!area) return;
    injectStyles();
    var main = document.querySelector('.main-content') || document.body;

    // hide the app's own page sections while an L2 page is up
    document.querySelectorAll('section[data-page]').forEach(function (s) { s.style.display = 'none'; });
    var host = document.getElementById('hphmi-l2');
    if (!host) {
      host = document.createElement('section');
      host.id = 'hphmi-l2';
      var anySection = document.querySelector('section[data-page]');
      (anySection ? anySection.parentElement : main).appendChild(host);
    }
    host.style.display = 'block';

    var seen = {};
    var alarms = (window._aevusAlarms || []).filter(function (al) {
      if (!area.match.test(al.asset_id || '') || al.status === 'resolved') return false;
      // one row per (asset, alarm): the demo accumulator re-emits
      // instances; the display shows the condition, not the emissions.
      var k = (al.asset_id || '') + '|' + (al.alarm || al.message || '');
      if (seen[k]) return false;
      seen[k] = 1;
      return true;
    }).sort(function (p, q) {
      var rank = { critical: 0, high: 1, warning: 2, medium: 2, low: 3 };
      return (rank[p.severity] || 4) - (rank[q.severity] || 4);
    });
    var assets = (window._aevusAssets || []).filter(function (t) { return area.match.test(t.id || ''); });

    var vitalCards = assets.map(function (a) {
      var bars = (a.vitals || []).map(vitalBandBar).filter(Boolean).slice(0, 4).join('<div style="height:10px"></div>');
      if (!bars) return '';
      return '<div class="hphmi-l2-card"><div class="hphmi-l2-card-title">' + a.id +
        ' · ' + (a.name || '') + (a.health != null ? ' · ' + a.health : '') + '</div>' + bars + '</div>';
    }).filter(Boolean).join('');

    var alarmRows = alarms.map(function (al) {
      return '<div class="hphmi-l2-alarm" data-p="' + al.severity + '">' +
        '<span class="chip">' + (al.severity === 'critical' ? '■ 1' : al.severity === 'high' ? '▲ 2' : '● 3') + '</span>' +
        '<span style="font-family:var(--font-mono);color:var(--text-secondary);">' + (al.asset_id || '') + '</span>' +
        '<span style="color:var(--text-primary);">' + (al.alarm || al.message || '') + '</span>' +
        '<span class="hint">' + (al.value || '') + (al.threshold ? ' · limit ' + al.threshold : '') + '</span>' +
        '</div>';
    }).join('');

    var html =
      '<div class="hphmi-l2-head">' +
        '<div class="hphmi-l2-title">' + area.label + ' — Unit Display</div>' +
        '<span class="hphmi-l2-back" onclick="window.location.hash=\'#overview\'">← L1 Overview</span>' +
      '</div>' +
      (vitalCards ? '<div class="hphmi-l2-grid">' + vitalCards + '</div>' :
        '<div class="hphmi-l2-empty">No live vitals for this unit — connect the testbed backend for full band indicators.</div>') +
      '<div class="hphmi-l2-card"><div class="hphmi-l2-card-title">UNIT ALARMS (' + alarms.length + ')</div>' +
        '<div class="hphmi-l2-alarms">' + (alarmRows || '<div class="hphmi-l2-empty">No unresolved alarms in this unit.</div>') + '</div></div>';
    // Change-guarded (observer-cycle safe), and re-rendered from schedule()
    // so a deep link that lands before the 10s data publish fills in.
    if (host.__lastHtml !== html) {
      host.__lastHtml = html;
      host.innerHTML = html;
    }
  }

  function routeL2() {
    var m = (location.hash || '').match(/^#unit-([a-z]+)/);
    var host = document.getElementById('hphmi-l2');
    if (!m) {
      if (host && host.style.display !== 'none') {
        host.style.display = 'none';
        // restore whichever app section the hash points at
        var page = (location.hash || '#overview').replace('#', '') || 'overview';
        document.querySelectorAll('section[data-page]').forEach(function (s) {
          s.style.display = s.getAttribute('data-page') === page ? '' : s.style.display;
        });
      }
      return;
    }
    renderL2(m[1]);
  }
  window.addEventListener('hashchange', routeL2);

  // ── observer: transforms re-apply as the bundle re-renders ───────────
  var scheduled = false;
  function schedule() {
    if (scheduled) return;
    scheduled = true;
    // rAF never fires in a hidden tab — a backgrounded console would stop
    // updating (and re-open stale). Fall back to a timeout when hidden.
    var defer = document.hidden
      ? function (fn) { setTimeout(fn, 50); }
      : requestAnimationFrame.bind(window);
    defer(function () {
      scheduled = false;
      try { transformRadials(); } catch (e) { /* never break the page */ }
      try { purgeFinancials(); } catch (e) { /* never break the page */ }
      try { renderL1Strip(); } catch (e) { /* never break the page */ }
      try { routeL2(); } catch (e) { /* never break the page */ }
    });
  }

  function start() {
    injectStyles();
    schedule();
    routeL2();  // honor a #unit-* deep link on load
    new MutationObserver(schedule).observe(document.body, { childList: true, subtree: true });
    // Heartbeat: a quiet page produces no mutations, but the bundle
    // publishes state every 10s — re-run transforms on the same cadence
    // so deep-linked L2 pages fill in when data lands. All renderers are
    // change-guarded, so idle ticks are free. routeL2 runs directly (not
    // through the rAF defer) so a backgrounded or paused-render tab still
    // refreshes the unit page.
    setInterval(function () {
      schedule();
      try { routeL2(); } catch (e) { /* never break the page */ }
    }, 3000);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }

  window.AevusHPHMI = { bandBar: bandBar, transformRadials: transformRadials, renderL2: renderL2, BANDS: BANDS };
})();

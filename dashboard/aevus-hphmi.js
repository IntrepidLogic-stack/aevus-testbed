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
    el.textContent = CSS + '\n' + STRIP_CSS + '\n' + L2_CSS + '\n' + LEDGER_CSS + '\n' + WATCH_CSS + '\n' + SIT_CSS + '\n' + HANDOFF_CSS + '\n' + ESC_CSS;
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
    }).join('') + ledgerChipHtml() + escChipHtml() + '</div>';

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

  // ── P2: Suppression Ledger (Woods D1 — the invisible hand made visible)
  // The operator's hardest model is "what is the system hiding and why."
  // Shelved alarms get an ambient chip on L1 — never only a tab. Tap
  // opens the ledger with reason + age per item. Release scheduling lands
  // with the engine work; until then the ledger is honest about that too.
  var LEDGER_CSS = [
    '.hphmi-ledger-chip { display:inline-flex; align-items:center; gap:5px; font-family:var(--font-mono); font-size:11px; font-weight:700; padding:2px 8px; border-radius:2px; cursor:pointer; border:1px dashed #5A646E; color:var(--text-muted); }',
    '.hphmi-ledger-chip[data-n="0"] { display:none; }',
    '.hphmi-ledger-panel { position:fixed; right:16px; top:64px; z-index:300; width:340px; background:var(--bg-card); border:1px solid var(--border-light); border-radius:4px; padding:14px 16px; box-shadow:0 8px 32px rgba(0,0,0,0.4); }',
    '.hphmi-ledger-title { font-size:10px; letter-spacing:1.2px; color:var(--text-muted); font-weight:600; margin-bottom:10px; display:flex; justify-content:space-between; }',
    '.hphmi-ledger-row { padding:8px 0; border-bottom:1px solid var(--border); font-size:12px; }',
    '.hphmi-ledger-row:last-child { border-bottom:none; }',
    '.hphmi-ledger-row .why { color:var(--text-muted); font-size:10px; font-family:var(--font-mono); margin-top:3px; }'
  ].join('\n');

  function shelvedAlarms() {
    var seen = {};
    return (window._aevusAlarms || []).filter(function (a) {
      if (!a.shelved || a.status === 'resolved') return false;
      var k = (a.asset_id || '') + '|' + (a.alarm || a.message || '');
      if (seen[k]) return false;
      seen[k] = 1;
      return true;
    });
  }

  function fmtAge(iso) {
    if (!iso) return '';
    var m = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
    return m < 60 ? m + 'm' : (m / 60).toFixed(1) + 'h';
  }

  function ledgerChipHtml() {
    var s = shelvedAlarms();
    return '<span class="hphmi-ledger-chip" data-n="' + s.length + '" ' +
      'onclick="window.AevusHPHMI.toggleLedger()">⊘ ' + s.length +
      ' shelved</span>';
  }

  function toggleLedger() {
    var p = document.getElementById('hphmi-ledger-panel');
    if (p) { p.remove(); return; }
    var s = shelvedAlarms();
    p = document.createElement('div');
    p.id = 'hphmi-ledger-panel';
    p.className = 'hphmi-ledger-panel';
    p.innerHTML = '<div class="hphmi-ledger-title"><span>SUPPRESSION LEDGER</span>' +
      '<span style="cursor:pointer;" onclick="this.closest(\'.hphmi-ledger-panel\').remove()">✕</span></div>' +
      (s.length ? s.map(function (a) {
        return '<div class="hphmi-ledger-row">' +
          '<span style="font-family:var(--font-mono);color:var(--text-secondary);">' + (a.asset_id || '') + '</span> ' +
          '<span style="color:var(--text-primary);">' + (a.alarm || a.message || '') + '</span>' +
          '<div class="why">shelved ' + fmtAge(a.shelved_at) + ' ago · ' +
          (a.shelve_reason || 'reason not recorded') + ' · no auto-release scheduled</div></div>';
      }).join('') : '<div class="hphmi-ledger-row">Nothing shelved.</div>') +
      '<div class="why" style="margin-top:8px;color:var(--text-faint);font-size:9px;">Shelved alarms remain in the Active count. Staged release + expiry timers land with the alarm-engine phase.</div>';
    document.body.appendChild(p);
  }

  // ── P2: Watch Item — hypotheses held as falsifiable predictions ──────
  // Klein: experts hold a hypothesis as a prediction that can fail.
  // The IL9000 insight (bundle-rendered prose) becomes a card with an
  // expectancy, a disconfirming cue, and the expert verb set. Dispositions
  // persist locally — the audit seed the S3 scoreboard will read.
  var WATCH_CSS = [
    '.hphmi-watch { background:var(--bg-card); border:1px solid var(--border); border-left:3px solid #5A646E; border-radius:4px; padding:10px 14px; margin-top:10px; }',
    '.hphmi-watch-tag { font-size:9px; letter-spacing:1.2px; color:var(--text-muted); font-weight:700; }',
    '.hphmi-watch-hyp { font-size:12.5px; color:var(--text-primary); margin:4px 0; }',
    '.hphmi-watch-exp { font-size:11px; color:var(--text-secondary); font-family:var(--font-mono); }',
    '.hphmi-watch-cue { font-size:10px; color:var(--text-muted); font-family:var(--font-mono); margin-top:2px; }',
    '.hphmi-watch-verbs { display:flex; gap:8px; margin-top:8px; }',
    '.hphmi-watch-verb { font-size:10px; font-weight:600; padding:3px 10px; border-radius:2px; border:1px solid var(--border-light); color:var(--text-secondary); cursor:pointer; background:transparent; }',
    '.hphmi-watch-verb:hover { border-color:var(--accent); color:var(--accent); }',
    '.hphmi-watch[data-disposed="1"] { opacity:0.55; }',
    '.hphmi-watch-disposed { font-size:10px; color:var(--text-muted); font-family:var(--font-mono); margin-top:6px; }'
  ].join('\n');

  function watchDispositions() {
    try { return JSON.parse(localStorage.getItem('aevus_watch_dispositions') || '{}'); }
    catch (e) { return {}; }
  }

  function disposeWatch(key, verb) {
    var reason = null;
    if (verb === 'reject') {
      reason = prompt('Reject hypothesis — reason (feeds rationalization telemetry):');
      if (!reason) return;
    }
    var d = watchDispositions();
    d[key] = { verb: verb, reason: reason, at: new Date().toISOString(), role: window.aevusRole || 'operator' };
    try { localStorage.setItem('aevus_watch_dispositions', JSON.stringify(d)); } catch (e) {}
    renderWatchItem();
    if (verb === 'investigate') window.location.hash = '#unit-compress';
  }

  function currentInsight() {
    // The bundle renders the IL9000 insight beside the banner; read it as
    // the hypothesis text. (P3 replaces this with a structured feed.)
    var el = document.querySelector('#situation-banner ~ * [class*="il9000"], .ov-situation ~ *');
    // A hypothesis is a prediction with a magnitude: require a trend/
    // prediction verb AND a number-with-unit. Explainer prose ("watches
    // weather, RF...") has the verbs but not the measurement. The insight
    // may be split across child spans, so test containers (≤3 children)
    // and take the smallest match.
    var best = null;
    var all = document.querySelectorAll('div,span');
    for (var i = 0; i < all.length; i++) {
      var t = (all[i].textContent || '').trim();
      if (all[i].children.length <= 5 &&
          /trending|predicted|project/i.test(t) &&
          /[+-]?\d+(\.\d+)?\s*(°F|°C|psi|dB|%|\/hr|mph)/i.test(t) &&
          t.length > 40 && t.length < 220 &&
          (!best || t.length < best.length)) { best = t; }
    }
    return best;
  }

  function renderWatchItem() {
    var strip = document.getElementById('hphmi-l1-strip');
    if (!strip) return;
    var hyp = currentInsight();
    var host = document.getElementById('hphmi-watch');
    if (!hyp) { if (host) host.remove(); return; }
    var key = 'wi-' + hyp.slice(0, 40).replace(/\W+/g, '-');
    var disposed = watchDispositions()[key];

    if (!host) {
      host = document.createElement('div');
      host.id = 'hphmi-watch';
      strip.parentElement.insertBefore(host, strip.nextSibling);
    }
    var expMatch = hyp.match(/in\s*~?\s*(\d+\s*h)/i);
    var exp = expMatch ? 'Expect: alarm within ' + expMatch[1] + ' if trend holds.' :
      'Expect: condition progresses if attribution is correct.';
    var html = '<div class="hphmi-watch"' + (disposed ? ' data-disposed="1"' : '') + '>' +
      '<span class="hphmi-watch-tag">WATCH ITEM · IL9000 HYPOTHESIS</span>' +
      '<div class="hphmi-watch-hyp">' + hyp + '</div>' +
      '<div class="hphmi-watch-exp">' + exp + '</div>' +
      '<div class="hphmi-watch-cue">Disconfirming cue: trend rate flattens or reverses before the window closes.</div>' +
      (disposed ?
        '<div class="hphmi-watch-disposed">Disposed: ' + disposed.verb.toUpperCase() +
        (disposed.reason ? ' — ' + disposed.reason : '') + ' · ' + fmtAge(disposed.at) + ' ago</div>' :
        '<div class="hphmi-watch-verbs">' +
        '<button class="hphmi-watch-verb" onclick="window.AevusHPHMI.disposeWatch(\'' + key + '\',\'agree\')">Agree</button>' +
        '<button class="hphmi-watch-verb" onclick="window.AevusHPHMI.disposeWatch(\'' + key + '\',\'watch\')">Watch</button>' +
        '<button class="hphmi-watch-verb" onclick="window.AevusHPHMI.disposeWatch(\'' + key + '\',\'investigate\')">Investigate →</button>' +
        '<button class="hphmi-watch-verb" onclick="window.AevusHPHMI.disposeWatch(\'' + key + '\',\'reject\')">Reject…</button>' +
        '</div>') +
      '</div>';
    if (host.__lastHtml !== html) { host.__lastHtml = html; host.innerHTML = html; }
  }

  // ── P2: F9 — Declare Abnormal as a state machine (spec §7b) ──────────
  // Until now window.declareAbnormal was called but never defined: F9 was
  // theater. ASM intent: declaring abnormal reconfigures the console. The
  // situation page auto-composes — affected unit, its alarms, comms state,
  // a response checklist where every step carries an action-expectancy
  // (Klein: experts evaluate actions by simulating outcomes), and a live
  // event timeline. Closeout is gated: a note is required, and open
  // criticals demand an explicit override. Everything logs to the shift-
  // log seed (aevus_situation_log).
  var SIT_CSS = [
    '#hphmi-sit { padding:0 4px; }',
    '.hphmi-sit-head { display:flex; align-items:center; justify-content:space-between; margin:6px 0 4px; }',
    '.hphmi-sit-title { font-size:20px; font-weight:700; color:var(--text-primary); font-family:var(--font-heading); }',
    '.hphmi-sit-meta { font-size:10px; color:var(--text-muted); font-family:var(--font-mono); margin-bottom:14px; }',
    '.hphmi-sit-grid { display:grid; grid-template-columns:1fr 1fr; gap:12px; }',
    '@media (max-width:900px){ .hphmi-sit-grid { grid-template-columns:1fr; } }',
    '.hphmi-sit-card { background:var(--bg-card); border:1px solid var(--border); border-radius:4px; padding:12px 14px; }',
    '.hphmi-sit-card-title { font-size:10px; letter-spacing:1.2px; color:var(--text-muted); font-weight:600; margin-bottom:8px; }',
    '.hphmi-check { display:flex; gap:10px; padding:8px 0; border-bottom:1px solid var(--border); align-items:flex-start; }',
    '.hphmi-check:last-child { border-bottom:none; }',
    '.hphmi-check input { margin-top:2px; accent-color:#4CC3E8; }',
    '.hphmi-check .step { font-size:12.5px; color:var(--text-primary); }',
    '.hphmi-check .expect { font-size:10px; color:var(--text-muted); font-family:var(--font-mono); margin-top:2px; }',
    '.hphmi-timeline-row { font-size:11px; font-family:var(--font-mono); color:var(--text-secondary); padding:4px 0; }',
    '.hphmi-timeline-row .t { color:var(--text-faint); margin-right:8px; }',
    '.hphmi-sit-close { margin-top:14px; display:flex; gap:10px; align-items:center; }',
    '.hphmi-sit-close button { font-size:11px; font-weight:600; padding:6px 16px; border-radius:2px; border:1px solid var(--border-light); background:transparent; color:var(--text-secondary); cursor:pointer; }',
    '.hphmi-sit-close button:hover { border-color:var(--accent); color:var(--accent); }',
    '.hphmi-f9-proposed { outline:1.8px solid #FBBF24 !important; outline-offset:2px; }'
  ].join('\n');

  // Response procedures with action-expectancies (rationalization seed —
  // same guidance the alarm hints show, structured as testable steps).
  var RESPONSES = {
    'Suction Pressure High': [
      { step: 'Inspect relief valve and check for leaks', expect: 'Expect: suction pressure trends down within 15 min of correction' },
      { step: 'Verify recycle valve position locally', expect: 'Expect: valve state confirmed; remote indication matches local' }
    ],
    'Voltage Elevated': [
      { step: 'Check power supply unit and UPS battery', expect: 'Expect: voltage returns below 13.8V within 10 min' }
    ],
    'Signal Quality Degraded': [
      { step: 'Check antenna alignment and cable connections', expect: 'Expect: RSSI recovers ≥5 dB after correction; if wind-correlated, defer to Watch Item' }
    ]
  };
  var DEFAULT_RESPONSE = [
    { step: 'Verify remote indication against a local reading', expect: 'Expect: remote and local agree within tolerance — if not, treat indication as suspect' }
  ];

  function situationLog() {
    try { return JSON.parse(localStorage.getItem('aevus_situation_log') || '[]'); }
    catch (e) { return []; }
  }
  function logSituation(ev) {
    var log = situationLog();
    log.push(ev);
    try { localStorage.setItem('aevus_situation_log', JSON.stringify(log)); } catch (e) {}
  }

  var activeSituation = null;

  function worstUnresolved() {
    var alarms = (window._aevusAlarms || []).filter(function (a) { return a.status !== 'resolved'; });
    var crits = alarms.filter(function (a) { return a.severity === 'critical'; });
    return (crits[0] || alarms[0]) || null;
  }

  function areaFor(assetId) {
    for (var i = 0; i < AREAS.length; i++) if (AREAS[i].match.test(assetId || '')) return AREAS[i];
    return AREAS[1]; // default: compression
  }

  function declareAbnormal() {
    var trigger = worstUnresolved();
    var area = trigger ? areaFor(trigger.asset_id) : AREAS[1];
    activeSituation = {
      declared_at: new Date().toISOString(),
      area: area.key,
      trigger: trigger ? (trigger.asset_id + ' ' + (trigger.alarm || '')) : 'manual declaration',
      role: window.aevusRole || 'operator',
      events: [{ t: new Date().toISOString(), msg: 'ABNORMAL DECLARED — ' + area.label + (trigger ? ' · trigger: ' + trigger.asset_id + ' ' + (trigger.alarm || '') : '') }]
    };
    logSituation({ type: 'declared', at: activeSituation.declared_at, area: area.key, trigger: activeSituation.trigger, role: activeSituation.role });
    window.location.hash = '#situation';
    renderSituation();
  }

  function renderSituation() {
    if (!activeSituation) { window.location.hash = '#overview'; return; }
    document.querySelectorAll('section[data-page]').forEach(function (s) { s.style.display = 'none'; });
    var l2host = document.getElementById('hphmi-l2');
    if (l2host) l2host.style.display = 'none';
    var host = document.getElementById('hphmi-sit');
    if (!host) {
      host = document.createElement('section');
      host.id = 'hphmi-sit';
      var anySection = document.querySelector('section[data-page]');
      (anySection ? anySection.parentElement : document.body).appendChild(host);
    }
    host.style.display = 'block';

    var area = null;
    for (var i = 0; i < AREAS.length; i++) if (AREAS[i].key === activeSituation.area) area = AREAS[i];
    var seen = {};
    var alarms = (window._aevusAlarms || []).filter(function (al) {
      if (!area.match.test(al.asset_id || '') || al.status === 'resolved') return false;
      var k = (al.asset_id || '') + '|' + (al.alarm || '');
      if (seen[k]) return false; seen[k] = 1; return true;
    });
    var commsArea = AREAS[3];
    var commsAlarms = (window._aevusAlarms || []).filter(function (al) {
      return commsArea.match.test(al.asset_id || '') && al.status !== 'resolved';
    });
    var openCrits = alarms.filter(function (a) { return a.severity === 'critical'; }).length;

    var checklist = [];
    alarms.forEach(function (al) {
      (RESPONSES[al.alarm] || DEFAULT_RESPONSE).forEach(function (r) {
        checklist.push({ alarm: al.asset_id + ' ' + al.alarm, step: r.step, expect: r.expect });
      });
    });
    if (!checklist.length) checklist = DEFAULT_RESPONSE.map(function (r) { return { alarm: '', step: r.step, expect: r.expect }; });

    var html =
      '<div class="hphmi-sit-head">' +
        '<div class="hphmi-sit-title">⚑ SITUATION — ' + area.label + '</div>' +
        '<span class="hphmi-l2-back" onclick="window.location.hash=\'#overview\'">← L1 (situation stays active)</span>' +
      '</div>' +
      '<div class="hphmi-sit-meta">declared ' + fmtAge(activeSituation.declared_at) + ' ago · by ' + activeSituation.role +
        ' · trigger: ' + activeSituation.trigger + '</div>' +
      '<div class="hphmi-sit-grid">' +
        '<div class="hphmi-sit-card"><div class="hphmi-sit-card-title">UNIT ALARMS (' + alarms.length + ')</div>' +
          alarms.map(function (al) {
            return '<div class="hphmi-l2-alarm" data-p="' + al.severity + '" style="cursor:pointer;" onclick="window.location.hash=\'#asset-' + (al.asset_id || '') + '\'">' +
              '<span class="chip">' + (al.severity === 'critical' ? '■ 1' : al.severity === 'high' ? '▲ 2' : '● 3') + '</span>' +
              '<span style="font-family:var(--font-mono);color:var(--text-secondary);">' + (al.asset_id || '') + '</span>' +
              '<span style="color:var(--text-primary);">' + (al.alarm || '') + '</span>' +
              '<span class="hint">' + (al.value || '') + (al.threshold ? ' · limit ' + al.threshold : '') + '</span></div>';
          }).join('') + '</div>' +
        '<div class="hphmi-sit-card"><div class="hphmi-sit-card-title">SERVING COMM PATH</div>' +
          '<div style="font-size:12px;color:var(--text-secondary);">' +
          (commsAlarms.length ? commsAlarms.length + ' unresolved comm alarm(s) — view may be degraded; verify locally before trusting remote indication' :
            'Comm path quiet — remote indication trustworthy') + '</div>' +
          ((window._staleAssetIds || []).length ? '<div style="font-size:10px;color:#FBBF24;font-family:var(--font-mono);margin-top:6px;">STALE: ' +
            (window._staleAssetIds || []).join(', ') + '</div>' : '') + '</div>' +
      '</div>' +
      '<div class="hphmi-sit-card" style="margin-top:12px;"><div class="hphmi-sit-card-title">RESPONSE CHECKLIST — every step carries its expectancy</div>' +
        checklist.map(function (c, idx) {
          return '<div class="hphmi-check"><input type="checkbox" id="sit-chk-' + idx + '">' +
            '<div><div class="step">' + c.step + (c.alarm ? ' <span style="color:var(--text-faint);font-size:10px;">(' + c.alarm + ')</span>' : '') + '</div>' +
            '<div class="expect">' + c.expect + '</div></div></div>';
        }).join('') + '</div>' +
      '<div class="hphmi-sit-card" style="margin-top:12px;"><div class="hphmi-sit-card-title">EVENT TIMELINE</div>' +
        activeSituation.events.map(function (ev) {
          return '<div class="hphmi-timeline-row"><span class="t">' + new Date(ev.t).toLocaleTimeString() + '</span>' + ev.msg + '</div>';
        }).join('') + '</div>' +
      '<div class="hphmi-sit-close">' +
        '<button onclick="window.AevusHPHMI.closeSituation()">Close out situation…</button>' +
        (openCrits ? '<span style="font-size:10px;color:#FBBF24;font-family:var(--font-mono);">' + openCrits + ' critical still active — closeout will require override</span>' : '') +
      '</div>';

    if (host.__lastHtml !== html) { host.__lastHtml = html; host.innerHTML = html; }
  }

  function closeSituation() {
    if (!activeSituation) return;
    var area = null;
    for (var i = 0; i < AREAS.length; i++) if (AREAS[i].key === activeSituation.area) area = AREAS[i];
    var openCrits = (window._aevusAlarms || []).filter(function (al) {
      return area.match.test(al.asset_id || '') && al.status !== 'resolved' && al.severity === 'critical';
    }).length;
    if (openCrits > 0 && !confirm(openCrits + ' critical alarm(s) still unresolved in ' + area.label +
      ' — variables are NOT back in band. Override and close anyway?')) return;
    var note = prompt('Closeout note (required — one line for the shift log):');
    if (!note) return;
    logSituation({ type: 'closed', at: new Date().toISOString(), area: activeSituation.area, note: note, override: openCrits > 0, role: window.aevusRole || 'operator' });
    activeSituation = null;
    var host = document.getElementById('hphmi-sit');
    if (host) { host.style.display = 'none'; host.__lastHtml = null; }
    window.location.hash = '#overview';
  }

  function decorateF9() {
    // System-proposed, operator-confirmed (Klein pre-mortem #3): when an
    // unresolved critical exists and no situation is active, the Declare
    // button visibly proposes itself — confirming beats confessing.
    var btns = document.querySelectorAll('button,[role="button"],div[onclick]');
    for (var i = 0; i < btns.length; i++) {
      if (/Declare Abnormal/.test(btns[i].textContent || '')) {
        var propose = !activeSituation && (window._aevusAlarms || []).some(function (a) {
          return a.severity === 'critical' && a.status !== 'resolved';
        });
        btns[i].classList.toggle('hphmi-f9-proposed', propose);
        btns[i].title = propose ? 'Entry criteria met — system proposes declaring abnormal (F9)' : '';
        break;
      }
    }
  }

  window.declareAbnormal = declareAbnormal;

  // ── P2: Standing-alarm escalation (spec §7f) ─────────────────────────
  // Acked ≠ resolved. Each priority has a designed response time from
  // rationalization defaults; an unresolved alarm past 2× re-annunciates
  // (standing chip on L1, aged styling), past 3× earns a supervisor-notify
  // mark in the log. Ack never permanently silences.
  var RESPONSE_MIN = { critical: 15, high: 30, warning: 60, medium: 60, low: 240 };

  function standingAlarms() {
    var now = Date.now(), out = [], seen = {};
    (window._aevusAlarms || []).forEach(function (a) {
      if (a.status === 'resolved' || a.shelved) return;
      var k = (a.asset_id || '') + '|' + (a.alarm || '');
      if (seen[k]) return; seen[k] = 1;
      var ageMin = (now - new Date(a.timestamp || now).getTime()) / 60000;
      var designed = RESPONSE_MIN[a.severity] || 60;
      if (ageMin > 2 * designed) {
        out.push({ alarm: a, ageMin: ageMin, designed: designed, supervisor: ageMin > 3 * designed });
      }
    });
    return out.sort(function (p, q) { return q.ageMin - p.ageMin; });
  }

  var _supervisorNotified = {};
  function escalateStanding() {
    var st = standingAlarms();
    st.forEach(function (s) {
      var k = (s.alarm.asset_id || '') + '|' + (s.alarm.alarm || '');
      if (s.supervisor && !_supervisorNotified[k]) {
        _supervisorNotified[k] = true;
        logSituation({
          type: 'supervisor_notify', at: new Date().toISOString(),
          alarm: k, age_min: Math.round(s.ageMin),
          designed_min: s.designed,
          msg: 'Standing ' + s.alarm.severity + ' at 3× designed response time'
        });
      }
    });
    // ambient standing chip beside the ledger chip
    var strip = document.querySelector('.hphmi-alarmstrip');
    if (!strip) return;
    var chip = document.getElementById('hphmi-standing-chip');
    if (!st.length) { if (chip) chip.remove(); return; }
    var oldest = st[0];
    var label = '⏱ ' + st.length + ' standing · oldest ' + fmtAge(oldest.alarm.timestamp);
    if (!chip) {
      chip = document.createElement('span');
      chip.id = 'hphmi-standing-chip';
      chip.className = 'hphmi-ledger-chip';
      chip.style.borderStyle = 'solid';
      chip.style.color = '#FBBF24';
      chip.style.borderColor = '#FBBF24';
      chip.onclick = function () { window.location.hash = '#alarms'; };
      strip.appendChild(chip);
    }
    chip.setAttribute('data-n', st.length);
    chip.title = 'Unresolved past 2× designed response time — ack never permanently silences';
    if (chip.textContent !== label) chip.textContent = label;
  }

  // ── P2: Shift handover artifact (spec §7e — expectancies first) ──────
  // Klein: the load-bearing content of a handover is expectancies, not
  // inventories. Order: what to expect next shift (open Watch Items with
  // per-item re-adoption), then standing alarms, shelved, stale points,
  // situation history. Dual sign-off persists; un-countersigned handover
  // is visible state, not a formality.
  var HANDOFF_CSS = [
    '#hphmi-handover { padding:0 4px; }',
    '.hphmi-ho-sec { background:var(--bg-card); border:1px solid var(--border); border-radius:4px; padding:12px 14px; margin-bottom:12px; }',
    '.hphmi-ho-sec-title { font-size:10px; letter-spacing:1.2px; color:var(--text-muted); font-weight:600; margin-bottom:8px; }',
    '.hphmi-ho-row { padding:7px 0; border-bottom:1px solid var(--border); font-size:12px; color:var(--text-secondary); }',
    '.hphmi-ho-row:last-child { border-bottom:none; }',
    '.hphmi-ho-row .mono { font-family:var(--font-mono); font-size:10px; color:var(--text-muted); }',
    '.hphmi-ho-sign { display:flex; gap:10px; align-items:center; margin-top:4px; }',
    '.hphmi-ho-sign button { font-size:11px; font-weight:600; padding:6px 16px; border-radius:2px; border:1px solid var(--border-light); background:transparent; color:var(--text-secondary); cursor:pointer; }',
    '.hphmi-ho-sign button:hover { border-color:var(--accent); color:var(--accent); }',
    '.hphmi-ho-signed { font-size:10px; font-family:var(--font-mono); color:#8FBF9F; }'
  ].join('\n');

  function handoverState() {
    try { return JSON.parse(localStorage.getItem('aevus_handover_current') || '{}'); }
    catch (e) { return {}; }
  }
  function setHandoverState(s) {
    try { localStorage.setItem('aevus_handover_current', JSON.stringify(s)); } catch (e) {}
  }

  function signHandover(which) {
    var name = prompt(which === 'out' ? 'Outgoing operator — sign handover (name):' : 'Incoming operator — countersign (name):');
    if (!name) return;
    var s = handoverState();
    s[which] = { name: name, at: new Date().toISOString() };
    if (which === 'in' && s.out) {
      // archive the completed handover
      var log = [];
      try { log = JSON.parse(localStorage.getItem('aevus_handover_log') || '[]'); } catch (e) {}
      log.push({ out: s.out, in: s.in, archived_at: new Date().toISOString() });
      try { localStorage.setItem('aevus_handover_log', JSON.stringify(log)); } catch (e) {}
      setHandoverState({});
      alert('Handover archived. New shift owns the board.');
      window.location.hash = '#overview';
      return;
    }
    setHandoverState(s);
    renderHandover();
  }

  function renderHandover() {
    document.querySelectorAll('section[data-page]').forEach(function (s) { s.style.display = 'none'; });
    ['hphmi-l2', 'hphmi-sit'].forEach(function (id) {
      var el = document.getElementById(id); if (el) el.style.display = 'none';
    });
    var host = document.getElementById('hphmi-handover');
    if (!host) {
      host = document.createElement('section');
      host.id = 'hphmi-handover';
      var anySection = document.querySelector('section[data-page]');
      (anySection ? anySection.parentElement : document.body).appendChild(host);
    }
    host.style.display = 'block';

    var hyp = currentInsight();
    var dispositions = watchDispositions();
    var st = standingAlarms();
    var shelved = shelvedAlarms();
    var stale = window._staleAssetIds || [];
    var sitLog = situationLog().slice(-6).reverse();
    var signed = handoverState();

    var expectRows = '';
    if (hyp) {
      var key = 'wi-' + hyp.slice(0, 40).replace(/\W+/g, '-');
      var d = dispositions[key];
      expectRows += '<div class="hphmi-ho-row">' + hyp +
        '<div class="mono">' + (d ? 'disposed: ' + d.verb.toUpperCase() + (d.reason ? ' — ' + d.reason : '') : 'OPEN — incoming shift must re-adopt or close') + '</div>' +
        (!d || d.verb === 'watch' || d.verb === 'agree' ?
          '<div class="hphmi-watch-verbs" style="margin-top:6px;">' +
          '<button class="hphmi-watch-verb" onclick="window.AevusHPHMI.disposeWatch(\'' + key + '\',\'agree\')">Re-adopt</button>' +
          '<button class="hphmi-watch-verb" onclick="window.AevusHPHMI.disposeWatch(\'' + key + '\',\'reject\')">Close…</button></div>' : '') +
        '</div>';
    }
    var trendNote = '';
    Object.keys(HIST).forEach(function (id) {
      var h = HIST[id];
      if (h.length >= 4 && h[h.length - 1].v - h[0].v < -0.5) {
        trendNote += '<div class="hphmi-ho-row">' + id + ' health declining (' + h[0].v + ' → ' + h[h.length - 1].v + ')' +
          '<div class="mono">expect continued decline unless intervened</div></div>';
      }
    });

    var html =
      '<div class="hphmi-sit-head">' +
        '<div class="hphmi-sit-title">SHIFT HANDOVER</div>' +
        '<span class="hphmi-l2-back" onclick="window.location.hash=\'#overview\'">← L1</span></div>' +
      '<div class="hphmi-sit-meta">compiled ' + new Date().toLocaleTimeString() + ' · expectancies first, inventories after</div>' +
      '<div class="hphmi-ho-sec"><div class="hphmi-ho-sec-title">WHAT TO EXPECT NEXT SHIFT</div>' +
        (expectRows || trendNote || '<div class="hphmi-ho-row">No open hypotheses or declining trends — quiet board expected.</div>') +
        (expectRows && trendNote ? trendNote : '') + '</div>' +
      '<div class="hphmi-ho-sec"><div class="hphmi-ho-sec-title">STANDING ALARMS (' + st.length + ') — unresolved past 2× designed response</div>' +
        (st.map(function (s) {
          return '<div class="hphmi-ho-row">' + (s.alarm.asset_id || '') + ' ' + (s.alarm.alarm || '') +
            '<div class="mono">standing ' + fmtAge(s.alarm.timestamp) + ' · designed response ' + s.designed + 'm' +
            (s.supervisor ? ' · SUPERVISOR NOTIFIED (3×)' : '') + '</div></div>';
        }).join('') || '<div class="hphmi-ho-row">None.</div>') + '</div>' +
      '<div class="hphmi-ho-sec"><div class="hphmi-ho-sec-title">SHELVED (' + shelved.length + ')</div>' +
        (shelved.map(function (a) {
          return '<div class="hphmi-ho-row">' + (a.asset_id || '') + ' ' + (a.alarm || '') +
            '<div class="mono">shelved ' + fmtAge(a.shelved_at) + ' ago · ' + (a.shelve_reason || 'reason not recorded') + '</div></div>';
        }).join('') || '<div class="hphmi-ho-row">Nothing shelved.</div>') + '</div>' +
      '<div class="hphmi-ho-sec"><div class="hphmi-ho-sec-title">STALE / UNVERIFIED POINTS</div>' +
        (stale.length ? '<div class="hphmi-ho-row">' + stale.join(', ') + '<div class="mono">values from these sources unconfirmed</div></div>' :
          '<div class="hphmi-ho-row">All points verified.</div>') + '</div>' +
      '<div class="hphmi-ho-sec"><div class="hphmi-ho-sec-title">SITUATION / ESCALATION LOG (recent)</div>' +
        (sitLog.map(function (ev) {
          return '<div class="hphmi-ho-row"><span class="mono">' + new Date(ev.at).toLocaleTimeString() + '</span> ' +
            ev.type.toUpperCase() + (ev.area ? ' · ' + ev.area : '') + (ev.alarm ? ' · ' + ev.alarm : '') +
            (ev.note ? ' · "' + ev.note + '"' : '') + (ev.override ? ' · OVERRIDE' : '') + '</div>';
        }).join('') || '<div class="hphmi-ho-row">No declarations this shift.</div>') + '</div>' +
      '<div class="hphmi-ho-sec"><div class="hphmi-ho-sec-title">SIGN-OFF — dual acknowledgment</div>' +
        '<div class="hphmi-ho-sign">' +
        (signed.out ? '<span class="hphmi-ho-signed">Outgoing: ' + signed.out.name + ' · ' + new Date(signed.out.at).toLocaleTimeString() + '</span>' :
          '<button onclick="window.AevusHPHMI.signHandover(\'out\')">Outgoing sign…</button>') +
        (signed.out ? (signed.in ? '' : '<button onclick="window.AevusHPHMI.signHandover(\'in\')">Incoming countersign…</button>') :
          '<span class="mono" style="font-size:10px;">incoming countersigns after outgoing signs</span>') +
        '</div></div>';

    if (host.__lastHtml !== html) { host.__lastHtml = html; host.innerHTML = html; }
  }

  window._shiftHandover = function () {
    window.location.hash = '#handover';
    renderHandover();
  };

  // ── P3: Capture-and-escalate (spec §7d — context must travel) ────────
  // One tap freezes the operating picture: comm/alarm/stale/vitals state
  // plus the trend history, with the operator's mandatory one-line "what
  // made me suspicious" (Klein: the expectancy violation is the packet's
  // highest-value, least-recoverable cue). Escalation is cheap and
  // shame-free; packets persist locally, surface in handover, and export
  // as JSON for the analyst handoff.
  var ESC_CSS = [
    '.hphmi-esc-chip { display:inline-flex; align-items:center; gap:5px; font-family:var(--font-mono); font-size:11px; font-weight:700; padding:2px 8px; border-radius:2px; cursor:pointer; border:1px solid #B48EAD; color:#B48EAD; }',
    '.hphmi-esc-row { padding:7px 0; border-bottom:1px solid var(--border); font-size:12px; color:var(--text-secondary); }',
    '.hphmi-esc-row:last-child { border-bottom:none; }',
    '.hphmi-esc-row .mono { font-family:var(--font-mono); font-size:10px; color:var(--text-muted); }'
  ].join('\n');

  function escalations() {
    try { return JSON.parse(localStorage.getItem('aevus_escalations') || '[]'); }
    catch (e) { return []; }
  }

  function captureAndEscalate() {
    var why = prompt('Capture & escalate — what made you suspicious? (required; travels with the packet)');
    if (!why) return;
    var assets = (window._aevusAssets || []).map(function (a) {
      return { id: a.id, status: a.status, health: a.health, last_seen: a.last_seen,
        vitals: (a.vitals || []).map(function (v) { return { label: v.label, value: v.value, status: v.status }; }) };
    });
    var seen = {};
    var alarms = (window._aevusAlarms || []).filter(function (al) {
      var k = (al.asset_id || '') + '|' + (al.alarm || '');
      if (seen[k] || al.status === 'resolved') return false; seen[k] = 1; return true;
    }).map(function (al) {
      return { asset: al.asset_id, alarm: al.alarm, severity: al.severity, status: al.status, value: al.value, since: al.timestamp };
    });
    var packet = {
      id: 'ESC-' + Date.now().toString(36).toUpperCase(),
      at: new Date().toISOString(),
      by: window.aevusRole || 'operator',
      why: why,
      view: location.hash || '#overview',
      stale: window._staleAssetIds || [],
      alarms: alarms,
      assets: assets,
      trend_history: HIST
    };
    var list = escalations();
    list.push(packet);
    try { localStorage.setItem('aevus_escalations', JSON.stringify(list)); } catch (e) {}
    logSituation({ type: 'escalation', at: packet.at, id: packet.id, why: why, role: packet.by });
    // immediate evidence export for the analyst handoff
    try {
      var blob = new Blob([JSON.stringify(packet, null, 2)], { type: 'application/json' });
      var a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = 'aevus_' + packet.id + '.json';
      a.click();
      URL.revokeObjectURL(a.href);
    } catch (e) {}
    alert('Escalation ' + packet.id + ' captured — packet downloaded and queued for handover. Verify locally before trusting remote indication on the affected assets.');
  }

  function escChipHtml() {
    var n = escalations().length;
    return '<span class="hphmi-esc-chip" onclick="window.AevusHPHMI.captureAndEscalate()" ' +
      'title="Capture the current operating picture and escalate — cheap and reversible">⚑ escalate' +
      (n ? ' · ' + n : '') + '</span>';
  }

  // ── P3: Asset entity pages (#asset-<ID> — spec §10 S2) ───────────────
  // Every asset becomes a navigable object: vitals as BandBars, every
  // unresolved alarm referencing it, watch dispositions, situation-log
  // and escalation mentions. Monitoring becomes investigation.
  function renderEntity(assetId) {
    document.querySelectorAll('section[data-page]').forEach(function (s) { s.style.display = 'none'; });
    ['hphmi-l2', 'hphmi-sit', 'hphmi-handover'].forEach(function (id) {
      var el = document.getElementById(id); if (el) el.style.display = 'none';
    });
    var host = document.getElementById('hphmi-entity');
    if (!host) {
      host = document.createElement('section');
      host.id = 'hphmi-entity';
      var anySection = document.querySelector('section[data-page]');
      (anySection ? anySection.parentElement : document.body).appendChild(host);
    }
    host.style.display = 'block';

    var asset = (window._aevusAssets || []).find(function (a) {
      return (a.id || '').toUpperCase() === assetId.toUpperCase();
    });
    var seen = {};
    var alarms = (window._aevusAlarms || []).filter(function (al) {
      if ((al.asset_id || '').toUpperCase() !== assetId.toUpperCase() || al.status === 'resolved') return false;
      var k = al.alarm || al.message || '';
      if (seen[k]) return false; seen[k] = 1; return true;
    });
    var sitMentions = situationLog().filter(function (ev) {
      return JSON.stringify(ev).toUpperCase().indexOf(assetId.toUpperCase()) >= 0;
    }).slice(-5).reverse();
    var escMentions = escalations().filter(function (p) {
      return JSON.stringify(p.alarms).toUpperCase().indexOf(assetId.toUpperCase()) >= 0 ||
             (p.stale || []).join(',').toUpperCase().indexOf(assetId.toUpperCase()) >= 0;
    });
    var stale = (window._staleAssetIds || []).indexOf(assetId) >= 0;

    var bars = asset ? (asset.vitals || []).map(vitalBandBar).filter(Boolean).join('<div style="height:10px"></div>') : '';

    var html =
      '<div class="hphmi-sit-head">' +
        '<div class="hphmi-sit-title">' + assetId + (asset && asset.name ? ' — ' + asset.name : '') + '</div>' +
        '<span class="hphmi-l2-back" onclick="history.back()">← back</span></div>' +
      '<div class="hphmi-sit-meta">' +
        (asset ? ('status ' + (asset.status || '—') + (asset.health != null ? ' · health ' + asset.health : '') +
          ' · last seen ' + (asset.last_seen ? fmtAge(asset.last_seen) + ' ago' : '—')) : 'no live record — historical references only') +
        (stale ? ' · <span style="color:#FBBF24;">STALE — values unconfirmed</span>' : '') + '</div>' +
      '<div class="hphmi-sit-grid">' +
        '<div class="hphmi-sit-card"><div class="hphmi-sit-card-title">LIVE VITALS</div>' +
          (bars || '<div class="hphmi-l2-empty">No live vitals.</div>') + '</div>' +
        '<div class="hphmi-sit-card"><div class="hphmi-sit-card-title">UNRESOLVED ALARMS (' + alarms.length + ')</div>' +
          (alarms.map(function (al) {
            return '<div class="hphmi-l2-alarm" data-p="' + al.severity + '" style="cursor:pointer;" onclick="window.location.hash=\'#asset-' + (al.asset_id || '') + '\'">' +
              '<span class="chip">' + (al.severity === 'critical' ? '■ 1' : al.severity === 'high' ? '▲ 2' : '● 3') + '</span>' +
              '<span style="color:var(--text-primary);">' + (al.alarm || '') + '</span>' +
              '<span class="hint">' + (al.value || '') + (al.threshold ? ' · limit ' + al.threshold : '') + '</span></div>';
          }).join('') || '<div class="hphmi-l2-empty">None.</div>') + '</div>' +
      '</div>' +
      '<div class="hphmi-sit-card" style="margin-top:12px;"><div class="hphmi-sit-card-title">EVENT REFERENCES — situations & escalations naming this asset</div>' +
        (sitMentions.map(function (ev) {
          return '<div class="hphmi-esc-row"><span class="mono">' + new Date(ev.at).toLocaleString() + '</span> ' +
            ev.type.toUpperCase() + (ev.note ? ' · "' + ev.note + '"' : '') + (ev.why ? ' · "' + ev.why + '"' : '') + '</div>';
        }).join('') +
        escMentions.map(function (p) {
          return '<div class="hphmi-esc-row"><span class="mono">' + new Date(p.at).toLocaleString() + '</span> ESCALATION ' +
            p.id + ' · "' + p.why + '"</div>';
        }).join('') || '<div class="hphmi-l2-empty">No recorded events reference this asset.</div>') + '</div>';

    if (host.__lastHtml !== html) { host.__lastHtml = html; host.innerHTML = html; }
  }

  function routeEntity() {
    var m = (location.hash || '').match(/^#asset-([A-Za-z0-9-]+)/);
    var host = document.getElementById('hphmi-entity');
    if (!m) { if (host) host.style.display = 'none'; return; }
    renderEntity(m[1]);
  }
  window.addEventListener('hashchange', routeEntity);

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
      return '<div class="hphmi-l2-alarm" data-p="' + al.severity + '" style="cursor:pointer;" onclick="window.location.hash=\'#asset-' + (al.asset_id || '') + '\'">' +
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
      try { renderWatchItem(); } catch (e) { /* never break the page */ }
      try { if (location.hash === '#situation' && activeSituation) renderSituation(); } catch (e) { /* never break the page */ }
      try { decorateF9(); } catch (e) { /* never break the page */ }
      try { escalateStanding(); } catch (e) { /* never break the page */ }
      try { if (location.hash === '#handover') renderHandover(); } catch (e) { /* never break the page */ }
      try { routeEntity(); } catch (e) { /* never break the page */ }
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

  window.AevusHPHMI = { bandBar: bandBar, transformRadials: transformRadials, renderL2: renderL2, toggleLedger: toggleLedger, disposeWatch: disposeWatch, closeSituation: closeSituation, declareAbnormal: declareAbnormal, signHandover: signHandover, captureAndEscalate: captureAndEscalate, renderEntity: renderEntity, BANDS: BANDS };
})();

/**
 * Aevus Radio Hover — live data overlay
 * ─────────────────────────────────────────────────────────────────────
 * The existing rfHover() in api-client.js (minified bundle) shows a tooltip
 * with HARDCODED values for RAD-01/RAD-02: firmware "v4.2.1-b38", uptime
 * "47d 12h", channel "902.5 MHz", modulation "OFDM 64-QAM", "AES-256 ✓",
 * last reboot "Mar 29, 2026". Only IP came from the live asset feed.
 *
 * Since the Trio JR900s are now polled real over SNMP (Task #131/#138),
 * we have real firmware, uptime, vitals, and active alarms available at:
 *   GET /api/v1/assets        → real Trio MIB fields per radio
 *   GET /api/v1/alerts        → active + chattering meta-alarms per asset
 *
 * This overlay wraps rfHover() AFTER the minified bundle has run, polls
 * those endpoints every 30s, caches the latest, and rewrites the tooltip
 * innerHTML for RAD-01/RAD-02 only. Tooltip classes (.tt-title, .tt-row,
 * .tt-label, .tt-val) are preserved so styling is unchanged. All other
 * assets (RTU, EFM, RF-LINK, switches) flow through the original rfHover
 * unchanged.
 *
 * REVERSAL: remove the <script src="rad-hover-live.js"></script> tag
 * from Aevus_Console.html. Nothing else changes.
 *
 * Companion to: rf-live-bridge.js (MQTT inline-card updater for the main
 * dashboard fields rf-r1-rssi, rf-r1-qual, etc.).
 */
(function () {
  'use strict';

  if (window.__AEVUS_RAD_HOVER_LIVE__) {
    console.log('[Aevus Rad Hover] Already running');
    return;
  }
  window.__AEVUS_RAD_HOVER_LIVE__ = true;

  // ── Config ──────────────────────────────────────────────────────────
  // Production dashboard (aevus.intrepidlogic.io) has a Pi-poll bridge
  // sidecar proxying /api/v1/* to the Pi backend (Task #94). Same-origin
  // by default; override with window.AEVUS_API_BASE if needed.
  var API_BASE = (window.AEVUS_API_BASE || '') + '/api/v1';
  var POLL_MS = 30000;
  var TARGETS = ['RAD-01', 'RAD-02'];

  // ── State ───────────────────────────────────────────────────────────
  var assetCache = {};   // { 'RAD-01': Asset, 'RAD-02': Asset }
  var alertCache = {};   // { 'RAD-01': [Alert,...], 'RAD-02': [...] }
  var chatterCache = {}; // { 'RAD-01': true/false } — ISA-18.2 meta-alarm

  // ── Utilities ───────────────────────────────────────────────────────
  // Local setText: was relying on api-client.js's global, which isn't
  // guaranteed to exist when this overlay runs (race + scope). Defining it
  // here makes the overlay self-contained.
  function setText(id, v) {
    var el = document.getElementById(id);
    if (el) el.textContent = v;
  }

  function esc(s) {
    if (s == null) return '—';
    return String(s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function vital(asset, label) {
    if (!asset || !asset.vitals) return null;
    for (var i = 0; i < asset.vitals.length; i++) {
      if (asset.vitals[i].label === label) return asset.vitals[i];
    }
    return null;
  }

  function freshnessBadge(asset) {
    if (!asset || !asset.last_seen) return '<span style="color:#7B8499;">—</span>';
    var age = (Date.now() - new Date(asset.last_seen).getTime()) / 1000;
    var color = age < 90 ? '#10D478' : age < 300 ? '#FBBF24' : '#EF4444';
    var label = age < 60 ? Math.round(age) + 's ago'
              : age < 3600 ? Math.round(age / 60) + 'm ago'
              : Math.round(age / 3600) + 'h ago';
    return '<span style="color:' + color + ';">● ' + label + '</span>';
  }

  function vitalRow(asset, label, displayLabel, statusColors) {
    var v = vital(asset, label);
    if (!v) return '';
    var color = '';
    if (statusColors && v.status === 'good') color = 'color:#10D478;';
    else if (statusColors && v.status === 'warn') color = 'color:#FBBF24;';
    else if (statusColors && v.status === 'bad') color = 'color:#EF4444;';
    return '<div class="tt-row"><span class="tt-label">' + esc(displayLabel) +
           '</span><span class="tt-val" style="' + color + '">' + esc(v.value) + '</span></div>';
  }

  // ── Build the radio tooltip body ────────────────────────────────────
  function buildRadioTooltip(assetId) {
    var a = assetCache[assetId];
    var alerts = alertCache[assetId] || [];
    var chattering = chatterCache[assetId];

    // Prefer the live ROLE vital (Trio MIB radio-type: MASTER/SLAVE) when the
    // radio is answering SNMP; fall back to the known wiring (RAD-01=master).
    var roleWord = assetId === 'RAD-01' ? 'MASTER' : 'SLAVE';
    var role = roleWord;
    if (a) {
      var rv = vital(a, 'ROLE');
      if (rv && rv.value && rv.value !== '—') roleWord = rv.value;
      role = a.vendor + ' ' + a.model + ' — ' + roleWord;
    }

    var html = '<div class="tt-title">' + esc(assetId);
    if (a && a.status) {
      var sColor = a.status === 'good' ? '#10D478'
                 : a.status === 'warn' ? '#FBBF24'
                 : a.status === 'bad'  ? '#EF4444'
                 : '#A78BFA';
      html += ' <span style="color:' + sColor + ';font-size:10px;">● ' + esc(a.status.toUpperCase()) + '</span>';
    }
    html += '</div>';

    if (!a) {
      html += '<div class="tt-row" style="color:#FBBF24;">Live data loading… (no cached asset)</div>';
      html += '<div style="margin-top:6px;font-size:9px;color:#7B8499;">Click for diagnostics</div>';
      return html;
    }

    // ── Identification (real, from SNMP) ─────────────────────────────
    html += '<div class="tt-row"><span class="tt-label">Role</span><span class="tt-val">' + esc(role) + '</span></div>';
    html += '<div class="tt-row"><span class="tt-label">Firmware</span><span class="tt-val">' + esc(a.firmware || '—') + '</span></div>';
    html += '<div class="tt-row"><span class="tt-label">IP Address</span><span class="tt-val">' + esc(a.ip_address || '—') + '</span></div>';
    html += '<div class="tt-row"><span class="tt-label">Health</span><span class="tt-val">' +
            (a.health != null ? esc(a.health) + ' / 100' : '—') + '</span></div>';
    html += '<div class="tt-row"><span class="tt-label">Last Poll</span><span class="tt-val">' + freshnessBadge(a) + '</span></div>';

    // ── Live vitals (real, from Trio MIB) ────────────────────────────
    html += '<div style="margin-top:6px;border-top:1px solid #2A3550;padding-top:4px;font-size:9px;color:#7B8499;">RF VITALS</div>';
    html += vitalRow(a, 'RSSI', 'RSSI', true);
    html += vitalRow(a, 'SIGNAL QUALITY', 'Signal Qual', true);
    html += vitalRow(a, 'TX POWER', 'Tx Power', false);
    html += vitalRow(a, 'LINK STATE', 'Link', true);
    html += vitalRow(a, 'LATENCY', 'Heartbeat', true);
    html += vitalRow(a, 'TEMPERATURE', 'Temp', true);
    html += vitalRow(a, 'VOLTAGE', 'Voltage', true);

    // ── Active alarms (filtered to this asset) ───────────────────────
    var unresolved = alerts.filter(function (al) {
      return al.status !== 'resolved';
    });
    html += '<div style="margin-top:6px;border-top:1px solid #2A3550;padding-top:4px;font-size:9px;color:#7B8499;">LIVE ALARMS</div>';

    if (chattering) {
      html += '<div class="tt-row" style="background:#3a2424;padding:2px 4px;border-radius:2px;">' +
              '<span class="tt-label" style="color:#EF4444;font-weight:700;">⚠ CHATTERING</span>' +
              '<span class="tt-val" style="color:#EF4444;">ISA-18.2 §7</span></div>';
    }
    if (unresolved.length === 0 && !chattering) {
      html += '<div class="tt-row" style="color:#10D478;"><span class="tt-label">No active alarms</span><span class="tt-val">✓</span></div>';
    } else {
      // Show up to 4 most-recent unresolved
      unresolved.slice(0, 4).forEach(function (al) {
        var sevColor = al.severity === 'critical' ? '#EF4444'
                     : al.severity === 'warning'  ? '#FBBF24'
                     : '#60A5FA';
        html += '<div class="tt-row"><span class="tt-label" style="color:' + sevColor +
                ';">' + esc(al.severity.toUpperCase()) + '</span>' +
                '<span class="tt-val" style="font-size:10px;">' + esc(al.message.slice(0, 42)) + '</span></div>';
      });
      if (unresolved.length > 4) {
        html += '<div class="tt-row" style="color:#7B8499;font-size:9px;"><span class="tt-label">+' +
                (unresolved.length - 4) + ' more</span><span class="tt-val">→ click to view</span></div>';
      }
    }

    html += '<div style="margin-top:6px;font-size:9px;color:#7B8499;">Click for full diagnostics · live every ' +
            (POLL_MS / 1000) + 's</div>';
    return html;
  }

  // ── Central link-quality card (between the two towers) ───────────────
  // Honest sourcing: PACKETS + ERRORS are real sums across both radios.
  // LINK QUALITY / status derived from RSSI + link-state. LATENCY + UPTIME
  // have no real radio source, so we show "—" rather than fake numbers.
  function rawVital(asset, label) {
    var v = vital(asset, label);
    return v && typeof v.raw_value === 'number' ? v.raw_value : 0;
  }

  function fmtCount(n) {
    return n >= 1000000 ? (n / 1000000).toFixed(1) + 'M'
         : n >= 1000 ? Math.round(n / 1000) + 'K'
         : String(Math.round(n));
  }

  function updateLinkCard() {
    var r1 = assetCache['RAD-01'];
    var r2 = assetCache['RAD-02'];
    if (!r1 && !r2) return;

    // PACKETS = TX + RX across both radios
    var pkts = 0, errs = 0;
    [r1, r2].forEach(function (a) {
      if (!a) return;
      pkts += rawVital(a, 'TX PACKETS') + rawVital(a, 'RX PACKETS');
      errs += rawVital(a, 'TX ERRORS') + rawVital(a, 'RX ERRORS') + rawVital(a, 'RX DROPPED');
    });
    setText('rf-total-pkts', fmtCount(pkts));
    var errEl = document.getElementById('rf-total-err');
    if (errEl) {
      errEl.textContent = fmtCount(errs);
      errEl.setAttribute('fill', errs > 0 ? '#FBBF24' : '#10D478');
    }

    // LATENCY — real ICMP heartbeat RTT from the edge collector ("LATENCY"
    // vital, source=icmp). A link is as slow as its worse end, so show the
    // max of the two. "—" until a heartbeat lands (no fake number).
    var lat1 = vital(r1, 'LATENCY');
    var lat2 = vital(r2, 'LATENCY');
    var latVal = null;
    if (lat1 && lat2) latVal = Math.max(lat1.raw_value, lat2.raw_value);
    else if (lat1) latVal = lat1.raw_value;
    else if (lat2) latVal = lat2.raw_value;
    setText('rf-latency', latVal == null ? '—' : Math.round(latVal) + ' ms');

    // UPTIME — real 24h reachability rollup from the backend ("UPTIME 24H"
    // vital). Link uptime = the worse of the two endpoints (a link is only as
    // available as its weakest end). "—" until samples exist (no fake 100%).
    var up1 = rawVital(r1, 'UPTIME 24H');
    var up2 = rawVital(r2, 'UPTIME 24H');
    var have1 = vital(r1, 'UPTIME 24H') != null;
    var have2 = vital(r2, 'UPTIME 24H') != null;
    var linkUptime = null;
    if (have1 && have2) linkUptime = Math.min(up1, up2);
    else if (have1) linkUptime = up1;
    else if (have2) linkUptime = up2;
    setText('rf-uptime', linkUptime == null ? '—' : linkUptime.toFixed(1) + '%');

    // Fix the hardcoded fake IPs in the per-radio summary cards
    // (rf-r1-ip / rf-r2-ip ship as 10.0.1.11 / 10.0.1.12 — never wired).
    if (r1 && r1.ip_address) setText('rf-r1-ip', r1.ip_address);
    if (r2 && r2.ip_address) setText('rf-r2-ip', r2.ip_address);

    // Phase 2 secondary callout (Task #160): per-radio FW/ROLE/STATE +
    // per-direction error split. Inline because the data is here and the
    // callout structure mirrors rf-r1-* / rf-r2-* element naming.
    [['r1', r1], ['r2', r2]].forEach(function (pair) {
      var key = pair[0], asset = pair[1];
      if (!asset) return;
      // Firmware — collected via Trio MIB OID .5.0 → Asset.firmware.
      // Truncate aggressively: Trio reports "3.8.4 Build 4104" which is
      // 16 chars, way wider than the ~10-char SVG column. Show the major
      // version only ("3.8.4") so it doesn't overlap the ROLE column.
      var fwRaw = asset.firmware || '—';
      var fwShort = fwRaw.split(/[\s\n]/)[0].slice(0, 10);
      setText('rf-' + key + '-fw', fwShort);
      // ROLE — MASTER (AP) vs SLAVE (Remote)
      var roleVital = vital(asset, 'ROLE');
      setText('rf-' + key + '-role', (roleVital && roleVital.value) || (key === 'r1' ? 'MASTER' : 'SLAVE'));
      // LINK STATE — normalizer now correctly returns "LINKED" for ACTIVE
      // radios (Task #155). Color by status (good=green, bad=red).
      var stateVital = vital(asset, 'LINK STATE');
      var stateEl = document.getElementById('rf-' + key + '-state');
      if (stateEl && stateVital) {
        stateEl.textContent = stateVital.value || '—';
        stateEl.setAttribute('fill',
          stateVital.status === 'good' ? '#10D478' :
          stateVital.status === 'bad'  ? '#EF4444' : '#FBBF24');
      }
      // Per-direction error split (RF engineer perspective from design doc)
      function setErr(slot, label) {
        var v = rawVital(asset, label);
        var el = document.getElementById('rf-' + key + '-' + slot);
        if (!el) return;
        el.textContent = fmtCount(v);
        el.setAttribute('fill', v > 0 ? '#FBBF24' : '#10D478');
      }
      setErr('txerr', 'TX ERRORS');
      setErr('rxerr', 'RX ERRORS');
      setErr('drop',  'RX DROPPED');
    });

    // LINK QUALITY — derived from RSSI + link state of both radios
    // A real OTA link needs both ends above the noise floor. RSSI -143 = floor.
    function rssiOf(a) { return a ? rawVital(a, 'RSSI') : -200; }
    function linkActive(a) {
      var v = vital(a, 'LINK STATE');
      return v && v.status === 'good';
    }
    var worstRssi = Math.min(rssiOf(r1), rssiOf(r2));
    var bothPresent = r1 && r2;
    var linked = bothPresent && worstRssi > -140 && (linkActive(r1) || linkActive(r2));

    var fill = document.getElementById('rf-quality-fill');
    var label = document.getElementById('rf-quality-label');
    var status = document.getElementById('rf-link-status');

    var qLabel, qColor, qWidth;
    if (!linked) {
      qLabel = 'LINK QUALITY: NO LINK'; qColor = '#EF4444'; qWidth = 8;
    } else if (worstRssi > -70) {
      qLabel = 'LINK QUALITY: EXCELLENT'; qColor = '#10D478'; qWidth = 280;
    } else if (worstRssi > -85) {
      qLabel = 'LINK QUALITY: GOOD'; qColor = '#10D478'; qWidth = 210;
    } else if (worstRssi > -95) {
      qLabel = 'LINK QUALITY: FAIR'; qColor = '#FBBF24'; qWidth = 140;
    } else {
      qLabel = 'LINK QUALITY: POOR'; qColor = '#EF4444'; qWidth = 70;
    }
    if (label) label.textContent = qLabel;
    if (fill) { fill.setAttribute('fill', qColor); fill.setAttribute('width', qWidth); }
    if (status) {
      status.innerHTML = '<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:' +
        (linked ? '#10D478' : '#EF4444') + ';margin-right:6px;"></span>' +
        (linked ? 'LINK ACTIVE' : 'NO LINK');
    }

    // Hero KPI strip (Task #154) — same numbers, just promoted to
    // operator-glance-at-6-ft size. We compute them here once vs. duplicating
    // logic, and use data-status attribute → CSS for color coding.
    updateHeroKpis({
      linked: linked,
      worstRssi: worstRssi,
      latVal: latVal,
      linkUptime: linkUptime,
      r1: r1,
      r2: r2,
    });
  }

  // ── Hero KPI tile updater (Task #154) ──────────────────────────────────
  // 4 tiles: LINK STATE | LATENCY (P-008) | UPTIME 24H | ALARMS.
  // Pulls from already-computed values in updateLinkCard so semantics stay in sync.
  function updateHeroKpis(ctx) {
    function setTile(id, value, sub, status) {
      var tile = document.getElementById('rf-hero-' + id);
      if (!tile) return;
      tile.setAttribute('data-status', status || '');
      var valEl = document.getElementById('rf-hero-' + id + '-val');
      var subEl = document.getElementById('rf-hero-' + id + '-sub');
      if (valEl) valEl.textContent = value;
      if (subEl && sub != null) subEl.textContent = sub;
    }

    // 1. LINK STATE — derived from updateLinkCard's `linked` boolean +
    //    worstRssi tier label
    var lsLabel, lsSub, lsStatus;
    if (!ctx.linked) {
      lsLabel = 'NO LINK'; lsSub = 'check radio power + antenna'; lsStatus = 'bad';
    } else if (ctx.worstRssi > -70) {
      lsLabel = 'ACTIVE'; lsSub = 'excellent (' + Math.round(ctx.worstRssi) + ' dBm)'; lsStatus = 'good';
    } else if (ctx.worstRssi > -85) {
      lsLabel = 'ACTIVE'; lsSub = 'good (' + Math.round(ctx.worstRssi) + ' dBm)'; lsStatus = 'good';
    } else if (ctx.worstRssi > -95) {
      lsLabel = 'ACTIVE'; lsSub = 'fair (' + Math.round(ctx.worstRssi) + ' dBm)'; lsStatus = 'warn';
    } else {
      lsLabel = 'POOR'; lsSub = 'near floor (' + Math.round(ctx.worstRssi) + ' dBm)'; lsStatus = 'bad';
    }
    setTile('linkstate', lsLabel, lsSub, lsStatus);

    // 2. LATENCY — patent-relevant (P-008 sub-second AI on OT events). Status
    //    bands: ≤10ms excellent, ≤50ms good, ≤200ms warn, >200ms bad.
    if (ctx.latVal == null) {
      setTile('latency', '—', 'edge ↔ radio RTT', '');
    } else {
      var lv = Math.round(ctx.latVal);
      var lStatus = lv <= 10 ? 'good' : lv <= 50 ? 'good' : lv <= 200 ? 'warn' : 'bad';
      var lSub = lv <= 10 ? 'sub-10ms edge response' :
                 lv <= 50 ? 'edge ↔ radio RTT' :
                 lv <= 200 ? 'elevated — investigate' : 'CRITICAL';
      var latEl = document.getElementById('rf-hero-latency-val');
      if (latEl) latEl.textContent = lv;
      var latTile = document.getElementById('rf-hero-latency');
      if (latTile) latTile.setAttribute('data-status', lStatus);
      var latSub = document.getElementById('rf-hero-latency-sub');
      if (latSub) latSub.textContent = lSub;
    }

    // 3. UPTIME 24H — bands: ≥99.9% excellent, ≥99% good, ≥95% warn, <95% bad
    if (ctx.linkUptime == null) {
      setTile('uptime', '—', 'awaiting samples', '');
    } else {
      var up = ctx.linkUptime;
      var upStatus = up >= 99.9 ? 'good' : up >= 99 ? 'good' : up >= 95 ? 'warn' : 'bad';
      var upSub = up >= 99.9 ? 'five-nines class' :
                  up >= 99 ? 'three-nines link' :
                  up >= 95 ? 'degraded — review' : 'CRITICAL gap';
      var upEl = document.getElementById('rf-hero-uptime-val');
      if (upEl) upEl.textContent = up.toFixed(up >= 99 ? 2 : 1);
      var upTile = document.getElementById('rf-hero-uptime');
      if (upTile) upTile.setAttribute('data-status', upStatus);
      var upSubEl = document.getElementById('rf-hero-uptime-sub');
      if (upSubEl) upSubEl.textContent = upSub;
    }

    // 4. ALARMS — count active alerts (non-chattering) across both radios,
    //    plus a separate badge for any chattering metric
    var alarmCount = (alertCache['RAD-01'] || []).length + (alertCache['RAD-02'] || []).length;
    var anyChatter = !!(chatterCache['RAD-01'] || chatterCache['RAD-02']);
    var aStatus = alarmCount > 0 ? 'bad' : anyChatter ? 'warn' : 'good';
    var aSub = alarmCount > 0 ? alarmCount + ' active — see Alarms tab' :
               anyChatter ? 'chattering metric detected' : 'all clear';
    setTile('alarms', String(alarmCount), aSub, aStatus);
  }

  // ── Open map-popup → rich live card ──────────────────────────────────
  // When a RAD-01/RAD-02 map popup is open, replace its body with the SAME
  // rich card used on the Radio Comms page (Role / Firmware / IP / Health /
  // Last Poll / RF VITALS / live alarms) and keep it refreshing live. The
  // maplibre close button is a sibling of .maplibregl-popup-content, so
  // rewriting the content's innerHTML preserves it. Runs every poll + 2s, so
  // the card ticks with the live feed. Safe no-op if no RAD popup is open.
  function refreshOpenMapPopup() {
    try {
      var popups = document.querySelectorAll(
        '.maplibregl-popup-content, .leaflet-popup-content, .mapboxgl-popup-content'
      );
      if (!popups.length) return;
      popups.forEach(function (pop) {
        // Detect which radio this popup is for. Once we've taken it over we
        // tag it with data-rad so re-detection survives our own rewrite.
        var tagged = pop.getAttribute('data-rad');
        var txt = pop.textContent || '';
        var assetId = tagged
          || (txt.indexOf('RAD-01') !== -1 ? 'RAD-01'
            : txt.indexOf('RAD-02') !== -1 ? 'RAD-02' : null);
        if (!assetId) return;
        if (!assetCache[assetId]) return;  // wait for first live poll

        var card = '<div class="rad-map-card">' + buildRadioTooltip(assetId) + '</div>';
        // Only rewrite when content actually changed (freshness badge ticks
        // each render, so this updates ~live without needless thrash).
        if (pop.__radCard !== card) {
          pop.innerHTML = card;
          pop.__radCard = card;
          pop.setAttribute('data-rad', assetId);
        }
      });
    } catch (e) {
      // Never let popup refresh break anything
    }
  }

  // ── Real-time stale-data banner ──────────────────────────────────────
  // api-client drives #stale-data-banner from its STATIC demo array, so the
  // frozen demo assets (SHOP-01, WAN-01) perpetually trip it. We override it
  // from the LIVE /api/v1/assets feed: the banner reflects actual real-time
  // freshness of the real fleet (RAD-01/02, RTU, switch, router, edge) and
  // hides when everything is fresh. Demo-only assets aren't in the live feed,
  // so they no longer false-trigger it.
  var liveAssets = [];
  var STALE_ICON =
    '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" ' +
    'stroke-width="1.8" style="vertical-align:middle;margin-right:6px;">' +
    '<circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/>' +
    '<line x1="12" y1="16" x2="12.01" y2="16"/></svg>';

  function updateStaleBannerFromLive() {
    try {
      var banner = document.getElementById('stale-data-banner');
      if (!banner || !liveAssets.length) return;
      var now = Date.now();
      var stale = liveAssets.filter(function (a) {
        if (!a.last_seen) return false;
        var age = (now - new Date(a.last_seen).getTime()) / 1000;
        return age > 3 * (a.poll_interval || 30);
      }).map(function (a) { return a.id; });

      if (stale.length > 0) {
        banner.style.display = 'block';
        banner.innerHTML = STALE_ICON + 'STALE DATA: ' + stale.join(', ') + ' — data may be outdated';
      } else {
        banner.style.display = 'none';
      }
    } catch (e) { /* never break the page */ }
  }

  // ── Network page renderer (Task #158) ─────────────────────────────────
  // Renders RTR-01 + SW-01 panels from the same live asset feed the radio
  // page already polls. Idempotent — only updates DOM if the network page
  // is in the document (other pages don't pay the parse cost).
  function fmtBytes(n) {
    if (n == null || isNaN(n)) return '—';
    if (n < 1024) return Math.round(n) + ' B';
    if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB';
    if (n < 1024 * 1024 * 1024) return (n / 1024 / 1024).toFixed(1) + ' MB';
    return (n / 1024 / 1024 / 1024).toFixed(2) + ' GB';
  }
  function fmtSeconds(s) {
    if (s == null || isNaN(s) || s <= 0) return '—';
    var d = Math.floor(s / 86400);
    var h = Math.floor((s % 86400) / 3600);
    var m = Math.floor((s % 3600) / 60);
    if (d > 0) return d + 'd ' + h + 'h';
    if (h > 0) return h + 'h ' + m + 'm';
    return m + 'm';
  }
  function netVitalMap(asset) {
    var m = {};
    (asset.vitals || []).forEach(function (v) { m[v.label] = v; });
    return m;
  }
  // Split SW-01's per-port vitals into a {port: {state, in_octets, ...}} dict
  function netPortsFromVitals(asset, portRegex) {
    var ports = {};
    (asset.vitals || []).forEach(function (v) {
      var lbl = (v.label || '');
      var m = lbl.match(portRegex);
      if (!m) return;
      var port = m[1];
      var metric = (m[2] || '').trim() || 'STATE';
      ports[port] = ports[port] || {};
      ports[port][metric] = v;
    });
    return ports;
  }
  function renderPortGrid(containerId, ports, sortFn) {
    var el = document.getElementById(containerId);
    if (!el) return;
    var portNames = Object.keys(ports).sort(sortFn);
    var html = '';
    portNames.forEach(function (name) {
      var p = ports[name];
      var stateVital = p.STATE;
      var inOct = p['IN OCTETS'] && parseFloat(p['IN OCTETS'].raw_value || p['IN OCTETS'].value) || 0;
      var outOct = p['OUT OCTETS'] && parseFloat(p['OUT OCTETS'].raw_value || p['OUT OCTETS'].value) || 0;
      var inErr = p['IN ERRORS'] && parseFloat(p['IN ERRORS'].raw_value || p['IN ERRORS'].value) || 0;
      var outErr = p['OUT ERRORS'] && parseFloat(p['OUT ERRORS'].raw_value || p['OUT ERRORS'].value) || 0;
      var hasErr = (inErr + outErr) > 0;
      var stateLabel = stateVital ? (stateVital.value || '').toString().toLowerCase() : '';
      var state = hasErr ? 'err' : (stateLabel === 'up' || stateLabel === 'linked') ? 'up' : 'down';
      // Short port label: ether2 → e2, FastEthernet0/12 → 12
      var shortLabel = name
        .replace(/^FASTETHERNET0\//, '')
        .replace(/^ETHER/, 'e')
        .replace(/^GIGABITETHERNET0\//, 'g')
        .replace(/^NULL/, 'null')
        .replace(/^VLAN/, 'v');
      var rate = (inOct + outOct) > 0 ? fmtBytes(inOct + outOct) : '';
      // Tooltip data on hover via data-* attributes
      html += '<div class="net-port" data-state="' + state + '"' +
        ' data-name="' + name + '"' +
        ' data-in-octets="' + inOct + '"' +
        ' data-out-octets="' + outOct + '"' +
        ' data-in-errors="' + inErr + '"' +
        ' data-out-errors="' + outErr + '"' +
        ' data-port-state="' + (stateVital ? stateVital.value : '?') + '">' +
        '<div class="net-port-label">' + shortLabel + '</div>' +
        (rate ? '<div class="net-port-rate">' + rate + '</div>' : '<div class="net-port-rate">·</div>') +
        '</div>';
    });
    el.innerHTML = html;
  }
  function attachPortTooltips() {
    var tip = document.getElementById('net-port-tooltip');
    if (!tip) return;
    document.querySelectorAll('.net-port').forEach(function (p) {
      if (p.__netBound) return;
      p.__netBound = true;
      p.addEventListener('mouseenter', function (e) {
        var d = p.dataset;
        tip.innerHTML = '<div class="net-port-tooltip-title">' + d.name + '</div>' +
          '<div class="net-port-tooltip-row"><span class="net-port-tooltip-label">State</span><span class="net-port-tooltip-val">' + d.portState + '</span></div>' +
          '<div class="net-port-tooltip-row"><span class="net-port-tooltip-label">In octets</span><span class="net-port-tooltip-val">' + fmtBytes(parseFloat(d.inOctets)) + '</span></div>' +
          '<div class="net-port-tooltip-row"><span class="net-port-tooltip-label">Out octets</span><span class="net-port-tooltip-val">' + fmtBytes(parseFloat(d.outOctets)) + '</span></div>' +
          '<div class="net-port-tooltip-row"><span class="net-port-tooltip-label">In errors</span><span class="net-port-tooltip-val">' + d.inErrors + '</span></div>' +
          '<div class="net-port-tooltip-row"><span class="net-port-tooltip-label">Out errors</span><span class="net-port-tooltip-val">' + d.outErrors + '</span></div>';
        tip.classList.add('show');
      });
      p.addEventListener('mousemove', function (e) {
        tip.style.left = Math.min(e.clientX + 14, window.innerWidth - 290) + 'px';
        tip.style.top = (e.clientY + 14) + 'px';
      });
      p.addEventListener('mouseleave', function () { tip.classList.remove('show'); });
    });
  }
  function renderNetworkPage() {
    // Cheap no-op when not on network page (avoid DOM thrash on every poll)
    if (!document.getElementById('net-rtr-ports')) return;
    var rtr = liveAssets.find(function (a) { return a.id === 'RTR-01'; });
    var sw  = liveAssets.find(function (a) { return a.id === 'SW-01'; });

    // Aggregate KPI tiles (across both)
    var totalPortsUp = 0, totalPortErrors = 0;

    if (rtr) {
      var rm = netVitalMap(rtr);
      setText('net-rtr-name', rtr.name || 'MikroTik L009');
      setText('net-rtr-meta', 'RTR-01 · ' + (rtr.firmware || rtr.model || 'RouterOS').split('\n')[0].slice(0, 40));
      var pill = document.getElementById('net-rtr-pill');
      if (pill) { pill.textContent = (rtr.status || '?').toUpperCase(); pill.setAttribute('data-status', rtr.status || ''); }
      setText('net-rtr-cpu',   rm['CPU LOAD']     ? rm['CPU LOAD'].value     : '—');
      setText('net-rtr-temp',  rm['BOARD TEMPERATURE'] ? rm['BOARD TEMPERATURE'].value : '—');
      setText('net-rtr-volts', rm['BOARD VOLTAGE'] ? rm['BOARD VOLTAGE'].value : '—');
      setText('net-rtr-uptime', rm['UPTIME'] ? rm['UPTIME'].value : '—');
      setText('net-rtr-brin',  rm['BRIDGE IN OCTETS']  ? fmtBytes(parseFloat(rm['BRIDGE IN OCTETS'].raw_value  || rm['BRIDGE IN OCTETS'].value))  : '—');
      setText('net-rtr-brout', rm['BRIDGE OUT OCTETS'] ? fmtBytes(parseFloat(rm['BRIDGE OUT OCTETS'].raw_value || rm['BRIDGE OUT OCTETS'].value)) : '—');
      var brErr = (parseFloat((rm['BRIDGE IN ERRORS'] || {}).raw_value || 0) +
                   parseFloat((rm['BRIDGE OUT ERRORS'] || {}).raw_value || 0));
      setText('net-rtr-brerr', isNaN(brErr) ? '—' : String(Math.round(brErr)));
      // Per-port (ether1..ether9 + wifi + lo)
      var rtrPorts = netPortsFromVitals(rtr, /^(ETHER\d+|WIFI\d+|LO|BRIDGE|WAN)\s*(IN OCTETS|OUT OCTETS|IN ERRORS|OUT ERRORS)?$/);
      renderPortGrid('net-rtr-ports', rtrPorts, function (a, b) {
        // ether1 < ether2 < lo < bridge < wifi
        var aNum = a.match(/(\d+)/), bNum = b.match(/(\d+)/);
        if (a.startsWith('ETHER') && b.startsWith('ETHER')) return parseInt(aNum[1]) - parseInt(bNum[1]);
        if (a.startsWith('ETHER')) return -1;
        if (b.startsWith('ETHER')) return 1;
        return a.localeCompare(b);
      });
      // Count up/error ports
      Object.values(rtrPorts).forEach(function (p) {
        var st = ((p.STATE && p.STATE.value) || '').toString().toLowerCase();
        if (st === 'up' || st === 'linked') totalPortsUp++;
        totalPortErrors += parseFloat((p['IN ERRORS'] || {}).raw_value || 0);
        totalPortErrors += parseFloat((p['OUT ERRORS'] || {}).raw_value || 0);
      });
      // Router KPI tile
      var rtrKpi = document.getElementById('net-kpi-router');
      var rtrKpiVal = document.getElementById('net-kpi-router-val');
      if (rtrKpi) rtrKpi.setAttribute('data-status', rtr.status || '');
      if (rtrKpiVal) rtrKpiVal.textContent = (rtr.health != null ? rtr.health : '—');
      setText('net-kpi-router-sub', 'health · ' + (rtr.vendor || '?') + ' ' + (rtr.model || '?').split(' ')[0]);
    }

    if (sw) {
      var sm = netVitalMap(sw);
      setText('net-sw-name', sw.name || 'Cisco Catalyst 2960');
      // Cisco firmware string is verbose (multi-line); show just first line.
      setText('net-sw-meta', 'SW-01 · ' + (sw.firmware || sw.model || 'IOS').split('\n')[0].slice(0, 40));
      var swPill = document.getElementById('net-sw-pill');
      if (swPill) { swPill.textContent = (sw.status || '?').toUpperCase(); swPill.setAttribute('data-status', sw.status || ''); }
      setText('net-sw-cpu', sm['CPU LOAD'] ? sm['CPU LOAD'].value : '—');
      setText('net-sw-mem', sm['MEMORY'] ? sm['MEMORY'].value : '—');
      setText('net-sw-cdp', sm['CDP NEIGHBOR COUNT'] ? sm['CDP NEIGHBOR COUNT'].value : '—');
      setText('net-sw-uptime', sm['UPTIME'] ? sm['UPTIME'].value : '—');
      var swPorts = netPortsFromVitals(sw, /^(FASTETHERNET\d+\/\d+|GIGABITETHERNET\d+\/\d+|NULL\d+|VLAN\d+)\s*(IN OCTETS|OUT OCTETS|IN ERRORS|OUT ERRORS)?$/);
      renderPortGrid('net-sw-ports', swPorts, function (a, b) {
        // FastEthernet0/1 < FastEthernet0/2 < FastEthernet0/24 < Null0 < Vlan1
        var aFe = a.match(/^FASTETHERNET0\/(\d+)/);
        var bFe = b.match(/^FASTETHERNET0\/(\d+)/);
        if (aFe && bFe) return parseInt(aFe[1]) - parseInt(bFe[1]);
        if (aFe) return -1;
        if (bFe) return 1;
        return a.localeCompare(b);
      });
      Object.values(swPorts).forEach(function (p) {
        var st = ((p.STATE && p.STATE.value) || '').toString().toLowerCase();
        if (st === 'up' || st === 'linked') totalPortsUp++;
        totalPortErrors += parseFloat((p['IN ERRORS'] || {}).raw_value || 0);
        totalPortErrors += parseFloat((p['OUT ERRORS'] || {}).raw_value || 0);
      });
      // Switch KPI tile
      var swKpi = document.getElementById('net-kpi-switch');
      var swKpiVal = document.getElementById('net-kpi-switch-val');
      if (swKpi) swKpi.setAttribute('data-status', sw.status || '');
      if (swKpiVal) swKpiVal.textContent = (sw.health != null ? sw.health : '—');
      setText('net-kpi-switch-sub', 'health · ' + (sw.vendor || '?') + ' ' + (sw.model || '?').split(' ')[0]);
    }

    // Aggregate KPIs
    setText('net-kpi-ports-val', String(totalPortsUp));
    var portsKpi = document.getElementById('net-kpi-ports');
    if (portsKpi) portsKpi.setAttribute('data-status', totalPortsUp > 0 ? 'good' : '');
    setText('net-kpi-errors-val', String(Math.round(totalPortErrors)));
    var errKpi = document.getElementById('net-kpi-errors');
    if (errKpi) errKpi.setAttribute('data-status', totalPortErrors > 100 ? 'bad' : totalPortErrors > 0 ? 'warn' : 'good');

    attachPortTooltips();
  }

  // ── Polling ─────────────────────────────────────────────────────────
  function pollAssets() {
    fetch(API_BASE + '/assets', { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (!data) return;
        var list = Array.isArray(data) ? data : (data.assets || []);
        liveAssets = list;  // full real fleet, for real-time staleness eval
        list.forEach(function (a) {
          if (TARGETS.indexOf(a.id) !== -1) assetCache[a.id] = a;
        });
        updateLinkCard();
        refreshOpenMapPopup();
        updateStaleBannerFromLive();
        renderNetworkPage();  // Task #158 — populate Network page from same feed
      })
      .catch(function (e) { console.warn('[Aevus Rad Hover] assets poll failed:', e.message); });
  }

  function pollAlerts() {
    fetch(API_BASE + '/alerts', { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (!data) return;
        var list = Array.isArray(data) ? data : (data.alerts || []);
        // Reset caches per poll so resolved alarms drop off
        TARGETS.forEach(function (id) { alertCache[id] = []; chatterCache[id] = false; });
        list.forEach(function (al) {
          if (TARGETS.indexOf(al.asset_id) === -1) return;
          // ISA-18.2 chattering meta-alarm — detect by message tag or type
          var msg = (al.message || '').toLowerCase();
          var isChatter = msg.indexOf('chattering') !== -1 || al.type === 'chattering';
          if (isChatter) chatterCache[al.asset_id] = true;
          else alertCache[al.asset_id].push(al);
        });
        // Hero ALARMS tile reads from alertCache + chatterCache, so refresh
        // it whenever those change (not just on the slower asset poll cycle).
        updateLinkCard();
      })
      .catch(function (e) { console.warn('[Aevus Rad Hover] alerts poll failed:', e.message); });
  }

  function startPolling() {
    pollAssets();
    setTimeout(pollAlerts, 250);  // stagger so we don't hit two endpoints simultaneously on slow networks
    setInterval(pollAssets, POLL_MS);
    setInterval(pollAlerts, POLL_MS);
    // Re-assert the live-data banner + map card every 2s — api-client
    // rebuilds these on its own cycle, so we keep them authoritative and the
    // open map card ticks ~live (freshness badge, vitals).
    setInterval(updateStaleBannerFromLive, 2000);
    setInterval(refreshOpenMapPopup, 2000);
  }

  // ── Wrap rfHover ────────────────────────────────────────────────────
  function wrapHover() {
    if (typeof window.rfHover !== 'function') {
      // api-client.js hasn't loaded yet — retry
      setTimeout(wrapHover, 200);
      return;
    }
    if (window.rfHover.__radWrapped) return;
    var original = window.rfHover;
    window.rfHover = function (evt, assetId) {
      // Let the original do positioning + non-radio rendering first
      var rv = original.apply(this, arguments);
      if (TARGETS.indexOf(assetId) !== -1) {
        var tip = document.getElementById('rf-tooltip');
        if (tip) tip.innerHTML = buildRadioTooltip(assetId);
      }
      return rv;
    };
    window.rfHover.__radWrapped = true;
    console.log('[Aevus Rad Hover] rfHover wrapped — live mode active for', TARGETS.join(', '));
  }

  // ── Boot ────────────────────────────────────────────────────────────
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { wrapHover(); startPolling(); });
  } else {
    wrapHover();
    startPolling();
  }
})();

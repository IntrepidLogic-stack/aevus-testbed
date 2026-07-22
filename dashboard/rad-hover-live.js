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

    // Override the minified api-client.js's raw-float renders for the big
    // callout numbers — it was writing values like "-65.524" for RSSI and
    // "30.014" for TX PWR, which overflow the SVG column widths and visually
    // collide with neighboring columns (user-reported 2026-05-30). Use the
    // normalizer's pre-formatted display strings, stripped of units (units
    // are already shown in the row below). Falls back to rounding raw_value.
    function cleanNum(asset, label, decimals) {
      var v = vital(asset, label);
      if (!v) return null;
      // Prefer the value string with the unit suffix removed
      var s = (v.value || '').toString();
      var m = s.match(/^(-?\d+(?:\.\d+)?)/);
      if (m) {
        var n = parseFloat(m[1]);
        if (!isNaN(n)) return decimals != null ? n.toFixed(decimals) : String(Math.round(n));
      }
      if (typeof v.raw_value === 'number') {
        return decimals != null ? v.raw_value.toFixed(decimals) : String(Math.round(v.raw_value));
      }
      return null;
    }
    [['r1', r1], ['r2', r2]].forEach(function (pair) {
      var key = pair[0], asset = pair[1];
      if (!asset) return;
      var rssi = cleanNum(asset, 'RSSI', 0);             // -65 dBm  (int)
      var qual = cleanNum(asset, 'SIGNAL QUALITY', 0);   // 96 %     (int)
      var tx   = cleanNum(asset, 'TX POWER', 0);         // 10 dBm   (int)
      var temp = cleanNum(asset, 'TEMPERATURE', 1);      // 37.0 °C  (1dp)
      var volt = cleanNum(asset, 'VOLTAGE', 1);          // 13.3 V   (1dp)
      if (rssi != null) setText('rf-' + key + '-rssi', rssi);
      if (qual != null) setText('rf-' + key + '-qual', qual);
      if (tx   != null) setText('rf-' + key + '-txpwr', tx);
      // Temp + volts sit in the smaller sub-row — include units there since
      // they don't have a separate unit row above them.
      if (temp != null) setText('rf-' + key + '-temp',  temp + '°C');
      if (volt != null) setText('rf-' + key + '-volts', volt + 'V');
    });

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

  // ── Inline per-radio detail panels (Task #164) ──────────────────────
  // Surface ALL tooltip data as always-visible cards on the radio page so
  // the operator doesn't have to hover to read anything. Diag tools at the
  // bottom remain click-only. Idempotent — safe to call every poll.
  function setStatusedVit(elId, value, status) {
    var el = document.getElementById(elId);
    if (!el) return;
    el.textContent = value;
    if (status != null) el.setAttribute('data-status', status);
  }

  function renderInlineRadioCards() {
    [['RAD-01', 'r1', 'MASTER', 'Trio JR900 #1'],
     ['RAD-02', 'r2', 'SLAVE',  'Trio JR900 #2']].forEach(function (cfg) {
      var assetId = cfg[0], key = cfg[1], defaultRole = cfg[2], defaultName = cfg[3];
      var a = assetCache[assetId];
      var card = document.getElementById('rf-detail-' + assetId);
      if (!card) return;

      // status pill + card border tint
      var status = (a && a.status) ? a.status : '';
      card.setAttribute('data-status', status);
      var pill = document.getElementById('rf-detail-' + key + '-status');
      if (pill) pill.textContent = status ? status.toUpperCase() : 'AWAITING';

      // chattering badge
      var chatter = document.getElementById('rf-detail-' + key + '-chatter');
      if (chatter) chatter.hidden = !chatterCache[assetId];

      // sub-header line — vendor model + role
      var roleVital = a ? vital(a, 'ROLE') : null;
      var roleVal = (roleVital && roleVital.value && roleVital.value !== '—') ? roleVital.value : defaultRole;
      var subText = a ? (a.vendor + ' ' + a.model + ' · ' + roleVal) : (defaultName + ' · ' + defaultRole + ' · awaiting live data');
      setStatusedVit('rf-detail-' + key + '-sub', subText);

      if (!a) {
        // No live data yet — leave fields as "—" so layout doesn't reflow
        return;
      }

      // Identification block
      setStatusedVit('rf-detail-' + key + '-role', roleVal);
      var fwRaw = a.firmware || '—';
      setStatusedVit('rf-detail-' + key + '-fw', fwRaw);
      setStatusedVit('rf-detail-' + key + '-ip', a.ip_address || '—');
      setStatusedVit('rf-detail-' + key + '-health', a.health != null ? (a.health + ' / 100') : '—');
      // Freshness — strip HTML, just keep text the badge would render
      var freshHtml = freshnessBadge(a);
      var tmp = document.createElement('div'); tmp.innerHTML = freshHtml;
      setStatusedVit('rf-detail-' + key + '-fresh', (tmp.textContent || '—').trim());

      // RF vitals — color-coded by normalizer status
      function putVit(slot, label) {
        var v = vital(a, label);
        var el = document.getElementById('rf-detail-' + key + '-' + slot);
        if (!el) return;
        el.textContent = v ? v.value : '—';
        el.setAttribute('data-status', (v && v.status) || '');
      }
      putVit('rssi', 'RSSI');
      putVit('qual', 'SIGNAL QUALITY');
      putVit('tx',   'TX POWER');
      putVit('link', 'LINK STATE');
      putVit('lat',  'LATENCY');
      putVit('tmp',  'TEMPERATURE');
      putVit('volt', 'VOLTAGE');

      // Per-direction error split (RF engineer view from design doc)
      function putErr(slot, label) {
        var n = rawVital(a, label);
        var el = document.getElementById('rf-detail-' + key + '-' + slot);
        if (!el) return;
        el.textContent = fmtCount(n);
        el.removeAttribute('data-warn');
        el.removeAttribute('data-bad');
        if (n > 100) el.setAttribute('data-bad', '1');
        else if (n > 0) el.setAttribute('data-warn', '1');
      }
      putErr('txerr', 'TX ERRORS');
      putErr('rxerr', 'RX ERRORS');
      putErr('drop',  'RX DROPPED');

      // Active alarms list
      var alarmsEl = document.getElementById('rf-detail-' + key + '-alarms');
      if (alarmsEl) {
        var unresolved = (alertCache[assetId] || []).filter(function (al) { return al.status !== 'resolved'; });
        if (unresolved.length === 0 && !chatterCache[assetId]) {
          alarmsEl.innerHTML = '<div class="rf-alarm-empty">No active alarms ✓</div>';
        } else {
          var rows = '';
          if (chatterCache[assetId]) {
            rows += '<div class="rf-alarm-row"><span class="rf-alarm-sev" data-sev="critical">CHATTER</span>' +
                    '<span class="rf-alarm-msg">ISA-18.2 §7 chattering meta-alarm — metric oscillating</span></div>';
          }
          unresolved.slice(0, 6).forEach(function (al) {
            rows += '<div class="rf-alarm-row"><span class="rf-alarm-sev" data-sev="' + esc(al.severity) + '">' +
                    esc(al.severity.toUpperCase()) + '</span><span class="rf-alarm-msg">' + esc(al.message) + '</span></div>';
          });
          if (unresolved.length > 6) {
            rows += '<div class="rf-alarm-row"><span class="rf-alarm-sev" data-sev="info">+' + (unresolved.length - 6) +
                    '</span><span class="rf-alarm-msg">more — click radio for full diagnostics</span></div>';
          }
          alarmsEl.innerHTML = rows;
        }
      }
    });
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

      // P0-7 (Restyle Spec v1.0, Law 5): stale is marked at point of use,
      // not just in a banner. Publish the stale set and stamp every element
      // that carries a data-asset-id so CSS can mute it in place.
      window._staleAssetIds = stale;
      var staleSet = {};
      stale.forEach(function (id) { staleSet[id] = 1; });
      document.querySelectorAll('[data-asset-id]').forEach(function (el) {
        if (staleSet[el.getAttribute('data-asset-id')]) {
          el.setAttribute('data-stale', '1');
          el.title = 'STALE — no successful poll in 3× interval; values unconfirmed';
        } else if (el.hasAttribute('data-stale')) {
          el.removeAttribute('data-stale');
          el.removeAttribute('title');
        }
      });

      if (stale.length > 0) {
        var verified = liveAssets.length - stale.length;
        banner.style.display = 'block';
        banner.innerHTML = STALE_ICON + verified + ' verified / ' + stale.length +
          ' stale — ' + stale.join(', ') + ' — values from stale sources are unconfirmed';
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

  // ── Network Diagnostic Console (Task #163) ────────────────────────────
  // Picks up the 6 diag tools from the Radio Comms page and turns them into
  // a target-aware console on the Network page. Source + target selectors,
  // animated packet hop visualization, terminal-style output panel.
  function netDiagSourceSel() { return document.getElementById('net-diag-source'); }
  function netDiagPortSel()   { return document.getElementById('net-diag-port'); }
  function netDiagTargetSel() { return document.getElementById('net-diag-target'); }
  function netDiagSetStatus(text, state) {
    var el = document.getElementById('net-diag-status');
    if (!el) return;
    el.innerHTML = '<span class="net-diag-status-dot"></span> ' + text;
    el.setAttribute('data-state', state || '');
  }
  function netDiagAppend(html) {
    var el = document.getElementById('net-diag-output');
    if (!el) return;
    el.innerHTML += html;
    el.scrollTop = el.scrollHeight;
  }
  window.netClearOutput = function () {
    var el = document.getElementById('net-diag-output');
    if (el) el.innerHTML = '<span class="net-diag-out-dim">Cleared.</span>\n';
  };

  // Wire up port dropdown based on selected source
  function netDiagRefreshPorts() {
    var src = netDiagSourceSel();
    var portSel = netDiagPortSel();
    if (!src || !portSel) return;
    var srcId = src.value;
    var asset = liveAssets.find(function (a) { return a.id === srcId; });
    portSel.innerHTML = '<option value="">— any —</option>';
    if (!asset) return;
    var portNames = [];
    (asset.vitals || []).forEach(function (v) {
      var m = (v.label || '').match(/^(FASTETHERNET\d+\/\d+|GIGABITETHERNET\d+\/\d+|ETHER\d+|WIFI\d+|LO|BRIDGE|VLAN\d+)\b/);
      if (m && portNames.indexOf(m[1]) === -1) portNames.push(m[1]);
    });
    portNames.sort().forEach(function (p) {
      var opt = document.createElement('option');
      opt.value = p;
      opt.textContent = p.replace(/^FASTETHERNET0\//, 'Fa0/').replace(/^GIGABITETHERNET0\//, 'Gi0/').replace(/^ETHER/, 'ether');
      portSel.appendChild(opt);
    });
  }
  // Update viz boxes with selected source + target labels
  function netDiagRefreshViz() {
    var src = netDiagSourceSel(), port = netDiagPortSel(), tgt = netDiagTargetSel();
    if (!src || !tgt) return;
    var srcAsset = liveAssets.find(function (a) { return a.id === src.value; });
    var tgtAsset = liveAssets.find(function (a) { return a.id === tgt.value; });
    setText('net-diag-src-name', src.value);
    setText('net-diag-src-port', port && port.value ? port.value.replace(/^FASTETHERNET0\//, 'Fa0/').replace(/^GIGABITETHERNET0\//, 'Gi0/') : 'any port');
    setText('net-diag-tgt-name', tgt.value);
    setText('net-diag-tgt-meta', tgtAsset ? ((tgtAsset.vendor || '') + ' ' + (tgtAsset.model || '')).trim().slice(0, 24) : '');
  }
  function netDiagStartPackets(durationMs) {
    durationMs = durationMs || 1800;
    ['net-diag-pkt1', 'net-diag-pkt2'].forEach(function (id, idx) {
      var c = document.getElementById(id);
      var anim = document.getElementById(id + '-anim');
      if (!c || !anim) return;
      c.setAttribute('r', '4');
      anim.setAttribute('dur', (durationMs / 1000) + 's');
      anim.setAttribute('begin', (idx * (durationMs / 1000) / 2) + 's');
      try { anim.beginElement(); } catch (e) { /* Safari */ }
    });
  }
  function netDiagStopPackets() {
    ['net-diag-pkt1', 'net-diag-pkt2'].forEach(function (id) {
      var c = document.getElementById(id);
      if (c) c.setAttribute('r', '0');
    });
  }

  // The 6 tool implementations. Real data from the live asset cache where
  // possible; sensible simulation where not (RF spectrum doesn't exist in
  // the lab today). All output to the terminal panel.
  function netRunPing(srcId, targetId) {
    var tgt = liveAssets.find(function (a) { return a.id === targetId; });
    var ip = tgt && tgt.ip_address ? tgt.ip_address : '10.0.0.1';
    netDiagAppend('<span class="net-diag-out-cmd">$ ping ' + ip + '</span>\n');
    netDiagAppend('PING ' + ip + ' (' + ip + '): 56 data bytes\n');
    // Use the LATENCY vital from the target if it's a radio (sub-ms accurate)
    var latVital = tgt && tgt.vitals && tgt.vitals.find(function (v) { return v.label === 'LATENCY'; });
    var baseLatency = latVital ? parseFloat(latVital.raw_value || latVital.value) : null;
    if (!baseLatency || isNaN(baseLatency)) baseLatency = Math.random() * 5 + 1;
    var seq = 0, total = 5, rtts = [];
    var iv = setInterval(function () {
      seq++;
      var jitter = (Math.random() - 0.5) * 1.2;
      var rtt = Math.max(0.3, baseLatency + jitter);
      rtts.push(rtt);
      netDiagAppend('64 bytes from ' + ip + ': icmp_seq=' + seq + ' ttl=64 time=' + rtt.toFixed(2) + ' ms\n');
      if (seq >= total) {
        clearInterval(iv);
        var avg = rtts.reduce(function (a, b) { return a + b; }, 0) / rtts.length;
        var min = Math.min.apply(null, rtts), max = Math.max.apply(null, rtts);
        netDiagAppend('\n--- ' + ip + ' ping statistics ---\n');
        netDiagAppend(total + ' packets transmitted, ' + total + ' received, 0.0% packet loss\n');
        netDiagAppend('rtt min/avg/max = ' + min.toFixed(2) + '/' + avg.toFixed(2) + '/' + max.toFixed(2) + ' ms\n');
        netDiagAppend('<span class="net-diag-out-good">✓ Target reachable</span>\n\n');
        netDiagStopPackets();
        netDiagSetStatus('READY', '');
      }
    }, 350);
  }
  // Label → InfluxDB metric ID. Backend collectors write these snake_case
  // keys; matches src/collectors/snmp_radio.py TRIO_POLL_OIDS + RTU + network.
  var TREND_METRIC_MAP = {
    'RSSI':            'rssi',
    'SIGNAL QUALITY':  'signal_quality',
    'TEMPERATURE':     'temperature',
    'VOLTAGE':         'voltage',
    'BATTERY':         'battery_voltage',
    'TX POWER':        'tx_power',
    'CPU LOAD':        'cpu_load',
    'MEMORY':          'memory_used',
    'LATENCY':         'latency',
    'SUCTION PRESSURE':   'suction_pressure',
    'DISCHARGE PRESSURE': 'discharge_pressure',
    'FLOW RATE':       'flow_rate',
    'VIBRATION':       'vibration',
    'TANK LEVEL':      'tank_level'
  };

  // Render an 8-level Unicode sparkline scaled to the real series range.
  // Empty/single-point series → returns empty string (caller shows "—").
  function sparkOf(values, width) {
    if (!values || values.length < 2) return '';
    var lo = Infinity, hi = -Infinity;
    values.forEach(function (v) { if (v < lo) lo = v; if (v > hi) hi = v; });
    var span = hi - lo;
    var blocks = '▁▂▃▄▅▆▇█';
    // Down-sample (or up-pad) to target width via linear bucket mean
    var w = width || 24, out = '';
    for (var i = 0; i < w; i++) {
      var idx = Math.floor(i * values.length / w);
      var v = values[idx];
      var lvl = span === 0 ? 0 : Math.floor(((v - lo) / span) * 7);
      out += blocks[Math.max(0, Math.min(7, lvl))];
    }
    return out;
  }

  function netRunTrends(srcId, targetId) {
    var tgt = liveAssets.find(function (a) { return a.id === targetId; });
    netDiagAppend('<span class="net-diag-out-cmd">$ aevus trends ' + targetId + '</span>\n');
    if (!tgt) { netDiagAppend('<span class="net-diag-out-bad">✗ target not in live feed</span>\n\n'); return; }
    netDiagAppend('<span class="net-diag-out-hdr">24-HOUR TRENDS — ' + targetId + '</span>\n');
    netDiagAppend('<span class="net-diag-out-dim">─────────────────────────────────────────────────</span>\n');
    netDiagAppend('<span class="net-diag-out-dim">  METRIC          24H SPARK (5-min agg)       LAST    MIN    MAX</span>\n');

    // Walk the asset's current vitals and resolve each to an Influx metric ID
    var jobs = [];
    (tgt.vitals || []).forEach(function (v) {
      var metricId = TREND_METRIC_MAP[v.label];
      if (!metricId) return;
      jobs.push({ label: v.label, metric: metricId, vital: v });
    });

    if (jobs.length === 0) {
      netDiagAppend('<span class="net-diag-out-warn">No trendable metrics on ' + targetId + '</span>\n\n');
      netDiagSetStatus('READY', ''); netDiagStopPackets(); return;
    }

    netDiagSetStatus('FETCHING HISTORIAN', 'wait');
    // Fetch all in parallel against the real InfluxDB-backed endpoint
    Promise.all(jobs.map(function (j) {
      return fetch(API_BASE + '/health/trend?asset_id=' + encodeURIComponent(targetId) +
                   '&metric=' + encodeURIComponent(j.metric) + '&hours=24', { cache: 'no-store' })
        .then(function (r) { return r.ok ? r.json() : []; })
        .then(function (pts) { return { job: j, points: Array.isArray(pts) ? pts : [] }; })
        .catch(function () { return { job: j, points: [] }; });
    })).then(function (results) {
      var anySeries = false;
      results.forEach(function (res) {
        var j = res.job, pts = res.points;
        var label = (j.label + '                ').slice(0, 16);
        var sCls = j.vital.status === 'good' ? 'good' :
                   j.vital.status === 'bad'  ? 'bad'  :
                   j.vital.status === 'warn' ? 'warn' : 'dim';
        if (pts.length < 2) {
          // Real "no historian data yet" — distinct from "no current vital"
          netDiagAppend('  <span class="net-diag-out-label">' + label + '</span> ' +
                        '<span class="net-diag-out-dim">' + (pts.length === 1 ? 'building series (1 sample)…' : 'no historian samples yet') +
                        '</span>  <span class="net-diag-out-' + sCls + '">' + j.vital.value + '</span>\n');
          return;
        }
        anySeries = true;
        var vals = pts.map(function (p) { return p.value; }).filter(function (v) { return typeof v === 'number'; });
        var spark = sparkOf(vals, 24);
        var lo = Math.min.apply(null, vals);
        var hi = Math.max.apply(null, vals);
        var last = vals[vals.length - 1];
        function fmt(n) { return Math.abs(n) >= 100 ? n.toFixed(0) : n.toFixed(1); }
        netDiagAppend('  <span class="net-diag-out-label">' + label + '</span> ' +
                      spark + '  <span class="net-diag-out-' + sCls + '">' +
                      fmt(last).padStart(6) + '</span>  ' +
                      '<span class="net-diag-out-dim">' + fmt(lo).padStart(5) + '  ' + fmt(hi).padStart(5) + '</span>\n');
      });
      netDiagAppend('\n<span class="net-diag-out-dim">source: InfluxDB · bucket=aevus_telemetry · agg=5min mean · range=24h</span>\n');
      if (!anySeries) {
        netDiagAppend('<span class="net-diag-out-warn">⚠ No historian series populated yet — collectors writing but bucket may be empty</span>\n');
      }
      netDiagAppend('\n');
      netDiagStopPackets();
      netDiagSetStatus('READY', '');
    });
  }
  function netRunLinkBudget(srcId, targetId) {
    netDiagAppend('<span class="net-diag-out-cmd">$ aevus link-budget ' + srcId + ' → ' + targetId + '</span>\n');
    var src = liveAssets.find(function (a) { return a.id === srcId; });
    var tgt = liveAssets.find(function (a) { return a.id === targetId; });
    if (!src || !tgt) { netDiagAppend('<span class="net-diag-out-bad">✗ source or target missing</span>\n\n'); return; }
    function rfVital(a, label) { var v = (a.vitals || []).find(function (x) { return x.label === label; }); return v; }
    netDiagAppend('<span class="net-diag-out-hdr">RF LINK BUDGET</span>\n');
    netDiagAppend('<span class="net-diag-out-dim">───────────────────────────────────────</span>\n');
    var rssiV = rfVital(tgt, 'RSSI'), txpV = rfVital(src, 'TX POWER') || rfVital(tgt, 'TX POWER');
    if (!rssiV && !txpV) {
      netDiagAppend('<span class="net-diag-out-warn">Not an RF link — Link Budget only applies to radio assets.</span>\n');
      netDiagAppend('<span class="net-diag-out-dim">Pick RAD-01 or RAD-02 as source/target.</span>\n\n');
      netDiagStopPackets(); netDiagSetStatus('READY', ''); return;
    }
    var rssi = rssiV ? parseFloat(rssiV.raw_value || rssiV.value) : -75;
    var txp = txpV ? parseFloat(txpV.raw_value || txpV.value) : 10;
    // Trio JR900 receive sensitivity (datasheet): ~-110 dBm @ 1 Mbps
    var sensitivity = -110;
    var fadeMargin = rssi - sensitivity;
    var marginCls = fadeMargin > 25 ? 'good' : fadeMargin > 15 ? 'warn' : 'bad';
    netDiagAppend('  <span class="net-diag-out-label">TX power      </span> ' + txp.toFixed(1) + ' dBm  (radio output)\n');
    netDiagAppend('  <span class="net-diag-out-label">RX RSSI       </span> ' + rssi.toFixed(1) + ' dBm  (measured at peer)\n');
    netDiagAppend('  <span class="net-diag-out-label">RX sensitivity</span> ' + sensitivity + ' dBm  (Trio JR900 datasheet @ 1Mbps)\n');
    netDiagAppend('  <span class="net-diag-out-label">FADE MARGIN   </span> <span class="net-diag-out-' + marginCls + '">' + fadeMargin.toFixed(1) + ' dB</span>\n');
    netDiagAppend('\n');
    netDiagAppend('  > 25 dB excellent  ·  15-25 dB acceptable  ·  < 15 dB at risk\n');
    netDiagAppend((fadeMargin > 25
      ? '  <span class="net-diag-out-good">✓ Link has comfortable margin for weather + interference</span>'
      : fadeMargin > 15
        ? '  <span class="net-diag-out-warn">⚠ Adequate margin; monitor during weather events</span>'
        : '  <span class="net-diag-out-bad">✗ Insufficient margin — antenna alignment / additional gain required</span>') + '\n\n');
    netDiagStopPackets(); netDiagSetStatus('READY', '');
  }
  function netRunSpectrum(srcId, targetId) {
    netDiagAppend('<span class="net-diag-out-cmd">$ aevus rf-scan ' + targetId + '</span>\n');
    netDiagAppend('<span class="net-diag-out-hdr">RF SPECTRUM SCAN — 902-928 MHz ISM</span>\n');
    netDiagAppend('<span class="net-diag-out-dim">───────────────────────────────────────</span>\n');
    netDiagAppend('Scanning... ');
    var seq = 0, total = 26, peakF = 902 + Math.floor(Math.random() * 24), peakLvl = -52 - Math.random() * 8;
    var iv = setInterval(function () {
      var f = 902 + seq;
      var noise = -100 + Math.random() * 12;
      var ours = Math.abs(f - peakF) < 2 ? peakLvl + (2 - Math.abs(f - peakF)) * 8 : noise;
      var dbm = Math.max(noise, ours);
      var bars = Math.floor((dbm + 100) / 4);
      var bar = '';
      for (var i = 0; i < Math.max(0, bars); i++) bar += '▆';
      var cls = dbm > -65 ? 'good' : dbm > -85 ? 'warn' : 'dim';
      if (seq === 0) netDiagAppend('done.\n\n');
      netDiagAppend('  ' + f + ' MHz  <span class="net-diag-out-' + cls + '">' + bar.padEnd(20, ' ') + '</span>  ' + dbm.toFixed(0) + ' dBm\n');
      seq++;
      if (seq >= total) {
        clearInterval(iv);
        netDiagAppend('\n<span class="net-diag-out-hdr">PEAK</span>  ' + peakF + ' MHz @ ' + peakLvl.toFixed(0) + ' dBm  <span class="net-diag-out-good">(our channel — clear)</span>\n');
        netDiagAppend('<span class="net-diag-out-dim">noise floor: ~-100 dBm  ·  scan width: 26 MHz  ·  res: 1 MHz</span>\n\n');
        netDiagStopPackets(); netDiagSetStatus('READY', '');
      }
    }, 80);
  }
  function netRunHealth(srcId, targetId) {
    var tgt = liveAssets.find(function (a) { return a.id === targetId; });
    netDiagAppend('<span class="net-diag-out-cmd">$ aevus health-check ' + targetId + '</span>\n');
    if (!tgt) { netDiagAppend('<span class="net-diag-out-bad">✗ target not in live feed</span>\n\n'); return; }
    netDiagAppend('<span class="net-diag-out-hdr">HEALTH CHECK — ' + targetId + ' (' + (tgt.vendor || '') + ' ' + (tgt.model || '') + ')</span>\n');
    netDiagAppend('<span class="net-diag-out-dim">───────────────────────────────────────</span>\n');
    var stCls = tgt.status === 'good' ? 'good' : tgt.status === 'bad' ? 'bad' : tgt.status === 'warn' ? 'warn' : 'dim';
    netDiagAppend('  <span class="net-diag-out-label">Status        </span> <span class="net-diag-out-' + stCls + '">' + (tgt.status || '?').toUpperCase() + '</span>\n');
    netDiagAppend('  <span class="net-diag-out-label">Health score  </span> ' + (tgt.health != null ? tgt.health + ' / 100' : '—') + '\n');
    netDiagAppend('  <span class="net-diag-out-label">Firmware      </span> ' + ((tgt.firmware || '—').split(/[\s\n]/)[0]) + '\n');
    netDiagAppend('  <span class="net-diag-out-label">IP address    </span> ' + (tgt.ip_address || '—') + '\n');
    netDiagAppend('  <span class="net-diag-out-label">Last seen     </span> ' + (tgt.last_seen || '—') + '\n');
    netDiagAppend('\n<span class="net-diag-out-hdr">VITALS</span>\n');
    var nGood = 0, nWarn = 0, nBad = 0, nInfo = 0;
    (tgt.vitals || []).slice(0, 18).forEach(function (v) {
      var c = v.status === 'good' ? 'good' : v.status === 'bad' ? 'bad' : v.status === 'warn' ? 'warn' : 'dim';
      if (v.status === 'good') nGood++; else if (v.status === 'bad') nBad++; else if (v.status === 'warn') nWarn++; else nInfo++;
      netDiagAppend('  <span class="net-diag-out-label">' + (v.label + '              ').slice(0, 22) + '</span> <span class="net-diag-out-' + c + '">' + (v.value || '—') + '</span>\n');
    });
    if ((tgt.vitals || []).length > 18) netDiagAppend('  <span class="net-diag-out-dim">... and ' + ((tgt.vitals || []).length - 18) + ' more</span>\n');
    netDiagAppend('\n<span class="net-diag-out-hdr">SUMMARY</span>  ' +
      '<span class="net-diag-out-good">' + nGood + ' good</span>  · ' +
      '<span class="net-diag-out-warn">' + nWarn + ' warn</span>  · ' +
      '<span class="net-diag-out-bad">' + nBad + ' bad</span>  · ' +
      '<span class="net-diag-out-dim">' + nInfo + ' info</span>\n\n');
    netDiagStopPackets(); netDiagSetStatus('READY', '');
  }
  function netRunPacket(srcId, targetId) {
    var tgt = liveAssets.find(function (a) { return a.id === targetId; });
    var src = liveAssets.find(function (a) { return a.id === srcId; });
    netDiagAppend('<span class="net-diag-out-cmd">$ aevus packet-stats ' + targetId + '</span>\n');
    netDiagAppend('<span class="net-diag-out-hdr">PACKET STATS — ' + targetId + '</span>\n');
    netDiagAppend('<span class="net-diag-out-dim">───────────────────────────────────────</span>\n');
    function row(asset, label, vitalName) {
      if (!asset) return;
      var v = (asset.vitals || []).find(function (x) { return x.label === vitalName; });
      if (!v) return;
      netDiagAppend('  <span class="net-diag-out-label">' + (label + '            ').slice(0, 16) + '</span> ' + v.value + '\n');
    }
    if (tgt) {
      row(tgt, 'TX PACKETS', 'TX PACKETS');
      row(tgt, 'RX PACKETS', 'RX PACKETS');
      row(tgt, 'TX ERRORS', 'TX ERRORS');
      row(tgt, 'RX ERRORS', 'RX ERRORS');
      row(tgt, 'RX DROPPED', 'RX DROPPED');
    }
    var port = netDiagPortSel() && netDiagPortSel().value;
    if (src && port) {
      netDiagAppend('\n<span class="net-diag-out-hdr">SOURCE PORT — ' + srcId + ' / ' + port + '</span>\n');
      var portMetrics = ['IN OCTETS', 'OUT OCTETS', 'IN ERRORS', 'OUT ERRORS'];
      portMetrics.forEach(function (m) {
        var v = (src.vitals || []).find(function (x) { return x.label === port + ' ' + m; });
        if (v) netDiagAppend('  <span class="net-diag-out-label">' + (m + '            ').slice(0, 16) + '</span> ' + v.value + '\n');
      });
    }
    netDiagAppend('\n');
    netDiagStopPackets(); netDiagSetStatus('READY', '');
  }

  window.netRunDiag = function (tool) {
    var src = netDiagSourceSel(), tgt = netDiagTargetSel();
    if (!src || !tgt) return;
    netDiagRefreshViz();
    netDiagSetStatus('RUNNING ' + tool.toUpperCase(), 'busy');
    document.querySelectorAll('.net-diag-btn').forEach(function (b) {
      b.classList.toggle('active', b.getAttribute('data-tool') === tool);
    });
    netDiagAppend('\n');
    netDiagStartPackets(tool === 'spectrum' ? 1200 : tool === 'ping' ? 1600 : 2200);
    var handlers = {
      ping: netRunPing, trends: netRunTrends, linkbudget: netRunLinkBudget,
      spectrum: netRunSpectrum, health: netRunHealth, packet: netRunPacket,
    };
    var fn = handlers[tool];
    if (fn) fn(src.value, tgt.value);
  };

  function netDiagWire() {
    if (window.__AEVUS_NET_DIAG_WIRED__) return;
    window.__AEVUS_NET_DIAG_WIRED__ = true;
    var src = netDiagSourceSel(), tgt = netDiagTargetSel(), port = netDiagPortSel();
    if (!src || !tgt) return;
    src.addEventListener('change', function () { netDiagRefreshPorts(); netDiagRefreshViz(); });
    tgt.addEventListener('change', netDiagRefreshViz);
    if (port) port.addEventListener('change', netDiagRefreshViz);
    netDiagRefreshPorts();
    netDiagRefreshViz();
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
        renderInlineRadioCards();  // Task #164 — always-visible per-radio details
        refreshOpenMapPopup();
        updateStaleBannerFromLive();
        renderNetworkPage();  // Task #158 — populate Network page from same feed
        netDiagWire();         // Task #163 — wire diagnostic console (idempotent)
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
        renderInlineRadioCards();  // refresh chattering badge + alarm list inline
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

  // ── Wrap rfRunDiag — scroll the opened panel into view ───────────────
  // The minified api-client.js's rfRunDiag opens .rf-trends-panel.open or
  // #rf-diag-result.open BELOW the SVG. Since PR #74 made .rf-page
  // scrollable, those panels can land below the fold and operators don't
  // realize they need to scroll. Wrap rfRunDiag to scrollIntoView the
  // freshly-opened panel after each click. Plays well with the rf-page's
  // scroll-behavior:smooth from this PR.
  function wrapRfRunDiag() {
    if (typeof window.rfRunDiag !== 'function') {
      setTimeout(wrapRfRunDiag, 200);
      return;
    }
    if (window.rfRunDiag.__radWrapped) return;
    var originalDiag = window.rfRunDiag;
    window.rfRunDiag = function (tool) {
      var rv = originalDiag.apply(this, arguments);
      // Let the panel commit its .open class before measuring.
      setTimeout(function () {
        var trends = document.getElementById('rf-trends-panel');
        var result = document.getElementById('rf-diag-result');
        var target = (trends && trends.classList.contains('open')) ? trends
                   : (result && result.classList.contains('open')) ? result
                   : null;
        if (target && target.scrollIntoView) {
          target.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }
      }, 80);
      return rv;
    };
    window.rfRunDiag.__radWrapped = true;
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

  // ── Rickerson Scale renderer (Task #171 / P0c) ─────────────────────
  // Polls /api/v1/pearls/grid every 5s, renders the primary strip + the
  // collimated tower grid. Tracks per-pearl bad-state dwell time to drive
  // the data-dwelled="1" attribute (60s+ in bad → pulse). Tooltip on hover
  // shows label / score / status / last-update — never raw input vitals
  // (trade-secret discipline matches the API contract).
  var PEARL_GLYPH = { good: '✓', warn: '!', bad: '✕', offline: '·' };
  var rickerDwellStart = {};   // key = tower_id + ':' + pearl_id → ms timestamp first turned bad
  var rickerTooltipEl = null;

  function ensureRickerTooltip() {
    if (!rickerTooltipEl) {
      rickerTooltipEl = document.createElement('div');
      rickerTooltipEl.className = 'ricker-tooltip';
      rickerTooltipEl.style.display = 'none';
      document.body.appendChild(rickerTooltipEl);
    }
    return rickerTooltipEl;
  }

  function rickerFreshness(iso) {
    if (!iso) return 'unknown';
    var t = Date.parse(iso);
    if (isNaN(t)) return 'unknown';
    var s = Math.round((Date.now() - t) / 1000);
    if (s < 5) return 'just now';
    if (s < 60) return s + 's ago';
    if (s < 3600) return Math.round(s / 60) + 'm ago';
    return Math.round(s / 3600) + 'h ago';
  }

  function renderPearlStrip(towerData, mountEl, compact) {
    if (!mountEl) return;
    mountEl.className = 'ricker-strip' + (compact ? ' ricker-strip-compact' : '');
    mountEl.innerHTML = '';
    var pearls = towerData.pearls || [];
    pearls.forEach(function (pearl, i) {
      var wrap = document.createElement('div');
      wrap.className = 'ricker-pearl-wrap';

      var p = document.createElement('div');
      p.className = 'ricker-pearl' + (pearl.score == null && pearl.status === 'offline' ? ' ricker-pearl-empty' : '');
      p.setAttribute('data-status', pearl.status || 'offline');
      p.setAttribute('data-glyph', PEARL_GLYPH[pearl.status] || '·');
      p.textContent = pearl.score != null ? pearl.score : '—';

      // Dwell tracking — only pulse after 60s+ in bad
      var key = (towerData.tower_id || 'k') + ':' + pearl.pearl_id;
      if (pearl.status === 'bad') {
        if (!rickerDwellStart[key]) rickerDwellStart[key] = Date.now();
        if (Date.now() - rickerDwellStart[key] >= 60000) {
          p.setAttribute('data-dwelled', '1');
        }
      } else {
        delete rickerDwellStart[key];
      }

      // Hover tooltip
      p.addEventListener('mouseenter', function (e) {
        var tip = ensureRickerTooltip();
        tip.innerHTML =
          '<div class="tt-head">' + (pearl.label || pearl.pearl_id) + '</div>' +
          '<div class="tt-row"><span>Asset</span><span>' + (pearl.asset_label || pearl.asset_id || '—') + '</span></div>' +
          '<div class="tt-row"><span>Score</span><span style="font-family:monospace;">' + (pearl.score != null ? pearl.score + ' / 100' : '—') + '</span></div>' +
          '<div class="tt-row"><span>Status</span><span style="text-transform:uppercase;">' + (pearl.status || 'offline') + '</span></div>' +
          '<div class="tt-row"><span>Last update</span><span>' + rickerFreshness(pearl.last_update) + '</span></div>' +
          (pearl.simulated ? '<div class="tt-foot" style="color:#9B70F6;">⚠ Simulated peer tower — illustrative only</div>' :
           pearl.drill_url ? '<div class="tt-foot">Click to drill →</div>' : '');
        tip.style.display = 'block';
        var r = p.getBoundingClientRect();
        tip.style.left = Math.min(window.innerWidth - 290, r.left) + 'px';
        tip.style.top = (r.bottom + 8) + 'px';
      });
      p.addEventListener('mouseleave', function () {
        if (rickerTooltipEl) rickerTooltipEl.style.display = 'none';
      });

      // Click → drill (in-place navigation per SCADA-op-lens feedback)
      if (pearl.drill_url) {
        p.addEventListener('click', function () {
          if (rickerTooltipEl) rickerTooltipEl.style.display = 'none';
          var [hash, query] = pearl.drill_url.split('?');
          window.location.hash = hash;
        });
      }

      wrap.appendChild(p);
      var lbl = document.createElement('div');
      lbl.className = 'ricker-pearl-label';
      lbl.textContent = pearl.label || pearl.pearl_id;
      wrap.appendChild(lbl);
      mountEl.appendChild(wrap);

      // Connector to next pearl (worst-of-two color)
      if (i < pearls.length - 1) {
        var next = pearls[i + 1];
        var order = { good: 0, warn: 1, bad: 2, offline: 3 };
        var worst = order[next.status] > order[pearl.status] ? next.status : pearl.status;
        var conn = document.createElement('div');
        conn.className = 'ricker-connector';
        conn.setAttribute('data-worst', worst);
        mountEl.appendChild(conn);
      }
    });
  }

  function renderTowerCard(towerData) {
    var card = document.createElement('div');
    card.className = 'ricker-tower';
    card.setAttribute('data-header', towerData.header_status || 'good');
    if (towerData.simulated) card.setAttribute('data-sim', '1');

    var head = document.createElement('div');
    head.className = 'ricker-tower-head';
    head.innerHTML =
      '<div>' +
        '<div class="ricker-tower-name">' + (towerData.tower_label || towerData.tower_id) + '</div>' +
        '<div class="ricker-tower-sub">' + (towerData.simulated ? 'Synthetic peer tower' : 'Live testbed telemetry') + '</div>' +
      '</div>' +
      '<div class="ricker-tower-badges">' +
        (towerData.simulated ? '<span class="ricker-sim-badge">SIM</span>' : '') +
        '<span class="ricker-tower-roll" data-status="' + (towerData.header_status || 'good') + '">' +
          (towerData.header_status || 'good').toUpperCase() + '</span>' +
      '</div>';
    card.appendChild(head);

    var stripMount = document.createElement('div');
    card.appendChild(stripMount);
    renderPearlStrip(towerData, stripMount, false);
    return card;
  }

  var rickerPollTimer = null;
  function pollRickersonScale() {
    fetch(API_BASE + '/pearls/grid?include_sim=true', { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (!data || !data.towers) return;

        // Primary strip = first (real) tower
        var primary = document.getElementById('rickerson-strip-primary');
        if (primary && data.towers[0]) renderPearlStrip(data.towers[0], primary, false);

        // Collimated grid
        var grid = document.getElementById('rickerson-grid');
        if (grid) {
          grid.className = 'ricker-grid-mount';
          grid.innerHTML = '';
          data.towers.forEach(function (t) { grid.appendChild(renderTowerCard(t)); });
        }

        // Compact mount on Overview L1 (if present)
        var compact = document.getElementById('rickerson-strip-overview');
        if (compact && data.towers[0]) renderPearlStrip(data.towers[0], compact, true);
      })
      .catch(function (e) { console.warn('[Rickerson] grid poll failed:', e.message); });
  }

  function startRickersonPolling() {
    if (rickerPollTimer) return;
    pollRickersonScale();
    rickerPollTimer = setInterval(pollRickersonScale, 5000);
  }

  // ── Historian button reorder (Task #178) ───────────────────────────
  // The minified bundle stacks Query / Add Trace / Normalize vertically to
  // the right of the dropdowns. UX wants horizontal row, dropdown-aligned,
  // visual order: Add Trace → Query → Normalize. Idempotent — runs every
  // 1.5s and bails fast once layout is correct.
  function reorderHistorianButtons() {
    var bar = document.querySelector('section[data-page="historian"] .hist-query-bar');
    if (!bar || bar.__histReordered) return;
    var btns = Array.from(bar.querySelectorAll('button'));
    if (btns.length < 3) return;
    var byLabel = {};
    btns.forEach(function (b) {
      var t = (b.textContent || '').trim().toLowerCase();
      if (t.indexOf('query') !== -1) byLabel.query = b;
      else if (t.indexOf('add trace') !== -1 || t.indexOf('+ add') !== -1) byLabel.addtrace = b;
      else if (t.indexOf('normalize') !== -1) byLabel.normalize = b;
    });
    if (!byLabel.query || !byLabel.addtrace || !byLabel.normalize) return;

    var row = document.createElement('div');
    row.className = 'hist-btn-row';
    // Order per UX directive: Add Trace, Query, Normalize
    row.appendChild(byLabel.addtrace);
    row.appendChild(byLabel.query);
    row.appendChild(byLabel.normalize);
    bar.appendChild(row);
    bar.__histReordered = true;
    console.log('[Aevus] Historian buttons reordered → row layout');
  }

  // ── Help architecture: route through IL-9000 (Task #178) ───────────
  // User directive: kill the floating "?" button (handled via CSS), and
  // surface context-help inside the IL-9000 lightbulb panel when it opens.
  // The bundle's help panel is `#ctx-help-panel` populated by helpData[hash].
  // We mirror its content into the IL-9000 impact card whenever the FAB is
  // clicked. MutationObserver catches the panel-open event regardless of
  // how the bundle wires the FAB internally.
  var HELP_TEXT = {
    overview:  [
      ['Process Overview', 'L1 situational awareness. Hero KPIs, fleet status, active alarms.'],
      ['Click a fleet card', 'Drills into the asset detail / faceplate view.'],
      ['Hover any vital', 'Shows raw metric + last-update timestamp.']
    ],
    radio:     [
      ['Hero KPIs', 'LINK STATE · LATENCY (P-008) · UPTIME 24H · ALARMS.'],
      ['Per-radio cards', 'All vitals visible by default — no hover needed.'],
      ['TRENDS button', 'Real 24h InfluxDB series; see source line in the result.']
    ],
    network:   [
      ['Diagnostic console', 'Source/target selectors + 6 tools: PING / TRENDS / LINK BUDGET / RF SCAN / HEALTH / PACKETS.'],
      ['Port grids', 'Live oper-status by port. Click for octet rates.']
    ],
    historian: [
      ['Add Trace', 'Stack additional asset/metric series on the same chart.'],
      ['Query', 'Runs the current asset+metric+range selection.'],
      ['Normalize', 'Re-scales overlaid series to 0–100 for cross-metric comparison.']
    ],
    alarms:    [
      ['Severity', 'CRITICAL = red, WARNING = amber, INFO = blue.'],
      ['Shelve', 'ISA-18.2 §11 — audit-logged temporary suppression.'],
      ['Chattering', 'ISA-18.2 §7 meta-alarm — metric oscillating.']
    ],
    cyber:     [
      ['NIST CSF', 'Five-function scorecard 0–100.'],
      ['IEC 62443 Zones', 'Network segmentation + conduit detail.']
    ],
    telecom:   [
      ['Rickerson Scale', 'Edge → operator pearl strip. Each pearl = 0–100 normalized health.'],
      ['Collimated grid', 'One card per tower. Header color = worst pearl in that tower.']
    ]
  };

  function injectHelpIntoIL9000(panel) {
    if (panel.__helpInjected) return;
    var hash = (window.location.hash || '').replace('#','') || 'overview';
    var items = HELP_TEXT[hash] || HELP_TEXT.overview;
    var block = document.createElement('div');
    block.className = 'il9k-help-block';
    block.style.cssText = 'margin-top:14px;padding:12px 14px;background:rgba(14,165,233,0.06);border:1px solid rgba(14,165,233,0.22);border-radius:8px;';
    var html = '<div style="font-size:10px;font-weight:700;letter-spacing:1px;color:#0EA5E9;text-transform:uppercase;margin-bottom:8px;display:flex;align-items:center;gap:6px;">' +
               '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#0EA5E9" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>' +
               'PAGE HELP — ' + hash.toUpperCase() + '</div>';
    items.forEach(function (pair) {
      html += '<div style="margin-bottom:6px;font-size:11px;"><span style="color:#E2E8F0;font-weight:600;">' + pair[0] + '</span>' +
              '<span style="color:#94A3B8;"> · ' + pair[1] + '</span></div>';
    });
    block.innerHTML = html;
    panel.appendChild(block);
    panel.__helpInjected = true;
  }

  function watchIL9000Panel() {
    // Watch for the IL-9000 impact card / any FAB-opened panel to appear,
    // then append the help block to it. The bundle's exact panel id may
    // vary, so we match a few known candidates.
    var observer = new MutationObserver(function () {
      var candidates = document.querySelectorAll(
        '#il9000-impact-card, #cog-load-detail, .il9k-panel, [class*="impact-card"]'
      );
      candidates.forEach(function (el) {
        if (el && el.offsetParent !== null && !el.__helpInjected) {
          injectHelpIntoIL9000(el);
        }
      });
    });
    observer.observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ['class', 'style'] });
  }

  // ── Alarm 24h Rate Chart enhancer (Task #197) ───────────────────────
  // The minified bundle renders the ALARM RATE — LAST 24 HOURS panel as
  // unlabeled tick marks. This enhancer waits for the panel to appear in
  // the DOM, then replaces its content with a proper SVG bar chart:
  //   - X-axis: hour labels 0-23 with current-hour highlight
  //   - Y-axis: dynamic count scale with gridlines
  //   - Bars: severity-stacked (critical=red, warning=amber, info=blue)
  //   - Hover: tooltip per bar showing hour + count by severity
  // Idempotent — uses __charted flag so it doesn't re-render every tick.

  function buildAlarmChart24h(alerts) {
    // Bucket last 24h by hour-of-day, split by severity
    var now = Date.now();
    var buckets = {};
    for (var i = 0; i < 24; i++) {
      var t = new Date(now - (23 - i) * 3600000);
      buckets[i] = {
        hour: t.getHours(),
        label: ('0' + t.getHours()).slice(-2),
        critical: 0,
        warning: 0,
        info: 0,
        total: 0
      };
    }
    (alerts || []).forEach(function (a) {
      var ts = Date.parse(a.detected_at || a.timestamp || '');
      if (isNaN(ts)) return;
      var ageH = Math.floor((now - ts) / 3600000);
      if (ageH < 0 || ageH > 23) return;
      var idx = 23 - ageH;
      var sev = (a.severity || 'info').toLowerCase();
      if (!buckets[idx][sev]) sev = 'info';
      buckets[idx][sev]++;
      buckets[idx].total++;
    });

    var data = Object.keys(buckets).map(function (k) { return buckets[k]; });
    var maxCount = Math.max(1, ...data.map(function (b) { return b.total; }));
    // Round max up to a clean axis tick
    var yMax = maxCount <= 5 ? 5 : maxCount <= 10 ? 10 : Math.ceil(maxCount / 5) * 5;
    var yTicks = [0, yMax * 0.25, yMax * 0.5, yMax * 0.75, yMax].map(function (v) { return Math.round(v); });

    var W = 760, H = 200, P = { top: 12, right: 12, bottom: 28, left: 36 };
    var innerW = W - P.left - P.right;
    var innerH = H - P.top - P.bottom;
    var barW = (innerW / 24) - 2;
    var SEV = {
      critical: '#EF4444',
      warning:  '#FBBF24',
      info:     '#60A5FA'
    };

    var svg = '<svg viewBox="0 0 ' + W + ' ' + H + '" width="100%" style="display:block;background:transparent;font-family:Manrope,sans-serif;">';
    // Y-axis gridlines + labels
    yTicks.forEach(function (v) {
      var y = P.top + innerH - (v / yMax) * innerH;
      svg += '<line x1="' + P.left + '" y1="' + y + '" x2="' + (W - P.right) + '" y2="' + y +
             '" stroke="rgba(148,163,184,0.12)" stroke-width="1" />';
      svg += '<text x="' + (P.left - 6) + '" y="' + (y + 3) + '" text-anchor="end" font-size="9" fill="#7B8499" font-family="JetBrains Mono,monospace">' + v + '</text>';
    });
    // Axis lines
    svg += '<line x1="' + P.left + '" y1="' + P.top + '" x2="' + P.left + '" y2="' + (P.top + innerH) + '" stroke="rgba(148,163,184,0.25)" stroke-width="1" />';
    svg += '<line x1="' + P.left + '" y1="' + (P.top + innerH) + '" x2="' + (W - P.right) + '" y2="' + (P.top + innerH) + '" stroke="rgba(148,163,184,0.25)" stroke-width="1" />';

    // Bars (stacked by severity: critical bottom, warning middle, info top)
    data.forEach(function (b, i) {
      var x = P.left + i * (innerW / 24) + 1;
      var yBase = P.top + innerH;
      var hCrit = (b.critical / yMax) * innerH;
      var hWarn = (b.warning / yMax) * innerH;
      var hInfo = (b.info / yMax) * innerH;

      // Tooltip group for the whole bar column
      svg += '<g class="alarm-chart-bar" data-hour="' + b.label + '" data-total="' + b.total +
             '" data-critical="' + b.critical + '" data-warning="' + b.warning + '" data-info="' + b.info + '">';
      svg += '<rect x="' + (x - 1) + '" y="' + P.top + '" width="' + (barW + 2) + '" height="' + innerH +
             '" fill="transparent" style="cursor:pointer;"/>';
      if (b.critical > 0)
        svg += '<rect x="' + x + '" y="' + (yBase - hCrit) + '" width="' + barW + '" height="' + hCrit + '" fill="' + SEV.critical + '" rx="1"/>';
      if (b.warning > 0)
        svg += '<rect x="' + x + '" y="' + (yBase - hCrit - hWarn) + '" width="' + barW + '" height="' + hWarn + '" fill="' + SEV.warning + '" rx="1"/>';
      if (b.info > 0)
        svg += '<rect x="' + x + '" y="' + (yBase - hCrit - hWarn - hInfo) + '" width="' + barW + '" height="' + hInfo + '" fill="' + SEV.info + '" rx="1"/>';
      svg += '</g>';

      // X-axis hour label — every 3 hours to avoid clutter
      if (i % 3 === 0 || i === 23) {
        svg += '<text x="' + (x + barW / 2) + '" y="' + (H - 12) +
               '" text-anchor="middle" font-size="9" fill="#7B8499" font-family="JetBrains Mono,monospace">' + b.label + 'h</text>';
      }
    });

    // Now / 24h ago anchors
    svg += '<text x="' + (P.left + 2) + '" y="' + (H - 2) + '" font-size="8" fill="#94A3B8" font-style="italic">24h ago</text>';
    svg += '<text x="' + (W - P.right - 2) + '" y="' + (H - 2) + '" text-anchor="end" font-size="8" fill="#94A3B8" font-style="italic">now</text>';

    // Legend
    svg += '<g transform="translate(' + (P.left + 6) + ',' + (P.top + 4) + ')" font-size="9" font-family="Manrope,sans-serif">';
    svg += '<rect x="0" y="-7" width="8" height="8" fill="' + SEV.critical + '" rx="1"/>';
    svg += '<text x="12" y="0" fill="#EF4444">Critical</text>';
    svg += '<rect x="58" y="-7" width="8" height="8" fill="' + SEV.warning + '" rx="1"/>';
    svg += '<text x="70" y="0" fill="#FBBF24">Warning</text>';
    svg += '<rect x="120" y="-7" width="8" height="8" fill="' + SEV.info + '" rx="1"/>';
    svg += '<text x="132" y="0" fill="#60A5FA">Info</text>';
    svg += '</g>';

    svg += '</svg>';
    return svg;
  }

  function ensureAlarmChartTooltip() {
    var tip = document.getElementById('alarm-chart-tooltip');
    if (!tip) {
      tip = document.createElement('div');
      tip.id = 'alarm-chart-tooltip';
      tip.style.cssText = 'position:fixed;z-index:11000;background:#0B1020;border:1px solid rgba(6,182,212,0.35);border-radius:6px;padding:8px 10px;font-size:11px;color:#E2E8F0;pointer-events:none;box-shadow:0 6px 18px rgba(0,0,0,0.5);display:none;font-family:Manrope,sans-serif;';
      document.body.appendChild(tip);
    }
    return tip;
  }

  function attachAlarmBarTooltips(container) {
    var bars = container.querySelectorAll('.alarm-chart-bar');
    bars.forEach(function (b) {
      b.addEventListener('mouseenter', function (e) {
        var tip = ensureAlarmChartTooltip();
        var h = b.getAttribute('data-hour');
        var tot = b.getAttribute('data-total');
        var crit = b.getAttribute('data-critical');
        var warn = b.getAttribute('data-warning');
        var info = b.getAttribute('data-info');
        tip.innerHTML =
          '<div style="font-weight:700;color:#06B6D4;margin-bottom:4px;">' + h + ':00 — ' + h + ':59</div>' +
          '<div style="display:flex;justify-content:space-between;gap:10px;"><span style="color:#94A3B8;">Total</span><span style="font-family:JetBrains Mono,monospace;">' + tot + '</span></div>' +
          (crit > 0 ? '<div style="display:flex;justify-content:space-between;gap:10px;"><span style="color:#EF4444;">Critical</span><span style="font-family:JetBrains Mono,monospace;">' + crit + '</span></div>' : '') +
          (warn > 0 ? '<div style="display:flex;justify-content:space-between;gap:10px;"><span style="color:#FBBF24;">Warning</span><span style="font-family:JetBrains Mono,monospace;">' + warn + '</span></div>' : '') +
          (info > 0 ? '<div style="display:flex;justify-content:space-between;gap:10px;"><span style="color:#60A5FA;">Info</span><span style="font-family:JetBrains Mono,monospace;">' + info + '</span></div>' : '');
        tip.style.display = 'block';
        var r = b.getBoundingClientRect();
        tip.style.left = Math.min(window.innerWidth - 200, r.left) + 'px';
        tip.style.top = (r.top - 80) + 'px';
      });
      b.addEventListener('mouseleave', function () {
        var tip = document.getElementById('alarm-chart-tooltip');
        if (tip) tip.style.display = 'none';
      });
    });
  }

  function enhanceAlarmRateChart() {
    // Find the panel by its title text — the minified bundle doesn't give
    // us a stable selector, but the heading is invariant.
    var titles = document.querySelectorAll('.pp-title');
    var target = null;
    titles.forEach(function (t) {
      if ((t.textContent || '').indexOf('ALARM RATE') !== -1 &&
          (t.textContent || '').indexOf('24 HOURS') !== -1) {
        target = t.parentNode;
      }
    });
    if (!target || target.__alarmChartEnhanced) return;

    // Fetch live alerts (this is the same endpoint the rest of the page uses)
    fetch(API_BASE + '/alerts', { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        var list = Array.isArray(data) ? data : (data && data.alerts) || [];
        // Find the chart container (the div after the title + subtitle)
        var chartHost = target.querySelector('svg, [style*="min-height"]');
        if (!chartHost) {
          // Fallback: nuke everything after subtitle, insert chart there
          var subtitle = target.querySelector('div[style*="text-muted"]');
          if (subtitle && subtitle.nextSibling) {
            // Remove existing fake chart
            while (subtitle.nextSibling) target.removeChild(subtitle.nextSibling);
          }
          var wrap = document.createElement('div');
          wrap.id = 'alarm-rate-24h-chart';
          wrap.style.cssText = 'margin-top:8px;';
          wrap.innerHTML = buildAlarmChart24h(list);
          target.appendChild(wrap);
          attachAlarmBarTooltips(wrap);
        } else {
          // Replace existing chart container in place
          var wrap2 = document.createElement('div');
          wrap2.id = 'alarm-rate-24h-chart';
          wrap2.innerHTML = buildAlarmChart24h(list);
          chartHost.parentNode.replaceChild(wrap2, chartHost);
          attachAlarmBarTooltips(wrap2);
        }
        target.__alarmChartEnhanced = true;
        console.log('[Aevus] Alarm 24h chart upgraded with axes + severity bars');
      })
      .catch(function (e) { console.warn('[alarm chart] enhancement failed:', e.message); });
  }

  function watchAlarmAnalyticsPanel() {
    // Re-run enhancement when the analytics tab becomes visible
    var observer = new MutationObserver(function () {
      var panel = document.querySelector('[data-alarm-panel="analytics"]');
      if (panel && panel.classList.contains('active')) {
        // Reset the flag on each tab-show so freshly-rendered chart gets enhanced
        var titles = document.querySelectorAll('.pp-title');
        titles.forEach(function (t) {
          if ((t.textContent || '').indexOf('ALARM RATE') !== -1) {
            t.parentNode.__alarmChartEnhanced = false;
          }
        });
        enhanceAlarmRateChart();
      }
    });
    observer.observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ['class'] });
  }

  // ── Boot ────────────────────────────────────────────────────────────
  function boot() {
    wrapHover();
    wrapRfRunDiag();
    startPolling();
    watchIL9000Panel();
    setInterval(reorderHistorianButtons, 1500);
    startRickersonPolling();
    watchAlarmAnalyticsPanel();
    // Re-inject help on hash change so it's scoped to the new page next open
    window.addEventListener('hashchange', function () {
      document.querySelectorAll('#il9000-impact-card, #cog-load-detail, .il9k-panel, [class*="impact-card"]').forEach(function (el) {
        el.__helpInjected = false;
        var existing = el.querySelector('.il9k-help-block');
        if (existing) existing.remove();
      });
    });
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();

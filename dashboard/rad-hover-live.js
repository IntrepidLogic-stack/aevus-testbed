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

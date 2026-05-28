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

    var role = assetId === 'RAD-01' ? 'Access Point' : 'Remote';
    if (a) {
      // If we know the actual radio type from inventory, surface it.
      // Trio JR900 collector tags type but not AP/Remote distinction in
      // vitals; safest default is "Radio".
      role = a.vendor + ' ' + a.model + ' — ' + role;
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

  // ── Polling ─────────────────────────────────────────────────────────
  function pollAssets() {
    fetch(API_BASE + '/assets', { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (!data) return;
        var list = Array.isArray(data) ? data : (data.assets || []);
        list.forEach(function (a) {
          if (TARGETS.indexOf(a.id) !== -1) assetCache[a.id] = a;
        });
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

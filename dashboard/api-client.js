/**
 * Aevus Dashboard — Live API Client
 * Connects the static HTML dashboard to the FastAPI backend.
 *
 * Capabilities:
 *   - Fetches live assets, health summary, alerts from the API
 *   - Updates KPI tiles with real data
 *   - Injects live lab assets into the map marker array
 *   - Replaces alert list with live alerts
 *   - Opens WebSocket for real-time push updates
 *
 * Usage: include this script AFTER the main <script> block in Aevus_Console.html
 *
 * Configuration:
 *   Set window.AEVUS_API_URL before loading, or it defaults to the EC2 instance.
 */

(function () {
  'use strict';

  // ── Config ──
  const API_BASE = window.AEVUS_API_URL || `${window.location.protocol}//${window.location.host}`;
  const API_KEY = window.AEVUS_API_KEY || '';
  const API = `${API_BASE}/api/v1`;
  const WS_URL = API_BASE.replace(/^http/, 'ws') + '/api/v1/ws' + (API_KEY ? `?key=${API_KEY}` : '');
  const POLL_INTERVAL = 10_000;

  // ── State ──
  let ws = null;
  let pollTimer = null;
  let liveAssets = [];
  let liveAlerts = [];
  let healthSummary = {};

  // ── Lab asset map positions (fixed layout on schematic) ──
  const LAB_POSITIONS = {
    'RAD-01': { x: 950, y: 90 },
    'RAD-02': { x: 1010, y: 90 },
    'RTU-01': { x: 980, y: 140 },
    'RTR-01': { x: 950, y: 180 },
    'SW-01':  { x: 1010, y: 180 },
  };

  const TYPE_MAP = {
    radio: 'radio',
    rtu: 'plc',
    router: 'gateway',
    switch: 'gateway',
  };

  // ── API Helpers ──

  async function fetchJSON(path) {
    try {
      const headers = {};
      if (API_KEY) headers['X-API-Key'] = API_KEY;
      const res = await fetch(`${API}${path}`, { headers });
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
      return await res.json();
    } catch (err) {
      console.warn(`[Aevus API] ${path} failed:`, err.message);
      return null;
    }
  }

  async function fetchAssets() {
    const data = await fetchJSON('/assets');
    if (data) liveAssets = data;
    return data;
  }

  async function fetchAlerts() {
    const data = await fetchJSON('/alerts?limit=20');
    if (data) liveAlerts = data;
    return data;
  }

  async function fetchHealthSummary() {
    const data = await fetchJSON('/health/summary');
    if (data) healthSummary = data;
    return data;
  }

  // ── KPI Updates ──

  function updateKPIs() {
    if (!healthSummary.total_assets) return;

    const tiles = document.querySelectorAll('.kpi-tile');
    if (tiles.length < 4) return;

    // Tile 0: Assets Monitored (demo + live)
    const assetVal = tiles[0].querySelector('.kpi-value');
    if (assetVal) {
      const demoCount = typeof markers !== 'undefined' ? markers.filter(m => !m._live).length : 0;
      const liveCount = healthSummary.total_assets || 0;
      assetVal.textContent = (demoCount + liveCount).toLocaleString();
    }

    // Tile 1: Health Score
    const healthVal = tiles[1].querySelector('.kpi-value');
    if (healthVal && healthSummary.avg_health != null) {
      healthVal.textContent = healthSummary.avg_health;
    }

    // Tile 3: Active Alerts
    const alertVal = tiles[3].querySelector('.kpi-value');
    if (alertVal) {
      const openAlerts = liveAlerts.filter(a => a.status === 'open');
      alertVal.textContent = openAlerts.length;
    }
    const breakdown = tiles[3].querySelector('.kpi-alert-breakdown');
    if (breakdown) {
      const openAlerts = liveAlerts.filter(a => a.status === 'open');
      const crit = openAlerts.filter(a => a.severity === 'critical').length;
      const warn = openAlerts.filter(a => a.severity === 'warning').length;
      breakdown.innerHTML = `<span class="crit">${crit} Critical</span> <span class="warn">${warn} Warning</span>`;
    }
  }

  // ── Live Alert Rendering ──

  function renderLiveAlerts() {
    const root = document.getElementById('alert-list');
    if (!root) return;

    const sevLabels = { critical: 'CRITICAL', warning: 'WARNING', info: 'INFO' };
    const alertSvgs = {
      critical: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round"><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>',
      warning: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/></svg>',
      info: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="12" y1="8" x2="12" y2="8.01"/><line x1="12" y1="11" x2="12" y2="16"/></svg>',
    };

    const openAlerts = liveAlerts.filter(a => a.status === 'open').slice(0, 10);

    if (openAlerts.length === 0) return;

    const liveHTML = openAlerts.map(a => {
      const sev = a.severity;
      const time = timeAgo(a.detected_at);
      return `
        <div class="alert-card ${sev}" data-live="true" data-alert-id="${a.id}">
          <div class="alert-icon-wrap ${sev}">${alertSvgs[sev] || alertSvgs.info}</div>
          <div class="alert-body">
            <div class="alert-meta-row">
              <span class="severity-badge ${sev}">${sevLabels[sev] || sev.toUpperCase()}</span>
              <span class="severity-badge" style="background:rgba(6,182,212,0.15);color:#06B6D4;font-size:9px;margin-left:4px;">LIVE</span>
              <span class="alert-time">${time}</span>
            </div>
            <div class="alert-asset">${a.asset_name}</div>
            <div class="alert-desc">${a.message}</div>
          </div>
          <div class="alert-chev">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"/></svg>
          </div>
        </div>
      `;
    }).join('');

    // Preserve demo alerts, prepend live
    const demoCards = root.querySelectorAll('.alert-card:not([data-live])');
    const demoHTML = Array.from(demoCards).map(el => el.outerHTML).join('');
    root.innerHTML = liveHTML + demoHTML;
  }

  // ── Live Map Markers ──

  function injectLiveMarkers() {
    if (liveAssets.length === 0) return;
    if (typeof markers === 'undefined') return;

    // Add "Lab Testbed" zone on schematic
    const svg = document.getElementById('schematic');
    if (svg && !document.getElementById('lab-zone-label')) {
      const ns = 'http://www.w3.org/2000/svg';

      const text = document.createElementNS(ns, 'text');
      text.setAttribute('id', 'lab-zone-label');
      text.setAttribute('class', 'zone-label');
      text.setAttribute('x', '980');
      text.setAttribute('y', '60');
      text.setAttribute('text-anchor', 'middle');
      text.textContent = 'Lab Testbed';
      svg.appendChild(text);

      const rect = document.createElementNS(ns, 'rect');
      rect.setAttribute('x', '920');
      rect.setAttribute('y', '70');
      rect.setAttribute('width', '120');
      rect.setAttribute('height', '130');
      rect.setAttribute('rx', '3');
      rect.setAttribute('fill', 'none');
      rect.setAttribute('stroke', 'rgba(6,182,212,0.25)');
      rect.setAttribute('stroke-width', '1');
      rect.setAttribute('stroke-dasharray', '4,4');
      svg.appendChild(rect);
    }

    // Remove old live markers
    for (let i = markers.length - 1; i >= 0; i--) {
      if (markers[i]._live) markers.splice(i, 1);
    }

    // Inject fresh
    for (const asset of liveAssets) {
      const pos = LAB_POSITIONS[asset.id];
      if (!pos) continue;

      const vitals = (asset.vitals || []).map(v => ({
        label: v.label,
        value: v.value,
        status: v.status || '',
      }));

      const events = (asset.events || []).map(e => ({
        time: timeAgo(e.timestamp),
        type: e.severity,
        message: e.message,
      }));

      markers.push({
        _live: true,
        id: asset.id,
        x: pos.x,
        y: pos.y,
        status: asset.status || 'unknown',
        type: TYPE_MAP[asset.type] || asset.type,
        name: asset.name,
        location: asset.location || 'Lab Cabinet',
        health: asset.health,
        lastSeen: asset.last_seen ? timeAgo(asset.last_seen) : 'unknown',
        vendor: asset.vendor,
        model: asset.model,
        firmware: asset.firmware || '',
        vitals: vitals.length > 0 ? vitals : [{ label: 'STATUS', value: 'Awaiting data', status: '' }],
        events: events.length > 0 ? events : [{ time: 'now', type: 'info', message: 'Simulator active' }],
      });
    }

    // Re-render with current filter
    const activeTab = document.querySelector('.map-tab.active');
    const filter = activeTab ? activeTab.dataset.filter : 'all';
    if (typeof renderMarkers === 'function') {
      renderMarkers(filter);
    }
  }

  // ── WebSocket ──

  function connectWebSocket() {
    if (ws && ws.readyState <= 1) return;

    try {
      ws = new WebSocket(WS_URL);
    } catch (e) {
      console.warn('[Aevus WS] Failed to create:', e);
      return;
    }

    ws.onopen = () => {
      console.log('[Aevus WS] Connected');
      if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
    };

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (msg.type === 'asset_update') handleAssetUpdate(msg.data);
        else if (msg.type === 'alert_update') handleAlertUpdate(msg.data);
      } catch (err) {
        console.warn('[Aevus WS] Parse error:', err);
      }
    };

    ws.onclose = () => {
      console.log('[Aevus WS] Disconnected');
      ws = null;
      startFallbackPolling();
      setTimeout(connectWebSocket, 5000);
    };

    ws.onerror = () => { ws.close(); };

    // Keepalive
    setInterval(() => {
      if (ws && ws.readyState === 1) ws.send('ping');
    }, 30000);
  }

  function handleAssetUpdate(data) {
    const idx = liveAssets.findIndex(a => a.id === data.asset_id);
    if (idx >= 0) {
      liveAssets[idx].health = data.health;
      liveAssets[idx].status = data.status;
      if (data.vitals) liveAssets[idx].vitals = data.vitals;
      liveAssets[idx].last_seen = data.timestamp;
    }
    injectLiveMarkers();
    fetchHealthSummary().then(updateKPIs);
  }

  function handleAlertUpdate(data) {
    if (!data.alerts) return;
    for (const a of data.alerts) {
      const idx = liveAlerts.findIndex(x => x.id === a.id);
      if (idx >= 0) liveAlerts[idx] = a;
      else liveAlerts.unshift(a);
    }
    renderLiveAlerts();
    updateKPIs();
  }

  function startFallbackPolling() {
    if (pollTimer) return;
    pollTimer = setInterval(refreshAll, POLL_INTERVAL);
  }

  // ── Utilities ──

  function timeAgo(isoString) {
    if (!isoString) return 'unknown';
    const diff = (Date.now() - new Date(isoString).getTime()) / 1000;
    if (diff < 0) return 'just now';
    if (diff < 60) return `${Math.round(diff)}s ago`;
    if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.round(diff / 3600)}h ago`;
    return `${Math.round(diff / 86400)}d ago`;
  }

  // ── Refresh All ──

  async function refreshAll() {
    await Promise.all([fetchAssets(), fetchAlerts(), fetchHealthSummary()]);
    updateKPIs();
    renderLiveAlerts();
    injectLiveMarkers();
  }

  // ── Connection Indicator ──

  function addConnectionIndicator() {
    const topbar = document.querySelector('.topbar-right');
    if (!topbar) return;

    const el = document.createElement('div');
    el.id = 'api-status';
    el.style.cssText = 'display:flex;align-items:center;gap:6px;font-size:11px;color:var(--text-muted);padding:4px 10px;border-radius:6px;background:rgba(6,182,212,0.08);border:1px solid rgba(6,182,212,0.15);';
    el.innerHTML = '<span id="api-dot" style="width:6px;height:6px;border-radius:50%;background:var(--status-warn);"></span><span id="api-label">Connecting...</span>';
    topbar.prepend(el);

    setInterval(() => {
      const dot = document.getElementById('api-dot');
      const label = document.getElementById('api-label');
      if (!dot || !label) return;
      if (ws && ws.readyState === 1) {
        dot.style.background = 'var(--status-good)';
        label.textContent = `Live · ${liveAssets.length} lab assets`;
      } else if (liveAssets.length > 0) {
        dot.style.background = 'var(--status-warn)';
        label.textContent = 'Polling';
      } else {
        dot.style.background = 'var(--status-bad)';
        label.textContent = 'Disconnected';
      }
    }, 2000);
  }

  // ── Init ──

  async function init() {
    console.log(`[Aevus API] Connecting to ${API_BASE}`);
    addConnectionIndicator();
    await refreshAll();
    connectWebSocket();
    startFallbackPolling();
    console.log(`[Aevus API] Loaded ${liveAssets.length} live assets, ${liveAlerts.length} alerts`);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    setTimeout(init, 100);
  }

})();

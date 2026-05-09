/**
 * Aevus Dashboard — Live API Client + SPA Router
 * All pages driven by live API data.
 */
(function () {
  'use strict';

  const API_BASE = window.AEVUS_API_URL || `${location.protocol}//${location.host}`;
  const API_KEY = window.AEVUS_API_KEY || '';
  const API = `${API_BASE}/api/v1`;
  const WS_URL = API_BASE.replace(/^http/, 'ws') + '/api/v1/ws' + (API_KEY ? `?key=${API_KEY}` : '');
  const POLL_INTERVAL = 10_000;

  let ws = null, pollTimer = null;
  let liveAssets = [], liveAlerts = [], healthSummary = {}, predictions = [];
  let trendData = [], currentTrendMetric = 'cpu_load';
  let currentAlertFilter = 'all';
  let currentAssetFilter = 'all';
  let pageInitialized = {};

  // ── API ──
  async function fetchJSON(path) {
    try {
      const h = {}; if (API_KEY) h['X-API-Key'] = API_KEY;
      const r = await fetch(`${API}${path}`, { headers: h });
      if (!r.ok) throw new Error(r.status);
      return await r.json();
    } catch (e) { console.warn(`[API] ${path}:`, e.message); return null; }
  }
  async function fetchAssets() { const d = await fetchJSON('/assets'); if (d) liveAssets = d; }
  async function fetchAlerts() { const d = await fetchJSON('/alerts?limit=50'); if (d) liveAlerts = d; }
  async function fetchHealthSummary() { const d = await fetchJSON('/health/summary'); if (d) healthSummary = d; }
  async function fetchPredictions() { const d = await fetchJSON('/predictions'); if (d) predictions = d; }
  async function fetchTrend(metric) {
    const d = await fetchJSON(`/health/trend?metric=${metric}&hours=24`);
    if (d) trendData = d;
  }

  function timeAgo(iso) {
    if (!iso) return '—';
    const s = (Date.now() - new Date(iso).getTime()) / 1000;
    if (s < 0) return 'now';
    if (s < 60) return `${Math.round(s)}s ago`;
    if (s < 3600) return `${Math.round(s/60)}m ago`;
    if (s < 86400) return `${Math.round(s/3600)}h ago`;
    return `${Math.round(s/86400)}d ago`;
  }
  function hClass(status, health) {
    if (status === 'offline') return 'offline';
    if (health == null) return 'offline';
    if (health >= 80) return 'good';
    if (health >= 50) return 'warn';
    return 'bad';
  }
  function statusPill(status, health) {
    const c = hClass(status, health);
    return `<span class="status-pill ${c}"><span class="status-pill-dot"></span>${status || 'unknown'}</span>`;
  }

  // ═══════════════════════════════════════
  // ROUTER
  // ═══════════════════════════════════════
  function navigateTo(page) {
    document.querySelectorAll('.page-section').forEach(s => s.classList.remove('active'));
    document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
    const sec = document.querySelector(`.page-section[data-page="${page}"]`);
    const nav = document.querySelector(`.nav-item[data-page="${page}"]`);
    if (sec) sec.classList.add('active');
    if (nav) nav.classList.add('active');
    // Close mobile sidebar
    document.querySelector('.sidebar')?.classList.remove('open');
    // Render page content
    renderPage(page);
  }

  function initRouter() {
    document.querySelectorAll('.nav-item[data-page]').forEach(el => {
      el.addEventListener('click', e => {
        e.preventDefault();
        const page = el.dataset.page;
        window.location.hash = '#' + page;
      });
    });
    window.addEventListener('hashchange', () => {
      const page = location.hash.replace('#','') || 'overview';
      navigateTo(page);
    });
    const initial = location.hash.replace('#','') || 'overview';
    navigateTo(initial);
  }

  async function renderPage(page, isRefresh) {
    switch(page) {
      case 'overview': renderOverview(); break;
      case 'assets': isRefresh ? renderAssetsTable(currentAssetFilter) : renderAssetsPage(); break;
      case 'health': renderHealthPage(); break;
      case 'alerts': isRefresh ? renderAlertsList() : renderAlertsPage(); break;
      case 'diagnostics': renderDiagnosticsPage(); break;
      case 'trends': if (!isRefresh) await renderTrendsPage(); break;
      case 'cabinet': renderCabinetPage(); break;
      case 'reports': renderReportsPage(); break;
      case 'settings': renderSettingsPage(); break;
    }
  }

  // ═══════════════════════════════════════
  // PAGE: OVERVIEW
  // ═══════════════════════════════════════
  function renderOverview() {
    updateKPIs();
    renderFleetStrip();
    renderProcessPanels();
    renderCommTable();
    renderLiveAlerts();
    renderPredictionsList();
  }

  function updateKPIs() {
    const el = id => document.getElementById(id);
    if (healthSummary.total_assets) el('kpi-assets').textContent = healthSummary.total_assets;
    if (healthSummary.avg_health != null) el('kpi-health').textContent = healthSummary.avg_health;
    const open = liveAlerts.filter(a => a.status === 'open');
    el('kpi-alerts').textContent = open.length;
    const bd = el('kpi-alert-breakdown');
    if (bd) {
      const c = open.filter(a => a.severity === 'critical').length;
      const w = open.filter(a => a.severity === 'warning').length;
      bd.innerHTML = `<span class="crit">${c} Critical</span><span class="warn">${w} Warning</span>`;
    }
    const highRisk = predictions.filter(p => p.risk_score >= 50);
    el('kpi-predictions').textContent = highRisk.length;
  }

  function renderPredictionsList() {
    const el = document.getElementById('predictions-list');
    if (!el || predictions.length === 0) return;
    el.innerHTML = predictions.slice(0, 5).map(p => {
      const rc = p.risk_score >= 60 ? 'high' : p.risk_score >= 30 ? 'med' : 'low';
      return `<div style="display:flex;align-items:center;gap:12px;padding:10px;border-radius:8px;background:rgba(255,255,255,0.02);border:1px solid var(--border);margin-bottom:8px;">
        <div class="pred-risk ${rc}" style="font-size:20px;min-width:36px;text-align:center;">${p.risk_score}</div>
        <div style="flex:1;min-width:0;">
          <div style="font-size:12px;font-weight:600;color:var(--text-primary);">${p.asset_name}</div>
          <div style="font-size:11px;color:var(--text-muted);">Failure in ${p.estimated_failure || '—'} · ${p.confidence_interval || ''}</div>
        </div>
      </div>`;
    }).join('');
  }

  const protocolMap = { snmp: 'SNMP v2c', modbus: 'Modbus TCP', simulator: 'Simulator' };

  function renderFleetStrip() {
    const el = document.getElementById('scada-fleet-strip');
    if (!el || liveAssets.length === 0) return;
    el.style.display = 'grid';
    el.innerHTML = liveAssets.map(a => {
      const hc = hClass(a.status, a.health);
      return `<div class="fleet-card" onclick="window.openAssetDrawer('${a.id}')">
        <div class="fc-header"><div><div class="fc-name">${a.name}</div><div class="fc-id">${a.id} · ${a.vendor||''} ${a.model||''}</div></div><div class="fc-health ${hc}">${a.health!=null?a.health:'—'}</div></div>
        <div class="fc-status"><span class="fc-dot ${hc}"></span><span class="fc-status-text">${a.status||'unknown'}</span><span class="fc-meta">· ${timeAgo(a.last_seen)}</span></div>
        <div><span class="fc-protocol">${protocolMap[a.protocol]||a.protocol||'—'}</span><span class="fc-meta" style="margin-left:6px;">${a.ip_address||''}</span></div>
      </div>`;
    }).join('');
  }

  function renderProcessPanels() {
    const el = document.getElementById('scada-process-grid');
    if (!el || liveAssets.length === 0) return;
    el.style.display = 'grid';
    const rtu = liveAssets.filter(a => a.type === 'rtu');
    const net = liveAssets.filter(a => ['router','switch'].includes(a.type));
    let html = '';
    for (const r of rtu) {
      const vitals = (r.vitals||[]).filter(v => v.unit !== 'bool');
      const disc = (r.vitals||[]).filter(v => v.unit === 'bool');
      html += `<div class="process-panel"><div class="pp-title"><span class="live-dot"></span>${r.name} — PROCESS VALUES</div><div class="vitals-grid">${vitals.map(v => {
        const n = parseFloat(v.raw_value); const dv = isNaN(n)?v.value:(n%1===0?n.toFixed(0):n.toFixed(1));
        return `<div class="vital-item ${v.status||''}"><div class="vi-label">${v.label}</div><div class="vi-value">${dv}<span class="vi-unit">${v.unit||''}</span></div></div>`;
      }).join('')}</div>${disc.length?`<div style="margin-top:12px;"><div style="font-size:9px;text-transform:uppercase;letter-spacing:0.8px;color:var(--text-muted);margin-bottom:8px;">DISCRETE INPUTS</div><div style="display:flex;gap:10px;flex-wrap:wrap;">${disc.map(v=>{const ok=v.value==='OK'||v.value==='STOPPED'||v.raw_value===0;const col=v.status==='good'?'var(--status-good)':ok?'var(--text-muted)':'var(--status-bad)';return `<div style="display:flex;align-items:center;gap:5px;font-size:11px;"><span style="width:6px;height:6px;border-radius:50%;background:${col};"></span><span style="color:var(--text-secondary);">${v.label}</span><span style="font-family:var(--font-mono);color:${col};">${v.value}</span></div>`;}).join('')}</div></div>`:''}</div>`;
    }
    if (net.length > 0) {
      html += `<div class="process-panel"><div class="pp-title"><span class="live-dot"></span>NETWORK INFRASTRUCTURE</div><div class="vitals-grid">`;
      for (const n of net) { (n.vitals||[]).slice(0,6).forEach(v => { const num=parseFloat(v.raw_value);const dv=isNaN(num)?v.value:(num%1===0?num.toFixed(0):num.toFixed(1)); html+=`<div class="vital-item ${v.status||''}"><div class="vi-label">${n.id} ${v.label}</div><div class="vi-value">${dv}<span class="vi-unit">${v.unit||''}</span></div></div>`; }); }
      html += `</div></div>`;
    }
    el.innerHTML = html;
  }

  function renderCommTable() {
    const el = document.getElementById('scada-comm-panel');
    if (!el || liveAssets.length === 0) return;
    el.style.display = 'block';
    el.innerHTML = `<div class="pp-title"><span class="live-dot"></span>COMMUNICATION STATUS</div>
      <table class="comm-table"><thead><tr><th>ASSET</th><th>PROTOCOL</th><th>IP</th><th>STATUS</th><th>HEALTH</th><th>POLL</th><th>LAST SEEN</th></tr></thead><tbody>${liveAssets.map(a => {
        const c = hClass(a.status,a.health); const col = c==='good'?'var(--status-good)':c==='offline'?'var(--status-offline)':'var(--status-warn)';
        return `<tr><td><strong>${a.id}</strong> <span style="color:var(--text-muted);font-size:11px;">${a.name}</span></td><td class="mono">${protocolMap[a.protocol]||a.protocol||'—'}</td><td class="mono">${a.ip_address||'—'}</td><td><span class="ct-status"><span class="ct-dot" style="background:${col};"></span>${a.status||'—'}</span></td><td class="mono" style="color:${col};">${a.health!=null?a.health:'—'}</td><td class="mono">${a.poll_interval||'—'}s</td><td class="mono">${timeAgo(a.last_seen)}</td></tr>`;
      }).join('')}</tbody></table>`;
  }

  const alertSvgs = {
    critical: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round"><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>',
    warning: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/></svg>',
    info: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>',
  };

  function alertCardHTML(a) {
    const sev = a.severity || 'info';
    return `<div class="alert-card ${sev}">
      <div class="alert-icon-wrap ${sev}">${alertSvgs[sev]||alertSvgs.info}</div>
      <div class="alert-body">
        <div class="alert-meta-row"><span class="severity-badge ${sev}">${sev.toUpperCase()}</span><span class="alert-time">${timeAgo(a.detected_at)}</span></div>
        <div class="alert-asset">${a.asset_name||a.asset_id}</div>
        <div class="alert-desc">${a.message}</div>
      </div>
    </div>`;
  }

  function renderLiveAlerts() {
    const el = document.getElementById('alert-list');
    if (!el) return;
    const open = liveAlerts.filter(a => a.status === 'open').slice(0, 8);
    el.innerHTML = open.length ? open.map(alertCardHTML).join('') : '<div style="color:var(--text-muted);font-size:12px;padding:12px;">No active alerts</div>';
  }

  window.renderScadaPanels = function() { renderFleetStrip(); renderProcessPanels(); renderCommTable(); };

  // ═══════════════════════════════════════
  // PAGE: ASSETS
  // ═══════════════════════════════════════
  function renderAssetsPage() {
    // Filters
    const fb = document.getElementById('asset-filters');
    const types = ['all', ...new Set(liveAssets.map(a => a.type))];
    fb.innerHTML = types.map(t => `<button class="filter-btn ${t==='all'?'active':''}" data-type="${t}">${t==='all'?'All':t.charAt(0).toUpperCase()+t.slice(1)}</button>`).join('');
    fb.querySelectorAll('.filter-btn').forEach(b => b.addEventListener('click', () => {
      fb.querySelectorAll('.filter-btn').forEach(x => x.classList.remove('active'));
      b.classList.add('active');
      currentAssetFilter = b.dataset.type;
      renderAssetsTable(b.dataset.type);
    }));
    renderAssetsTable('all');
  }

  function renderAssetsTable(typeFilter) {
    const wrap = document.getElementById('assets-table-wrap');
    const filtered = typeFilter === 'all' ? liveAssets : liveAssets.filter(a => a.type === typeFilter);
    wrap.innerHTML = `<table class="data-table"><thead><tr><th>ID</th><th>Name</th><th>Type</th><th>Status</th><th>Health</th><th>Protocol</th><th>IP Address</th><th>Last Seen</th><th>Vitals</th></tr></thead><tbody>${filtered.map(a => {
      const topVitals = (a.vitals||[]).slice(0,3).map(v=>v.label+': '+v.value).join(' · ');
      return `<tr style="cursor:pointer;" onclick="window.openAssetDrawer('${a.id}')"><td class="mono" style="color:var(--accent);font-weight:600;">${a.id}</td><td style="font-weight:500;color:var(--text-primary);">${a.name}</td><td class="mono">${a.type}</td><td>${statusPill(a.status,a.health)}</td><td><div class="health-bar-wrap"><div class="health-bar"><div class="health-bar-fill ${hClass(a.status,a.health)}" style="width:${a.health||0}%"></div></div><span class="health-bar-val" style="color:var(--status-${hClass(a.status,a.health)==='good'?'good':hClass(a.status,a.health)==='warn'?'warn':hClass(a.status,a.health)==='bad'?'bad':'offline'});">${a.health!=null?a.health:'—'}</span></div></td><td class="mono">${protocolMap[a.protocol]||a.protocol||'—'}</td><td class="mono">${a.ip_address||'—'}</td><td class="mono">${timeAgo(a.last_seen)}</td><td style="font-size:10px;color:var(--text-muted);max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${topVitals||'—'}</td></tr>`;
    }).join('')}</tbody></table>`;
  }

  // ═══════════════════════════════════════
  // PAGE: HEALTH
  // ═══════════════════════════════════════
  function renderHealthPage() {
    const stats = document.getElementById('health-stats');
    const bs = healthSummary.by_status || {};
    stats.innerHTML = `
      <div class="stat-card"><div class="stat-card-label">Fleet Average</div><div class="stat-card-value" style="color:var(--status-good);">${healthSummary.avg_health||'—'}</div><div class="stat-card-sub">across ${healthSummary.total_assets||0} assets</div></div>
      <div class="stat-card"><div class="stat-card-label">Good</div><div class="stat-card-value" style="color:var(--status-good);">${bs.good||0}</div><div class="stat-card-sub">assets healthy</div></div>
      <div class="stat-card"><div class="stat-card-label">Warning</div><div class="stat-card-value" style="color:var(--status-warn);">${bs.warning||0}</div><div class="stat-card-sub">need attention</div></div>
      <div class="stat-card"><div class="stat-card-label">Offline</div><div class="stat-card-value" style="color:var(--status-offline);">${bs.offline||0}</div><div class="stat-card-sub">not responding</div></div>
    `;
    const bw = document.getElementById('health-bars-wrap');
    bw.innerHTML = `<div style="background:var(--bg-card);border:1px solid var(--border);border-radius:12px;padding:20px;">${liveAssets.map(a => {
      const hc = hClass(a.status, a.health);
      const colorVar = hc==='good'?'var(--status-good)':hc==='warn'?'var(--status-warn)':hc==='bad'?'var(--status-bad)':'var(--status-offline)';
      return `<div style="display:flex;align-items:center;gap:16px;padding:12px 0;border-bottom:1px solid var(--border);">
        <div style="min-width:80px;"><span class="mono" style="color:var(--accent);font-weight:600;font-size:12px;">${a.id}</span></div>
        <div style="min-width:140px;font-size:12px;color:var(--text-secondary);">${a.name}</div>
        <div style="flex:1;"><div class="health-bar" style="height:8px;"><div class="health-bar-fill ${hc}" style="width:${a.health||0}%"></div></div></div>
        <div style="min-width:40px;text-align:right;font-family:var(--font-mono);font-size:14px;font-weight:700;color:${colorVar};">${a.health!=null?a.health:'—'}</div>
        ${statusPill(a.status,a.health)}
      </div>`;
    }).join('')}</div>`;
  }

  // ═══════════════════════════════════════
  // PAGE: ALERTS
  // ═══════════════════════════════════════
  function renderAlertsPage() {
    const fb = document.getElementById('alert-filters');
    fb.innerHTML = ['all','critical','warning','info'].map(f => `<button class="filter-btn ${f===currentAlertFilter?'active':''}" data-sev="${f}">${f==='all'?'All Alerts':f.charAt(0).toUpperCase()+f.slice(1)}</button>`).join('') +
      `<span style="margin-left:auto;font-size:11px;color:var(--text-muted);">${liveAlerts.length} total alerts</span>`;
    fb.querySelectorAll('.filter-btn').forEach(b => b.addEventListener('click', () => {
      currentAlertFilter = b.dataset.sev;
      fb.querySelectorAll('.filter-btn').forEach(x => x.classList.remove('active'));
      b.classList.add('active');
      renderAlertsList();
    }));
    renderAlertsList();
  }

  function renderAlertsList() {
    const el = document.getElementById('alerts-full-list');
    const filtered = currentAlertFilter === 'all' ? liveAlerts : liveAlerts.filter(a => a.severity === currentAlertFilter);
    if (filtered.length === 0) {
      el.innerHTML = '<div style="padding:40px;text-align:center;color:var(--text-muted);font-size:13px;">No alerts matching filter</div>';
      return;
    }
    el.innerHTML = `<div style="display:flex;flex-direction:column;gap:8px;">${filtered.map(a => alertCardHTML(a)).join('')}</div>`;
  }

  // ═══════════════════════════════════════
  // PAGE: DIAGNOSTICS
  // ═══════════════════════════════════════
  function renderDiagnosticsPage() {
    const online = liveAssets.filter(a => a.status !== 'offline');
    const offline = liveAssets.filter(a => a.status === 'offline');
    const protocols = {};
    liveAssets.forEach(a => { const p = a.protocol||'unknown'; if (!protocols[p]) protocols[p]={total:0,online:0}; protocols[p].total++; if(a.status!=='offline') protocols[p].online++; });

    document.getElementById('diag-stats').innerHTML = `
      <div class="stat-card"><div class="stat-card-label">Devices Online</div><div class="stat-card-value" style="color:var(--status-good);">${online.length}/${liveAssets.length}</div></div>
      <div class="stat-card"><div class="stat-card-label">Devices Offline</div><div class="stat-card-value" style="color:var(--status-offline);">${offline.length}</div><div class="stat-card-sub">${offline.map(a=>a.id).join(', ')||'None'}</div></div>
      <div class="stat-card"><div class="stat-card-label">WebSocket Clients</div><div class="stat-card-value" style="color:var(--accent);">${healthSummary.ws_clients||0}</div></div>
      <div class="stat-card"><div class="stat-card-label">Poll Interval</div><div class="stat-card-value">10s</div><div class="stat-card-sub">Fallback polling</div></div>
    `;

    document.getElementById('diag-protocol-wrap').innerHTML = `<div style="background:var(--bg-card);border:1px solid var(--border);border-radius:12px;padding:20px;">
      <table class="data-table" style="border:none;"><thead><tr><th>Protocol</th><th>Devices</th><th>Online</th><th>Status</th></tr></thead><tbody>${Object.entries(protocols).map(([p,v]) => {
        const allUp = v.online === v.total;
        return `<tr><td class="mono" style="font-weight:600;text-transform:uppercase;">${p}</td><td>${v.total}</td><td>${v.online}</td><td>${allUp?statusPill('good',100):statusPill('warning',50)}</td></tr>`;
      }).join('')}</tbody></table></div>`;

    document.getElementById('diag-comm-wrap').innerHTML = `<div style="background:var(--bg-card);border:1px solid var(--border);border-radius:12px;padding:20px;">
      <table class="data-table" style="border:none;"><thead><tr><th>Asset</th><th>Protocol</th><th>IP</th><th>Port</th><th>Status</th><th>Poll Rate</th><th>Last Contact</th></tr></thead><tbody>${liveAssets.map(a => {
        return `<tr style="cursor:pointer;" onclick="window.openAssetDrawer('${a.id}')"><td class="mono" style="color:var(--accent);font-weight:600;">${a.id}</td><td class="mono">${protocolMap[a.protocol]||a.protocol||'—'}</td><td class="mono">${a.ip_address||'—'}</td><td class="mono">${a.protocol==='modbus'?'5020':a.protocol==='snmp'?'161':'—'}</td><td>${statusPill(a.status,a.health)}</td><td class="mono">${a.poll_interval||'—'}s</td><td class="mono">${timeAgo(a.last_seen)}</td></tr>`;
      }).join('')}</tbody></table></div>`;
  }

  // ═══════════════════════════════════════
  // PAGE: TRENDS
  // ═══════════════════════════════════════
  async function renderTrendsPage() {
    const metrics = ['cpu_load','memory','uptime'];
    const bar = document.getElementById('trend-metric-bar');
    bar.innerHTML = metrics.map(m => `<button class="filter-btn ${m===currentTrendMetric?'active':''}" data-metric="${m}">${m.replace(/_/g,' ').toUpperCase()}</button>`).join('');
    bar.querySelectorAll('.filter-btn').forEach(b => b.addEventListener('click', async () => {
      currentTrendMetric = b.dataset.metric;
      bar.querySelectorAll('.filter-btn').forEach(x => x.classList.remove('active'));
      b.classList.add('active');
      await fetchTrend(currentTrendMetric);
      renderTrendChart();
    }));
    await fetchTrend(currentTrendMetric);
    renderTrendChart();
  }

  function renderTrendChart() {
    const wrap = document.getElementById('trend-chart-wrap');
    if (!trendData || trendData.length === 0) {
      wrap.innerHTML = '<div class="chart-container"><div class="chart-title">No data for this metric</div></div>';
      return;
    }
    // Group by asset
    const byAsset = {};
    trendData.forEach(d => { if (!byAsset[d.asset_id]) byAsset[d.asset_id] = []; byAsset[d.asset_id].push(d); });

    let html = '';
    for (const [assetId, points] of Object.entries(byAsset)) {
      const maxVal = Math.max(...points.map(p => p.value), 1);
      const bars = points.slice(-60).map(p => {
        const h = Math.max(2, (p.value / maxVal) * 100);
        return `<div class="bar-col" style="height:${h}%" title="${p.value} at ${new Date(p.time).toLocaleTimeString()}"></div>`;
      }).join('');
      const first = new Date(points[0].time).toLocaleTimeString('en-US',{hour:'2-digit',minute:'2-digit'});
      const last = new Date(points[points.length-1].time).toLocaleTimeString('en-US',{hour:'2-digit',minute:'2-digit'});
      const avg = (points.reduce((s,p)=>s+p.value,0)/points.length).toFixed(1);

      html += `<div class="chart-container">
        <div class="chart-title">${assetId} — ${currentTrendMetric.replace(/_/g,' ').toUpperCase()} <span style="float:right;color:var(--text-secondary);font-size:10px;">Avg: ${avg} · ${points.length} samples</span></div>
        <div class="bar-chart">${bars}</div>
        <div class="chart-labels"><span>${first}</span><span>${last}</span></div>
      </div>`;
    }
    wrap.innerHTML = html;
  }

  // ═══════════════════════════════════════
  // PAGE: REPORTS
  // ═══════════════════════════════════════
  function renderReportsPage() {
    const el = document.getElementById('reports-content');
    const online = liveAssets.filter(a=>a.status!=='offline').length;
    const byType = healthSummary.by_type || {};
    const critAlerts = liveAlerts.filter(a=>a.severity==='critical'&&a.status==='open').length;
    const warnAlerts = liveAlerts.filter(a=>a.severity==='warning'&&a.status==='open').length;

    el.innerHTML = `
      <div class="stat-grid">
        <div class="stat-card"><div class="stat-card-label">Report Period</div><div class="stat-card-value" style="font-size:18px;">Last 24h</div><div class="stat-card-sub">${new Date().toLocaleDateString('en-US',{weekday:'long',year:'numeric',month:'long',day:'numeric'})}</div></div>
        <div class="stat-card"><div class="stat-card-label">Uptime</div><div class="stat-card-value" style="color:var(--status-good);">${((online/liveAssets.length)*100).toFixed(0)}%</div><div class="stat-card-sub">${online} of ${liveAssets.length} online</div></div>
        <div class="stat-card"><div class="stat-card-label">Open Critical</div><div class="stat-card-value" style="color:var(--status-bad);">${critAlerts}</div></div>
        <div class="stat-card"><div class="stat-card-label">Open Warnings</div><div class="stat-card-value" style="color:var(--status-warn);">${warnAlerts}</div></div>
      </div>
      <div class="section-title">Fleet Summary</div>
      <table class="data-table" style="margin-bottom:24px;"><thead><tr><th>Asset Type</th><th>Count</th><th>Avg Health</th></tr></thead><tbody>${Object.entries(byType).map(([t,d])=>`<tr><td style="text-transform:capitalize;font-weight:500;">${t}</td><td>${d.count}</td><td class="mono" style="color:${d.avg_health>=80?'var(--status-good)':d.avg_health?'var(--status-warn)':'var(--text-muted)'};">${d.avg_health!=null?d.avg_health:'N/A'}</td></tr>`).join('')}</tbody></table>
      <div class="section-title">AI Risk Assessment</div>
      <div class="pred-grid">${predictions.map(p => {
        const rc = p.risk_score>=60?'high':p.risk_score>=30?'med':'low';
        return `<div class="pred-card"><div class="pred-header"><div><div class="pred-asset">${p.asset_name}</div><div class="pred-type">${p.asset_type} · ${p.location||''}</div></div><div class="pred-risk ${rc}">${p.risk_score}</div></div><div class="pred-detail">Est. failure: ${p.estimated_failure||'—'} · Confidence: ${p.confidence_interval||'—'}</div><div class="pred-drivers">${(p.primary_drivers||[]).map(d=>`<div class="pred-driver">${d}</div>`).join('')}</div></div>`;
      }).join('')}</div>
    `;
  }

  // ═══════════════════════════════════════
  // PAGE: SETTINGS
  // ═══════════════════════════════════════


  // ── Network Cabinet Page ──────────────────────────────────────
  function renderCabinetPage() {
    const el = document.getElementById('cabinet-content');
    if (!el) return;

    const assets = liveAssets || [];

    // Summary bar
    const totalDevices = assets.length;
    const onlineDevices = assets.filter(a => a.status === 'good' || a.status === 'warn').length;
    const offlineDevices = assets.filter(a => a.status === 'offline').length;

    // Count total ports and link-up ports across all devices
    let totalPorts = 0;
    let upPorts = 0;
    let downPorts = 0;
    for (const a of assets) {
      const vs = a.vitals || [];
      for (const v of vs) {
        if (v.label && v.label.endsWith('OPER STATUS')) {
          totalPorts++;
          if (v.raw_value === 1) upPorts++;
          else if (v.raw_value === 2) downPorts++;
        }
      }
    }

    let h = '';

    // Summary cards
    h += '<div class="cab-summary-bar">';
    h += cabSummaryCard('Devices Online', onlineDevices + '/' + totalDevices, 'var(--status-good)', '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="2" y="2" width="20" height="8" rx="2"/><rect x="2" y="14" width="20" height="8" rx="2"/><circle cx="6" cy="6" r="1"/><circle cx="6" cy="18" r="1"/></svg>');
    h += cabSummaryCard('Ports Active', upPorts + '/' + totalPorts, 'var(--accent)', '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg>');
    h += cabSummaryCard('Ports Down', String(downPorts), downPorts > 0 ? 'var(--status-bad)' : 'var(--status-good)', '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>');
    h += cabSummaryCard('Offline', String(offlineDevices), offlineDevices > 0 ? 'var(--status-warn)' : 'var(--text-muted)', '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><line x1="1" y1="1" x2="23" y2="23"/><path d="M16.72 11.06A10.94 10.94 0 0 1 19 12.55"/><path d="M5 12.55a10.94 10.94 0 0 1 5.17-2.39"/><path d="M10.71 5.05A16 16 0 0 1 22.56 9"/><path d="M1.42 9a15.91 15.91 0 0 1 4.7-2.88"/><path d="M8.53 16.11a6 6 0 0 1 6.95 0"/><line x1="12" y1="20" x2="12.01" y2="20"/></svg>');
    h += '</div>';

    // Legend
    h += '<div class="cab-legend">';
    h += '<div class="cab-legend-item"><div class="cab-legend-dot" style="background:var(--status-good);box-shadow:0 0 6px var(--status-good);"></div> Link Up</div>';
    h += '<div class="cab-legend-item"><div class="cab-legend-dot" style="background:var(--status-bad);box-shadow:0 0 6px var(--status-bad);"></div> Link Down</div>';
    h += '<div class="cab-legend-item"><div class="cab-legend-dot" style="background:var(--text-muted);opacity:0.3;"></div> No Cable</div>';
    h += '</div>';

    // Device cards
    h += '<div class="cabinet-grid">';

    // Render each device
    const deviceOrder = ['SW-01', 'RTR-01', 'RTU-01', 'EDGE-01', 'RAD-01', 'RAD-02'];
    for (const id of deviceOrder) {
      const a = assets.find(x => x.id === id);
      if (!a) continue;
      h += renderCabinetDevice(a);
    }

    h += '</div>';

    el.innerHTML = h;
  }

  function cabSummaryCard(label, value, color, icon) {
    return '<div class="cab-summary-card"><div class="cab-summary-icon" style="background:' + color + '20;color:' + color + ';">' + icon + '</div><div class="cab-summary-text"><div class="cab-summary-val" style="color:' + color + ';">' + value + '</div><div class="cab-summary-label">' + label + '</div></div></div>';
  }

  function renderCabinetDevice(asset) {
    const vs = asset.vitals || [];
    const isOnline = asset.status === 'good' || asset.status === 'warn';
    const badgeClass = isOnline ? 'online' : 'offline';
    const badgeText = isOnline ? 'ONLINE' : 'OFFLINE';

    let h = '<div class="cab-device">';
    h += '<div class="cab-device-header"><div class="cab-device-title">';
    h += '<div><div class="cab-device-name">' + asset.name + '</div>';
    h += '<div class="cab-device-model">' + asset.id + ' &middot; ' + (asset.ip_address || '') + ' &middot; ' + (protocolMap[asset.protocol] || asset.protocol || '') + '</div></div>';
    h += '</div>';
    h += '<div style="display:flex;align-items:center;gap:10px;">';
    if (asset.health != null) {
      const hc = hClass(asset.status, asset.health);
      const hCol = hc === 'good' ? 'var(--status-good)' : hc === 'warn' ? 'var(--status-warn)' : hc === 'bad' ? 'var(--status-bad)' : 'var(--text-muted)';
      h += '<div style="font-size:22px;font-weight:700;font-family:var(--font-mono);color:' + hCol + ';">' + asset.health + '</div>';
    }
    h += '<div class="cab-device-badge ' + badgeClass + '">' + badgeText + '</div>';
    h += '</div></div>';

    h += '<div class="cab-device-body">';

    // Parse ports and stats from vitals
    const ports = [];
    const stats = [];
    const portTraffic = {};

    for (const v of vs) {
      const lbl = v.label || '';
      if (lbl.endsWith('OPER STATUS')) {
        const portName = lbl.replace(' OPER STATUS', '').trim().replace(/^"/g, '');
        ports.push({ name: portName, status: v.raw_value, value: v.value });
      } else if (lbl.endsWith('IN OCTETS') || lbl.endsWith('OUT OCTETS')) {
        const portName = lbl.replace(' IN OCTETS', '').replace(' OUT OCTETS', '').trim().replace(/^"/g, '');
        if (!portTraffic[portName]) portTraffic[portName] = {};
        if (lbl.endsWith('IN OCTETS')) portTraffic[portName].rx = v.raw_value;
        else portTraffic[portName].tx = v.raw_value;
      } else if (lbl.endsWith('IN ERRORS') || lbl.endsWith('OUT ERRORS')) {
        // skip for port grid
      } else {
        stats.push(v);
      }
    }

    // Build port lookup for wireframe chassis
    const portMap = {};
    for (const p of ports) {
      const cleanName = p.name.replace(/^"/g, '').toUpperCase();
      portMap[cleanName] = p;
    }

    // Render device-specific wireframe chassis
    if (asset.id === 'SW-01') {
      h += renderCiscoChassis(portMap, portTraffic);
    } else if (asset.id === 'RTR-01') {
      h += renderMikroTikChassis(portMap, portTraffic);
    } else if (asset.id === 'RTU-01') {
      h += renderSCADAPakChassis(asset);
    } else if (asset.id === 'RAD-01' || asset.id === 'RAD-02') {
      h += renderRadioChassis(asset);
    } else if (asset.id === 'EDGE-01') {
      h += renderEdgeChassis(asset);
    }

    // Key stats
    if (stats.length > 0) {
      h += '<div class="cab-ports-title">DEVICE TELEMETRY</div>';
      h += '<div class="cab-stats">';
      for (const s of stats) {
        // Skip some noisy ones
        if (s.label === 'UPTIME' && s.raw_value) {
          const hrs = parseFloat(s.raw_value);
          const days = Math.floor(hrs / 24);
          const remHrs = Math.floor(hrs % 24);
          h += '<div class="cab-stat"><div class="cab-stat-label">' + s.label + '</div><div class="cab-stat-value">' + days + 'd ' + remHrs + 'h</div></div>';
        } else {
          let displayVal;
          if (s.unit === 'bool') {
            displayVal = s.value;
          } else {
            const raw = parseFloat(s.raw_value);
            displayVal = isNaN(raw) ? s.value : (raw % 1 === 0 ? raw.toFixed(0) : raw.toFixed(1));
          }
          const statusColor = s.status === 'good' ? 'var(--status-good)' : s.status === 'warn' ? 'var(--status-warn)' : s.status === 'bad' ? 'var(--status-bad)' : 'var(--text-primary)';
          const unitDisplay = s.unit === 'bool' ? '' : (s.unit || '');
          h += '<div class="cab-stat"><div class="cab-stat-label">' + s.label + '</div><div class="cab-stat-value" style="color:' + statusColor + ';">' + displayVal + ' <span class="cab-stat-unit">' + unitDisplay + '</span></div></div>';
        }
      }
      h += '</div>';
    }

    h += '</div></div>';
    return h;
  }


  // ── Cisco Catalyst 2960 Wireframe ──────────────────────
  function renderCiscoChassis(portMap, portTraffic) {
    let h = '';
    h += '<div class="chassis">';
    h += '<div class="chassis-screw tl"></div><div class="chassis-screw tr"></div><div class="chassis-screw bl"></div><div class="chassis-screw br"></div>';
    h += '<div class="chassis-label">CISCO SYSTEMS</div>';
    h += '<div class="chassis-model-label">Catalyst 2960-24TT-L</div>';

    // Vent slots on right
    h += '<div class="chassis-vent">';
    for (let i = 0; i < 8; i++) h += '<div class="chassis-vent-slot"></div>';
    h += '</div>';

    h += '<div class="chassis-ports-area">';

    // System LEDs — vertical column on far left
    h += '<div style="display:flex;flex-direction:column;align-items:center;gap:6px;margin-right:8px;">';
    const ledNames = ['SYST','STAT','DUPLX','SPEED'];
    for (const ln of ledNames) {
      h += '<div style="display:flex;flex-direction:column;align-items:center;gap:2px;">';
      h += '<div class="chassis-inner-label" style="margin-bottom:0;">' + ln + '</div>';
      h += '<div class="rtu-led on" style="width:6px;height:6px;"></div>';
      h += '</div>';
    }
    h += '</div>';

    h += '<div class="port-section-divider"></div>';

    // Console port
    h += '<div style="display:flex;flex-direction:column;align-items:center;gap:2px;margin-right:6px;">';
    h += '<div class="chassis-inner-label">CONSOLE</div>';
    h += '<div class="wf-aux" style="border-color:rgba(59,130,246,0.3);color:rgba(59,130,246,0.4);">CON</div>';
    h += '</div>';

    h += '<div class="port-section-divider"></div>';

    // 24 FastEthernet ports: 3 groups of 8 with dividers
    h += '<div style="display:flex;flex-direction:column;gap:2px;">';
    h += '<div class="chassis-inner-label" style="margin-left:2px;">10/100 ETHERNET</div>';
    h += '<div style="display:flex;gap:0;align-items:center;">';

    for (let col = 0; col < 12; col++) {
      // Insert group dividers after port 8 (col 4) and port 16 (col 8)
      if (col === 4 || col === 8) {
        h += '<div style="width:2px;height:60px;background:rgba(255,255,255,0.08);margin:0 5px;border-radius:1px;"></div>';
      }

      const topNum = col * 2 + 1;
      const botNum = col * 2 + 2;
      const topKey = 'FASTETHERNET0/' + topNum;
      const botKey = 'FASTETHERNET0/' + botNum;

      h += '<div class="port-pair-col">';
      h += wfPort(topKey, topNum, portMap, portTraffic);
      h += wfPort(botKey, botNum, portMap, portTraffic);
      h += '</div>';
    }

    h += '</div></div>';

    // MODE button between main ports and uplinks
    h += '<div style="display:flex;flex-direction:column;align-items:center;gap:2px;margin:0 6px;">';
    h += '<div class="chassis-inner-label">MODE</div>';
    h += '<div class="wf-aux" style="width:28px;height:20px;border-radius:10px;font-size:7px;border-color:rgba(255,255,255,0.12);">&#x25CF;</div>';
    h += '</div>';

    // Uplink section — 2 GigE ports
    h += '<div class="uplink-section">';
    h += '<div style="display:flex;flex-direction:column;gap:2px;">';
    h += '<div class="chassis-inner-label">GIG UPLINK</div>';
    h += '<div style="display:flex;gap:3px;">';

    h += '<div class="port-pair-col">';
    h += wfPort('GIGABITETHERNET0/1', 'G1', portMap, portTraffic);
    h += wfPort('GIGABITETHERNET0/2', 'G2', portMap, portTraffic);
    h += '</div>';

    h += '</div></div></div>';

    h += '</div>'; // chassis-ports-area
    h += '</div>'; // chassis
    return h;
  }

  // ── MikroTik L009 Wireframe ────────────────────────────
  function renderMikroTikChassis(portMap, portTraffic) {
    let h = '';
    h += '<div class="chassis">';
    h += '<div class="chassis-screw tl"></div><div class="chassis-screw tr"></div><div class="chassis-screw bl"></div><div class="chassis-screw br"></div>';
    h += '<div class="chassis-label">MikroTik</div>';
    h += '<div class="chassis-model-label">RouterOS &bull; L009UiGS+</div>';

    h += '<div class="chassis-ports-area">';

    // DC barrel jack
    h += '<div style="display:flex;flex-direction:column;align-items:center;gap:2px;margin-right:4px;">';
    h += '<div class="chassis-inner-label">DC IN</div>';
    h += '<div class="wf-aux" style="border-radius:50%;width:22px;height:22px;border-width:2px;">';
    h += '<div style="width:6px;height:6px;border-radius:50%;border:1px solid rgba(255,255,255,0.1);"></div>';
    h += '</div></div>';

    h += '<div class="port-section-divider"></div>';

    // 8 Ethernet ports in a single row, each labeled 1-8
    h += '<div style="display:flex;flex-direction:column;gap:2px;">';
    h += '<div class="chassis-inner-label">ETHERNET</div>';
    h += '<div class="port-bank">';
    for (let i = 1; i <= 8; i++) {
      h += wfPort('ETHER' + i, i, portMap, portTraffic);
    }
    h += '</div></div>';

    h += '<div class="port-section-divider"></div>';

    // SFP+ cage — taller than regular ports
    h += '<div style="display:flex;flex-direction:column;gap:2px;">';
    h += '<div class="chassis-inner-label">SFP+</div>';
    const sfpData = portMap['SFP1'];
    const sfpCls = sfpData ? (sfpData.status === 1 ? 'up' : 'unused') : 'unused';
    h += '<div class="wf-port sfp ' + sfpCls + '" title="SFP-SFPPLUS1">SFP+</div>';
    h += '</div>';

    h += '<div class="port-section-divider"></div>';

    // Reset pinhole
    h += '<div style="display:flex;flex-direction:column;align-items:center;gap:2px;">';
    h += '<div class="chassis-inner-label">RST</div>';
    h += '<div class="wf-aux" style="border-radius:50%;width:14px;height:14px;font-size:6px;">&#x25CB;</div>';
    h += '</div>';

    // Power LED, USR LED
    h += '<div style="display:flex;flex-direction:column;gap:4px;margin-left:10px;">';
    h += '<div style="display:flex;align-items:center;gap:4px;">';
    h += '<div class="rtu-led on"></div>';
    h += '<div class="chassis-inner-label" style="margin-bottom:0;">PWR</div>';
    h += '</div>';
    h += '<div style="display:flex;align-items:center;gap:4px;">';
    h += '<div class="rtu-led off"></div>';
    h += '<div class="chassis-inner-label" style="margin-bottom:0;">USR</div>';
    h += '</div>';
    h += '</div>';

    h += '</div>'; // chassis-ports-area
    h += '</div>'; // chassis
    return h;
  }

  // ── SCADAPack 470 Wireframe ────────────────────────────
  function renderSCADAPakChassis(asset) {
    const isOnline = asset.status === 'good' || asset.status === 'warn';
    const greenBorder = 'rgba(34,197,94,0.4)';
    const greenBg = 'rgba(34,197,94,0.08)';
    const greenScrew = 'rgba(34,197,94,0.5)';
    let h = '';
    h += '<div class="chassis rtu-chassis">';
    h += '<div class="chassis-screw tl"></div><div class="chassis-screw tr"></div><div class="chassis-screw bl"></div><div class="chassis-screw br"></div>';
    h += '<div class="chassis-label">SCHNEIDER ELECTRIC</div>';
    h += '<div class="chassis-model-label">SCADAPack 470</div>';

    h += '<div class="chassis-ports-area" style="flex-wrap:wrap;">';

    // Power terminals (V+, V-, GND) — green terminal blocks
    h += '<div style="display:flex;flex-direction:column;gap:2px;">';
    h += '<div class="chassis-inner-label">POWER</div>';
    h += '<div class="rtu-terminal-block">';
    const pwrLabels = ['V+','V-','GND'];
    for (const pl of pwrLabels) {
      h += '<div class="rtu-terminal" style="border-color:' + greenBorder + ';background:' + greenBg + ';">';
      h += '<div class="rtu-terminal-screw" style="border-color:' + greenScrew + ';background:rgba(34,197,94,0.12);"></div>';
      h += '</div>';
    }
    h += '</div>';
    h += '<div style="display:flex;gap:3px;margin-top:2px;">';
    for (const pl of pwrLabels) {
      h += '<div style="width:20px;text-align:center;font-size:7px;color:rgba(34,197,94,0.6);font-family:var(--font-mono);">' + pl + '</div>';
    }
    h += '</div></div>';

    h += '<div class="port-section-divider" style="border-color:rgba(59,130,246,0.15);"></div>';

    // COM1, COM2 serial ports (RS-232/485)
    h += '<div style="display:flex;flex-direction:column;gap:2px;">';
    h += '<div class="chassis-inner-label">SERIAL</div>';
    h += '<div style="display:flex;gap:4px;">';
    for (let c = 1; c <= 2; c++) {
      h += '<div style="display:flex;flex-direction:column;align-items:center;gap:2px;">';
      h += '<div class="wf-aux" style="width:40px;height:24px;border-color:rgba(59,130,246,0.25);font-size:8px;color:rgba(59,130,246,0.4);">COM' + c + '</div>';
      h += '</div>';
    }
    h += '</div></div>';

    h += '<div class="port-section-divider" style="border-color:rgba(59,130,246,0.15);"></div>';

    // Ethernet port
    h += '<div style="display:flex;flex-direction:column;gap:2px;">';
    h += '<div class="chassis-inner-label">ETHERNET</div>';
    h += '<div class="wf-port ' + (isOnline ? 'up' : 'down') + '" title="Modbus TCP">ETH</div>';
    h += '</div>';

    h += '<div class="port-section-divider" style="border-color:rgba(59,130,246,0.15);"></div>';

    // 8 Analog Inputs (AI1-AI8)
    h += '<div style="display:flex;flex-direction:column;gap:2px;">';
    h += '<div class="chassis-inner-label">ANALOG IN</div>';
    h += '<div class="rtu-terminal-block">';
    for (let i = 1; i <= 8; i++) {
      h += '<div class="rtu-terminal" style="border-color:' + greenBorder + ';background:' + greenBg + ';">';
      h += '<div class="rtu-terminal-screw" style="border-color:' + greenScrew + ';background:rgba(34,197,94,0.12);"></div>';
      h += '</div>';
    }
    h += '</div>';
    h += '<div style="display:flex;gap:3px;margin-top:1px;">';
    for (let i = 1; i <= 8; i++) {
      h += '<div style="width:20px;text-align:center;font-size:6px;color:rgba(34,197,94,0.5);font-family:var(--font-mono);">AI' + i + '</div>';
    }
    h += '</div></div>';

    h += '<div class="port-section-divider" style="border-color:rgba(59,130,246,0.15);"></div>';

    // 4 Analog Outputs (AO1-AO4)
    h += '<div style="display:flex;flex-direction:column;gap:2px;">';
    h += '<div class="chassis-inner-label">ANALOG OUT</div>';
    h += '<div class="rtu-terminal-block">';
    for (let i = 1; i <= 4; i++) {
      h += '<div class="rtu-terminal" style="border-color:' + greenBorder + ';background:' + greenBg + ';">';
      h += '<div class="rtu-terminal-screw" style="border-color:' + greenScrew + ';background:rgba(34,197,94,0.12);"></div>';
      h += '</div>';
    }
    h += '</div>';
    h += '<div style="display:flex;gap:3px;margin-top:1px;">';
    for (let i = 1; i <= 4; i++) {
      h += '<div style="width:20px;text-align:center;font-size:6px;color:rgba(34,197,94,0.5);font-family:var(--font-mono);">AO' + i + '</div>';
    }
    h += '</div></div>';

    h += '<div class="port-section-divider" style="border-color:rgba(59,130,246,0.15);"></div>';

    // 8 Digital Inputs (DI1-DI8)
    h += '<div style="display:flex;flex-direction:column;gap:2px;">';
    h += '<div class="chassis-inner-label">DIGITAL IN</div>';
    h += '<div class="rtu-terminal-block">';
    for (let i = 1; i <= 8; i++) {
      h += '<div class="rtu-terminal" style="border-color:' + greenBorder + ';background:' + greenBg + ';">';
      h += '<div class="rtu-terminal-screw" style="border-color:' + greenScrew + ';background:rgba(34,197,94,0.12);"></div>';
      h += '</div>';
    }
    h += '</div>';
    h += '<div style="display:flex;gap:3px;margin-top:1px;">';
    for (let i = 1; i <= 8; i++) {
      h += '<div style="width:20px;text-align:center;font-size:6px;color:rgba(34,197,94,0.5);font-family:var(--font-mono);">DI' + i + '</div>';
    }
    h += '</div></div>';

    h += '<div class="port-section-divider" style="border-color:rgba(59,130,246,0.15);"></div>';

    // 4 Digital Outputs (DO1-DO4)
    h += '<div style="display:flex;flex-direction:column;gap:2px;">';
    h += '<div class="chassis-inner-label">DIGITAL OUT</div>';
    h += '<div class="rtu-terminal-block">';
    for (let i = 1; i <= 4; i++) {
      h += '<div class="rtu-terminal" style="border-color:' + greenBorder + ';background:' + greenBg + ';">';
      h += '<div class="rtu-terminal-screw" style="border-color:' + greenScrew + ';background:rgba(34,197,94,0.12);"></div>';
      h += '</div>';
    }
    h += '</div>';
    h += '<div style="display:flex;gap:3px;margin-top:1px;">';
    for (let i = 1; i <= 4; i++) {
      h += '<div style="width:20px;text-align:center;font-size:6px;color:rgba(34,197,94,0.5);font-family:var(--font-mono);">DO' + i + '</div>';
    }
    h += '</div></div>';

    // Status LEDs: RUN, PWR, COM, ERR
    h += '<div style="display:flex;flex-direction:column;gap:4px;margin-left:12px;">';
    h += '<div class="chassis-inner-label">STATUS</div>';
    const rtuLeds = [
      {n:'RUN', on: isOnline},
      {n:'PWR', on: true},
      {n:'COM', on: isOnline},
      {n:'ERR', on: false}
    ];
    for (const led of rtuLeds) {
      h += '<div style="display:flex;align-items:center;gap:4px;">';
      h += '<div class="rtu-led ' + (led.on ? 'on' : 'off') + '"' + (led.n === 'ERR' && !led.on ? ' style="background:rgba(239,68,68,0.15);"' : '') + '></div>';
      h += '<div style="font-size:7px;color:var(--text-muted);font-family:var(--font-mono);">' + led.n + '</div>';
      h += '</div>';
    }
    h += '</div>';

    h += '</div>'; // chassis-ports-area
    h += '</div>'; // chassis
    return h;
  }

  // ── Trio JR900 Radio Wireframe ─────────────────────────
  function renderRadioChassis(asset) {
    const isOnline = asset.status === 'good' || asset.status === 'warn';
    let h = '';
    h += '<div class="chassis radio-chassis">';
    h += '<div class="chassis-screw tl"></div><div class="chassis-screw tr"></div><div class="chassis-screw bl"></div><div class="chassis-screw br"></div>';
    h += '<div class="chassis-label">TRIO DATACOM</div>';
    h += '<div class="chassis-model-label">JR900</div>';

    h += '<div class="chassis-ports-area">';

    // N-type antenna connector (larger SVG ~36px)
    h += '<div style="display:flex;flex-direction:column;align-items:center;gap:2px;">';
    h += '<div class="chassis-inner-label">ANT</div>';
    h += '<svg width="36" height="36" viewBox="0 0 36 36" fill="none" stroke="rgba(168,85,247,0.5)" stroke-width="1.5">';
    h += '<circle cx="18" cy="18" r="14"/>';
    h += '<circle cx="18" cy="18" r="8"/>';
    h += '<circle cx="18" cy="18" r="3"/>';
    h += '<circle cx="18" cy="18" r="1" fill="rgba(168,85,247,0.5)"/>';
    h += '</svg>';
    h += '</div>';

    h += '<div class="port-section-divider" style="border-color:rgba(168,85,247,0.15);"></div>';

    // Green power terminal block (V+, V-)
    h += '<div style="display:flex;flex-direction:column;align-items:center;gap:2px;">';
    h += '<div class="chassis-inner-label">PWR</div>';
    h += '<div class="rtu-terminal-block">';
    h += '<div class="rtu-terminal" style="border-color:rgba(34,197,94,0.4);background:rgba(34,197,94,0.08);"><div class="rtu-terminal-screw" style="border-color:rgba(34,197,94,0.5);background:rgba(34,197,94,0.12);"></div></div>';
    h += '<div class="rtu-terminal" style="border-color:rgba(34,197,94,0.4);background:rgba(34,197,94,0.08);"><div class="rtu-terminal-screw" style="border-color:rgba(34,197,94,0.5);background:rgba(34,197,94,0.12);"></div></div>';
    h += '</div>';
    h += '<div style="display:flex;gap:3px;">';
    h += '<div style="width:20px;text-align:center;font-size:7px;color:rgba(34,197,94,0.6);font-family:var(--font-mono);">V+</div>';
    h += '<div style="width:20px;text-align:center;font-size:7px;color:rgba(34,197,94,0.6);font-family:var(--font-mono);">V-</div>';
    h += '</div></div>';

    h += '<div class="port-section-divider" style="border-color:rgba(168,85,247,0.15);"></div>';

    // DB9 serial port — D-shaped trapezoid
    h += '<div style="display:flex;flex-direction:column;align-items:center;gap:2px;">';
    h += '<div class="chassis-inner-label">SERIAL</div>';
    h += '<svg width="44" height="28" viewBox="0 0 44 28" fill="none">';
    h += '<path d="M6,2 L38,2 C40,2 42,4 42,6 L40,22 C40,24 38,26 36,26 L8,26 C6,26 4,24 4,22 L2,6 C2,4 4,2 6,2 Z" stroke="rgba(168,85,247,0.4)" stroke-width="1.5" fill="rgba(168,85,247,0.05)"/>';
    h += '<text x="22" y="17" text-anchor="middle" fill="rgba(168,85,247,0.5)" font-size="8" font-family="var(--font-mono)">DB9</text>';
    h += '</svg>';
    h += '</div>';

    h += '<div class="port-section-divider" style="border-color:rgba(168,85,247,0.15);"></div>';

    // 2x RJ45 serial ports (Serial A, Serial B)
    h += '<div style="display:flex;flex-direction:column;gap:2px;">';
    h += '<div class="chassis-inner-label">SERIAL A/B</div>';
    h += '<div style="display:flex;gap:3px;">';
    h += '<div class="wf-aux" style="width:42px;border-color:rgba(168,85,247,0.2);color:rgba(168,85,247,0.35);font-size:8px;">SER-A</div>';
    h += '<div class="wf-aux" style="width:42px;border-color:rgba(168,85,247,0.2);color:rgba(168,85,247,0.35);font-size:8px;">SER-B</div>';
    h += '</div></div>';

    h += '<div class="port-section-divider" style="border-color:rgba(168,85,247,0.15);"></div>';

    // Ethernet RJ45
    h += '<div style="display:flex;flex-direction:column;gap:2px;">';
    h += '<div class="chassis-inner-label">ETH</div>';
    h += '<div class="wf-port ' + (isOnline ? 'up' : 'down') + '" title="Ethernet">RJ45</div>';
    h += '</div>';

    // LEDs: PWR, LINK, TX, RX
    h += '<div style="display:flex;flex-direction:column;gap:4px;margin-left:12px;">';
    h += '<div class="chassis-inner-label">STATUS</div>';
    const radioLeds = [
      {n:'PWR', on: isOnline},
      {n:'LINK', on: isOnline},
      {n:'TX', on: false},
      {n:'RX', on: false}
    ];
    for (const led of radioLeds) {
      h += '<div style="display:flex;align-items:center;gap:4px;">';
      h += '<div class="rtu-led ' + (led.on ? 'on' : 'off') + '"></div>';
      h += '<div style="font-size:7px;color:var(--text-muted);font-family:var(--font-mono);">' + led.n + '</div>';
      h += '</div>';
    }
    h += '</div>';

    h += '</div>'; // chassis-ports-area
    h += '</div>'; // chassis
    return h;
  }

  // ── Raspberry Pi Edge Wireframe ────────────────────────
  function renderEdgeChassis(asset) {
    const isOnline = asset.status === 'good' || asset.status === 'warn';
    let h = '';
    h += '<div class="chassis edge-chassis">';
    h += '<div class="chassis-screw tl"></div><div class="chassis-screw tr"></div><div class="chassis-screw bl"></div><div class="chassis-screw br"></div>';
    h += '<div class="chassis-label">RASPBERRY PI</div>';
    h += '<div class="chassis-model-label">Model 4B</div>';

    h += '<div class="chassis-ports-area">';

    // USB-C power
    h += '<div style="display:flex;flex-direction:column;align-items:center;gap:2px;">';
    h += '<div class="chassis-inner-label">PWR</div>';
    h += '<div class="wf-aux" style="width:24px;height:14px;border-radius:6px;font-size:7px;border-color:rgba(236,72,153,0.3);color:rgba(236,72,153,0.4);">USB-C</div>';
    h += '</div>';

    h += '<div class="port-section-divider" style="border-color:rgba(236,72,153,0.15);"></div>';

    // 2x micro-HDMI ports
    h += '<div style="display:flex;flex-direction:column;align-items:center;gap:2px;">';
    h += '<div class="chassis-inner-label">HDMI</div>';
    h += '<div style="display:flex;gap:3px;">';
    h += '<div class="wf-aux" style="width:28px;height:16px;font-size:7px;border-color:rgba(236,72,153,0.2);color:rgba(236,72,153,0.3);">H0</div>';
    h += '<div class="wf-aux" style="width:28px;height:16px;font-size:7px;border-color:rgba(236,72,153,0.2);color:rgba(236,72,153,0.3);">H1</div>';
    h += '</div></div>';

    h += '<div class="port-section-divider" style="border-color:rgba(236,72,153,0.15);"></div>';

    // CSI camera connector (thin slot)
    h += '<div style="display:flex;flex-direction:column;align-items:center;gap:2px;">';
    h += '<div class="chassis-inner-label">CSI</div>';
    h += '<div style="width:36px;height:6px;border:1px solid rgba(236,72,153,0.2);border-radius:1px;background:rgba(236,72,153,0.04);"></div>';
    h += '</div>';

    h += '<div class="port-section-divider" style="border-color:rgba(236,72,153,0.15);"></div>';

    // Ethernet RJ45 with activity LEDs
    h += '<div style="display:flex;flex-direction:column;align-items:center;gap:2px;">';
    h += '<div class="chassis-inner-label">ETH</div>';
    h += '<div style="position:relative;">';
    h += '<div class="wf-port ' + (isOnline ? 'up' : 'down') + '" title="Ethernet" style="height:32px;">RJ45</div>';
    h += '<div style="position:absolute;top:-2px;left:2px;display:flex;gap:2px;">';
    h += '<div style="width:4px;height:4px;border-radius:50;background:' + (isOnline ? 'rgba(245,158,11,0.8)' : 'rgba(255,255,255,0.1)') + ';"></div>';
    h += '<div style="width:4px;height:4px;border-radius:50%;background:' + (isOnline ? 'var(--status-good)' : 'rgba(255,255,255,0.1)') + ';"></div>';
    h += '</div></div></div>';

    h += '<div class="port-section-divider" style="border-color:rgba(236,72,153,0.15);"></div>';

    // USB ports: 2x USB 3.0 (blue border) stacked, 2x USB 2.0 (gray border) stacked
    h += '<div style="display:flex;flex-direction:column;align-items:center;gap:2px;">';
    h += '<div class="chassis-inner-label">USB</div>';
    h += '<div style="display:flex;gap:4px;">';
    h += '<div class="port-pair-col">';
    h += '<div class="wf-aux" style="width:28px;height:18px;font-size:7px;border-color:rgba(59,130,246,0.5);color:rgba(59,130,246,0.5);">3.0</div>';
    h += '<div class="wf-aux" style="width:28px;height:18px;font-size:7px;border-color:rgba(59,130,246,0.5);color:rgba(59,130,246,0.5);">3.0</div>';
    h += '</div>';
    h += '<div class="port-pair-col">';
    h += '<div class="wf-aux" style="width:28px;height:18px;font-size:7px;border-color:rgba(255,255,255,0.12);color:rgba(255,255,255,0.2);">2.0</div>';
    h += '<div class="wf-aux" style="width:28px;height:18px;font-size:7px;border-color:rgba(255,255,255,0.12);color:rgba(255,255,255,0.2);">2.0</div>';
    h += '</div>';
    h += '</div></div>';

    h += '<div class="port-section-divider" style="border-color:rgba(236,72,153,0.15);"></div>';

    // GPIO 40-pin header (thin long rectangle on top edge)
    h += '<div style="display:flex;flex-direction:column;align-items:center;gap:2px;">';
    h += '<div class="chassis-inner-label">GPIO</div>';
    h += '<div style="width:80px;height:10px;border:1px solid rgba(236,72,153,0.25);border-radius:2px;background:rgba(236,72,153,0.04);display:flex;align-items:center;justify-content:center;">';
    h += '<div style="font-size:6px;color:rgba(236,72,153,0.35);font-family:var(--font-mono);">40-PIN</div>';
    h += '</div></div>';

    // LED indicators: PWR (red), ACT (green)
    h += '<div style="display:flex;flex-direction:column;gap:4px;margin-left:10px;">';
    h += '<div class="chassis-inner-label">LED</div>';
    h += '<div style="display:flex;align-items:center;gap:4px;">';
    h += '<div class="rtu-led on" title="PWR" style="background:var(--status-bad);box-shadow:0 0 6px var(--status-bad);"></div>';
    h += '<div style="font-size:7px;color:var(--text-muted);font-family:var(--font-mono);">PWR</div>';
    h += '</div>';
    h += '<div style="display:flex;align-items:center;gap:4px;">';
    h += '<div class="rtu-led ' + (isOnline ? 'on' : 'off') + '" title="ACT"></div>';
    h += '<div style="font-size:7px;color:var(--text-muted);font-family:var(--font-mono);">ACT</div>';
    h += '</div>';
    h += '</div>';

    h += '</div>'; // chassis-ports-area
    h += '</div>'; // chassis
    return h;
  }

  // ── Port helper ────────────────────────────────────────
  function wfPort(key, label, portMap, portTraffic) {
    const cleanKey = key.replace(/^"/g, '').toUpperCase();
    const p = portMap[cleanKey];
    const traffic = portTraffic[cleanKey] || portTraffic[key] || {};
    let cls = 'unused';
    let tipStatus = 'N/A';

    if (p) {
      const hasTraffic = (traffic.rx || 0) > 0 || (traffic.tx || 0) > 0;
      if (p.status === 1) { cls = 'up'; tipStatus = 'UP'; }
      else if (p.status === 2) { cls = hasTraffic ? 'down' : 'unused'; tipStatus = 'DOWN'; }
      else if (p.status === 6) { cls = 'unused'; tipStatus = 'NOT PRESENT'; }
    }

    let tip = cleanKey + ' — ' + tipStatus;
    if (traffic.rx != null) tip += '\nRX: ' + formatBytes(traffic.rx);
    if (traffic.tx != null) tip += '\nTX: ' + formatBytes(traffic.tx);

    return '<div class="wf-port ' + cls + '" title="' + tip + '">' + label + '</div>';
  }


  function formatBytes(bytes) {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
  }


  function renderSettingsPage() {
    const el = document.getElementById('settings-content');
    el.innerHTML = `
      <div class="settings-section">
        <div class="settings-title">Platform</div>
        <div class="settings-row"><span class="settings-label">Version</span><span class="settings-val">2.4.1</span></div>
        <div class="settings-row"><span class="settings-label">Site</span><span class="settings-val">Killdeer Field</span></div>
        <div class="settings-row"><span class="settings-label">API Endpoint</span><span class="settings-val">${API}</span></div>
        <div class="settings-row"><span class="settings-label">WebSocket</span><span class="settings-val">${ws&&ws.readyState===1?'Connected':'Reconnecting...'}</span></div>
      </div>
      <div class="settings-section">
        <div class="settings-title">Polling Configuration</div>
        <div class="settings-row"><span class="settings-label">Default Poll Interval</span><span class="settings-val">10s</span></div>
        <div class="settings-row"><span class="settings-label">RTU Poll Interval</span><span class="settings-val">15s</span></div>
        <div class="settings-row"><span class="settings-label">SNMP Poll Interval</span><span class="settings-val">30s</span></div>
        <div class="settings-row"><span class="settings-label">WebSocket Keepalive</span><span class="settings-val">30s</span></div>
      </div>
      <div class="settings-section">
        <div class="settings-title">Connected Devices</div>
        ${liveAssets.map(a => `<div class="settings-row"><span class="settings-label">${a.id} — ${a.name}</span><span class="settings-val">${a.protocol?.toUpperCase()||'—'} · ${a.ip_address||'—'}</span></div>`).join('')}
      </div>
      <div class="settings-section">
        <div class="settings-title">Data Retention</div>
        <div class="settings-row"><span class="settings-label">Metrics History</span><span class="settings-val">30 days</span></div>
        <div class="settings-row"><span class="settings-label">Alert History</span><span class="settings-val">90 days</span></div>
        <div class="settings-row"><span class="settings-label">Prediction Model</span><span class="settings-val">72-hour rolling</span></div>
      </div>
    `;
  }


  // ═══════════════════════════════════════
  // ASSET DETAIL DRAWER
  // ═══════════════════════════════════════
  let drawerOpen = false;
  let drawerAssetId = null;

  function openAssetDrawer(assetId) {
    drawerAssetId = assetId;
    drawerOpen = true;
    document.getElementById('drawer-overlay').classList.add('open');
    document.getElementById('asset-drawer').classList.add('open');
    renderDrawerContent(assetId);
    fetchJSON('/predictions/' + assetId).then(pred => {
      if (pred) renderDrawerPrediction(pred);
    });
  }
  window.openAssetDrawer = openAssetDrawer;

  function closeAssetDrawer() {
    drawerOpen = false;
    drawerAssetId = null;
    document.getElementById('drawer-overlay').classList.remove('open');
    document.getElementById('asset-drawer').classList.remove('open');
  }
  window.closeAssetDrawer = closeAssetDrawer;

  document.addEventListener('keydown', e => { if (e.key === 'Escape' && drawerOpen) closeAssetDrawer(); });
  setTimeout(() => {
    const cb = document.getElementById('drawer-close-btn');
    if (cb) cb.addEventListener('click', closeAssetDrawer);
    const ov = document.getElementById('drawer-overlay');
    if (ov) ov.addEventListener('click', closeAssetDrawer);
  }, 200);

  function renderDrawerContent(assetId) {
    const asset = liveAssets.find(a => a.id === assetId);
    if (!asset) return;
    const hc = hClass(asset.status, asset.health);
    const hCol = hc==='good'?'var(--status-good)':hc==='warn'?'var(--status-warn)':hc==='bad'?'var(--status-bad)':'var(--status-offline)';

    document.getElementById('drawer-name').innerHTML = asset.name + ' ' + statusPill(asset.status, asset.health);
    document.getElementById('drawer-meta').textContent = asset.id + ' · ' + (asset.vendor||'') + ' ' + (asset.model||'') + ' · ' + (asset.location||'');

    const assetAlerts = liveAlerts.filter(a => a.asset_id === assetId).slice(0, 10);

    let h = '';

    // Summary
    h += `<div class="drawer-section"><div class="drawer-section-title">
      <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="3" width="18" height="18" rx="2"/><line x1="9" y1="9" x2="15" y2="9"/><line x1="9" y1="15" x2="15" y2="15"/></svg>
      DEVICE SUMMARY</div>
      <div class="drawer-summary-grid">
        <div class="drawer-summary-item"><div class="drawer-summary-label">Health Score</div><div class="drawer-summary-val" style="color:${hCol};font-size:24px;">${asset.health!=null?asset.health:'—'}</div></div>
        <div class="drawer-summary-item"><div class="drawer-summary-label">Protocol</div><div class="drawer-summary-val">${protocolMap[asset.protocol]||asset.protocol||'—'}</div></div>
        <div class="drawer-summary-item"><div class="drawer-summary-label">IP Address</div><div class="drawer-summary-val">${asset.ip_address||'—'}</div></div>
        <div class="drawer-summary-item"><div class="drawer-summary-label">Poll Interval</div><div class="drawer-summary-val">${asset.poll_interval||'—'}s</div></div>
        <div class="drawer-summary-item"><div class="drawer-summary-label">Last Seen</div><div class="drawer-summary-val">${timeAgo(asset.last_seen)}</div></div>
        <div class="drawer-summary-item"><div class="drawer-summary-label">Type</div><div class="drawer-summary-val" style="text-transform:capitalize;">${asset.type||'—'}</div></div>
      </div></div>`;

    // Group vitals by category
    const groupLabels = {
      compressor: {title: 'COMPRESSOR', icon: '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="3"/><path d="M12 1v4M12 19v4M4.22 4.22l2.83 2.83M16.95 16.95l2.83 2.83M1 12h4M19 12h4M4.22 19.78l2.83-2.83M16.95 7.05l2.83-2.83"/></svg>'},
      well: {title: 'WELLHEAD', icon: '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 2v20M8 6h8M6 10h12M8 14h8"/></svg>'},
      production: {title: 'PRODUCTION / TANKS', icon: '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="3" width="18" height="18" rx="2"/><line x1="3" y1="15" x2="21" y2="15"/><line x1="3" y1="9" x2="21" y2="9"/></svg>'},
      power: {title: 'POWER', icon: '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.8"><polyline points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>'},
      safety: {title: 'SAFETY / GAS DETECTION', icon: '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>'},
      environment: {title: 'ENVIRONMENT', icon: '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M14 14.76V3.5a2.5 2.5 0 0 0-5 0v11.26a4.5 4.5 0 1 0 5 0z"/></svg>'},
      system: {title: 'SYSTEM', icon: '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>'},
      rf: {title: 'RF / RADIO', icon: '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M5 12.55a11 11 0 0 1 14.08 0"/><path d="M1.42 9a16 16 0 0 1 21.16 0"/><path d="M8.53 16.11a6 6 0 0 1 6.95 0"/><circle cx="12" cy="20" r="1"/></svg>'},
      traffic: {title: 'TRAFFIC', icon: '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.8"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>'},
    };
    const allVitals = asset.vitals || [];
    const groups = {};
    for (const v of allVitals) {
      const g = v.group || 'system';
      if (!groups[g]) groups[g] = {analog: [], discrete: []};
      if (v.unit === 'bool') groups[g].discrete.push(v);
      else groups[g].analog.push(v);
    }
    const groupOrder = ['compressor','well','production','safety','power','environment','rf','traffic','system'];
    for (const gk of groupOrder) {
      const gd = groups[gk];
      if (!gd) continue;
      const gl = groupLabels[gk] || {title: gk.toUpperCase(), icon: ''};
      const hasAnalog = gd.analog.length > 0;
      const hasDiscrete = gd.discrete.length > 0;
      if (!hasAnalog && !hasDiscrete) continue;
      h += '<div class="drawer-section"><div class="drawer-section-title">' + gl.icon + ' <span class="live-dot"></span> ' + gl.title + '</div>';
      if (hasAnalog) {
        h += '<div class="drawer-vitals-grid">';
        for (const v of gd.analog) {
          const raw = parseFloat(v.raw_value);
          const dv = isNaN(raw) ? v.value : (raw % 1 === 0 ? raw.toFixed(0) : raw.toFixed(1));
          h += '<div class="drawer-vital ' + (v.status||'') + '"><div class="drawer-vital-label">' + v.label + '</div><div class="drawer-vital-value">' + dv + '<span class="drawer-vital-unit">' + (v.unit||'') + '</span></div></div>';
        }
        h += '</div>';
      }
      if (hasDiscrete) {
        for (const v of gd.discrete) {
          const isOk = v.value==='OK'||v.value==='STOPPED'||v.raw_value===0;
          const dc = v.status==='good'?'var(--status-good)':isOk?'var(--text-muted)':'var(--status-bad)';
          h += '<div class="drawer-discrete-row"><div class="drawer-discrete-dot" style="background:' + dc + ';"></div><div class="drawer-discrete-label">' + v.label + '</div><div class="drawer-discrete-val" style="color:' + dc + ';">' + v.value + '</div></div>';
        }
      }
      h += '</div>';
    }

    // AI Prediction placeholder
    h += `<div class="drawer-section" id="drawer-pred-section" style="display:none;"></div>`;

    // Alerts
    h += `<div class="drawer-section"><div class="drawer-section-title">
      <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
      ALERTS (${assetAlerts.length})</div>`;
    if (assetAlerts.length === 0) {
      h += `<div style="text-align:center;padding:16px;color:var(--text-muted);font-size:12px;">No alerts for this asset</div>`;
    } else {
      for (const a of assetAlerts) {
        const sev = a.severity||'info';
        const sc = sev==='critical'?'var(--status-bad)':sev==='warning'?'var(--status-warn)':'var(--accent)';
        h += `<div style="display:flex;align-items:flex-start;gap:10px;padding:10px;border-radius:8px;background:var(--bg-card);border:1px solid var(--border);border-left:3px solid ${sc};margin-bottom:8px;">
          <div style="flex:1;"><div style="display:flex;align-items:center;gap:6px;margin-bottom:3px;">
            <span class="severity-badge ${sev}">${sev.toUpperCase()}</span>
            <span style="font-size:10px;color:var(--text-muted);font-family:var(--font-mono);">${timeAgo(a.detected_at)}</span>
          </div><div style="font-size:11px;color:var(--text-secondary);">${a.message}</div></div></div>`;
      }
    }
    h += `</div>`;

    document.getElementById('drawer-body').innerHTML = h;
  }

  function renderDrawerPrediction(pred) {
    const sec = document.getElementById('drawer-pred-section');
    if (!sec || !pred) return;
    sec.style.display = 'block';
    const rc = pred.risk_score >= 60 ? 'var(--status-bad)' : pred.risk_score >= 30 ? 'var(--status-warn)' : 'var(--status-good)';
    sec.innerHTML = `<div class="drawer-section-title">
      <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/></svg>
      AI PREDICTION</div>
      <div style="display:flex;align-items:center;gap:16px;margin-bottom:12px;">
        <div style="font-family:var(--font-mono);font-size:36px;font-weight:700;color:${rc};">${pred.risk_score}</div>
        <div style="font-size:12px;color:var(--text-muted);">Risk Score</div>
      </div>
      <div class="drawer-summary-grid" style="margin-bottom:12px;">
        <div class="drawer-summary-item"><div class="drawer-summary-label">Est. Failure</div><div class="drawer-summary-val" style="color:${rc};">${pred.estimated_failure||'—'}</div></div>
        <div class="drawer-summary-item"><div class="drawer-summary-label">Confidence</div><div class="drawer-summary-val">${pred.confidence_interval||'—'}</div></div>
      </div>
      ${pred.primary_drivers && pred.primary_drivers.length > 0 ? '<div style="font-size:9px;text-transform:uppercase;letter-spacing:1px;color:var(--text-muted);margin-bottom:8px;">Risk Drivers</div>' + pred.primary_drivers.map(d => '<div style="display:flex;align-items:center;gap:6px;font-size:12px;color:var(--text-secondary);padding:4px 0;"><span style="width:4px;height:4px;border-radius:50%;background:var(--accent);flex-shrink:0;"></span>' + d + '</div>').join('') : ''}`;
  }

  function refreshDrawerIfOpen() {
    if (drawerOpen && drawerAssetId) renderDrawerContent(drawerAssetId);
  }

  // ═══════════════════════════════════════
  // WEBSOCKET
  // ═══════════════════════════════════════
  function connectWebSocket() {
    if (ws && ws.readyState <= 1) return;
    try { ws = new WebSocket(WS_URL); } catch(e) { return; }
    ws.onopen = () => { console.log('[WS] Connected'); if(pollTimer){clearInterval(pollTimer);pollTimer=null;} };
    ws.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data);
        if (msg.type === 'asset_update') {
          const d = msg.data, idx = liveAssets.findIndex(a=>a.id===d.asset_id);
          if (idx>=0) { liveAssets[idx].health=d.health; liveAssets[idx].status=d.status; if(d.vitals) liveAssets[idx].vitals=d.vitals; liveAssets[idx].last_seen=d.timestamp; }
          fetchHealthSummary().then(()=> { const page = location.hash.replace('#','')||'overview'; renderPage(page, true); refreshDrawerIfOpen(); });
        } else if (msg.type === 'alert_update' && msg.data?.alerts) {
          for(const a of msg.data.alerts) { const i=liveAlerts.findIndex(x=>x.id===a.id); if(i>=0) liveAlerts[i]=a; else liveAlerts.unshift(a); }
          const page = location.hash.replace('#','')||'overview'; renderPage(page, true);
        }
      } catch(err) {}
    };
    ws.onclose = () => { ws=null; startPolling(); setTimeout(connectWebSocket,5000); };
    ws.onerror = () => { ws.close(); };
    setInterval(()=>{ if(ws&&ws.readyState===1)ws.send('ping'); },30000);
  }

  function startPolling() { if(!pollTimer) pollTimer=setInterval(refreshAll,POLL_INTERVAL); }

  async function refreshAll() {
    await Promise.all([fetchAssets(), fetchAlerts(), fetchHealthSummary(), fetchPredictions()]);
    const page = location.hash.replace('#','')||'overview';
    renderPage(page, true);
  }

  // ── Connection Indicator ──
  function addConnectionIndicator() {
    const bar = document.querySelector('.topbar-right');
    if (!bar) return;
    const el = document.createElement('div');
    el.id = 'api-status';
    el.style.cssText = 'display:flex;align-items:center;gap:6px;font-size:11px;color:var(--text-muted);padding:4px 10px;border-radius:6px;background:rgba(6,182,212,0.08);border:1px solid rgba(6,182,212,0.15);';
    el.innerHTML = '<span id="api-dot" style="width:6px;height:6px;border-radius:50%;background:var(--status-warn);"></span><span id="api-label">Connecting...</span>';
    bar.prepend(el);
    setInterval(()=>{
      const dot=document.getElementById('api-dot'),lbl=document.getElementById('api-label');
      if(!dot||!lbl)return;
      if(ws&&ws.readyState===1){dot.style.background='var(--status-good)';lbl.textContent=`Live · ${liveAssets.length} assets`;}
      else if(liveAssets.length>0){dot.style.background='var(--status-warn)';lbl.textContent='Polling';}
      else{dot.style.background='var(--status-bad)';lbl.textContent='Disconnected';}
    },2000);
  }

  // ── INIT ──
  async function init() {
    console.log(`[Aevus] Connecting to ${API_BASE}`);
    addConnectionIndicator();
    await refreshAll();
    initRouter();
    connectWebSocket();
    startPolling();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else setTimeout(init, 50);
})();

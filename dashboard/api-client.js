// ══════════════════════════════════════════
// ── GLOBAL UTILITIES (always available) ──
// ══════════════════════════════════════════

// Logout
window.aevusLogout = function() {
  localStorage.removeItem('aevus_id_token');
  localStorage.removeItem('aevus_access_token');
  localStorage.removeItem('aevus_user_email');
  window.location.href = '/dashboard/login.html';
};

// Tab badge — show alert count in browser tab title
window.updateTabBadge = function(count) {
  var base = 'Aevus — Killdeer Field';
  document.title = count > 0 ? 'Aevus (' + count + ') — Killdeer Field' : base;
};

// Bell dropdown toggle
window.toggleBellDropdown = function() {
  var dd = document.getElementById('bell-dropdown');
  if (!dd) return;
  dd.style.display = dd.style.display === 'block' ? 'none' : 'block';
};

// Close bell dropdown on outside click
document.addEventListener('click', function(e) {
  var dd = document.getElementById('bell-dropdown');
  var bell = document.querySelector('.topbar-bell');
  if (dd && bell && !bell.contains(e.target) && !dd.contains(e.target)) {
    dd.style.display = 'none';
  }
});

// Show user email from Cognito
(function() {
  var userEmail = localStorage.getItem('aevus_user_email');
  if (userEmail) {
    document.addEventListener('DOMContentLoaded', function() {
      var nameEl = document.querySelector('.sidebar-user-name');
      if (nameEl) nameEl.textContent = userEmail.split('@')[0].replace(/\./g, ' ').replace(/\b\w/g, function(l){return l.toUpperCase();});
    });
  }
})();


// ── ALARM POLLING FOR BELL + TAB BADGE ──
(function() {
  var API_KEY = '8U7_JghqHK-nmG5bDwUx5w-A9uFg8F7tiVmvR9WJDyY';
  function pollAlarms() {
    var tok = localStorage.getItem('aevus_id_token');
    var headers = {'X-API-Key': API_KEY};
    if (tok) headers['Authorization'] = 'Bearer ' + tok;
    fetch('/api/alarms', {headers: headers})
      .then(function(r){return r.json()})
      .then(function(d){
        var alarms = d.alarms || [];
        var active = alarms.filter(function(a){return a.state==='active'}).length;
        if(window.updateTabBadge) window.updateTabBadge(active);
        var dd = document.getElementById('bell-dropdown-list');
        if(dd){
          if(alarms.length===0){
            dd.innerHTML='<div style="padding:16px;text-align:center;color:#7B8499;font-size:12px;">No recent alarms</div>';
          } else {
            dd.innerHTML=alarms.slice(0,8).map(function(a){
              var col = a.severity==='critical'?'#EF4444':a.severity==='warning'?'#FBBF24':'#7B8499';
              return '<div style="padding:8px 12px;border-bottom:1px solid rgba(148,163,184,0.08);display:flex;gap:8px;align-items:flex-start;">' +
                '<div style="width:6px;height:6px;border-radius:50%;background:'+col+';margin-top:5px;flex-shrink:0;"></div>' +
                '<div><div style="font-size:11px;color:#FFFFFF;">'+a.asset_id+' — '+(a.metric||a.message||'alarm')+'</div>' +
                '<div style="font-size:10px;color:#7B8499;">'+a.severity+' · '+(a.state||'')+'</div></div></div>';
            }).join('');
          }
        }
      }).catch(function(){
        var dd = document.getElementById('bell-dropdown-list');
        if(dd) dd.innerHTML='<div style="padding:16px;text-align:center;color:#7B8499;font-size:12px;">No recent alarms</div>';
      });
  }
  setTimeout(pollAlarms, 2000);
  setInterval(pollAlarms, 15000);
})();

// ── ROLE-BASED ACCESS CONTROL ──
(function() {
  var idToken = localStorage.getItem('aevus_id_token');
  if (!idToken) return;
  
  // Decode JWT payload (no validation, just read claims)
  try {
    var payload = JSON.parse(atob(idToken.split('.')[1]));
    var groups = payload['cognito:groups'] || [];
    var role = 'viewer'; // default
    if (groups.indexOf('Admin') >= 0) role = 'admin';
    else if (groups.indexOf('Operator') >= 0) role = 'operator';
    
    window.aevusRole = role;
    
    // Update sidebar role display
    var roleEl = document.querySelector('.sidebar-user-role');
    if (roleEl) {
      var roleLabels = {admin: 'Administrator', operator: 'Operator', viewer: 'Viewer'};
      roleEl.textContent = roleLabels[role] || 'Viewer';
    }
    
    // Hide nav items based on role
    document.addEventListener('DOMContentLoaded', function() {
      var restricted = {
        viewer: ['settings', 'cybersecurity'],
        operator: ['settings']
      };
      var hidden = restricted[role] || [];
      hidden.forEach(function(page) {
        var nav = document.querySelector('a[data-page="' + page + '"]');
        if (nav) nav.style.display = 'none';
      });
      
      // Hide action buttons for viewers
      if (role === 'viewer') {
        // Hide CSV import, acknowledge alarm buttons, etc
        document.querySelectorAll('[data-admin-only]').forEach(function(el) {
          el.style.display = 'none';
        });
      }
    });
  } catch(e) {
    window.aevusRole = 'viewer';
  }
})();


/**
 * Aevus Dashboard — Live API Client + SPA Router
 * All pages driven by live API data.
 */
(function () {
  'use strict';

  // ── Supabase Auth Guard ──
  const SUPABASE_TOKEN = localStorage.getItem('aevus_supabase_token') || '';
  if (!SUPABASE_TOKEN && !window.AEVUS_API_KEY) {
    // No Supabase token and no hardcoded API key -- redirect to login
    window.location.href = '/dashboard/login.html';
    return;  // Stop IIFE execution
  }

  const API_BASE = window.AEVUS_API_URL || `${location.protocol}//${location.host}`;
  const API_KEY = window.AEVUS_API_KEY || '';
  const API = `${API_BASE}/api/v1`;
  const WS_URL = API_BASE.replace(/^http/, 'ws') + '/api/v1/ws' + (API_KEY ? `?key=${API_KEY}` : '');
  const POLL_INTERVAL = 10_000;

  let ws = null, pollTimer = null;
  let liveAssets = [], liveAlerts = [], healthSummary = {}, predictions = [];
  let trendData = [], currentTrendMetric = 'cpu_load';
  let weatherData = null, correlations = [], commandLog = [];
  let forecastData = null;
  const MAPBOX_TOKEN = window.AEVUS_MAPBOX_TOKEN || 'pk.eyJ1Ijoid29vZHlpbCIsImEiOiJjbWR4eW5keTUwOTlvMmxxMXo1aGljdWdyIn0.f4ud1cQ6mf-oNM69iY6fEg';
  const SITE_LAT = 29.3905;
  const SITE_LON = -95.8375;
  let currentAlertFilter = 'all';
  let currentAlertStatusFilter = 'open';
  let currentAssetFilter = 'all';
  let pageInitialized = {};

  // ── API ──
  async function fetchJSON(path) {
    try {
      const h = {}; if (API_KEY) h['X-API-Key'] = API_KEY;
        var idTok = localStorage.getItem('aevus_id_token');
        if (idTok) h['Authorization'] = 'Bearer ' + idTok; if (SUPABASE_TOKEN) h['Authorization'] = 'Bearer ' + SUPABASE_TOKEN;
      const r = await fetch(`${API}${path}`, { headers: h });
      if (!r.ok) throw new Error(r.status);
      return await r.json();
    } catch (e) { console.warn(`[API] ${path}:`, e.message); return null; }
  }
  async function fetchAssets() { const d = await fetchJSON('/assets'); if (d) liveAssets = d; }
  async function fetchAlerts() { const d = await fetchJSON('/alerts?limit=50'); if (d) liveAlerts = d; }

  window.ackAlert = async function(id) {
    const r = await fetch(API + '/alerts/' + id + '/acknowledge', {method:'POST'});
    if (r.ok) { const a = await r.json(); const i = liveAlerts.findIndex(x=>x.id===a.id); if(i>=0) liveAlerts[i]=a; renderAlertsPage(); renderLiveAlerts(); }
  };
  window.resolveAlert = async function(id) {
    const r = await fetch(API + '/alerts/' + id + '/resolve', {method:'POST'});
    if (r.ok) { const a = await r.json(); const i = liveAlerts.findIndex(x=>x.id===a.id); if(i>=0) liveAlerts[i]=a; renderAlertsPage(); renderLiveAlerts(); }
  };
  async function fetchHealthSummary() { const d = await fetchJSON('/health/summary'); if (d) healthSummary = d; }
  async function fetchPredictions() { const d = await fetchJSON('/predictions'); if (d) predictions = d; }
  async function fetchTrend(metric) {
    const d = await fetchJSON(`/health/trend?metric=${metric}&hours=24`);
    if (d) trendData = d;
  }

  async function fetchWeather() { const d = await fetchJSON('/weather'); if (d) weatherData = d; }
  async function fetchCorrelations() { const d = await fetchJSON('/correlations'); if (d) correlations = d; }
  async function fetchCommandLog() { const d = await fetchJSON('/commands/log?limit=20'); if (d) commandLog = d; }

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
    // Board rec #5: Update breadcrumb
    var bc = document.getElementById('breadcrumb-trail');
    if (bc) {
      var pageNames = {overview:'Process Overview',assets:'Assets',alarms:'Alarm Management',health:'System Health',diagnostics:'Diagnostics',trends:'Historian',cabinet:'Cabinet View',operations:'Operations',weather:'Weather Intelligence',radio:'Radio Comms',map:'Site Map',network:'Network Topology',cybersecurity:'Cybersecurity',reports:'Reports',settings:'Settings'};
      bc.innerHTML = '<span style="color:var(--accent);">Killdeer Field</span> <span style="color:var(--text-faint);margin:0 6px;">›</span> <span>' + (pageNames[page]||page) + '</span>';
    }
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

  async function renderPage(page, isRefresh) { var ft=document.querySelector('.footer');if(ft)ft.style.display=(page==='weather'||page==='radio'||page==='map')?'none':'';var sf=document.querySelector('.sidebar-footer');if(sf)sf.style.display=(page==='weather'||page==='radio'||page==='map')?'none':'';document.body.style.overflow=(page==='weather'||page==='radio'||page==='map')?'hidden':'';
    switch(page) {
      case 'overview': renderOverview(); break;
      case 'assets': isRefresh ? renderAssetsTable(currentAssetFilter) : renderAssetsPage(); break;
      case 'health': renderHealthPage(); break;
      case 'alerts': isRefresh ? renderAlertsList() : renderAlertsPage(); break;
      case 'diagnostics': renderDiagnosticsPage(); break;
      case 'trends': if (!isRefresh) await renderTrendsPage(); break;
      case 'cabinet': renderCabinetPage(); break;
      case 'operations': renderOperationsPage(); break;
      case 'weather': renderWeatherPage(); break;
      case 'reports': renderReportsPage(); break;
      case 'alarms': renderAlarmsPage(); break;
      case 'historian': renderHistorianPage(); break;
      case 'network': renderNetworkPage(); break;
      case 'cyber': renderCyberPage(); break;
      case 'radio': renderRadioCommsPage(); break;
      case 'map': renderMapPage(); break;
      case 'settings': renderSettingsPage(); break;
      case 'map': renderMapPage(); break;
    }
  }

  // ═══════════════════════════════════════
  // PAGE: OVERVIEW
  // ═══════════════════════════════════════
  function renderOverview() {
    updateKPIs();
    renderWeatherStrip();
    renderCorrelationsOverview();
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


  // HPI: Analog range bar — shows where value sits within normal operating range
  const VITAL_RANGES = {
    'PSI': [0, 1500], 'psi': [0, 1500], 'PSIG': [0, 1500],
    '°F': [-40, 250], 'F': [-40, 250],
    'RPM': [0, 3600], 'rpm': [0, 3600],
    'mm/s': [0, 10], 'A': [0, 50],
    'MCFD': [0, 5000], 'MCF': [0, 500000],
    'BOPD': [0, 500], 'BBL/h': [0, 100],
    '%': [0, 100], 'in': [0, 200], 'IN': [0, 200],
    'VDC': [0, 30], 'vdc': [0, 30],
    'PPM': [0, 50], 'ppm': [0, 50],
    '%LEL': [0, 100],
    'hrs': [0, 50000],
    'dBm': [-120, 0], 'dB': [0, 40],
    'Mbps': [0, 100], 'ms': [0, 500],
    'INH2O': [0, 100], 'inH2O': [0, 100],
    'SG': [0, 2], 'sg': [0, 2],
    'BTU/CF': [0, 2000], 'MMBTU': [0, 500], 'MMBTU/D': [0, 100],
    'count': [0, 100000],
    'bool': null,
  };
  function analogBar(raw, unit, status) {
    var range = VITAL_RANGES[unit];
    if (!range) return '';
    var n = parseFloat(raw);
    if (isNaN(n)) return '';
    var pct = Math.max(0, Math.min(100, ((n - range[0]) / (range[1] - range[0])) * 100));
    var col = status === 'critical' ? '#EF4444' : status === 'warning' ? '#FBBF24' : '#4A5168';
    return '<div style="height:4px;background:rgba(255,255,255,0.10);border-radius:2px;margin-top:4px;width:100%;"><div style="height:100%;width:' + pct.toFixed(1) + '%;background:' + col + ';border-radius:2px;transition:width 0.5s;"></div></div>';
  }



  // Board rec #4: Range string for tooltips
  function vitalRangeStr(unit) {
    var r = typeof VITAL_RANGES !== 'undefined' ? VITAL_RANGES[unit] : null;
    if (!r) return 'N/A';
    return r[0] + '–' + r[1] + ' ' + (unit||'');
  }

  // Board rec #3: Classify vitals into display tiers
  var SAFETY_LABELS = ['H2S','LEL','ESD','Gas','Shutdown','Emergency','Flame'];
  var INFO_LABELS = ['Run Hours','Hours','Battery','Signal','RSSI','SNR','Uptime','Firmware'];
  function vitalTier(v) {
    var label = (v.label||'').toLowerCase();
    for (var i=0;i<SAFETY_LABELS.length;i++) if (label.indexOf(SAFETY_LABELS[i].toLowerCase())>=0) return 'safety';
    if (v.status === 'critical' || v.status === 'warning') return 'critical';
    for (var j=0;j<INFO_LABELS.length;j++) if (label.indexOf(INFO_LABELS[j].toLowerCase())>=0) return 'info';
    return 'process';
  }


  // Board rec #1: Compact sparkline for process panel vitals
  function compactSparkline(raw, unit, status) {
    var n = parseFloat(raw);
    if (isNaN(n)) return '';
    var hist = fakeHistory(n, unit, 16);
    if (!hist) return '';
    var w = 60, h = 16, pad = 1;
    var min = Math.min.apply(null, hist), max = Math.max.apply(null, hist);
    var range = max - min || 1;
    var pts = [];
    for (var i = 0; i < hist.length; i++) {
      var x = (pad + (i / (hist.length - 1)) * (w - 2 * pad)).toFixed(1);
      var y = (h - pad - ((hist[i] - min) / range) * (h - 2 * pad)).toFixed(1);
      pts.push(x + ',' + y);
    }
    var col = status === 'critical' ? '#EF4444' : status === 'warning' ? '#FBBF24' : '#4A5168';
    return '<svg width="' + w + '" height="' + h + '" viewBox="0 0 ' + w + ' ' + h + '" style="display:block;margin-top:2px;opacity:0.7;"><polyline points="' + pts.join(' ') + '" fill="none" stroke="' + col + '" stroke-width="1" stroke-linecap="round" stroke-linejoin="round"/></svg>';
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
        return `<div class="vital-item ${v.status||''} tier-${vitalTier(v)}" title="${v.label}: ${dv} ${v.unit||''} — Range: ${vitalRangeStr(v.unit)}"><div class="vi-label">${v.label}</div><div class="vi-value">${dv}<span class="vi-unit">${v.unit||''}</span></div>${analogBar(v.raw_value, v.unit, v.status)}${compactSparkline(v.raw_value, v.unit, v.status)}</div>`;
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

  function alertCardHTML(a, full) {
    const sev = a.severity || 'info';
    const borderColor = sev === 'critical' ? '#EF4444' : sev === 'warning' ? '#FBBF24' : '#06B6D4';
    const isTrap = a.message && (a.message.toLowerCase().includes('link down') || a.message.toLowerCase().includes('cold start') || a.message.toLowerCase().includes('trap'));
    const trapBadge = isTrap ? '<span style="font-size:9px;padding:2px 6px;border-radius:4px;background:rgba(167,139,250,0.15);color:#A78BFA;font-weight:600;margin-left:6px;">TRAP</span>' : '';
    const statusBadge = a.status !== 'open' ? `<span style="font-size:9px;padding:2px 6px;border-radius:4px;background:${a.status==='acknowledged'?'rgba(251,191,36,0.15)':'rgba(16,212,120,0.15)'};color:${a.status==='acknowledged'?'#FBBF24':'#10D478'};font-weight:600;margin-left:6px;">${a.status.toUpperCase()}</span>` : '';
    const actions = full && a.status !== 'resolved' ? `<div style="display:flex;gap:6px;margin-top:8px;">${a.status==='open'?`<button onclick="window.ackAlert('${a.id}')" style="font-size:10px;padding:4px 10px;border-radius:6px;border:1px solid rgba(251,191,36,0.3);background:rgba(251,191,36,0.1);color:#FBBF24;cursor:pointer;font-family:var(--font-body);">Acknowledge</button>`:''}<button onclick="window.resolveAlert('${a.id}')" style="font-size:10px;padding:4px 10px;border-radius:6px;border:1px solid rgba(16,212,120,0.3);background:rgba(16,212,120,0.1);color:#10D478;cursor:pointer;font-family:var(--font-body);">Resolve</button></div>` : '';
    return `<div class="alert-card ${sev}" style="border-left:3px solid ${borderColor};${isTrap?'box-shadow:0 0 8px rgba(167,139,250,0.15);':''}">
      <div class="alert-icon-wrap ${sev}">${alertSvgs[sev]||alertSvgs.info}</div>
      <div class="alert-body">
        <div class="alert-meta-row"><span class="severity-badge ${sev}">${sev.toUpperCase()}</span>${statusBadge}${trapBadge}<span class="alert-time">${timeAgo(a.detected_at)}</span></div>
        <div class="alert-asset">${a.asset_name||a.asset_id}</div>
        <div class="alert-desc">${a.message}</div>${actions}
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
  // Enhanced asset table state
  let assetSortCol = 'id', assetSortDir = 'asc', assetSearchTerm = '', assetStatusFilter = 'all';
  let assetColumns = JSON.parse(localStorage.getItem('aevus_asset_columns') || 'null') || ['id','name','type','status','health','protocol','ip_address','last_seen','vitals'];
  const allAssetColumns = [
    {key:'id',label:'ID'}, {key:'name',label:'Name'}, {key:'type',label:'Type'},
    {key:'status',label:'Status'}, {key:'health',label:'Health'}, {key:'protocol',label:'Protocol'},
    {key:'ip_address',label:'IP Address'}, {key:'last_seen',label:'Last Seen'}, {key:'vitals',label:'Vitals'},
    {key:'vendor',label:'Vendor'}, {key:'model',label:'Model'}, {key:'location',label:'Location'},
    {key:'poll_interval',label:'Poll Interval'}
  ];

  function renderAssetsPage() {
    const fb = document.getElementById('asset-filters');
    const types = ['all', ...new Set(liveAssets.map(a => a.type))];
    const statuses = ['all', ...new Set(liveAssets.map(a => a.status||'unknown'))];

    fb.innerHTML =
      // Search bar
      '<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;width:100%;">' +
      '<div style="position:relative;flex:1;min-width:200px;">' +
      '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.8" style="position:absolute;left:10px;top:50%;transform:translateY(-50%);color:var(--text-muted);"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>' +
      '<input id="asset-search" type="text" placeholder="Search assets..." value="' + assetSearchTerm + '" style="width:100%;padding:6px 10px 6px 30px;border-radius:8px;border:1px solid var(--border-light);background:var(--bg-card);color:var(--text-primary);font-size:12px;font-family:var(--font-body);outline:none;">' +
      '</div>' +
      // Type filters
      '<div style="display:flex;gap:4px;">' +
      types.map(t => '<button class="filter-btn ' + (t===currentAssetFilter?'active':'') + '" data-type="' + t + '">' + (t==='all'?'All':t.charAt(0).toUpperCase()+t.slice(1)) + '</button>').join('') +
      '</div>' +
      // Status filter
      '<div style="display:flex;gap:4px;">' +
      statuses.map(s => '<button class="filter-btn ' + (s===assetStatusFilter?'active':'') + '" data-status="' + s + '" style="font-size:10px;padding:4px 8px;">' + (s==='all'?'Any Status':s.charAt(0).toUpperCase()+s.slice(1)) + '</button>').join('') +
      '</div>' +
      // Column toggle
      '<button id="col-toggle-btn" class="filter-btn" style="font-size:10px;padding:4px 8px;">' +
      '<svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/></svg> Columns</button>' +
      // Saved views
      '<button id="save-view-btn" class="filter-btn" style="font-size:10px;padding:4px 8px;">' +
      '<svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M19 21H5a2 2 0 01-2-2V5a2 2 0 012-2h11l5 5v11a2 2 0 01-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/></svg> Save View</button>' +
      '<button id="csv-export-btn" class="filter-btn" style="font-size:10px;padding:4px 8px;"><svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg> Export CSV</button>' +
      '<button id="csv-import-btn" class="filter-btn" style="font-size:10px;padding:4px 8px;"><svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg> Import CSV</button>' +
      '<input type="file" id="csv-file-input" accept=".csv" style="display:none">' +
      '</div>';

    // Column toggle popup
    document.getElementById('col-toggle-btn').addEventListener('click', function(e) {
      e.stopPropagation();
      let popup = document.getElementById('col-popup');
      if (popup) { popup.remove(); return; }
      popup = document.createElement('div');
      popup.id = 'col-popup';
      popup.style.cssText = 'position:absolute;z-index:100;background:var(--bg-card-solid);border:1px solid var(--border-light);border-radius:10px;padding:12px;box-shadow:0 8px 32px rgba(0,0,0,0.4);min-width:180px;';
      popup.innerHTML = '<div style="font-size:11px;font-weight:600;color:var(--text-secondary);margin-bottom:8px;text-transform:uppercase;letter-spacing:1px;">Visible Columns</div>' +
        allAssetColumns.map(c => '<label style="display:flex;align-items:center;gap:6px;padding:4px 0;font-size:12px;color:var(--text-primary);cursor:pointer;"><input type="checkbox" data-col="' + c.key + '" ' + (assetColumns.includes(c.key)?'checked':'') + ' style="accent-color:var(--accent);"> ' + c.label + '</label>').join('');
      this.parentElement.appendChild(popup);
      popup.querySelectorAll('input').forEach(cb => cb.addEventListener('change', function() {
        if (this.checked && !assetColumns.includes(this.dataset.col)) assetColumns.push(this.dataset.col);
        else assetColumns = assetColumns.filter(c => c !== this.dataset.col);
        localStorage.setItem('aevus_asset_columns', JSON.stringify(assetColumns));
        renderAssetsTable(currentAssetFilter);
      }));
      document.addEventListener('click', function handler() { popup.remove(); document.removeEventListener('click', handler); });
    // CSV Export
    document.getElementById("csv-export-btn").addEventListener("click", async function() {
      try {
        var h = {}; if (API_KEY) h["X-API-Key"] = API_KEY;
        var r = await fetch(API + "/csv/export", { headers: h });
        if (!r.ok) throw new Error("Export failed: " + r.status);
        var blob = await r.blob();
        var url = URL.createObjectURL(blob);
        var a = document.createElement("a"); a.href = url;
        a.download = "aevus_assets.csv"; a.click();
        URL.revokeObjectURL(url);
      } catch (e) { alert("CSV export error: " + e.message); }
    });
    // CSV Import
    document.getElementById("csv-import-btn").addEventListener("click", function() {
      document.getElementById("csv-file-input").click();
    });
    document.getElementById("csv-file-input").addEventListener("change", async function() {
      if (!this.files.length) return;
      try {
        var fd = new FormData(); fd.append("file", this.files[0]);
        var h = {}; if (API_KEY) h["X-API-Key"] = API_KEY;
        var r = await fetch(API + "/csv/import", { method: "POST", headers: h, body: fd });
        if (!r.ok) throw new Error("Import failed: " + r.status);
        var result = await r.json();
        alert("Imported: " + result.imported + ", Skipped: " + result.skipped +
          (result.errors.length ? "\nErrors:\n" + result.errors.join("\n") : ""));
        this.value = "";
        await fetchAssets(); renderAssetsPage();
      } catch (e) { alert("CSV import error: " + e.message); }
    });

    });

    // Save view
    document.getElementById('save-view-btn').addEventListener('click', function() {
      const name = prompt('View name:');
      if (!name) return;
      const views = JSON.parse(localStorage.getItem('aevus_saved_views') || '[]');
      views.push({name, columns: [...assetColumns], type: currentAssetFilter, status: assetStatusFilter, sort: assetSortCol, dir: assetSortDir});
      localStorage.setItem('aevus_saved_views', JSON.stringify(views));
      alert('View "' + name + '" saved');
    });

    // Search handler
    document.getElementById('asset-search').addEventListener('input', function() {
      assetSearchTerm = this.value.toLowerCase();
      renderAssetsTable(currentAssetFilter);
    });

    // Type filter handlers
    fb.querySelectorAll('[data-type]').forEach(b => b.addEventListener('click', () => {
      fb.querySelectorAll('[data-type]').forEach(x => x.classList.remove('active'));
      b.classList.add('active');
      currentAssetFilter = b.dataset.type;
      renderAssetsTable(b.dataset.type);
    }));

    // Status filter handlers
    fb.querySelectorAll('[data-status]').forEach(b => b.addEventListener('click', () => {
      fb.querySelectorAll('[data-status]').forEach(x => x.classList.remove('active'));
      b.classList.add('active');
      assetStatusFilter = b.dataset.status;
      renderAssetsTable(currentAssetFilter);
    }));

    renderAssetsTable(currentAssetFilter || 'all');
  }

  function renderAssetsTable(typeFilter) {
    const wrap = document.getElementById('assets-table-wrap');
    let filtered = typeFilter === 'all' ? [...liveAssets] : liveAssets.filter(a => a.type === typeFilter);

    // Status filter
    if (assetStatusFilter !== 'all') filtered = filtered.filter(a => (a.status||'unknown') === assetStatusFilter);

    // Search filter
    if (assetSearchTerm) {
      filtered = filtered.filter(a => {
        const searchable = [a.id, a.name, a.type, a.status, a.protocol, a.ip_address, a.vendor, a.model, a.location].join(' ').toLowerCase();
        return searchable.includes(assetSearchTerm);
      });
    }

    // Sort
    filtered.sort((a, b) => {
      let va = a[assetSortCol], vb = b[assetSortCol];
      if (assetSortCol === 'health') { va = va||0; vb = vb||0; }
      if (assetSortCol === 'last_seen') { va = va||''; vb = vb||''; }
      if (typeof va === 'number' && typeof vb === 'number') return assetSortDir === 'asc' ? va - vb : vb - va;
      va = String(va||'').toLowerCase(); vb = String(vb||'').toLowerCase();
      return assetSortDir === 'asc' ? va.localeCompare(vb) : vb.localeCompare(va);
    });

    const sortIcon = (col) => assetSortCol === col ? (assetSortDir === 'asc' ? ' ▲' : ' ▼') : '';
    const colDefs = {
      id: (a) => '<td class="mono" style="color:var(--accent);font-weight:600;">' + a.id + '</td>',
      name: (a) => '<td style="font-weight:500;color:var(--text-primary);">' + a.name + '</td>',
      type: (a) => '<td class="mono">' + a.type + '</td>',
      status: (a) => '<td>' + statusPill(a.status,a.health) + '</td>',
      health: (a) => '<td><div class="health-bar-wrap"><div class="health-bar"><div class="health-bar-fill ' + hClass(a.status,a.health) + '" style="width:' + (a.health||0) + '%"></div></div><span class="health-bar-val" style="color:var(--status-' + (hClass(a.status,a.health)==='good'?'good':hClass(a.status,a.health)==='warn'?'warn':hClass(a.status,a.health)==='bad'?'bad':'offline') + ');">' + (a.health!=null?a.health:'—') + '</span></div></td>',
      protocol: (a) => '<td class="mono">' + (protocolMap[a.protocol]||a.protocol||'—') + '</td>',
      ip_address: (a) => '<td class="mono">' + (a.ip_address||'—') + '</td>',
      last_seen: (a) => '<td class="mono">' + timeAgo(a.last_seen) + '</td>',
      vitals: (a) => '<td style="font-size:10px;color:var(--text-muted);max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' + ((a.vitals||[]).slice(0,3).map(v=>v.label+': '+v.value).join(' · ')||'—') + '</td>',
      vendor: (a) => '<td class="mono">' + (a.vendor||'—') + '</td>',
      model: (a) => '<td class="mono">' + (a.model||'—') + '</td>',
      location: (a) => '<td class="mono">' + (a.location||'—') + '</td>',
      poll_interval: (a) => '<td class="mono">' + (a.poll_interval||'—') + 's</td>',
    };
    const colLabels = {id:'ID',name:'Name',type:'Type',status:'Status',health:'Health',protocol:'Protocol',ip_address:'IP Address',last_seen:'Last Seen',vitals:'Vitals',vendor:'Vendor',model:'Model',location:'Location',poll_interval:'Poll'};

    const headers = assetColumns.map(c => '<th style="cursor:pointer;user-select:none;" data-sort="' + c + '">' + (colLabels[c]||c) + sortIcon(c) + '</th>').join('');
    const rows = filtered.map(a => '<tr style="cursor:pointer;" onclick="window.openAssetDrawer(\'' + a.id + '\')">' + assetColumns.map(c => colDefs[c]?colDefs[c](a):'<td>—</td>').join('') + '</tr>').join('');

    wrap.innerHTML = '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;"><span style="font-size:11px;color:var(--text-muted);">' + filtered.length + ' of ' + liveAssets.length + ' assets</span></div>' +
      '<table class="data-table"><thead><tr>' + headers + '</tr></thead><tbody>' + (rows || '<tr><td colspan="' + assetColumns.length + '" style="text-align:center;padding:40px;color:var(--text-muted);">No assets match filters</td></tr>') + '</tbody></table>';

    // Sort handlers
    wrap.querySelectorAll('th[data-sort]').forEach(th => th.addEventListener('click', () => {
      if (assetSortCol === th.dataset.sort) assetSortDir = assetSortDir === 'asc' ? 'desc' : 'asc';
      else { assetSortCol = th.dataset.sort; assetSortDir = 'asc'; }
      renderAssetsTable(currentAssetFilter);
    }));
  }


  // ═══════════════════════════════════════
  // PAGE: HEALTH
  // ═══════════════════════════════════════
  
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
    const sevCounts = {all:liveAlerts.length, critical:liveAlerts.filter(a=>a.severity==='critical').length, warning:liveAlerts.filter(a=>a.severity==='warning').length, info:liveAlerts.filter(a=>a.severity==='info').length};
    const statusCounts = {open:liveAlerts.filter(a=>a.status==='open').length, acknowledged:liveAlerts.filter(a=>a.status==='acknowledged').length, resolved:liveAlerts.filter(a=>a.status==='resolved').length};
    fb.innerHTML = `<div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center;">` +
      ['all','critical','warning','info'].map(f => {
        const clr = f==='critical'?'#EF4444':f==='warning'?'#FBBF24':f==='info'?'#06B6D4':'var(--text-primary)';
        return `<button class="filter-btn sev-filter ${f===currentAlertFilter?'active':''}" data-sev="${f}" style="${f===currentAlertFilter?'background:rgba(6,182,212,0.1);border-color:rgba(6,182,212,0.3);':''}">${f==='all'?'All':f.charAt(0).toUpperCase()+f.slice(1)} <span style="font-size:9px;padding:1px 5px;border-radius:8px;background:rgba(123,132,153,0.2);color:${clr};margin-left:4px;">${sevCounts[f]}</span></button>`;
      }).join('') +
      `<span style="width:1px;height:20px;background:var(--border);margin:0 8px;"></span>` +
      ['open','acknowledged','resolved'].map(s => {
        const clr = s==='open'?'var(--text-primary)':s==='acknowledged'?'#FBBF24':'#10D478';
        return `<button class="filter-btn status-filter ${s===currentAlertStatusFilter?'active':''}" data-status="${s}" style="${s===currentAlertStatusFilter?'background:rgba(6,182,212,0.1);border-color:rgba(6,182,212,0.3);':''}">${s.charAt(0).toUpperCase()+s.slice(1)} <span style="font-size:9px;padding:1px 5px;border-radius:8px;background:rgba(123,132,153,0.2);color:${clr};margin-left:4px;">${statusCounts[s]}</span></button>`;
      }).join('') + `</div>`;
    fb.querySelectorAll('.sev-filter').forEach(b => b.addEventListener('click', () => {
      currentAlertFilter = b.dataset.sev;
      fb.querySelectorAll('.sev-filter').forEach(x => x.classList.remove('active'));
      b.classList.add('active');
      renderAlertsList();
    }));
    fb.querySelectorAll('.status-filter').forEach(b => b.addEventListener('click', () => {
      currentAlertStatusFilter = b.dataset.status;
      fb.querySelectorAll('.status-filter').forEach(x => x.classList.remove('active'));
      b.classList.add('active');
      renderAlertsList();
    }));
    renderAlertsList();
  }

  function renderAlertsList() {
    const el = document.getElementById('alerts-full-list');
    let filtered = currentAlertFilter === 'all' ? [...liveAlerts] : liveAlerts.filter(a => a.severity === currentAlertFilter);
    filtered = filtered.filter(a => a.status === currentAlertStatusFilter);
    if (filtered.length === 0) {
      el.innerHTML = '<div style="padding:40px;text-align:center;color:var(--text-muted);font-size:13px;">No alerts matching filter</div>';
      return;
    }
    el.innerHTML = `<div style="display:flex;flex-direction:column;gap:8px;">${filtered.map(a => alertCardHTML(a, true)).join('')}</div>`;
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
  // PAGE: TRENDS (Interactive)
  // ═══════════════════════════════════════

  const TREND_CATEGORIES = [
    {
      id: 'process', label: 'Process',
      color: '#10D478', colorDim: 'rgba(16,212,120,0.12)', borderColor: 'rgba(16,212,120,0.3)',
      icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg>',
      metrics: [
        { key: 'suction_pressure', label: 'Suction Press', unit: 'PSI', asset: 'RTU-01' },
        { key: 'discharge_pressure', label: 'Discharge Press', unit: 'PSI', asset: 'RTU-01' },
        { key: 'casing_pressure', label: 'Casing Press', unit: 'PSI', asset: 'RTU-01' },
        { key: 'tubing_pressure', label: 'Tubing Press', unit: 'PSI', asset: 'RTU-01' },
        { key: 'flow_rate', label: 'Flow Rate', unit: 'MCFD', asset: 'RTU-01' },
        { key: 'oil_production', label: 'Oil Production', unit: 'BOPD', asset: 'RTU-01' },
      ]
    },
    {
      id: 'mechanical', label: 'Mechanical',
      color: '#FBBF24', colorDim: 'rgba(245,158,11,0.12)', borderColor: 'rgba(245,158,11,0.3)',
      icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>',
      metrics: [
        { key: 'vibration', label: 'Vibration', unit: 'mm/s', asset: 'RTU-01' },
        { key: 'motor_current', label: 'Motor Current', unit: 'A', asset: 'RTU-01' },
        { key: 'compressor_rpm', label: 'Compressor RPM', unit: 'RPM', asset: 'RTU-01' },
        { key: 'oil_pressure', label: 'Oil Pressure', unit: 'PSI', asset: 'RTU-01' },
        { key: 'run_hours', label: 'Run Hours', unit: 'hrs', asset: 'RTU-01' },
      ]
    },
    {
      id: 'thermal', label: 'Thermal',
      color: '#EF4444', colorDim: 'rgba(239,68,68,0.12)', borderColor: 'rgba(239,68,68,0.3)',
      icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M14 14.76V3.5a2.5 2.5 0 0 0-5 0v11.26a4.5 4.5 0 1 0 5 0z"/></svg>',
      metrics: [
        { key: 'gas_temp', label: 'Gas Temp', unit: '°F', asset: 'RTU-01' },
        { key: 'interstage_temp', label: 'Interstage', unit: '°F', asset: 'RTU-01' },
        { key: 'coolant_temp', label: 'Coolant', unit: '°F', asset: 'RTU-01' },
        { key: 'ambient_temp', label: 'Ambient', unit: '°F', asset: 'RTU-01' },
      ]
    },
    {
      id: 'power', label: 'Power & Levels',
      color: '#A78BFA', colorDim: 'rgba(167,139,250,0.12)', borderColor: 'rgba(167,139,250,0.3)',
      icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/></svg>',
      metrics: [
        { key: 'battery_voltage', label: 'Battery', unit: 'VDC', asset: 'RTU-01' },
        { key: 'solar_voltage', label: 'Solar', unit: 'VDC', asset: 'RTU-01' },
        { key: 'separator_level', label: 'Separator Lvl', unit: '%', asset: 'RTU-01' },
        { key: 'oil_tank_level', label: 'Oil Tank Lvl', unit: 'in', asset: 'RTU-01' },
        { key: 'water_tank_level', label: 'Water Tank Lvl', unit: 'in', asset: 'RTU-01' },
      ]
    },
    {
      id: 'network', label: 'Network & Comm',
      color: '#06B6D4', colorDim: 'rgba(6,182,212,0.12)', borderColor: 'rgba(6,182,212,0.3)',
      icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M5 12.55a11 11 0 0 1 14 0"/><path d="M1.42 9a16 16 0 0 1 21.16 0"/><path d="M8.53 16.11a6 6 0 0 1 6.95 0"/><line x1="12" y1="20" x2="12.01" y2="20"/></svg>',
      metrics: [
        { key: 'cpu_load', label: 'CPU Load', unit: '%', asset: null },
        { key: 'memory', label: 'Memory', unit: '%', asset: null },
        { key: 'rssi', label: 'Radio RSSI', unit: 'dBm', asset: null },
        { key: 'snr', label: 'Radio SNR', unit: 'dB', asset: null },
      ]
    },
    {
      id: 'safety', label: 'Safety & Gas',
      color: '#06B6D4', colorDim: 'rgba(6,182,212,0.12)', borderColor: 'rgba(6,182,212,0.3)',
      icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>',
      metrics: [
        { key: 'h2s', label: 'H₂S', unit: 'PPM', asset: 'RTU-01' },
        { key: 'lel', label: 'LEL', unit: '%LEL', asset: 'RTU-01' },
        { key: 'water_cut', label: 'Water Cut', unit: '%', asset: 'RTU-01' },
      ]
    },
  ];

  let currentTrendCategory = 'process';
  let trendHours = 24;
  let trendChartData = {};
  let focusedMetric = null; // when user clicks a KPI or search result

  // ── All metrics flat for search ──
  function getAllMetrics() {
    const all = [];
    for (const cat of TREND_CATEGORIES) {
      for (const m of cat.metrics) {
        all.push({ ...m, category: cat.id, catLabel: cat.label, color: cat.color, colorDim: cat.colorDim, borderColor: cat.borderColor });
      }
    }
    return all;
  }

  // ── Search ──
  function initTrendSearch() {
    const input = document.getElementById('trend-search');
    const results = document.getElementById('trend-search-results');
    if (!input || !results) return;
    
    input.addEventListener('input', () => {
      const q = input.value.trim().toLowerCase();
      if (q.length < 2) { results.style.display = 'none'; return; }
      const all = getAllMetrics();
      const matches = all.filter(m =>
        m.label.toLowerCase().includes(q) ||
        m.key.toLowerCase().includes(q) ||
        m.unit.toLowerCase().includes(q) ||
        m.catLabel.toLowerCase().includes(q)
      );
      if (matches.length === 0) {
        results.style.display = 'block';
        results.innerHTML = '<div style="padding:14px;color:var(--text-muted);font-size:12px;">No metrics matching "' + q + '"</div>';
        return;
      }
      results.style.display = 'block';
      results.innerHTML = matches.map(m =>
        '<div class="trend-search-item" data-key="' + m.key + '" data-cat="' + m.category + '" style="padding:10px 14px;cursor:pointer;display:flex;align-items:center;gap:10px;border-bottom:1px solid var(--border);transition:background 0.15s;" onmouseenter="this.style.background=\'var(--bg-card-hover)\'" onmouseleave="this.style.background=\'transparent\'">' +
          '<div style="width:4px;height:28px;border-radius:2px;background:' + m.color + ';flex-shrink:0;"></div>' +
          '<div style="flex:1;">' +
            '<div style="font-size:12px;font-weight:600;color:var(--text-primary);">' + m.label + '</div>' +
            '<div style="font-size:10px;color:var(--text-muted);">' + m.catLabel + ' · ' + m.unit + (m.asset ? ' · ' + m.asset : ' · All assets') + '</div>' +
          '</div>' +
          '<div style="font-family:var(--font-mono);font-size:10px;color:' + m.color + ';padding:2px 8px;border-radius:4px;background:' + m.colorDim + ';">' + m.key + '</div>' +
        '</div>'
      ).join('');

      results.querySelectorAll('.trend-search-item').forEach(el => {
        el.addEventListener('click', () => {
          const key = el.dataset.key;
          const catId = el.dataset.cat;
          input.value = '';
          results.style.display = 'none';
          // Switch category and focus the metric
          currentTrendCategory = catId;
          focusedMetric = key;
          renderTrendsPageContent();
        });
      });
    });

    // Close dropdown on outside click
    document.addEventListener('click', (e) => {
      if (!input.contains(e.target) && !results.contains(e.target)) {
        results.style.display = 'none';
      }
    });
  }

  // ── Time range selector ──
  function renderTimeBar() {
    const bar = document.getElementById('trend-time-bar');
    if (!bar) return;
    const ranges = [
      { h: 1, label: '1H' },
      { h: 6, label: '6H' },
      { h: 12, label: '12H' },
      { h: 24, label: '24H' },
      { h: 72, label: '3D' },
      { h: 168, label: '7D' },
    ];
    bar.innerHTML = ranges.map(r =>
      '<button class="filter-btn' + (r.h === trendHours ? ' active' : '') + '" data-hours="' + r.h + '" style="padding:5px 12px;font-size:10px;' + (r.h === trendHours ? 'background:var(--accent-dim);color:var(--accent-light);border-color:rgba(6,182,212,0.3);' : '') + '">' + r.label + '</button>'
    ).join('');
    bar.querySelectorAll('.filter-btn').forEach(b => b.addEventListener('click', async () => {
      trendHours = parseInt(b.dataset.hours);
      bar.querySelectorAll('.filter-btn').forEach(x => { x.classList.remove('active'); x.style.background=''; x.style.color=''; x.style.borderColor=''; });
      b.classList.add('active');
      b.style.background = 'var(--accent-dim)'; b.style.color = 'var(--accent-light)'; b.style.borderColor = 'rgba(6,182,212,0.3)';
      await loadCategoryTrends();
      renderTrendCharts();
    }));
  }

  // ── Category bar ──
  function renderCategoryBar() {
    const bar = document.getElementById('trend-metric-bar');
    if (!bar) return;
    bar.innerHTML = TREND_CATEGORIES.map(cat =>
      '<button class="filter-btn ' + (cat.id===currentTrendCategory?'active':'') + '" data-cat="' + cat.id + '" style="' + (cat.id===currentTrendCategory ? 'background:'+cat.colorDim+';color:'+cat.color+';border-color:'+cat.borderColor : '') + '">' + cat.icon + '<span style="margin-left:4px;">' + cat.label + '</span></button>'
    ).join('');
    bar.querySelectorAll('.filter-btn').forEach(b => b.addEventListener('click', async () => {
      currentTrendCategory = b.dataset.cat;
      focusedMetric = null;
      bar.querySelectorAll('.filter-btn').forEach(x => { x.classList.remove('active'); x.style.background=''; x.style.color=''; x.style.borderColor=''; });
      b.classList.add('active');
      const cat = TREND_CATEGORIES.find(c=>c.id===currentTrendCategory);
      if(cat){ b.style.background=cat.colorDim; b.style.color=cat.color; b.style.borderColor=cat.borderColor; }
      await loadCategoryTrends();
      renderTrendCharts();
    }));
  }

  async function renderTrendsPage() {
    renderTimeBar();
    initTrendSearch();
    await renderTrendsPageContent();
  }

  async function renderTrendsPageContent() {
    renderCategoryBar();
    await loadCategoryTrends();
    renderTrendCharts();
  }

  async function loadCategoryTrends() {
    const cat = TREND_CATEGORIES.find(c => c.id === currentTrendCategory);
    if (!cat) return;
    trendChartData = {};
    const promises = cat.metrics.map(async m => {
      const assetParam = m.asset ? '&asset_id=' + m.asset : '';
      const d = await fetchJSON('/health/trend?metric=' + m.key + '&hours=' + trendHours + assetParam);
      if (d && d.length > 0) trendChartData[m.key] = d;
    });
    await Promise.all(promises);
  }

  function renderTrendCharts() {
    const wrap = document.getElementById('trend-chart-wrap');
    const cat = TREND_CATEGORIES.find(c => c.id === currentTrendCategory);
    if (!cat || !wrap) return;

    let metricsWithData = cat.metrics.filter(m => trendChartData[m.key] && trendChartData[m.key].length > 0);
    
    // If a focused metric, show it first/highlighted
    const focusedM = focusedMetric ? cat.metrics.find(m => m.key === focusedMetric) : null;

    if (metricsWithData.length === 0) {
      wrap.innerHTML = '<div style="background:var(--bg-card);border:1px solid var(--border);border-radius:var(--card-radius);padding:40px;text-align:center;"><div style="color:var(--text-muted);font-size:13px;">No trend data for ' + cat.label + ' in the last ' + trendHours + 'h</div></div>';
      return;
    }

    const rangeLabel = trendHours <= 1 ? '1 hour' : trendHours <= 24 ? trendHours + 'h' : (trendHours/24) + ' day' + (trendHours>24?'s':'');
    let html = '';

    // KPI summary row — clickable cards
    html += '<div class="stat-grid" style="grid-template-columns:repeat(' + Math.min(metricsWithData.length, 6) + ',1fr);margin-bottom:20px;">';
    for (const m of metricsWithData) {
      const points = trendChartData[m.key];
      const latest = points[points.length - 1].value;
      const avg = points.reduce((s,p) => s + p.value, 0) / points.length;
      const min = Math.min(...points.map(p => p.value));
      const max = Math.max(...points.map(p => p.value));
      const displayVal = latest % 1 === 0 ? latest.toFixed(0) : latest.toFixed(1);
      const isFocused = focusedMetric === m.key;
      const focusStyle = isFocused ? 'box-shadow:0 0 0 2px ' + cat.color + ',var(--shadow-card);transform:scale(1.02);' : '';

      html += '<div class="stat-card" style="border-top:2px solid ' + cat.color + ';cursor:pointer;transition:all 0.2s;' + focusStyle + '" onclick="window.focusTrendMetric(\'' + m.key + '\')" onmouseenter="this.style.borderColor=\'' + cat.color + '\';this.style.boxShadow=\'0 0 0 1px ' + cat.color + ',var(--shadow-card)\'" onmouseleave="this.style.boxShadow=\'' + (isFocused ? '0 0 0 2px ' + cat.color + ',var(--shadow-card)' : 'var(--shadow-card)') + '\'">';
      html += '<div class="stat-card-label">' + m.label + '</div>';
      html += '<div class="stat-card-value" style="color:' + cat.color + ';">' + displayVal + ' <span style="font-size:11px;color:var(--text-muted);">' + m.unit + '</span></div>';
      html += '<div class="stat-card-sub">Avg ' + avg.toFixed(1) + ' · Min ' + min.toFixed(1) + ' · Max ' + max.toFixed(1) + '</div>';
      html += '</div>';
    }
    html += '</div>';

    // If focused metric, show expanded single chart first
    if (focusedM && trendChartData[focusedM.key]) {
      html += renderExpandedChart(focusedM, cat);
    }

    // Chart grid — 2 columns (skip focused if already shown expanded)
    const chartMetrics = focusedM ? metricsWithData.filter(m => m.key !== focusedM.key) : metricsWithData;
    if (chartMetrics.length > 0) {
      if (focusedM) html += '<div class="section-title" style="margin-top:20px;">Other ' + cat.label + ' Metrics</div>';
      html += '<div style="display:grid;grid-template-columns:repeat(2,1fr);gap:16px;">';
      for (const m of chartMetrics) {
        html += renderCompactChart(m, cat);
      }
      html += '</div>';
    }

    wrap.innerHTML = html;
    // Scroll focused chart into view
    if (focusedM) {
      const expanded = document.getElementById('expanded-chart');
      if (expanded) expanded.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  }

  // Expanded single-metric chart (when focused)
  function renderExpandedChart(m, cat) {
    const points = trendChartData[m.key];
    const byAsset = {};
    points.forEach(p => { const aid = p.asset_id || 'RTU-01'; if (!byAsset[aid]) byAsset[aid] = []; byAsset[aid].push(p); });

    let html = '';
    for (const [assetId, assetPoints] of Object.entries(byAsset)) {
      const maxVal = Math.max(...assetPoints.map(p => p.value), 0.01);
      const minVal = Math.min(...assetPoints.map(p => p.value));
      const range = maxVal - minVal || 1;
      const avg = assetPoints.reduce((s,p) => s + p.value, 0) / assetPoints.length;
      const latest = assetPoints[assetPoints.length - 1].value;
      const latestDisplay = latest % 1 === 0 ? latest.toFixed(0) : latest.toFixed(1);
      const assetLabel = m.asset ? '' : ' · ' + assetId;

      // Build interactive bars — each bar has onclick for detail
      const displayPoints = assetPoints.slice(-120);
      const bars = displayPoints.map((p, i) => {
        const pct = Math.max(3, ((p.value - minVal) / range) * 100);
        const ts = new Date(p.time);
        const timeStr = ts.toLocaleTimeString('en-US', { hour:'2-digit', minute:'2-digit', second:'2-digit' });
        const dateStr = ts.toLocaleDateString('en-US', { month:'short', day:'numeric' });
        return '<div class="bar-col" style="height:' + pct + '%;background:' + cat.color + ';opacity:0.75;cursor:pointer;" title="' + p.value.toFixed(2) + ' ' + m.unit + ' at ' + timeStr + '" onclick="window.showTrendDetail(\'' + m.key + '\',\'' + m.label + '\',\'' + m.unit + '\',\'' + cat.color + '\',' + i + ',\'' + assetId + '\')" onmouseenter="this.style.opacity=1;this.style.boxShadow=\'0 0 8px ' + cat.color + '\'" onmouseleave="this.style.opacity=0.75;this.style.boxShadow=\'none\'"></div>';
      }).join('');

      const first = displayPoints.length > 0 ? new Date(displayPoints[0].time).toLocaleTimeString('en-US',{hour:'2-digit',minute:'2-digit'}) : '';
      const last = displayPoints.length > 0 ? new Date(displayPoints[displayPoints.length-1].time).toLocaleTimeString('en-US',{hour:'2-digit',minute:'2-digit'}) : '';

      html += '<div id="expanded-chart" class="chart-container" style="border:1px solid ' + cat.borderColor + ';box-shadow:0 0 20px ' + cat.colorDim + ';">';
      html += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">';
      html += '<div>';
      html += '<div style="font-size:16px;font-weight:700;color:var(--text-primary);display:flex;align-items:center;gap:8px;">' + m.label + assetLabel;
      html += ' <span style="font-size:10px;padding:2px 8px;border-radius:4px;background:' + cat.colorDim + ';color:' + cat.color + ';">FOCUSED</span>';
      html += ' <button style="font-size:10px;padding:2px 8px;border-radius:4px;background:rgba(255,255,255,0.05);color:var(--text-muted);border:1px solid var(--border);cursor:pointer;" onclick="window.focusTrendMetric(null)">Clear</button>';
      html += '</div>';
      html += '<div style="font-size:11px;color:var(--text-muted);margin-top:2px;">' + trendHours + 'h trend · ' + assetPoints.length + ' samples · Click any bar for details</div>';
      html += '</div>';
      html += '<div style="text-align:right;">';
      html += '<div style="font-family:var(--font-mono);font-size:32px;font-weight:700;color:' + cat.color + ';">' + latestDisplay + '</div>';
      html += '<div style="font-size:11px;color:var(--text-muted);">' + m.unit + ' · LIVE</div>';
      html += '</div></div>';

      // Stats row
      html += '<div style="display:flex;gap:16px;margin:12px 0;padding:10px 0;border-top:1px solid var(--border);border-bottom:1px solid var(--border);">';
      html += '<div style="flex:1;text-align:center;"><div style="font-size:9px;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.5px;">Average</div><div style="font-family:var(--font-mono);font-size:16px;font-weight:600;color:var(--text-primary);">' + avg.toFixed(2) + '</div></div>';
      html += '<div style="flex:1;text-align:center;"><div style="font-size:9px;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.5px;">Minimum</div><div style="font-family:var(--font-mono);font-size:16px;font-weight:600;color:var(--status-good);">' + minVal.toFixed(2) + '</div></div>';
      html += '<div style="flex:1;text-align:center;"><div style="font-size:9px;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.5px;">Maximum</div><div style="font-family:var(--font-mono);font-size:16px;font-weight:600;color:var(--status-bad);">' + maxVal.toFixed(2) + '</div></div>';
      html += '<div style="flex:1;text-align:center;"><div style="font-size:9px;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.5px;">Spread</div><div style="font-family:var(--font-mono);font-size:16px;font-weight:600;color:var(--text-secondary);">' + range.toFixed(2) + '</div></div>';
      html += '<div style="flex:1;text-align:center;"><div style="font-size:9px;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.5px;">Samples</div><div style="font-family:var(--font-mono);font-size:16px;font-weight:600;color:var(--text-secondary);">' + assetPoints.length + '</div></div>';
      html += '</div>';

      html += '<div class="bar-chart" style="height:160px;">' + bars + '</div>';
      html += '<div class="chart-labels"><span>' + first + '</span><span>' + last + '</span></div>';
      html += '</div>';
    }
    return html;
  }

  // Compact chart for grid view
  function renderCompactChart(m, cat) {
    const points = trendChartData[m.key];
    if (!points) return '';
    const byAsset = {};
    points.forEach(p => { const aid = p.asset_id || 'RTU-01'; if (!byAsset[aid]) byAsset[aid] = []; byAsset[aid].push(p); });

    let html = '';
    for (const [assetId, assetPoints] of Object.entries(byAsset)) {
      const maxVal = Math.max(...assetPoints.map(p => p.value), 0.01);
      const minVal = Math.min(...assetPoints.map(p => p.value));
      const range = maxVal - minVal || 1;
      const avg = assetPoints.reduce((s,p) => s + p.value, 0) / assetPoints.length;
      const latest = assetPoints[assetPoints.length - 1].value;
      const latestDisplay = latest % 1 === 0 ? latest.toFixed(0) : latest.toFixed(1);
      const assetLabel = m.asset ? '' : ' · ' + assetId;

      const displayPoints = assetPoints.slice(-72);
      const bars = displayPoints.map((p, i) => {
        const pct = Math.max(3, ((p.value - minVal) / range) * 100);
        return '<div class="bar-col" style="height:' + pct + '%;background:' + cat.color + ';opacity:0.7;cursor:pointer;" title="' + p.value.toFixed(2) + ' ' + m.unit + '" onclick="window.focusTrendMetric(\'' + m.key + '\')" onmouseenter="this.style.opacity=1" onmouseleave="this.style.opacity=0.7"></div>';
      }).join('');

      const first = displayPoints.length > 0 ? new Date(displayPoints[0].time).toLocaleTimeString('en-US',{hour:'2-digit',minute:'2-digit'}) : '';
      const last = displayPoints.length > 0 ? new Date(displayPoints[displayPoints.length-1].time).toLocaleTimeString('en-US',{hour:'2-digit',minute:'2-digit'}) : '';

      html += '<div class="chart-container" style="border-top:2px solid ' + cat.color + ';cursor:pointer;" onclick="window.focusTrendMetric(\'' + m.key + '\')">';
      html += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">';
      html += '<div>';
      html += '<div style="font-size:13px;font-weight:600;color:var(--text-primary);">' + m.label + assetLabel + '</div>';
      html += '<div style="font-size:10px;color:var(--text-muted);margin-top:2px;">' + assetPoints.length + ' samples · Avg ' + avg.toFixed(1) + ' ' + m.unit + '</div>';
      html += '</div>';
      html += '<div style="text-align:right;">';
      html += '<div style="font-family:var(--font-mono);font-size:22px;font-weight:700;color:' + cat.color + ';">' + latestDisplay + '</div>';
      html += '<div style="font-size:10px;color:var(--text-muted);">' + m.unit + '</div>';
      html += '</div></div>';
      html += '<div class="bar-chart" style="height:100px;">' + bars + '</div>';
      html += '<div class="chart-labels"><span>' + first + '</span><span>' + last + '</span></div>';
      html += '</div>';
    }
    return html;
  }

  // ── Focus a metric (from KPI click or search) ──
  window.focusTrendMetric = function(key) {
    focusedMetric = key === focusedMetric ? null : key;
    renderTrendCharts();
  };

  // ── Detail overlay for a clicked bar ──
  window.showTrendDetail = function(metricKey, label, unit, color, barIdx, assetId) {
    const points = trendChartData[metricKey];
    if (!points) return;
    const assetPoints = points.filter(p => (p.asset_id || 'RTU-01') === assetId);
    const displayPoints = assetPoints.slice(-120);
    const p = displayPoints[barIdx];
    if (!p) return;

    const ts = new Date(p.time);
    const avg = assetPoints.reduce((s,x) => s + x.value, 0) / assetPoints.length;
    const deviation = p.value - avg;
    const deviationPct = avg !== 0 ? ((deviation / avg) * 100).toFixed(1) : '0';
    const devColor = Math.abs(parseFloat(deviationPct)) > 10 ? 'var(--status-warn)' : 'var(--status-good)';

    // Find neighboring points for rate of change
    const prevIdx = barIdx > 0 ? barIdx - 1 : null;
    const prevP = prevIdx !== null ? displayPoints[prevIdx] : null;
    const rateOfChange = prevP ? (p.value - prevP.value) : null;
    const rateLabel = rateOfChange !== null ? (rateOfChange >= 0 ? '+' : '') + rateOfChange.toFixed(2) + ' ' + unit : 'N/A';
    const rateColor = rateOfChange === null ? 'var(--text-muted)' : rateOfChange > 0 ? 'var(--status-warn)' : rateOfChange < 0 ? 'var(--status-good)' : 'var(--text-muted)';

    const panel = document.getElementById('trend-detail-panel');
    panel.innerHTML =
      '<div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:20px;">' +
        '<div>' +
          '<div style="font-size:18px;font-weight:700;color:var(--text-primary);">' + label + '</div>' +
          '<div style="font-size:12px;color:var(--text-muted);margin-top:2px;">' + assetId + ' · ' + ts.toLocaleDateString('en-US', { weekday:'short', month:'short', day:'numeric', year:'numeric' }) + '</div>' +
        '</div>' +
        '<button style="width:28px;height:28px;border-radius:6px;border:1px solid var(--border);background:transparent;color:var(--text-muted);cursor:pointer;display:flex;align-items:center;justify-content:center;" onclick="window.closeTrendDetail()"><svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></button>' +
      '</div>' +

      '<div style="text-align:center;padding:20px 0;border-top:1px solid var(--border);border-bottom:1px solid var(--border);margin-bottom:20px;">' +
        '<div style="font-family:var(--font-mono);font-size:48px;font-weight:700;color:' + color + ';">' + p.value.toFixed(2) + '</div>' +
        '<div style="font-size:13px;color:var(--text-muted);">' + unit + ' at ' + ts.toLocaleTimeString('en-US', { hour:'2-digit', minute:'2-digit', second:'2-digit' }) + '</div>' +
      '</div>' +

      '<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:20px;">' +
        '<div style="text-align:center;padding:12px;border-radius:8px;background:var(--bg-card);border:1px solid var(--border);">' +
          '<div style="font-size:9px;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.5px;">Deviation from Avg</div>' +
          '<div style="font-family:var(--font-mono);font-size:18px;font-weight:700;color:' + devColor + ';">' + (deviation >= 0 ? '+' : '') + deviation.toFixed(2) + '</div>' +
          '<div style="font-size:10px;color:' + devColor + ';">' + deviationPct + '% from mean</div>' +
        '</div>' +
        '<div style="text-align:center;padding:12px;border-radius:8px;background:var(--bg-card);border:1px solid var(--border);">' +
          '<div style="font-size:9px;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.5px;">Rate of Change</div>' +
          '<div style="font-family:var(--font-mono);font-size:18px;font-weight:700;color:' + rateColor + ';">' + rateLabel + '</div>' +
          '<div style="font-size:10px;color:var(--text-muted);">vs previous sample</div>' +
        '</div>' +
        '<div style="text-align:center;padding:12px;border-radius:8px;background:var(--bg-card);border:1px solid var(--border);">' +
          '<div style="font-size:9px;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.5px;">Period Average</div>' +
          '<div style="font-family:var(--font-mono);font-size:18px;font-weight:700;color:var(--text-primary);">' + avg.toFixed(2) + '</div>' +
          '<div style="font-size:10px;color:var(--text-muted);">' + unit + ' over ' + trendHours + 'h</div>' +
        '</div>' +
      '</div>' +

      '<div style="font-size:11px;color:var(--text-muted);">' +
        '<div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid var(--border);"><span>Metric Key</span><span class="mono" style="color:var(--text-primary);">' + metricKey + '</span></div>' +
        '<div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid var(--border);"><span>Asset</span><span class="mono" style="color:var(--accent);">' + assetId + '</span></div>' +
        '<div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid var(--border);"><span>Timestamp (UTC)</span><span class="mono" style="color:var(--text-primary);">' + ts.toISOString() + '</span></div>' +
        '<div style="display:flex;justify-content:space-between;padding:6px 0;"><span>Sample Index</span><span class="mono" style="color:var(--text-primary);">' + (barIdx + 1) + ' of ' + displayPoints.length + '</span></div>' +
      '</div>';

    document.getElementById('trend-detail-overlay').style.display = 'block';
  };

  window.closeTrendDetail = function() {
    document.getElementById('trend-detail-overlay').style.display = 'none';
  };

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
  // WEATHER STRIP (Overview)
  // ═══════════════════════════════════════
  function renderWeatherStrip() {
    const el = document.getElementById('weather-strip');
    if (!el || !weatherData) return;
    el.style.display = 'grid';
    const w = weatherData;
    const condIcon = w.condition === 'clear' || w.condition === 'mostly_clear'
      ? '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>'
      : '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10z"/></svg>';
    const condLabel = (w.condition || '').replace(/_/g, ' ');
    const solarPct = Math.round((w.solar_production_factor || 0) * 100);
    const solarCol = solarPct > 60 ? 'var(--status-good)' : solarPct > 30 ? 'var(--status-warn)' : 'var(--text-muted)';

    el.innerHTML = `
      <div class="kpi-tile"><div class="weather-tile"><div class="weather-icon" style="background:rgba(245,158,11,0.12);color:#FBBF24;">${condIcon}</div><div><div class="weather-val">${w.temp_f != null ? Math.round(w.temp_f) + '°' : '—'}</div><div class="weather-label">${condLabel}</div></div></div></div>
      <div class="kpi-tile"><div class="weather-tile"><div class="weather-icon" style="background:rgba(6,182,212,0.12);color:var(--accent);"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M9.59 4.59A2 2 0 1 1 11 8H2m10.59 11.41A2 2 0 1 0 14 16H2m15.73-8.27A2.5 2.5 0 1 1 19.5 12H2"/></svg></div><div><div class="weather-val">${w.wind_mph != null ? Math.round(w.wind_mph) : '—'}<span style="font-size:12px;color:var(--text-muted);"> mph</span></div><div class="weather-label">Wind${w.wind_gust_mph ? ' · Gust ' + Math.round(w.wind_gust_mph) : ''}</div></div></div></div>
      <div class="kpi-tile"><div class="weather-tile"><div class="weather-icon" style="background:rgba(16,212,120,0.12);color:var(--status-good);"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/></svg></div><div><div class="weather-val" style="color:${solarCol};">${solarPct}%</div><div class="weather-label">Solar Factor</div><div class="solar-bar" style="width:80px;"><div class="solar-bar-fill" style="width:${solarPct}%;"></div></div></div></div></div>
      <div class="kpi-tile"><div class="weather-tile"><div class="weather-icon" style="background:rgba(167,139,250,0.12);color:#A78BFA;"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M17 18a5 5 0 0 0-10 0"/><line x1="12" y1="9" x2="12" y2="2"/><line x1="4.22" y1="10.22" x2="5.64" y2="11.64"/><line x1="1" y1="18" x2="3" y2="18"/><line x1="21" y1="18" x2="23" y2="18"/><line x1="18.36" y1="11.64" x2="19.78" y2="10.22"/></svg></div><div><div class="weather-val">${w.daylight_hours ? w.daylight_hours.toFixed(1) : '—'}<span style="font-size:12px;color:var(--text-muted);"> hrs</span></div><div class="weather-label">${w.is_daylight ? '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/></svg> Daylight' : '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg> Night'}</div></div></div></div>
      <div class="kpi-tile"><div class="weather-tile"><div class="weather-icon" style="background:rgba(6,182,212,0.12);color:#06B6D4;"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 2.69l5.66 5.66a8 8 0 1 1-11.31 0z"/></svg></div><div><div class="weather-val">${w.precip_in != null ? w.precip_in.toFixed(2) : '0'}<span style="font-size:12px;color:var(--text-muted);"> in</span></div><div class="weather-label">Precipitation</div></div></div></div>
    `;
  }

  // ═══════════════════════════════════════
  // CORRELATIONS (Overview)
  // ═══════════════════════════════════════
  function renderCorrelationsOverview() {
    const el = document.getElementById('correlations-panel');
    if (!el) return;
    if (!correlations || correlations.length === 0) {
      el.style.display = 'none';
      return;
    }
    el.style.display = 'block';
    el.innerHTML = '<div class="section-title">Cross-Domain Correlations</div>' +
      correlations.slice(0, 5).map(c => {
        const sev = c.severity || 'low';
        return '<div class="corr-card ' + sev + '">' +
          '<span class="corr-severity ' + sev + '">' + sev + '</span>' +
          '<div style="flex:1;"><div style="font-size:13px;font-weight:600;color:var(--text-primary);">' + (c.pattern || c.type || '—') + '</div>' +
          '<div style="font-size:11px;color:var(--text-muted);margin-top:2px;">' + (c.message || '') + '</div>' +
          '<div style="font-size:10px;color:var(--text-muted);margin-top:2px;">Assets: ' + ((c.assets || []).join(', ') || '—') + '</div></div>' +
          '<div style="font-size:10px;color:var(--text-muted);font-family:var(--font-mono);">' + timeAgo(c.detected_at) + '</div>' +
          '</div>';
      }).join('');
  }

  // ═══════════════════════════════════════
  // PAGE: WEATHER
  // ═══════════════════════════════════════

  const WX_ICONS = {
    clear: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="18.36" y1="4.22" x2="19.78" y2="5.64"/><line x1="4.22" y1="18.36" x2="5.64" y2="19.78"/></svg>',
    mostly_clear: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="10" cy="10" r="4"/><line x1="10" y1="2" x2="10" y2="4"/><line x1="3.27" y1="5.27" x2="4.69" y2="6.69"/><line x1="2" y1="12" x2="4" y2="12"/><line x1="16.73" y1="5.27" x2="15.31" y2="6.69"/><path d="M18 18H8a4 4 0 0 1-.76-7.93"/></svg>',
    partly_cloudy: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="10" cy="8" r="4"/><line x1="10" y1="1" x2="10" y2="3"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><path d="M18 18H8a4 4 0 0 1-.76-7.93A5 5 0 0 1 18 14a3 3 0 0 1 0 4z"/></svg>',
    overcast: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10z"/></svg>',
    fog: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><line x1="3" y1="8" x2="21" y2="8"/><line x1="5" y1="12" x2="19" y2="12"/><line x1="3" y1="16" x2="21" y2="16"/></svg>',
    drizzle: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10z"/><line x1="8" y1="19" x2="8" y2="21"/><line x1="12" y1="19" x2="12" y2="21"/></svg>',
    rain: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10z"/><line x1="8" y1="19" x2="8" y2="22"/><line x1="12" y1="19" x2="12" y2="22"/><line x1="16" y1="19" x2="16" y2="22"/></svg>',
    heavy_rain: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10z"/><line x1="7" y1="19" x2="6" y2="23"/><line x1="11" y1="19" x2="10" y2="23"/><line x1="15" y1="19" x2="14" y2="23"/></svg>',
    snow: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10z"/><circle cx="9" cy="19" r="0.5"/><circle cx="13" cy="17" r="0.5"/><circle cx="11" cy="21" r="0.5"/></svg>',
    heavy_snow: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2v4m0 12v4M4.93 4.93l2.83 2.83m8.48 8.48l2.83 2.83M2 12h4m12 0h4M4.93 19.07l2.83-2.83m8.48-8.48l2.83-2.83"/></svg>',
    showers: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10z"/><line x1="10" y1="19" x2="9" y2="22"/><line x1="14" y1="19" x2="13" y2="22"/></svg>',
    heavy_showers: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10z"/><polyline points="13 16 12 20 15 20"/></svg>',
    ice: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2v4m0 12v4M4.93 4.93l2.83 2.83m8.48 8.48l2.83 2.83M2 12h4m12 0h4"/><circle cx="12" cy="12" r="3"/></svg>',
    snow_showers: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10z"/><circle cx="10" cy="19" r="0.5"/><circle cx="14" cy="17" r="0.5"/></svg>',
    thunderstorm: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10z"/><polyline points="13 16 12 20 15 20"/></svg>',
    thunderstorm_hail: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10z"/><polyline points="13 16 12 20 15 20"/><circle cx="9" cy="20" r="1"/></svg>',
    unknown: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="2" x2="12" y2="14"/><circle cx="12" cy="18" r="3"/></svg>',
  };
  const WMO_MAP = {
    0:'clear',1:'mostly_clear',2:'partly_cloudy',3:'overcast',
    45:'fog',48:'fog',51:'drizzle',53:'drizzle',55:'drizzle',
    61:'rain',63:'rain',65:'heavy_rain',71:'snow',73:'snow',
    75:'heavy_snow',77:'ice',80:'showers',81:'showers',82:'heavy_showers',
    85:'snow_showers',86:'snow_showers',95:'thunderstorm',
    96:'thunderstorm_hail',99:'thunderstorm_hail'
  };

  async function renderWeatherPage() {
    // Fetch forecast + current
    const [_, fc] = await Promise.all([
      fetchWeather(),
      fetchJSON('/weather/forecast')
    ]);
    if (fc && !fc.error) forecastData = fc;

    renderWxCurrentBadge();
    renderWxConditions();
    renderWxSolarPanel();
    renderWxMap();
    renderWxHourlyStrip();
    renderWxDailyForecast();
    renderWxImpactPanel();
    renderWxWindChart();
    renderWxPrecipChart();
  }


  // ══════════════════════════════════════════════════════════════
  //  RADIO COMMUNICATIONS PAGE
  // ══════════════════════════════════════════════════════════════
  function renderRadioCommsPage() {
    var assets = liveAssets || [];
    var r1 = assets.find(function(a){return a.id==='RAD-01';});
    var r2 = assets.find(function(a){return a.id==='RAD-02';});

    var linkEl = document.getElementById('rc-link-badge');
    var metaEl = document.getElementById('rc-link-meta');
    if (linkEl && r1 && r2) {
      var r1Link = getVitalRaw(r1, 'link_state');
      var r2Link = getVitalRaw(r2, 'link_state');
      var bothLinked = r1Link == 1 && r2Link == 1;
      var r1Rssi = getVitalRaw(r1, 'rssi');
      var r2Rssi = getVitalRaw(r2, 'rssi');
      var r1Qual = getVitalRaw(r1, 'signal_quality');
      var r2Qual = getVitalRaw(r2, 'signal_quality');

      linkEl.innerHTML =
        '<span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:' + (bothLinked ? 'var(--status-good)' : 'var(--status-bad)') + ';animation:' + (bothLinked ? 'wxPulse 2s infinite' : 'none') + ';"></span>' +
        '<span style="font-size:13px;font-weight:700;color:' + (bothLinked ? 'var(--status-good)' : 'var(--status-bad)') + ';">' + (bothLinked ? 'LINKED' : 'NO LINK') + '</span>' +
        '<span style="font-size:11px;color:var(--text-muted);margin-left:12px;">Network: <span style="color:var(--accent);font-weight:600;">killdeer</span></span>' +
        '<span style="font-size:11px;color:var(--text-muted);margin-left:12px;">Band: <span style="color:var(--text-primary);">900 MHz</span></span>' +
        '<span style="font-size:11px;color:var(--text-muted);margin-left:12px;">Mode: <span style="color:var(--text-primary);">AP ↔ Remote</span></span>';

      metaEl.innerHTML =
        'Avg RSSI: <span style="color:var(--accent);font-weight:600;">' + ((r1Rssi+r2Rssi)/2).toFixed(0) + ' dBm</span>' +
        ' · Avg Quality: <span style="color:var(--accent);font-weight:600;">' + ((r1Qual+r2Qual)/2).toFixed(0) + '%</span>';
    }

    renderRadioPanel('rc-r1', r1);
    renderRadioPanel('rc-r2', r2);
    renderPacketFlow(r1, r2);
    renderSignalChart(r1, r2);
  }

  function getVitalRaw(asset, key) {
    if (!asset || !asset.vitals) return 0;
    var v = asset.vitals.find(function(v){return v.label.toLowerCase().replace(/ /g,'_') === key;});
    return v ? v.raw_value : 0;
  }

  function renderRadioPanel(prefix, asset) {
    var metricsEl = document.getElementById(prefix + '-metrics');
    var statusEl = document.getElementById(prefix + '-status');
    var infoEl = document.getElementById(prefix + '-info');
    if (!metricsEl || !asset) return;

    var voltage = getVitalRaw(asset, 'voltage');
    var temp = getVitalRaw(asset, 'temperature');
    var qual = getVitalRaw(asset, 'signal_quality');
    var rssi = getVitalRaw(asset, 'rssi');
    var txPow = getVitalRaw(asset, 'tx_power');
    var txPkts = getVitalRaw(asset, 'tx_packets');
    var rxPkts = getVitalRaw(asset, 'rx_packets');
    var txErr = getVitalRaw(asset, 'tx_error');
    var rxErr = getVitalRaw(asset, 'rx_error');
    var rxDrop = getVitalRaw(asset, 'rx_dropped');
    var totalPkts = txPkts + rxPkts;
    var errRate = totalPkts > 0 ? ((txErr + rxErr) / totalPkts * 100).toFixed(3) : '0.000';

    var rssiColor = rssi > -50 ? 'var(--status-good)' : rssi > -70 ? 'var(--status-warn)' : 'var(--status-bad)';

    statusEl.innerHTML =
      '<span style="display:inline-flex;align-items:center;gap:4px;padding:2px 8px;border-radius:4px;font-size:10px;font-weight:600;background:' +
      (asset.status==='good' ? 'rgba(16,212,120,0.15);color:var(--status-good)' : 'rgba(239,68,68,0.15);color:var(--status-bad)') + ';">' +
      '<span style="width:6px;height:6px;border-radius:50%;background:currentColor;"></span>' +
      asset.status.toUpperCase() + '</span>';

    metricsEl.innerHTML =
      rcMetric('RSSI', rssi + ' dBm', rssiColor, rssiGauge(qual)) +
      rcMetric('Signal Quality', qual + '%', qual > 80 ? 'var(--status-good)' : qual > 50 ? 'var(--status-warn)' : 'var(--status-bad)', '') +
      rcMetric('TX Power', txPow + ' dBm', 'var(--accent)', '') +
      rcMetric('Voltage', voltage.toFixed(1) + ' V', voltage > 10 ? 'var(--status-good)' : 'var(--status-bad)', '') +
      rcMetric('Temperature', temp + ' °C', temp < 50 ? 'var(--status-good)' : 'var(--status-warn)', '') +
      rcMetric('Error Rate', errRate + '%', parseFloat(errRate) < 1 ? 'var(--status-good)' : 'var(--status-bad)', '') +
      rcMetric('TX Packets', txPkts.toLocaleString(), 'var(--text-primary)', '') +
      rcMetric('RX Packets', rxPkts.toLocaleString(), 'var(--text-primary)', '') +
      rcMetric('Dropped', rxDrop.toLocaleString(), rxDrop === 0 ? 'var(--status-good)' : 'var(--status-bad)', '');

    infoEl.innerHTML =
      '<div style="display:flex;gap:16px;flex-wrap:wrap;">' +
      '<span>IP: <span style="color:var(--accent);">' + (asset.ip_address||'—') + '</span></span>' +
      '<span>Protocol: <span style="color:var(--text-primary);">' + (asset.protocol||'—').toUpperCase() + '</span></span>' +
      '<span>Poll: <span style="color:var(--text-primary);">' + (asset.poll_interval||30) + 's</span></span>' +
      '<span>Last: <span style="color:var(--text-primary);">' + timeAgo(asset.last_seen) + '</span></span>' +
      '</div>';
  }

  function rcMetric(label, value, color, sub) {
    return '<div style="background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:8px 10px;">' +
      '<div style="font-size:9px;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:2px;">' + label + '</div>' +
      '<div style="font-family:var(--font-mono);font-size:16px;font-weight:700;color:' + color + ';">' + value + '</div>' +
      (sub ? '<div style="font-size:9px;color:var(--text-muted);margin-top:1px;">' + sub + '</div>' : '') +
    '</div>';
  }

  function rssiGauge(pct) {
    var bars = '';
    for (var i = 0; i < 5; i++) {
      var filled = pct >= (i+1) * 20;
      bars += '<span style="display:inline-block;width:6px;height:' + (6 + i*3) + 'px;border-radius:1px;background:' + (filled ? 'var(--status-good)' : 'var(--border)') + ';margin-right:2px;vertical-align:bottom;"></span>';
    }
    return bars;
  }

  function renderPacketFlow(r1, r2) {
    var el = document.getElementById('rc-packet-flow');
    if (!el || !r1 || !r2) return;

    var r1tx = getVitalRaw(r1, 'tx_packets');
    var r1rx = getVitalRaw(r1, 'rx_packets');
    var r2tx = getVitalRaw(r2, 'tx_packets');
    var r2rx = getVitalRaw(r2, 'rx_packets');
    var r1err = getVitalRaw(r1, 'tx_error') + getVitalRaw(r1, 'rx_error');
    var r2err = getVitalRaw(r2, 'tx_error') + getVitalRaw(r2, 'rx_error');
    var maxPkt = Math.max(r1tx, r1rx, r2tx, r2rx, 1);

    el.innerHTML =
      '<div style="display:flex;align-items:center;gap:12px;margin-bottom:16px;">' +
        '<div style="flex:1;text-align:center;">' +
          '<div style="font-size:10px;font-weight:700;color:var(--accent);">RAD-01 MASTER</div>' +
          '<div style="font-size:9px;color:var(--text-muted);">192.168.88.11</div>' +
        '</div>' +
        '<div style="flex:2;">' +
          pktBar('TX →', r1tx, maxPkt, 'var(--accent)') +
          pktBar('← RX', r1rx, maxPkt, '#8b5cf6') +
        '</div>' +
        '<div style="width:40px;text-align:center;">' +
          '<svg viewBox="0 0 40 40" width="40" height="40"><circle cx="20" cy="20" r="16" fill="none" stroke="var(--border)" stroke-width="2"/><path d="M12 20h16M24 16l4 4-4 4" stroke="var(--status-good)" stroke-width="2" fill="none"/></svg>' +
          '<div style="font-size:8px;color:var(--status-good);font-weight:700;">RF LINK</div>' +
        '</div>' +
        '<div style="flex:2;">' +
          pktBar('TX →', r2tx, maxPkt, 'var(--accent)') +
          pktBar('← RX', r2rx, maxPkt, '#8b5cf6') +
        '</div>' +
        '<div style="flex:1;text-align:center;">' +
          '<div style="font-size:10px;font-weight:700;color:var(--accent);">RAD-02 REMOTE</div>' +
          '<div style="font-size:9px;color:var(--text-muted);">192.168.88.12</div>' +
        '</div>' +
      '</div>' +
      '<div style="display:flex;gap:24px;justify-content:center;margin-top:12px;">' +
        '<div style="text-align:center;"><div style="font-size:9px;color:var(--text-muted);">TOTAL PACKETS</div><div style="font-family:var(--font-mono);font-size:18px;font-weight:700;color:var(--accent);">' + (r1tx+r1rx+r2tx+r2rx).toLocaleString() + '</div></div>' +
        '<div style="text-align:center;"><div style="font-size:9px;color:var(--text-muted);">TOTAL ERRORS</div><div style="font-family:var(--font-mono);font-size:18px;font-weight:700;color:' + ((r1err+r2err)===0?'var(--status-good)':'var(--status-bad)') + ';">' + (r1err+r2err).toLocaleString() + '</div></div>' +
        '<div style="text-align:center;"><div style="font-size:9px;color:var(--text-muted);">LINK UPTIME</div><div style="font-family:var(--font-mono);font-size:18px;font-weight:700;color:var(--status-good);">100%</div></div>' +
      '</div>';
  }

  function pktBar(label, val, max, color) {
    var w = Math.max((val/max)*100, 2);
    return '<div style="display:flex;align-items:center;gap:6px;margin-bottom:4px;">' +
      '<span style="font-size:9px;color:var(--text-muted);width:30px;">' + label + '</span>' +
      '<div style="flex:1;height:12px;background:var(--surface);border-radius:3px;overflow:hidden;">' +
        '<div style="width:' + w + '%;height:100%;background:' + color + ';border-radius:3px;transition:width 0.5s;"></div>' +
      '</div>' +
      '<span style="font-family:var(--font-mono);font-size:10px;color:var(--text-primary);width:50px;text-align:right;">' + val.toLocaleString() + '</span>' +
    '</div>';
  }

  function renderSignalChart(r1, r2) {
    var el = document.getElementById('rc-signal-chart');
    if (!el || !r1 || !r2) return;

    var r1rssi = getVitalRaw(r1, 'rssi');
    var r2rssi = getVitalRaw(r2, 'rssi');
    var r1qual = getVitalRaw(r1, 'signal_quality');
    var r2qual = getVitalRaw(r2, 'signal_quality');
    var r1pwr = getVitalRaw(r1, 'tx_power');
    var r2pwr = getVitalRaw(r2, 'tx_power');

    function rssiArc(rssi, label, x) {
      var pct = Math.max(0, Math.min(100, (rssi - (-100)) / ((-20) - (-100)) * 100));
      var color = pct > 60 ? '#10b981' : pct > 30 ? '#f59e0b' : '#ef4444';
      var r = 45;
      var cx = x, cy = 65;
      var circumference = Math.PI * r;
      var filled = circumference * (pct / 100);
      var gap = circumference - filled;
      return '<g transform="translate(' + cx + ',' + cy + ')">' +
        '<path d="M-' + r + ',0 A' + r + ',' + r + ' 0 0,1 ' + r + ',0" fill="none" stroke="rgba(255,255,255,0.08)" stroke-width="10" stroke-linecap="round"/>' +
        '<path d="M-' + r + ',0 A' + r + ',' + r + ' 0 0,1 ' + r + ',0" fill="none" stroke="' + color + '" stroke-width="10" stroke-linecap="round" stroke-dasharray="' + filled.toFixed(1) + ' ' + gap.toFixed(1) + '"/>' +
        '<text x="0" y="-12" text-anchor="middle" fill="' + color + '" font-size="22" font-weight="700" font-family="monospace">' + rssi + '</text>' +
        '<text x="0" y="4" text-anchor="middle" fill="rgba(255,255,255,0.4)" font-size="10">dBm</text>' +
        '<text x="0" y="24" text-anchor="middle" fill="rgba(255,255,255,0.7)" font-size="11" font-weight="600">' + label + '</text>' +
        '<text x="-' + r + '" y="14" text-anchor="middle" fill="rgba(255,255,255,0.3)" font-size="8">-100</text>' +
        '<text x="' + r + '" y="14" text-anchor="middle" fill="rgba(255,255,255,0.3)" font-size="8">-20</text>' +
      '</g>';
    }

    el.innerHTML =
      '<svg viewBox="0 0 400 110" width="100%" style="max-height:140px;">' +
        rssiArc(r1rssi, 'RAD-01 RSSI', 100) +
        rssiArc(r2rssi, 'RAD-02 RSSI', 300) +
      '</svg>' +
      '<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:8px;">' +
        '<div style="display:flex;justify-content:space-around;">' +
          sigStat('Quality', r1qual + '%', r1qual > 80 ? 'var(--status-good)' : 'var(--status-warn)') +
          sigStat('TX Power', r1pwr + ' dBm', 'var(--accent)') +
          sigStat('Voltage', getVitalRaw(r1,'voltage').toFixed(1) + 'V', 'var(--text-primary)') +
        '</div>' +
        '<div style="display:flex;justify-content:space-around;">' +
          sigStat('Quality', r2qual + '%', r2qual > 80 ? 'var(--status-good)' : 'var(--status-warn)') +
          sigStat('TX Power', r2pwr + ' dBm', 'var(--accent)') +
          sigStat('Voltage', getVitalRaw(r2,'voltage').toFixed(1) + 'V', 'var(--text-primary)') +
        '</div>' +
      '</div>';
  }

  function sigStat(label, val, color) {
    return '<div style="text-align:center;">' +
      '<div style="font-size:9px;color:var(--text-muted);text-transform:uppercase;">' + label + '</div>' +
      '<div style="font-family:var(--font-mono);font-size:14px;font-weight:700;color:' + color + ';">' + val + '</div>' +
    '</div>';
  }

  function renderWxCurrentBadge() {
    var el = document.getElementById('wx-current-badge');
    if (!el || !weatherData) return;
    var w = weatherData;
    var wxSvg = '<svg viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="currentColor" stroke-width="1.5">';
    if (w.condition==='clear'||w.condition==='mostly_clear') wxSvg += '<circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/>';
    else if (w.condition==='rain'||w.condition==='heavy_rain'||w.condition==='showers'||w.condition==='heavy_showers'||w.condition==='drizzle') wxSvg += '<path d="M20 17.58A5 5 0 0 0 18 8h-1.26A8 8 0 1 0 4 16.25"/><line x1="8" y1="16" x2="8" y2="20"/><line x1="12" y1="18" x2="12" y2="22"/><line x1="16" y1="16" x2="16" y2="20"/>';
    else if (w.condition==='snow'||w.condition==='heavy_snow'||w.condition==='snow_showers'||w.condition==='ice') wxSvg += '<path d="M20 17.58A5 5 0 0 0 18 8h-1.26A8 8 0 1 0 4 16.25"/><path d="M8 16h.01M8 20h.01M12 18h.01M12 22h.01M16 16h.01M16 20h.01"/>';
    else if (w.condition==='thunderstorm'||w.condition==='thunderstorm_hail') wxSvg += '<path d="M19 16.9A5 5 0 0 0 18 7h-1.26a8 8 0 1 0-11.62 9"/><polyline points="13 11 9 17 15 17 11 23"/>';
    else wxSvg += '<path d="M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10z"/>';
    wxSvg += '</svg>';
    el.innerHTML =
      '<div style="color:var(--accent);">' + wxSvg + '</div>' +
      '<div>' +
        '<div style="font-family:var(--font-mono);font-size:28px;font-weight:700;line-height:1;">' + Math.round(w.temp_f) + '<span style="font-size:14px;">°F</span></div>' +
        '<div style="font-size:10px;color:var(--text-muted);text-transform:capitalize;">' + (w.condition||'').replace(/_/g,' ') + '</div>' +
      '</div>' +
      '<div style="margin-left:auto;text-align:right;font-size:10px;color:var(--text-muted);">' +
        '<div>Feels ' + Math.round(w.temp_f) + '°F</div>' +
        '<div>' + Math.round(w.wind_mph) + ' mph ' + (w.wind_dir||'') + '</div>' +
      '</div>';
  }

  function renderWxConditions() {
    var el = document.getElementById('wx-conditions');
    if (!el) return;
    var w = weatherData || {};
    var hum = 0, pres = 0, vis = 0, uv = 0;
    if (forecastData && forecastData.hourly) {
      var h = forecastData.hourly;
      var now = new Date();
      var idx = 0;
      for (var i = 0; i < (h.time||[]).length; i++) {
        if (new Date(h.time[i]) >= now) { idx = Math.max(0, i-1); break; }
      }
      hum = h.relative_humidity_2m ? h.relative_humidity_2m[idx] : 0;
      pres = h.surface_pressure ? h.surface_pressure[idx] : 0;
      vis = h.visibility ? (h.visibility[idx] / 1609.34).toFixed(1) : 0;
      uv = h.uv_index ? h.uv_index[idx] : 0;
    }
    var windColor = (w.wind_mph||0) > 30 ? 'var(--status-bad)' : (w.wind_mph||0) > 20 ? 'var(--status-warn)' : 'var(--text-primary)';
    var humColor = hum > 90 ? 'var(--status-warn)' : 'var(--text-primary)';
    var uvColor = uv > 7 ? 'var(--status-bad)' : uv > 4 ? 'var(--status-warn)' : 'var(--text-primary)';
    function tile(label, val, unit, color, sub) {
      return '<div class="wx-cond-tile">' +
        '<div class="wx-cond-label">' + label + '</div>' +
        '<div class="wx-cond-val" style="color:' + (color||'var(--text-primary)') + ';">' + val + '<span style="font-size:10px;color:var(--text-muted);">' + unit + '</span></div>' +
        (sub ? '<div class="wx-cond-sub">' + sub + '</div>' : '') +
      '</div>';
    }
    el.innerHTML =
      tile('WIND', Math.round(w.wind_mph||0), ' mph', windColor, 'Gust ' + Math.round(w.wind_gust_mph||0)) +
      tile('PRECIP', (w.precip_in||0).toFixed(2), ' in', 'var(--text-primary)', 'Current hr') +
      tile('HUMIDITY', Math.round(hum), '%', humColor, 'Relative') +
      tile('PRESSURE', Math.round(pres), ' hPa', 'var(--text-primary)', 'Surface') +
      tile('VISIBILITY', vis, ' mi', 'var(--text-primary)', '') +
      tile('UV INDEX', uv.toFixed?uv.toFixed(1):uv, '', uvColor, uv<3?'Low':uv<6?'Mod':'High');
  }

  function renderWxSolarPanel() {
    var el = document.getElementById('wx-solar-panel');
    if (!el || !forecastData) return;
    var d = forecastData.daily;
    var sunrise = d.sunrise ? d.sunrise[0] : null;
    if (sunrise && sunrise.length > 5) { var sd = new Date(sunrise); sunrise = sd.getHours().toString().padStart(2,'0') + ':' + sd.getMinutes().toString().padStart(2,'0'); }
    var sunset = d.sunset ? d.sunset[0] : null;
    if (sunset && sunset.length > 5) { var ss = new Date(sunset); sunset = ss.getHours().toString().padStart(2,'0') + ':' + ss.getMinutes().toString().padStart(2,'0'); }
    var now = new Date();
    var hr = now.getHours() + now.getMinutes()/60;
    var factor = Math.max(0, Math.sin((hr - 6) / 12 * Math.PI));
    var cloud = weatherData ? (weatherData.cloud_cover || 50) : 50;
    var solar = Math.round(factor * (1 - cloud/100) * 100);
    var daylight = d.daylight_duration ? (d.daylight_duration[0]/3600).toFixed(1) : (weatherData ? weatherData.daylight_hours.toFixed(1) : '—');
    var barW = Math.max(2, solar);
    var solarColor = solar > 60 ? 'var(--status-good)' : solar > 25 ? 'var(--status-warn)' : 'var(--text-muted)';

    el.innerHTML =
      '<div class="wx-panel-label">' +
        '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/></svg>' +
        'SOLAR & DAYLIGHT</div>' +
      '<div style="display:flex;gap:12px;align-items:center;">' +
        '<div style="text-align:center;flex:1;">' +
          '<div style="font-family:var(--font-mono);font-size:22px;font-weight:700;color:' + solarColor + ';">' + solar + '%</div>' +
          '<div style="font-size:8px;color:var(--text-muted);margin-top:2px;">SOLAR FACTOR</div>' +
          '<div style="height:4px;background:rgba(255,255,255,0.06);border-radius:2px;margin-top:4px;">' +
            '<div style="height:100%;width:' + barW + '%;background:' + solarColor + ';border-radius:2px;transition:width 0.5s;"></div>' +
          '</div>' +
        '</div>' +
        '<div style="text-align:center;flex:1;">' +
          '<div style="font-family:var(--font-mono);font-size:22px;font-weight:700;">' + daylight + '<span style="font-size:10px;color:var(--text-muted);">h</span></div>' +
          '<div style="font-size:8px;color:var(--text-muted);margin-top:2px;">DAYLIGHT</div>' +
        '</div>' +
      '</div>' +
      '<div style="display:flex;justify-content:space-between;margin-top:8px;font-size:9px;font-family:var(--font-mono);">' +
        '<div><span style="color:var(--text-muted);">RISE</span> <span style="color:var(--status-warn);">' + (sunrise||'—') + '</span></div>' +
        '<div><span style="color:var(--text-muted);">SET</span> <span style="color:#A78BFA;">' + (sunset||'—') + '</span></div>' +
      '</div>';
  }

  let _wxMap = null;

  function renderWxMap() {
    var container = document.getElementById('wx-map');
    if (!container) return;

    if (_wxMap) {
      updateWxOverlay();
      return;
    }

    container.innerHTML = '';
    container.style.zIndex = '1';

    var map = L.map('wx-map', {
      center: [SITE_LAT, SITE_LON],
      zoom: 11,
      zoomControl: false,
      attributionControl: false,
    });

    // Dark tile layer — CartoDB Dark Matter (free, no key, no zoom limits)
    L.tileLayer('https://basemaps.cartocdn.com/dark_all/{z}/{x}/{y}@2x.png', {
      maxZoom: 19,
      attribution: '&copy; OpenStreetMap &copy; CARTO',
    }).addTo(map);

    // Zoom control top-right
    L.control.zoom({ position: 'topright' }).addTo(map);

    // Scale bar
    L.control.scale({ position: 'bottomleft', imperial: true, metric: false }).addTo(map);

    _wxMap = map;

    // Pulsing site marker
    var pulseIcon = L.divIcon({
      className: '',
      html: '<div style="position:relative;width:28px;height:28px;">' +
        '<div style="position:absolute;inset:0;border-radius:50%;background:rgba(6,182,212,0.25);animation:wxPulse 2s ease-in-out infinite;"></div>' +
        '<div style="position:absolute;inset:4px;border-radius:50%;background:#06B6D4;border:3px solid white;box-shadow:0 0 12px rgba(6,182,212,0.6);"></div></div>',
      iconSize: [28, 28],
      iconAnchor: [14, 14],
    });

    var marker = L.marker([SITE_LAT, SITE_LON], { icon: pulseIcon }).addTo(map);
    marker.bindPopup(
      '<div style="font-family:Manrope,sans-serif;padding:4px;min-width:200px;">' +
      '<div style="font-weight:700;font-size:14px;">Killdeer Field</div>' +
      '<div style="font-size:11px;color:#6B7280;">10102 Clydesdale Dr, Needville, TX 77461</div>' +
      '<div style="font-size:11px;color:#6B7280;">29.39°N, 95.84°W · Elev 85 ft</div>' +
      (weatherData ? '<div style="margin-top:6px;padding-top:6px;border-top:1px solid rgba(148,163,184,0.08);font-size:12px;">' +
        '<span style="font-weight:600;font-size:16px;">' + Math.round(weatherData.temp_f) + '°F</span> · ' +
        Math.round(weatherData.wind_mph) + ' mph ' + (weatherData.wind_dir||'') + ' · ' +
        (weatherData.condition||'').replace(/_/g,' ') + '</div>' : '') +
      '</div>',
      { maxWidth: 280 }
    );

    // 25-mile ops radius ring
    var opsCircle = L.circle([SITE_LAT, SITE_LON], {
      radius: 40234, // 25 miles in meters
      color: '#06B6D4',
      weight: 1.5,
      dashArray: '8, 6',
      fillColor: '#06B6D4',
      fillOpacity: 0.03,
      opacity: 0.4,
    }).addTo(map);

    // Live weather radar overlay (RainViewer)
    var radarLayer = null;
    fetch('https://api.rainviewer.com/public/weather-maps.json')
      .then(function(r) { return r.json(); })
      .then(function(rv) {
        var ts = rv.radar && rv.radar.past && rv.radar.past.length > 0
          ? rv.radar.past[rv.radar.past.length - 1].path : null;
        if (ts) {
          radarLayer = L.tileLayer('https://tilecache.rainviewer.com' + ts + '/256/{z}/{x}/{y}/6/1_1.png', {
            opacity: 0.5,
            maxNativeZoom: 6,
            maxZoom: 19,
          });
        }
      }).catch(function() {
  // ── COGNITO AUTH GUARD ──
  var idToken = localStorage.getItem('aevus_id_token');
  var API_KEY_HARDCODED = false; // Set false to require Cognito login
  if (!API_KEY_HARDCODED && !idToken) {
    window.location.href = '/dashboard/login.html';
  }
});

    // Satellite tile layer (toggle)
    var satLayer = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
      maxZoom: 19,
    });

    // Layer toggle controls
    var ctrl = document.getElementById('wx-map-controls');
    if (ctrl) {
      ctrl.innerHTML =
        '<button class="wx-layer-btn" data-layer="radar" title="Live weather radar">' +
          '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4.9 19.1A14 14 0 0 1 2 12C2 6.5 6.5 2 12 2s10 4.5 10 10-4.5 10-10 10"/><path d="M7.1 16.9A8 8 0 0 1 4 12a8 8 0 0 1 16 0"/><circle cx="12" cy="12" r="1" fill="currentColor"/></svg> Radar</button>' +
        '<button class="wx-layer-btn active" data-layer="ops-ring" title="25-mi operational radius">' +
          '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/></svg> Ops Ring</button>' +
        '<button class="wx-layer-btn" data-layer="satellite" title="Satellite imagery">' +
          '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 15l4-4 4 4 4-6 5 6"/></svg> Satellite</button>';

      ctrl.addEventListener('click', function(e) {
        var btn = e.target.closest('.wx-layer-btn');
        if (!btn || !_wxMap) return;
        var layer = btn.dataset.layer;
        btn.classList.toggle('active');
        var active = btn.classList.contains('active');

        if (layer === 'radar') {
          if (radarLayer) { active ? radarLayer.addTo(_wxMap) : _wxMap.removeLayer(radarLayer); }
        }
        if (layer === 'ops-ring') {
          active ? opsCircle.addTo(_wxMap) : _wxMap.removeLayer(opsCircle);
        }
        if (layer === 'satellite') {
          active ? satLayer.addTo(_wxMap) : _wxMap.removeLayer(satLayer);
        }
      });
    }

    updateWxOverlay();

    // Fix Leaflet size after container is visible
    setTimeout(function() { map.invalidateSize(); }, 200);
  }

  function updateWxOverlay() {
    var overlay = document.getElementById('wx-map-overlay');
    if (!overlay) return;
    overlay.innerHTML =
      '<div style="padding:6px 12px;border-radius:8px;background:rgba(7,11,22,0.85);backdrop-filter:blur(8px);border:1px solid rgba(255,255,255,0.1);font-size:10px;color:var(--text-secondary);display:flex;align-items:center;gap:6px;">' +
      '<div style="width:6px;height:6px;border-radius:50%;background:var(--accent);box-shadow:0 0 6px var(--accent);animation:wxPulse 2s ease-in-out infinite;"></div>' +
      'Killdeer Field · Needville, TX 77461 · 29.39°N 95.84°W · Elev 85 ft</div>' +
      '<div style="padding:6px 12px;border-radius:8px;background:rgba(7,11,22,0.85);backdrop-filter:blur(8px);border:1px solid rgba(255,255,255,0.1);font-size:10px;color:var(--text-secondary);margin-left:auto;">' +
      (weatherData ? Math.round(weatherData.temp_f) + '°F · ' + Math.round(weatherData.wind_mph) + ' mph ' + (weatherData.wind_dir||'') + ' · ' + (weatherData.condition||'').replace(/_/g,' ') : '') +
      '</div>';
  }

  function buildWxMapControls() { /* handled inline in renderWxMap */ }

  function renderWxHourlyStrip() {
    const el = document.getElementById('wx-hourly-strip');
    if (!el || !forecastData) return;
    const h = forecastData.hourly;
    const now = new Date();
    const nowHour = now.getHours();

    // Find current hour index
    let startIdx = 0;
    for (let i = 0; i < h.time.length; i++) {
      const t = new Date(h.time[i]);
      if (t >= now) { startIdx = Math.max(0, i-1); break; }
    }

    const cards = [];
    const count = Math.min(48, h.time.length - startIdx);
    for (let i = startIdx; i < startIdx + count; i++) {
      const t = new Date(h.time[i]);
      const hr = t.getHours();
      const isNow = (i === startIdx);
      const code = h.weather_code[i];
      const cond = WMO_MAP[code] || 'unknown';
      const icon = WX_ICONS[cond] || '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="2" x2="12" y2="14"/><circle cx="12" cy="18" r="3"/></svg>';
      const temp = Math.round(h.temperature_2m[i]);
      const wind = Math.round(h.wind_speed_10m[i]);
      const precip = h.precipitation_probability[i];
      const timeLabel = isNow ? 'NOW' : (hr === 0 ? t.toLocaleDateString('en-US',{weekday:'short'}) : (hr>12?(hr-12)+'p':(hr===0?'12a':hr+'a')));

      cards.push(
        '<div class="wx-hour-card' + (isNow?' now':'') + '">' +
          '<div class="wx-h-time">' + timeLabel + '</div>' +
          '<div class="wx-h-icon">' + icon + '</div>' +
          '<div class="wx-h-temp">' + temp + '°</div>' +
          '<div class="wx-h-detail"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:middle;margin-right:2px;"><path d="M9.59 4.59A2 2 0 1 1 11 8H2m10.59 11.41A2 2 0 1 0 14 16H2m15.73-8.27A2.5 2.5 0 1 1 19.5 12H2"/></svg>' + wind + '</div>' +
          (precip > 20 ? '<div class="wx-h-detail" style="color:var(--accent);"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:middle;margin-right:2px;"><path d="M12 2.69l5.66 5.66a8 8 0 1 1-11.31 0z"/></svg>' + precip + '%</div>' : '') +
        '</div>'
      );
    }
    el.innerHTML = cards.join('');
  }

  function renderWxDailyForecast() {
    const el = document.getElementById('wx-daily-forecast');
    if (!el || !forecastData) return;
    const d = forecastData.daily;
    const allTemps = [...d.temperature_2m_max, ...d.temperature_2m_min];
    const globalMin = Math.min(...allTemps);
    const globalMax = Math.max(...allTemps);
    const globalRange = globalMax - globalMin || 1;

    let html = '';
    for (let i = 0; i < Math.min(d.time.length, 7); i++) {
      const date = new Date(d.time[i] + 'T12:00:00');
      const dayName = i === 0 ? 'Today' : i === 1 ? 'Tomorrow' : date.toLocaleDateString('en-US',{weekday:'short'});
      const dateStr = date.toLocaleDateString('en-US',{month:'short',day:'numeric'});
      const code = d.weather_code[i];
      const cond = WMO_MAP[code] || 'unknown';
      const icon = WX_ICONS[cond] || '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="2" x2="12" y2="14"/><circle cx="12" cy="18" r="3"/></svg>';
      const hi = Math.round(d.temperature_2m_max[i]);
      const lo = Math.round(d.temperature_2m_min[i]);
      const wind = Math.round(d.wind_speed_10m_max[i]);
      const precip = (d.precipitation_sum[i]||0).toFixed(2);
      const precipProb = d.precipitation_probability_max[i] || 0;

      // Bar position within global range
      const barLeft = ((lo - globalMin) / globalRange) * 100;
      const barWidth = ((hi - lo) / globalRange) * 100;

      html += '<div class="wx-day-row">' +
        '<div class="wx-day-name">' + dayName + '</div>' +
        '<div class="wx-day-icon">' + icon + '</div>' +
        '<div class="wx-day-temps"><span class="wx-day-lo">' + lo + '°</span><span style="color:var(--text-muted);font-size:10px;"> – </span><span class="wx-day-hi">' + hi + '°</span></div>' +
        (precipProb > 20 ? '<div style="font-size:9px;color:var(--accent);font-family:var(--font-mono);">' + precipProb + '%</div>' : '') +
      '</div>';
    }
    el.innerHTML = html;
  }

  function renderWxImpactPanel() {
    const el = document.getElementById('wx-impact-panel');
    if (!el) return;
    const impacts = [];
    const w = weatherData;
    const fc = forecastData;

    if (w) {
      // Wind impact
      if (w.wind_mph > 30) impacts.push({level:'high',label:'High Wind Warning',desc:'Sustained winds >30 mph. Radio links may degrade. Secure loose equipment.'});
      else if (w.wind_mph > 20) impacts.push({level:'medium',label:'Elevated Wind',desc:'Winds 20-30 mph. Monitor radio SNR for signal degradation.'});
      else impacts.push({level:'low',label:'Wind Normal',desc:'Winds <20 mph. No impact on operations.'});

      // Temp impact
      if (w.temp_f < 0) impacts.push({level:'high',label:'Extreme Cold',desc:'Sub-zero temps. Risk of frozen instrumentation and pipe freeze.'});
      else if (w.temp_f < 20) impacts.push({level:'medium',label:'Cold Weather',desc:'Below 20°F. Monitor gas temp and oil viscosity.'});
      else if (w.temp_f > 100) impacts.push({level:'high',label:'Extreme Heat',desc:'Above 100°F. Motor overheating risk. Monitor coolant temp.'});
      else impacts.push({level:'low',label:'Temperature Normal',desc:'Within safe operating range.'});

      // Solar/power
      if (w.solar_production_factor < 0.1 && !w.is_daylight) impacts.push({level:'low',label:'Night Operations',desc:'Solar charging offline. Battery draw active.'});
      else if (w.solar_production_factor < 0.3) impacts.push({level:'medium',label:'Low Solar Output',desc:'Cloud cover limiting solar charging. Monitor battery voltage.'});

      // Precipitation
      if (w.precip_in > 0.5) impacts.push({level:'high',label:'Heavy Precipitation',desc:'Risk of road access issues and equipment moisture ingress.'});
      else if (w.precip_in > 0.1) impacts.push({level:'medium',label:'Active Precipitation',desc:'Light precipitation. Monitor enclosure seals.'});
    }

    // Forecast-based
    if (fc && fc.daily) {
      const maxWind = Math.max(...fc.daily.wind_speed_10m_max);
      if (maxWind > 40) impacts.push({level:'high',label:'Forecast: Severe Wind',desc:'Winds up to '+Math.round(maxWind)+' mph expected this week.'});
      const maxPrecip = Math.max(...(fc.daily.precipitation_probability_max||[]));
      if (maxPrecip > 70) impacts.push({level:'medium',label:'Forecast: High Precip Chance',desc:'Up to '+maxPrecip+'% precipitation probability this week.'});
    }

    if (impacts.length === 0) impacts.push({level:'low',label:'All Clear',desc:'No weather-related operational concerns.'});

    el.innerHTML = impacts.map(i =>
      '<div class="wx-impact-item ' + i.level + '">' +
        '<div class="wx-impact-label">' + '<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:' + (i.level==='high'?'var(--status-bad)':i.level==='medium'?'var(--status-warn)':'var(--status-good)') + ';margin-right:4px;"></span>' + i.label + '</div>' +
        '<div class="wx-impact-desc">' + i.desc + '</div>' +
      '</div>'
    ).join('');
  }

  function renderWxWindChart() {
    const el = document.getElementById('wx-wind-chart');
    const labels = document.getElementById('wx-wind-labels');
    if (!el || !forecastData) return;
    const h = forecastData.hourly;
    const points = h.wind_speed_10m.slice(0, 48);
    const maxVal = Math.max(...points, 1);
    el.innerHTML = points.map((v,i) => {
      const pct = Math.max(2, (v / maxVal) * 100);
      const col = v > 30 ? 'var(--status-bad)' : v > 20 ? 'var(--status-warn)' : 'var(--accent)';
      return '<div class="bar-col" style="height:'+pct+'%;background:'+col+';opacity:0.8;" title="'+Math.round(v)+' mph at '+h.time[i]+'"></div>';
    }).join('');
    if (labels) {
      const first = new Date(h.time[0]).toLocaleTimeString('en-US',{hour:'2-digit',minute:'2-digit'});
      const last = new Date(h.time[47]).toLocaleTimeString('en-US',{hour:'2-digit',minute:'2-digit'});
      labels.innerHTML = '<span>'+first+'</span><span>'+last+'</span>';
    }
  }

  function renderWxPrecipChart() {
    const el = document.getElementById('wx-precip-chart');
    const labels = document.getElementById('wx-precip-labels');
    if (!el || !forecastData) return;
    const h = forecastData.hourly;
    const points = h.precipitation_probability.slice(0, 48);
    el.innerHTML = points.map((v,i) => {
      const pct = Math.max(2, v);
      const col = v > 60 ? 'var(--accent)' : v > 30 ? 'rgba(6,182,212,0.6)' : 'rgba(6,182,212,0.3)';
      return '<div class="bar-col" style="height:'+pct+'%;background:'+col+';opacity:0.8;" title="'+v+'% at '+h.time[i]+'"></div>';
    }).join('');
    if (labels) {
      const first = new Date(h.time[0]).toLocaleTimeString('en-US',{hour:'2-digit',minute:'2-digit'});
      const last = new Date(h.time[47]).toLocaleTimeString('en-US',{hour:'2-digit',minute:'2-digit'});
      labels.innerHTML = '<span>'+first+'</span><span>'+last+'</span>';
    }
  }

  // ═══════════════════════════════════════
  // PAGE: OPERATIONS
  // ═══════════════════════════════════════
  async function renderOperationsPage() {
    await Promise.all([fetchWeather(), fetchCorrelations(), fetchCommandLog()]);
    renderOpsWeather();
    renderOpsCommands();
    renderOpsCommandLog();
    renderOpsCorrelations();
  }

  function renderOpsWeather() {
    const el = document.getElementById('ops-weather-detail');
    if (!el) return;
    const w = weatherData;
    if (!w) { el.innerHTML = '<div style="color:var(--text-muted);font-size:12px;">Weather data not available</div>'; return; }
    const solarPct = Math.round((w.solar_production_factor || 0) * 100);
    const solarCol = solarPct > 60 ? 'var(--status-good)' : solarPct > 30 ? 'var(--status-warn)' : 'var(--text-muted)';
    el.innerHTML = `<div class="stat-grid" style="grid-template-columns:repeat(6,1fr);">
      <div class="stat-card"><div class="stat-card-label">Temperature</div><div class="stat-card-value" style="color:#FBBF24;">${w.temp_f != null ? Math.round(w.temp_f) + '°F' : '—'}</div><div class="stat-card-sub">${(w.condition||'').replace(/_/g,' ')}</div></div>
      <div class="stat-card"><div class="stat-card-label">Wind Speed</div><div class="stat-card-value" style="color:var(--accent);">${w.wind_mph != null ? Math.round(w.wind_mph) : '—'} <span style="font-size:12px;">mph</span></div><div class="stat-card-sub">Gust: ${w.wind_gust_mph ? Math.round(w.wind_gust_mph) + ' mph' : '—'}</div></div>
      <div class="stat-card"><div class="stat-card-label">Precipitation</div><div class="stat-card-value" style="color:#06B6D4;">${w.precip_in != null ? w.precip_in.toFixed(2) : '0'} <span style="font-size:12px;">in</span></div></div>
      <div class="stat-card"><div class="stat-card-label">Solar Factor</div><div class="stat-card-value" style="color:${solarCol};">${solarPct}%</div><div class="solar-bar" style="width:100%;margin-top:6px;"><div class="solar-bar-fill" style="width:${solarPct}%;"></div></div></div>
      <div class="stat-card"><div class="stat-card-label">Daylight</div><div class="stat-card-value">${w.daylight_hours ? w.daylight_hours.toFixed(1) : '—'} <span style="font-size:12px;">hrs</span></div><div class="stat-card-sub">${w.is_daylight ? 'Currently daylight' : 'Currently night'}</div></div>
      <div class="stat-card"><div class="stat-card-label">Sun Times</div><div class="stat-card-value" style="font-size:14px;">${w.sunrise || '—'}</div><div class="stat-card-sub">Sunset: ${w.sunset || '—'}</div></div>
    </div>`;
  }

  function renderOpsCommands() {
    const el = document.getElementById('ops-command-panel');
    if (!el) return;
    const rtu = liveAssets.find(a => a.type === 'rtu') || { id: 'RTU-01' };
    const commands = [
      { cmd: 'start_motor', label: 'Start Motor', icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><polygon points="5 3 19 12 5 21 5 3"/></svg>' },
      { cmd: 'stop_motor', label: 'Stop Motor', icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg>' },
      { cmd: 'open_valve', label: 'Open Valve', icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 2v4m0 12v4M4.93 4.93l2.83 2.83m8.48 8.48l2.83 2.83M2 12h4m12 0h4M4.93 19.07l2.83-2.83m8.48-8.48l2.83-2.83"/></svg>' },
      { cmd: 'close_valve', label: 'Close Valve', icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>' },
    ];
    el.innerHTML = '<div style="margin-bottom:10px;font-size:11px;color:var(--text-muted);display:flex;align-items:center;gap:6px;"><svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="var(--status-good)" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg> IL-9000 Safety Interlock: <span style="color:var(--status-good);font-weight:600;">ACTIVE</span></div>' +
      '<div style="font-size:10px;color:var(--text-muted);margin-bottom:12px;">Target: ' + rtu.id + ' · All commands are simulated</div>' +
      commands.map(c =>
        '<button class="cmd-btn" onclick="window.executeCommand(\'' + rtu.id + '\',\'' + c.cmd + '\')">' + c.icon + '<span>' + c.label + '</span></button>'
      ).join('');
  }

  window.executeCommand = async function(assetId, command) {
    if (!confirm('Execute ' + command.replace(/_/g,' ') + ' on ' + assetId + '?\n\nIL-9000 safety check will run.')) return;
    try {
      const h = { 'Content-Type': 'application/json' };
      if (API_KEY) h['X-API-Key'] = API_KEY;
        var idTok = localStorage.getItem('aevus_id_token');
        if (idTok) h['Authorization'] = 'Bearer ' + idTok;
      const r = await fetch(API + '/commands', {
        method: 'POST', headers: h,
        body: JSON.stringify({ asset_id: assetId, command: command, confirm: true })
      });
      const d = await r.json();
      if (r.ok) {
        alert('Command executed:\n' + (d.result || 'OK'));
        fetchCommandLog().then(() => renderOpsCommandLog());
      } else {
        alert('Command failed:\n' + (d.detail || JSON.stringify(d)));
      }
    } catch (e) { alert('Error: ' + e.message); }
  };

  function renderOpsCommandLog() {
    const el = document.getElementById('ops-command-log');
    if (!el) return;
    if (!commandLog || commandLog.length === 0) {
      el.innerHTML = '<div style="color:var(--text-muted);font-size:12px;padding:12px;">No commands executed yet</div>';
      return;
    }
    el.innerHTML = commandLog.slice(0, 15).map(c => {
      const isOk = (c.result || '').startsWith('simulated');
      return '<div class="cmd-log-row">' +
        '<span class="mono" style="color:var(--accent);min-width:50px;">' + (c.asset_id || '') + '</span>' +
        '<span style="color:var(--text-primary);font-weight:500;min-width:90px;">' + (c.command || '').replace(/_/g, ' ') + '</span>' +
        '<span class="cmd-result ' + (isOk ? 'ok' : 'fail') + '">' + (isOk ? 'OK' : 'REJECTED') + '</span>' +
        '<span style="color:var(--text-muted);font-size:10px;margin-left:auto;font-family:var(--font-mono);">' + timeAgo(c.timestamp) + '</span>' +
        '</div>';
    }).join('');
  }

  function renderOpsCorrelations() {
    const el = document.getElementById('ops-correlations-detail');
    if (!el) return;
    if (!correlations || correlations.length === 0) {
      el.innerHTML = '<div style="background:var(--bg-card);border:1px solid var(--border);border-radius:var(--card-radius);padding:24px;text-align:center;color:var(--text-muted);font-size:13px;">No active cross-domain correlations — all systems nominal</div>';
      return;
    }
    el.innerHTML = correlations.map(c => {
      const sev = c.severity || 'low';
      return '<div class="corr-card ' + sev + '">' +
        '<span class="corr-severity ' + sev + '">' + sev + '</span>' +
        '<div style="flex:1;"><div style="font-size:14px;font-weight:600;color:var(--text-primary);">' + (c.pattern || c.type || '') + '</div>' +
        '<div style="font-size:12px;color:var(--text-secondary);margin-top:4px;">' + (c.message || '') + '</div>' +
        '<div style="font-size:11px;color:var(--text-muted);margin-top:4px;">Affected: ' + ((c.assets || []).join(', ') || '—') + '</div></div>' +
        '<div style="text-align:right;"><div style="font-size:10px;color:var(--text-muted);font-family:var(--font-mono);">' + timeAgo(c.detected_at) + '</div>' +
        '<div style="font-size:10px;color:var(--text-muted);margin-top:2px;">' + (c.type || '') + '</div></div>' +
        '</div>';
    }).join('');
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
    h += '<div class="wf-aux" style="border-color:rgba(6,182,212,0.3);color:rgba(6,182,212,0.4);">CON</div>';
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

    h += '<div class="port-section-divider" style="border-color:rgba(6,182,212,0.15);"></div>';

    // COM1, COM2 serial ports (RS-232/485)
    h += '<div style="display:flex;flex-direction:column;gap:2px;">';
    h += '<div class="chassis-inner-label">SERIAL</div>';
    h += '<div style="display:flex;gap:4px;">';
    for (let c = 1; c <= 2; c++) {
      h += '<div style="display:flex;flex-direction:column;align-items:center;gap:2px;">';
      h += '<div class="wf-aux" style="width:40px;height:24px;border-color:rgba(6,182,212,0.25);font-size:8px;color:rgba(6,182,212,0.4);">COM' + c + '</div>';
      h += '</div>';
    }
    h += '</div></div>';

    h += '<div class="port-section-divider" style="border-color:rgba(6,182,212,0.15);"></div>';

    // Ethernet port
    h += '<div style="display:flex;flex-direction:column;gap:2px;">';
    h += '<div class="chassis-inner-label">ETHERNET</div>';
    h += '<div class="wf-port ' + (isOnline ? 'up' : 'down') + '" title="Modbus TCP">ETH</div>';
    h += '</div>';

    h += '<div class="port-section-divider" style="border-color:rgba(6,182,212,0.15);"></div>';

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

    h += '<div class="port-section-divider" style="border-color:rgba(6,182,212,0.15);"></div>';

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

    h += '<div class="port-section-divider" style="border-color:rgba(6,182,212,0.15);"></div>';

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

    h += '<div class="port-section-divider" style="border-color:rgba(6,182,212,0.15);"></div>';

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
    h += '<svg width="36" height="36" viewBox="0 0 36 36" fill="none" stroke="rgba(167,139,250,0.5)" stroke-width="1.5">';
    h += '<circle cx="18" cy="18" r="14"/>';
    h += '<circle cx="18" cy="18" r="8"/>';
    h += '<circle cx="18" cy="18" r="3"/>';
    h += '<circle cx="18" cy="18" r="1" fill="rgba(167,139,250,0.5)"/>';
    h += '</svg>';
    h += '</div>';

    h += '<div class="port-section-divider" style="border-color:rgba(167,139,250,0.15);"></div>';

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

    h += '<div class="port-section-divider" style="border-color:rgba(167,139,250,0.15);"></div>';

    // DB9 serial port — D-shaped trapezoid
    h += '<div style="display:flex;flex-direction:column;align-items:center;gap:2px;">';
    h += '<div class="chassis-inner-label">SERIAL</div>';
    h += '<svg width="44" height="28" viewBox="0 0 44 28" fill="none">';
    h += '<path d="M6,2 L38,2 C40,2 42,4 42,6 L40,22 C40,24 38,26 36,26 L8,26 C6,26 4,24 4,22 L2,6 C2,4 4,2 6,2 Z" stroke="rgba(167,139,250,0.4)" stroke-width="1.5" fill="rgba(167,139,250,0.05)"/>';
    h += '<text x="22" y="17" text-anchor="middle" fill="rgba(167,139,250,0.5)" font-size="8" font-family="var(--font-mono)">DB9</text>';
    h += '</svg>';
    h += '</div>';

    h += '<div class="port-section-divider" style="border-color:rgba(167,139,250,0.15);"></div>';

    // 2x RJ45 serial ports (Serial A, Serial B)
    h += '<div style="display:flex;flex-direction:column;gap:2px;">';
    h += '<div class="chassis-inner-label">SERIAL A/B</div>';
    h += '<div style="display:flex;gap:3px;">';
    h += '<div class="wf-aux" style="width:42px;border-color:rgba(167,139,250,0.2);color:rgba(167,139,250,0.35);font-size:8px;">SER-A</div>';
    h += '<div class="wf-aux" style="width:42px;border-color:rgba(167,139,250,0.2);color:rgba(167,139,250,0.35);font-size:8px;">SER-B</div>';
    h += '</div></div>';

    h += '<div class="port-section-divider" style="border-color:rgba(167,139,250,0.15);"></div>';

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
    h += '<div class="wf-aux" style="width:28px;height:18px;font-size:7px;border-color:rgba(6,182,212,0.5);color:rgba(6,182,212,0.5);">3.0</div>';
    h += '<div class="wf-aux" style="width:28px;height:18px;font-size:7px;border-color:rgba(6,182,212,0.5);color:rgba(6,182,212,0.5);">3.0</div>';
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



  // ================================================================
  // ALARMS MODULE — ISA 18.2 Alarm Management
  // ================================================================
  function buildKpi(label, value, status) {
    var colors = {critical:'#EF4444',warning:'#FBBF24',good:'#B4BCD0',neutral:'#B4BCD0'};
    var color = colors[status] || '#B4BCD0';
    return '<div class="kpi-tile"><div class="kpi-label">' + label + '</div><div class="kpi-value" style="color:' + color + '">' + value + '</div></div>';
  }

  function renderAlarmsPage() {
    // Reuse existing alerts data but present in ISA 18.2 format
    const page = document.querySelector('section[data-page="alarms"]');
    if (!page) return;

    const active = liveAlerts.filter(a => a.status !== 'resolved');
    const critical = active.filter(a => a.severity === 'critical').length;
    const high = active.filter(a => a.severity === 'high').length;
    const medium = active.filter(a => a.severity === 'medium' || a.severity === 'warning').length;
    const resolved24h = liveAlerts.filter(a => a.status === 'resolved').length;
    const ackd = active.filter(a => a.acknowledged).length;

    page.innerHTML =
      '<div class="module-header">' +
        '<div><h2 class="page-title">Alarm Management</h2>' +
        '<div class="module-subtitle">ISA 18.2 compliant alarm handling — Killdeer Field</div></div>' +
        '<div class="module-actions">' +
          '<button class="module-btn" onclick="window.alarmsView=\'shelved\';renderAlarmsPage()"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M3 3h18v18H3z"/><path d="M3 9h18"/></svg> Shelved</button>' +
          '<button class="module-btn" onclick="window.alarmsView=\'history\';renderAlarmsPage()"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg> History</button>' +
        '</div>' +
      '</div>' +

      // KPI strip
      '<div class="kpi-strip">' +
        buildKpi('ACTIVE ALARMS', active.length, active.length > 5 ? 'critical' : active.length > 0 ? 'warning' : 'good') +
        buildKpi('CRITICAL', critical, critical > 0 ? 'critical' : 'good') +
        buildKpi('HIGH', high, high > 0 ? 'warning' : 'good') +
        buildKpi('MEDIUM / LOW', medium, 'neutral') +
        buildKpi('ACKNOWLEDGED', ackd + '/' + active.length, 'neutral') +
        buildKpi('RESOLVED (24H)', resolved24h, 'good') +
      '</div>' +

      // Tab bar
      '<div class="tab-bar">' +
        '<div class="tab-item' + (window.alarmsView !== 'history' && window.alarmsView !== 'shelved' ? ' active' : '') + '" onclick="window.alarmsView=\'active\';renderAlarmsPage()">Active Alarms</div>' +
        '<div class="tab-item' + (window.alarmsView === 'history' ? ' active' : '') + '" onclick="window.alarmsView=\'history\';renderAlarmsPage()">Alarm History</div>' +
        '<div class="tab-item' + (window.alarmsView === 'shelved' ? ' active' : '') + '" onclick="window.alarmsView=\'shelved\';renderAlarmsPage()">Shelved</div>' +
        '<div class="tab-item" onclick="window.alarmsView=\'analytics\';renderAlarmsPage()">Analytics</div>' +
      '</div>' +

      // Alarm table
      '<div class="panel-box" style="padding:0;overflow:auto;max-height:500px;">' +
        '<table class="ics-table">' +
          '<thead><tr>' +
            '<th>Severity</th><th>Asset</th><th>Alarm</th><th>Value</th><th>Time</th><th>Duration</th><th>Status</th><th>Action</th>' +
          '</tr></thead>' +
          '<tbody>' +
          (window.alarmsView === 'history'
            ? groupAlarms(liveAlerts).map(a => renderAlarmRow(a)).join('')
            : groupAlarms(active).map(a => renderAlarmRow(a)).join('') || '<tr><td colspan="8" style="text-align:center;padding:40px;color:var(--text-muted);">No active alarms — all systems nominal</td></tr>'
          ) +
          '</tbody>' +
        '</table>' +
      '</div>';
  }



  // Board rec #6: Tiny alarm trend sparkline
  function alarmMiniSpark(a) {
    if (a.value == null || isNaN(parseFloat(a.value))) return '';
    var n = parseFloat(a.value);
    var hist = fakeHistory(n, a.unit||'', 8);
    if (!hist) return '';
    var w = 40, h = 12, pad = 1;
    var min = Math.min.apply(null, hist), max = Math.max.apply(null, hist);
    var range = max - min || 1;
    var pts = [];
    for (var i = 0; i < hist.length; i++) {
      var x = (pad + (i / (hist.length - 1)) * (w - 2 * pad)).toFixed(1);
      var y = (h - pad - ((hist[i] - min) / range) * (h - 2 * pad)).toFixed(1);
      pts.push(x + ',' + y);
    }
    var sev = a.severity || 'info';
    var col = sev === 'critical' ? '#EF4444' : sev === 'warning' ? '#FBBF24' : '#60A5FA';
    return '<svg width="' + w + '" height="' + h + '" viewBox="0 0 ' + w + ' ' + h + '" style="display:inline-block;vertical-align:middle;margin-left:6px;opacity:0.6;"><polyline points="' + pts.join(' ') + '" fill="none" stroke="' + col + '" stroke-width="1" stroke-linecap="round"/></svg>';
  }

  // Board rec #2: Group duplicate alarms with count badges
  function groupAlarms(alarms) {
    var groups = {};
    var order = [];
    for (var i = 0; i < alarms.length; i++) {
      var a = alarms[i];
      var key = (a.asset_id||'') + '::' + (a.metric||a.message||'');
      if (!groups[key]) {
        groups[key] = {alarm: a, count: 1, latest: a.created_at||''};
        order.push(key);
      } else {
        groups[key].count++;
        if ((a.created_at||'') > groups[key].latest) {
          groups[key].alarm = a;
          groups[key].latest = a.created_at||'';
        }
      }
    }
    var result = [];
    for (var j = 0; j < order.length; j++) {
      var g = groups[order[j]];
      g.alarm._groupCount = g.count;
      result.push(g.alarm);
    }
    return result;
  }

  function renderAlarmRow(a) {
    const sev = a.severity || 'info';
    const age = a.created_at ? getTimeAgo(a.created_at) : '—';
    const dur = a.created_at ? getTimeDuration(a.created_at) : '—';
    return '<tr class="sev-' + sev + '" onclick="showAlarmDetail(\'' + (a.id||'') + '\')">' +
      '<td><span class="sev-badge ' + sev + '">' + sev + '</span></td>' +
      '<td><span class="mono">' + (a.asset_id||'—') + '</span></td>' +
      "<td>" + (a.metric||a.message||'—') + (a._groupCount > 1 ? ' <span style="font-size:9px;padding:1px 5px;border-radius:8px;background:rgba(96,165,250,0.15);color:#60A5FA;font-weight:600;">×' + a._groupCount + '</span>' : '') + '</td>' +
      '<td class="mono">' + (a.value != null ? a.value + (a.unit ? ' ' + a.unit : '') : '—') + alarmMiniSpark(a) + '</td>' +
      '<td class="mono">' + age + '</td>' +
      '<td class="mono">' + dur + '</td>' +
      '<td><span class="status-dot ' + (a.status||'') + '"></span>' + (a.status||'active') + '</td>' +
      '<td><button class="module-btn" style="padding:2px 8px;font-size:10px;" onclick="event.stopPropagation()">ACK</button></td>' +
    '</tr>';
  }

  function showAlarmDetail(id) {
    const a = liveAlerts.find(x => x.id === id);
    if (!a) return;
    // Open in drawer
    const drawer = document.getElementById('detail-drawer');
    if (drawer) {
      drawer.classList.add('open');
      const body = document.getElementById('drawer-body');
      if (body) {
        body.innerHTML =
          '<h3 style="margin:0 0 12px;">Alarm Detail</h3>' +
          '<div class="sev-badge ' + (a.severity||'info') + '" style="margin-bottom:12px;">' + (a.severity||'info') + '</div>' +
          '<div style="margin-bottom:8px;"><span style="color:var(--text-muted);font-size:11px;">Asset</span><br><span class="mono">' + (a.asset_id||'—') + '</span></div>' +
          '<div style="margin-bottom:8px;"><span style="color:var(--text-muted);font-size:11px;">Metric</span><br>' + (a.metric||'—') + '</div>' +
          '<div style="margin-bottom:8px;"><span style="color:var(--text-muted);font-size:11px;">Message</span><br>' + (a.message||'—') + '</div>' +
          '<div style="margin-bottom:8px;"><span style="color:var(--text-muted);font-size:11px;">Value</span><br><span class="mono">' + (a.value!=null?a.value:'—') + ' ' + (a.unit||'') + '</span></div>' +
          '<div style="margin-bottom:8px;"><span style="color:var(--text-muted);font-size:11px;">Threshold</span><br><span class="mono">' + (a.threshold!=null?a.threshold:'—') + '</span></div>' +
          '<div style="margin-bottom:8px;"><span style="color:var(--text-muted);font-size:11px;">Timestamp</span><br><span class="mono">' + (a.created_at||'—') + '</span></div>' +
          '<div style="margin-bottom:8px;"><span style="color:var(--text-muted);font-size:11px;">Root Cause Analysis</span><br>' +
            '<div class="panel-box" style="padding:12px;margin-top:4px;">' +
              '<div style="font-size:11px;color:var(--text-secondary);">Analyzing correlation with recent events...</div>' +
              '<div style="margin-top:8px;font-size:11px;">' +
                '<div>• Check ' + (a.asset_id||'device') + ' physical connections</div>' +
                '<div>• Review trend data for ' + (a.metric||'metric') + ' over last 24h</div>' +
                '<div>• Cross-reference with weather/environmental data</div>' +
              '</div>' +
            '</div>' +
          '</div>';
      }
    }
  }


  // ================================================================
  // HISTORIAN MODULE — Time-Series Query & Analysis (InfluxDB)
  // ================================================================
  var _histData = [];
  var _histAutoRefresh = null;

  function renderHistorianPage() {
    const page = document.getElementById('historian-page');
    if (!page) return;
    if (_histAutoRefresh) { clearInterval(_histAutoRefresh); _histAutoRefresh = null; }

    const metrics = [];
    if (liveAssets && liveAssets.length) {
      liveAssets.forEach(function(a) {
        if (a.vitals) a.vitals.forEach(function(v) {
          metrics.push({ asset: a.id, name: a.name, label: v.label, value: v.raw_value, unit: v.unit, status: v.status, group: v.group });
        });
      });
    }

    page.innerHTML =
      '<div class="module-header">' +
        '<div><h2 class="page-title">Historian</h2>' +
        '<div class="module-subtitle">Time-series data analysis from InfluxDB — real telemetry trends</div></div>' +
        '<div class="module-actions">' +
          '<button class="module-btn" onclick="exportHistorianCSV()"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" width="16" height="16"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg> Export CSV</button>' +
        '</div>' +
      '</div>' +

      '<div class="hist-query-bar">' +
        '<div><label>Asset</label><br><select id="hist-asset" onchange="updateHistMetrics()">' +
          (liveAssets||[]).map(function(a){ return '<option value="'+a.id+'">'+a.id+' — '+(a.name||a.type)+'</option>'; }).join('') +
        '</select></div>' +
        '<div><label>Metric</label><br><select id="hist-metric"></select></div>' +
        '<div><label>Time Range</label><br><select id="hist-range">' +
          '<option value="1">Last 1 Hour</option>' +
          '<option value="6">Last 6 Hours</option>' +
          '<option value="24" selected>Last 24 Hours</option>' +
          '<option value="168">Last 7 Days</option>' +
          '<option value="720">Last 30 Days</option>' +
        '</select></div>' +
        '<div style="align-self:flex-end;">' +
          '<button class="module-btn primary" onclick="queryHistorian()"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" width="14" height="14"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg> Query</button>' +
        '</div>' +
      '</div>' +

      '<div class="panel-box" style="min-height:320px;padding:20px;">' +
        '<div id="hist-chart-header" style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">' +
          '<div id="hist-chart-title" style="font-size:13px;color:var(--text-secondary);font-weight:600;"></div>' +
          '<div id="hist-chart-stats" style="display:flex;gap:16px;font-size:11px;font-family:var(--font-mono);color:var(--text-muted);"></div>' +
        '</div>' +
        '<div id="hist-chart" style="width:100%;height:260px;position:relative;cursor:crosshair;"></div>' +
        '<div id="hist-tooltip" style="display:none;position:absolute;background:var(--bg-elevated);border:1px solid var(--border);border-radius:6px;padding:8px 12px;font-size:11px;font-family:var(--font-mono);pointer-events:none;z-index:100;color:var(--text-primary);"></div>' +
      '</div>' +

      '<div style="margin-top:16px;">' +
        '<div style="font-size:13px;font-weight:600;color:var(--text-secondary);margin-bottom:8px;">LIVE VALUES</div>' +
        '<div class="panel-box" style="padding:0;overflow:auto;max-height:400px;">' +
          '<table class="ics-table">' +
            '<thead><tr><th>Asset</th><th>Metric</th><th>Value</th><th>Unit</th><th>Status</th><th>Group</th></tr></thead>' +
            '<tbody>' +
            metrics.slice(0, 50).map(function(m) {
              var sc = m.status==='good'?'var(--status-good)':m.status==='warning'||m.status==='warn'?'var(--status-warn)':m.status==='bad'||m.status==='critical'?'var(--status-bad)':'var(--text-muted)';
              return '<tr>' +
                '<td class="mono">' + m.asset + '</td>' +
                '<td>' + m.label + '</td>' +
                '<td class="mono" style="font-weight:600;">' + (m.value != null ? (typeof m.value==="number"?m.value.toFixed(1):m.value) : '—') + '</td>' +
                '<td>' + (m.unit||'') + '</td>' +
                '<td><span style="display:inline-block;width:6px;height:6px;border-radius:50%;background:'+sc+';margin-right:4px;"></span>' + (m.status||'—') + '</td>' +
                '<td style="color:var(--text-muted);text-transform:capitalize;">' + (m.group||'—') + '</td>' +
              '</tr>';
            }).join('') +
            '</tbody>' +
          '</table>' +
        '</div>' +
      '</div>';

    updateHistMetrics();
    setTimeout(queryHistorian, 300);
  }

  window.updateHistMetrics = function() {
    var sel = document.getElementById('hist-asset');
    var metricSel = document.getElementById('hist-metric');
    if (!sel || !metricSel) return;
    var assetId = sel.value;
    var asset = liveAssets.find(function(a){ return a.id === assetId; });
    if (!asset || !asset.vitals) return;
    var seen = {};
    var opts = '';
    asset.vitals.forEach(function(v) {
      var key = v.label.toLowerCase().replace(/ /g, '_');
      if (!seen[key]) {
        seen[key] = true;
        opts += '<option value="'+key+'">'+v.label+' ('+v.unit+')</option>';
      }
    });
    metricSel.innerHTML = opts;
  };

  window.queryHistorian = function() {
    var assetId = document.getElementById('hist-asset')?.value;
    var metric = document.getElementById('hist-metric')?.value;
    var hours = document.getElementById('hist-range')?.value || '24';
    if (!assetId || !metric) return;

    var titleEl = document.getElementById('hist-chart-title');
    if (titleEl) titleEl.textContent = 'Loading...';

    fetch(API + '/health/trend?asset_id=' + assetId + '&metric=' + metric + '&hours=' + hours, {
      headers: API_KEY ? { 'X-API-Key': API_KEY } : {}
    })
    .then(function(r){ return r.json(); })
    .then(function(data){
      _histData = data;
      renderHistorianSVG(data, assetId, metric, hours);
      // Auto-refresh for short ranges
      if (_histAutoRefresh) clearInterval(_histAutoRefresh);
      if (parseInt(hours) <= 1) {
        _histAutoRefresh = setInterval(function(){ queryHistorian(); }, 30000);
      }
    })
    .catch(function(e){
      var el = document.getElementById('hist-chart');
      if (el) el.innerHTML = '<div style="text-align:center;padding:60px;color:var(--text-muted);">Query failed: ' + e.message + '</div>';
    });
  };

  function renderHistorianSVG(data, assetId, metric, hours) {
    var el = document.getElementById('hist-chart');
    if (!el) return;

    if (!data || data.length === 0) {
      el.innerHTML = '<div style="text-align:center;padding:60px;color:var(--text-muted);">No data for this metric/range. Try a different time range or metric.</div>';
      document.getElementById('hist-chart-title').textContent = metric.toUpperCase().replace(/_/g, ' ') + ' — ' + assetId;
      document.getElementById('hist-chart-stats').innerHTML = '';
      return;
    }

    var w = el.offsetWidth || 800;
    var h = 260;
    var pad = { top: 10, right: 20, bottom: 30, left: 50 };
    var cw = w - pad.left - pad.right;
    var ch = h - pad.top - pad.bottom;

    var values = data.map(function(d){ return d.value; });
    var minV = Math.min.apply(null, values);
    var maxV = Math.max.apply(null, values);
    var avgV = values.reduce(function(s,v){return s+v;},0) / values.length;
    var range = maxV - minV || 1;
    // Add 5% padding
    minV -= range * 0.05;
    maxV += range * 0.05;
    range = maxV - minV;

    // Stats
    var statsEl = document.getElementById('hist-chart-stats');
    if (statsEl) {
      statsEl.innerHTML =
        '<span>Min: <b style="color:var(--status-info);">' + Math.min.apply(null,values).toFixed(1) + '</b></span>' +
        '<span>Max: <b style="color:var(--status-warn);">' + Math.max.apply(null,values).toFixed(1) + '</b></span>' +
        '<span>Avg: <b style="color:var(--accent);">' + avgV.toFixed(1) + '</b></span>' +
        '<span>Points: <b>' + data.length + '</b></span>';
    }
    var titleEl = document.getElementById('hist-chart-title');
    if (titleEl) titleEl.textContent = metric.toUpperCase().replace(/_/g, ' ') + ' — ' + assetId + ' — Last ' + hours + 'h';

    // Build path
    var pathD = '';
    var dots = '';
    data.forEach(function(d, i) {
      var x = pad.left + (i / (data.length - 1)) * cw;
      var y = pad.top + (1 - (d.value - minV) / range) * ch;
      pathD += (i === 0 ? 'M' : 'L') + x.toFixed(1) + ',' + y.toFixed(1);
    });

    var areaD = pathD + ' L' + (pad.left + cw).toFixed(1) + ',' + (pad.top + ch) + ' L' + pad.left + ',' + (pad.top + ch) + ' Z';

    // Y-axis labels
    var yLabels = '';
    for (var yi = 0; yi <= 4; yi++) {
      var yy = pad.top + (yi / 4) * ch;
      var yVal = (maxV - (yi / 4) * range).toFixed(1);
      yLabels += '<line x1="'+pad.left+'" y1="'+yy+'" x2="'+(w-pad.right)+'" y2="'+yy+'" stroke="rgba(255,255,255,0.06)" stroke-width="1"/>';
      yLabels += '<text x="'+(pad.left-6)+'" y="'+(yy+3)+'" fill="rgba(255,255,255,0.3)" font-size="9" text-anchor="end" font-family="var(--font-mono)">'+yVal+'</text>';
    }

    // X-axis labels
    var xLabels = '';
    var labelCount = Math.min(6, data.length);
    for (var xi = 0; xi < labelCount; xi++) {
      var idx = Math.floor(xi / (labelCount-1) * (data.length-1));
      var xx = pad.left + (idx / (data.length-1)) * cw;
      var t = new Date(data[idx].time);
      var tLabel = t.getHours().toString().padStart(2,'0') + ':' + t.getMinutes().toString().padStart(2,'0');
      if (parseInt(hours) > 24) tLabel = (t.getMonth()+1)+'/'+t.getDate()+' '+tLabel;
      xLabels += '<text x="'+xx+'" y="'+(h-4)+'" fill="rgba(255,255,255,0.3)" font-size="9" text-anchor="middle" font-family="var(--font-mono)">'+tLabel+'</text>';
    }

    // Average line
    var avgY = pad.top + (1 - (avgV - minV) / range) * ch;
    var avgLine = '<line x1="'+pad.left+'" y1="'+avgY.toFixed(1)+'" x2="'+(w-pad.right)+'" y2="'+avgY.toFixed(1)+'" stroke="rgba(6,182,212,0.4)" stroke-width="1" stroke-dasharray="4,4"/>';

    el.innerHTML =
      '<svg width="'+w+'" height="'+h+'" style="display:block;" id="hist-svg">' +
        '<defs><linearGradient id="hg2" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#06B6D4" stop-opacity="0.2"/><stop offset="100%" stop-color="#06B6D4" stop-opacity="0"/></linearGradient></defs>' +
        yLabels + xLabels + avgLine +
        '<path d="'+areaD+'" fill="url(#hg2)"/>' +
        '<path d="'+pathD+'" fill="none" stroke="#06B6D4" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>' +
        '<circle cx="'+(pad.left + cw)+'" cy="'+(pad.top + (1 - (data[data.length-1].value - minV) / range) * ch).toFixed(1)+'" r="3" fill="#06B6D4"/>' +
        '<rect id="hist-hover-area" x="'+pad.left+'" y="'+pad.top+'" width="'+cw+'" height="'+ch+'" fill="transparent"/>' +
      '</svg>';

    // Hover tooltip
    var svg = document.getElementById('hist-svg');
    var tooltip = document.getElementById('hist-tooltip');
    if (svg && tooltip) {
      svg.addEventListener('mousemove', function(e) {
        var rect = svg.getBoundingClientRect();
        var mx = e.clientX - rect.left - pad.left;
        if (mx < 0 || mx > cw) { tooltip.style.display='none'; return; }
        var idx = Math.round((mx / cw) * (data.length - 1));
        idx = Math.max(0, Math.min(data.length-1, idx));
        var d = data[idx];
        var t = new Date(d.time);
        tooltip.style.display = 'block';
        tooltip.style.left = (e.clientX - el.getBoundingClientRect().left + 12) + 'px';
        tooltip.style.top = (e.clientY - el.getBoundingClientRect().top - 30) + 'px';
        tooltip.innerHTML = '<div style="color:var(--accent);font-weight:600;">' + d.value.toFixed(2) + '</div><div style="color:var(--text-muted);font-size:10px;">' + t.toLocaleString() + '</div>';
      });
      svg.addEventListener('mouseleave', function() { tooltip.style.display='none'; });
    }
  }

  window.exportHistorianCSV = function() {
    if (!_histData || !_histData.length) { alert('No data to export. Run a query first.'); return; }
    var assetId = document.getElementById('hist-asset')?.value || '';
    var metric = document.getElementById('hist-metric')?.value || '';
    var csv = 'timestamp,asset_id,metric,value\n';
    _histData.forEach(function(d) { csv += d.time + ',' + assetId + ',' + metric + ',' + d.value + '\n'; });
    var blob = new Blob([csv], {type:'text/csv'});
    var a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'aevus_' + assetId + '_' + metric + '_' + new Date().toISOString().slice(0,10) + '.csv';
    a.click();
  };

  // ================================================================
  // NETWORK MODULE — ICS Network Topology
  // ================================================================
  function renderNetworkPage() {
    var page = document.getElementById('network-page');
    if (!page) return;

    function nodeColor(assetId) {
      var a = (liveAssets||[]).find(function(x){return x.id===assetId;});
      if (!a) return '#6B7280';
      var s = a.status;
      return s==='good'?'#7B8499':s==='warn'||s==='warning'?'#FBBF24':s==='bad'||s==='critical'?'#EF4444':'#6B7280';
    }
    function nodeHealth(assetId) {
      var a = (liveAssets||[]).find(function(x){return x.id===assetId;});
      return a && a.health != null ? a.health : '—';
    }
    function nodeStatus(assetId) {
      var a = (liveAssets||[]).find(function(x){return x.id===assetId;});
      return a ? (a.status||'unknown') : 'unknown';
    }

    var nodes = [
      {id:'WAN', label:'WAN / Internet', x:400, y:30, icon:'cloud', ip:'', noClick:true},
      {id:'RTR-01', label:'MikroTik L009', x:400, y:130, icon:'router', ip:'.1'},
      {id:'SW-01', label:'Catalyst 2960', x:400, y:250, icon:'switch', ip:'.2'},
      {id:'RAD-01', label:'Trio JR900 #1', x:180, y:380, icon:'radio', ip:'.11'},
      {id:'RAD-02', label:'Trio JR900 #2', x:400, y:380, icon:'radio', ip:'.12'},
      {id:'EDGE-01', label:'Raspberry Pi', x:620, y:380, icon:'server', ip:'.254'},
      {id:'RTU-01', label:'SCADAPack 470', x:180, y:500, icon:'gauge', ip:'.21'},
      {id:'EFM-01', label:'TotalFlow XFC G4', x:400, y:500, icon:'meter', ip:'DNP3'},
    ];
    var edges = [
      {from:'WAN',to:'RTR-01',proto:'WireGuard'},
      {from:'RTR-01',to:'SW-01',proto:'Ethernet'},
      {from:'SW-01',to:'RAD-01',proto:'SNMP v2c'},
      {from:'SW-01',to:'RAD-02',proto:'SNMP v2c'},
      {from:'SW-01',to:'EDGE-01',proto:'SNMP v2c'},
      {from:'RAD-01',to:'RTU-01',proto:'Modbus TCP'},
      {from:'RAD-02',to:'EFM-01',proto:'DNP3'},
    ];

    var W=800, H=570;
    var svg = '<svg viewBox="0 0 '+W+' '+H+'" width="100%" style="max-width:800px;display:block;margin:0 auto;">';

    // Edges
    edges.forEach(function(e){
      var n1 = nodes.find(function(n){return n.id===e.from;});
      var n2 = nodes.find(function(n){return n.id===e.to;});
      if(!n1||!n2) return;
      var c1 = nodeColor(e.from);
      var c2 = nodeColor(e.to);
      var active = nodeStatus(e.to)!=='offline' && nodeStatus(e.to)!=='unknown';
      var stroke = active ? '#10D478' : '#EF4444';
      var dash = active ? '' : ' stroke-dasharray="6,4"';
      svg += '<line x1="'+n1.x+'" y1="'+(n1.y+25)+'" x2="'+n2.x+'" y2="'+(n2.y-25)+'" stroke="'+stroke+'" stroke-width="1.5" stroke-opacity="0.5"'+dash+'/>';
      var mx=(n1.x+n2.x)/2, my=(n1.y+n2.y)/2;
      svg += '<text x="'+mx+'" y="'+(my-4)+'" fill="rgba(255,255,255,0.25)" font-size="8" text-anchor="middle" font-family="var(--font-mono)">'+e.proto+'</text>';
    });

    // Animated flow dots on active edges
    svg += '<style>@keyframes flowDot{0%{offset-distance:0%}100%{offset-distance:100%}}</style>';

    // Nodes
    nodes.forEach(function(n){
      var c = n.id==='WAN' ? '#6B7280' : nodeColor(n.id);
      var h = n.id==='WAN' ? '' : nodeHealth(n.id);
      var rw=140, rh=50;

      // Node box
      svg += '<g style="cursor:pointer;" onclick="'+(n.noClick?'':'openAssetDrawer(&quot;'+n.id+'&quot;)')+'">';
      svg += '<rect x="'+(n.x-rw/2)+'" y="'+(n.y-rh/2)+'" width="'+rw+'" height="'+rh+'" rx="8" fill="#161E33" stroke="'+c+'" stroke-width="1.5"/>';

      // Icon placeholder (simple text for now)
      var iconMap = {cloud:'◌',router:'⟐',switch:'⏚',radio:'◎',server:'▣',gauge:'◉',meter:'◈'};
      svg += '<text x="'+(n.x-rw/2+14)+'" y="'+(n.y+1)+'" fill="'+c+'" font-size="14" text-anchor="middle" dominant-baseline="middle">'+iconMap[n.icon]+'</text>';

      // Label
      svg += '<text x="'+(n.x-rw/2+28)+'" y="'+(n.y-6)+'" fill="#FFFFFF" font-size="10" font-weight="600" font-family="Manrope">'+n.label+'</text>';
      svg += '<text x="'+(n.x-rw/2+28)+'" y="'+(n.y+8)+'" fill="#7B8499" font-size="8" font-family="var(--font-mono)">'+n.id+(n.ip?' · '+n.ip:'')+'</text>';

      // Health badge
      if (h !== '') {
        svg += '<rect x="'+(n.x+rw/2-28)+'" y="'+(n.y-rh/2-8)+'" width="26" height="16" rx="4" fill="'+c+'"/>';
        svg += '<text x="'+(n.x+rw/2-15)+'" y="'+(n.y-rh/2+4)+'" fill="#0B1020" font-size="9" font-weight="700" text-anchor="middle" font-family="var(--font-mono)">'+h+'</text>';
      }
      svg += '</g>';
    });

    // SNMP Trap indicator on MikroTik
    svg += '<rect x="475" y="115" width="70" height="16" rx="4" fill="rgba(6,182,212,0.15)" stroke="rgba(6,182,212,0.3)" stroke-width="0.5"/>';
    svg += '<text x="510" y="126" fill="#06B6D4" font-size="7" text-anchor="middle" font-family="var(--font-mono)">TRAP RECV ●</text>';

    svg += '</svg>';

    page.innerHTML =
      '<div class="module-header"><div><h2 class="page-title">Network Topology</h2>' +
      '<div class="module-subtitle">ICS network layout — Killdeer Field · 192.168.88.0/24</div></div></div>' +
      '<div class="panel-box" style="padding:24px;text-align:center;">'+svg+'</div>' +
      '<div style="display:flex;gap:16px;margin-top:12px;justify-content:center;flex-wrap:wrap;">' +
        '<div style="display:flex;align-items:center;gap:6px;font-size:11px;color:var(--text-muted);"><span style="width:20px;height:2px;background:#10D478;display:inline-block;"></span> Active Link</div>' +
        '<div style="display:flex;align-items:center;gap:6px;font-size:11px;color:var(--text-muted);"><span style="width:20px;height:2px;background:#EF4444;display:inline-block;border-top:1px dashed #EF4444;"></span> Down Link</div>' +
        '<div style="display:flex;align-items:center;gap:6px;font-size:11px;color:var(--text-muted);"><span style="width:8px;height:8px;border-radius:50%;background:#10D478;display:inline-block;"></span> Good</div>' +
        '<div style="display:flex;align-items:center;gap:6px;font-size:11px;color:var(--text-muted);"><span style="width:8px;height:8px;border-radius:50%;background:#FBBF24;display:inline-block;"></span> Warning</div>' +
        '<div style="display:flex;align-items:center;gap:6px;font-size:11px;color:var(--text-muted);"><span style="width:8px;height:8px;border-radius:50%;background:#EF4444;display:inline-block;"></span> Critical</div>' +
      '</div>';
  }

  // ================================================================
  // MAP MODULE — Geographic Asset Map (Mapbox)
  // ================================================================
  function renderMapPage() {
    var page = document.querySelector('section[data-page="map"]');
    if (!page) return;
    page.style.position='relative';page.style.minHeight='calc(100vh - 60px)';page.style.overflow='hidden';

    page.innerHTML =
      '<div id="aevus-map" style="width:100%;height:calc(100vh - 60px);"></div>';

    if (typeof mapboxgl === 'undefined') {
      // Load Mapbox GL JS
      var link = document.createElement('link');
      link.rel = 'stylesheet';
      link.href = 'https://api.mapbox.com/mapbox-gl-js/v3.12.0/mapbox-gl.css';
      document.head.appendChild(link);
      var script = document.createElement('script');
      script.src = 'https://api.mapbox.com/mapbox-gl-js/v3.12.0/mapbox-gl.js';
      script.onload = function(){ initAevusMap(); };
      document.head.appendChild(script);
    } else {
      setTimeout(initAevusMap, 100);
    }
  }

  function initAevusMap() {
    mapboxgl.accessToken = 'pk.eyJ1Ijoid29vZHlpbCIsImEiOiJjbWR4eW5keTUwOTlvMmxxMXo1aGljdWdyIn0.f4ud1cQ6mf-oNM69iY6fEg';
    var map = new mapboxgl.Map({
      container: 'aevus-map',
      style: 'mapbox://styles/mapbox/dark-v11',
      center: [-95.8375, 29.3905],
      zoom: 17,
      pitch: 45,
    });
    map.addControl(new mapboxgl.NavigationControl(), 'top-right');

    var statusColors = {good:'#7B8499',warn:'#FBBF24',warning:'#FBBF24',bad:'#EF4444',critical:'#EF4444',offline:'#6B7280',unknown:'#6B7280'};

    (liveAssets||[]).forEach(function(a) {
      if (!a.latitude || !a.longitude) return;
      var c = statusColors[a.status] || '#6B7280';
      var h = a.health != null ? a.health : '?';

      // Custom marker element
      var el = document.createElement('div');
      el.style.cssText = 'width:36px;height:36px;border-radius:50%;background:'+c+';border:3px solid rgba(255,255,255,0.3);display:flex;align-items:center;justify-content:center;font-size:10px;font-weight:700;color:#0B1020;font-family:var(--font-mono);cursor:pointer;box-shadow:0 0 12px '+c+'44;';
      el.textContent = h;
      el.title = a.name;

      // Popup
      var popup = new mapboxgl.Popup({offset:25, closeButton:false}).setHTML(
        '<div style="font-family:Manrope;padding:4px;">' +
          '<div style="font-weight:700;font-size:13px;margin-bottom:4px;">'+a.name+'</div>' +
          '<div style="font-size:11px;color:#7B8499;">'+a.id+' · '+(a.type||'')+'</div>' +
          '<div style="font-size:11px;margin-top:4px;">Health: <b style="color:'+c+'">'+h+'</b> · '+(a.status||'unknown')+'</div>' +
          '<div style="font-size:10px;color:#7B8499;margin-top:2px;">'+(a.ip_address||'')+'</div>' +
        '</div>'
      );

      var marker = new mapboxgl.Marker({element:el})
        .setLngLat([a.longitude, a.latitude])
        .setPopup(popup)
        .addTo(map);

      el.addEventListener('click', function(){ openAssetDrawer(a.id); });
    });
  }


  function updateMapMarkers() {
    if (!mapInstance) return;

    // Remove existing markers
    mapMarkers.forEach(m => m.remove());
    mapMarkers = [];

    if (liveAssets.length === 0) return;

    const bounds = new mapboxgl.LngLatBounds();
    const offsets = {};
    let idx = 0;

    liveAssets.forEach(asset => {
      let lat = asset.latitude;
      let lng = asset.longitude;

      // Placeholder coordinates around Needville, TX 77461 if no GPS
      if (lat == null || lng == null) {
        const angle = (idx / liveAssets.length) * 2 * Math.PI;
        const r = 0.005 + (idx * 0.002);
        lat = 29.39 + Math.cos(angle) * r;
        lng = -95.84 + Math.sin(angle) * r;
      }
      idx++;

      // Color by status
      let color = '#6B7280'; // gray/unknown
      const s = (asset.status || '').toLowerCase();
      if (s === 'good') color = '#7B8499';
      else if (s === 'warn' || s === 'warning') color = '#FBBF24';
      else if (s === 'bad' || s === 'critical') color = '#EF4444';

      // Create marker element
      const el = document.createElement('div');
      el.style.cssText = 'width:16px;height:16px;border-radius:50%;border:2px solid rgba(255,255,255,0.8);cursor:pointer;box-shadow:0 0 8px ' + color;
      el.style.background = color;

      const popup = new mapboxgl.Popup({ offset: 20, className: 'aevus-map-popup' })
        .setHTML(
          '<div style="font-family:Manrope,sans-serif;padding:4px;">' +
          '<div style="font-weight:600;font-size:13px;margin-bottom:4px;">' + (asset.name || asset.id) + '</div>' +
          '<div style="font-size:11px;color:#B4BCD0;">Status: <span style="color:' + color + ';font-weight:600;">' + (asset.status || 'unknown') + '</span></div>' +
          '<div style="font-size:11px;color:#B4BCD0;">Health: ' + (asset.health != null ? asset.health + '%' : 'N/A') + '</div>' +
          '<div style="font-size:11px;color:#B4BCD0;">Type: ' + (asset.type || '-') + '</div>' +
          '<div style="font-size:10px;color:#6B7280;margin-top:4px;">' + (asset.ip_address || '') + '</div>' +
          '</div>'
        );

      const marker = new mapboxgl.Marker({ element: el })
        .setLngLat([lng, lat])
        .setPopup(popup)
        .addTo(mapInstance);

      mapMarkers.push(marker);
      bounds.extend([lng, lat]);
    });

    if (mapMarkers.length > 1) {
      mapInstance.fitBounds(bounds, { padding: 60, maxZoom: 15 });
    } else if (mapMarkers.length === 1) {
      mapInstance.flyTo({ center: bounds.getCenter(), zoom: 14 });
    }
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

  // Mini sparkline SVG generator — creates a tiny line chart from an array of values
  function miniSparkline(values, color) {
    if (!values || values.length < 2) return "";
    const w = 120, h = 24, pad = 2;
    const min = Math.min(...values), max = Math.max(...values);
    const range = max - min || 1;
    const pts = values.map((v, i) => {
      const x = pad + (i / (values.length - 1)) * (w - 2 * pad);
      const y = h - pad - ((v - min) / range) * (h - 2 * pad);
      return x.toFixed(1) + "," + y.toFixed(1);
    }).join(" ");
    const lastY = (h - pad - ((values[values.length-1] - min) / range) * (h - 2 * pad)).toFixed(1);
    return '<div class="drawer-vital-spark"><svg viewBox="0 0 ' + w + ' ' + h + '" preserveAspectRatio="none">' +
      '<polyline points="' + pts + '" fill="none" stroke="' + color + '" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>' +
      '<circle cx="' + (w - pad) + '" cy="' + lastY + '" r="2" fill="' + color + '"/>' +
      '</svg></div>';
  }

  // Generate simulated historical points around a current value
  function fakeHistory(current, unit, n) {
    if (current == null || isNaN(current)) return null;
    const variance = unit === "%" ? 3 : unit === "°F" ? 2 : unit === "PSI" ? 8 : unit === "V" ? 0.5 : current * 0.05;
    const pts = [];
    let v = current - variance * (Math.random() - 0.3);
    for (let i = 0; i < n; i++) {
      v += (Math.random() - 0.48) * variance * 0.4;
      pts.push(v);
    }
    pts[n - 1] = current;
    return pts;
  }
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
          const sparkColor = v.status==='critical'?'var(--status-bad)':v.status==='warning'?'var(--status-warn)':'var(--accent)'; const sparkData = fakeHistory(parseFloat(v.raw_value), v.unit, 12); h += '<div class="drawer-vital ' + (v.status||'') + '"><div class="drawer-vital-label">' + v.label + '</div><div class="drawer-vital-value">' + dv + '<span class="drawer-vital-unit">' + (v.unit||'') + '</span></div>' + (sparkData ? miniSparkline(sparkData, sparkColor) : '') + '</div>';
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
    await Promise.all([fetchAssets(), fetchAlerts(), fetchHealthSummary(), fetchPredictions(), fetchWeather(), fetchCorrelations()]);
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

    // Show user info and logout button if Supabase auth
    const userEmail = localStorage.getItem('aevus_user_email');
    if (SUPABASE_TOKEN && userEmail) {
      const nameEl = document.getElementById('sidebar-user-name');
      const roleEl = document.getElementById('sidebar-user-role');
      const avatarEl = document.getElementById('sidebar-avatar');
      const logoutBtn = document.getElementById('logout-btn');
      if (nameEl) nameEl.textContent = userEmail;
      if (roleEl) roleEl.textContent = 'Authenticated';
      if (avatarEl) avatarEl.textContent = userEmail.substring(0, 2).toUpperCase();
      if (logoutBtn) logoutBtn.style.display = 'block';
    }

    addConnectionIndicator();
    await refreshAll();
    initRouter();
    connectWebSocket();
    startPolling();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else setTimeout(init, 50);

})();


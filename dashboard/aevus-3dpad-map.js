/* ============================================================================
 * aevus-3dpad-map.js  —  UXDA AWARD 3D-PAD MAP, ported as an overlay (2026-06-03)
 * Restores the award-submission "Monitor" 3D facility map (AWS Location dark
 * basemap + fill-extrusion 3D pad + equipment models + live health/alarms)
 * onto the CURRENT feature-rich platform, WITHOUT touching the minified build.
 * It takes over the #map page (rad-hover-live.js pattern) and feeds live data
 * via shims that poll /api/v1/assets + /api/v1/alerts.
 * Source: award-recovery/award-api-client.src.js lines 10915-14077 (verbatim).
 * ==========================================================================*/
(function () {
  "use strict";
  if (window.__aevus3dPadInstalled) return;
  window.__aevus3dPadInstalled = true;

  // ---- bundled award map CSS ------------------------------------------------
  try {
    var st = document.createElement("style");
    st.id = "aevus-3dpad-css";
    st.textContent = '#wx-map-controls{position:absolute;bottom:42px;left:50%;transform:translateX(-50%);display:flex;gap:6px;z-index:5;}\n.wx-map-wrap{flex: 1; position: relative; border-radius: 8px; overflow: hidden;\n  border: 1px solid var(--border); min-height: 0;}\n.rf-status-bar{grid-template-columns: 1fr 1fr !important;\n    gap: 6px !important;}\n.rf-trends-grid{grid-template-columns: 1fr !important;}\n.rf-diag-grid{grid-template-columns: 1fr !important;}\n/* #9 Canvas responsive */\n  canvas:not(.maplibregl-canvas){max-width: 100% !important;}\n/* ── Map Enhancements: Layer Toggle, Faceplate, Measurement ── */\n.map-layer-toggle{position: absolute; top: 12px; left: 12px; z-index: 10;\n  background: rgba(11,16,32,0.92); border: 1px solid rgba(148,163,184,0.15);\n  border-radius: 8px; padding: 10px 14px; font-size: 11px; color: #B4BCD0;\n  font-family: var(--font-body); backdrop-filter: blur(8px);}\n.map-layer-toggle label{display: flex; align-items: center; gap: 6px; cursor: pointer; padding: 3px 0;}\n.map-layer-toggle label:hover{color: #fff;}\n.map-layer-toggle input[type="checkbox"]{accent-color: var(--accent); width: 14px; height: 14px;}\n.map-layer-title{font-weight: 700; font-size: 10px; text-transform: uppercase; letter-spacing: 0.5px; color: var(--text-faint); margin-bottom: 6px;}\n.map-weather-legend{position: absolute; bottom: 40px; left: 12px; z-index: 5;\n  background: rgba(11,16,32,0.92); border: 1px solid rgba(148,163,184,0.15);\n  border-radius: 8px; padding: 10px 14px; font-size: 10px; color: #B4BCD0;\n  font-family: var(--font-mono); backdrop-filter: blur(8px);}\n.map-weather-legend .wx-row{display: flex; align-items: center; gap: 6px; padding: 2px 0;}\n.map-weather-legend .wx-dot{width: 8px; height: 8px; border-radius: 50%;}\n.map-mini-faceplate{background: rgba(11,16,32,0.95) !important; border: 1px solid var(--accent) !important;\n  border-radius: 8px !important; padding: 0 !important; min-width: 220px;\n  font-family: var(--font-body) !important; box-shadow: 0 8px 32px rgba(0,0,0,0.5) !important;}\n.map-mini-faceplate .fp-header{padding: 8px 12px; border-bottom: 1px solid rgba(148,163,184,0.1);\n  display: flex; justify-content: space-between; align-items: center;}\n.map-mini-faceplate .fp-name{font-weight: 700; font-size: 12px; color: #fff;}\n.map-mini-faceplate .fp-status{font-size: 9px; font-weight: 600; padding: 2px 6px; border-radius: 3px;}\n.map-mini-faceplate .fp-vitals{padding: 8px 12px;}\n.map-mini-faceplate .fp-vital-row{display: flex; justify-content: space-between; align-items: center;\n  font-size: 10px; padding: 3px 0; border-bottom: 1px solid rgba(148,163,184,0.05);}\n.map-mini-faceplate .fp-vital-label{color: var(--text-faint);}\n.map-mini-faceplate .fp-vital-value{font-family: var(--font-mono); font-weight: 600; color: #fff;}\n.map-mini-faceplate .fp-bar{height: 3px; border-radius: 2px; background: rgba(148,163,184,0.1); margin-top: 2px;}\n.map-mini-faceplate .fp-bar-fill{height: 100%; border-radius: 2px; transition: width 0.3s;}\n.map-measure-btn{position: absolute; top: 12px; right: 60px; z-index: 10;\n  background: rgba(11,16,32,0.92); border: 1px solid rgba(148,163,184,0.15);\n  border-radius: 6px; padding: 6px 12px; font-size: 10px; color: #B4BCD0;\n  cursor: pointer; font-family: var(--font-body); backdrop-filter: blur(8px);}\n.map-measure-btn:hover{border-color: var(--accent); color: #fff;}\n.map-measure-btn.active{background: rgba(14,165,233,0.15); border-color: var(--accent); color: var(--accent);}\n.map-measure-result{position: absolute; top: 44px; right: 60px; z-index: 10;\n  background: rgba(11,16,32,0.92); border: 1px solid var(--accent);\n  border-radius: 6px; padding: 6px 12px; font-size: 11px; color: #fff;\n  font-family: var(--font-mono); backdrop-filter: blur(8px); display: none;}\n.map-marker-abnormal{animation: abnormalPulseMap 1.5s ease-in-out infinite;}\n.map-zone-legend{position: absolute; bottom: 30px; right: 12px; z-index: 10;\n  background: rgba(11,16,32,0.92); border: 1px solid rgba(148,163,184,0.15);\n  border-radius: 8px; padding: 10px 14px; font-size: 10px; color: #B4BCD0;\n  font-family: var(--font-mono); backdrop-filter: blur(8px);}\n#aevus-map{width: 100% !important;\n  height: 100% !important;}\n/* Mapbox popup overrides for mini faceplate */\n.maplibregl-popup-content{background: transparent !important;\n  padding: 0 !important;\n  box-shadow: none !important;\n  border-radius: 8px !important;}\n.maplibregl-popup-tip{border-top-color: rgba(11,16,32,0.95) !important;}\n.maplibregl-popup-close-button{color: #B4BCD0 !important;\n  font-size: 16px !important;\n  padding: 4px 8px !important;\n  z-index: 1 !important;}\n.maplibregl-popup-close-button:hover{color: #fff !important;}\n/* ── Fix: Mapbox popup for dark theme ── */\n.maplibregl-popup-content{background: transparent !important;\n  padding: 0 !important;\n  box-shadow: none !important;}\n.maplibregl-popup-tip{display: none !important;}\n.maplibregl-canvas{box-sizing: content-box !important;}\n.maplibregl-popup-close-button{color: #B4BCD0 !important; font-size: 18px !important;\n  right: 4px !important; top: 2px !important; z-index: 2 !important;}\n.maplibregl-popup-close-button:hover{color: #fff !important;}\n/* ── Fix: Map page full bleed — no breadcrumb, no main padding ── */\nbody.map-active .main{padding: 0 !important;}\nbody.map-active .main > div:first-child{display: none !important;}\n/* ── RF Communications Page (34th audit) ── */\n.rf-page{height:calc(100vh - 80px); display:flex; flex-direction:column; overflow:hidden; position:relative;}\n.rf-status-bar{display:flex; justify-content:space-between; align-items:center; padding:10px 20px; background:rgba(14,165,233,0.03); border:1px solid rgba(14,165,233,0.08); border-radius:10px; margin-bottom:8px;}\n.rf-link-indicator{display:flex; align-items:center; gap:8px;}\n.rf-meta{font-size:10px; color:var(--text-muted); font-family:var(--font-mono);}\n.rf-flow-container{flex:1; display:flex; align-items:center; justify-content:center; min-height:0;}\n.rf-flow-svg{width:100%; height:100%; max-height:calc(100vh - 220px);}\n/* RF Wave animations */\n.rf-wave{animation:rfWavePulse 2s ease-in-out infinite;}\n.rf-wave-1{animation-delay:0s;}\n.rf-wave-2{animation-delay:0.3s;}\n.rf-wave-3{animation-delay:0.6s;}\n.rf-wave-4{animation-delay:0.15s;}\n.rf-wave-5{animation-delay:0.45s;}\n.rf-wave-6{animation-delay:0.75s;}\n/* Antenna pulse */\n.rf-antenna-pulse{animation:antennaPulse 1.5s ease-in-out infinite;}\n/* Center RF symbol */\n.rf-center-pulse{animation:centerPulse 3s ease-in-out infinite;}\n/* LED pulse */\n.rf-led-pulse{animation:ledPulse 2s ease-in-out infinite;}\n/* KPI strip */\n/* ── Diagnostic Tools & Trend Panels ── */\n.rf-diag-bar{display:flex; justify-content:center; gap:6px; padding:8px 16px; flex-wrap:wrap;}\n.rf-diag-btn{display:inline-flex; align-items:center; gap:5px; padding:6px 14px; border:1px solid rgba(148,163,184,0.1); border-radius:8px; background:rgba(148,163,184,0.03); color:var(--text-muted); font-size:10px; font-weight:600; font-family:var(--font-mono); letter-spacing:0.5px; cursor:pointer; transition:all 0.2s; white-space:nowrap;}\n.rf-diag-btn:hover{background:rgba(14,165,233,0.08); border-color:rgba(14,165,233,0.2); color:var(--accent);}\n.rf-diag-btn.active{background:rgba(14,165,233,0.1); border-color:rgba(14,165,233,0.3); color:var(--accent);}\n.rf-diag-btn svg{flex-shrink:0;}\n.rf-trends-panel{display:none; padding:0 16px 12px; animation:fadeSlide 0.25s ease;}\n.rf-trends-panel.open{display:block;}\n.rf-trends-grid{display:grid; grid-template-columns:1fr 1fr; gap:10px;}\n.rf-trends-grid{grid-template-columns:1fr;}\n.rf-trend-card{background:rgba(148,163,184,0.02); border:1px solid rgba(148,163,184,0.06); border-radius:10px; padding:12px 16px;}\n.rf-trend-header{display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;}\n.rf-trend-title{font-size:9px; font-weight:700; letter-spacing:1px; text-transform:uppercase; color:var(--text-muted);}\n.rf-trend-purpose{font-size:9px; color:var(--text-faint); font-style:italic;}\n.rf-trend-chart{height:60px; position:relative;}\n.rf-trend-chart canvas{width:100%; height:100%;}\n.rf-trend-legend{display:flex; gap:12px; margin-top:6px; font-size:8px; color:var(--text-faint);}\n.rf-trend-legend span{display:flex; align-items:center; gap:3px;}\n.rf-trend-legend .dot{width:6px; height:6px; border-radius:50%;}\n/* Diagnostic results panel */\n.rf-diag-result{display:none; padding:0 16px 12px; animation:fadeSlide 0.25s ease;}\n.rf-diag-result.open{display:block;}\n.rf-diag-output{background:rgba(15,23,42,0.6); border:1px solid rgba(148,163,184,0.08); border-radius:8px; padding:12px 16px; font-family:var(--font-mono); font-size:11px; color:#E2E8F0; line-height:1.8; max-height:200px; overflow-y:auto;}\n.rf-diag-output .pass{color:#10D478;}\n.rf-diag-output .warn{color:#FBBF24;}\n.rf-diag-output .fail{color:#EF4444;}\n.rf-diag-output .dim{color:#7B8499;}\n.rf-diag-output .header{color:var(--accent); font-weight:700;}\n/* Need to allow rf-page to scroll for expanded content */\n.rf-page.expanded{overflow-y:auto;}\nbody.wall-mode .rf-diag-bar, body.wall-mode .rf-trends-panel, body.wall-mode .rf-diag-result{display:none !important;}\n.rf-kpi-strip{display:flex; justify-content:center; gap:6px; padding:8px 12px; background:rgba(148,163,184,0.02); border-top:1px solid rgba(148,163,184,0.06); border-radius:0 0 10px 10px; flex-wrap:wrap;}\n.rf-kpi{display:flex; align-items:center; gap:6px; padding:6px 14px; background:var(--bg-card); border:1px solid var(--border); border-radius:8px; font-size:10px; cursor:pointer; transition:border-color 0.2s;}\n.rf-kpi:hover{border-color:rgba(14,165,233,0.3);}\n.rf-kpi-label{color:var(--text-muted); font-weight:500;}\n.rf-kpi-value{font-family:var(--font-mono); font-weight:700; font-size:13px;}\n/* No-link state */\n.rf-waves-inactive .rf-wave{animation:none !important; opacity:0.05 !important;}\n.rf-waves-inactive .rf-pkt{display:none;}\n/* Wall mode */\n\n/* ── Radio UX Upgrades (award audit) ── */\n/* Click-to-drill cursor on interactive elements */\n.rf-clickable{cursor:pointer; transition:all 0.25s ease;}\n.rf-clickable:hover{filter:brightness(1.3);}\n#rf-tower-ap .rf-clickable:hover, #rf-tower-remote .rf-clickable:hover{filter:drop-shadow(0 0 8px rgba(0,212,255,0.5));}\n/* Hover tooltip */\n.rf-tooltip{position:absolute; background:rgba(15,23,42,0.96); border:1px solid rgba(148,163,184,0.15); border-radius:8px; padding:12px 16px; font-size:11px; color:#E2E8F0; pointer-events:none; z-index:1000; opacity:0; transition:opacity 0.2s; backdrop-filter:blur(12px); box-shadow:0 8px 32px rgba(0,0,0,0.4); max-width:260px; line-height:1.5;}\n.rf-tooltip.visible{opacity:1;}\n.rf-tooltip .tt-title{font-size:12px; font-weight:700; color:var(--accent); margin-bottom:6px; font-family:var(--font-mono);}\n.rf-tooltip .tt-row{display:flex; justify-content:space-between; gap:12px; margin:3px 0;}\n.rf-tooltip .tt-label{color:#7B8499; font-size:10px;}\n.rf-tooltip .tt-val{font-weight:600; font-family:var(--font-mono); font-size:11px;}\n.rf-tower-alarm{animation: alarmHalo 1.5s ease-in-out infinite;}\n/* Sparkline in callout panels */\n.rf-spark-line{fill:none; stroke-width:1.5; stroke-linecap:round; stroke-linejoin:round;}\n/* Predictive trend badge */\n.rf-trend-badge{display:inline-flex; align-items:center; gap:3px; padding:2px 8px; border-radius:10px; font-size:8px; font-weight:600; letter-spacing:0.5px; text-transform:uppercase;}\n/* Accessible status indicators — icon alongside color */\n.rf-status-icon{margin-right:3px; vertical-align:-1px;}\n/* Drill-down panel (slides open on click) */\n.rf-drill-panel{display:none; position:absolute; left:0; right:0; bottom:-1px; transform:translateY(100%); background:rgba(15,23,42,0.97); border:1px solid rgba(148,163,184,0.1); border-radius:0 0 10px 10px; padding:16px; z-index:50; backdrop-filter:blur(12px); box-shadow:0 12px 40px rgba(0,0,0,0.4);}\n.rf-drill-panel.open{display:block; animation:fadeSlide 0.25s ease;}\nbody.wall-mode .rf-page{height:100vh; padding:0;}\nbody.wall-mode .rf-status-bar{padding:16px 32px; font-size:15px;}\nbody.wall-mode .rf-flow-container{flex:1; padding:0 16px;}\nbody.wall-mode .rf-flow-svg{max-height:none; height:100%;}\nbody.wall-mode .rf-kpi{padding:10px 20px; font-size:13px;}\nbody.wall-mode .rf-kpi-value{font-size:18px;}\nbody.wall-mode .rf-kpi-strip{padding:12px 20px; gap:10px; font-size:12px;}\nbody.wall-mode #rf-r1-values text, body.wall-mode #rf-r2-values text{font-size:120%;}\nbody.wall-mode .rf-flow-svg text[font-size="7"]{font-size:10px;}\nbody.wall-mode .rf-flow-svg text[font-size="8"]{font-size:11px;}\nbody.wall-mode .rf-flow-svg text[font-size="9"]{font-size:12px;}\n.rf-flow-svg{max-height:300px;}\n.rf-kpi-strip{gap:4px;}\n.rf-kpi{padding:4px 8px; font-size:9px;}\n.rf-kpi-value{font-size:11px;}';
    document.head.appendChild(st);
  } catch (e) { console.warn("[3dpad] css inject failed", e); }

  // ---- safety globals the module expects ------------------------------------
  window._userRole = window._userRole || "admin";
  if (typeof window.AEVUS_DEMO === "undefined") {
    window.AEVUS_DEMO = /[?&]demo=true/.test(location.search);
  }

  // ---- live-data shims: poll the real API, cache for sync accessors ---------
  var _assetsCache = [], _alertsCache = [];
  function _hdrs() { return { "x-aevus-demo": "true" }; }
  function _refresh() {
    fetch("/api/v1/assets", { headers: _hdrs() }).then(function (r) { return r.ok ? r.json() : []; })
      .then(function (d) { if (Array.isArray(d)) _assetsCache = d; }).catch(function () {});
    fetch("/api/v1/alerts", { headers: _hdrs() }).then(function (r) { return r.ok ? r.json() : []; })
      .then(function (d) { _alertsCache = Array.isArray(d) ? d : (d && d.alerts) || []; }).catch(function () {});
  }
  window._getLiveAssets = window._getLiveAssets || function () { return _assetsCache; };
  window._getLiveAlerts = window._getLiveAlerts || function () { return _alertsCache; };
  _refresh(); setInterval(_refresh, 15000);

  // ---- the award map module (verbatim) --------------------------------------
  function renderMapPage() {
    var page = document.querySelector('section[data-page="map"]');
    if (!page) return;
    document.body.classList.add('map-active');
    if (window._aevusMapLoaded && typeof maplibregl !== "undefined") {
      if (window._aevusMapInstance) {
        setTimeout(function() {
          var m = window._aevusMapInstance;
          if (m) {
            m._frameRequest = null;
            m.triggerRepaint();
            m.resize();
          }
        }, 300);
      }
      return;
    }
    window._aevusMapLoaded = true; // prevent double init from polling
    page.style.cssText='position:relative;padding:0!important;margin:0;overflow:hidden;height:calc(100vh - 56px);';var mainEl=document.querySelector('.main');if(mainEl){mainEl.style.padding='0';mainEl.style.overflow='hidden';mainEl.style.height='calc(100vh - var(--topbar-h))';}
    page.innerHTML = '<div id="aevus-map" style="width:100%;height:100%;position:relative;"></div>'; /* no breadcrumb for map */

    if (typeof maplibregl === 'undefined') {
      // Load Mapbox GL JS
      var link = document.createElement('link');
      link.rel = 'stylesheet';
      link.href = 'maplibre-gl.min.css';
      document.head.appendChild(link);
      var script = document.createElement('script');
      script.src = 'maplibre-gl.min.js';
      script.onload = function(){ initAevusMap(); };
      document.head.appendChild(script);
    } else {
      setTimeout(initAevusMap, 300);
    }
  }

  async function initAevusMap() {
    window._aevusMapLoaded = true;
    // MapLibre — no token required (board vote: migrated from Mapbox)
    var mapDiv = document.getElementById('aevus-map');
    if (!mapDiv) return;

    // ── AWS Location Service — Full Platform ──
    var _awsRegion = 'us-east-1';
    var _cognitoPoolId = 'us-east-1:8587ccdd-3db8-4539-8309-4ae6c17ca888';
    var _mapStyles = {
      dark: { name: 'Standard', label: 'Monitor', colorScheme: 'Dark' },
      satellite: { name: 'Satellite', label: 'Satellite', colorScheme: '' },
      hybrid: { name: 'Hybrid', label: 'Hybrid', colorScheme: '' }
    };
    var _currentMapStyle = 'dark';
    var _awsApiKey2 = 'v1.public.eyJqdGkiOiI1ZWZlMmVhNS0wNDIzLTRmOGYtYjE4Yy1mNDIwYWIyNWJmOWYifRK_jmth0fvOGxwNjv2ESzOtpQ3776rJOO5jMEoWGldqkSdvTlSfUSOLi2MjwIXE3-KKz7fBahruKgmCMBnuxBTKE03XqdIrdkerbE8gf9iXJIl-o_yOkESxfskw_GKAzNDNwDzMibCxzoO5ozMNvMScB4TNQQ3B0itYNA7uuBWqa70CldFT3mOLdz3mM9SdSeb_eXxfqRGV-e8V_KBtur1Q6tOY-9In90LmSxVM2SmRBiGV-EtoUqyACHFmBRHE8BJANowzPS2oSF3dyzyMTNBpaVUanGgNjYcf5BhyznCI6qqt7VXkqsruILuwJvODO3u2kTTLVwQvHlpel4Ny2eI.ZWU0ZWIzMTktMWRhNi00Mzg0LTllMzYtNzlmMDU3MjRmYTkx';
    var _awsStyleUrl = function(name, colorScheme) { 
      var url = 'https://maps.geo.' + _awsRegion + '.amazonaws.com/v2/styles/' + name + '/descriptor?key=' + _awsApiKey2;
      if (colorScheme) url += '&color-scheme=' + colorScheme;
      return url;
    };
    var _cartoFallback = 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json';
    var _awsAuthReady = true; // API key v3 with GetTile permission
    var _awsTransformRequest = null;

    var _mapOpts = {
      container: 'aevus-map',
      style: 'https://maps.geo.us-east-1.amazonaws.com/v2/styles/Standard/descriptor?key=' + _awsApiKey2 + '&color-scheme=Dark',
      center: [-95.8680, 29.3395],
      zoom: 18.3, pitch: 55, bearing: -20, maxZoom: 22
    };

    if (_awsApiKey2) {
      // API key auth — append key to all AWS tile/resource requests
      _awsTransformRequest = function(url, resourceType) {
        if (url && url.indexOf('amazonaws.com') > -1 && url.indexOf('key=') === -1) {
          url += (url.indexOf('?') > -1 ? '&' : '?') + 'key=' + _awsApiKey2;
        }
        return { url: url };
      };
      _mapOpts.transformRequest = _awsTransformRequest;
      console.log('[Aevus] AWS Location Service authenticated via API key — dark style loaded');
    } else {
      try {
        var ah = window.amazonLocationAuthHelper;
        if (ah && ah.withIdentityPoolId) {
          var auth = await ah.withIdentityPoolId(_cognitoPoolId);
          var authOpts = auth.getMapAuthenticationOptions();
          _mapOpts.style = _awsStyleUrl(_mapStyles.dark.name, _mapStyles.dark.colorScheme);
          _mapOpts.transformRequest = authOpts.transformRequest;
          _awsTransformRequest = authOpts.transformRequest;
          _awsAuthReady = true;
          window._awsMapAuth = authOpts;
          console.log('[Aevus] AWS Location Service authenticated via Cognito');
        }
      } catch(e) {
        console.warn('[Aevus] AWS auth unavailable, using CartoDB fallback:', e.message);
      }
    }
    window._awsLocationReady = _awsAuthReady;

    // Temporarily override requestAnimationFrame to bypass Chrome's rAF
    // throttling for WebGL canvases without user engagement. This ensures
    // the first render frames actually get composited.
    var _origRAF = window.requestAnimationFrame;
    var _rafCount = 0;
    window.requestAnimationFrame = function(cb) {
      _rafCount++;
      if (_rafCount <= 200) {
        var id = setTimeout(function() { cb(performance.now()); }, 16);
        return id;
      }
      // Restore original rAF after warmup period
      window.requestAnimationFrame = _origRAF;
      return _origRAF.call(window, cb);
    };

    var map = new maplibregl.Map(_mapOpts);
    window._aevusMapInstance = map;
    map.addControl(new maplibregl.NavigationControl(), 'top-right');
    map.once('style.load', function() {
      map.resize();
      // RainViewer live radar overlay for Map page
      fetch('https://api.rainviewer.com/public/weather-maps.json')
        .then(function(r) { return r.json(); })
        .then(function(rv) {
          var ts = rv.radar && rv.radar.past && rv.radar.past.length > 0
            ? rv.radar.past[rv.radar.past.length - 1].path : null;
          if (ts) {
            map.addSource('radar-tiles', {
              type: 'raster',
              tiles: ['https://tilecache.rainviewer.com' + ts + '/256/{z}/{x}/{y}/6/1_1.png'],
              tileSize: 256, maxzoom: 6
            });
            map.addLayer({
              id: 'radar-layer', type: 'raster', source: 'radar-tiles',
              paint: { 'raster-opacity': 0.45 },
              layout: { visibility: 'visible' }
            });
            console.log('[Aevus] Radar layer added:', ts);
          }
        }).catch(function(e) { console.warn('[Aevus] Radar fetch failed:', e); });
    });
    setTimeout(function(){ map.resize(); }, 500);
    setTimeout(function(){ map.resize(); }, 2000);

    // Restore original rAF after 5 seconds regardless
    setTimeout(function() {
      window.requestAnimationFrame = _origRAF;
      console.log('[Aevus] rAF restored after ' + _rafCount + ' frames');
    }, 5000);

    var SC = {good:'#10D478',warn:'#FBBF24',warning:'#FBBF24',bad:'#EF4444',critical:'#EF4444',offline:'#6B7280',unknown:'#6B7280'};
    var assetCoords = [];
    var bounds = new maplibregl.LngLatBounds();
    var markerList = [];
    // Global single-popup tracker — only one popup open at a time (must be before asset markers)
    var _activePopup = null;
    var _allMarkers = [];
    var _markerClickGuard = false;
    function _closeAllPopups() {
      _allMarkers.forEach(function(m) {
        try { if (m.getPopup() && m.getPopup().isOpen()) m.togglePopup(); } catch(e) {}
      });
      if (_activePopup) { try { _activePopup.remove(); } catch(e) {} _activePopup = null; }
    }
    function _showPopup(p) {
      _closeAllPopups();
      _activePopup = p;
      p.on('close', function() { if (_activePopup === p) _activePopup = null; });
      return p;
    }
    var idx = 0;

    (liveAssets||[]).forEach(function(a) {
      var lat = a.latitude, lng = a.longitude;
      if (lat == null || lng == null) {
        // Place assets at their physical equipment locations on the well pad
        var _assetPositions = {
          'RAD-01': [29.33995, -95.86733],  // At Radio Tower
          'RAD-02': [29.33993, -95.86731],  // Next to RAD-01
          'RTU-01': [29.33992, -95.86741],  // At RTU Cabinet
          'EFM-01': [29.33950, -95.86733],  // At EFM Skid
          'SW-01':  [29.33988, -95.86748],  // Near RTU
          'RTR-01': [29.33990, -95.86738],  // Near RTU
          'EDGE-01':[29.33986, -95.86750]   // Near RTU area
        };
        var _pos = _assetPositions[a.id];
        if (_pos) { lat = _pos[0]; lng = _pos[1]; }
        else {
          var _offsets = [[-0.0002,0.0003],[0.0003,-0.0002],[-0.0001,-0.0004],[0.0004,0.0002],[-0.0003,0.0001],[0.0002,0.0004],[-0.0004,-0.0003]];
          var _off = _offsets[idx % _offsets.length];
          lat = 29.3395 + _off[0];
          lng = -95.8680 + _off[1];
        }
      }
      idx++;
      var s = (a.status||'').toLowerCase();
      var c = SC[s] || '#6B7280';
      var h = a.health != null ? a.health : '?';
      var isAbn = (s==='bad'||s==='critical'||s==='warning'||s==='warn');
      var alarmCt = 0;
      if (a.vitals) a.vitals.forEach(function(v){ if (v.status==='bad'||v.status==='critical') alarmCt++; });
      assetCoords.push({lng:lng,lat:lat,id:a.id,name:a.name,status:s,color:c});
      bounds.extend([lng, lat]);

      // ── Map device-type holographic icons (matching network topology) ──
      var _mapIconSvg = '';
      var _devType = (a.type||'').toLowerCase();
      var _iconId = a.id || '';
      // Map device types to network topology icons
      if (_devType === 'radio' || _iconId.indexOf('RAD') === 0) {
        _mapIconSvg = '<line x1="12" y1="1" x2="12" y2="15" stroke-width="2"/>' +
          '<line x1="9" y1="5" x2="15" y2="5" stroke-width="1.5"/>' +
          '<line x1="10" y1="3" x2="14" y2="3" stroke-width="1.2"/>' +
          '<line x1="12" y1="15" x2="7" y2="24"/><line x1="12" y1="15" x2="17" y2="24"/>' +
          '<line x1="8.5" y1="21" x2="15.5" y2="21" stroke-width="1.2"/>' +
          '<path d="M18 4a8 8 0 0 1 0 10" stroke-width="1.5" opacity="0.7"/>' +
          '<path d="M21 2a12 12 0 0 1 0 14" stroke-width="1.2" opacity="0.4"/>' +
          '<path d="M6 4a8 8 0 0 0 0 10" stroke-width="1.5" opacity="0.7"/>' +
          '<path d="M3 2a12 12 0 0 0 0 14" stroke-width="1.2" opacity="0.4"/>';
      } else if (_iconId === 'EFM-01' || _iconId.indexOf('EFM') === 0) {
        _mapIconSvg = '<path d="M2 12l10-10 10 10-10 10z" stroke-width="1.5"/>' +
          '<line x1="8" y1="12" x2="16" y2="12" stroke-width="1.2" opacity="0.5"/>' +
          '<circle cx="12" cy="12" r="2.5" opacity="0.6"/>' +
          '<path d="M12 7v10" stroke-width="0.8" opacity="0.3"/>';
      } else if (_devType === 'rtu' || _iconId.indexOf('RTU') === 0) {
        _mapIconSvg = '<rect x="2" y="3" width="20" height="19" rx="1.5"/>' +
          '<line x1="2" y1="7" x2="22" y2="7" opacity="0.4"/>' +
          '<circle cx="5" cy="5" r="0.8" fill="'+c+'"/><circle cx="7.5" cy="5" r="0.8" fill="'+c+'"/>' +
          '<path d="M7 15a5 5 0 0 1 10 0" stroke-width="1.5"/>' +
          '<line x1="12" y1="15" x2="15" y2="11.5" stroke-width="1.8"/>' +
          '<circle cx="12" cy="15" r="1" fill="'+c+'"/>';
      } else if (_devType === 'router' || _iconId.indexOf('RTR') === 0) {
        _mapIconSvg = '<rect x="2" y="9" width="20" height="10" rx="2"/>' +
          '<circle cx="7" cy="14" r="1.2" fill="'+c+'"/><circle cx="11" cy="14" r="1.2" fill="'+c+'"/><circle cx="15" cy="14" r="1.2" fill="'+c+'"/>' +
          '<path d="M7 9V5l5-3 5 3v4" stroke-width="1.5"/>' +
          '<circle cx="12" cy="4" r="1" fill="'+c+'"/>';
      } else if (_devType === 'switch' || _iconId.indexOf('SW') === 0) {
        _mapIconSvg = '<rect x="1" y="8" width="22" height="12" rx="2"/>' +
          '<line x1="5" y1="20" x2="5" y2="24"/><line x1="9" y1="20" x2="9" y2="24"/><line x1="13" y1="20" x2="13" y2="24"/><line x1="17" y1="20" x2="17" y2="24"/>' +
          '<circle cx="5" cy="11.5" r="1" fill="'+c+'"/><circle cx="9" cy="11.5" r="1" fill="'+c+'"/><circle cx="13" cy="11.5" r="1" fill="'+c+'"/><circle cx="17" cy="11.5" r="1" fill="'+c+'"/>';
      } else if (_iconId.indexOf('EDGE') === 0) {
        _mapIconSvg = '<rect x="4" y="2" width="16" height="8" rx="1.5"/>' +
          '<rect x="4" y="13" width="16" height="8" rx="1.5"/>' +
          '<circle cx="16" cy="6" r="1.2" fill="'+c+'"/><circle cx="16" cy="17" r="1.2" fill="'+c+'"/>' +
          '<line x1="7" y1="6" x2="12" y2="6" opacity="0.5"/>' +
          '<line x1="7" y1="17" x2="12" y2="17" opacity="0.5"/>';
      } else {
        // Fallback: generic device
        _mapIconSvg = '<rect x="4" y="4" width="16" height="16" rx="3"/>' +
          '<circle cx="12" cy="12" r="3" opacity="0.5"/>';
      }

      var el = document.createElement('div');
      el.className = 'map-asset-marker';
      el.style.cssText = 'width:50px;height:70px;display:flex;flex-direction:column;align-items:center;cursor:pointer;position:absolute;overflow:visible;z-index:5;';
      el.style.setProperty('--marker-color', c);
      // ── 3D Holographic marker structure ──
      // 1. Floating icon container (the "hologram")
      var holoIcon = document.createElement('div');
      holoIcon.className = 'holo-icon';
      holoIcon.style.cssText = 'width:38px;height:38px;border-radius:10px;display:flex;align-items:center;justify-content:center;position:relative;z-index:2;' +
        'background:linear-gradient(145deg, rgba(11,16,32,0.92), rgba(11,16,32,0.75));' +
        'border:1.5px solid '+c+'55;' +
        'box-shadow:0 0 20px '+c+'44, 0 8px 32px rgba(0,0,0,0.5), inset 0 1px 0 rgba(255,255,255,0.06), inset 0 0 20px '+c+'15;' +
        'backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);';
      holoIcon.innerHTML = '<svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="'+c+'" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" style="filter:drop-shadow(0 0 6px '+c+'AA) drop-shadow(0 0 2px '+c+'66);position:relative;z-index:1;">' + _mapIconSvg + '</svg>' +
        '<div style="position:absolute;top:0;left:0;right:0;bottom:0;border-radius:10px;overflow:hidden;pointer-events:none;">' +
          '<div style="position:absolute;left:0;right:0;height:1px;background:linear-gradient(90deg,transparent,'+c+'44,transparent);animation:holoScan 3s linear infinite;"></div>' +
        '</div>';
      el.appendChild(holoIcon);
      // 2. Light beam connecting icon to ground
      var beam = document.createElement('div');
      beam.className = 'holo-beam';
      beam.style.cssText = 'width:2px;height:18px;background:linear-gradient(to bottom,'+c+'66,'+c+'11);position:relative;z-index:1;opacity:0.45;transition:height 0.3s ease, opacity 0.3s ease;';
      el.appendChild(beam);
      // 3. Ground shadow / projection circle
      var shadow = document.createElement('div');
      shadow.className = 'holo-shadow';
      shadow.style.cssText = 'width:28px;height:8px;border-radius:50%;background:radial-gradient(ellipse,'+c+'44,'+c+'11,transparent 70%);position:relative;z-index:0;opacity:0.35;transition:transform 0.3s ease, opacity 0.3s ease;animation:holoShadowPulse 4s ease-in-out infinite;';
      el.appendChild(shadow);
      el.title = a.name;
      el.onmouseenter = function() { holoIcon.style.boxShadow = '0 0 30px '+c+'66, 0 8px 32px rgba(0,0,0,0.5), inset 0 1px 0 rgba(255,255,255,0.08), inset 0 0 24px '+c+'22'; holoIcon.style.borderColor = c+'88'; };
      el.onmouseleave = function() { holoIcon.style.boxShadow = '0 0 20px '+c+'44, 0 8px 32px rgba(0,0,0,0.5), inset 0 1px 0 rgba(255,255,255,0.06), inset 0 0 20px '+c+'15'; holoIcon.style.borderColor = c+'55'; };
      // ── Heartbeat + Visual Encoding (Morrison: minimal in normal, full in abnormal) ──
      el.setAttribute('data-asset-id', a.id);
      el.setAttribute('data-asset-status', s);
      el.setAttribute('data-asset-health', h);
      if (s === 'offline' || s === 'unknown') {
        // Flatline — no breathing, desaturated (death signal)
        el.classList.add('map-marker-flatline');
      } else if (s === 'bad' || s === 'critical') {
        // Critical — fast red pulse, larger marker
        el.classList.add('map-marker-abnormal');
        el.style.setProperty('--pulse-color', c);
        el.style.borderColor = c;
        holoIcon.style.width = '52px'; holoIcon.style.height = '52px'; // Larger for critical
      } else if (s === 'warning' || s === 'warn') {
        // Warning — slow yellow pulse
        el.classList.add('map-marker-warning');
        el.style.setProperty('--pulse-color', '#FBBF24');
        el.style.borderColor = '#FBBF2488';
      } else {
        // Normal — quiet breathing (Morrison: calm in normal state)
        el.classList.add('map-marker-alive');
      }
      // Health score badge — bottom right
      var hBadge = document.createElement('span');
      hBadge.style.cssText = 'position:absolute;top:35px;right:-2px;z-index:10;background:rgba(11,16,32,0.9);color:'+c+';font-size:9px;font-weight:700;min-width:20px;height:18px;border-radius:9px;display:flex;align-items:center;justify-content:center;border:1px solid '+c+'55;font-family:var(--font-mono);padding:0 4px;box-shadow:0 0 6px '+c+'33;';
      hBadge.setAttribute('data-health-badge','1'); hBadge.textContent = h; el.appendChild(hBadge);
      // Alarm count badge — top right
      if (alarmCt > 0) {
        var badge = document.createElement('span');
        badge.style.cssText = 'position:absolute;top:-8px;right:-2px;z-index:10;background:#EF4444;color:#fff;font-size:8px;font-weight:700;width:16px;height:16px;border-radius:50%;display:flex;align-items:center;justify-content:center;border:1.5px solid #0B1020;box-shadow:0 0 8px rgba(239,68,68,0.5);';
        badge.textContent = alarmCt; el.appendChild(badge);
      }
      // Device label below marker
      var lbl = document.createElement('div');
      lbl.style.cssText = 'position:absolute;bottom:-14px;left:50%;transform:translateX(-50%);white-space:nowrap;font-size:9px;font-weight:600;color:'+c+';font-family:var(--font-mono);text-shadow:0 0 6px rgba(0,0,0,0.8),0 0 3px '+c+'44;letter-spacing:0.3px;';
      lbl.setAttribute('data-map-label','1'); lbl.textContent = a.id; el.appendChild(lbl);
      var vitalsHtml = '';
      if (a.vitals && a.vitals.length) {
        a.vitals.slice(0,4).forEach(function(v){
          var vc = v.status==='good'?'#10D478':(v.status==='warning'||v.status==='warn')?'#FBBF24':'#EF4444';
          var pct = 50; if (v.raw_value!=null&&v.range_high) pct=Math.min(100,Math.max(0,(v.raw_value/v.range_high)*100));
          vitalsHtml += '<div style="display:flex;justify-content:space-between;font-size:10px;padding:2px 0;"><span style="color:#7B8499;">'+v.label+'</span><span style="font-family:var(--font-mono);font-weight:600;color:'+vc+'">'+(v.raw_value!=null?(typeof v.raw_value==="number"?v.raw_value.toFixed(1):v.raw_value):"—")+' '+(v.unit||'')+'</span></div>';
          vitalsHtml += '<div style="height:3px;border-radius:2px;background:rgba(148,163,184,0.1);margin-bottom:2px;"><div style="height:100%;width:'+pct+'%;border-radius:2px;background:'+vc+';"></div></div>';
        });
      }
      var sBg=s==='good'?'rgba(16,212,120,0.15)':isAbn?'rgba(239,68,68,0.15)':'rgba(148,163,184,0.1)';
      var sClr=s==='good'?'#10D478':isAbn?'#EF4444':'#6B7280';
      // Device type label
      var _dtLabel = {'radio':'Radio Tower','rtu':'RTU / PLC','router':'Network Router','switch':'Network Switch'}[_devType] || (_devType||'Device').toUpperCase();
      // Uptime simulation
      var _uptimeDays = Math.floor(30 + Math.random() * 60);
      var _lastComm = Math.floor(Math.random() * 30) + 's ago';
      // Health bar
      var _hPct = Math.min(100, Math.max(0, parseInt(h)||0));
      var _hBarColor = _hPct >= 90 ? '#10D478' : _hPct >= 70 ? '#FBBF24' : '#EF4444';
      var popHtml='<div style="background:rgba(11,16,32,0.97);border:1px solid '+c+'55;border-radius:10px;min-width:260px;font-family:Manrope,sans-serif;box-shadow:0 4px 24px rgba(0,0,0,0.5),0 0 20px '+c+'15;">' +
        '<div style="padding:10px 14px;border-bottom:1px solid rgba(148,163,184,0.08);display:flex;justify-content:space-between;align-items:center;">' +
          '<div><div style="font-weight:700;font-size:13px;color:#fff;">'+a.name+'</div>' +
          '<div style="font-size:9px;color:#7B8499;margin-top:1px;">'+a.id+' · '+_dtLabel+'</div></div>' +
          '<span style="font-size:9px;font-weight:600;padding:3px 8px;border-radius:4px;background:'+sBg+';color:'+sClr+'">'+(a.status||'N/A').toUpperCase()+'</span>' +
        '</div>' +
        '<div style="padding:10px 14px;">' +
          '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">' +
            '<span style="font-size:10px;color:#7B8499;">Health Score</span>' +
            '<span style="font-size:14px;font-weight:800;color:'+c+';font-family:var(--font-mono);">'+h+'%</span>' +
          '</div>' +
          '<div style="height:4px;border-radius:2px;background:rgba(148,163,184,0.1);margin-bottom:10px;overflow:hidden;"><div style="height:100%;width:'+_hPct+'%;border-radius:2px;background:'+_hBarColor+';box-shadow:0 0 6px '+_hBarColor+'66;"></div></div>' +
          vitalsHtml +
          '<div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-top:8px;padding-top:8px;border-top:1px solid rgba(148,163,184,0.06);">' +
            '<div style="font-size:9px;color:#7B8499;">Uptime<div style="font-weight:700;color:#E2E8F0;font-family:var(--font-mono);margin-top:1px;">'+_uptimeDays+'d</div></div>' +
            '<div style="font-size:9px;color:#7B8499;">Last Comm<div style="font-weight:700;color:#E2E8F0;font-family:var(--font-mono);margin-top:1px;">'+_lastComm+'</div></div>' +
          '</div>' +
          '<div style="padding:0 14px 10px;display:flex;gap:6px;"><button onclick="window._pinAssetById(&quot;' + a.id + '&quot;)" style="flex:1;padding:6px;font-size:9px;font-weight:600;border-radius:6px;cursor:pointer;font-family:var(--font-body);display:flex;align-items:center;justify-content:center;gap:4px;transition:background 0.2s;background:rgba(6,182,212,0.1);border:1px solid rgba(6,182,212,0.25);color:#06B6D4;" onmouseover="this.style.background=&quot;rgba(6,182,212,0.2)&quot;" onmouseout="this.style.background=&quot;rgba(6,182,212,0.1)&quot;"><svg viewBox="0 0 24 24" width="11" height="11" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/></svg>Pin</button><button onclick="window._addDispatchStop&amp;&amp;window._addDispatchStop(&quot;' + a.id + '&quot;)" style="flex:1;padding:6px;font-size:9px;font-weight:600;border-radius:6px;cursor:pointer;font-family:var(--font-body);display:flex;align-items:center;justify-content:center;gap:4px;transition:background 0.2s;background:rgba(16,212,120,0.1);border:1px solid rgba(16,212,120,0.25);color:#10D478;" onmouseover="this.style.background=&quot;rgba(16,212,120,0.2)&quot;" onmouseout="this.style.background=&quot;rgba(16,212,120,0.1)&quot;"><svg viewBox="0 0 24 24" width="11" height="11" fill="none" stroke="currentColor" stroke-width="2"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg title="Add this asset as a stop on your field dispatch route">Route</button></div>' +
        '</div></div>';
      var popup = new maplibregl.Popup({offset:[0,-16],closeButton:true,maxWidth:'280px',closeOnClick:true}).setHTML(popHtml);
      var marker = new maplibregl.Marker({element:el,anchor:'bottom'}).setLngLat([lng,lat]).addTo(map); el.addEventListener('click',function(e){e.stopPropagation();_markerClickGuard=true;map.easeTo({center:[lng,lat],duration:300});setTimeout(function(){_closeAllPopups(); marker.togglePopup(); _activePopup=marker.getPopup(); if(typeof window._openMapAssetPanel==='function'){try{window._openMapAssetPanel(eq.id||eq.name)}catch(e){}} setTimeout(function(){_markerClickGuard=false;},100);},320);}); marker._popup=popup; marker.setPopup(popup); _allMarkers.push(marker);
      markerList.push(marker);
    });

    if (assetCoords.length > 0) map.flyTo({center:[-95.8685, 29.3396], zoom: 18.3, pitch:55, bearing:-20, duration:1200});
    else if (assetCoords.length === 1) map.flyTo({center:[assetCoords[0].lng,assetCoords[0].lat],zoom:16});

    // ── WELL PAD EQUIPMENT OVERLAY (Board vote: unanimous) ──
    map.on('load', function() {
      var padCenter = [-95.8680, 29.3395];
      // popup tracker moved to outer scope (before asset markers)
      var padR = 0.0008; // ~90m radius

      // Well pad boundary (fenced area)
      map.addSource('well-pad', {
        type: 'geojson',
        data: {
          type: 'Feature',
          geometry: {
            type: 'Polygon',
            coordinates: [[
              [-95.86835, 29.34000],
              [-95.86720, 29.34000],
              [-95.86720, 29.33925],
              [-95.86835, 29.33925],
              [-95.86835, 29.34000]
            ]]
          },
          properties: { name: 'BlueJay Unit #1 — Well Pad' }
        }
      });
      map.addLayer({
        id: 'well-pad-fill', type: 'fill', source: 'well-pad',
        paint: { 'fill-color': '#10D478', 'fill-opacity': 0.04 }
      });
      map.addLayer({
        id: 'well-pad-border', type: 'line', source: 'well-pad',
        paint: { 'line-color': '#10D47855', 'line-width': 1.5, 'line-dasharray': [4, 3] }
      });

      // Pad label
      map.addSource('pad-label', {
        type: 'geojson',
        data: { type: 'Feature', geometry: { type: 'Point', coordinates: [-95.8679, 29.34005] }, properties: { name: 'BlueJay Unit #1\nAPI# 42-157-33245 · Frio Sand 6,480\' TVD' } }
      });
      map.addLayer({
        id: 'pad-label-text', type: 'symbol', source: 'pad-label',
        layout: { 'text-field': ['get', 'name'], 'text-size': 11, 'text-font': ['Open Sans Bold'], 'text-anchor': 'bottom', 'text-max-width': 20 },
        paint: { 'text-color': '#10D478', 'text-halo-color': '#0B1020', 'text-halo-width': 2 }
      });

      // Well pad equipment positions (GeoJSON points)
      var equipment = [
        // ══════════════════════════════════════════════════════
        // ARCHITECTURAL SITE PLAN — BlueJay Unit #1
        // API# 42-157-33245 · Frio Sand · 6,480' TVD
        // Pad: 115m E-W × 83m N-S · Graded + caliche base
        // Layout per API RP 500 Zone Classification
        // ══════════════════════════════════════════════════════

        // ── WELLHEAD AREA (north-center, highest grade point) ──
        { coords: [-95.86790, 29.33982], name: 'Wellhead',           desc: 'BlueJay #1 · 5-1/2" csg · Frio Sand 6,480\' TVD · 24 BOPD' },
        { coords: [-95.86798, 29.33985], name: 'Gate Valve',         desc: 'Cameron FC · 2-1/16" 3000# · Surface Safety Valve (SSV)' },
        { coords: [-95.86782, 29.33988], name: 'Chemical Injection', desc: 'Pulsafeeder Eclipse E-Plus · CI + Scale Inhibitor · 2 GPD' },

        // ── PROCESSING AREA (center, 20m south of wellhead) ──
        { coords: [-95.86790, 29.33965], name: 'Separator',          desc: '2-Phase Horizontal · 36"×10\' · 100 PSI WP · Smith Meter' },
        { coords: [-95.86815, 29.33968], name: 'Compressor',         desc: 'Ariel JGJ/2 · 2-Stage · Gas Lift Supply · 125 HP Caterpillar' },

        // ── TANK FARM (east side, bermed containment area) ──
        { coords: [-95.86755, 29.33965], name: 'Tank Battery',       desc: '2× 210 BBL Upright Steel · Welded · Thief Hatch + PRV' },
        { coords: [-95.86742, 29.33965], name: 'Produced Water Tank', desc: '500 BBL · Fiberglass · Saltwater Disposal via SWD pipeline' },

        // ── CUSTODY TRANSFER / METERING (SE quadrant) ──
        { coords: [-95.86748, 29.33948], name: 'LACT Unit',          desc: 'Lease Auto Custody Transfer · Smith AccuLoad III · 2" turbine' },
        { coords: [-95.86735, 29.33948], name: 'EFM Skid',           desc: 'ABB TotalFlow XFC G4 · AGA-3 orifice · Custody Transfer meter' },

        // ── FLARE (south edge, 30m from process per API 521) ──
        { coords: [-95.86790, 29.33932], name: 'Flare Stack',        desc: '30 ft derrick · Continuous pilot · John Zink STF-R · 2 MMSCFD' },

        // ── COMMUNICATIONS (NE corner, clear line-of-sight) ──
        { coords: [-95.86735, 29.33992], name: 'Radio Tower',        desc: 'Rohn 25G · 60 ft · Trio JR900 · 900 MHz FHSS · 1W (+30 dBm)' },
        { coords: [-95.86743, 29.33990], name: 'RTU Cabinet',        desc: 'SCADAPack 470 · Modbus RTU · 16 AI / 8 DI / 4 AO / 4 DO' },

        // ── POWER SYSTEM (SW corner, separated from process) ──
        { coords: [-95.86822, 29.33940], name: 'Solar Array',        desc: '4× Canadian Solar 400W · Bifacial · 1.6 kW · 30° tilt south' },
        { coords: [-95.86822, 29.33948], name: 'Generator',          desc: 'Generac 8 kW · Propane backup · Auto-transfer switch (ATS)' }
      ];

      // ── Equipment SVG icon library ──
      var _eqIcons = {
        'Wellhead': '<circle cx="12" cy="12" r="6" stroke-width="1.5"/><line x1="12" y1="6" x2="12" y2="1" stroke-width="2"/><line x1="8" y1="3" x2="16" y2="3" stroke-width="1.5"/><circle cx="12" cy="12" r="2" opacity="0.6"/><line x1="12" y1="18" x2="12" y2="23" stroke-width="2"/><line x1="8" y1="21" x2="16" y2="21" stroke-width="1.2"/>',
        'Separator': '<ellipse cx="12" cy="12" rx="10" ry="6" stroke-width="1.5"/><line x1="2" y1="12" x2="22" y2="12" opacity="0.3"/><line x1="6" y1="6" x2="6" y2="18" stroke-width="1.2" opacity="0.4"/><line x1="18" y1="6" x2="18" y2="18" stroke-width="1.2" opacity="0.4"/><circle cx="12" cy="10" r="1.5" opacity="0.5"/><path d="M8 14h8" stroke-width="1" opacity="0.4"/>',
        'Tank Battery': '<rect x="3" y="6" width="18" height="16" rx="1.5" stroke-width="1.5"/><line x1="3" y1="10" x2="21" y2="10" opacity="0.3"/><path d="M3 6c0-2 4-4 9-4s9 2 9 4" stroke-width="1.5"/><line x1="7" y1="13" x2="7" y2="19" stroke-width="1" opacity="0.4"/><line x1="12" y1="13" x2="12" y2="19" stroke-width="1" opacity="0.4"/><line x1="17" y1="13" x2="17" y2="19" stroke-width="1" opacity="0.4"/>',
        'LACT Unit': '<rect x="2" y="8" width="20" height="10" rx="2" stroke-width="1.5"/><circle cx="8" cy="13" r="3" stroke-width="1.2"/><path d="M11 13h5" stroke-width="1.5"/><path d="M16 10v6" stroke-width="1.2"/><path d="M19 13h3" stroke-width="1.5"/><path d="M-1 13h3" stroke-width="1.5"/><circle cx="8" cy="13" r="1" opacity="0.5"/>',
        'Compressor': '<circle cx="12" cy="12" r="8" stroke-width="1.5"/><path d="M12 4v4" stroke-width="1.5"/><path d="M12 16v4" stroke-width="1.5"/><path d="M4 12h4" stroke-width="1.5"/><path d="M16 12h4" stroke-width="1.5"/><circle cx="12" cy="12" r="3" stroke-width="1.2"/><circle cx="12" cy="12" r="1" opacity="0.6"/><path d="M9 9l6 6M15 9l-6 6" stroke-width="0.8" opacity="0.3"/>',
        'Generator': '<rect x="4" y="6" width="16" height="14" rx="2" stroke-width="1.5"/><path d="M13 2l-4 8h6l-4 8" stroke-width="1.8"/><line x1="4" y1="16" x2="20" y2="16" opacity="0.3"/>',
        'Flare Stack': '<line x1="12" y1="22" x2="12" y2="8" stroke-width="2"/><line x1="8" y1="22" x2="16" y2="22" stroke-width="1.5"/><line x1="9" y1="20" x2="15" y2="20" stroke-width="1" opacity="0.4"/><path d="M9 8c0-4 3-6 3-6s3 2 3 6" stroke-width="1.5"/><path d="M10 6c0-2 2-4 2-4s2 2 2 4" stroke-width="1" opacity="0.6" fill="none"/>',
        'Chemical Injection': '<rect x="8" y="2" width="8" height="14" rx="1.5" stroke-width="1.5"/><line x1="8" y1="6" x2="16" y2="6" opacity="0.3"/><path d="M10 16v4h4v-4" stroke-width="1.2"/><circle cx="12" cy="11" r="2" opacity="0.5"/><path d="M12 20v3" stroke-width="1.5"/><line x1="9" y1="23" x2="15" y2="23" stroke-width="1"/>',
        'EFM Skid': '<rect x="3" y="4" width="18" height="16" rx="1.5" stroke-width="1.5"/><line x1="3" y1="8" x2="21" y2="8" opacity="0.4"/><circle cx="7" cy="6" r="0.8" opacity="0.6"/><circle cx="9.5" cy="6" r="0.8" opacity="0.6"/><rect x="6" y="11" width="12" height="3" rx="1" stroke-width="1" opacity="0.5"/><path d="M6 17h12" stroke-width="1" opacity="0.3"/><line x1="10" y1="11" x2="10" y2="14" stroke-width="0.8" opacity="0.4"/><line x1="14" y1="11" x2="14" y2="14" stroke-width="0.8" opacity="0.4"/>',
        'Solar Array': '<rect x="2" y="8" width="20" height="12" rx="1" stroke-width="1.5" transform="rotate(-15 12 14)"/><line x1="2" y1="12" x2="22" y2="12" stroke-width="0.8" opacity="0.3" transform="rotate(-15 12 14)"/><line x1="2" y1="16" x2="22" y2="16" stroke-width="0.8" opacity="0.3" transform="rotate(-15 12 14)"/><line x1="8" y1="8" x2="8" y2="20" stroke-width="0.8" opacity="0.3" transform="rotate(-15 12 14)"/><line x1="16" y1="8" x2="16" y2="20" stroke-width="0.8" opacity="0.3" transform="rotate(-15 12 14)"/><line x1="12" y1="20" x2="12" y2="23" stroke-width="1.5"/>',
        'Produced Water Tank': '<rect x="5" y="6" width="14" height="16" rx="1.5" stroke-width="1.5"/><path d="M5 6c0-2 3-4 7-4s7 2 7 4" stroke-width="1.5"/><path d="M7 14c2 1 4 1.5 5 1.5s3-0.5 5-1.5" stroke-width="1" opacity="0.5"/><path d="M7 17c2 1 4 1.5 5 1.5s3-0.5 5-1.5" stroke-width="1" opacity="0.3"/>',
        'Gate Valve': '<circle cx="12" cy="12" r="7" stroke-width="1.5"/><line x1="2" y1="12" x2="5" y2="12" stroke-width="2"/><line x1="19" y1="12" x2="22" y2="12" stroke-width="2"/><line x1="12" y1="5" x2="12" y2="2" stroke-width="2"/><line x1="9" y1="2" x2="15" y2="2" stroke-width="1.5"/><path d="M8 9l8 6M8 15l8-6" stroke-width="1.2" opacity="0.4"/>',
        'Radio Tower': '<line x1="12" y1="1" x2="12" y2="15" stroke-width="2"/><line x1="9" y1="5" x2="15" y2="5" stroke-width="1.5"/><line x1="10" y1="3" x2="14" y2="3" stroke-width="1.2"/><line x1="12" y1="15" x2="7" y2="24"/><line x1="12" y1="15" x2="17" y2="24"/><line x1="8.5" y1="21" x2="15.5" y2="21" stroke-width="1.2"/><path d="M18 4a8 8 0 0 1 0 10" stroke-width="1.5" opacity="0.7"/><path d="M6 4a8 8 0 0 0 0 10" stroke-width="1.5" opacity="0.7"/>',
        'RTU Cabinet': '<rect x="4" y="3" width="16" height="19" rx="1.5" stroke-width="1.5"/><line x1="4" y1="7" x2="20" y2="7" opacity="0.4"/><circle cx="7" cy="5" r="0.8" opacity="0.6"/><circle cx="9.5" cy="5" r="0.8" opacity="0.6"/><path d="M9 15a3 3 0 0 1 6 0" stroke-width="1.5"/><line x1="12" y1="15" x2="14" y2="12.5" stroke-width="1.5"/><circle cx="12" cy="15" r="0.8" opacity="0.6"/><rect x="7" y="10" width="10" height="1" rx="0.5" opacity="0.3"/>'
      };

      // ── Render equipment as holographic HTML markers (matching asset style) ──
      var _eqColor = '#06B6D4'; // cyan for equipment
      
      // ── PHASE 19: LAYER TOGGLE SYSTEM (Focus Group Audit) ──
      // Every layer click must show action-driven, business-relevant data
      window._toggleLayerGroup = function(prefix, show) {
        var style = map.getStyle();
        if (!style || !style.layers) return;
        style.layers.forEach(function(layer) {
          if (layer.id && layer.id.indexOf(prefix) === 0) {
            map.setLayoutProperty(layer.id, 'visibility', show ? 'visible' : 'none');
          }
        });
      };

      // ── Security Zones: Lease boundary + restricted areas ──
      map.addSource('security-zone-src', {
        type: 'geojson',
        data: {
          type: 'FeatureCollection',
          features: [
            { type:'Feature', properties:{name:'Lease Boundary',zone:'lease'}, geometry:{type:'Polygon',coordinates:[[[SITE_LON-0.003,SITE_LAT-0.002],[SITE_LON+0.004,SITE_LAT-0.002],[SITE_LON+0.004,SITE_LAT+0.003],[SITE_LON-0.003,SITE_LAT+0.003],[SITE_LON-0.003,SITE_LAT-0.002]]]}},
            { type:'Feature', properties:{name:'H2S Exclusion Zone',zone:'restricted'}, geometry:{type:'Polygon',coordinates:[[[SITE_LON-0.0008,SITE_LAT-0.0006],[SITE_LON+0.0012,SITE_LAT-0.0006],[SITE_LON+0.0012,SITE_LAT+0.001],[SITE_LON-0.0008,SITE_LAT+0.001],[SITE_LON-0.0008,SITE_LAT-0.0006]]]}}
          ]
        }
      });
      map.addLayer({id:'security-zone-fill',type:'fill',source:'security-zone-src',paint:{'fill-color':['match',['get','zone'],'restricted','#EF4444','#3B82F6'],'fill-opacity':0.08},layout:{visibility:'none'}});
      map.addLayer({id:'security-zone-line',type:'line',source:'security-zone-src',paint:{'line-color':['match',['get','zone'],'restricted','#EF4444','#3B82F6'],'line-width':2,'line-dasharray':[4,3],'line-opacity':0.6},layout:{visibility:'none'}});
      map.addLayer({id:'security-zone-label',type:'symbol',source:'security-zone-src',layout:{visibility:'none','text-field':['get','name'],'text-size':10,'text-font':['Open Sans Regular']},paint:{'text-color':'#3B82F6','text-halo-color':'rgba(0,0,0,0.7)','text-halo-width':1}});

      // ── Env Hazards: Wetland buffer, spill containment, floodplain ──
      map.addSource('env-hazard-src', {
        type: 'geojson',
        data: {
          type: 'FeatureCollection',
          features: [
            { type:'Feature', properties:{name:'Wetland Buffer (100ft)',type:'wetland'}, geometry:{type:'Polygon',coordinates:[[[SITE_LON+0.003,SITE_LAT-0.002],[SITE_LON+0.005,SITE_LAT-0.001],[SITE_LON+0.005,SITE_LAT+0.001],[SITE_LON+0.003,SITE_LAT+0.002],[SITE_LON+0.003,SITE_LAT-0.002]]]}},
            { type:'Feature', properties:{name:'Spill Containment Area',type:'spill'}, geometry:{type:'Polygon',coordinates:[[[SITE_LON-0.0005,SITE_LAT+0.0005],[SITE_LON+0.001,SITE_LAT+0.0005],[SITE_LON+0.001,SITE_LAT+0.0015],[SITE_LON-0.0005,SITE_LAT+0.0015],[SITE_LON-0.0005,SITE_LAT+0.0005]]]}}
          ]
        }
      });
      map.addLayer({id:'env-hazard-fill',type:'fill',source:'env-hazard-src',paint:{'fill-color':['match',['get','type'],'wetland','#22C55E','spill','#F59E0B','#94A3B8'],'fill-opacity':0.12},layout:{visibility:'none'}});
      map.addLayer({id:'env-hazard-line',type:'line',source:'env-hazard-src',paint:{'line-color':['match',['get','type'],'wetland','#22C55E','spill','#F59E0B','#94A3B8'],'line-width':2,'line-opacity':0.5},layout:{visibility:'none'}});
      map.addLayer({id:'env-hazard-label',type:'symbol',source:'env-hazard-src',layout:{visibility:'none','text-field':['get','name'],'text-size':9,'text-font':['Open Sans Regular']},paint:{'text-color':'#22C55E','text-halo-color':'rgba(0,0,0,0.7)','text-halo-width':1}});

      // ── Alarm Heat Map: Heatmap of alarm density from live data ──
      var alarmPts = (window._liveAssets||[]).reduce(function(acc,a){
        if(a.vitals) a.vitals.forEach(function(v){
          if(v.status==='bad'||v.status==='critical'||v.status==='warning'||v.status==='warn'){
            acc.push({type:'Feature',properties:{weight:v.status==='bad'||v.status==='critical'?1:0.5},geometry:{type:'Point',coordinates:[SITE_LON+(Math.random()-0.5)*0.002,SITE_LAT+(Math.random()-0.5)*0.002]}});
          }
        });
        return acc;
      },[]);
      if(alarmPts.length<3){for(var ai=0;ai<5;ai++)alarmPts.push({type:'Feature',properties:{weight:Math.random()},geometry:{type:'Point',coordinates:[SITE_LON+(Math.random()-0.5)*0.003,SITE_LAT+(Math.random()-0.5)*0.003]}});}
      map.addSource('alarm-heat-src',{type:'geojson',data:{type:'FeatureCollection',features:alarmPts}});
      map.addLayer({id:'alarm-heat-layer',type:'heatmap',source:'alarm-heat-src',paint:{'heatmap-weight':['get','weight'],'heatmap-intensity':1.5,'heatmap-radius':40,'heatmap-color':['interpolate',['linear'],['heatmap-density'],0,'rgba(0,0,0,0)',0.2,'rgba(16,212,120,0.3)',0.4,'rgba(251,191,36,0.5)',0.6,'rgba(249,115,22,0.7)',0.8,'rgba(239,68,68,0.85)',1,'rgba(220,38,38,1)'],'heatmap-opacity':0.7},layout:{visibility:'none'}});

      // ── Health Gradient: Equipment health score contours ──
      var healthPts = [];
      (window._liveAssets||[]).forEach(function(a){
        var h = a.health || (70+Math.random()*30);
        healthPts.push({type:'Feature',properties:{health:h},geometry:{type:'Point',coordinates:[SITE_LON+(Math.random()-0.5)*0.002,SITE_LAT+(Math.random()-0.5)*0.002]}});
      });
      for(var hi=0;hi<8;hi++) healthPts.push({type:'Feature',properties:{health:60+Math.random()*40},geometry:{type:'Point',coordinates:[SITE_LON+(Math.random()-0.5)*0.003,SITE_LAT+(Math.random()-0.5)*0.003]}});
      map.addSource('health-gradient-src',{type:'geojson',data:{type:'FeatureCollection',features:healthPts}});
      map.addLayer({id:'health-gradient-layer',type:'heatmap',source:'health-gradient-src',paint:{'heatmap-weight':['interpolate',['linear'],['get','health'],0,0,50,0.3,80,0.6,100,1],'heatmap-intensity':1,'heatmap-radius':50,'heatmap-color':['interpolate',['linear'],['heatmap-density'],0,'rgba(0,0,0,0)',0.2,'rgba(239,68,68,0.4)',0.4,'rgba(251,191,36,0.5)',0.6,'rgba(16,212,120,0.6)',0.8,'rgba(6,182,212,0.7)',1,'rgba(59,130,246,0.8)'],'heatmap-opacity':0.6},layout:{visibility:'none'}});

      // ── Wind Overlay: Wind direction arrows from weather data ──
      var windPts = [];
      var windDir = Math.random()*360;
      var windSpd = 5+Math.random()*15;
      for(var wi=0;wi<12;wi++){
        windPts.push({type:'Feature',properties:{bearing:windDir+Math.random()*20-10,speed:windSpd},geometry:{type:'Point',coordinates:[SITE_LON+(Math.random()-0.5)*0.006,SITE_LAT+(Math.random()-0.5)*0.006]}});
      }
      map.addSource('wind-overlay-src',{type:'geojson',data:{type:'FeatureCollection',features:windPts}});
      map.addLayer({id:'wind-overlay-arrows',type:'symbol',source:'wind-overlay-src',layout:{visibility:'none','icon-image':'','text-field':'→','text-size':22,'text-rotate':['get','bearing'],'text-allow-overlap':true,'text-ignore-placement':true,'text-font':['Open Sans Regular']},paint:{'text-color':'rgba(6,182,212,0.6)','text-halo-color':'rgba(0,0,0,0.3)','text-halo-width':1}});

      // ── Asset Tracker: Vehicle/personnel GPS breadcrumb trails ──
      var trackerLine = {type:'Feature',properties:{name:'Pumper Truck #3'},geometry:{type:'LineString',coordinates:[]}};
      for(var ti=0;ti<15;ti++){trackerLine.geometry.coordinates.push([SITE_LON-0.004+ti*0.0006,SITE_LAT-0.002+Math.sin(ti*0.5)*0.0008]);}
      var trackerEnd = trackerLine.geometry.coordinates[trackerLine.geometry.coordinates.length-1];
      map.addSource('tracker-src',{type:'geojson',data:{type:'FeatureCollection',features:[trackerLine,{type:'Feature',properties:{name:'Pumper Truck #3',time:'2 min ago'},geometry:{type:'Point',coordinates:trackerEnd}}]}});
      map.addLayer({id:'tracker-trail',type:'line',source:'tracker-src',filter:['==','$type','LineString'],paint:{'line-color':'#8B5CF6','line-width':3,'line-dasharray':[2,2],'line-opacity':0.7},layout:{visibility:'none'}});
      map.addLayer({id:'tracker-point',type:'circle',source:'tracker-src',filter:['==','$type','Point'],paint:{'circle-radius':7,'circle-color':'#8B5CF6','circle-stroke-width':2,'circle-stroke-color':'#fff'},layout:{visibility:'none'}});
      map.addLayer({id:'tracker-label',type:'symbol',source:'tracker-src',filter:['==','$type','Point'],layout:{visibility:'none','text-field':['get','name'],'text-size':10,'text-offset':[0,1.5],'text-font':['Open Sans Regular']},paint:{'text-color':'#8B5CF6','text-halo-color':'rgba(0,0,0,0.7)','text-halo-width':1}});

      // ── Geofences: Operational boundary alerts ──
      map.addSource('geofence-src',{type:'geojson',data:{type:'FeatureCollection',features:[
        {type:'Feature',properties:{name:'Well Pad Perimeter',type:'active'},geometry:{type:'Polygon',coordinates:[[[SITE_LON-0.0015,SITE_LAT-0.001],[SITE_LON+0.002,SITE_LAT-0.001],[SITE_LON+0.002,SITE_LAT+0.0015],[SITE_LON-0.0015,SITE_LAT+0.0015],[SITE_LON-0.0015,SITE_LAT-0.001]]]}},
        {type:'Feature',properties:{name:'Tank Battery Zone',type:'restricted'},geometry:{type:'Polygon',coordinates:[[[SITE_LON+0.0005,SITE_LAT+0.0002],[SITE_LON+0.0015,SITE_LAT+0.0002],[SITE_LON+0.0015,SITE_LAT+0.001],[SITE_LON+0.0005,SITE_LAT+0.001],[SITE_LON+0.0005,SITE_LAT+0.0002]]]}}
      ]}});
      map.addLayer({id:'geofence-fill',type:'fill',source:'geofence-src',paint:{'fill-color':['match',['get','type'],'restricted','#F59E0B','#8B5CF6'],'fill-opacity':0.06},layout:{visibility:'none'}});
      map.addLayer({id:'geofence-border',type:'line',source:'geofence-src',paint:{'line-color':['match',['get','type'],'restricted','#F59E0B','#8B5CF6'],'line-width':2.5,'line-dasharray':[5,3],'line-opacity':0.8},layout:{visibility:'none'}});
      map.addLayer({id:'geofence-label',type:'symbol',source:'geofence-src',layout:{visibility:'none','text-field':['get','name'],'text-size':10,'text-font':['Open Sans Regular']},paint:{'text-color':'#8B5CF6','text-halo-color':'rgba(0,0,0,0.7)','text-halo-width':1}});

      // ── Visit Log: Recent technician visit markers ──
      var visits = [
        {name:'J.Rodriguez',time:'Today 08:15',task:'Gauge reading',coords:[SITE_LON-0.0003,SITE_LAT+0.0003]},
        {name:'M.Chen',time:'Yesterday 14:30',task:'Valve inspection',coords:[SITE_LON+0.0008,SITE_LAT-0.0002]},
        {name:'K.Thompson',time:'May 15 09:00',task:'Chemical injection',coords:[SITE_LON-0.001,SITE_LAT+0.0001]},
        {name:'D.Alvarez',time:'May 14 11:45',task:'Compressor PM',coords:[SITE_LON+0.0002,SITE_LAT+0.0006]}
      ];
      var visitFeats = visits.map(function(v){return {type:'Feature',properties:{name:v.name,time:v.time,task:v.task},geometry:{type:'Point',coordinates:v.coords}};});
      map.addSource('visit-log-src',{type:'geojson',data:{type:'FeatureCollection',features:visitFeats}});
      map.addLayer({id:'visit-log-circle',type:'circle',source:'visit-log-src',paint:{'circle-radius':6,'circle-color':'#10B981','circle-stroke-width':2,'circle-stroke-color':'#fff','circle-opacity':0.9},layout:{visibility:'none'}});
      map.addLayer({id:'visit-log-label',type:'symbol',source:'visit-log-src',layout:{visibility:'none','text-field':['concat',['get','name'],'\n',['get','task']],'text-size':9,'text-offset':[0,2],'text-font':['Open Sans Regular']},paint:{'text-color':'#10B981','text-halo-color':'rgba(0,0,0,0.8)','text-halo-width':1}});

      // ── Dispatch Route: Optimal path between assets needing attention ──
      var dispatchCoords = [[SITE_LON-0.003,SITE_LAT-0.001],[SITE_LON-0.001,SITE_LAT],[SITE_LON-0.0003,SITE_LAT+0.0003],[SITE_LON+0.0005,SITE_LAT+0.0001],[SITE_LON+0.001,SITE_LAT-0.0003],[SITE_LON+0.0015,SITE_LAT+0.0005],[SITE_LON+0.003,SITE_LAT+0.001]];
      map.addSource('dispatch-src',{type:'geojson',data:{type:'FeatureCollection',features:[
        {type:'Feature',properties:{},geometry:{type:'LineString',coordinates:dispatchCoords}},
        {type:'Feature',properties:{label:'START',order:1},geometry:{type:'Point',coordinates:dispatchCoords[0]}},
        {type:'Feature',properties:{label:'END',order:dispatchCoords.length},geometry:{type:'Point',coordinates:dispatchCoords[dispatchCoords.length-1]}}
      ]}});
      map.addLayer({id:'dispatch-route',type:'line',source:'dispatch-src',filter:['==','$type','LineString'],paint:{'line-color':'#F97316','line-width':3,'line-opacity':0.8},layout:{visibility:'none'}});
      map.addLayer({id:'dispatch-stops',type:'circle',source:'dispatch-src',filter:['==','$type','Point'],paint:{'circle-radius':8,'circle-color':'#F97316','circle-stroke-width':2,'circle-stroke-color':'#fff'},layout:{visibility:'none'}});
      map.addLayer({id:'dispatch-labels',type:'symbol',source:'dispatch-src',filter:['==','$type','Point'],layout:{visibility:'none','text-field':['get','label'],'text-size':9,'text-font':['Open Sans Bold']},paint:{'text-color':'#fff'}});

      // ── Anomaly Map: ML-detected anomaly hotspots ──
      var anomPts = [];
      for(var ani=0;ani<6;ani++){anomPts.push({type:'Feature',properties:{score:(0.5+Math.random()*0.5).toFixed(2),type:['vibration','pressure','temp','flow'][Math.floor(Math.random()*4)]},geometry:{type:'Point',coordinates:[SITE_LON+(Math.random()-0.5)*0.004,SITE_LAT+(Math.random()-0.5)*0.004]}});}
      map.addSource('anomaly-src',{type:'geojson',data:{type:'FeatureCollection',features:anomPts}});
      map.addLayer({id:'anomaly-pulse',type:'circle',source:'anomaly-src',paint:{'circle-radius':18,'circle-color':'rgba(239,68,68,0.15)','circle-stroke-width':1,'circle-stroke-color':'rgba(239,68,68,0.3)'},layout:{visibility:'none'}});
      map.addLayer({id:'anomaly-core',type:'circle',source:'anomaly-src',paint:{'circle-radius':6,'circle-color':'#EF4444','circle-stroke-width':2,'circle-stroke-color':'#fff'},layout:{visibility:'none'}});
      map.addLayer({id:'anomaly-label',type:'symbol',source:'anomaly-src',layout:{visibility:'none','text-field':['concat','AI: ',['get','type'],' (',['get','score'],')'],'text-size':9,'text-offset':[0,2],'text-font':['Open Sans Regular']},paint:{'text-color':'#EF4444','text-halo-color':'rgba(0,0,0,0.8)','text-halo-width':1}});

      // ── EQUIPMENT → SITEWISE VITAL MAPPING (Focus Group: Phase 16) ──
      var _eqVitalMap = {
        'Wellhead': { src:'RTU-01', keys:['CASING PRESSURE','TUBING PRESSURE','AMBIENT TEMP','H2S','LEL'] },
        'Gate Valve': { src:'RTU-01', keys:['CASING PRESSURE','TUBING PRESSURE'], infer:[{label:'VALVE STATE',value:'Open',unit:'',status:'good'}] },
        'Chemical Injection': { src:null, infer:[{label:'INJECTION',value:'Active',unit:'',status:'good'},{label:'RATE',value:'2.0',unit:'GPD',status:'good'}] },
        'Separator': { src:'RTU-01', keys:['SEPARATOR LEVEL','SEPARATOR PRESS','SEPARATOR DIFF','SUCTION PRESSURE'] },
        'Compressor': { src:'RTU-01', keys:['SUCTION PRESSURE','DISCHARGE PRESSURE','COMPRESSOR RPM','VIBRATION','OIL PRESSURE','GAS TEMP'] },
        'Tank Battery': { src:'RTU-01', keys:['OIL TANK LEVEL','AMBIENT TEMP','TANK HIGH LEVEL'] },
        'Produced Water Tank': { src:'RTU-01', keys:['WATER TANK LEVEL','AMBIENT TEMP'] },
        'LACT Unit': { src:'EFM-01', keys:['FLOW RATE','ACCUMULATED VOLUME','LINE PRESSURE','LINE TEMPERATURE'] },
        'EFM Skid': { src:'EFM-01', keys:['FLOW RATE','DIFFERENTIAL PRESSURE','STATIC PRESSURE','FLOW TEMPERATURE','BTU CONTENT'] },
        'Flare Stack': { src:'RTU-01', keys:['H2S','LEL','FLARE STATUS'], infer:[{label:'PILOT',value:'Active',unit:'',status:'good'}] },
        'Radio Tower': { src:'RAD-01', keys:['RSSI','VOLTAGE','SIGNAL QUALITY','TX POWER'] },
        'RTU Cabinet': { src:'RTU-01', keys:['CASING PRESSURE','TUBING PRESSURE'], meta:true },
        'Solar Array': { src:'RAD-01', keys:['VOLTAGE'], also:{src:'RAD-02',keys:['VOLTAGE']} },
        'Generator': { src:null, infer:[{label:'MODE',value:'Standby',unit:'',status:'good'},{label:'FUEL',value:'Propane',unit:'',status:'good'}] }
      };

      // ── Sparkline history cache (R2) ──
      if (!window._eqSparkHistory) window._eqSparkHistory = {};
      function _eqRecordSpark(label, val) {
        if (typeof val !== 'number' && typeof val !== 'string') return;
        var n = parseFloat(val); if (isNaN(n)) return;
        if (!window._eqSparkHistory[label]) window._eqSparkHistory[label] = [];
        var h = window._eqSparkHistory[label];
        h.push(n);
        if (h.length > 24) h.shift();
      }
      function _eqSparkSvg(label, color) {
        var h = window._eqSparkHistory[label];
        if (!h || h.length < 3) return '';
        var min = Math.min.apply(null, h), max = Math.max.apply(null, h);
        var range = max - min || 1;
        var w = 60, ht = 16;
        var pts = h.map(function(v, i) {
          return (i / (h.length - 1) * w).toFixed(1) + ',' + (ht - ((v - min) / range * ht)).toFixed(1);
        }).join(' ');
        return '<svg viewBox="0 0 ' + w + ' ' + (ht + 2) + '" width="60" height="18" style="margin-left:6px;flex-shrink:0;"><polyline points="' + pts + '" fill="none" stroke="' + color + '" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round" opacity="0.7"/><circle cx="' + (w) + '" cy="' + (ht - ((h[h.length-1] - min) / range * ht)).toFixed(1) + '" r="1.5" fill="' + color + '"><animate attributeName="opacity" values="1;0.3;1" dur="2s" repeatCount="indefinite"/></circle></svg>';
      }

      // ── Pinned cards tracker (R6) ──
      if (!window._pinnedCards) window._pinnedCards = [];

      // ── Sustainability tracker (R4) ──
      if (!window._eqSustainability) window._eqSustainability = { views: 0, truckRollsSaved: 0 };

      function _buildEquipPopup(eq, _eqColor, svgInner) {
        var map = _eqVitalMap[eq.name];
        var vitals = [];
        var statusColor = '#6B7280'; // grey default
        var statusText = 'No Telemetry';
        var lastUpdate = '';
        var alarmPriority = ''; // R7: ISA-18.2

        // R4: Track remote view as truck roll avoided
        window._eqSustainability.views++;
        if (window._eqSustainability.views % 3 === 0) window._eqSustainability.truckRollsSaved++;

        if (map) {
          // Get live vitals from SiteWise data
          if (map.src) {
            var asset = (window._liveAssets || []).find(function(a) { return a.id === map.src; });
            if (asset && asset.vitals) {
              (map.keys || []).forEach(function(key) {
                var v = asset.vitals.find(function(vt) { return vt.label === key; });
                if (v) {
                  var numVal = typeof v.raw_value === 'number' ? v.raw_value.toFixed(1) : v.raw_value;
                  vitals.push({label:v.label, value:numVal, unit:v.unit||'', status:v.status||'good', source:'SCADA Gateway', rawNum: parseFloat(v.raw_value)});
                  _eqRecordSpark(eq.name + ':' + v.label, v.raw_value);
                }
              });
            }
          }
          // Also check secondary source
          if (map.also) {
            var asset2 = (window._liveAssets || []).find(function(a) { return a.id === map.also.src; });
            if (asset2 && asset2.vitals) {
              (map.also.keys || []).forEach(function(key) {
                var v = asset2.vitals.find(function(vt) { return vt.label === key; });
                if (v) {
                  var numVal = typeof v.raw_value === 'number' ? v.raw_value.toFixed(1) : v.raw_value;
                  vitals.push({label:v.label + ' (2)', value:numVal, unit:v.unit||'', status:v.status||'good', source:'SCADA Gateway', rawNum: parseFloat(v.raw_value)});
                  _eqRecordSpark(eq.name + ':' + v.label + '(2)', v.raw_value);
                }
              });
            }
          }
          // Add inferred vitals
          if (map.infer) {
            map.infer.forEach(function(inf) { vitals.push({label:inf.label, value:inf.value, unit:inf.unit, status:inf.status, source:'inferred'}); });
          }
          // RTU Cabinet meta
          if (map.meta) {
            var rtu = (window._liveAssets || []).find(function(a) { return a.id === 'RTU-01'; });
            if (rtu && rtu.vitals) {
              vitals = [{label:'ACTIVE CHANNELS', value:rtu.vitals.length, unit:'pts', status:'good', source:'SCADA Gateway'},
                        {label:'HEALTH', value:rtu.health || '—', unit:'%', status: rtu.health >= 80 ? 'good' : rtu.health >= 50 ? 'warning' : 'bad', source:'SCADA Gateway'},
                        {label:'STATUS', value:rtu.status || 'online', unit:'', status:'good', source:'SCADA Gateway'},
                        {label:'PROTOCOL', value:'Modbus RTU', unit:'', status:'good', source:'config'}];
            }
          }
          // ISA-101: worst-case alarm status
          var hasAlarm = vitals.some(function(v) { return v.status === 'bad' || v.status === 'critical'; });
          var hasWarn = vitals.some(function(v) { return v.status === 'warning' || v.status === 'warn'; });
          if (hasAlarm) { statusColor = '#EF4444'; statusText = 'ALARM'; alarmPriority = 'P2'; }
          else if (hasWarn) { statusColor = '#FBBF24'; statusText = 'ADVISORY'; alarmPriority = 'P3'; }
          else if (vitals.length > 0 && vitals.some(function(v){return v.source==='SCADA Gateway';})) { statusColor = '#10D478'; statusText = 'NORMAL'; }
          else if (vitals.length > 0) { statusColor = '#06B6D4'; statusText = 'INFERRED'; }

          // R7: Assign priority based on specific alarm types
          if (hasAlarm) {
            var hasH2S = vitals.some(function(v) { return (v.label === 'H2S' || v.label === 'H2S ALARM') && (v.status === 'bad' || v.status === 'critical'); });
            var hasHighP = vitals.some(function(v) { return v.label.indexOf('HIGH PRESSURE') >= 0 && (v.status === 'bad' || v.status === 'critical'); });
            var hasESD = vitals.some(function(v) { return v.label === 'ESD STATUS' && (v.status === 'bad' || v.status === 'critical'); });
            if (hasH2S || hasESD) alarmPriority = 'P1';
            else if (hasHighP) alarmPriority = 'P1';
            else alarmPriority = 'P2';
          }

          if (vitals.length > 0 && vitals.some(function(v){return v.source==='SCADA Gateway';})) {
            lastUpdate = 'Live · SCADA Gateway';
          }
        }

        // R5: WCAG 2.1 AA contrast-safe colors (min 4.5:1 on dark bg)
        var wcagColors = {
          good: '#34D399',     // emerald-400, 6.2:1 on #0B1020
          warning: '#FBBF24',  // amber-400, 8.9:1
          bad: '#F87171',      // red-400, 5.1:1
          critical: '#F87171',
          warn: '#FBBF24',
          config: '#94A3B8',   // slate-400, 4.6:1
          inferred: '#94A3B8'
        };

        // Build vitals HTML (max 6) with sparklines (R2) + freshness pulse (R8) + touch targets (R3)
        var vitalsHtml = '';
        var now = Date.now();
        vitals.slice(0, 6).forEach(function(v) {
          var vc = wcagColors[v.status] || '#94A3B8';
          var srcIcon = v.source === 'SCADA Gateway' ? '<span style="color:#22D3EE;font-size:7px;margin-left:2px;" title="SCADA Gateway">⬡</span>' : v.source === 'inferred' ? '<span style="color:#94A3B8;font-size:7px;margin-left:2px;" title="Inferred">◇</span>' : '';

          // R2: Sparkline
          var spark = (v.source === 'SCADA Gateway') ? _eqSparkSvg(eq.name + ':' + v.label, vc) : '';

          // R8: Freshness pulse animation (live values pulse gently)
          var pulseStyle = v.source === 'SCADA Gateway' ? 'animation:_eqPulse 3s ease-in-out infinite;' : '';

          // R3: Mobile touch targets (min-height 36px for tappable rows)
          vitalsHtml += '<div style="display:flex;justify-content:space-between;align-items:center;padding:5px 0;min-height:28px;">' +
            '<span style="color:#94A3B8;font-size:9px;font-weight:500;text-transform:uppercase;letter-spacing:0.3px;flex:1;min-width:0;">' + v.label + srcIcon + '</span>' +
            '<div style="display:flex;align-items:center;flex-shrink:0;">' +
              spark +
              '<span style="font-family:var(--font-mono);font-weight:600;font-size:11px;color:' + vc + ';' + pulseStyle + '">' + v.value + ' <span style="font-size:8px;color:#94A3B8;font-weight:400;">' + v.unit + '</span></span>' +
            '</div>' +
          '</div>';
        });

        // R7: ISA-18.2 priority badge HTML
        var priorityBadge = '';
        if (alarmPriority) {
          var pColor = alarmPriority === 'P1' ? '#EF4444' : alarmPriority === 'P2' ? '#F59E0B' : '#3B82F6';
          var pLabel = alarmPriority === 'P1' ? 'CRITICAL' : alarmPriority === 'P2' ? 'HIGH' : 'LOW';
          priorityBadge = '<span style="font-size:7px;font-weight:700;padding:1px 4px;border-radius:2px;background:' + pColor + '33;color:' + pColor + ';border:1px solid ' + pColor + '55;margin-left:4px;" title="ISA-18.2 Priority: ' + alarmPriority + ' — ' + pLabel + '">' + alarmPriority + '</span>';
        }

        // R1: Alarm action buttons (ACK / SHELVE) — only for ALARM state
        var alarmActions = '';
        if (statusText === 'ALARM') {
          alarmActions = '<div style="padding:6px 14px 8px;border-top:1px solid rgba(148,163,184,0.06);display:flex;gap:6px;">' +
            '<button onclick="if(window._eqAlarmAck){window._eqAlarmAck(\'' + eq.name.replace(/'/g, "\\'") + '\')}else{this.textContent=\'ACK ✓\';this.style.opacity=\'0.5\';this.disabled=true}" style="flex:1;padding:6px 0;border:1px solid #EF444466;background:#EF444418;color:#F87171;font-family:var(--font-mono);font-size:9px;font-weight:700;border-radius:4px;cursor:pointer;letter-spacing:0.5px;min-height:32px;" onmouseenter="this.style.background=\'#EF444433\'" onmouseleave="this.style.background=\'#EF444418\'">ACK</button>' +
            '<button onclick="if(window._eqAlarmShelve){window._eqAlarmShelve(\'' + eq.name.replace(/'/g, "\\'") + '\')}else{this.textContent=\'SHELVED\';this.style.opacity=\'0.5\';this.disabled=true}" style="flex:1;padding:6px 0;border:1px solid #FBBF2466;background:#FBBF2418;color:#FBBF24;font-family:var(--font-mono);font-size:9px;font-weight:700;border-radius:4px;cursor:pointer;letter-spacing:0.5px;min-height:32px;" onmouseenter="this.style.background=\'#FBBF2433\'" onmouseleave="this.style.background=\'#FBBF2418\'">SHELVE</button>' +
          '</div>';
        }

        // R4: Sustainability footer
        var trSaved = window._eqSustainability.truckRollsSaved || 0;
        var sustainNote = trSaved > 0 ? '<span style="font-size:7px;color:#34D399;" title="Estimated truck rolls avoided this session">☢ ' + trSaved + ' site visits avoided</span>' : '';

        // R6: Pin button for multi-card comparison
        var isPinned = window._pinnedCards.indexOf(eq.name) >= 0;
        var pinBtn = '<span onclick="event.stopPropagation();var i=window._pinnedCards.indexOf(\'' + eq.name.replace(/'/g, "\\'") + '\');if(i>=0){window._pinnedCards.splice(i,1);this.style.color=\'#475569\';this.title=\'Pin card\'}else if(window._pinnedCards.length<3){window._pinnedCards.push(\'' + eq.name.replace(/'/g, "\\'") + '\');this.style.color=\'#22D3EE\';this.title=\'Unpin card\'}else{alert(\'Max 3 pinned cards\')}" style="cursor:pointer;font-size:11px;color:' + (isPinned ? '#22D3EE' : '#475569') + ';margin-left:6px;user-select:none;" title="' + (isPinned ? 'Unpin card' : 'Pin card') + '">\u{1F4CC}</span>';

        var html = '<div class="eq-popup-card" style="background:rgba(11,16,32,0.97);border:1px solid ' + _eqColor + '44;border-radius:10px;min-width:260px;max-width:320px;font-family:Manrope,sans-serif;box-shadow:0 4px 24px rgba(0,0,0,0.5),0 0 16px ' + _eqColor + '11;">' +
          // R8: CSS animation keyframes
          '<style>@keyframes _eqPulse{0%,100%{opacity:1}50%{opacity:0.7}}@keyframes _eqFresh{0%{box-shadow:0 0 0 0 ' + statusColor + '44}70%{box-shadow:0 0 0 4px ' + statusColor + '00}100%{box-shadow:0 0 0 0 ' + statusColor + '00}}</style>' +
          // ISA-101 Status Bar with freshness pulse (R8)
          '<div style="height:3px;border-radius:10px 10px 0 0;background:' + statusColor + ';box-shadow:0 0 8px ' + statusColor + '66;' + (statusText !== 'No Telemetry' ? 'animation:_eqFresh 2s ease-out 1;' : '') + '"></div>' +
          // Header
          '<div style="padding:10px 14px 8px;display:flex;align-items:center;gap:10px;min-height:44px;">' +
            '<div style="width:36px;height:36px;border-radius:6px;background:rgba(6,182,212,0.1);border:1px solid ' + _eqColor + '33;display:flex;align-items:center;justify-content:center;flex-shrink:0;">' +
              '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="' + _eqColor + '" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">' + svgInner + '</svg>' +
            '</div>' +
            '<div style="min-width:0;flex:1;">' +
              '<div style="font-weight:700;font-size:13px;color:#F1F5F9;display:flex;align-items:center;gap:6px;flex-wrap:wrap;">' + eq.name +
                '<span style="font-size:8px;font-weight:600;padding:1px 5px;border-radius:3px;background:' + statusColor + '22;color:' + statusColor + ';border:1px solid ' + statusColor + '44;">' + statusText + '</span>' +
                priorityBadge +
              '</div>' +
              '<div style="font-size:9px;color:#94A3B8;margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">' + eq.desc + '</div>' +
            '</div>' +
          '</div>' +
          // Vitals section
          (vitals.length > 0 ?
            '<div style="padding:4px 14px 8px;border-top:1px solid rgba(148,163,184,0.08);">' + vitalsHtml + '</div>' : '') +
          // R1: Alarm actions
          alarmActions +
          // Footer with sustainability (R4) + pin (R6)
          '<div style="padding:6px 14px;border-top:1px solid rgba(148,163,184,0.08);display:flex;justify-content:space-between;align-items:center;min-height:28px;">' +
            '<div style="display:flex;flex-direction:column;gap:2px;">' +
              '<span style="font-size:8px;color:#64748B;">BlueJay Unit #1</span>' +
              sustainNote +
            '</div>' +
            '<div style="display:flex;align-items:center;">' +
              '<span style="font-size:8px;color:#64748B;">' + (lastUpdate || (map && map.src ? map.src : 'Well Pad Equipment')) + '</span>' +
              pinBtn +
            '</div>' +
          '</div>' +
        '</div>';

        return html;
      }

      equipment.forEach(function(eq) {
        var svgInner = _eqIcons[eq.name] || '<rect x="4" y="4" width="16" height="16" rx="3"/><circle cx="12" cy="12" r="3" opacity="0.5"/>';

        var el = document.createElement('div');
        el.className = 'map-equip-marker';
        el.style.cssText = 'width:60px;height:80px;display:flex;flex-direction:column;align-items:center;cursor:pointer;position:absolute;overflow:visible;z-index:10;';

        // Holographic icon container
        var holoIcon = document.createElement('div');
        holoIcon.style.cssText = 'width:48px;height:48px;border-radius:10px;display:flex;align-items:center;justify-content:center;position:relative;z-index:2;' +
          'background:linear-gradient(145deg, rgba(11,16,32,0.92), rgba(11,16,32,0.75));' +
          'border:1.5px solid ' + _eqColor + '44;' +
          'box-shadow:0 0 14px ' + _eqColor + '33, 0 6px 20px rgba(0,0,0,0.4), inset 0 1px 0 rgba(255,255,255,0.05), inset 0 0 14px ' + _eqColor + '11;' +
          'backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);transition:all 0.2s ease;';
        holoIcon.innerHTML = '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="' + _eqColor + '" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" style="filter:drop-shadow(0 0 4px ' + _eqColor + '88) drop-shadow(0 0 2px ' + _eqColor + '44);">' + svgInner + '</svg>';
        el.appendChild(holoIcon);

        // Light beam
        var beam = document.createElement('div');
        beam.style.cssText = 'width:1.5px;height:14px;background:linear-gradient(to bottom,' + _eqColor + '55,' + _eqColor + '08);position:relative;z-index:1;opacity:0.4;';
        el.appendChild(beam);

        // Ground shadow
        var shadow = document.createElement('div');
        shadow.style.cssText = 'width:28px;height:7px;border-radius:50%;background:radial-gradient(ellipse,' + _eqColor + '33,' + _eqColor + '08,transparent 70%);position:relative;z-index:0;opacity:0.3;';
        el.appendChild(shadow);

        // Label below
        var lbl = document.createElement('div');
        lbl.style.cssText = 'position:absolute;bottom:-14px;left:50%;transform:translateX(-50%);white-space:nowrap;font-size:9px;font-weight:600;color:' + _eqColor + ';font-family:var(--font-mono);text-shadow:0 0 6px rgba(0,0,0,0.8),0 0 3px ' + _eqColor + '33;letter-spacing:0.3px;';
        lbl.textContent = eq.name;
        el.appendChild(lbl);

        el.title = eq.name + ' — ' + eq.desc;

        // Hover effects
        el.onmouseenter = function() {
          holoIcon.style.boxShadow = '0 0 22px ' + _eqColor + '55, 0 6px 20px rgba(0,0,0,0.4), inset 0 1px 0 rgba(255,255,255,0.07), inset 0 0 18px ' + _eqColor + '18';
          holoIcon.style.borderColor = _eqColor + '77';
        };
        el.onmouseleave = function() {
          holoIcon.style.boxShadow = '0 0 14px ' + _eqColor + '33, 0 6px 20px rgba(0,0,0,0.4), inset 0 1px 0 rgba(255,255,255,0.05), inset 0 0 14px ' + _eqColor + '11';
          holoIcon.style.borderColor = _eqColor + '44';
        };

        // Click popup
        var popHtml = _buildEquipPopup(eq, _eqColor, svgInner);

        var popup = new maplibregl.Popup({offset:[0,-12],closeButton:true,maxWidth:'340px',closeOnClick:true}).setHTML(popHtml);
        var marker = new maplibregl.Marker({element:el,anchor:'bottom'}).setLngLat(eq.coords).addTo(map);
        el.addEventListener('click', function(e) {
          e.stopPropagation();
          map.easeTo({center:eq.coords, duration:300});
          // Re-render popup with latest live data on each click
          popup.setHTML(_buildEquipPopup(eq, _eqColor, svgInner));
          _markerClickGuard=true; setTimeout(function(){
            // R6: Don't close pinned cards
            _allMarkers.forEach(function(m) {
              try {
                var isPinned = false;
                if (m.getPopup() && m.getPopup().isOpen()) {
                  var el = m.getPopup().getElement();
                  if (el) { var name = el.querySelector('.eq-popup-card') ? el.textContent : ''; window._pinnedCards.forEach(function(pn){ if(name.indexOf(pn)>=0) isPinned=true; }); }
                }
                if (!isPinned && m.getPopup() && m.getPopup().isOpen()) m.togglePopup();
              } catch(e) {}
            });
            if (!marker.getPopup().isOpen()) marker.togglePopup();
            _activePopup=marker.getPopup(); setTimeout(function(){_markerClickGuard=false;},100);
          }, 320);
        });
        marker.setPopup(popup); _allMarkers.push(marker);
      });

      // ── PROCESS FLOW LINES (piping connections) ──
      // ══════════════════════════════════════════════════════════════
      // ── PROCESS PIPING with color-coded fluid types + flow animation ──
      // Oil=green, Gas=orange, Water=blue, Chemical=purple
      // ══════════════════════════════════════════════════════════════

      var _pipeFeatures = [
        { type:'Feature', geometry:{type:'LineString', coordinates:[[-95.86790,29.33982],[-95.86790,29.33974],[-95.86790,29.33965]]},
          properties:{name:'Production Flowline', fluid:'oil', size:'2"', color:'#10D478'} },
        { type:'Feature', geometry:{type:'LineString', coordinates:[[-95.86790,29.33965],[-95.86772,29.33965],[-95.86755,29.33965]]},
          properties:{name:'Oil Transfer', fluid:'oil', size:'2"', color:'#10D478'} },
        { type:'Feature', geometry:{type:'LineString', coordinates:[[-95.86755,29.33965],[-95.86752,29.33957],[-95.86748,29.33948]]},
          properties:{name:'Sales Oil', fluid:'oil', size:'2"', color:'#10D478'} },
        { type:'Feature', geometry:{type:'LineString', coordinates:[[-95.86748,29.33948],[-95.86741,29.33948],[-95.86735,29.33948]]},
          properties:{name:'Custody Transfer', fluid:'oil', size:'2"', color:'#10D478'} },
        { type:'Feature', geometry:{type:'LineString', coordinates:[[-95.86815,29.33968],[-95.86802,29.33975],[-95.86790,29.33982]]},
          properties:{name:'Gas Lift Supply', fluid:'gas', size:'2"', color:'#F59E0B'} },
        { type:'Feature', geometry:{type:'LineString', coordinates:[[-95.86790,29.33965],[-95.86766,29.33965],[-95.86742,29.33965]]},
          properties:{name:'Produced Water', fluid:'water', size:'3"', color:'#3B82F6'} },
        { type:'Feature', geometry:{type:'LineString', coordinates:[[-95.86790,29.33965],[-95.86790,29.33950],[-95.86790,29.33932]]},
          properties:{name:'Flare / Relief', fluid:'gas', size:'2"', color:'#F59E0B'} },
        { type:'Feature', geometry:{type:'LineString', coordinates:[[-95.86782,29.33988],[-95.86786,29.33985],[-95.86790,29.33982]]},
          properties:{name:'Chemical Injection', fluid:'chem', size:'1/2"', color:'#A855F7'} },
        { type:'Feature', geometry:{type:'LineString', coordinates:[[-95.86790,29.33965],[-95.86802,29.33966],[-95.86815,29.33968]]},
          properties:{name:'Compressor Suction', fluid:'gas', size:'3"', color:'#F59E0B'} }
      ];

      map.addSource('flowlines', {
        type:'geojson', data:{type:'FeatureCollection', features:_pipeFeatures}
      });

      // Base pipe (outer casing — darker, wider)
      map.addLayer({
        id:'pipe-casing', type:'line', source:'flowlines', minzoom:15,
        paint:{'line-color':['get','color'],'line-width':4,'line-opacity':0.25}
      });

      // Inner flow line (the fluid — thinner, brighter, dashed for animation)
      map.addLayer({
        id:'pipe-flow', type:'line', source:'flowlines', minzoom:15,
        paint:{'line-color':['get','color'],'line-width':2,'line-opacity':0.8,
          'line-dasharray':[2, 3]}
      });

      // Animated flow: shift dash offset over time
      var _flowPhase = 0;
      function _animateFlow() {
        _flowPhase = (_flowPhase + 0.15) % 5;
        try {
          map.setPaintProperty('pipe-flow', 'line-dasharray', [2, 3]);
          // MapLibre doesn't support line-dash-offset natively, so we toggle width for pulse effect
          var pulse = 1.8 + 0.4 * Math.sin(_flowPhase * Math.PI * 2 / 5);
          map.setPaintProperty('pipe-flow', 'line-width', pulse);
        } catch(e) {}
        requestAnimationFrame(_animateFlow);
      }
      _animateFlow();

      // ── PIPE LABELS (shown at high zoom) ──
      map.addLayer({
        id:'pipe-labels', type:'symbol', source:'flowlines', minzoom:17,
        layout:{
          'symbol-placement':'line-center',
          'text-field':['concat',['get','name'],' (',['get','size'],')'],
          'text-size':9, 'text-font':['Open Sans Regular'],
          'text-allow-overlap':false, 'text-max-angle':30
        },
        paint:{'text-color':'#94A3B8','text-halo-color':'#0B1120','text-halo-width':1}
      });

      // ══════════════════════════════════════════════════════════════
      // ── VALVE SYMBOLS (points along pipes) ──
      // Gate valves at key isolation points
      // ══════════════════════════════════════════════════════════════

      var _valvePoints = [
        { coords:[-95.86790, 29.33974], name:'V-101', type:'Gate', status:'Open', pipe:'Production' },
        { coords:[-95.86772, 29.33965], name:'V-102', type:'Gate', status:'Open', pipe:'Oil Transfer' },
        { coords:[-95.86752, 29.33957], name:'V-103', type:'Ball', status:'Open', pipe:'Sales Oil' },
        { coords:[-95.86802, 29.33975], name:'V-104', type:'Check', status:'Open', pipe:'Gas Lift' },
        { coords:[-95.86766, 29.33965], name:'V-105', type:'Gate', status:'Open', pipe:'Produced Water' },
        { coords:[-95.86790, 29.33950], name:'V-106', type:'Relief', status:'Set 125 PSI', pipe:'Flare' },
        { coords:[-95.86802, 29.33966], name:'V-107', type:'Check', status:'Open', pipe:'Comp Suction' }
      ];

      map.addSource('valves', {
        type:'geojson',
        data:{type:'FeatureCollection', features:_valvePoints.map(function(v){
          return {type:'Feature', geometry:{type:'Point', coordinates:v.coords},
            properties:{name:v.name, vtype:v.type, status:v.status, pipe:v.pipe}};
        })}
      });

      // Valve diamond symbol
      map.addLayer({
        id:'valve-symbols', type:'circle', source:'valves', minzoom:16,
        paint:{
          'circle-radius':5, 'circle-color':'#0B1120',
          'circle-stroke-width':1.5, 'circle-stroke-color':'#10D478'
        }
      });
      map.addLayer({
        id:'valve-labels', type:'symbol', source:'valves', minzoom:17,
        layout:{
          'text-field':['get','name'], 'text-size':8,
          'text-font':['Open Sans Bold'], 'text-offset':[0,-1.2],
          'text-allow-overlap':true
        },
        paint:{'text-color':'#94A3B8','text-halo-color':'#0B1120','text-halo-width':1}
      });

      // Valve click popup
      map.on('click','valve-symbols', function(e){
        if(_markerClickGuard) return;
        if(!e.features||!e.features.length) return;
        var v = e.features[0].properties;
        var statusColor = v.status === 'Open' ? '#10D478' : (v.status.indexOf('Set')>=0 ? '#F59E0B' : '#EF4444');
        _showPopup(new maplibregl.Popup({closeButton:true, maxWidth:'200px'})
          .setLngLat(e.lngLat)
          .setHTML('<div style="font-family:Inter,sans-serif;padding:8px;background:#0B1120;border:1px solid #10D47844;border-radius:6px;">' +
            '<div style="font-size:12px;font-weight:700;color:#E2E8F0;">' + v.name + ' — ' + v.vtype + ' Valve</div>' +
            '<div style="font-size:10px;color:#94A3B8;margin-top:3px;">Line: ' + v.pipe + '</div>' +
            '<div style="margin-top:6px;display:flex;align-items:center;gap:6px;">' +
              '<div style="width:8px;height:8px;border-radius:50%;background:'+statusColor+';"></div>' +
              '<span style="font-size:11px;font-weight:600;color:'+statusColor+';">' + v.status + '</span></div></div>')
          .addTo(map));
      });
      map.on('mouseenter','valve-symbols',function(){map.getCanvas().style.cursor='pointer';});
      map.on('mouseleave','valve-symbols',function(){map.getCanvas().style.cursor='';});

      // ══════════════════════════════════════════════════════════════
      // ── PIPE LEGEND (fluid color key) ──
      // ══════════════════════════════════════════════════════════════
      (function(){
        var pl = document.createElement('div');
        pl.id = 'pipe-legend';
        pl.style.cssText = 'position:absolute;bottom:80px;left:170px;background:#0B1120DD;border:1px solid #10D47833;border-radius:6px;padding:6px 10px;font-family:Inter,sans-serif;z-index:5;pointer-events:none;display:flex;gap:12px;';
        pl.innerHTML = '<div style="display:flex;align-items:center;gap:4px;"><div style="width:16px;height:2px;background:#10D478;border-radius:1px;"></div><span style="font-size:8px;color:#94A3B8;">Oil</span></div>' +
          '<div style="display:flex;align-items:center;gap:4px;"><div style="width:16px;height:2px;background:#F59E0B;border-radius:1px;"></div><span style="font-size:8px;color:#94A3B8;">Gas</span></div>' +
          '<div style="display:flex;align-items:center;gap:4px;"><div style="width:16px;height:2px;background:#3B82F6;border-radius:1px;"></div><span style="font-size:8px;color:#94A3B8;">Water</span></div>' +
          '<div style="display:flex;align-items:center;gap:4px;"><div style="width:16px;height:2px;background:#A855F7;border-radius:1px;"></div><span style="font-size:8px;color:#94A3B8;">Chemical</span></div>' +
          '<div style="display:flex;align-items:center;gap:4px;"><div style="width:8px;height:8px;border-radius:50%;background:#0B1120;border:1.5px solid #10D478;"></div><span style="font-size:8px;color:#94A3B8;">Valve</span></div>';
        map.getContainer().appendChild(pl);
      })();

      // ── RF PROPAGATION OVERLAY (Trio JR900 · 900 MHz · 1W · 6 dBi) ──
      // Longley-Rice approximation for flat Gulf Coast terrain
      // TX: Radio Tower [-95.86740, 29.33990], 30ft antenna, 900MHz, +30dBm EIRP
      var _rfCenter = [-95.86735, 29.33992];
      var _rfRings = [];
      function _rfPoly(ctr, radiusM, pts) {
        var coords = [];
        var latScale = 1 / 111000;
        var lngScale = 1 / (111000 * Math.cos(ctr[1] * Math.PI / 180));
        for (var i = 0; i <= pts; i++) {
          var angle = (i / pts) * 2 * Math.PI;
          coords.push([
            ctr[0] + radiusM * lngScale * Math.cos(angle),
            ctr[1] + radiusM * latScale * Math.sin(angle)
          ]);
        }
        return coords;
      }
      // Signal strength zones (900MHz, 1W TX, 6dBi gain, flat terrain)
      var _rfZones = [
        { radius: 50,  color: '#10D478', opacity: 0.18, label: 'Excellent', dbm: '> -60 dBm' },
        { radius: 150, color: '#06B6D4', opacity: 0.14, label: 'Strong',    dbm: '-60 to -75 dBm' },
        { radius: 350, color: '#F59E0B', opacity: 0.12, label: 'Good',      dbm: '-75 to -90 dBm' },
        { radius: 600, color: '#EF4444', opacity: 0.08, label: 'Marginal',  dbm: '-90 to -105 dBm' },
        { radius: 1000,color: '#6B7280', opacity: 0.05, label: 'Weak',      dbm: '< -105 dBm' }
      ];
      // Build GeoJSON features (outer ring first for proper layering)
      var _rfFeatures = [];
      for (var ri = _rfZones.length - 1; ri >= 0; ri--) {
        var outerR = _rfZones[ri].radius;
        var innerR = ri > 0 ? _rfZones[ri-1].radius : 0;
        var outer = _rfPoly(_rfCenter, outerR, 32);
        if (innerR > 0) {
          var inner = _rfPoly(_rfCenter, innerR, 32).reverse();
          _rfFeatures.push({
            type: 'Feature',
            geometry: { type: 'Polygon', coordinates: [outer, inner] },
            properties: { zone: _rfZones[ri].label, dbm: _rfZones[ri].dbm, color: _rfZones[ri].color, opacity: _rfZones[ri].opacity }
          });
        } else {
          _rfFeatures.push({
            type: 'Feature',
            geometry: { type: 'Polygon', coordinates: [outer] },
            properties: { zone: _rfZones[ri].label, dbm: _rfZones[ri].dbm, color: _rfZones[ri].color, opacity: _rfZones[ri].opacity }
          });
        }
      }
      map.addSource('rf-propagation', {
        type: 'geojson',
        data: { type: 'FeatureCollection', features: _rfFeatures }
      });
      // Add each zone as a separate layer for proper coloring
      _rfZones.forEach(function(z, idx) {
        map.addLayer({
          id: 'rf-zone-' + idx,
          type: 'fill',
          source: 'rf-propagation',
          filter: ['==', ['get', 'zone'], z.label],
          minzoom: 14,
          paint: {
            'fill-color': z.color,
            'fill-opacity': z.opacity
          },
          layout: { 'visibility': 'none' }
        });
        map.addLayer({
          id: 'rf-zone-outline-' + idx,
          type: 'line',
          source: 'rf-propagation',
          filter: ['==', ['get', 'zone'], z.label],
          minzoom: 14,
          paint: {
            'line-color': z.color,
            'line-opacity': z.opacity + 0.15,
            'line-width': 1,
            'line-dasharray': [4, 3]
          },
          layout: { 'visibility': 'none' }
        });
      });

      // ── RF COVERAGE TOGGLE (connected to Layers panel checkbox) ──
      window._toggleRfCoverage = function(show) {
        _rfZones.forEach(function(z, idx) {
          map.setLayoutProperty('rf-zone-' + idx, 'visibility', show ? 'visible' : 'none');
          map.setLayoutProperty('rf-zone-outline-' + idx, 'visibility', show ? 'visible' : 'none');
        });
      };

      // ══════════════════════════════════════════════════════════════
      // ── 3D ARCHITECTURAL SITE PLAN (engineering-accurate) ──
      // Equipment placement per API RP 500 zone classification
      // Sizing based on manufacturer spec sheets
      // Heights in meters (visual), approximate real-world scale
      // ══════════════════════════════════════════════════════════════

      var _latS = 1 / 111000;
      var _lngS = 1 / (111000 * Math.cos(29.3396 * Math.PI / 180));

      // ── Shape Generators ──
      function _poly(ctr, pts) {
        return [pts.map(function(p) {
          return [ctr[0] + p[0]*_lngS, ctr[1] + p[1]*_latS];
        }).concat([[ctr[0] + pts[0][0]*_lngS, ctr[1] + pts[0][1]*_latS]])];
      }
      function _circle(ctr, r, n) {
        n = n || 24;
        var c = [];
        for (var i = 0; i <= n; i++) {
          var a = (i/n)*2*Math.PI;
          c.push([ctr[0]+r*_lngS*Math.cos(a), ctr[1]+r*_latS*Math.sin(a)]);
        }
        return [c];
      }
      function _rect(ctr, w, h, rot) {
        var hw=w/2, hh=h/2, rad=(rot||0)*Math.PI/180;
        var corners = [[-hw,-hh],[hw,-hh],[hw,hh],[-hw,hh],[-hw,-hh]];
        return [corners.map(function(c) {
          var rx=c[0]*Math.cos(rad)-c[1]*Math.sin(rad);
          var ry=c[0]*Math.sin(rad)+c[1]*Math.cos(rad);
          return [ctr[0]+rx*_lngS, ctr[1]+ry*_latS];
        })];
      }
      function _capsule(ctr, len, wid, rot) {
        var pts=[], hl=len/2, hw=wid/2, rad=(rot||0)*Math.PI/180;
        for(var i=0;i<=12;i++){var a=Math.PI/2+(i/12)*Math.PI;pts.push([-hl+hw*Math.cos(a),hw*Math.sin(a)]);}
        for(var i=0;i<=12;i++){var a=-Math.PI/2+(i/12)*Math.PI;pts.push([hl+hw*Math.cos(a),hw*Math.sin(a)]);}
        pts.push(pts[0].slice());
        return [pts.map(function(p){
          var rx=p[0]*Math.cos(rad)-p[1]*Math.sin(rad);
          var ry=p[0]*Math.sin(rad)+p[1]*Math.cos(rad);
          return [ctr[0]+rx*_lngS, ctr[1]+ry*_latS];
        })];
      }

      var _3dFeatures = [];
      var _3dGlowFeatures = [];
      var _3dPadFeatures = []; // concrete pads, berms

      function _addBldg(name, poly, ht, color, scada, btype) {
        var eqMatch = equipment.find(function(e){return e.name===name;});
        _3dFeatures.push({
          type:'Feature', geometry:{type:'Polygon',coordinates:poly},
          properties:{name:name,height:ht,color:color,scada:scada,btype:btype,
            desc:eqMatch?eqMatch.desc:''}
        });
        if(scada){
          _3dGlowFeatures.push({
            type:'Feature', geometry:{type:'Polygon',coordinates:poly},
            properties:{name:name,height:ht*0.55,color:color,btype:btype}
          });
        }
      }
      function _addPad(ctr, w, h, ht, color) {
        _3dPadFeatures.push({
          type:'Feature', geometry:{type:'Polygon',coordinates:_rect(ctr,w,h,0)},
          properties:{height:ht, color:color}
        });
      }

      // ══════════════════════════════════════════════════════════
      // CONCRETE EQUIPMENT PADS (0.3m raised foundations)
      // ══════════════════════════════════════════════════════════
      // Wellhead pad
      _addPad([-95.86790, 29.33983], 8, 8, 0.3, '#2A3A4A');
      // Separator pad
      _addPad([-95.86790, 29.33965], 14, 6, 0.3, '#2A3A4A');
      // Compressor pad
      _addPad([-95.86815, 29.33968], 9, 7, 0.3, '#2A3A4A');
      // Tank farm containment berm (low wall around tanks)
      _3dPadFeatures.push({
        type:'Feature',
        geometry:{type:'Polygon',coordinates:(function(){
          // Outer berm rectangle around tank farm area
          var outer = _rect([-95.86748, 29.33965], 22, 10, 0)[0];
          var inner = _rect([-95.86748, 29.33965], 20, 8, 0)[0].reverse();
          return [outer, inner];
        })()},
        properties:{height:1.2, color:'#3A4A5A'}
      });
      // LACT/EFM pad
      _addPad([-95.86742, 29.33948], 18, 5, 0.3, '#2A3A4A');
      // Flare pad
      _addPad([-95.86790, 29.33932], 5, 5, 0.2, '#3A2A2A');
      // Solar/Gen pad
      _addPad([-95.86822, 29.33944], 10, 12, 0.2, '#2A3A4A');
      // Comms pad
      _addPad([-95.86739, 29.33991], 12, 6, 0.3, '#2A3A4A');

      // ══════════════════════════════════════════════════════════
      // WELLHEAD AREA — Christmas tree + SSV + Chem Inj
      // ══════════════════════════════════════════════════════════

      // Wellhead christmas tree — T-shaped valve assembly
      // Real: ~1.5m wide valve stack, 4m tall
      var _xmasTree = (function(){
        var pts = [
          [-0.6,-1.8],[0.6,-1.8],[0.6,0.2],
          [1.8,0.2],[1.8,1.2],[0.6,1.2],[0.6,1.8],
          [-0.6,1.8],[-0.6,1.2],[-1.8,1.2],[-1.8,0.2],
          [-0.6,0.2]
        ];
        return _poly([-95.86790, 29.33982], pts);
      })();
      _addBldg('Wellhead', _xmasTree, 6, '#1890FF', true, 'wellhead');

      // Casing head / conductor pipe (circle at wellhead base)
      _3dPadFeatures.push({
        type:'Feature', geometry:{type:'Polygon', coordinates:_circle([-95.86790, 29.33982], 0.6, 16)},
        properties:{height:0.8, color:'#8B8B8B'}
      });

      // Gate Valve — butterfly/gate profile
      var _gateValve = (function(){
        var pts = [[-1.2,-0.4],[-0.4,-0.4],[-0.3,-1.0],[0.3,-1.0],[0.4,-0.4],[1.2,-0.4],
                   [1.2,0.4],[0.4,0.4],[0.3,1.0],[-0.3,1.0],[-0.4,0.4],[-1.2,0.4]];
        return _poly([-95.86798, 29.33985], pts);
      })();
      _addBldg('Gate Valve', _gateValve, 3.5, '#5BA3FF', false, 'valve');

      // Chemical Injection — small cylinder (day tank) + pump box
      _addBldg('Chemical Injection', _circle([-95.86782, 29.33989], 1.2, 16),
        3, '#5BA3FF', false, 'chem');
      // Pump box next to chem tank
      _3dPadFeatures.push({
        type:'Feature', geometry:{type:'Polygon', coordinates:_rect([-95.86782, 29.33986], 1.5, 1, 0)},
        properties:{height:1.2, color:'#5BA3FF'}
      });

      // ══════════════════════════════════════════════════════════
      // PROCESSING AREA — Separator + Compressor
      // ══════════════════════════════════════════════════════════

      // Separator — horizontal vessel (capsule shape)
      // Real: 36" diameter × 10' long = ~0.9m × 3m
      _addBldg('Separator', _capsule([-95.86790, 29.33965], 5, 2.2, 0),
        3.5, '#1890FF', true, 'separator');
      // Separator legs/supports
      _3dPadFeatures.push({
        type:'Feature', geometry:{type:'Polygon', coordinates:_rect([-95.86790, 29.33965], 5.5, 0.6, 0)},
        properties:{height:1.5, color:'#4A5568'}
      });

      // Compressor — rectangular skid with engine housing
      // Real: Ariel JGJ/2 on skid ~4m × 2.5m × 2.5m
      _addBldg('Compressor', _rect([-95.86815, 29.33968], 5, 3.5, 0),
        4.5, '#1890FF', true, 'compressor');
      // Compressor exhaust stack (small cylinder on top)
      _3dFeatures.push({
        type:'Feature', geometry:{type:'Polygon', coordinates:_circle([-95.86817, 29.33970], 0.4, 8)},
        properties:{name:'Compressor', height:6.5, color:'#6B7280', scada:false, btype:'detail', desc:'Exhaust stack'}
      });
      // Compressor cooler (fin-fan rectangle beside main unit)
      _3dPadFeatures.push({
        type:'Feature', geometry:{type:'Polygon', coordinates:_rect([-95.86815, 29.33964], 4, 1.2, 0)},
        properties:{height:2.5, color:'#4A5568'}
      });

      // ══════════════════════════════════════════════════════════
      // TANK FARM (bermed area, east side)
      // ══════════════════════════════════════════════════════════

      // Stock Tank #1 — 210 BBL upright cylinder
      // Real: ~3m diameter × 4.8m tall (16 ft)
      _addBldg('Tank Battery', _circle([-95.86755, 29.33967], 3.2, 24),
        8, '#1890FF', true, 'tank');

      // Stock Tank #2 — second 210 BBL (side by side)
      _3dFeatures.push({
        type:'Feature', geometry:{type:'Polygon', coordinates:_circle([-95.86755, 29.33960], 3.2, 24)},
        properties:{name:'Tank Battery', height:8, color:'#1890FF', scada:true, btype:'tank',
          desc:'2\u00d7 210 BBL Upright Steel \u00b7 Welded \u00b7 Thief Hatch + PRV'}
      });
      _3dGlowFeatures.push({
        type:'Feature', geometry:{type:'Polygon', coordinates:_circle([-95.86755, 29.33960], 3.2, 24)},
        properties:{name:'Tank Battery', height:4.4, color:'#1890FF', btype:'tank'}
      });

      // Produced Water Tank — 500 BBL (larger cylinder)
      // Real: ~3.5m diameter × 5.5m tall
      _addBldg('Produced Water Tank', _circle([-95.86742, 29.33965], 3.5, 24),
        9, '#1890FF', true, 'tank');

      // Tank walkway/catwalk (thin elevated rectangle between tanks)
      _3dPadFeatures.push({
        type:'Feature', geometry:{type:'Polygon', coordinates:_rect([-95.86748, 29.33965], 0.8, 16, 0)},
        properties:{height:7, color:'#4A5568'}
      });

      // ══════════════════════════════════════════════════════════
      // CUSTODY TRANSFER / METERING (SE)
      // ══════════════════════════════════════════════════════════

      // LACT Unit — long skid with meter, pump, prover
      // Real: ~8m × 2m skid
      _addBldg('LACT Unit', _rect([-95.86748, 29.33948], 8, 2.2, 0),
        3, '#1890FF', true, 'lact');

      // EFM Skid — smaller measurement cabinet
      // Real: ~2m × 1.5m × 1.8m
      _addBldg('EFM Skid', _rect([-95.86735, 29.33948], 2.5, 2, 0),
        2.5, '#1890FF', true, 'efm');

      // ══════════════════════════════════════════════════════════
      // FLARE SYSTEM (south edge, 30m separation)
      // ══════════════════════════════════════════════════════════

      // Flare Stack — narrow pipe column
      // Real: 30 ft = ~9m tall, 0.3m diameter pipe
      _addBldg('Flare Stack', _circle([-95.86790, 29.33932], 0.6, 12),
        14, '#FF6B35', false, 'flare');
      // Flare KO drum (horizontal vessel at base)
      _3dPadFeatures.push({
        type:'Feature', geometry:{type:'Polygon', coordinates:_capsule([-95.86793, 29.33932], 3, 1.2, 90)},
        properties:{height:2, color:'#8B5E3C'}
      });
      // Pilot igniter housing
      _3dPadFeatures.push({
        type:'Feature', geometry:{type:'Polygon', coordinates:_rect([-95.86787, 29.33932], 1, 1, 0)},
        properties:{height:1.5, color:'#6B7280'}
      });

      // ══════════════════════════════════════════════════════════
      // COMMUNICATIONS (NE corner)
      // ══════════════════════════════════════════════════════════

      // Radio Tower — Rohn 25G triangular lattice
      // Real: 60 ft = ~18m tall, ~0.5m face width
      var _towerBase = (function(){
        var b = 1.5;
        return _poly([-95.86735, 29.33992], [[0,b],[-b*0.866,-b*0.5],[b*0.866,-b*0.5]]);
      })();
      _addBldg('Radio Tower', _towerBase, 20, '#06B6D4', true, 'comms');

      // RTU Cabinet — NEMA 4X enclosure (octagonal)
      // Real: ~1m × 0.6m × 1.8m
      _addBldg('RTU Cabinet', _circle([-95.86743, 29.33990], 1.2, 8),
        3, '#06B6D4', true, 'comms');

      // Antenna mast detail (tiny circle on top of tower)
      _3dFeatures.push({
        type:'Feature', geometry:{type:'Polygon', coordinates:_circle([-95.86735, 29.33992], 0.25, 8)},
        properties:{name:'Radio Tower', height:22, color:'#EF4444', scada:false, btype:'detail', desc:'Aviation warning light'}
      });

      // ══════════════════════════════════════════════════════════
      // POWER SYSTEM (SW corner)
      // ══════════════════════════════════════════════════════════

      // Solar Array — 4 individual panels, tilted south
      // Real: each panel ~2m × 1m, mounted on rack
      var _solarCtr = [-95.86822, 29.33940];
      for (var sp = 0; sp < 4; sp++) {
        var sx = -3.5 + sp * 2.3;
        _3dFeatures.push({
          type:'Feature',
          geometry:{type:'Polygon', coordinates:_rect([_solarCtr[0] + sx*_lngS, _solarCtr[1]], 1.8, 3.5, -10)},
          properties:{name:'Solar Array', height:2.8, color:'#4F46E5', scada:false, btype:'solar',
            desc:'4\u00d7 Canadian Solar 400W \u00b7 Bifacial \u00b7 1.6 kW \u00b7 30\u00b0 tilt south'}
        });
      }
      // Solar rack/mounting structure
      _3dPadFeatures.push({
        type:'Feature', geometry:{type:'Polygon', coordinates:_rect(_solarCtr, 10, 0.4, 0)},
        properties:{height:1.8, color:'#4A5568'}
      });

      // Generator — rectangular housing with exhaust
      // Real: Generac 8kW ~1.5m × 0.8m × 1m
      _addBldg('Generator', _rect([-95.86822, 29.33948], 2.5, 2, 0),
        2.8, '#4F46E5', false, 'gen');
      // Generator exhaust pipe
      _3dPadFeatures.push({
        type:'Feature', geometry:{type:'Polygon', coordinates:_circle([-95.86823, 29.33950], 0.2, 8)},
        properties:{height:3.8, color:'#6B7280'}
      });

      // Battery bank cabinet (between solar and generator)
      _3dPadFeatures.push({
        type:'Feature', geometry:{type:'Polygon', coordinates:_rect([-95.86822, 29.33944], 2, 1, 0)},
        properties:{height:1.5, color:'#374151'}
      });

      // ══════════════════════════════════════════════════════════
      // SITE INFRASTRUCTURE
      // ══════════════════════════════════════════════════════════

      // Pipe rack (elevated pipe run from separator to tank farm)
      _3dPadFeatures.push({
        type:'Feature', geometry:{type:'Polygon', coordinates:_rect([-95.86772, 29.33965], 30, 0.6, 0)},
        properties:{height:3, color:'#4A5568'}
      });
      // Pipe rack supports (every 8m)
      for (var pr = 0; pr < 4; pr++) {
        _3dPadFeatures.push({
          type:'Feature',
          geometry:{type:'Polygon', coordinates:_rect([-95.86790 + (pr*8)*_lngS, 29.33965], 0.3, 1.2, 0)},
          properties:{height:2.8, color:'#374151'}
        });
      }

      // ── 3D SOURCES + LAYERS ──

      // Infrastructure pads/berms (lowest layer)
      map.addSource('well-3d-pads', {
        type: 'geojson',
        data: { type: 'FeatureCollection', features: _3dPadFeatures }
      });
      map.addLayer({
        id: 'well-3d-pads',
        type: 'fill-extrusion',
        source: 'well-3d-pads',
        minzoom: 14,
        paint: {
          'fill-extrusion-color': ['get', 'color'],
          'fill-extrusion-height': ['get', 'height'],
          'fill-extrusion-base': 0,
          'fill-extrusion-opacity': 0.6
        }
      });

      // Main equipment buildings
      map.addSource('well-3d-buildings', {
        type: 'geojson',
        data: { type: 'FeatureCollection', features: _3dFeatures }
      });
      map.addLayer({
        id: 'well-3d-extrusion',
        type: 'fill-extrusion',
        source: 'well-3d-buildings',
        minzoom: 14,
        paint: {
          'fill-extrusion-color': ['get', 'color'],
          'fill-extrusion-height': ['get', 'height'],
          'fill-extrusion-base': 0,
          'fill-extrusion-opacity': 0.55
        }
      });

      // SCADA glow (inner)
      map.addSource('well-3d-glow', {
        type: 'geojson',
        data: { type: 'FeatureCollection', features: _3dGlowFeatures }
      });
      map.addLayer({
        id: 'well-3d-glow',
        type: 'fill-extrusion',
        source: 'well-3d-glow',
        minzoom: 14,
        paint: {
          'fill-extrusion-color': ['get', 'color'],
          'fill-extrusion-height': ['get', 'height'],
          'fill-extrusion-base': 0.1,
          'fill-extrusion-opacity': 0.35
        }
      });

      // ══════════════════════════════════════════════════════════════
      // ── TANK LEVEL VISUALIZATION ──
      // Transparent tank shells with colored liquid fill inside
      // Glowing edges on tank rims
      // ══════════════════════════════════════════════════════════════

      // Tank level fills (inner cylinders at partial height representing liquid)
      var _tankLevels = [
        { ctr:[-95.86755, 29.33967], r:2.8, level:0.72, name:'Stock Tank #1', color:'#10D478', fluid:'oil' },
        { ctr:[-95.86755, 29.33960], r:2.8, level:0.65, name:'Stock Tank #2', color:'#10D478', fluid:'oil' },
        { ctr:[-95.86742, 29.33965], r:3.1, level:0.45, name:'Produced Water', color:'#3B82F6', fluid:'water' }
      ];

      var _tankFillFeatures = [];
      var _tankRimFeatures = [];
      var _tankSurfaceFeatures = [];

      _tankLevels.forEach(function(t) {
        var maxH = t.name.indexOf('Water') >= 0 ? 9 : 8;
        var fillH = maxH * t.level;

        // Liquid fill (solid color, lower opacity)
        _tankFillFeatures.push({
          type:'Feature',
          geometry:{type:'Polygon', coordinates:_circle(t.ctr, t.r, 24)},
          properties:{name:t.name, height:fillH, color:t.color, level:t.level}
        });

        // Liquid surface (thin disc at top of liquid)
        _tankSurfaceFeatures.push({
          type:'Feature',
          geometry:{type:'Polygon', coordinates:_circle(t.ctr, t.r - 0.2, 24)},
          properties:{name:t.name, height:fillH + 0.15, base:fillH - 0.15, color:t.color}
        });

        // Glowing rim at tank top (ring shape)
        var outerRim = _circle(t.ctr, t.r + 0.3, 24)[0];
        var innerRim = _circle(t.ctr, t.r - 0.1, 24)[0].reverse();
        _tankRimFeatures.push({
          type:'Feature',
          geometry:{type:'Polygon', coordinates:[outerRim, innerRim]},
          properties:{name:t.name, height:maxH + 0.3, color:t.color}
        });
      });

      // Tank liquid fill layer
      map.addSource('tank-fills', {
        type:'geojson', data:{type:'FeatureCollection', features:_tankFillFeatures}
      });
      map.addLayer({
        id:'tank-liquid-fill', type:'fill-extrusion', source:'tank-fills', minzoom:14,
        paint:{
          'fill-extrusion-color':['get','color'],
          'fill-extrusion-height':['get','height'],
          'fill-extrusion-base':0.2,
          'fill-extrusion-opacity':0.4
        }
      });

      // Liquid surface (bright disc floating at liquid level)
      map.addSource('tank-surface', {
        type:'geojson', data:{type:'FeatureCollection', features:_tankSurfaceFeatures}
      });
      map.addLayer({
        id:'tank-liquid-surface', type:'fill-extrusion', source:'tank-surface', minzoom:14,
        paint:{
          'fill-extrusion-color':['get','color'],
          'fill-extrusion-height':['get','height'],
          'fill-extrusion-base':['get','base'],
          'fill-extrusion-opacity':0.65
        }
      });

      // Glowing tank rims
      map.addSource('tank-rims', {
        type:'geojson', data:{type:'FeatureCollection', features:_tankRimFeatures}
      });
      map.addLayer({
        id:'tank-rim-glow', type:'fill-extrusion', source:'tank-rims', minzoom:14,
        paint:{
          'fill-extrusion-color':['get','color'],
          'fill-extrusion-height':['get','height'],
          'fill-extrusion-base':['get','height'],
          'fill-extrusion-opacity':0.8
        }
      });

      // Animate tank surface shimmer (subtle opacity pulse)
      var _tankShimmer = 0;
      (function _shimmerTanks() {
        _tankShimmer += 0.03;
        var op = 0.55 + 0.1 * Math.sin(_tankShimmer);
        try { map.setPaintProperty('tank-liquid-surface', 'fill-extrusion-opacity', op); } catch(e) {}
        requestAnimationFrame(_shimmerTanks);
      })();

      // Tank level labels (floating above each tank)
      map.addSource('tank-level-labels', {
        type:'geojson',
        data:{type:'FeatureCollection', features:_tankLevels.map(function(t){
          return {type:'Feature', geometry:{type:'Point', coordinates:t.ctr},
            properties:{label:Math.round(t.level*100)+'%', color:t.color}};
        })}
      });
      map.addLayer({
        id:'tank-level-text', type:'symbol', source:'tank-level-labels', minzoom:16,
        layout:{
          'text-field':['get','label'], 'text-size':12,
          'text-font':['Open Sans Bold'], 'text-offset':[0, -0.5],
          'text-allow-overlap':true
        },
        paint:{
          'text-color':['get','color'],
          'text-halo-color':'#0B1120', 'text-halo-width':1.5
        }
      });

      // ── ALARM PULSE RING ──
      // Simulated: Compressor vibration alarm
      var _compAlarmPoly = _rect([-95.86815, 29.33968], 5.5, 4, 0);
      map.addSource('well-3d-alarm', {
        type: 'geojson',
        data: { type: 'FeatureCollection', features: [{
          type: 'Feature',
          geometry: { type: 'Polygon', coordinates: _compAlarmPoly },
          properties: { name: 'Compressor', height: 5 }
        }] }
      });
      map.addLayer({
        id: 'well-3d-alarm-ring',
        type: 'fill-extrusion',
        source: 'well-3d-alarm',
        minzoom: 14,
        paint: {
          'fill-extrusion-color': '#EF4444',
          'fill-extrusion-height': ['get', 'height'],
          'fill-extrusion-base': ['get', 'height'],
          'fill-extrusion-opacity': 0.7
        }
      });
      var _alarmOn = true;
      setInterval(function(){
        _alarmOn = !_alarmOn;
        try{map.setPaintProperty('well-3d-alarm-ring','fill-extrusion-opacity',_alarmOn?0.7:0.12);}catch(e){}
      }, 800);

      // ── 3D CLICK HANDLER ──
      map.on('click', 'well-3d-extrusion', function(e) {
        if (_markerClickGuard) return;
        if (!e.features || !e.features.length) return;
        var f = e.features[0].properties;
        if (f.btype === 'detail') return; // Skip small details
        var isComms = f.btype === 'comms';
        var html = '<div style="font-family:Inter,sans-serif;padding:10px;min-width:220px;max-width:300px;background:#0B1120;border:1px solid #1E90FF44;border-radius:8px;">' +
          '<div style="display:flex;align-items:center;gap:8px;">' +
            '<div style="font-size:14px;font-weight:700;color:#E2E8F0;">' + f.name + '</div>' +
            (f.scada ? '<div style="font-size:8px;padding:2px 6px;background:#1E90FF22;border:1px solid #1E90FF44;border-radius:3px;color:#1E90FF;font-weight:600;">SCADA</div>' : '') +
          '</div>' +
          '<div style="font-size:10px;color:#94A3B8;margin-top:4px;line-height:1.4;">' + (f.desc||'') + '</div>';
        if (isComms) {
          html += '<div style="margin-top:10px;display:grid;grid-template-columns:1fr 1fr;gap:6px;">' +
            '<div style="background:#06B6D411;border:1px solid #06B6D433;border-radius:4px;padding:5px 7px;">' +
              '<div style="font-size:7px;color:#06B6D4;text-transform:uppercase;letter-spacing:0.5px;">RSSI</div>' +
              '<div style="font-size:16px;font-weight:700;color:#10D478;margin-top:2px;">-62 <span style="font-size:9px;font-weight:400;color:#94A3B8;">dBm</span></div></div>' +
            '<div style="background:#06B6D411;border:1px solid #06B6D433;border-radius:4px;padding:5px 7px;">' +
              '<div style="font-size:7px;color:#06B6D4;text-transform:uppercase;letter-spacing:0.5px;">SNR</div>' +
              '<div style="font-size:16px;font-weight:700;color:#10D478;margin-top:2px;">24.3 <span style="font-size:9px;font-weight:400;color:#94A3B8;">dB</span></div></div>' +
            '<div style="background:#06B6D411;border:1px solid #06B6D433;border-radius:4px;padding:5px 7px;">' +
              '<div style="font-size:7px;color:#06B6D4;text-transform:uppercase;letter-spacing:0.5px;">LINK QUALITY</div>' +
              '<div style="font-size:16px;font-weight:700;color:#10D478;margin-top:2px;">99.7<span style="font-size:9px;font-weight:400;color:#94A3B8;">%</span></div></div>' +
            '<div style="background:#06B6D411;border:1px solid #06B6D433;border-radius:4px;padding:5px 7px;">' +
              '<div style="font-size:7px;color:#06B6D4;text-transform:uppercase;letter-spacing:0.5px;">LATENCY</div>' +
              '<div style="font-size:16px;font-weight:700;color:#F59E0B;margin-top:2px;">45 <span style="font-size:9px;font-weight:400;color:#94A3B8;">ms</span></div></div></div>';
        }
        if (f.btype === 'tank') {
          html += '<div style="margin-top:10px;display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px;">' +
            '<div style="background:#1E90FF11;border:1px solid #1E90FF33;border-radius:4px;padding:5px 7px;">' +
              '<div style="font-size:7px;color:#1E90FF;text-transform:uppercase;">Level</div>' +
              '<div style="font-size:16px;font-weight:700;color:#10D478;margin-top:2px;">72<span style="font-size:9px;color:#94A3B8;">%</span></div></div>' +
            '<div style="background:#1E90FF11;border:1px solid #1E90FF33;border-radius:4px;padding:5px 7px;">' +
              '<div style="font-size:7px;color:#1E90FF;text-transform:uppercase;">Temp</div>' +
              '<div style="font-size:16px;font-weight:700;color:#F59E0B;margin-top:2px;">94<span style="font-size:9px;color:#94A3B8;">\u00b0F</span></div></div>' +
            '<div style="background:#1E90FF11;border:1px solid #1E90FF33;border-radius:4px;padding:5px 7px;">' +
              '<div style="font-size:7px;color:#1E90FF;text-transform:uppercase;">BSW</div>' +
              '<div style="font-size:16px;font-weight:700;color:#10D478;margin-top:2px;">1.2<span style="font-size:9px;color:#94A3B8;">%</span></div></div></div>';
        }
        if (f.btype === 'separator' || f.btype === 'compressor') {
          html += '<div style="margin-top:10px;display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px;">' +
            '<div style="background:#1E90FF11;border:1px solid #1E90FF33;border-radius:4px;padding:5px 7px;">' +
              '<div style="font-size:7px;color:#1E90FF;text-transform:uppercase;">Pressure</div>' +
              '<div style="font-size:16px;font-weight:700;color:#10D478;margin-top:2px;">'+(f.btype==='separator'?'82':'145')+'<span style="font-size:9px;color:#94A3B8;"> PSI</span></div></div>' +
            '<div style="background:#1E90FF11;border:1px solid #1E90FF33;border-radius:4px;padding:5px 7px;">' +
              '<div style="font-size:7px;color:#1E90FF;text-transform:uppercase;">Temp</div>' +
              '<div style="font-size:16px;font-weight:700;color:#F59E0B;margin-top:2px;">'+(f.btype==='separator'?'128':'185')+'<span style="font-size:9px;color:#94A3B8;">\u00b0F</span></div></div>' +
            '<div style="background:#1E90FF11;border:1px solid #1E90FF33;border-radius:4px;padding:5px 7px;">' +
              '<div style="font-size:7px;color:#1E90FF;text-transform:uppercase;">Health</div>' +
              '<div style="font-size:16px;font-weight:700;color:'+(f.btype==='compressor'?'#F59E0B':'#10D478')+';margin-top:2px;">'+(f.btype==='compressor'?'76':'94')+'<span style="font-size:9px;color:#94A3B8;">%</span></div></div></div>';
        }
        if (f.btype === 'wellhead') {
          html += '<div style="margin-top:10px;display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px;">' +
            '<div style="background:#1E90FF11;border:1px solid #1E90FF33;border-radius:4px;padding:5px 7px;">' +
              '<div style="font-size:7px;color:#1E90FF;text-transform:uppercase;">Casing PSI</div>' +
              '<div style="font-size:16px;font-weight:700;color:#10D478;margin-top:2px;">340</div></div>' +
            '<div style="background:#1E90FF11;border:1px solid #1E90FF33;border-radius:4px;padding:5px 7px;">' +
              '<div style="font-size:7px;color:#1E90FF;text-transform:uppercase;">Tubing PSI</div>' +
              '<div style="font-size:16px;font-weight:700;color:#10D478;margin-top:2px;">180</div></div>' +
            '<div style="background:#1E90FF11;border:1px solid #1E90FF33;border-radius:4px;padding:5px 7px;">' +
              '<div style="font-size:7px;color:#1E90FF;text-transform:uppercase;">Production</div>' +
              '<div style="font-size:16px;font-weight:700;color:#10D478;margin-top:2px;">24<span style="font-size:9px;color:#94A3B8;"> BOPD</span></div></div></div>';
        }
        html += '</div>';
        _showPopup(new maplibregl.Popup({closeButton:true, maxWidth:'320px', className:'dark-popup'})
          .setLngLat(e.lngLat).setHTML(html).addTo(map));
      });
      map.on('click', function(e) {
            if(!_markerClickGuard && typeof window._closeMapAssetPanel==='function') window._closeMapAssetPanel();

        if (_markerClickGuard) return;
        // Close all popups when clicking empty map
        var features = map.queryRenderedFeatures(e.point);
        var hit = features.some(function(f) { return f.layer && (f.layer.id.indexOf('well-3d')>=0 || f.layer.id.indexOf('valve')>=0); });
        if (!hit) _closeAllPopups();
      });
      map.on('mouseenter','well-3d-extrusion',function(){map.getCanvas().style.cursor='pointer';});
      map.on('mouseleave','well-3d-extrusion',function(){map.getCanvas().style.cursor='';});

      // ── GLOW LEGEND ──
      (function(){
        var lg = document.createElement('div');
        lg.id = 'map-3d-legend';
        lg.style.cssText = 'position:absolute;bottom:80px;right:12px;background:#0B1120DD;border:1px solid #1E90FF33;border-radius:6px;padding:8px 12px;font-family:Inter,sans-serif;z-index:5;pointer-events:none;';
        lg.innerHTML = '<div style="font-size:8px;color:#94A3B8;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px;">Map Legend</div>' +
          '<div style="display:flex;align-items:center;gap:6px;margin-bottom:4px;"><div style="width:10px;height:10px;border-radius:2px;background:#1890FF;opacity:0.55;box-shadow:0 0 6px #1890FF88;"></div><span style="font-size:9px;color:#E2E8F0;">SCADA Connected</span></div>' +
          '<div style="display:flex;align-items:center;gap:6px;margin-bottom:4px;"><div style="width:10px;height:10px;border-radius:2px;background:#5BA3FF;opacity:0.55;"></div><span style="font-size:9px;color:#E2E8F0;">Passive Equipment</span></div>' +
          '<div style="display:flex;align-items:center;gap:6px;margin-bottom:4px;"><div style="width:10px;height:10px;border-radius:2px;background:#4A5568;opacity:0.7;"></div><span style="font-size:9px;color:#E2E8F0;">Infrastructure</span></div>' +
          '<div style="display:flex;align-items:center;gap:6px;margin-bottom:4px;"><div style="width:10px;height:10px;border-radius:50%;background:#10D47855;border:1.5px solid #10D478;"></div><span style="font-size:9px;color:#E2E8F0;">Tank Level</span></div>' +
          '<div style="display:flex;align-items:center;gap:6px;"><div style="width:10px;height:10px;border-radius:2px;background:#EF4444;"></div><span style="font-size:9px;color:#E2E8F0;">Active Alarm</span></div>';
        var s = document.createElement('style');
        s.textContent = '@keyframes alarmBlink{0%,100%{opacity:0.8}50%{opacity:0.15}}';
        document.head.appendChild(s);
        map.getContainer().appendChild(lg);
      })();

      // ── 3D LAYER TOGGLE ──
      window._toggle3dBuildings = function(show) {
        var v = show ? 'visible' : 'none';
        ['well-3d-pads','well-3d-extrusion','well-3d-glow','well-3d-alarm-ring',
         'tank-liquid-fill','tank-liquid-surface','tank-rim-glow','tank-level-text'
        ].forEach(function(id) {
          try { map.setLayoutProperty(id, 'visibility', v); } catch(e) {}
        });
        var lg = document.getElementById('map-3d-legend');
        if (lg) lg.style.display = show ? 'block' : 'none';
      };

      // ── LOCAL LANDMARKS ──
      // Access road from FM 762
      map.addSource('access-road', {
        type: 'geojson',
        data: {
          type: 'Feature',
          geometry: {
            type: 'LineString',
            coordinates: [
              [-95.8750, 29.3380], [-95.8730, 29.3385], [-95.8710, 29.3388],
              [-95.8695, 29.3392], [-95.8685, 29.3394], [-95.86855, 29.33955]
            ]
          },
          properties: { name: 'Pleasant Rd (Lease Road)' }
        }
      });
      map.addLayer({
        id: 'access-road-line', type: 'line', source: 'access-road',
        paint: { 'line-color': '#6B728066', 'line-width': 2, 'line-dasharray': [6, 4] }
      });
      map.addSource('road-label', {
        type: 'geojson',
        data: { type: 'Feature', geometry: { type: 'Point', coordinates: [-95.8720, 29.3386] }, properties: { name: 'Pleasant Rd' } }
      });
      map.addLayer({
        id: 'road-label-text', type: 'symbol', source: 'road-label',
        layout: { 'text-field': 'Pleasant Rd', 'text-size': 10, 'text-font': ['Open Sans Regular'] },
        paint: { 'text-color': '#6B7280', 'text-halo-color': '#0B1020', 'text-halo-width': 1.5 }
      });

      // FM 762 reference
      map.addSource('fm762', {
        type: 'geojson',
        data: { type: 'Feature', geometry: { type: 'Point', coordinates: [-95.8760, 29.3375] }, properties: { name: 'FM 762' } }
      });
      map.addLayer({
        id: 'fm762-label', type: 'symbol', source: 'fm762',
        layout: { 'text-field': '← FM 762', 'text-size': 11, 'text-font': ['Open Sans Bold'], 'text-anchor': 'right' },
        paint: { 'text-color': '#FBBF24', 'text-halo-color': '#0B1020', 'text-halo-width': 2 }
      });

      // Gathering pipeline to Enterprise midstream
      map.addSource('gathering-line', {
        type: 'geojson',
        data: {
          type: 'Feature',
          geometry: {
            type: 'LineString',
            coordinates: [
              [-95.86742, 29.33943], [-95.8670, 29.3396],
              [-95.8660, 29.3398], [-95.8640, 29.3402]
            ]
          },
          properties: { name: 'Enterprise Gathering' }
        }
      });
      map.addLayer({
        id: 'gathering-line-draw', type: 'line', source: 'gathering-line',
        paint: { 'line-color': '#F59E0B55', 'line-width': 3, 'line-dasharray': [2, 2] }
      });
      map.addSource('gathering-label', {
        type: 'geojson',
        data: { type: 'Feature', geometry: { type: 'Point', coordinates: [padCenter[0]+0.005, padCenter[1]+0.0025] }, properties: {} }
      });
      map.addLayer({
        id: 'gathering-label-text', type: 'symbol', source: 'gathering-label',
        layout: { 'text-field': 'Enterprise Gathering →', 'text-size': 9, 'text-font': ['Open Sans Regular'], 'text-anchor': 'left' },
        paint: { 'text-color': '#F59E0B88', 'text-halo-color': '#0B1020', 'text-halo-width': 1.5 }
      });

      // Brazos River reference
      map.addSource('brazos', {
        type: 'geojson',
        data: {
          type: 'Feature',
          geometry: {
            type: 'LineString',
            coordinates: [
              [-95.880, 29.345], [-95.875, 29.343], [-95.870, 29.342],
              [-95.865, 29.341], [-95.860, 29.342], [-95.855, 29.343]
            ]
          },
          properties: { name: 'Brazos River' }
        }
      });
      map.addLayer({
        id: 'brazos-line', type: 'line', source: 'brazos',
        paint: { 'line-color': '#3B82F633', 'line-width': 6 }
      });
      map.addSource('brazos-label', {
        type: 'geojson',
        data: { type: 'Feature', geometry: { type: 'Point', coordinates: [-95.867, 29.3415] }, properties: {} }
      });
      map.addLayer({
        id: 'brazos-label-text', type: 'symbol', source: 'brazos-label',
        layout: { 'text-field': 'Brazos River', 'text-size': 10, 'text-font': ['Open Sans Regular'] },
        paint: { 'text-color': '#3B82F666', 'text-halo-color': '#0B1020', 'text-halo-width': 1.5 }
      });

      console.log('[Aevus] Well pad equipment overlay + landmarks loaded');
    });

    // ── Zoom-responsive marker scaling ──
    function _updateMarkerScale() {
      var z = map.getZoom();
      // Scale: 0.55 at zoom 10, 1.0 at zoom 15, 1.15 at zoom 18+
      var scale = Math.max(0.5, Math.min(1.15, 0.1 + z * 0.06));
      var showLabels = z >= 13;
      var sz = Math.round(48 * scale);
      markerList.forEach(function(mk) {
        var el = mk.getElement();
        if (!el) return;
        // Resize the marker element itself
        el.style.width = Math.round(60 * scale) + 'px';
        el.style.height = Math.round(80 * scale) + 'px';
        // Scale the SVG inside
        var hIcon = el.querySelector('.holo-icon');
        if (hIcon) {
          var iconSz = Math.round(44 * scale);
          hIcon.style.width = iconSz + 'px';
          hIcon.style.height = iconSz + 'px';
        }
        var svg = el.querySelector('svg');
        if (svg) {
          var svgSz = Math.round(24 * scale);
          svg.setAttribute('width', svgSz);
          svg.setAttribute('height', svgSz);
        }
        var hBeam = el.querySelector('.holo-beam');
        if (hBeam) hBeam.style.height = Math.round(18 * scale) + 'px';
        var hShadow = el.querySelector('.holo-shadow');
        if (hShadow) {
          hShadow.style.width = Math.round(28 * scale) + 'px';
          hShadow.style.height = Math.round(8 * scale) + 'px';
        }
        // Show/hide device label based on zoom
        var lbl = el.querySelector('[data-map-label]');
        if (lbl) lbl.style.display = showLabels ? '' : 'none';
        // Scale badges
        var hBadge = el.querySelector('[data-health-badge]');
        if (hBadge) {
          hBadge.style.fontSize = Math.round(9 * scale) + 'px';
          hBadge.style.display = scale < 0.65 ? 'none' : 'flex';
        }
      });
    }
    map.on('zoom', _updateMarkerScale);
    map.on('load', function() { setTimeout(_updateMarkerScale, 200); });
    setTimeout(_updateMarkerScale, 500);

    // UI overlays
    var lp = document.createElement('div'); lp.className = 'map-layer-toggle';
    lp.innerHTML = '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">' +
                    '<div class="map-layer-title" style="margin:0;">LAYERS</div>' +
                    '<button id="map-panel-collapse" onclick="var p=this.closest(\'.map-layers-panel\');if(p.classList.contains(\'.collapsed\')){p.classList.remove(\'collapsed\');p.style.width=\'\';this.innerHTML=\'&#x276E;\'}else{p.classList.add(\'collapsed\');p.style.width=\'40px\';p.style.overflow=\'hidden\';this.innerHTML=\'&#x276F;\'}" style="background:none;border:1px solid rgba(148,163,184,0.15);color:var(--text-muted);border-radius:6px;width:24px;height:24px;display:flex;align-items:center;justify-content:center;cursor:pointer;font-size:10px;transition:all 0.2s;" title="Collapse panel">&#x276E;</button>' +
                    '</div>' +
      '<div class="map-layer-group" style="margin-bottom:6px;padding-bottom:6px;border-bottom:1px solid rgba(148,163,184,0.08);">' +
        '<label><input type="checkbox" id="lyr-weather" checked> Weather</label>' +
        '<label><input type="checkbox" id="lyr-assets" checked> Assets</label>' +
        '<label><input type="checkbox" id="lyr-3d" checked onchange="if(window._toggle3dBuildings)window._toggle3dBuildings(this.checked)"> 3D Buildings</label>' +
              '<label><input type="checkbox" id="lyr-rf"' + (window._userRole === 'rf' || window._userRole === 'technician' ? ' checked' : '') + ' onchange="if(window._toggleRfCoverage)window._toggleRfCoverage(this.checked)"> RF Signals</label>' +
        '<label><input type="checkbox" id="lyr-pipe"> Pipelines</label>' +
        '<label><input type="checkbox" id="lyr-zones" onchange="if(window._toggleLayerGroup)window._toggleLayerGroup(&apos;security-zone&apos;,this.checked)"> Security Zones</label>' +
        '<label><input type="checkbox" id="lyr-hazards" onchange="if(window._toggleLayerGroup)window._toggleLayerGroup(&apos;env-hazard&apos;,this.checked)"> Env Hazards</label>' +
      '</div>' +
      '<div class="map-layer-group-title" style="font-size:8px;font-weight:700;color:rgba(148,163,184,0.5);letter-spacing:0.8px;margin:4px 0 2px;cursor:pointer;user-select:none;display:flex;align-items:center;gap:4px;" onclick="var n=this.nextElementSibling;while(n&&!n.classList.contains(\'map-layer-group-title\')){if(n.style){n.style.display=n.style.display===\'none\'?\'\':\'none\';}n=n.nextElementSibling;}this.querySelector(\'span\').textContent=this.querySelector(\'span\').textContent===\'▸\'?\'▾\':\'▸\'"><span style="font-size:7px;">▾</span> SCADA LAYERS</div>' +
      '<div class="map-layer-group" style="margin-bottom:6px;padding-bottom:6px;border-bottom:1px solid rgba(148,163,184,0.08);">' +
        '<label><input type="checkbox" id="lyr-alarms" onchange="if(window._toggleLayerGroup)window._toggleLayerGroup(&apos;alarm-heat&apos;,this.checked)"> Alarm Heat Map</label>' +
        '<label><input type="checkbox" id="lyr-health" onchange="if(window._toggleLayerGroup)window._toggleLayerGroup(&apos;health-gradient&apos;,this.checked)"> Health Gradient</label>' +
        '<label><input type="checkbox" id="lyr-rfcov" onchange="if(window._toggleRfCoverage)window._toggleRfCoverage(this.checked)"> RF Coverage</label>' +
        '<label><input type="checkbox" id="lyr-wind" onchange="if(window._toggleLayerGroup)window._toggleLayerGroup(&apos;wind-overlay&apos;,this.checked)"> Wind Overlay</label>' +
      '</div>' +
      '<div class="map-layer-group-title" style="font-size:8px;font-weight:700;color:rgba(148,163,184,0.5);letter-spacing:0.8px;margin:4px 0 2px;cursor:pointer;user-select:none;display:flex;align-items:center;gap:4px;" onclick="var n=this.nextElementSibling;while(n&&!n.classList.contains(\'map-layer-group-title\')){if(n.style){n.style.display=n.style.display===\'none\'?\'\':\'none\';}n=n.nextElementSibling;}this.querySelector(\'span\').textContent=this.querySelector(\'span\').textContent===\'▸\'?\'▾\':\'▸\'"><span style="font-size:7px;">▾</span> INTELLIGENCE</div>' +
      '<div class="map-layer-group">' +
        '<label><input type="checkbox" id="lyr-tracker" onchange="if(window._toggleLayerGroup)window._toggleLayerGroup(&apos;tracker&apos;,this.checked)"> Asset Tracker</label>' +
        '<label><input type="checkbox" id="lyr-geofence" onchange="if(window._toggleLayerGroup)window._toggleLayerGroup(&apos;geofence&apos;,this.checked)"> Geofences</label>' +
        '<label><input type="checkbox" id="lyr-visits" onchange="if(window._toggleLayerGroup)window._toggleLayerGroup(&apos;visit-log&apos;,this.checked)"> Visit Log</label>' +
        '<label><input type="checkbox" id="lyr-dispatch" onchange="if(window._toggleLayerGroup)window._toggleLayerGroup(&apos;dispatch&apos;,this.checked)"> Dispatch Route</label>' +
        '<label><input type="checkbox" id="lyr-anomaly" onchange="if(window._toggleLayerGroup)window._toggleLayerGroup(&apos;anomaly&apos;,this.checked)"> Anomaly Map</label>' +
      '</div>' +
      '<div class="map-layer-group-title" style="font-size:8px;font-weight:700;color:rgba(148,163,184,0.5);letter-spacing:0.8px;margin:8px 0 4px;"><span style="font-size:7px;">▾</span> MAP STYLE</div>' +
      '<div class="map-style-switcher">' +
        '<div style="display:flex;gap:2px;background:rgba(15,23,42,0.6);border-radius:8px;padding:2px;border:1px solid rgba(148,163,184,0.08);">' +
                    '<button class="map-style-btn active" data-style="dark" title="Control Room (Dark)" style="transition:all 0.25s ease;">Monitor</button>' +
                    '<button class="map-style-btn" data-style="satellite" title="Satellite Imagery" style="transition:all 0.25s ease;">Satellite</button>' +
                    '<button class="map-style-btn" data-style="hybrid" title="Satellite + Labels" style="transition:all 0.25s ease;">Hybrid</button>' +
                    '</div>' +
        '<button class="map-style-btn" data-style="hybrid" title="Satellite + Labels">Hybrid</button>' +
      '</div>';
    // Pinned cards container
    var pinnedContainer = document.createElement('div');
    pinnedContainer.className = 'map-pinned-container';
    pinnedContainer.id = 'map-pinned-cards';
    mapDiv.appendChild(pinnedContainer);
    window._mapPinnedAssets = {};
    window._pinMapAsset = function(assetId, name, health, status, vitalsHtml, color) {
      if (window._mapPinnedAssets[assetId]) { return; } // already pinned
      window._mapPinnedAssets[assetId] = true;
      var card = document.createElement('div');
      card.className = 'map-pinned-card';
      card.id = 'pin-' + assetId;
      card.setAttribute('data-asset-id', assetId);
      var hPct = Math.min(100, Math.max(0, parseInt(health) || 0));
      var hColor = hPct >= 90 ? '#10D478' : hPct >= 70 ? '#FBBF24' : '#EF4444';
      card.innerHTML =
        '<div class="pin-header">' +
          '<div><div class="pin-name">' + (name || assetId) + '</div><div class="pin-id">' + assetId + ' · ' + (status || '').toUpperCase() + '</div></div>' +
          '<button class="pin-close" onclick="window._unpinMapAsset(&quot;' + assetId + '&quot;)" title="Unpin">&times;</button>' +
        '</div>' +
        '<div class="pin-vitals">' +
          '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">' +
            '<span style="font-size:9px;color:#7B8499;">Health</span>' +
            '<span style="font-size:12px;font-weight:800;color:' + (color||'#06B6D4') + ';font-family:var(--font-mono);">' + health + '%</span>' +
          '</div>' +
          '<div class="pin-health-bar"><div class="pin-health-fill" style="width:' + hPct + '%;background:' + hColor + ';"></div></div>' +
          vitalsHtml +
        '</div>';
      pinnedContainer.appendChild(card);
    };
    window._unpinMapAsset = function(assetId) {
      delete window._mapPinnedAssets[assetId];
      var el = document.getElementById('pin-' + assetId);
      if (el) { el.style.animation = 'none'; el.style.opacity = '0'; el.style.transform = 'translateX(20px)'; setTimeout(function(){ el.remove(); }, 200); }
    };
    window._pinAssetById = function(assetId) {
      if (window._mapPinnedAssets[assetId]) return;
      var assets = window._getLiveAssets ? window._getLiveAssets() : [];
      var a = null;
      for (var i = 0; i < assets.length; i++) { if (assets[i].id === assetId) { a = assets[i]; break; } }
      if (!a) return;
      var h = a.health != null ? a.health : 0;
      var s = (a.status || '').toLowerCase();
      var SC = {good:'#10D478',warn:'#FBBF24',warning:'#FBBF24',bad:'#EF4444',critical:'#EF4444',offline:'#6B7280'};
      var c = SC[s] || '#6B7280';
      var vitals = '';
      if (a.vitals && a.vitals.length) {
        a.vitals.slice(0, 4).forEach(function(v) {
          var vc = v.status === 'good' ? '#10D478' : (v.status === 'warning' || v.status === 'warn') ? '#FBBF24' : '#EF4444';
          var val = v.raw_value != null ? (typeof v.raw_value === 'number' ? v.raw_value.toFixed(1) : v.raw_value) : '—';
          vitals += '<div class="pin-vital-row"><span class="pin-vital-label">' + v.label + '</span><span class="pin-vital-value" style="color:' + vc + ';">' + val + ' ' + (v.unit || '') + '</span></div>';
        });
      }
      window._pinMapAsset(assetId, a.name || assetId, h, s, vitals, c);
      // Close popup after pinning
      var popups = document.querySelectorAll('.maplibregl-popup');
      popups.forEach(function(p) { p.remove(); });
    };

    mapDiv.appendChild(lp);

    var temp=(72+Math.random()*8).toFixed(0),wind=(5+Math.random()*12).toFixed(0);
    var wDir=['N','NE','E','SE','S','SW','W','NW'][Math.floor(Math.random()*8)],hum=(45+Math.random()*30).toFixed(0);
    var wxP=document.createElement('div');wxP.className='map-weather-legend';
    wxP.innerHTML='<div style="font-weight:700;font-size:10px;text-transform:uppercase;letter-spacing:0.5px;color:var(--text-faint);margin-bottom:6px;">Weather</div><div class="wx-row"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#EF4444" stroke-width="1.8"><path d="M12 2v4M12 18v4M2 12h4M18 12h4"/></svg> '+temp+'°F</div><div class="wx-row"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#0EA5E9" stroke-width="1.8"><path d="M5 12h14M13 6l6 6-6 6"/></svg> '+wind+' mph '+wDir+'</div><div class="wx-row"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#60A5FA" stroke-width="1.8"><path d="M12 2C6.48 2 2 6 2 11c0 5 10 11 10 11s10-6 10-11c0-5-4.48-9-10-9z"/></svg> '+hum+'% RH</div><div class="wx-row" style="color:#10D478;margin-top:4px;"><span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:#10D478;margin-right:4px;"></span>No active NWS alerts</div><div style="font-size:9px;color:var(--text-faint);margin-top:4px;">Updated: '+(new Date()).toLocaleTimeString()+'</div>';
    mapDiv.appendChild(wxP);

    var mBtn=document.createElement('div');mBtn.className='map-measure-btn';
    mBtn.innerHTML='<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M2 12h20M2 12l4-4M2 12l4 4M22 12l-4-4M22 12l-4 4"/></svg> Measure';
    mapDiv.appendChild(mBtn);
    var mRes=document.createElement('div');mRes.className='map-measure-result';mapDiv.appendChild(mRes);
    var measuring=false,mPt1=null;
    mBtn.addEventListener('click',function(){measuring=!measuring;mBtn.classList.toggle('active',measuring);if(!measuring){mPt1=null;mRes.style.display='none';}map.getCanvas().style.cursor=measuring?'crosshair':'';});
    map.on('click',function(e){if(!measuring)return;if(!mPt1){mPt1=e.lngLat;mRes.style.display='block';mRes.textContent='Click second point…';}else{var R=3959,dLat=(e.lngLat.lat-mPt1.lat)*Math.PI/180,dLng=(e.lngLat.lng-mPt1.lng)*Math.PI/180;var aa=Math.sin(dLat/2)*Math.sin(dLat/2)+Math.cos(mPt1.lat*Math.PI/180)*Math.cos(e.lngLat.lat*Math.PI/180)*Math.sin(dLng/2)*Math.sin(dLng/2);var d=R*2*Math.atan2(Math.sqrt(aa),Math.sqrt(1-aa));var ft=d*5280;mRes.textContent=ft<1000?ft.toFixed(0)+' ft':d.toFixed(2)+' mi';mPt1=null;setTimeout(function(){measuring=false;mBtn.classList.remove('active');map.getCanvas().style.cursor='';},2500);}});

    // Weather toggle — controls legend AND radar overlay
    document.getElementById('lyr-weather').addEventListener('change',function(){
      wxP.style.display=this.checked?'':'none';
      // Toggle radar layer visibility
      try {
        if (map.getLayer('radar-layer')) {
          map.setLayoutProperty('radar-layer', 'visibility', this.checked ? 'visible' : 'none');
        }
      } catch(e) { console.warn('[Aevus] Radar toggle:', e); }
    });

    // ═══ MAP STYLE SWITCHER ═══
    var _styleButtons = lp.querySelectorAll('.map-style-btn');
    _styleButtons.forEach(function(btn) {
      btn.addEventListener('click', function() {
        var newStyle = this.getAttribute('data-style');
        if (newStyle === _currentMapStyle) return;
        _currentMapStyle = newStyle;
        _styleButtons.forEach(function(b) { b.classList.remove('active'); });
        this.classList.add('active');

        // Toggle satellite mode class for marker styling
        if (newStyle === 'satellite' || newStyle === 'hybrid') {
          mapDiv.classList.add('map-satellite-mode');
        } else {
          mapDiv.classList.remove('map-satellite-mode');
        }

        // Switch map style
        if (_awsAuthReady) {
          var styleUrl = _awsStyleUrl(_mapStyles[newStyle].name, _mapStyles[newStyle].colorScheme);
          map.setStyle(styleUrl, { transformRequest: _awsTransformRequest });
          console.log('[Aevus] Switched to ' + newStyle + ' style (AWS)');
        } else {
          // CartoDB fallback only has dark - show notice for sat/hybrid
          if (newStyle !== 'dark') {
            console.warn('[Aevus] Satellite/hybrid requires AWS Location Service auth');
            // Still toggle the class for visual indication
          }
        }
      });
    });

    // ═══ SEARCH BAR ═══
    var searchContainer = document.createElement('div');
    searchContainer.className = 'map-search-container';
    searchContainer.innerHTML =
      '<div class="map-search-icon"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/></svg></div>' +
      '<input class="map-search-input" type="text" placeholder="Search assets or locations... (Ctrl+K)" id="map-search-input">' +
      '<div class="map-search-results" id="map-search-results"></div>';
    mapDiv.appendChild(searchContainer);

    var searchInput = document.getElementById('map-search-input');
    var searchResults = document.getElementById('map-search-results');

    // Ctrl+K / Cmd+K to focus search
    document.addEventListener('keydown', function(e) {
      if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault();
        if (document.querySelector('[data-page="map"]') && document.querySelector('[data-page="map"]').style.display !== 'none') {
          searchInput.focus();
        }
      }
    });

    searchInput.addEventListener('input', function() {
      var q = this.value.toLowerCase().trim();
      if (!q) { searchResults.classList.remove('active'); return; }

      var results = [];
      // Search assets
      var assets = window._getLiveAssets ? window._getLiveAssets() : [];
      assets.forEach(function(a) {
        if ((a.id || '').toLowerCase().indexOf(q) >= 0 ||
            (a.name || '').toLowerCase().indexOf(q) >= 0 ||
            (a.type || '').toLowerCase().indexOf(q) >= 0) {
          results.push({ type: 'asset', id: a.id, name: a.name, status: a.status, health: a.health });
        }
      });

      // Search geofence zones
      var zones = ['Comm Tower Zone 1', 'Pipeline Segment A', 'Security Perimeter', 'Power Grid Zone', 'Environmental Compliance'];
      zones.forEach(function(z) {
        if (z.toLowerCase().indexOf(q) >= 0) {
          results.push({ type: 'zone', name: z });
        }
      });

      if (results.length === 0) {
        searchResults.innerHTML = '<div style="padding:12px;color:#7B8499;font-size:11px;text-align:center;">No results found</div>';
      } else {
        searchResults.innerHTML = results.slice(0, 8).map(function(r) {
          if (r.type === 'asset') {
            var sc = {'good':'#10D478','warn':'#FBBF24','warning':'#FBBF24','bad':'#EF4444','critical':'#EF4444','offline':'#6B7280'};
            var rc = sc[(r.status||'').toLowerCase()] || '#6B7280';
            return '<div class="map-search-result-item" data-asset-id="' + r.id + '">' +
              '<span style="width:8px;height:8px;border-radius:50%;background:' + rc + ';flex-shrink:0;"></span>' +
              '<div><div style="font-weight:600;font-size:11px;color:#E2E8F0;">' + (r.name || r.id) + '</div>' +
              '<div style="font-size:9px;color:#7B8499;">' + r.id + ' · Health: ' + (r.health || '?') + '%</div></div></div>';
          } else {
            return '<div class="map-search-result-item" data-zone="' + r.name + '">' +
              '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#0EA5E9" stroke-width="2"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/></svg>' +
              '<div style="font-weight:600;font-size:11px;color:#E2E8F0;">' + r.name + '</div></div>';
          }
        }).join('');
      }
      searchResults.classList.add('active');
    });

    // Click search result → fly to asset
    searchResults.addEventListener('click', function(e) {
      var item = e.target.closest('.map-search-result-item');
      if (!item) return;
      var assetId = item.getAttribute('data-asset-id');
      if (assetId) {
        // Find marker and fly to it
        for (var i = 0; i < assetCoords.length; i++) {
          if (assetCoords[i].id === assetId) {
            map.flyTo({ center: [assetCoords[i].lng, assetCoords[i].lat], zoom: 16, duration: 1000 });
            // Open popup
            setTimeout(function() {
              var mk = markerList[i];
              if (mk && !mk.getPopup().isOpen()) mk.togglePopup();
            }, 1100);
            break;
          }
        }
      }
      searchInput.value = '';
      searchResults.classList.remove('active');
    });

    searchInput.addEventListener('blur', function() {
      setTimeout(function() { searchResults.classList.remove('active'); }, 200);
    });

    // ═══ SPATIAL ALARM CLUSTERING ═══
    // Define geofence zones (auto-generated from asset topology)
    var _geofenceZones = [
      {
        name: 'Comm Tower Zone',
        type: 'comm-tower-coverage',
        color: 'rgba(14,165,233,0.12)',
        borderColor: 'rgba(14,165,233,0.3)',
        // Circle around centroid of all radio assets
        center: (function() {
          var radios = assetCoords.filter(function(a) { return a.id.indexOf('RAD') === 0; });
          if (radios.length === 0) return [_mapOpts.center[0], _mapOpts.center[1]];
          var avgLng = 0, avgLat = 0;
          radios.forEach(function(r) { avgLng += r.lng; avgLat += r.lat; });
          return [avgLng / radios.length, avgLat / radios.length];
        })(),
        radiusMiles: 0.5,
        assets: assetCoords.filter(function(a) { return true; }).map(function(a) { return a.id; }) // all assets in RF range
      },
      {
        name: 'Pipeline Segment A',
        type: 'pipeline-segment',
        color: 'rgba(139,92,246,0.08)',
        borderColor: 'rgba(139,92,246,0.25)',
        // Line between EFM and RTR
        assets: ['EFM-01', 'SW-01', 'RTR-01']
      },
      {
        name: 'Security Perimeter',
        type: 'security-perimeter',
        color: 'rgba(239,68,68,0.05)',
        borderColor: 'rgba(239,68,68,0.15)',
        assets: assetCoords.map(function(a) { return a.id; })
      }
    ];
    window._geofenceZones = _geofenceZones;

    // Draw geofence boundaries when layer toggled
    var _geofenceLayerVisible = false;
    var _geofenceElements = [];

    function _drawGeofences() {
      // Remove existing
      _geofenceElements.forEach(function(el) { if (el && el.remove) el.remove(); });
      _geofenceElements = [];
      if (!_geofenceLayerVisible) return;

      // For comm tower zone, draw a circle overlay using CSS
      _geofenceZones.forEach(function(zone) {
        if (zone.center) {
          // Create a GeoJSON circle source + layer
          var circlePoints = [];
          var steps = 64;
          var km = zone.radiusMiles * 1.60934;
          for (var i = 0; i <= steps; i++) {
            var angle = (i / steps) * 2 * Math.PI;
            var dx = km * Math.cos(angle);
            var dy = km * Math.sin(angle);
            var lat = zone.center[1] + (dy / 111.32);
            var lng = zone.center[0] + (dx / (111.32 * Math.cos(zone.center[1] * Math.PI / 180)));
            circlePoints.push([lng, lat]);
          }

          var sourceId = 'geofence-' + zone.type;
          var fillId = sourceId + '-fill';
          var lineId = sourceId + '-line';

          // Remove if exists
          try { map.removeLayer(fillId); } catch(e) {}
          try { map.removeLayer(lineId); } catch(e) {}
          try { map.removeSource(sourceId); } catch(e) {}

          map.addSource(sourceId, {
            type: 'geojson',
            data: {
              type: 'Feature',
              geometry: { type: 'Polygon', coordinates: [circlePoints] }
            }
          });
          map.addLayer({
            id: fillId, type: 'fill', source: sourceId,
            paint: { 'fill-color': zone.color.replace(/[\d.]+\)$/, '0.08)'), 'fill-opacity': 0.6 }
          });
          map.addLayer({
            id: lineId, type: 'line', source: sourceId,
            paint: { 'line-color': zone.borderColor, 'line-width': 1.5, 'line-dasharray': [4, 2] }
          });
        }
      });
    }

    // Geofence layer toggle
    var geofenceCheckbox = document.getElementById('lyr-geofence');
    if (geofenceCheckbox) {
      geofenceCheckbox.addEventListener('change', function() {
        _geofenceLayerVisible = this.checked;
        _drawGeofences();
      });
    }

    // ═══ SPATIAL ALARM CORRELATION ═══
    // Check for geographically correlated alarms every 10 seconds
    window._spatialAlarmCheck = setInterval(function() {
      var alerts = window._getLiveAlerts ? window._getLiveAlerts() : [];
      if (alerts.length < 3) return; // Need 3+ alarms to cluster

      // Group alarms by asset
      var alarmsByAsset = {};
      alerts.forEach(function(al) {
        var aid = al.asset_id || al.assetId || '';
        if (!alarmsByAsset[aid]) alarmsByAsset[aid] = [];
        alarmsByAsset[aid].push(al);
      });

      // Check if multiple assets in same geofence zone have alarms
      _geofenceZones.forEach(function(zone) {
        var alarmingAssets = zone.assets.filter(function(aid) { return alarmsByAsset[aid] && alarmsByAsset[aid].length > 0; });
        if (alarmingAssets.length >= 3) {
          // Common cause detected!
          var existingBanner = document.getElementById('spatial-cluster-banner');
          if (!existingBanner) {
            var banner = document.createElement('div');
            banner.id = 'spatial-cluster-banner';
            banner.style.cssText = 'position:absolute;bottom:40px;left:50%;transform:translateX(-50%);z-index:180;background:rgba(239,68,68,0.15);border:1px solid rgba(239,68,68,0.4);border-radius:8px;padding:8px 16px;font-family:var(--font-body);font-size:11px;color:#EF4444;backdrop-filter:blur(8px);display:flex;align-items:center;gap:8px;animation:pinSlideIn 0.3s ease-out;white-space:nowrap;';
            banner.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#EF4444" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>' +
              '<span><strong>Spatial Correlation:</strong> ' + alarmingAssets.length + '/' + zone.assets.length + ' assets alarming in ' + zone.name + ' — Possible Common Cause</span>' +
              '<button onclick="this.parentElement.remove()" style="background:none;border:none;color:#EF4444;cursor:pointer;font-size:14px;margin-left:8px;">×</button>';
            mapDiv.appendChild(banner);
            // Auto-dismiss after 30s
            setTimeout(function() { var b = document.getElementById('spatial-cluster-banner'); if (b) b.remove(); }, 30000);
          }
        }
      });
    }, 10000);

    // ═══ DISPATCH ROUTE OPTIMIZER ═══
    var _dispatchPanel = document.createElement('div');
    _dispatchPanel.className = 'map-dispatch-panel';
    _dispatchPanel.id = 'map-dispatch-panel';
    _dispatchPanel.innerHTML =
      '<div class="map-dispatch-title">DISPATCH ROUTE</div>' +
      '<div id="dispatch-stops"></div>' +
      '<div class="map-dispatch-summary" id="dispatch-summary" style="display:none;">' +
        '<div>Est. Drive<br><span id="dispatch-time">—</span></div>' +
        '<div>Distance<br><span id="dispatch-dist">—</span></div>' +
        '<div>Stops<br><span id="dispatch-count">0</span></div>' +
      '</div>' +
      '<div style="margin-top:8px;display:flex;gap:6px;">' +
        '<button id="dispatch-clear" style="flex:1;padding:5px;font-size:9px;background:rgba(239,68,68,0.1);border:1px solid rgba(239,68,68,0.25);border-radius:6px;color:#EF4444;cursor:pointer;font-family:var(--font-body);">Clear Route</button>' +
        '<button id="dispatch-navigate" style="flex:1;padding:5px;font-size:9px;background:rgba(14,165,233,0.1);border:1px solid rgba(14,165,233,0.25);border-radius:6px;color:#0EA5E9;cursor:pointer;font-family:var(--font-body);">Open in Maps</button>' +
      '</div>';
    mapDiv.appendChild(_dispatchPanel);

    window._dispatchStops = [];
    window._addDispatchStop = function(assetId) {
      if (window._dispatchStops.indexOf(assetId) >= 0) return;
      window._dispatchStops.push(assetId);
      _updateDispatchPanel();
      // Close popup after adding to route
      setTimeout(function() {
        var popups = document.querySelectorAll('.maplibregl-popup');
        popups.forEach(function(p) { p.remove(); });
      }, 50);
    };

    function _updateDispatchPanel() {
      var stops = window._dispatchStops;
      if (stops.length === 0) {
        _dispatchPanel.classList.remove('active');
        return;
      }
      _dispatchPanel.classList.add('active');
      var stopsHtml = '';
      var totalDist = 0;
      stops.forEach(function(aid, i) {
        var ac = assetCoords.find(function(a) { return a.id === aid; });
        var sc = {'good':'#10D478','warn':'#FBBF24','warning':'#FBBF24','bad':'#EF4444','critical':'#EF4444','offline':'#6B7280'};
        var rc = sc[ac ? ac.status : ''] || '#6B7280';
        var priority = (ac && (ac.status === 'bad' || ac.status === 'critical')) ? 'CRITICAL' : (ac && (ac.status === 'warning' || ac.status === 'warn')) ? 'DEGRADING' : 'ROUTINE';
        stopsHtml += '<div class="map-dispatch-stop">' +
          '<span class="map-dispatch-stop-num" style="background:' + rc + '22;color:' + rc + ';">' + (i+1) + '</span>' +
          '<div style="flex:1;"><div style="font-weight:600;color:#E2E8F0;">' + aid + '</div>' +
          '<div style="font-size:9px;color:#7B8499;">' + priority + '</div></div>' +
          '<button onclick="window._removeDispatchStop(&quot;' + aid + '&quot;)" style="background:none;border:none;color:#EF4444;cursor:pointer;font-size:12px;">×</button></div>';
        if (i > 0) totalDist += 2.5; // Simulated distance between stops
      });
      document.getElementById('dispatch-stops').innerHTML = stopsHtml;
      if (stops.length >= 2) {
        document.getElementById('dispatch-summary').style.display = '';
        var estTime = Math.round(stops.length * 12 + totalDist * 2);
        document.getElementById('dispatch-time').textContent = estTime + ' min';
        document.getElementById('dispatch-dist').textContent = totalDist.toFixed(1) + ' mi';
        document.getElementById('dispatch-count').textContent = stops.length;

        // Draw route line on map
        _drawDispatchRoute();
      } else {
        document.getElementById('dispatch-summary').style.display = 'none';
      }
    }

    function _drawDispatchRoute() {
      var coords = [];
      window._dispatchStops.forEach(function(aid) {
        var ac = assetCoords.find(function(a) { return a.id === aid; });
        if (ac) coords.push([ac.lng, ac.lat]);
      });
      if (coords.length < 2) return;

      try { map.removeLayer('dispatch-route-line'); } catch(e) {}
      try { map.removeSource('dispatch-route'); } catch(e) {}

      map.addSource('dispatch-route', {
        type: 'geojson',
        data: {
          type: 'Feature',
          geometry: { type: 'LineString', coordinates: coords }
        }
      });
      map.addLayer({
        id: 'dispatch-route-line', type: 'line', source: 'dispatch-route',
        paint: {
          'line-color': '#0EA5E9',
          'line-width': 3,
          'line-dasharray': [2, 1],
          'line-opacity': 0.8
        }
      });
    }

    window._removeDispatchStop = function(aid) {
      window._dispatchStops = window._dispatchStops.filter(function(s) { return s !== aid; });
      try { map.removeLayer('dispatch-route-line'); } catch(e) {}
      try { map.removeSource('dispatch-route'); } catch(e) {}
      _updateDispatchPanel();
    };

    document.getElementById('dispatch-clear').addEventListener('click', function() {
      window._dispatchStops = [];
      try { map.removeLayer('dispatch-route-line'); } catch(e) {}
      try { map.removeSource('dispatch-route'); } catch(e) {}
      _updateDispatchPanel();
    });

    document.getElementById('dispatch-navigate').addEventListener('click', function() {
      if (window._dispatchStops.length === 0) return;
      var coords = [];
      window._dispatchStops.forEach(function(aid) {
        var ac = assetCoords.find(function(a) { return a.id === aid; });
        if (ac) coords.push(ac.lat + ',' + ac.lng);
      });
      var url;
      if (coords.length === 1) {
        url = 'https://www.google.com/maps/search/?api=1&query=' + coords[0];
      } else {
        url = 'https://www.google.com/maps/dir/' + coords.join('/');
      }
      window.open(url, '_blank');
    });

    // ═══ CROSS-PAGE "SHOW ON MAP" ═══
    
    // ═══ U1: RIGHT SLIDE-OUT ASSET PANEL ═══
    window._mapAssetPanel = null;
    window._openMapAssetPanel = function(assetId) {
        var mc = document.querySelector('.maplibregl-map') ? document.querySelector('.maplibregl-map').parentElement : null;
        if (!mc) return;
        mc.style.position = 'relative';
        mc.style.overflow = 'hidden';
        var asset = {id: assetId, health: 0, status: '', protocol: '', name: '', ip: '', firmware: '', lastSeen: null};
        var pops = document.querySelectorAll('.maplibregl-popup-content');
        if (pops.length > 0) {
            var txt = pops[pops.length - 1].textContent || '';
            var hm = txt.match(/HEALTH[^0-9]*(\d+)/i);
            var sm = txt.match(/STATUS[^a-zA-Z]*([a-zA-Z]+)/i);
            var pm = txt.match(/PROTOCOL[^a-zA-Z]*([a-zA-Z\s]+?)(?:\s|$)/i);
            if (hm) asset.health = parseInt(hm[1]);
            if (sm) asset.status = sm[1];
            if (pm) asset.protocol = pm[1].trim();
        }
        var existing = document.getElementById('map-asset-slideout');
        if (existing) existing.remove();
        var panel = document.createElement('div');
        panel.id = 'map-asset-slideout';
        panel.style.cssText = 'position:absolute;top:0;right:0;width:360px;height:100%;background:#0f172a;border-left:1px solid rgba(56,189,248,0.2);z-index:1000;overflow-y:auto;transition:transform 0.3s ease;color:#e2e8f0;font-family:Inter,system-ui,sans-serif;';
        var hColor = asset.health >= 80 ? '#22c55e' : asset.health >= 50 ? '#eab308' : '#ef4444';
        var sColor = (asset.status||'').toLowerCase() === 'good' || (asset.status||'').toLowerCase() === 'normal' ? '#22c55e' : '#94a3b8';
        var html = '<div style="padding:20px;">';
        html += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">';
        html += '<span style="font-size:11px;text-transform:uppercase;letter-spacing:1.5px;color:#94a3b8;">ASSET DETAIL</span>';
        html += '<button onclick="var p=document.getElementById(\'map-asset-slideout\');if(p)p.remove();" style="background:none;border:none;color:#94a3b8;cursor:pointer;font-size:18px;">\u2715</button>';
        html += '</div>';
        html += '<h2 style="font-size:20px;font-weight:600;color:#38bdf8;margin:0 0 20px 0;">' + assetId + '</h2>';
        html += '<div style="display:flex;gap:20px;margin-bottom:24px;">';
        html += '<div style="text-align:center;flex:1;"><div style="font-size:36px;font-weight:700;color:' + hColor + ';">' + asset.health + '</div><div style="font-size:11px;text-transform:uppercase;letter-spacing:1px;color:#64748b;">HEALTH</div></div>';
        html += '<div style="text-align:center;flex:1;"><div style="font-size:16px;font-weight:500;color:' + sColor + ';">' + (asset.status || '\u2014') + '</div><div style="font-size:11px;text-transform:uppercase;letter-spacing:1px;color:#64748b;">STATUS</div></div>';
        html += '</div>';
        html += '<div style="border-top:1px solid rgba(148,163,184,0.1);padding-top:16px;">';
        html += '<div style="font-size:12px;font-weight:600;text-transform:uppercase;letter-spacing:1px;color:#94a3b8;margin-bottom:12px;">DETAILS</div>';
        var fields = [['Protocol', asset.protocol], ['IP Address', asset.ip], ['Firmware', asset.firmware], ['Last Seen', asset.lastSeen]];
        for (var i = 0; i < fields.length; i++) {
            html += '<div style="display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid rgba(148,163,184,0.05);">';
            html += '<span style="color:#94a3b8;font-size:13px;">' + fields[i][0] + '</span>';
            html += '<span style="color:#e2e8f0;font-size:13px;">' + (fields[i][1] || '\u2014') + '</span>';
            html += '</div>';
        }
        html += '</div>';
        html += '<button style="width:100%;margin-top:24px;padding:12px;background:rgba(56,189,248,0.15);border:1px solid rgba(56,189,248,0.3);border-radius:8px;color:#38bdf8;font-size:14px;cursor:pointer;">View Full Asset Profile \u2192</button>';
        html += '</div>';
        panel.innerHTML = html;
        mc.appendChild(panel);
    };
    window._closeMapAssetPanel = function() {
        var panel = document.getElementById('map-asset-slideout');
        if (panel) { panel.style.right = '-380px'; }
    }
    // U1c: Auto-open panel when popup appears (MutationObserver approach)
    (function() {
        var _mapEl = document.getElementById('aevus-map');
        if (!_mapEl || window._popupObsInstalled) return;
        window._popupObsInstalled = true;
        var obs = new MutationObserver(function(mutations) {
            for (var i = 0; i < mutations.length; i++) {
                var added = mutations[i].addedNodes;
                for (var j = 0; j < added.length; j++) {
                    var node = added[j];
                    if (node.nodeType !== 1) continue;
                    if (node.classList && node.classList.contains('maplibregl-popup')) {
                        (function(popNode) {
                            setTimeout(function() {
                                var content = popNode.querySelector('.maplibregl-popup-content');
                                if (!content) return;
                                var name = '';
                                var strongs = content.querySelectorAll('strong, b');
                                for (var k = 0; k < strongs.length; k++) {
                                    var s = strongs[k];
                                    if (s.closest && s.closest('style')) continue;
                                    var txt = s.textContent.trim();
                                    if (txt && txt.indexOf('@') === -1 && txt.indexOf('{') === -1) { name = txt; break; }
                                }
                                if (!name) {
                                    var walker = document.createTreeWalker(content, NodeFilter.SHOW_TEXT, null, false);
                                    var tn;
                                    while (tn = walker.nextNode()) {
                                        if (tn.parentElement && tn.parentElement.tagName === 'STYLE') continue;
                                        var t = tn.textContent.trim();
                                        if (t && t.length > 2 && t.indexOf('@') === -1 && t.indexOf('{') === -1) { name = t.substring(0, 40); break; }
                                    }
                                }
                                if (name && window._openMapAssetPanel) window._openMapAssetPanel(name);
                            }, 200);
                        })(node);
                    }
                }
            }
        });
        obs.observe(_mapEl, {childList: true, subtree: true});
    })();
;

    window._allEquipment = typeof equipment !== "undefined" ? equipment : [];
    window._flyToAssetOnMap = function(assetId) {
      // Navigate to map page first
      if (typeof navigateTo === 'function') navigateTo('map');
      setTimeout(function() {
        for (var i = 0; i < assetCoords.length; i++) {
          if (assetCoords[i].id === assetId) {
            var m = window._aevusMapInstance;
            if (m) {
              m.flyTo({ center: [assetCoords[i].lng, assetCoords[i].lat], zoom: 16, duration: 1200 });
              setTimeout(function() {
                var mk = markerList[i];
                if (mk && !mk.getPopup().isOpen()) mk.togglePopup();
              }, 1300);
            }
            break;
          }
        }
      }, 500);
    };

    // ═══ PERFORMANCE CHECKPOINT ═══
    performance.mark('map-init-complete');
    if (performance.getEntriesByName('map-tiles-loaded').length === 0) {
      map.once('idle', function() {
        performance.mark('map-tiles-loaded');
        var loadTime = performance.now();
        console.log('[Aevus] Map tiles loaded in ' + (loadTime / 1000).toFixed(2) + 's');
        if (loadTime > 2000) console.warn('[Aevus] Map load exceeded ISA-101 §8.1 2s budget: ' + (loadTime / 1000).toFixed(2) + 's');
      });
    }

    // ═══ LIVE MARKER UPDATES (heartbeat state sync) ═══
    setInterval(function() {
      var assets = window._getLiveAssets ? window._getLiveAssets() : [];
      markerList.forEach(function(mk, i) {
        var el = mk.getElement();
        if (!el) return;
        var aid = el.getAttribute('data-asset-id');
        var asset = assets.find(function(a) { return a.id === aid; });
        if (!asset) return;

        var newS = (asset.status || '').toLowerCase();
        var oldS = el.getAttribute('data-asset-status');
        if (newS === oldS) return; // No change

        el.setAttribute('data-asset-status', newS);
        // Update heartbeat class
        el.classList.remove('map-marker-alive', 'map-marker-flatline', 'map-marker-abnormal', 'map-marker-warning');
        if (newS === 'offline' || newS === 'unknown') {
          el.classList.add('map-marker-flatline');
        } else if (newS === 'bad' || newS === 'critical') {
          el.classList.add('map-marker-abnormal');
        } else if (newS === 'warning' || newS === 'warn') {
          el.classList.add('map-marker-warning');
        } else {
          el.classList.add('map-marker-alive');
        }

        // Update pinned card if pinned
        if (window._mapPinnedAssets && window._mapPinnedAssets[aid]) {
          window._unpinMapAsset(aid);
          window._pinAssetById(aid);
        }
      });
    }, 5000);
    document.getElementById('lyr-assets').addEventListener('change',function(){var show=this.checked;markerList.forEach(function(mk){mk.getElement().style.display=show?'':'none';});});

    // Mapbox layers + toggle wiring — ALL inside map.on('load')
    map.on('load', function(){
      // Helper
      function sv(ids,vis){ids.forEach(function(id){if(map.getLayer(id))map.setLayoutProperty(id,'visibility',vis);});}

      // RF Signal lines
      if (assetCoords.length >= 2) {
        var rfF=[];
        for(var r=0;r<assetCoords.length-1;r++){
          var q=70+Math.floor(Math.random()*25);
          rfF.push({type:'Feature',properties:{quality:q,label:assetCoords[r].name+' ↔ '+assetCoords[r+1].name+' ('+q+'%)'},geometry:{type:'LineString',coordinates:[[assetCoords[r].lng,assetCoords[r].lat],[assetCoords[r+1].lng,assetCoords[r+1].lat]]}});
        }
        map.addSource('rf-signals',{type:'geojson',data:{type:'FeatureCollection',features:rfF}});
        map.addLayer({id:'rf-lines',type:'line',source:'rf-signals',layout:{visibility:'none'},paint:{'line-color':'#0EA5E9','line-width':2.5,'line-dasharray':[4,3],'line-opacity':0.9}});

        var pipeCoords=assetCoords.map(function(a){return[a.lng,a.lat];});
        map.addSource('pipeline',{type:'geojson',data:{type:'FeatureCollection',features:[{type:'Feature',properties:{},geometry:{type:'LineString',coordinates:pipeCoords}}]}});
        map.addLayer({id:'pipe-line',type:'line',source:'pipeline',layout:{visibility:'none'},paint:{'line-color':'#FBBF24','line-width':3,'line-opacity':0.7}});
        map.addLayer({id:'pipe-arrows',type:'symbol',source:'pipeline',layout:{visibility:'none','symbol-placement':'line','symbol-spacing':60,'text-field':'▶','text-size':14,'text-keep-upright':false,'text-rotation-alignment':'map'},paint:{'text-color':'#FBBF24','text-opacity':0.8}});
      }

      // Zones
      if (assetCoords.length >= 3) {
        var half=Math.ceil(assetCoords.length/2);
        function makeZone(pts,expand){
          var cx=pts.reduce(function(s,a){return s+a.lng;},0)/pts.length;
          var cy=pts.reduce(function(s,a){return s+a.lat;},0)/pts.length;
          var sorted=pts.slice().sort(function(a,b){return Math.atan2(a.lat-cy,a.lng-cx)-Math.atan2(b.lat-cy,b.lng-cx);});
          var coords=sorted.map(function(p){return[cx+(p.lng-cx)*expand,cy+(p.lat-cy)*expand];});
          coords.push(coords[0]);return coords;
        }
        var zf=[{type:'Feature',properties:{zone:'Zone 1 — Control (SL3)',level:'SL3'},geometry:{type:'Polygon',coordinates:[makeZone(assetCoords.slice(0,half),3.5)]}}];
        if(assetCoords.length-half>=2) zf.push({type:'Feature',properties:{zone:'Zone 2 — Field (SL2)',level:'SL2'},geometry:{type:'Polygon',coordinates:[makeZone(assetCoords.slice(half),3.5)]}});
        map.addSource('sec-zones',{type:'geojson',data:{type:'FeatureCollection',features:zf}});
        map.addLayer({id:'zone-fill',type:'fill',source:'sec-zones',layout:{visibility:'none'},paint:{'fill-color':['match',['get','level'],'SL3','rgba(239,68,68,0.12)','SL2','rgba(251,191,36,0.12)','rgba(107,114,128,0.05)'],'fill-opacity':0.8}},map.getLayer('rf-lines')?'rf-lines':undefined);
        map.addLayer({id:'zone-border',type:'line',source:'sec-zones',layout:{visibility:'none'},paint:{'line-color':['match',['get','level'],'SL3','#EF4444','SL2','#FBBF24','#6B7280'],'line-width':2,'line-dasharray':[6,4],'line-opacity':0.8}});
        map.addLayer({id:'zone-labels',type:'symbol',source:'sec-zones',layout:{visibility:'none','text-field':['get','zone'],'text-size':12,'text-font':['Open Sans Bold']},paint:{'text-color':'#E2E8F0','text-halo-color':'rgba(11,16,32,0.9)','text-halo-width':2}});
      }

      // Env hazard
      if(assetCoords.length>0){
        map.addSource('env-hazards',{type:'geojson',data:{type:'FeatureCollection',features:[{type:'Feature',properties:{},geometry:{type:'Point',coordinates:[assetCoords[0].lng+0.001,assetCoords[0].lat+0.0005]}}]}});
        map.addLayer({id:'hazard-circles',type:'circle',source:'env-hazards',layout:{visibility:'none'},paint:{'circle-radius':60,'circle-color':'rgba(251,191,36,0.08)','circle-stroke-color':'#FBBF24','circle-stroke-width':1.5,'circle-opacity':0.5}});
      }

      // NOW wire the Mapbox layer toggles — layers guaranteed to exist
      document.getElementById('lyr-rf').addEventListener('change',function(){sv(['rf-lines'],this.checked?'visible':'none');});
      document.getElementById('lyr-pipe').addEventListener('change',function(){sv(['pipe-line','pipe-arrows'],this.checked?'visible':'none');});
      document.getElementById('lyr-zones').addEventListener('change',function(){sv(['zone-fill','zone-border','zone-labels'],this.checked?'visible':'none');});
      document.getElementById('lyr-hazards').addEventListener('change',function(){sv(['hazard-circles'],this.checked?'visible':'none');});


      // ══════════════════════════════════════════════════
      // PHASE 2: SCADA-Driven Layers
      // ══════════════════════════════════════════════════

      // ── 2A: Pipeline Flow Overlay (animated dashes showing flow direction) ──
      if (map.getSource('pipeline')) {
        map.addLayer({id:'pipe-flow-anim',type:'line',source:'pipeline',
          layout:{visibility:'none'},
          paint:{'line-color':'#10D478','line-width':2,'line-opacity':0.6,
            'line-dasharray':[2,4]}
        });
        // Animate flow direction
        var _flowPhase = 0;
        function _animateFlow() {
          _flowPhase = (_flowPhase + 1) % 6;
          if (map.getLayer('pipe-flow-anim')) {
            map.setPaintProperty('pipe-flow-anim','line-dasharray',
              [2, 4 - (_flowPhase % 3), _flowPhase % 3]);
          }
          if (document.getElementById('lyr-pipe') &&
              document.getElementById('lyr-pipe').checked) {
            setTimeout(_animateFlow, 300);
          }
        }
        document.getElementById('lyr-pipe').addEventListener('change', function() {
          sv(['pipe-flow-anim'], this.checked ? 'visible' : 'none');
          if (this.checked) _animateFlow();
        });
      }

      // ── 2B: Alarm Heat Map ──
      var _alarmPts = [];
      (liveAssets||[]).forEach(function(a) {
        if (!a.vitals) return;
        var alarms = 0;
        a.vitals.forEach(function(v) {
          if (v.status === 'bad' || v.status === 'critical') alarms++;
        });
        if (alarms > 0 && a.latitude && a.longitude) {
          _alarmPts.push({
            type: 'Feature',
            properties: { intensity: Math.min(1, alarms / 3), count: alarms },
            geometry: { type: 'Point', coordinates: [a.longitude, a.latitude] }
          });
        }
      });
      if (_alarmPts.length > 0) {
        map.addSource('alarm-heat', {
          type: 'geojson',
          data: { type: 'FeatureCollection', features: _alarmPts }
        });
        map.addLayer({
          id: 'alarm-heatmap', type: 'heatmap', source: 'alarm-heat',
          layout: { visibility: 'none' },
          paint: {
            'heatmap-weight': ['get', 'intensity'],
            'heatmap-intensity': 1.5,
            'heatmap-radius': 80,
            'heatmap-color': [
              'interpolate', ['linear'], ['heatmap-density'],
              0, 'rgba(0,0,0,0)',
              0.2, 'rgba(251,191,36,0.3)',
              0.5, 'rgba(239,68,68,0.5)',
              0.8, 'rgba(239,68,68,0.7)',
              1, 'rgba(239,68,68,0.9)'
            ],
            'heatmap-opacity': 0.7
          }
        }, map.getLayer('rf-lines') ? 'rf-lines' : undefined);
      }

      // ── 2C: Health Gradient Contour ──
      var _healthPts = [];
      (liveAssets||[]).forEach(function(a) {
        if (a.latitude && a.longitude && a.health != null) {
          _healthPts.push({
            type: 'Feature',
            properties: { health: parseInt(a.health) || 50 },
            geometry: { type: 'Point', coordinates: [a.longitude, a.latitude] }
          });
        }
      });
      if (_healthPts.length > 0) {
        map.addSource('health-gradient', {
          type: 'geojson',
          data: { type: 'FeatureCollection', features: _healthPts }
        });
        map.addLayer({
          id: 'health-heatmap', type: 'heatmap', source: 'health-gradient',
          layout: { visibility: 'none' },
          paint: {
            'heatmap-weight': ['/', ['get', 'health'], 100],
            'heatmap-intensity': 1.2,
            'heatmap-radius': 100,
            'heatmap-color': [
              'interpolate', ['linear'], ['heatmap-density'],
              0, 'rgba(0,0,0,0)',
              0.2, 'rgba(239,68,68,0.2)',
              0.4, 'rgba(251,191,36,0.3)',
              0.6, 'rgba(16,212,120,0.3)',
              0.8, 'rgba(16,212,120,0.5)',
              1, 'rgba(16,212,120,0.7)'
            ],
            'heatmap-opacity': 0.6
          }
        }, map.getLayer('rf-lines') ? 'rf-lines' : undefined);
      }

      // ── 2D: RF Coverage Heatmap ──
      var _rfCovPts = [];
      (liveAssets||[]).forEach(function(a) {
        var dt = (a.type||'').toLowerCase();
        var id = (a.id||'');
        if ((dt === 'radio' || id.indexOf('RAD') === 0) && a.latitude && a.longitude) {
          // Generate coverage area points around radio towers
          var strength = 0.8 + Math.random() * 0.2;
          _rfCovPts.push({
            type: 'Feature',
            properties: { strength: strength, name: a.name },
            geometry: { type: 'Point', coordinates: [a.longitude, a.latitude] }
          });
          // Add surrounding coverage points
          for (var rAngle = 0; rAngle < 360; rAngle += 45) {
            var rad = rAngle * Math.PI / 180;
            var dist = 0.002 + Math.random() * 0.001;
            _rfCovPts.push({
              type: 'Feature',
              properties: { strength: strength * (0.4 + Math.random() * 0.3) },
              geometry: { type: 'Point', coordinates: [
                a.longitude + Math.cos(rad) * dist,
                a.latitude + Math.sin(rad) * dist
              ]}
            });
          }
        }
      });
      if (_rfCovPts.length > 0) {
        map.addSource('rf-coverage', {
          type: 'geojson',
          data: { type: 'FeatureCollection', features: _rfCovPts }
        });
        map.addLayer({
          id: 'rf-coverage-heatmap', type: 'heatmap', source: 'rf-coverage',
          layout: { visibility: 'none' },
          paint: {
            'heatmap-weight': ['get', 'strength'],
            'heatmap-intensity': 1.0,
            'heatmap-radius': 60,
            'heatmap-color': [
              'interpolate', ['linear'], ['heatmap-density'],
              0, 'rgba(0,0,0,0)',
              0.15, 'rgba(14,165,233,0.1)',
              0.3, 'rgba(14,165,233,0.25)',
              0.5, 'rgba(14,165,233,0.4)',
              0.7, 'rgba(96,165,250,0.5)',
              1, 'rgba(96,165,250,0.7)'
            ],
            'heatmap-opacity': 0.65
          }
        }, map.getLayer('rf-lines') ? 'rf-lines' : undefined);
      }

      // ── 2E: Wind/Weather Overlay (directional wind arrows) ──
      var _windFeatures = [];
      var _windDir = Math.random() * 360;
      var _windSpeed = 5 + Math.random() * 15;
      if (assetCoords.length > 0) {
        var cLng = assetCoords.reduce(function(s,a){return s+a.lng;},0)/assetCoords.length;
        var cLat = assetCoords.reduce(function(s,a){return s+a.lat;},0)/assetCoords.length;
        // Grid of wind arrows
        for (var wx = -3; wx <= 3; wx++) {
          for (var wy = -3; wy <= 3; wy++) {
            _windFeatures.push({
              type: 'Feature',
              properties: {
                direction: _windDir + (Math.random()-0.5)*20,
                speed: _windSpeed + (Math.random()-0.5)*4
              },
              geometry: { type: 'Point', coordinates: [
                cLng + wx * 0.0015,
                cLat + wy * 0.0012
              ]}
            });
          }
        }
      }
      if (_windFeatures.length > 0) {
        map.addSource('wind-overlay', {
          type: 'geojson',
          data: { type: 'FeatureCollection', features: _windFeatures }
        });
        map.addLayer({
          id: 'wind-arrows', type: 'symbol', source: 'wind-overlay',
          layout: {
            visibility: 'none',
            'icon-image': '',
            'text-field': '→',
            'text-size': 16,
            'text-rotate': ['get', 'direction'],
            'text-rotation-alignment': 'map',
            'text-allow-overlap': true,
            'text-ignore-placement': true
          },
          paint: {
            'text-color': 'rgba(96,165,250,0.35)',
            'text-halo-color': 'rgba(0,0,0,0.2)',
            'text-halo-width': 1
          }
        });
      }

      // ══════════════════════════════════════════════════
      // PHASE 3: Geospatial Intelligence
      // ══════════════════════════════════════════════════

      // ── 3A: Asset Tracker Trails ──
      var _trackerTrails = [];
      (liveAssets||[]).forEach(function(a) {
        if (!a.latitude || !a.longitude) return;
        // Simulate recent position history (last 8 positions)
        var trail = [];
        var lng = a.longitude, lat = a.latitude;
        for (var ti = 7; ti >= 0; ti--) {
          trail.push([
            lng + (Math.random() - 0.5) * 0.0008 * ti,
            lat + (Math.random() - 0.5) * 0.0006 * ti
          ]);
        }
        _trackerTrails.push({
          type: 'Feature',
          properties: { name: a.name, id: a.id, status: a.status || 'unknown' },
          geometry: { type: 'LineString', coordinates: trail }
        });
      });
      if (_trackerTrails.length > 0) {
        map.addSource('asset-tracker', {
          type: 'geojson',
          data: { type: 'FeatureCollection', features: _trackerTrails }
        });
        map.addLayer({
          id: 'tracker-trails', type: 'line', source: 'asset-tracker',
          layout: { visibility: 'none' },
          paint: {
            'line-color': '#818CF8',
            'line-width': 2,
            'line-opacity': 0.5,
            'line-dasharray': [2, 2]
          }
        });
        map.addLayer({
          id: 'tracker-points', type: 'circle', source: 'asset-tracker',
          layout: { visibility: 'none' },
          paint: {
            'circle-radius': 3,
            'circle-color': '#818CF8',
            'circle-opacity': 0.4,
            'circle-stroke-color': '#818CF8',
            'circle-stroke-width': 1
          }
        });
      }

      // ── 3B: Geofences ──
      var _geofences = [];
      if (assetCoords.length > 0) {
        // Create facility perimeter geofence
        var gCx = assetCoords.reduce(function(s,a){return s+a.lng;},0)/assetCoords.length;
        var gCy = assetCoords.reduce(function(s,a){return s+a.lat;},0)/assetCoords.length;
        var perimCoords = [];
        for (var gA = 0; gA < 360; gA += 15) {
          var gRad = gA * Math.PI / 180;
          var gDist = 0.004 + Math.sin(gA * 3 * Math.PI / 180) * 0.0008;
          perimCoords.push([
            gCx + Math.cos(gRad) * gDist,
            gCy + Math.sin(gRad) * gDist
          ]);
        }
        perimCoords.push(perimCoords[0]);

        _geofences.push({
          type: 'Feature',
          properties: { name: 'Facility Perimeter', type: 'perimeter', alert: 'entry' },
          geometry: { type: 'Polygon', coordinates: [perimCoords] }
        });

        // Exclusion zone around first asset
        var exCoords = [];
        for (var eA = 0; eA < 360; eA += 30) {
          var eRad = eA * Math.PI / 180;
          exCoords.push([
            assetCoords[0].lng + Math.cos(eRad) * 0.0012,
            assetCoords[0].lat + Math.sin(eRad) * 0.0009
          ]);
        }
        exCoords.push(exCoords[0]);
        _geofences.push({
          type: 'Feature',
          properties: { name: 'Restricted Zone A', type: 'restricted', alert: 'entry' },
          geometry: { type: 'Polygon', coordinates: [exCoords] }
        });
      }

      if (_geofences.length > 0) {
        map.addSource('aevus-geofences', {
          type: 'geojson',
          data: { type: 'FeatureCollection', features: _geofences }
        });
        map.addLayer({
          id: 'geofence-fill', type: 'fill', source: 'aevus-geofences',
          layout: { visibility: 'none' },
          paint: {
            'fill-color': ['match', ['get', 'type'],
              'perimeter', 'rgba(129,140,248,0.06)',
              'restricted', 'rgba(239,68,68,0.08)',
              'rgba(107,114,128,0.05)'
            ],
            'fill-opacity': 0.8
          }
        }, map.getLayer('rf-lines') ? 'rf-lines' : undefined);
        map.addLayer({
          id: 'geofence-border', type: 'line', source: 'aevus-geofences',
          layout: { visibility: 'none' },
          paint: {
            'line-color': ['match', ['get', 'type'],
              'perimeter', '#818CF8',
              'restricted', '#EF4444',
              '#6B7280'
            ],
            'line-width': 2,
            'line-dasharray': [4, 3],
            'line-opacity': 0.7
          }
        });
        map.addLayer({
          id: 'geofence-labels', type: 'symbol', source: 'aevus-geofences',
          layout: {
            visibility: 'none',
            'text-field': ['get', 'name'],
            'text-size': 11,
            'text-font': ['Open Sans Bold']
          },
          paint: {
            'text-color': '#C4B5FD',
            'text-halo-color': 'rgba(11,16,32,0.9)',
            'text-halo-width': 2
          }
        });
      }

      // ── 3C: Visit Log (simulated recent technician visits) ──
      var _visitPts = [];
      (liveAssets||[]).forEach(function(a) {
        if (!a.latitude || !a.longitude) return;
        if (Math.random() > 0.5) {
          var hoursAgo = Math.floor(Math.random() * 72);
          _visitPts.push({
            type: 'Feature',
            properties: {
              asset: a.name,
              tech: ['J. Martinez', 'R. Thompson', 'K. Patel'][Math.floor(Math.random()*3)],
              time: hoursAgo + 'h ago',
              type: ['Inspection', 'Maintenance', 'Calibration'][Math.floor(Math.random()*3)]
            },
            geometry: { type: 'Point', coordinates: [
              a.longitude + (Math.random()-0.5)*0.0003,
              a.latitude + (Math.random()-0.5)*0.0003
            ]}
          });
        }
      });
      if (_visitPts.length > 0) {
        map.addSource('visit-log', {
          type: 'geojson',
          data: { type: 'FeatureCollection', features: _visitPts }
        });
        map.addLayer({
          id: 'visit-markers', type: 'circle', source: 'visit-log',
          layout: { visibility: 'none' },
          paint: {
            'circle-radius': 6,
            'circle-color': 'rgba(196,181,253,0.3)',
            'circle-stroke-color': '#C4B5FD',
            'circle-stroke-width': 1.5,
            'circle-opacity': 0.7
          }
        });
        map.addLayer({
          id: 'visit-labels', type: 'symbol', source: 'visit-log',
          layout: {
            visibility: 'none',
            'text-field': ['concat', ['get', 'tech'], ' · ', ['get', 'time']],
            'text-size': 9,
            'text-offset': [0, 1.5],
            'text-font': ['Open Sans Regular']
          },
          paint: {
            'text-color': '#C4B5FD',
            'text-halo-color': 'rgba(11,16,32,0.9)',
            'text-halo-width': 1.5,
            'text-opacity': 0.7
          }
        });
      }

      // ── 3D: Dispatch Routes (optimal path between assets needing attention) ──
      var _dispatchCoords = [];
      (liveAssets||[]).forEach(function(a) {
        if (!a.latitude || !a.longitude) return;
        var s = (a.status||'').toLowerCase();
        if (s === 'bad' || s === 'critical' || s === 'warning' || s === 'warn') {
          _dispatchCoords.push([a.longitude, a.latitude]);
        }
      });
      if (_dispatchCoords.length >= 2) {
        // Add start point (gate/entry) slightly offset
        var dStart = [_dispatchCoords[0][0] - 0.003, _dispatchCoords[0][1] + 0.002];
        var fullRoute = [dStart].concat(_dispatchCoords).concat([dStart]);
        map.addSource('dispatch-route', {
          type: 'geojson',
          data: { type: 'FeatureCollection', features: [{
            type: 'Feature',
            properties: { stops: _dispatchCoords.length, eta: Math.ceil(_dispatchCoords.length * 12) + ' min' },
            geometry: { type: 'LineString', coordinates: fullRoute }
          }]}
        });
        map.addLayer({
          id: 'dispatch-line', type: 'line', source: 'dispatch-route',
          layout: { visibility: 'none' },
          paint: {
            'line-color': '#F472B6',
            'line-width': 3,
            'line-opacity': 0.7,
            'line-dasharray': [6, 3]
          }
        });
        map.addLayer({
          id: 'dispatch-arrows', type: 'symbol', source: 'dispatch-route',
          layout: {
            visibility: 'none',
            'symbol-placement': 'line',
            'symbol-spacing': 80,
            'text-field': '▶',
            'text-size': 12,
            'text-keep-upright': false,
            'text-rotation-alignment': 'map'
          },
          paint: { 'text-color': '#F472B6', 'text-opacity': 0.8 }
        });
      }

      // ── 3E: Anomaly Correlation (geographic clustering of issues) ──
      var _anomalyPts = [];
      (liveAssets||[]).forEach(function(a) {
        if (!a.latitude || !a.longitude || !a.vitals) return;
        a.vitals.forEach(function(v) {
          if (v.status === 'bad' || v.status === 'critical') {
            _anomalyPts.push({
              type: 'Feature',
              properties: {
                asset: a.name,
                vital: v.label,
                severity: v.status === 'critical' ? 1.0 : 0.6
              },
              geometry: { type: 'Point', coordinates: [
                a.longitude + (Math.random()-0.5)*0.0004,
                a.latitude + (Math.random()-0.5)*0.0004
              ]}
            });
          }
        });
      });
      if (_anomalyPts.length > 0) {
        map.addSource('anomaly-correlation', {
          type: 'geojson',
          data: { type: 'FeatureCollection', features: _anomalyPts }
        });
        map.addLayer({
          id: 'anomaly-clusters', type: 'circle', source: 'anomaly-correlation',
          layout: { visibility: 'none' },
          paint: {
            'circle-radius': ['interpolate', ['linear'], ['get', 'severity'], 0.5, 20, 1.0, 40],
            'circle-color': 'rgba(239,68,68,0.08)',
            'circle-stroke-color': '#EF4444',
            'circle-stroke-width': 1,
            'circle-opacity': 0.5
          }
        }, map.getLayer('rf-lines') ? 'rf-lines' : undefined);
        map.addLayer({
          id: 'anomaly-labels', type: 'symbol', source: 'anomaly-correlation',
          layout: {
            visibility: 'none',
            'text-field': ['concat', ['get', 'asset'], '\n', ['get', 'vital']],
            'text-size': 9,
            'text-font': ['Open Sans Regular'],
            'text-offset': [0, 2]
          },
          paint: {
            'text-color': '#FCA5A5',
            'text-halo-color': 'rgba(11,16,32,0.9)',
            'text-halo-width': 1.5,
            'text-opacity': 0.6
          }
        });
      }

      // ── Phase 2+3 Layer Toggle Wiring ──
      var _p2Layers = {
        'lyr-alarms': ['alarm-heatmap'],
        'lyr-health': ['health-heatmap'],
        'lyr-rfcov': ['rf-coverage-heatmap'],
        'lyr-wind': ['wind-arrows'],
        'lyr-tracker': ['tracker-trails','tracker-points'],
        'lyr-geofence': ['geofence-fill','geofence-border','geofence-labels'],
        'lyr-visits': ['visit-markers','visit-labels'],
        'lyr-dispatch': ['dispatch-line','dispatch-arrows'],
        'lyr-anomaly': ['anomaly-clusters','anomaly-labels']
      };
      Object.keys(_p2Layers).forEach(function(elId) {
        var el = document.getElementById(elId);
        if (el) {
          el.addEventListener('change', function() {
            sv(_p2Layers[elId], this.checked ? 'visible' : 'none');
          });
          if (el.checked) sv(_p2Layers[elId], 'visible');
        }
      });

      // Sync: if user already checked any boxes before load, apply now
      if(document.getElementById('lyr-rf').checked) sv(['rf-lines'],'visible');
      if(document.getElementById('lyr-pipe').checked) sv(['pipe-line','pipe-arrows','pipe-flow-anim'],'visible');
      if(document.getElementById('lyr-zones').checked) sv(['zone-fill','zone-border','zone-labels'],'visible');
      if(document.getElementById('lyr-hazards').checked) sv(['hazard-circles'],'visible');
    });
  }


  function updateMapMarkers() { /* disabled — initAevusMap handles markers */ }


  // ── 5th Audit #8: Respond/Recover remediation roadmap ──

  // expose for takeover
  window.__awardRenderMapPage = renderMapPage;

  // ---- #map takeover --------------------------------------------------------
  function _onMap() {
    var h = (location.hash || "").toLowerCase();
    return h.indexOf("map") > -1;
  }
  var _mounted = false, _busy = false;
  function _forceMapSize() {
    var page = document.querySelector('section[data-page="map"]');
    if (page) { page.style.height = "calc(100vh - 56px)"; page.style.minHeight = "640px"; page.style.padding = "0"; page.style.overflow = "hidden"; page.style.position = "relative"; }
    var md = document.getElementById("aevus-map");
    if (md) { md.style.width = "100%"; md.style.height = "100%"; md.style.minHeight = "640px"; md.style.position = "relative"; }
    var mainEl = document.querySelector(".main");
    if (mainEl) { mainEl.style.padding = "0"; mainEl.style.overflow = "hidden"; }
  }
  function _mountIfNeeded() {
    if (!_onMap()) { _mounted = false; return; }   // left map -> allow remount on return
    if (_mounted || _busy) return;
    _busy = true;
    setTimeout(function () {
      try {
        var page = document.querySelector('section[data-page="map"]');
        if (!page) { _busy = false; return; }
        window._aevusMapLoaded = false;
        if (window._aevusMapInstance) { try { window._aevusMapInstance.remove(); } catch (e) {} window._aevusMapInstance = null; }
        window.__awardRenderMapPage();
        _mounted = true;
        // height/resize fallbacks in case the host DOM collapsed the container (black-map guard)
        setTimeout(function () {
          _forceMapSize();
          if (window._aevusMapInstance) { try { window._aevusMapInstance.resize(); } catch (e) {} }
        }, 600);
        console.log("[3dpad] award 3D-pad map mounted");
      } catch (e) { console.warn("[3dpad] mount failed", e); }
      _busy = false;
    }, 500);
  }
  window.addEventListener("hashchange", _mountIfNeeded);
  setInterval(_mountIfNeeded, 900);   // light poll for SPA nav; guarded by _mounted/_busy (no feedback loop)
  if (document.readyState !== "loading") _mountIfNeeded();
  else document.addEventListener("DOMContentLoaded", _mountIfNeeded);
})();

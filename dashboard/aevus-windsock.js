/* ============================================================================
 * Aevus — Map Windsock (live wind-direction instrument)
 *
 * A HUD windsock pinned to the Map page, wired TRUE to the wind:
 *   • DATA SOURCE: the backend /api/v1/weather endpoint — REAL Open-Meteo wind
 *     speed + direction for the site coordinates (not the random map widget). It
 *     also corrects the map's random Weather widget to the real values so the
 *     widget, topbar, and windsock all agree;
 *   • points the real geographic DOWNWIND direction — a real sock streams away
 *     from where the wind comes from (FROM-NW wind => sock streams to SE);
 *   • stays geographically correct relative to the map: it rotates by
 *     (windToward − mapBearing) and RE-rotates live as you rotate/orbit the map;
 *   • flutters, faster in stronger wind; brand teal + purple bands.
 *
 * SVG/DOM only (no WebGL) — works on every page state and is fully testable.
 * ========================================================================== */
(function () {
  "use strict";

  var WEATHER_MS = 60000;   // real weather changes slowly (backend caches ~10 min)
  // Compass FROM-direction (meteorological) -> degrees clockwise from North.
  var DIR_DEG = { N: 0, NE: 45, E: 90, SE: 135, S: 180, SW: 225, W: 270, NW: 315 };
  // 16-point compass (the /weather endpoint reports e.g. "SSE")
  var COMPASS16 = {
    N: 0, NNE: 22.5, NE: 45, ENE: 67.5, E: 90, ESE: 112.5, SE: 135, SSE: 157.5,
    S: 180, SSW: 202.5, SW: 225, WSW: 247.5, W: 270, WNW: 292.5, NW: 315, NNW: 337.5
  };
  var DEMO = (typeof window !== "undefined" && window.AEVUS_DEMO) || /demo=true/.test(location.search);
  var TEAL = "#06B6D4", PURPLE = "#6366F1";

  var _el = null;        // root (mounted on <body>, fixed)
  var _rotor = null;     // <g> that points to wind-toward dir
  var _compass = null;   // <g> N marker (rotates to true north)
  var _sock = null;      // sock group (flutter + speed-scale)
  var _label = null;
  var _wxTemp = null, _wxGust = null, _wxRH = null, _wxCond = null, _wxUpd = null;  // merged weather rows
  var _mounted = false;
  var _pollTimer = null;
  var _wind = { fromDeg: 0, mph: 0, dir: "N", gust: 0, temp: null, rh: null, cond: "", real: false };
  var _boundMap = null;
  var _userHidden = false;   // Layers-card "Weather" toggle state (controls this card)

  function onMapPage() {
    var h = (location.hash || "").toLowerCase();
    return h === "#map" || h.indexOf("map") !== -1;
  }

  function injectCSS() {
    if (document.getElementById("aws-windsock-css")) { return; }
    var st = document.createElement("style");
    st.id = "aws-windsock-css";
    st.textContent =
      "#aevus-windsock{position:fixed;z-index:30;width:160px;pointer-events:none;" +
      "font-family:Manrope,-apple-system,sans-serif;text-align:center;" +
      "filter:drop-shadow(0 4px 10px rgba(0,0,0,0.45));}" +
      "#aevus-windsock .ws-wrap{background:rgba(11,16,32,0.74);border:1px solid rgba(255,255,255,0.10);" +
      "border-radius:12px;padding:7px 9px 6px;backdrop-filter:blur(6px);}" +
      "#aevus-windsock svg.ws-dial{display:block;width:82px;height:82px;margin:0 auto;}" +
      "#aevus-windsock .ws-sock{transform-box:view-box;transform-origin:50px 50px;" +
      "animation:ws-flutter 2.2s ease-in-out infinite;}" +
      "@keyframes ws-flutter{0%{transform:rotate(-4deg)}50%{transform:rotate(4deg)}100%{transform:rotate(-4deg)}}" +
      "#aevus-windsock .ws-label{margin-top:1px;font-size:11px;font-weight:800;letter-spacing:0.3px;color:#E2E8F0;}" +
      "#aevus-windsock .ws-wx{margin-top:6px;border-top:1px solid rgba(255,255,255,0.10);padding-top:5px;text-align:left;}" +
      "#aevus-windsock .ws-wx-row{display:flex;align-items:center;gap:6px;font-size:10.5px;font-weight:600;" +
      "color:#CBD5E1;padding:1.5px 1px;line-height:1.2;}" +
      "#aevus-windsock .ws-wx-row svg{flex:0 0 auto;}" +
      "#aevus-windsock .ws-wx-alert{color:#10D478;font-weight:700;margin-top:2px;}" +
      "#aevus-windsock .ws-wx-upd{font-size:8px;font-weight:600;color:#4A5168;margin-top:4px;text-align:center;letter-spacing:0.3px;}" +
      "#aevus-windsock .ws-ntext{font:700 9px Manrope,sans-serif;fill:#94A3B8;}";
    document.head.appendChild(st);
  }

  // 4 tapered teal/purple bands streaming UP from the hub (default = north).
  function sockBands() {
    var bands = "", i, yBot, yTop, hwBot, hwTop, col;
    for (i = 0; i < 4; i++) {
      yBot = 50 - 9 * i; yTop = 50 - 9 * (i + 1);
      hwBot = 8 - 1.4 * i; hwTop = 8 - 1.4 * (i + 1);
      col = (i % 2 === 0) ? TEAL : PURPLE;
      bands += '<polygon points="' +
        (50 - hwBot) + "," + yBot + " " + (50 + hwBot) + "," + yBot + " " +
        (50 + hwTop) + "," + yTop + " " + (50 - hwTop) + "," + yTop +
        '" fill="' + col + '" stroke="rgba(255,255,255,0.25)" stroke-width="0.5"/>';
    }
    return bands;
  }

  function build() {
    injectCSS();
    var el = document.createElement("div");
    el.id = "aevus-windsock";
    el.setAttribute("role", "img");
    el.setAttribute("aria-label", "Wind direction");
    // thin-line weather row icons (strokeWidth 1.8, brand style — no emoji)
    var iTemp = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#EF4444" stroke-width="1.8"><path d="M10 13.5V5a2 2 0 0 1 4 0v8.5a3.5 3.5 0 1 1-4 0z"/></svg>';
    var iGust = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#0EA5E9" stroke-width="1.8" stroke-linecap="round"><path d="M3 8h11a2.5 2.5 0 1 0-2.5-2.5M3 14h15a2.5 2.5 0 1 1-2.5 2.5M3 11h8"/></svg>';
    var iCond = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#94A3B8" stroke-width="1.8"><path d="M6 17h11a4 4 0 0 0 0-8 5 5 0 0 0-9.6-1.3A3.5 3.5 0 0 0 6 17z"/></svg>';
    var iRH = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#60A5FA" stroke-width="1.8"><path d="M12 3c3 4 5 6.5 5 9.5A5 5 0 0 1 7 12.5C7 9.5 9 7 12 3z"/></svg>';
    el.innerHTML =
      '<div class="ws-wrap">' +
      '<svg class="ws-dial" viewBox="0 0 100 100">' +
        '<circle cx="50" cy="50" r="46" fill="none" stroke="rgba(255,255,255,0.10)" stroke-width="1"/>' +
        // compass N marker (rotates to true north)
        '<g class="ws-compass">' +
          '<path d="M50 4 L46 12 L54 12 Z" fill="#94A3B8"/>' +
          '<text class="ws-ntext" x="50" y="22" text-anchor="middle">N</text>' +
        '</g>' +
        // rotor -> points to wind-toward direction; sock flutters inside
        '<g class="ws-rotor">' +
          '<g class="ws-sock">' + sockBands() +
            '<ellipse cx="50" cy="50" rx="8" ry="2.6" fill="none" stroke="' + TEAL + '" stroke-width="1.4"/>' +
          '</g>' +
        '</g>' +
        '<circle cx="50" cy="50" r="3" fill="#E2E8F0"/>' +
      '</svg>' +
      '<div class="ws-label">CALM</div>' +
      // merged weather block (real /api/v1/weather data, windsock-card layout)
      '<div class="ws-wx">' +
        '<div class="ws-wx-row">' + iTemp + '<span class="ws-temp">--°F</span></div>' +
        '<div class="ws-wx-row">' + iGust + '<span class="ws-gust">steady</span></div>' +
        '<div class="ws-wx-row">' + iRH + '<span class="ws-rh">--% RH</span></div>' +
        '<div class="ws-wx-row">' + iCond + '<span class="ws-cond">—</span></div>' +
        '<div class="ws-wx-row ws-wx-alert"><span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:#10D478;margin-right:1px;"></span>No active NWS alerts</div>' +
        '<div class="ws-wx-upd">Updated —</div>' +
      '</div>' +
      '</div>';
    _rotor = el.querySelector(".ws-rotor");
    _compass = el.querySelector(".ws-compass");
    _sock = el.querySelector(".ws-sock");
    _label = el.querySelector(".ws-label");
    _wxTemp = el.querySelector(".ws-temp");
    _wxGust = el.querySelector(".ws-gust");
    _wxRH = el.querySelector(".ws-rh");
    _wxCond = el.querySelector(".ws-cond");
    _wxUpd = el.querySelector(".ws-wx-upd");
    return el;
  }

  // REAL data source: the backend /api/v1/weather endpoint (Open-Meteo for the
  // site coordinates) — temp_f, wind_mph, wind_gust_mph, wind_dir (16-pt compass).
  function fetchWeather() {
    var h = { Accept: "application/json" };
    if (DEMO) { h["X-Aevus-Demo"] = "true"; }
    return fetch("/api/v1/weather", { credentials: "same-origin", headers: h })
      .then(function (r) { if (!r.ok) { throw new Error("HTTP " + r.status); } return r.json(); })
      .then(function (d) {
        if (d && typeof d.wind_mph === "number") {
          _wind.mph = d.wind_mph;
          _wind.gust = d.wind_gust_mph || 0;
          _wind.dir = d.wind_dir || "";
          _wind.temp = (typeof d.temp_f === "number") ? d.temp_f : null;
          _wind.rh = (typeof d.humidity === "number") ? d.humidity : null;
          _wind.cond = d.condition || "";
          var deg = COMPASS16[_wind.dir];
          if (deg != null) { _wind.fromDeg = deg; }
          _wind.real = true;
          renderWx();
          hideLegend();   // merged into this card — retire the bottom-left weather panel
          update();
        }
      })
      .catch(function () { if (!_wind.real) { readWidget(); update(); } });
  }

  // Fallback only: parse the on-map Weather widget if the endpoint is unreachable.
  function readWidget() {
    try {
      var w = document.querySelector(".map-weather-legend");
      if (!w) { return; }
      var m = (w.textContent || "").match(/(\d+(?:\.\d+)?)\s*mph\s*(N|NE|E|SE|S|SW|W|NW)\b/i);
      if (m) {
        _wind.mph = parseFloat(m[1]) || 0;
        _wind.dir = m[2].toUpperCase();
        _wind.fromDeg = DIR_DEG[_wind.dir] != null ? DIR_DEG[_wind.dir] : 0;
      }
    } catch (e) {}
  }

  // Correct the map's bottom-left Weather widget (its temp/wind are client-random)
  // to the REAL values, so the widget, the topbar, and the windsock all agree.
  function syncWidget(d) {
    try {
      var w = document.querySelector(".map-weather-legend");
      if (!w) { return; }
      var rows = w.querySelectorAll(".wx-row");
      for (var i = 0; i < rows.length; i++) {
        var t = rows[i].textContent || "";
        if (/mph/i.test(t)) {
          rows[i].lastChild.textContent = " " + Math.round(d.wind_mph) + " mph " + (d.wind_dir || "");
        } else if (/°F/.test(t) && typeof d.temp_f === "number") {
          rows[i].lastChild.textContent = " " + Math.round(d.temp_f) + "°F";
        }
      }
    } catch (e) {}
  }

  // Populate the merged weather rows inside the windsock card (real /weather data).
  function renderWx() {
    if (_wxTemp) { _wxTemp.textContent = (_wind.temp != null ? Math.round(_wind.temp) : "--") + "°F"; }
    if (_wxGust) { _wxGust.textContent = (_wind.gust > _wind.mph + 1) ? ("gusts " + Math.round(_wind.gust) + " mph") : "steady"; }
    if (_wxRH) { _wxRH.textContent = (_wind.rh != null ? Math.round(_wind.rh) : "--") + "% RH"; }
    if (_wxCond) { _wxCond.textContent = _wind.cond ? (_wind.cond.charAt(0).toUpperCase() + _wind.cond.slice(1)) : "—"; }
    if (_wxUpd) { _wxUpd.textContent = "Updated " + new Date().toLocaleTimeString(); }
  }

  // Weather is now MERGED into this windsock card — retire the bottom-left panel.
  function hideLegend() {
    try { var w = document.querySelector(".map-weather-legend"); if (w) { w.style.display = "none"; } } catch (e) {}
  }

  function bearing() {
    try { return _boundMap && _boundMap.getBearing ? _boundMap.getBearing() : 0; } catch (e) { return 0; }
  }

  function update() {
    if (!_el) { return; }
    var b = bearing();
    var toward = (_wind.fromDeg + 180) % 360;        // a sock streams DOWNWIND
    // screen rotation = geographic bearing − map bearing (keeps it true as the map orbits)
    var rot = toward - b;
    var nRot = -b;
    if (_rotor) { _rotor.setAttribute("transform", "rotate(" + rot.toFixed(1) + " 50 50)"); }
    if (_compass) { _compass.setAttribute("transform", "rotate(" + nRot.toFixed(1) + " 50 50)"); }
    if (_sock) {
      // flutter faster in stronger wind (the speed cue); calm = slow, lazy sway
      var mph = _wind.mph;
      _sock.style.animationDuration = (mph > 1 ? Math.max(0.9, 2.6 - mph * 0.06) : 3.4) + "s";
    }
    if (_label) {
      _label.textContent = (_wind.mph <= 1) ? "CALM" : (_wind.dir + " · " + Math.round(_wind.mph) + " mph");
    }
  }

  function reposition() {
    if (!_el) { return; }
    var map = window._aevusMapInstance;
    var c = map && typeof map.getContainer === "function" ? map.getContainer() : null;
    if (!c) { return; }
    var r = c.getBoundingClientRect();
    if (r.width < 40) { return; }
    // top-right of the map area, above the zoom controls
    _el.style.left = Math.round(r.right - 160 - 12) + "px";
    _el.style.top = Math.round(r.top + 14) + "px";
  }

  function bindMap() {
    var map = window._aevusMapInstance;
    if (!map || _boundMap === map) { return; }
    _boundMap = map;
    try {
      map.on("rotate", update);
      map.on("move", update);     // covers drag-rotate + pitch
      map.on("moveend", update);
    } catch (e) {}
  }

  function ensureMounted() {
    var map = window._aevusMapInstance;
    if (!map || typeof map.getContainer !== "function" || !map.getContainer()) { return false; }
    if (_mounted && _el && _el.isConnected) { return true; }
    if (!_el) { _el = build(); }
    if (_el.parentNode !== document.body) { document.body.appendChild(_el); }
    _mounted = true;
    bindMap();
    reposition();
    return true;
  }

  function setVisible(on) { if (_el) { _el.style.display = on ? "block" : "none"; } }

  // The Layers card "Weather" toggle (#lyr-weather) used to show/hide the old
  // bottom-left weather widget — now merged into this card, so repoint it here.
  function hookLayerToggle() {
    var cb = document.getElementById("lyr-weather");
    if (!cb || cb._wsHooked) { return; }
    cb._wsHooked = true;
    _userHidden = !cb.checked;
    cb.addEventListener("change", function () {
      _userHidden = !this.checked;
      setVisible(!_userHidden);
      hideLegend();   // keep the merged-away legend hidden regardless
    });
  }

  function tick() {
    if (onMapPage()) {
      if (ensureMounted()) {
        hookLayerToggle();
        setVisible(!_userHidden);
        if (!_pollTimer) { fetchWeather(); _pollTimer = setInterval(fetchWeather, WEATHER_MS); }
      }
    } else {
      setVisible(false);
      if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null; }
    }
  }

  setInterval(tick, 1000);
  window.addEventListener("resize", reposition);
  window.addEventListener("hashchange", tick);

  window.AevusWindsock = {
    wind: function () { return { dir: _wind.dir, mph: _wind.mph, fromDeg: _wind.fromDeg, towardDeg: (_wind.fromDeg + 180) % 360, mapBearing: bearing() }; },
    refresh: function () { fetchWeather(); },
    // manual override for testing/demo: set wind FROM compass + speed
    set: function (dir, mph) { if (DIR_DEG[dir] != null) { _wind.dir = dir; _wind.fromDeg = DIR_DEG[dir]; } if (mph != null) { _wind.mph = mph; } update(); }
  };

  console.log("[windsock] module loaded");
})();

/* ============================================================================
 * Aevus — Map Windsock (live wind-direction instrument)
 *
 * A HUD windsock pinned to the Map page, wired TRUE to the wind:
 *   • reads the live wind (dir + speed) from the on-map Weather widget, so the
 *     sock and the widget always agree;
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

  var POLL_MS = 2000;
  // Compass FROM-direction (meteorological) -> degrees clockwise from North.
  var DIR_DEG = { N: 0, NE: 45, E: 90, SE: 135, S: 180, SW: 225, W: 270, NW: 315 };
  var TEAL = "#06B6D4", PURPLE = "#6366F1";

  var _el = null;        // root (mounted on <body>, fixed)
  var _rotor = null;     // <g> that points to wind-toward dir
  var _compass = null;   // <g> N marker (rotates to true north)
  var _sock = null;      // sock group (flutter + speed-scale)
  var _label = null;
  var _mounted = false;
  var _pollTimer = null;
  var _wind = { fromDeg: 0, mph: 0, dir: "N" };
  var _boundMap = null;

  function onMapPage() {
    var h = (location.hash || "").toLowerCase();
    return h === "#map" || h.indexOf("map") !== -1;
  }

  function injectCSS() {
    if (document.getElementById("aws-windsock-css")) { return; }
    var st = document.createElement("style");
    st.id = "aws-windsock-css";
    st.textContent =
      "#aevus-windsock{position:fixed;z-index:30;width:96px;pointer-events:none;" +
      "font-family:Manrope,-apple-system,sans-serif;text-align:center;" +
      "filter:drop-shadow(0 4px 10px rgba(0,0,0,0.45));}" +
      "#aevus-windsock .ws-wrap{background:rgba(11,16,32,0.72);border:1px solid rgba(255,255,255,0.10);" +
      "border-radius:12px;padding:6px 6px 5px;backdrop-filter:blur(6px);}" +
      "#aevus-windsock svg{display:block;width:84px;height:84px;margin:0 auto;}" +
      "#aevus-windsock .ws-sock{transform-box:view-box;transform-origin:50px 50px;" +
      "animation:ws-flutter 2.2s ease-in-out infinite;}" +
      "@keyframes ws-flutter{0%{transform:rotate(-4deg)}50%{transform:rotate(4deg)}100%{transform:rotate(-4deg)}}" +
      "#aevus-windsock .ws-label{margin-top:2px;font-size:10px;font-weight:800;letter-spacing:0.4px;color:#E2E8F0;}" +
      "#aevus-windsock .ws-sub{font-size:8px;font-weight:700;letter-spacing:0.6px;text-transform:uppercase;color:#94A3B8;}" +
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
    el.innerHTML =
      '<div class="ws-wrap">' +
      '<svg viewBox="0 0 100 100">' +
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
      '<div class="ws-sub">WIND</div>' +
      '</div>';
    _rotor = el.querySelector(".ws-rotor");
    _compass = el.querySelector(".ws-compass");
    _sock = el.querySelector(".ws-sock");
    _label = el.querySelector(".ws-label");
    return el;
  }

  // Parse the on-map Weather widget: "<n> mph <DIR>".
  function readWind() {
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
    _el.style.left = Math.round(r.right - 96 - 12) + "px";
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

  function tick() {
    if (onMapPage()) {
      if (ensureMounted()) {
        setVisible(true);
        if (!_pollTimer) { readWind(); update(); _pollTimer = setInterval(function () { readWind(); update(); }, POLL_MS); }
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
    refresh: function () { readWind(); update(); },
    // manual override for testing/demo: set wind FROM compass + speed
    set: function (dir, mph) { if (DIR_DEG[dir] != null) { _wind.dir = dir; _wind.fromDeg = DIR_DEG[dir]; } if (mph != null) { _wind.mph = mph; } update(); }
  };

  console.log("[windsock] module loaded");
})();

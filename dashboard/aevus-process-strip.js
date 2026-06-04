/* ============================================================================
 * Aevus — Maps-page Process Strip
 *
 * A slim, live process-flow strip pinned to the bottom of the Maps page. It
 * polls the backend twin process snapshot (the SOURCE of truth) and renders
 * per-stage engineering readings + the sales summary.
 *
 *   SOURCE:  GET /api/v1/twin/facility/<id>/process   (src/api/twin.py)
 *            -> physically-consistent SIMULATED wellsite snapshot, demo-gated.
 *            Poll-driven; gentle drift so values move live.
 *
 * Wellhead → Separator → Compressor → Tank Farm → Metering → Sales
 *
 * Self-mounts into the MapLibre container the moment the Maps page is active;
 * hides itself on every other page. No build step — vanilla JS, brand-aligned
 * (thin-line SVG icons, JetBrains Mono numerics, status-dot semantics).
 * ========================================================================== */
(function () {
  "use strict";

  var FACILITY = "killdeer";
  var POLL_MS = 5000;
  var ENDPOINT = "/api/v1/twin/facility/" + FACILITY + "/process";

  var COL = { good: "#10D478", warn: "#FBBF24", bad: "#EF4444", unknown: "#64748B", accent: "#22D3EE" };

  // Which two readings each stage promotes to the slim card (others kept in
  // the snapshot for the faceplate/L2 views). Labels match the backend.
  var PRIMARY = {
    wellhead: ["TBG", "CSG"],
    separator: ["PRESS", "LEVEL"],
    compressor: ["DISCH", "RPM"],
    tankfarm: ["OIL", "WATER"],
    metering: ["RATE", "TOTAL"]
  };

  // Thin-line SVG glyphs (strokeWidth 1.8, no fill) per stage.
  var ICON = {
    wellhead: '<path d="M12 21V9M8 9h8M9 6h6M12 6V3M6.5 13.5l-2 2M17.5 13.5l2 2"/>',
    separator: '<rect x="3" y="8" width="18" height="8" rx="4"/><path d="M12 4v4M9 16v3M15 16v3"/>',
    compressor: '<rect x="4" y="6" width="11" height="12" rx="2"/><circle cx="9.5" cy="12" r="2.6"/><path d="M15 9h4M15 15h4M19 7v10"/>',
    tankfarm: '<path d="M5 20V9a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v11M13 20v-8a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v8M5 11h6M13 13h6"/>',
    metering: '<circle cx="12" cy="12" r="8"/><path d="M12 12l4-3M12 6v1M18 12h-1M12 18v-1M6 12h1"/>'
  };

  var STAGE_ORDER = ["wellhead", "separator", "compressor", "tankfarm", "metering"];

  var _strip = null;       // root DOM node
  var _mounted = false;
  var _pollTimer = null;
  var _lastData = null;
  var _stale = false;

  function onMapPage() {
    var h = (location.hash || "").toLowerCase();
    return h === "#map" || h.indexOf("map") !== -1;
  }

  function injectCSS() {
    if (document.getElementById("aps-css")) { return; }
    var st = document.createElement("style");
    st.id = "aps-css";
    st.textContent =
      // Pinned to the VIEWPORT bottom (not the map container, which can be taller
      // than the viewport and would push the strip below the fold). left/width are
      // set in JS from the map container rect so it stays aligned to the map area.
      "#aevus-proc-strip{position:fixed;bottom:14px;left:12px;right:12px;z-index:30;" +
      "display:flex;align-items:stretch;gap:0;overflow-x:auto;overflow-y:hidden;" +
      "padding:8px 10px;border-radius:14px;font-family:Manrope,-apple-system,sans-serif;" +
      "background:linear-gradient(180deg,rgba(11,16,32,0.82),rgba(11,16,32,0.92));" +
      "border:1px solid rgba(255,255,255,0.09);backdrop-filter:blur(7px);" +
      "box-shadow:0 8px 28px rgba(0,0,0,0.45);scrollbar-width:none;transition:opacity .3s;}" +
      "#aevus-proc-strip::-webkit-scrollbar{display:none;}" +
      "#aevus-proc-strip.aps-stale{opacity:0.55;}" +
      ".aps-stage{flex:1 1 0;min-width:118px;display:flex;flex-direction:column;gap:5px;padding:2px 6px;}" +
      ".aps-head{display:flex;align-items:center;gap:6px;}" +
      ".aps-ico{width:18px;height:18px;flex:0 0 auto;color:rgba(148,163,184,0.9);}" +
      ".aps-ico svg{width:18px;height:18px;display:block;}" +
      ".aps-name{font-size:9px;font-weight:800;letter-spacing:0.7px;text-transform:uppercase;color:#CBD5E1;white-space:nowrap;}" +
      ".aps-dot{width:7px;height:7px;border-radius:50%;flex:0 0 auto;margin-left:auto;box-shadow:0 0 6px currentColor;}" +
      ".aps-reads{display:flex;gap:10px;}" +
      ".aps-rd{display:flex;flex-direction:column;line-height:1.05;}" +
      ".aps-val{font-family:'JetBrains Mono',ui-monospace,monospace;font-size:14px;font-weight:700;color:#F1F5F9;letter-spacing:-0.4px;}" +
      ".aps-unit{font-size:7px;font-weight:700;letter-spacing:0.4px;color:#64748B;text-transform:uppercase;margin-top:1px;}" +
      ".aps-arrow{flex:0 0 auto;display:flex;align-items:center;color:rgba(34,211,238,0.55);padding:0 2px;}" +
      ".aps-sales{flex:0 0 auto;display:flex;flex-direction:column;justify-content:center;gap:2px;padding:2px 12px 2px 10px;" +
      "border-left:1px solid rgba(255,255,255,0.10);margin-left:4px;}" +
      ".aps-sales-lab{font-size:8px;font-weight:800;letter-spacing:1px;color:var(--accent,#22D3EE);text-transform:uppercase;}" +
      ".aps-sales-oil{font-family:'JetBrains Mono',ui-monospace,monospace;font-size:18px;font-weight:800;color:#F8FAFC;letter-spacing:-0.5px;}" +
      ".aps-sales-sub{font-size:9px;font-weight:600;color:#94A3B8;font-family:'JetBrains Mono',ui-monospace,monospace;}" +
      "@media(max-width:640px){.aps-stage{min-width:104px;}.aps-name{font-size:8px;}.aps-val{font-size:12px;}}";
    document.head.appendChild(st);
  }

  function svgIcon(stageId) {
    return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" ' +
      'stroke-linecap="round" stroke-linejoin="round">' + (ICON[stageId] || "") + "</svg>";
  }

  function fmt(v) {
    if (v === null || v === undefined || isNaN(v)) { return "—"; }
    // big accumulators get thousands separators; everything else 1dp
    if (Math.abs(v) >= 10000) { return Math.round(v).toLocaleString("en-US"); }
    return (Math.round(v * 10) / 10).toFixed(1);
  }

  function build() {
    injectCSS();
    var el = document.createElement("div");
    el.id = "aevus-proc-strip";
    el.setAttribute("role", "group");
    el.setAttribute("aria-label", "Live process flow");
    return el;
  }

  // Keep the (viewport-pinned) strip horizontally aligned to the map area — match
  // the map container's left edge + width so it clears the left nav / panels.
  function reposition() {
    if (!_strip) { return; }
    var map = window._aevusMapInstance;
    var c = map && typeof map.getContainer === "function" ? map.getContainer() : null;
    if (!c) { return; }
    var r = c.getBoundingClientRect();
    if (r.width < 40) { return; }
    _strip.style.left = Math.round(r.left + 12) + "px";
    _strip.style.right = "auto";
    _strip.style.width = Math.round(r.width - 24) + "px";
  }

  function readingsFor(stage) {
    var want = PRIMARY[stage.id] || [];
    var byLabel = {};
    (stage.readings || []).forEach(function (r) { byLabel[r.label] = r; });
    return want.map(function (lab) { return byLabel[lab]; }).filter(Boolean);
  }

  function render(data) {
    if (!_strip) { return; }
    _strip.classList.toggle("aps-stale", !!_stale);
    if (!data) { return; }
    var stagesById = {};
    (data.stages || []).forEach(function (s) { stagesById[s.id] = s; });

    var html = "";
    for (var i = 0; i < STAGE_ORDER.length; i++) {
      var s = stagesById[STAGE_ORDER[i]];
      if (!s) { continue; }
      var dot = COL[s.status] || COL.unknown;
      var reads = readingsFor(s);
      var rhtml = reads.map(function (r) {
        var u = r.unit ? r.unit : (r.label === "RPM" ? "rpm" : "");
        return '<div class="aps-rd"><span class="aps-val">' + fmt(r.value) +
          '</span><span class="aps-unit">' + (r.label + (u ? " " + u : "")) + "</span></div>";
      }).join("");
      html +=
        '<div class="aps-stage">' +
          '<div class="aps-head"><span class="aps-ico">' + svgIcon(s.id) + "</span>" +
            '<span class="aps-name">' + s.name + "</span>" +
            '<span class="aps-dot" style="color:' + dot + ';background:' + dot + '"></span></div>' +
          '<div class="aps-reads">' + rhtml + "</div>" +
        "</div>";
      if (i < STAGE_ORDER.length - 1) {
        html += '<div class="aps-arrow"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" ' +
          'stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">' +
          '<path d="M5 12h13M13 6l6 6-6 6"/></svg></div>';
      }
    }

    var sales = data.sales || {};
    html += '<div class="aps-sales">' +
      '<span class="aps-sales-lab">→ Sales</span>' +
      '<span class="aps-sales-oil">' + fmt(sales.oil_bopd) + ' <span style="font-size:10px;color:#94A3B8;">BOPD</span></span>' +
      '<span class="aps-sales-sub">' + fmt(sales.gas_mcfd) + " MCFD · " + fmt(sales.water_bwpd) + " BWPD</span>" +
      "</div>";

    _strip.innerHTML = html;
    reposition();
  }

  function ensureMounted() {
    var map = window._aevusMapInstance;
    if (!map || typeof map.getContainer !== "function") { return false; }
    if (_mounted && _strip && _strip.isConnected) { return true; }
    try {
      var container = map.getContainer();
      if (!container) { return false; }
      if (!_strip) { _strip = build(); }
      // Append to <body>, NOT the map container: MapLibre puts a CSS transform on
      // the map's ancestor chain, and a transformed ancestor makes position:fixed
      // resolve against THAT element instead of the viewport (strip landed below
      // the fold + shifted right). In <body> the fixed positioning is true to the
      // viewport; reposition() then aligns left/width to the map's viewport rect.
      if (_strip.parentNode !== document.body) { document.body.appendChild(_strip); }
      _mounted = true;
      if (_lastData) { render(_lastData); }
      return true;
    } catch (e) { return false; }
  }

  function setVisible(on) {
    if (_strip) { _strip.style.display = on ? "flex" : "none"; }
  }

  function poll() {
    if (document.hidden || !onMapPage()) { return; }
    var ctrl = new AbortController();
    var to = setTimeout(function () { ctrl.abort(); }, 4500);
    fetch(ENDPOINT, {
      credentials: "same-origin",
      headers: { "X-Aevus-Demo": "true", "Accept": "application/json" },
      signal: ctrl.signal
    })
      .then(function (r) { if (!r.ok) { throw new Error("HTTP " + r.status); } return r.json(); })
      .then(function (d) { clearTimeout(to); _lastData = d; _stale = false; render(d); })
      .catch(function () { clearTimeout(to); _stale = true; render(_lastData); });
  }

  function startPolling() {
    if (_pollTimer) { return; }
    poll();
    _pollTimer = setInterval(poll, POLL_MS);
  }
  function stopPolling() {
    if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null; }
  }

  // Supervisor: keep the strip mounted + visibility synced to the active page,
  // and only poll while the Maps page is actually showing.
  function tick() {
    if (onMapPage()) {
      if (ensureMounted()) {
        setVisible(true);
        reposition();
        startPolling();
      }
    } else {
      setVisible(false);
      stopPolling();
    }
  }

  setInterval(tick, 1000);
  window.addEventListener("resize", reposition);
  window.addEventListener("hashchange", tick);
  document.addEventListener("visibilitychange", function () { if (!document.hidden) { poll(); } });

  window.AevusProcessStrip = {
    refresh: function () { poll(); },
    data: function () { return _lastData; },
    _debug: function () { return { mounted: _mounted, stale: _stale, onMap: onMapPage() }; }
  };

  console.log("[proc-strip] module loaded — polling " + ENDPOINT);
})();

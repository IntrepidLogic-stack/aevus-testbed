/* ============================================================================
 * Aevus — Spline Digital-Twin Binding Harness (Path B)
 *
 * Turns a Spline scene (the photoreal "body") into a real digital twin by
 * binding LIVE server data to it at runtime, joined by object NAME = asset ID.
 * Implements the contract in docs/SPLINE_TWIN_AUTHORING_CONTRACT.md §8:
 *   1. Load the .splinecode scene into a <canvas> on the Map page "3D View".
 *   2. findObjectByName(ID) per asset -> drive status (emissive / Spline var).
 *   3. Poll /twin/flow -> per-segment pipe flow + color (normalized 0..1).
 *   4. Project each <ID>_anchor -> screen -> pin the live HTML data card.
 *
 * Trade-secret + IL-9000 unchanged: only normalized flow + coarse status reach
 * the client; the twin is read-only/advisory and never commands a device.
 *
 * ── DORMANT BY DEFAULT ──────────────────────────────────────────────────────
 * No scene has been exported yet, so this harness does NOTHING until a scene
 * URL is provided. To ACTIVATE once you've exported from Spline (Export -> Code
 * -> .splinecode URL):
 *   1. Set the URL — either:
 *        window.AEVUS_SPLINE_URL = "https://prod.spline.design/XXXX/scene.splinecode";
 *      (before this script runs) OR edit SCENE_URL below.
 *   2. Add a mount point on the Map page: <div id="aevus-spline-mount"></div>
 *   3. Add the script tag in Aevus_Console.html and (if the CSP blocks the
 *      unpkg ESM) vendor @splinetool/runtime locally and point RUNTIME_URL at it.
 *   4. Name Spline objects per the contract: WH, CMP, HTR, …, PWR, plus
 *      <ID>_anchor empties and (optionally) <ID>_status Spline variables.
 * ========================================================================== */
(function () {
  "use strict";

  // ── Config ────────────────────────────────────────────────────────────────
  var SCENE_URL = (typeof window !== "undefined" && window.AEVUS_SPLINE_URL) || null;
  // ESM build of the vanilla runtime. If the dashboard CSP blocks cross-origin
  // module imports, vendor this file into /dashboard and set RUNTIME_URL local.
  var RUNTIME_URL = (typeof window !== "undefined" && window.AEVUS_SPLINE_RUNTIME) ||
    "https://unpkg.com/@splinetool/runtime@1.9.28/build/runtime.js";
  var MOUNT_ID = "aevus-spline-mount";
  var POLL_MS = 5000;

  // Canonical asset IDs (match src/api/twin.py topology + the asset registry).
  var ASSET_IDS = ["WH", "CMP", "HTR", "CHE", "SEP", "FLR", "OT1", "OT2", "PWT", "EFM", "RTU", "TWR", "PWR", "SOL", "COM"];

  // Status -> emissive color (contract §4). Hex ints for three/Spline material.
  var EMISSIVE = { good: 0x06b6d4, warn: 0xfbbf24, bad: 0xef4444, offline: 0x334155, unknown: 0x334155 };
  var INTENSITY = { good: 0.25, warn: 0.6, bad: 0.9, offline: 0.05, unknown: 0.05 };

  var DEMO = (typeof window !== "undefined" && window.AEVUS_DEMO) || /demo=true/.test(location.search);
  var API = {
    assets: "/api/v1/assets",
    flow: "/api/v1/twin/facility/killdeer/flow"
  };

  var _app = null;       // Spline Application instance
  var _canvas = null;
  var _objs = {};        // id -> Spline object handle (cached)
  var _anchors = {};     // id -> anchor object handle
  var _cards = {};       // id -> HTML card element
  var _pollTimer = null;
  var _rafId = 0;
  var _loaded = false;
  var _loading = false;

  function log() { try { console.log.apply(console, ["[spline-twin]"].concat([].slice.call(arguments))); } catch (e) {} }

  function apiFetch(url) {
    var headers = { Accept: "application/json" };
    if (DEMO) { headers["X-Aevus-Demo"] = "true"; }
    return fetch(url, { credentials: "same-origin", headers: headers })
      .then(function (r) { if (!r.ok) { throw new Error("HTTP " + r.status); } return r.json(); });
  }

  // ── Runtime load (dynamic ESM import; dormant unless SCENE_URL set) ──────────
  function loadRuntime() {
    // Use a Function wrapper so the dynamic import() doesn't trip older parsers
    // when the harness is shipped dormant.
    return new Function("u", "return import(u)")(RUNTIME_URL)
      .then(function (mod) { return mod.Application || (mod.default && mod.default.Application); });
  }

  function ensureMount() {
    var host = document.getElementById(MOUNT_ID);
    if (!host) { return null; }
    if (!_canvas) {
      _canvas = document.createElement("canvas");
      _canvas.id = "aevus-spline-canvas";
      _canvas.style.cssText = "width:100%;height:100%;display:block;";
      host.appendChild(_canvas);
    }
    return _canvas;
  }

  function init() {
    if (_loading || _loaded || !SCENE_URL) { return; }
    var canvas = ensureMount();
    if (!canvas) { return; }   // no mount point on the page yet
    _loading = true;
    log("loading scene", SCENE_URL);
    loadRuntime()
      .then(function (Application) {
        if (!Application) { throw new Error("runtime missing Application export"); }
        _app = new Application(canvas);
        return _app.load(SCENE_URL);
      })
      .then(function () {
        _loaded = true; _loading = false;
        cacheObjects();
        buildCards();
        startPolling();
        startProjection();
        log("scene loaded — bound", Object.keys(_objs).length, "assets");
      })
      .catch(function (e) {
        _loading = false;
        log("load failed:", e && e.message, "(CSP may be blocking the runtime ESM — vendor it and set window.AEVUS_SPLINE_RUNTIME)");
      });
  }

  function cacheObjects() {
    ASSET_IDS.forEach(function (id) {
      try {
        var o = _app.findObjectByName(id);
        if (o) { _objs[id] = o; }
        var a = _app.findObjectByName(id + "_anchor");
        if (a) { _anchors[id] = a; }
      } catch (e) {}
    });
  }

  // ── Status binding (contract §4) ────────────────────────────────────────────
  // Prefer a Spline Variable "<ID>_status" (drives a scene state-machine if the
  // author wired one); always also attempt to set the object's emissive so it
  // works whether or not variables exist.
  function applyStatus(byId) {
    ASSET_IDS.forEach(function (id) {
      var a = byId[id] || null;
      var status = a ? (a.status === "bad" ? "bad" : a.status === "warn" ? "warn" : a.status === "offline" ? "offline" : "good") : "unknown";
      // (a) Spline variable hook
      try { if (_app && _app.setVariable) { _app.setVariable(id + "_status", status); } } catch (e) {}
      // (b) emissive on the object's material (best-effort across runtime versions)
      var o = _objs[id];
      if (o) {
        try {
          var col = EMISSIVE[status], it = INTENSITY[status];
          if (o.emissiveColor !== undefined) { o.emissiveColor = col; }
          if (o.material && o.material.emissive !== undefined) { o.material.emissive = col; }
          if (o.emissiveIntensity !== undefined) { o.emissiveIntensity = it; }
        } catch (e2) {}
      }
    });
  }

  // ── Flow binding (contract §3, normalized 0..1 only) ────────────────────────
  function applyFlow(frame) {
    var segs = (frame && frame.segments) || [];
    segs.forEach(function (s) {
      // Per-segment Spline variables, if the author named pipe runs by edge id.
      try {
        if (_app && _app.setVariable) {
          _app.setVariable(s.id + "_flow", Math.max(0, Math.min(1, s.flow || 0)));
          _app.setVariable(s.id + "_status", s.status || "good");
        }
      } catch (e) {}
    });
  }

  // ── Live data cards (contract §2 + §8.4) ────────────────────────────────────
  function buildCards() {
    if (document.getElementById("aps-spline-card-css")) { return; }
    var st = document.createElement("style");
    st.id = "aps-spline-card-css";
    st.textContent =
      ".sp-card{position:absolute;transform:translate(-50%,-110%);pointer-events:none;z-index:6;" +
      "background:rgba(11,17,32,0.86);border:1px solid rgba(6,182,212,0.4);border-radius:10px;" +
      "padding:7px 10px;font-family:Manrope,-apple-system,sans-serif;color:#E2E8F0;min-width:120px;" +
      "backdrop-filter:blur(6px);box-shadow:0 6px 20px rgba(0,0,0,0.5);display:none;}" +
      ".sp-card-name{font-size:9px;font-weight:800;letter-spacing:0.5px;text-transform:uppercase;color:#94A3B8;}" +
      ".sp-card-rows{display:flex;flex-direction:column;gap:1px;margin-top:3px;}" +
      ".sp-card-row{display:flex;justify-content:space-between;gap:10px;font-size:11px;}" +
      ".sp-card-row span:first-child{color:#94A3B8;}" +
      ".sp-card-row span:last-child{font-family:'JetBrains Mono',ui-monospace,monospace;font-weight:700;}";
    document.head.appendChild(st);
  }

  function updateCards(byId) {
    var host = document.getElementById(MOUNT_ID);
    if (!host) { return; }
    ASSET_IDS.forEach(function (id) {
      if (!_anchors[id]) { return; }   // only assets that authored an anchor get a card
      var card = _cards[id];
      if (!card) {
        card = document.createElement("div");
        card.className = "sp-card";
        host.appendChild(card);
        _cards[id] = card;
      }
      var a = byId[id];
      if (!a) { card.style.display = "none"; return; }
      var vitals = (a.vitals || []).slice(0, 3);
      card.innerHTML = '<div class="sp-card-name">' + (a.name || id) + "</div>" +
        '<div class="sp-card-rows">' + vitals.map(function (v) {
          return '<div class="sp-card-row"><span>' + v.label + "</span><span>" + v.value + "</span></div>";
        }).join("") + "</div>";
    });
  }

  // Project each anchor's world position to screen and pin its card. The vanilla
  // runtime abstracts three.js, so we probe for a projection path defensively;
  // finalize against the real scene once exported.
  function startProjection() {
    cancelAnimationFrame(_rafId);
    function frame() {
      var host = document.getElementById(MOUNT_ID);
      if (host && _app) {
        ASSET_IDS.forEach(function (id) {
          var anchor = _anchors[id], card = _cards[id];
          if (!anchor || !card) { return; }
          var sp = screenOf(anchor);
          if (sp) { card.style.left = sp.x + "px"; card.style.top = sp.y + "px"; card.style.display = "block"; }
        });
      }
      _rafId = requestAnimationFrame(frame);
    }
    _rafId = requestAnimationFrame(frame);
  }

  // Best-effort world->screen for a Spline object. Returns {x,y} in mount-local
  // px or null if the runtime doesn't expose a usable camera/renderer.
  function screenOf(obj) {
    try {
      if (obj.screenPosition) { return obj.screenPosition; }          // some runtime versions
      var cam = _app && (_app._camera || (_app._scene && _app._scene.camera));
      var rend = _app && (_app._renderer || _app.renderer);
      if (cam && rend && obj.position && typeof obj.position.clone === "function" && window.THREE) {
        var v = obj.position.clone().project(cam);
        var rect = _canvas.getBoundingClientRect();
        return { x: (v.x * 0.5 + 0.5) * rect.width, y: (-v.y * 0.5 + 0.5) * rect.height };
      }
    } catch (e) {}
    return null;   // projection needs the real scene — cards stay hidden until then
  }

  // ── Polling ─────────────────────────────────────────────────────────────────
  function poll() {
    if (!_loaded || document.hidden) { return; }
    apiFetch(API.assets).then(function (data) {
      var list = Array.isArray(data) ? data : (data && data.assets) || [];
      var byId = {};
      list.forEach(function (a) { if (a && a.id) { byId[a.id] = a; } });
      applyStatus(byId);
      updateCards(byId);
    }).catch(function () {});
    apiFetch(API.flow).then(applyFlow).catch(function () {});
  }
  function startPolling() {
    if (_pollTimer) { return; }
    poll();
    _pollTimer = setInterval(poll, POLL_MS);
  }

  function destroy() {
    if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null; }
    cancelAnimationFrame(_rafId);
    try { if (_app && _app.dispose) { _app.dispose(); } } catch (e) {}
    _app = null; _loaded = false; _loading = false; _objs = {}; _anchors = {};
  }

  // ── Public API ──────────────────────────────────────────────────────────────
  window.AevusSplineTwin = {
    // Activate at runtime without editing this file:
    //   AevusSplineTwin.load("https://prod.spline.design/XXX/scene.splinecode")
    load: function (url, runtimeUrl) {
      if (url) { SCENE_URL = url; }
      if (runtimeUrl) { RUNTIME_URL = runtimeUrl; }
      destroy();
      init();
    },
    destroy: destroy,
    refresh: poll,
    status: function () {
      return { sceneUrl: SCENE_URL, loaded: _loaded, bound: Object.keys(_objs).length, anchors: Object.keys(_anchors).length };
    }
  };

  // Auto-init only if a scene URL was pre-set; otherwise stay fully dormant.
  if (SCENE_URL) {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", init);
    } else {
      init();
    }
    // also retry once the mount appears (e.g. user opens the 3D View tab)
    var _mountWatch = setInterval(function () {
      if (_loaded || _loading) { clearInterval(_mountWatch); return; }
      if (document.getElementById(MOUNT_ID)) { init(); }
    }, 1000);
  } else {
    log("dormant — set window.AEVUS_SPLINE_URL or call AevusSplineTwin.load(url) once a .splinecode is exported");
  }
})();

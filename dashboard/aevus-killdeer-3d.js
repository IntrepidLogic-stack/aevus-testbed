/* ============================================================================
 * aevus-killdeer-3d.js  —  KILLDEER FIELD · HIGH-FIDELITY 3D FACILITY  (2026-06-03)
 * ----------------------------------------------------------------------------
 * Renders the BlueJay/Killdeer pad as a true Three.js 3D process facility on
 * top of the live MapLibre base map: real equipment geometry (wellhead,
 * separator, compressor, oil + water tanks, flare, EFM skid, radio tower) and
 * COLORED process pipes carrying animated flow packets. Pipe colors follow the
 * platform legend — Oil #10D478 · Gas #F59E0B · Water #3B82F6 · Chemical #A855F7.
 *
 * It does NOT build its own map. It attaches a MapLibre `custom` 3D layer to
 * the existing award map instance (window._aevusMapInstance), and hides the old
 * boxy fill-extrusion pad via window._toggle3dBuildings(false). That keeps the
 * real basemap + camera + RF rings + roads, and swaps only the pad rendering.
 *
 * Lessons applied (the headaches): no ASI-fragile patterns, idempotent mount,
 * loop-safe re-attach on map remount, MapLibre layer hardening, vendored THREE
 * (no CDN-404 risk). Flow packets are live-flow-ready — Phase 3 drives speed +
 * color from real natural-gas process telemetry via AevusKilldeer3D.setFlow().
 *
 * Public API (window.AevusKilldeer3D):
 *   .setFlow(segId, {rate, state})  — Phase 3 hook: drive a pipe's flow
 *   .remount()                      — force re-attach
 *   ._segments                      — live segment registry (debug)
 * ========================================================================== */
(function () {
  "use strict";
  if (window.__aevusKilldeer3D) { return; }
  window.__aevusKilldeer3D = true;

  // ── CONFIG ────────────────────────────────────────────────────────────────
  var ORIGIN = [-95.8685, 29.3396];            // award pad center (lng,lat)
  var LAYER_ID = "killdeer-3d";
  // Camera framing that centers the equipment cluster (origin is the SW corner).
  var FRAME = { center: [-95.867718, 29.339562], zoom: 20.143, pitch: 59.5, bearing: 32 };

  // Bottom framing padding (~12% of the MAP CANVAS height) that lifts the facility
  // to vertical center under the 55° pitch. The pad is fraction-of-canvas so the
  // facility holds the SAME RELATIVE screen position at any canvas size — that's
  // what keeps it put when the canvas makes a real, lasting resize (the loader
  // overlay clearing / panels settling / api-client's ~3s map.resize()).
  //
  // The trap to avoid: the canvas clientHeight briefly reads 0/tiny during early
  // load — recomputing the pad from those transient values jumped the facility
  // (the original "shifts down" flicker). So we track the LAST GOOD (>200px)
  // canvas height and quantize to 8px buckets: transient jitter is ignored, but
  // a genuine resize updates the pad proportionally => the facility stays put,
  // no early flicker AND no ~3s slide.
  var _padCache = { ch: -1, pad: 110 }, _lastGoodCH = 0;
  function framePad() {
    var ch = 0;
    try { ch = (window._aevusMapInstance && window._aevusMapInstance.getCanvas().clientHeight) || 0; } catch (e) {}
    if (ch > 200) { _lastGoodCH = ch; }
    var basis = _lastGoodCH > 200 ? _lastGoodCH : Math.max(240, ((window.innerHeight || 800) - 120));
    var q = Math.round(basis / 8) * 8;          // quantize so 1px jitters don't re-pad
    if (q === _padCache.ch) { return _padCache.pad; }
    _padCache.ch = q;
    _padCache.pad = Math.max(40, Math.min(240, Math.round(basis * 0.12)));
    return _padCache.pad;
  }

  var PRODUCT = {
    oil:      0x10D478,
    gas:      0xF59E0B,
    water:    0x3B82F6,
    chemical: 0xA855F7
  };
  var COL = {
    steel:     0xB8C2D0,
    steelDark: 0x8893A4,
    skid:      0x5B6472,
    accent:    0x22D3EE,
    flame:     0xFF8A3C,
    blink:     0xEF4444,
    good:      0x10D478,
    warn:      0xF59E0B,
    bad:       0xEF4444
  };

  // Equipment registry — coords lifted from the award map so the 3D models land
  // exactly where the pad already sits.  id, lng, lat, type, name.
  var EQUIP = [
    { id: "WH",  lng: -95.86804, lat: 29.33961, type: "wellhead",  name: "Wellhead — BlueJay #1" },
    { id: "CHE", lng: -95.86808, lat: 29.33957, type: "chemtote",  name: "Chemical Injection" },
    { id: "SEP", lng: -95.86772, lat: 29.33957, type: "separator", name: "2-Phase Separator" },
    { id: "CMP", lng: -95.8676, lat: 29.33957, type: "compressor",name: "Gas-Lift Compressor" },
    { id: "OT1", lng: -95.86772, lat: 29.33968, type: "oiltank",   name: "Stock Tank #1" },
    { id: "OT2", lng: -95.8676, lat: 29.33968, type: "oiltank",   name: "Stock Tank #2" },
    { id: "PWT", lng: -95.86748, lat: 29.33968, type: "watertank", name: "Produced Water Tank" },
    { id: "EFM", lng: -95.86748, lat: 29.33957, type: "efm",       name: "EFM / Custody Meter" },
    { id: "FLR", lng: -95.8676, lat: 29.33935, type: "flare",     name: "Flare Stack" },
    { id: "TWR", lng: -95.86748, lat: 29.33976, type: "tower",     name: "Radio Tower" },
    { id: "HTR", lng: -95.86784, lat: 29.33957, type: "heater",    name: "Line Heater / Scrubber" },
    { id: "RTU", lng: -95.86796, lat: 29.33976, type: "shelter",   name: "PLC Shelter" },
    { id: "PWR", lng: -95.86784, lat: 29.33976, type: "power",     name: "Power System" },
    { id: "SOL", lng: -95.8676, lat: 29.33976, type: "solararray", name: "Solar Array" },
    { id: "COM", lng: -95.86772, lat: 29.33976, type: "comms",     name: "Communications" }
  ];

  // Process pipe network — product-colored, flow-ready. rackH staggers heights
  // so crossings read cleanly.
  var PIPES = [
    { id: "P1", from: "WH",  to: "SEP", product: "gas",      rackH: 2.4, speed: 0.10 },
    { id: "P2", from: "CHE", to: "WH",  product: "chemical", rackH: 1.8, speed: 0.06 },
    { id: "P3", from: "SEP", to: "CMP", product: "gas",      rackH: 2.6, speed: 0.12 },
    { id: "P4", from: "SEP", to: "OT1", product: "oil",      rackH: 2.0, speed: 0.07 },
    { id: "P5", from: "SEP", to: "PWT", product: "water",    rackH: 2.2, speed: 0.07 },
    { id: "P6", from: "CMP", to: "FLR", product: "gas",      rackH: 2.8, speed: 0.13 },
    { id: "P7", from: "CMP", to: "EFM", product: "gas",      rackH: 2.5, speed: 0.11 }
  ];

  // The EQUIP/PIPES above are the OFFLINE FALLBACK. The live geometry comes from
  // the twin topology endpoint (B1 binding contract) — backend owns the graph.
  var TWIN_FACILITY = "killdeer";
  var _topoReady = false;
  var _BASE_SPEED = { gas: 0.13, oil: 0.08, water: 0.08, chemical: 0.06 };

  // Load the facility graph from /api/v1/twin/.../topology and replace the
  // hardcoded EQUIP/PIPES. Geometry binds to the graph by id; if the endpoint is
  // unavailable we fall back to the bundled arrays so the twin still renders.
  // ── TOPOLOGY (B1) with stale-while-revalidate cache ──────────────────────────
  // First-ever visit: fetch from the API. Every visit after: hydrate the graph
  // from localStorage INSTANTLY (zero network wait before the twin builds), then
  // revalidate in the background and rebuild ONLY if the server graph actually
  // changed. Cache key is versioned so a shipped topology/frame change cleanly
  // invalidates stale client caches.
  var _TOPO_CACHE_KEY = "aevus_twin_topo_v17_" + TWIN_FACILITY;  // v13: condensate relabel + BPR/flare-valve inline devices + meter run
  function _applyTopology(t) {
    if (Array.isArray(t.origin) && t.origin.length === 2) { ORIGIN = t.origin; }
    if (t.frame && t.frame.center) {
      FRAME = { center: t.frame.center, zoom: t.frame.zoom, pitch: t.frame.pitch, bearing: t.frame.bearing };
    }
    EQUIP = t.nodes.map(function (n) {
      return { id: n.id, lng: n.lnglat[0], lat: n.lnglat[1], type: n.type, name: n.name, asset_id: n.asset_id };
    });
    PIPES = t.edges.map(function (e) {
      return { id: e.id, from: e.from, to: e.to, product: e.product,
               diameter: e.diameter_in || 3,
               detailed: true,  // engineer EVERY process line nozzle-to-nozzle — consistent across the whole pad
               inline: e.inline || null,  // "bpr" | "flare_valve" → inline field device on the run
               rackH: e.rack_h_m || 2.2, speed: _BASE_SPEED[e.product] || 0.1 };
    });
  }
  function loadTopology() {
    var finish = function () { _topoReady = true; };
    var cachedRaw = null, hydrated = false;
    // 1) Hydrate instantly from the last-good cache (stale-while-revalidate).
    try {
      cachedRaw = window.localStorage ? localStorage.getItem(_TOPO_CACHE_KEY) : null;
      if (cachedRaw) {
        var ct = JSON.parse(cachedRaw);
        if (ct && ct.nodes && ct.edges) {
          _applyTopology(ct); hydrated = true; _topoReady = true;
          console.log("[killdeer3d] topology from cache (instant build); revalidating…");
        }
      }
    } catch (e) { cachedRaw = null; }
    // 2) Revalidate from the API in the background. Only the COLD path gets gated
    //    by the safety timeout; a warm (cached) load is already _topoReady.
    var safety = hydrated ? null : setTimeout(finish, 5000);
    try {
      fetch("/api/v1/twin/facility/" + TWIN_FACILITY + "/topology", { credentials: "same-origin" })
        .then(function (r) { return r.ok ? r.text() : null; })
        .then(function (txt) {
          var t = null;
          if (txt) { try { t = JSON.parse(txt); } catch (e) { t = null; } }
          if (t && t.nodes && t.edges) {
            var changed = txt !== cachedRaw;
            try { if (window.localStorage) { localStorage.setItem(_TOPO_CACHE_KEY, txt); } } catch (e) {}
            if (!hydrated) {
              _applyTopology(t);
              console.log("[killdeer3d] topology from API:", EQUIP.length, "nodes,", PIPES.length, "edges");
            } else if (changed) {
              _applyTopology(t);
              console.log("[killdeer3d] topology changed on server — rebuilding twin");
              _attachedMap = null;  // force tick() to re-attach + rebuild from the fresh graph
            } else {
              console.log("[killdeer3d] topology revalidated (unchanged)");
            }
          } else if (!hydrated) {
            console.warn("[killdeer3d] topology API empty — using fallback geometry");
          }
          if (safety) { clearTimeout(safety); }
          finish();
        })
        .catch(function () {
          console.warn("[killdeer3d] topology revalidate failed — using " + (hydrated ? "cache" : "fallback"));
          if (safety) { clearTimeout(safety); }
          finish();
        });
    } catch (e) { if (safety) { clearTimeout(safety); } finish(); }
  }

  // ── GEO HELPERS ─────────────────────────────────────────────────────────────
  // Local meter frame: x = east, y = up, z = south (so north is -z).
  // Matches the custom-layer transform below (rotationX(+90°), scale y negative).
  function toLocal(lng, lat) {
    var east  = (lng - ORIGIN[0]) * 111320 * Math.cos(ORIGIN[1] * Math.PI / 180);
    var north = (lat - ORIGIN[1]) * 110540;
    return { x: east, z: -north };
  }
  function equipLocal(id) {
    var i, e;
    for (i = 0; i < EQUIP.length; i++) {
      e = EQUIP[i];
      if (e.id === id) { return toLocal(e.lng, e.lat); }
    }
    return { x: 0, z: 0 };
  }

  // ── STATE ───────────────────────────────────────────────────────────────────
  var THREEref = null;
  var scene = null, camera = null, renderer = null;
  var facility = null;
  var segments = [];            // {id, mesh, curve, packets[], product, baseSpeed, speed}
  var equipMeshes = {};         // id -> THREE.Object3D (for status tint)
  var _callouts = {};           // id -> {marker, dot, name, node} HTML callouts at equipment
  var flameMeshes = [];         // flicker
  var blinkMeshes = [];         // tower beacon
  var _windsock = null;         // {pivot, droop} — oriented to live wind each frame
  var _flares = [];             // [{yaw, lean, layers, light}] — flame flickers + leans downwind
  var _separator = null;        // cutaway internals: gas particles, droplets, liquid level
  var _heater = null;           // cutaway internals: fire-tube glow, bath bubbles, coil flow
  var _wellhead = null;         // cutaway internals: bore riser flow + wing-outlet flow
  var _tanks = [];              // storage-tank cutaways: level shimmer + fill droplets
  var _chemtote = null;         // chem tote cutaway: level + injection droplets
  var _compressor = null;       // compressor cutaway: reciprocating piston
  var _koDrum = null;           // flare KO-drum cutaway: knockout liquid pool
  var _FLAME_WARN = null, _FLAME_SOOT = null;  // status tint colors (lazy-init in animate)
  var WINDSOCK_LL = [-95.86771, 29.33947];  // clear open foreground (S of process train), unoccluded
  var transform = null;
  var _attachedMap = null;
  var _frameIv = null;          // single persistent auto-frame enforcement loop
  var _frameMove = null;        // per-frame 'move' snap handler (kills load flicker)
  var _frameResize = null;      // re-snap on map resize (padding is px-based)
  var _clock0 = (window.performance && performance.now) ? performance.now() : 0;

  // ── MATERIAL FACTORIES ────────────────────────────────────────────────────
  function metal(color) {
    return new THREEref.MeshStandardMaterial({ color: color, metalness: 0.55, roughness: 0.45 });
  }
  function skidMat() {
    return new THREEref.MeshStandardMaterial({ color: COL.skid, metalness: 0.4, roughness: 0.7 });
  }
  function pmat(color) {
    return new THREEref.MeshStandardMaterial({
      color: color, emissive: color, emissiveIntensity: 0.4, metalness: 0.3, roughness: 0.4
    });
  }
  function glowMat(color, opacity) {
    return new THREEref.MeshBasicMaterial({ color: color, transparent: true, opacity: opacity });
  }
  function addEdges(group, geo, mesh, color, opacity) {
    var eg = new THREEref.EdgesGeometry(geo);
    var lm = new THREEref.LineBasicMaterial({ color: color, transparent: true, opacity: opacity });
    var seg = new THREEref.LineSegments(eg, lm);
    if (mesh) { seg.position.copy(mesh.position); seg.rotation.copy(mesh.rotation); }
    group.add(seg);
  }

  // ── EQUIPMENT BUILDERS (y-up, base at y=0) ──────────────────────────────────
  // Wellhead / Christmas tree — CUTAWAY: solid casing + tubing-head spools at the
  // base, a transparent tree body so you see the production bore, and material
  // flowing — oil/gas rises up the tubing from the well and turns out the wing
  // valve to the flowline (animated in animate()).
  function buildWellhead() {
    var g = new THREEref.Group();
    var glassMat = new THREEref.MeshStandardMaterial({
      color: 0xBFD8E6, metalness: 0.1, roughness: 0.08, transparent: true, opacity: 0.16,
      side: THREEref.DoubleSide, depthWrite: false });
    var FLANGE = 0x9AA6B2, WHEEL = 0xCC4444;
    // reusable flange ring on the vertical bore
    function flange(y, r) {
      var f = new THREEref.Mesh(new THREEref.CylinderGeometry(r, r, 0.09, 18), metal(FLANGE));
      f.position.y = y; g.add(f); return f;
    }
    // a gate valve sitting ON the vertical bore — bonnet + rising-stem yoke + a
    // handwheel on the +Z back, out of the way of the production/kill wings (X axis).
    // The handwheel is SEATED ON the stem: its ring plane is perpendicular to the
    // stem so the stem passes through the wheel hub (in the groove), not a flat ring
    // floating beside the valve.
    function boreGate(y, bodyR, wheelR) {
      var b = new THREEref.Mesh(new THREEref.CylinderGeometry(bodyR, bodyR, 0.34, 14), metal(0x6B7785));
      b.position.set(0, y, 0); g.add(b);
      // bonnet flange where the stem leaves the body
      var bonnet = new THREEref.Mesh(new THREEref.CylinderGeometry(bodyR * 0.55, bodyR * 0.62, 0.16, 12), metal(COL.steel));
      bonnet.rotation.x = Math.PI / 2; bonnet.position.set(0, y, bodyR + 0.02); g.add(bonnet);
      // rising stem along +Z, through the wheel hub
      var stem = new THREEref.Mesh(new THREEref.CylinderGeometry(0.035, 0.035, 0.5, 8), metal(0x9AA6B2));
      stem.rotation.x = Math.PI / 2; stem.position.set(0, y, bodyR + 0.28); g.add(stem);
      // handwheel — ring plane perpendicular to the stem (axis = +Z, default torus),
      // hub seated on the stem end
      var w = new THREEref.Mesh(new THREEref.TorusGeometry(wheelR, 0.045, 8, 20), metal(WHEEL));
      w.position.set(0, y, bodyR + 0.42); g.add(w);
      var hub = new THREEref.Mesh(new THREEref.CylinderGeometry(0.06, 0.06, 0.1, 10), metal(COL.steelDark));
      hub.rotation.x = Math.PI / 2; hub.position.set(0, y, bodyR + 0.42); g.add(hub);
      // two spokes across the wheel so it reads as a real handwheel
      var sp1 = new THREEref.Mesh(new THREEref.CylinderGeometry(0.018, 0.018, wheelR * 2, 6), metal(WHEEL));
      sp1.position.set(0, y, bodyR + 0.42); g.add(sp1);
      var sp2 = new THREEref.Mesh(new THREEref.CylinderGeometry(0.018, 0.018, wheelR * 2, 6), metal(WHEEL));
      sp2.rotation.z = Math.PI / 2; sp2.position.set(0, y, bodyR + 0.42); g.add(sp2);
    }

    // ── concrete cellar pad + wide anchor skirt (a tree this tall needs a strong,
    // grounded footing — the stack reads heavy and planted, not spindly) ──
    var pad = new THREEref.Mesh(new THREEref.BoxGeometry(2.5, 0.28, 2.5),
      new THREEref.MeshStandardMaterial({ color: 0x8A8F96, metalness: 0.05, roughness: 0.95 }));
    pad.position.y = 0.14; g.add(pad);
    var skirt = new THREEref.Mesh(new THREEref.CylinderGeometry(0.72, 0.78, 0.34, 20), metal(COL.steelDark));
    skirt.position.y = 0.45; g.add(skirt);                          // base spool / tubing-hanger flange stack
    flange(0.64, 0.8);
    var i, ab;                                                      // anchor bolts around the base flange
    for (i = 0; i < 8; i++) {
      ab = new THREEref.Mesh(new THREEref.CylinderGeometry(0.04, 0.04, 0.12, 6), metal(0x4A535E));
      ab.position.set(Math.cos(i / 8 * Math.PI * 2) * 0.72, 0.66, Math.sin(i / 8 * Math.PI * 2) * 0.72); g.add(ab);
    }

    // ── casing-head spool + annulus (casing) valve & gauge (beefed up) ──
    var csg = new THREEref.Mesh(new THREEref.CylinderGeometry(0.58, 0.66, 0.86, 20), metal(COL.steelDark));
    csg.position.y = 1.05; g.add(csg);
    flange(1.5, 0.68);
    var annV = new THREEref.Mesh(new THREEref.CylinderGeometry(0.1, 0.1, 0.6, 10), metal(COL.steelDark));
    annV.rotation.x = Math.PI / 2; annV.position.set(0, 1.0, 0.62); g.add(annV);
    var annG = new THREEref.Mesh(new THREEref.CylinderGeometry(0.11, 0.11, 0.05, 14), metal(0xBFD8E6));
    annG.position.set(0, 1.24, 0.92); g.add(annG);                 // annulus pressure gauge

    // ── tubing-head spool + flange (beefed up) ──
    var th = new THREEref.Mesh(new THREEref.CylinderGeometry(0.5, 0.56, 0.66, 20), metal(COL.steel));
    th.position.y = 1.92; g.add(th);
    flange(2.3, 0.58);
    // chemical-injection quill + check valve into the tubing head (WEST) — the chem line ties here
    var chemIn = new THREEref.Mesh(new THREEref.CylinderGeometry(0.07, 0.07, 0.62, 8), metal(COL.steelDark));
    chemIn.rotation.z = Math.PI / 2; chemIn.position.set(-0.52, 1.85, 0); g.add(chemIn);
    var chemChk = new THREEref.Mesh(new THREEref.SphereGeometry(0.1, 8, 6), metal(PRODUCT.chemical));
    chemChk.position.set(-0.74, 1.85, 0); g.add(chemChk);
    // chem-injection inlet FLANGE — the purple chemical line lands ON this flange
    var chemFl = new THREEref.Mesh(new THREEref.CylinderGeometry(0.13, 0.13, 0.07, 14), metal(0x9AA6B2));
    chemFl.rotation.z = Math.PI / 2; chemFl.position.set(-0.82, 1.85, 0); g.add(chemFl);

    // ── SECTIONED steel tree body — a 270° opaque PAINTED-STEEL shell with a
    // quarter cut away (facing the production wing / +X) so the production bore and
    // the rising gas stay visible, like a cutaway training model. Reads as solid
    // steel field equipment, not a hollow glass tube. ──
    var steelBody = new THREEref.MeshStandardMaterial({
      color: 0x556372, metalness: 0.72, roughness: 0.42, side: THREEref.DoubleSide });
    var bodyG = new THREEref.CylinderGeometry(0.36, 0.36, 2.5, 28, 1, true, Math.PI * 0.25, Math.PI * 1.5);
    var body = new THREEref.Mesh(bodyG, steelBody); body.position.y = 3.35; g.add(body);
    addEdges(g, new THREEref.CylinderGeometry(0.36, 0.36, 2.5, 28), body, COL.accent, 0.28);
    // a faint glass pane closes the cutaway opening so the tree still reads enclosed
    var paneG = new THREEref.CylinderGeometry(0.355, 0.355, 2.5, 12, 1, true, Math.PI * 1.75, Math.PI * 0.5);
    var pane = new THREEref.Mesh(paneG, glassMat); pane.position.y = 3.35; g.add(pane);
    var bore = new THREEref.Mesh(new THREEref.CylinderGeometry(0.13, 0.13, 3.4, 14), metal(0x8893A0));
    bore.position.y = 3.0; g.add(bore);

    // ── LOWER MASTER VALVE (manual gate) ──
    boreGate(2.62, 0.3, 0.3);

    // ── SSV / UPPER MASTER — actuated, fail-CLOSE: the wellhead end of the ESD loop.
    // High/low pilots dump the actuator and the spring shuts the well in on an upset. ──
    var ssvB = new THREEref.Mesh(new THREEref.CylinderGeometry(0.3, 0.3, 0.46, 14), metal(0x6B7785));
    ssvB.position.set(0, 3.12, 0); g.add(ssvB);
    var ssvAct = new THREEref.Mesh(new THREEref.CylinderGeometry(0.31, 0.31, 0.46, 16), metal(WHEEL));
    ssvAct.rotation.x = Math.PI / 2; ssvAct.position.set(0, 3.12, -0.56); g.add(ssvAct);   // actuator (back)
    var ssvCap = new THREEref.Mesh(new THREEref.SphereGeometry(0.31, 14, 8), metal(COL.steelDark));
    ssvCap.position.set(0, 3.12, -0.82); g.add(ssvCap);

    // ── flow cross (where the wings come off the bore) ──
    var crossY = 3.78;
    var cross = new THREEref.Mesh(new THREEref.SphereGeometry(0.3, 14, 10), metal(0x7B8694));
    cross.position.set(0, crossY, 0); g.add(cross);

    // helper: a wing-valve handwheel SEATED on a rising stem — bonnet on top of the
    // wing valve, vertical stem, horizontal wheel with hub + spokes (axis vertical,
    // because a gate valve on a horizontal line has a vertical rising stem).
    function wingWheel(x, wheelR) {
      var bon = new THREEref.Mesh(new THREEref.CylinderGeometry(0.1, 0.12, 0.14, 12), metal(COL.steel));
      bon.position.set(x, crossY + 0.12, 0); g.add(bon);
      var st = new THREEref.Mesh(new THREEref.CylinderGeometry(0.03, 0.03, 0.34, 8), metal(0x9AA6B2));
      st.position.set(x, crossY + 0.32, 0); g.add(st);
      var w = new THREEref.Mesh(new THREEref.TorusGeometry(wheelR, 0.04, 8, 18), metal(WHEEL));
      w.rotation.x = Math.PI / 2; w.position.set(x, crossY + 0.46, 0); g.add(w);  // horizontal wheel ON the stem
      var hub = new THREEref.Mesh(new THREEref.CylinderGeometry(0.045, 0.045, 0.08, 8), metal(COL.steelDark));
      hub.position.set(x, crossY + 0.46, 0); g.add(hub);
      var s1 = new THREEref.Mesh(new THREEref.CylinderGeometry(0.016, 0.016, wheelR * 2, 6), metal(WHEEL));
      s1.rotation.z = Math.PI / 2; s1.position.set(x, crossY + 0.46, 0); g.add(s1);
      var s2 = new THREEref.Mesh(new THREEref.CylinderGeometry(0.016, 0.016, wheelR * 2, 6), metal(WHEEL));
      s2.rotation.x = Math.PI / 2; s2.position.set(x, crossY + 0.46, 0); g.add(s2);
    }
    // small pressure gauge (case + face) on a standpipe — face toward +Z (the viewer)
    function gauge(x, y, z) {
      var stand = new THREEref.Mesh(new THREEref.CylinderGeometry(0.025, 0.025, 0.34, 6), metal(COL.steelDark));
      stand.position.set(x, y - 0.17, z); g.add(stand);
      var face = new THREEref.Mesh(new THREEref.CylinderGeometry(0.12, 0.12, 0.06, 18), metal(0xBFD8E6));
      face.rotation.x = Math.PI / 2; face.position.set(x, y, z + 0.05); g.add(face);
      var ring = new THREEref.Mesh(new THREEref.TorusGeometry(0.12, 0.02, 6, 18), metal(COL.steelDark));
      ring.position.set(x, y, z + 0.08); g.add(ring);
    }

    // ── PRODUCTION WING (EAST, +X): a wing NIPPLE off the flow cross carries the
    // valve + handwheel OUT clear of the tree body, then CHOKE → flowline take-off
    // flange. (Valve/wheel pushed out so the red handwheel sits on the wing, not
    // overlapping the body.) ──
    var pwNip = new THREEref.Mesh(new THREEref.CylinderGeometry(0.12, 0.12, 0.56, 12), metal(COL.steelDark));
    pwNip.rotation.z = Math.PI / 2; pwNip.position.set(0.52, crossY, 0); g.add(pwNip);
    var pwBody = new THREEref.Mesh(new THREEref.CylinderGeometry(0.15, 0.15, 0.42, 12), metal(0x6B7785));
    pwBody.rotation.z = Math.PI / 2; pwBody.position.set(0.9, crossY, 0); g.add(pwBody);
    wingWheel(0.9, 0.2);                                              // production-wing handwheel — clear of the body
    var choke = new THREEref.Mesh(new THREEref.CylinderGeometry(0.18, 0.13, 0.46, 12), metal(0x6B7785));
    choke.rotation.z = Math.PI / 2; choke.position.set(1.34, crossY, 0); g.add(choke);
    var chokeInd = new THREEref.Mesh(new THREEref.CylinderGeometry(0.04, 0.04, 0.44, 8), metal(0xFBBF24));
    chokeInd.position.set(1.34, crossY + 0.38, 0); g.add(chokeInd);   // adjustable-choke position indicator
    var flFl = new THREEref.Mesh(new THREEref.CylinderGeometry(0.19, 0.19, 0.1, 14), metal(FLANGE));
    flFl.rotation.z = Math.PI / 2; flFl.position.set(1.78, crossY, 0); g.add(flFl);    // flowline take-off flange
    gauge(1.58, crossY + 0.05, 0.18);                                // FLOWLINE PRESSURE gauge (FLP) on the take-off

    // ── KILL WING (WEST, −X): nipple → wing gate (out clear of the body) → blind cap ──
    var kwNip = new THREEref.Mesh(new THREEref.CylinderGeometry(0.1, 0.1, 0.56, 10), metal(COL.steelDark));
    kwNip.rotation.z = Math.PI / 2; kwNip.position.set(-0.52, crossY, 0); g.add(kwNip);
    var kwBody = new THREEref.Mesh(new THREEref.CylinderGeometry(0.13, 0.13, 0.42, 10), metal(0x6B7785));
    kwBody.rotation.z = Math.PI / 2; kwBody.position.set(-0.9, crossY, 0); g.add(kwBody);
    wingWheel(-0.9, 0.16);                                            // kill-wing handwheel — clear of the body
    var kwCap = new THREEref.Mesh(new THREEref.CylinderGeometry(0.13, 0.14, 0.13, 12), metal(COL.steelDark));
    kwCap.rotation.z = Math.PI / 2; kwCap.position.set(-1.24, crossY, 0); g.add(kwCap);
    // TUBING-HEAD pressure gauge (well TBG) on the front (+X) face, casing-head level
    gauge(0.6, 1.85, 0.18);

    // ── SWAB VALVE (vertical access) + tree cap + master pressure gauge ──
    boreGate(4.18, 0.2, 0.21);
    var treeCap = new THREEref.Mesh(new THREEref.CylinderGeometry(0.23, 0.25, 0.18, 14), metal(COL.steel));
    treeCap.position.set(0, 4.54, 0); g.add(treeCap);
    var topG = new THREEref.Mesh(new THREEref.CylinderGeometry(0.12, 0.12, 0.05, 14), metal(0xBFD8E6));
    topG.position.set(0, 4.78, 0); g.add(topG);                    // master pressure gauge on top

    // ── animated material: gas rises up the bore; some turns out the production wing ──
    var riser = [], wingFlow = [], wp, rp;
    for (i = 0; i < 7; i++) {
      rp = new THREEref.Mesh(new THREEref.SphereGeometry(0.1, 8, 6), glowMat(PRODUCT.gas, 0.9));
      g.add(rp); riser.push({ mesh: rp, offset: i / 7 });
    }
    for (i = 0; i < 3; i++) {
      wp = new THREEref.Mesh(new THREEref.SphereGeometry(0.09, 7, 6), glowMat(PRODUCT.gas, 0.9));
      g.add(wp); wingFlow.push({ mesh: wp, offset: i / 3 });
    }
    _wellhead = { riser: riser, wingFlow: wingFlow, y0: 0.7, y1: 3.95, wingY: crossY, wingX: 1.1 };
    return g;
  }

  // Chemical injection — CUTAWAY caged IBC tote: transparent shell showing the
  // chemical level inside, a steel cage, and an injection pump metering chemical
  // up the injection line (animated droplets) to the wellhead.
  function buildChemTote() {
    var g = new THREEref.Group();
    var W = 1.2, glassMat = new THREEref.MeshStandardMaterial({
      color: 0xCBD5E1, metalness: 0.1, roughness: 0.08, transparent: true, opacity: 0.14,
      side: THREEref.DoubleSide, depthWrite: false });
    var base = new THREEref.Mesh(new THREEref.BoxGeometry(W + 0.15, 0.3, W + 0.15), skidMat());
    base.position.y = 0.15; g.add(base);
    // transparent tote + steel cage edges
    var tote = new THREEref.Mesh(new THREEref.BoxGeometry(W, W, W), glassMat);
    tote.position.y = 0.9; g.add(tote);
    addEdges(g, new THREEref.BoxGeometry(W, W, W), tote, 0xAEB8C4, 0.85);
    // mid cage bands
    [0.6, 1.2].forEach(function (yy) {
      var band = new THREEref.Mesh(new THREEref.BoxGeometry(W + 0.04, 0.05, W + 0.04), metal(COL.steelDark));
      band.position.y = yy; g.add(band);
    });
    // chemical level inside (~68% full) + bright interface line
    var fillH = W * 0.68, fillBot = 0.9 - W / 2;
    var fill = new THREEref.Mesh(new THREEref.BoxGeometry(W * 0.94, fillH, W * 0.94),
      new THREEref.MeshStandardMaterial({ color: PRODUCT.chemical, transparent: true, opacity: 0.6,
        metalness: 0.1, roughness: 0.3, emissive: PRODUCT.chemical, emissiveIntensity: 0.2 }));
    var fillTop = fillBot + fillH;
    fill.position.set(0, fillBot + fillH / 2, 0); g.add(fill);
    var level = new THREEref.Mesh(new THREEref.BoxGeometry(W * 0.94, 0.03, W * 0.94), glowMat(0xC084FC, 0.7));
    level.position.set(0, fillTop, 0); g.add(level);
    // injection pump beside the tote
    var pump = new THREEref.Mesh(new THREEref.BoxGeometry(0.5, 0.4, 0.4), metal(COL.steel));
    pump.position.set(W * 0.62 + 0.3, 0.5, 0); g.add(pump);
    var motor = new THREEref.Mesh(new THREEref.CylinderGeometry(0.16, 0.16, 0.4, 12), metal(COL.steelDark));
    motor.rotation.z = Math.PI / 2; motor.position.set(W * 0.62 + 0.3, 0.75, 0); g.add(motor);
    // injection line up + over toward the wellhead, with metered droplets
    var injPts = [
      new THREEref.Vector3(W * 0.62 + 0.3, 0.7, 0),
      new THREEref.Vector3(W * 0.62 + 0.3, 1.5, 0),
      new THREEref.Vector3(W * 0.62 + 1.4, 1.5, 0)
    ];
    var injCurve = new THREEref.CatmullRomCurve3(injPts, false, "catmullrom", 0.2);
    var inj = new THREEref.Mesh(new THREEref.TubeGeometry(injCurve, 28, 0.045, 8, false), metal(COL.steelDark));
    g.add(inj);
    var drops = [], i;
    for (i = 0; i < 4; i++) {
      var dm = new THREEref.Mesh(new THREEref.SphereGeometry(0.05, 7, 6), glowMat(PRODUCT.chemical, 0.95));
      g.add(dm); drops.push({ mesh: dm, offset: i / 4 });
    }
    _chemtote = { level: level, fillTop: fillTop, drops: drops, curve: injCurve };
    return g;
  }

  // 2-phase separator — CUTAWAY: bottom half solid metal (holds the liquid), top
  // half transparent glass so you see inside: gas space, liquid level, inlet
  // diverter + mist extractor. Gas flows along the top to the outlet; droplets
  // fall off the diverter into the pool (animated in animate()).
  function buildSeparator() {
    var g = new THREEref.Group();
    var len = 7.0, r = 1.4, yC = r + 0.9;   // shell center height
    var sx, k, dx;

    // shell: bottom 180° solid metal, top 180° glass (after rotz=+90°, theta=0 -> top)
    var botG = new THREEref.CylinderGeometry(r, r, len, 30, 1, true, Math.PI / 2, Math.PI);
    var bot = new THREEref.Mesh(botG, new THREEref.MeshStandardMaterial({
      color: COL.steel, metalness: 0.55, roughness: 0.45, side: THREEref.DoubleSide }));
    bot.rotation.z = Math.PI / 2; bot.position.y = yC; g.add(bot);
    var glassMat = new THREEref.MeshStandardMaterial({
      color: 0xBFD8E6, metalness: 0.1, roughness: 0.08, transparent: true, opacity: 0.15,
      side: THREEref.DoubleSide, depthWrite: false });
    var topG = new THREEref.CylinderGeometry(r, r, len, 30, 1, true, -Math.PI / 2, Math.PI);
    var top = new THREEref.Mesh(topG, glassMat);
    top.rotation.z = Math.PI / 2; top.position.y = yC; g.add(top);
    addEdges(g, new THREEref.CylinderGeometry(r, r, len, 30), bot, COL.accent, 0.4);
    // glass end caps (see in from the ends too)
    var capA = new THREEref.Mesh(new THREEref.SphereGeometry(r, 18, 12), glassMat);
    capA.position.set(-len / 2, yC, 0); g.add(capA);
    var capB = new THREEref.Mesh(new THREEref.SphereGeometry(r, 18, 12), glassMat);
    capB.position.set(len / 2, yC, 0); g.add(capB);

    // saddles
    dx = [-len * 0.3, len * 0.3];
    for (k = 0; k < dx.length; k++) {
      var sad = new THREEref.Mesh(new THREEref.BoxGeometry(0.6, 0.9, r * 2.0), skidMat());
      sad.position.set(dx[k], 0.45, 0); g.add(sad);
    }

    // ── INTERNALS (visible through the glass top) ──
    // ── 3-PHASE inventory: water (bottom) + condensate (top) with an interface,
    // a WEIR PLATE near the outlet end, and an oil bucket downstream of the weir ──
    var poolY = yC - 0.30;                 // condensate surface
    var poolBot = yC - r + 0.08;           // vessel bottom (water)
    var wInt = yC - 0.62;                  // oil/water interface
    var oilMat = new THREEref.MeshStandardMaterial({ color: PRODUCT.oil, transparent: true, opacity: 0.5,
      metalness: 0.1, roughness: 0.3, emissive: PRODUCT.oil, emissiveIntensity: 0.15 });
    var watMat = new THREEref.MeshStandardMaterial({ color: PRODUCT.water, transparent: true, opacity: 0.5,
      metalness: 0.1, roughness: 0.3, emissive: 0x1E5FA8, emissiveIntensity: 0.12 });
    var water = new THREEref.Mesh(new THREEref.BoxGeometry(len * 0.9, wInt - poolBot, 2.05), watMat);
    water.position.set(0, (poolBot + wInt) / 2, 0); g.add(water);                       // water layer (full length)
    var oilW = new THREEref.Mesh(new THREEref.BoxGeometry(len * 0.9 * 0.62, poolY - wInt, 2.05), oilMat);
    oilW.position.set(-len * 0.14, (wInt + poolY) / 2, 0); g.add(oilW);                 // condensate on the water, upstream of weir
    var oilB = new THREEref.Mesh(new THREEref.BoxGeometry(len * 0.18, poolY - poolBot, 2.05), oilMat);
    oilB.position.set(len * 0.36, (poolBot + poolY) / 2, 0); g.add(oilB);               // condensate bucket downstream of weir
    var weir = new THREEref.Mesh(new THREEref.BoxGeometry(0.08, r * 1.3, 1.9), metal(0xAEB8C4));
    weir.position.set(len * 0.28, yC - 0.45, 0); g.add(weir);                           // weir plate
    var iface = new THREEref.Mesh(new THREEref.BoxGeometry(len * 0.9, 0.04, 2.05), glowMat(0x38BDF8, 0.55));
    iface.position.set(0, wInt, 0); g.add(iface);                                       // oil/water interface
    var level = new THREEref.Mesh(new THREEref.BoxGeometry(len * 0.9, 0.04, 2.05), glowMat(0x34D399, 0.6));
    level.position.set(0, poolY, 0); g.add(level);                                      // condensate surface

    // inlet nozzle + diverter plate (gas/liquid enters, hits the diverter)
    var inNoz = new THREEref.Mesh(new THREEref.CylinderGeometry(0.18, 0.18, 1.0, 12), metal(COL.steelDark));
    inNoz.position.set(-len * 0.4, yC + r + 0.3, 0); g.add(inNoz);
    var div = new THREEref.Mesh(new THREEref.BoxGeometry(0.1, 1.0, 1.5), metal(0xAEB8C4));
    div.position.set(-len * 0.36, yC + 0.15, 0); div.rotation.z = 0.35; g.add(div);
    // mist extractor / demister pad before the gas outlet
    var mist = new THREEref.Mesh(new THREEref.BoxGeometry(0.18, 1.0, 1.7),
      new THREEref.MeshStandardMaterial({ color: 0xC7D0DA, transparent: true, opacity: 0.5, metalness: 0.3, roughness: 0.7 }));
    mist.position.set(len * 0.34, yC + 0.45, 0); g.add(mist);
    // 3-phase nozzles: gas (top), condensate (off the bucket, mid), water (bottom)
    var gOut = new THREEref.Mesh(new THREEref.CylinderGeometry(0.16, 0.16, 1.0, 10), metal(COL.steelDark));
    gOut.position.set(len * 0.42, yC + r + 0.3, 0); g.add(gOut);
    var oOut = new THREEref.Mesh(new THREEref.CylinderGeometry(0.14, 0.14, 0.9, 10), metal(COL.steelDark));
    oOut.rotation.z = Math.PI / 2; oOut.position.set(len / 2 + 0.35, poolY, 0.5); g.add(oOut);   // condensate outlet (E head, mid)
    var wOut = new THREEref.Mesh(new THREEref.CylinderGeometry(0.13, 0.13, 0.9, 10), metal(COL.steelDark));
    wOut.position.set(len * 0.42, yC - r - 0.25, -0.5); g.add(wOut);                              // water outlet (bottom)
    // PRESSURE-SAFETY VALVE (PSV) on the vessel top — relieves to the flare/relief
    // header on overpressure (the protective layer the audit flagged as missing).
    var psvBody = new THREEref.Mesh(new THREEref.CylinderGeometry(0.16, 0.2, 0.5, 12), metal(COL.steelDark));
    psvBody.position.set(-len * 0.18, yC + r + 0.35, 0); g.add(psvBody);
    var psvBonnet = new THREEref.Mesh(new THREEref.CylinderGeometry(0.12, 0.16, 0.55, 10), metal(0xCC4444));
    psvBonnet.position.set(-len * 0.18, yC + r + 0.85, 0); g.add(psvBonnet);
    var psvOut = new THREEref.Mesh(new THREEref.CylinderGeometry(0.1, 0.1, 0.6, 8), metal(COL.steelDark));
    psvOut.rotation.z = Math.PI / 2; psvOut.position.set(-len * 0.18 + 0.4, yC + r + 0.55, 0); g.add(psvOut);

    // ── animated material: gas flows along the top, droplets fall off the diverter ──
    var gasY = yC + 0.55, x0 = -len * 0.34, x1 = len * 0.30, gas = [], drops = [], i;
    for (i = 0; i < 6; i++) {
      var gp = new THREEref.Mesh(new THREEref.SphereGeometry(0.13, 8, 6), glowMat(0xFFE6A8, 0.4));
      g.add(gp); gas.push({ mesh: gp, offset: i / 6 });
    }
    for (i = 0; i < 4; i++) {
      var dpm = new THREEref.Mesh(new THREEref.SphereGeometry(0.09, 7, 6), glowMat(PRODUCT.oil, 0.85));
      g.add(dpm); drops.push({ mesh: dpm, offset: i / 4 });
    }
    _separator = { gas: gas, drops: drops, level: level, x0: x0, x1: x1, gasY: gasY,
                   poolY: poolY, dropX: -len * 0.34, dropTop: yC + r - 0.3 };
    return g;
  }

  // Gas-lift compressor — CUTAWAY: the compressor cylinder is a transparent glass
  // jacket showing a PISTON reciprocating inside (driven by the engine), plus a
  // suction scrubber bottle and a finned interstage cooler. (Piston animates.)
  function buildCompressor() {
    var g = new THREEref.Group();
    var skid = new THREEref.Mesh(new THREEref.BoxGeometry(5.2, 0.5, 3.0), skidMat());
    skid.position.y = 0.25; g.add(skid);
    var engine = new THREEref.Mesh(new THREEref.BoxGeometry(3.0, 1.7, 1.7), metal(COL.steel));
    engine.position.set(-0.6, 1.35, 0); g.add(engine);
    addEdges(g, new THREEref.BoxGeometry(3.0, 1.7, 1.7), engine, COL.accent, 0.3);

    // compressor cylinder — glass jacket so the piston is visible
    var cylLen = 2.2, cylR = 0.9, cylX = 1.7, cylY = 1.1;
    var cylG = new THREEref.CylinderGeometry(cylR, cylR, cylLen, 22, 1, true);
    var glassMat = new THREEref.MeshStandardMaterial({ color: 0xBFD8E6, metalness: 0.1, roughness: 0.08,
      transparent: true, opacity: 0.16, side: THREEref.DoubleSide, depthWrite: false });
    var cyl = new THREEref.Mesh(cylG, glassMat); cyl.rotation.z = Math.PI / 2; cyl.position.set(cylX, cylY, 0); g.add(cyl);
    addEdges(g, cylG, cyl, COL.accent, 0.3);
    // head end cap (solid)
    var head = new THREEref.Mesh(new THREEref.CylinderGeometry(cylR + 0.05, cylR + 0.05, 0.22, 22), metal(COL.steelDark));
    head.rotation.z = Math.PI / 2; head.position.set(cylX + cylLen / 2, cylY, 0); g.add(head);
    // PISTON inside (reciprocates along x) + rod back to the crank (engine)
    var piston = new THREEref.Mesh(new THREEref.CylinderGeometry(cylR * 0.82, cylR * 0.82, 0.4, 20), metal(0x8893A1));
    piston.rotation.z = Math.PI / 2; piston.position.set(cylX, cylY, 0); g.add(piston);
    var rod = new THREEref.Mesh(new THREEref.CylinderGeometry(0.1, 0.1, 1.2, 10), metal(COL.steel));
    rod.rotation.z = Math.PI / 2; rod.position.set(cylX - 0.8, cylY, 0); g.add(rod);

    // suction scrubber bottle (vertical) + finned interstage cooler
    var scrub = new THREEref.Mesh(new THREEref.CylinderGeometry(0.45, 0.45, 2.0, 16), metal(COL.steel));
    scrub.position.set(1.7, 1.5, 1.1); g.add(scrub);
    addEdges(g, new THREEref.CylinderGeometry(0.45, 0.45, 2.0, 16), scrub, COL.accent, 0.25);
    var cooler = new THREEref.Mesh(new THREEref.BoxGeometry(1.6, 0.5, 1.0), metal(COL.steelDark));
    cooler.position.set(-0.6, 0.65, -1.2); g.add(cooler);
    for (var fi = 0; fi < 6; fi++) {
      var fin = new THREEref.Mesh(new THREEref.BoxGeometry(0.04, 0.6, 1.0), metal(COL.steel));
      fin.position.set(-1.2 + fi * 0.24, 0.65, -1.2); g.add(fin);
    }
    var stack = new THREEref.Mesh(new THREEref.CylinderGeometry(0.22, 0.26, 3.2, 12), metal(COL.steelDark));
    stack.position.set(-1.6, 2.9, -0.6); g.add(stack);

    _compressor = { piston: piston, x0: cylX - 0.45, x1: cylX + 0.45, rod: rod, rodX: cylX - 0.8 };
    return g;
  }

  // Storage tank — CUTAWAY: a transparent shell with a short solid skirt at grade,
  // so the product LEVEL inside is visible (translucent fill + bright interface
  // line). External level gauge bead tracks the level; a fill stream drips to the
  // surface. (Level shimmers + droplets fall in animate().)
  function buildTank(productKey, level) {
    var g = new THREEref.Group();
    var r = 2.8, h = 6.0;
    var lvl = Math.max(0.08, Math.min(0.95, level || 0.6));
    var fillTop = h * lvl;
    // transparent shell (the cutaway) + a short opaque skirt grounding it
    var shellG = new THREEref.CylinderGeometry(r, r, h, 30, 1, true);
    var shell = new THREEref.Mesh(shellG, new THREEref.MeshStandardMaterial({
      color: 0xBFD8E6, metalness: 0.12, roughness: 0.1, transparent: true, opacity: 0.13,
      side: THREEref.DoubleSide, depthWrite: false }));
    shell.position.y = h / 2; g.add(shell);
    addEdges(g, new THREEref.CylinderGeometry(r, r, h, 30), shell, COL.accent, 0.3);
    var skirt = new THREEref.Mesh(new THREEref.CylinderGeometry(r + 0.02, r + 0.02, 0.7, 30, 1, true),
      metal(COL.steelDark));
    skirt.position.y = 0.35; g.add(skirt);
    // flat roof + thief hatch
    var roof = new THREEref.Mesh(new THREEref.CylinderGeometry(r, r, 0.3, 30), metal(COL.steelDark));
    roof.position.y = h + 0.15; g.add(roof);
    var hatch = new THREEref.Mesh(new THREEref.CylinderGeometry(0.4, 0.4, 0.4, 12), metal(COL.steelDark));
    hatch.position.set(r * 0.4, h + 0.4, 0); g.add(hatch);
    // product fill (translucent) + bright interface line
    var fill = new THREEref.Mesh(new THREEref.CylinderGeometry(r * 0.97, r * 0.97, fillTop, 30),
      new THREEref.MeshStandardMaterial({ color: PRODUCT[productKey], transparent: true, opacity: 0.55,
        metalness: 0.1, roughness: 0.3, emissive: PRODUCT[productKey], emissiveIntensity: 0.18 }));
    fill.position.y = fillTop / 2; g.add(fill);
    var level3 = new THREEref.Mesh(new THREEref.CylinderGeometry(r * 0.97, r * 0.97, 0.05, 30),
      glowMat(productKey === "oil" ? 0x34D399 : 0x60A5FA, 0.65));
    level3.position.y = fillTop; g.add(level3);
    // external level gauge (standpipe + float bead at the liquid level)
    var gauge = new THREEref.Mesh(new THREEref.CylinderGeometry(0.06, 0.06, h * 0.92, 8),
      metal(COL.steelDark));
    gauge.position.set(r + 0.12, h * 0.5, 0); g.add(gauge);
    var bead = new THREEref.Mesh(new THREEref.SphereGeometry(0.12, 10, 8), glowMat(0x34D399, 0.9));
    bead.position.set(r + 0.12, fillTop, 0); g.add(bead);
    // fill nozzle near top + dripping product to the surface
    var drops = [], i;
    for (i = 0; i < 3; i++) {
      var dm = new THREEref.Mesh(new THREEref.SphereGeometry(0.12, 8, 6), glowMat(PRODUCT[productKey], 0.85));
      g.add(dm); drops.push({ mesh: dm, offset: i / 3 });
    }
    _tanks.push({ level: level3, bead: bead, fillTop: fillTop, dropTop: h - 0.4,
                  dropX: r * 0.45, drops: drops });
    return g;
  }

  function buildFlare() {
    var g = new THREEref.Group();
    var H = 13.0;   // stack height
    var i, k;

    // ── KNOCKOUT DRUM + accurate flare piping ──────────────────────────────
    // Real flare path: process/relief gas -> KO drum (entrained liquids drop out
    // the boot/drain) -> dry gas rises out the drum top -> riser into the stack
    // -> tip. Pilot-gas lines run up the stack to the tip pilots.
    var skid = new THREEref.Mesh(new THREEref.BoxGeometry(4.6, 0.4, 2.2), skidMat());
    skid.position.set(1.7, 0.2, 0); g.add(skid);
    var koLen = 3.0, koR = 0.7, koCx = 2.4, koY = koR + 0.7;
    // CUTAWAY KO drum: bottom-half solid metal (holds knocked-out liquid), top-half
    // glass so you see the entrained liquid drop out before the gas rises to the stack.
    var koGlass = new THREEref.MeshStandardMaterial({ color: 0xBFD8E6, metalness: 0.1, roughness: 0.08,
      transparent: true, opacity: 0.16, side: THREEref.DoubleSide, depthWrite: false });
    var koBotG = new THREEref.CylinderGeometry(koR, koR, koLen, 22, 1, true, Math.PI / 2, Math.PI);
    var koBot = new THREEref.Mesh(koBotG, new THREEref.MeshStandardMaterial({
      color: COL.steel, metalness: 0.55, roughness: 0.45, side: THREEref.DoubleSide }));
    koBot.rotation.z = Math.PI / 2; koBot.position.set(koCx, koY, 0); g.add(koBot);
    var koTopG = new THREEref.CylinderGeometry(koR, koR, koLen, 22, 1, true, -Math.PI / 2, Math.PI);
    var koTop = new THREEref.Mesh(koTopG, koGlass);
    koTop.rotation.z = Math.PI / 2; koTop.position.set(koCx, koY, 0); g.add(koTop);
    addEdges(g, new THREEref.CylinderGeometry(koR, koR, koLen, 22), koBot, COL.accent, 0.3);
    var koA = new THREEref.Mesh(new THREEref.SphereGeometry(koR, 14, 10), koGlass);
    koA.position.set(koCx - koLen / 2, koY, 0); g.add(koA);
    var koB = new THREEref.Mesh(new THREEref.SphereGeometry(koR, 14, 10), koGlass);
    koB.position.set(koCx + koLen / 2, koY, 0); g.add(koB);
    // knocked-out liquid pool at the bottom + interface line + settling droplets
    var koPoolY = koY - 0.32, koPoolBot = koY - koR + 0.06, koPoolH = koPoolY - koPoolBot;
    var koLiq = new THREEref.Mesh(new THREEref.BoxGeometry(koLen * 0.86, koPoolH, koR * 1.5),
      new THREEref.MeshStandardMaterial({ color: PRODUCT.oil, transparent: true, opacity: 0.5,
        metalness: 0.1, roughness: 0.3, emissive: PRODUCT.oil, emissiveIntensity: 0.15 }));
    koLiq.position.set(koCx, koPoolBot + koPoolH / 2, 0); g.add(koLiq);
    var koLevel = new THREEref.Mesh(new THREEref.BoxGeometry(koLen * 0.86, 0.03, koR * 1.5), glowMat(0x34D399, 0.6));
    koLevel.position.set(koCx, koPoolY, 0); g.add(koLevel);
    var koDrops = [], kdI;
    for (kdI = 0; kdI < 4; kdI++) {
      var kdm = new THREEref.Mesh(new THREEref.SphereGeometry(0.07, 7, 6), glowMat(PRODUCT.oil, 0.85));
      g.add(kdm); koDrops.push({ mesh: kdm, offset: kdI / 4 });
    }
    _koDrum = { level: koLevel, drops: koDrops, poolY: koPoolY, dropTop: koY + koR - 0.2,
                cx: koCx, len: koLen };
    [koCx - 0.9, koCx + 0.9].forEach(function (sx) {
      var sad = new THREEref.Mesh(new THREEref.BoxGeometry(0.4, 0.6, 1.5), skidMat());
      sad.position.set(sx, 0.5, 0); g.add(sad);
    });

    // liquid boot (sump) under the drum + drain line to a small sump box
    var bootBot = koY - koR - 0.9;
    var boot = new THREEref.Mesh(new THREEref.CylinderGeometry(0.32, 0.32, 0.95, 12), metal(COL.steel));
    boot.position.set(koCx + 0.5, koY - koR - 0.3, 0); g.add(boot);
    var bootCap = new THREEref.Mesh(new THREEref.SphereGeometry(0.32, 12, 8), metal(COL.steel));
    bootCap.position.set(koCx + 0.5, bootBot + 0.15, 0); g.add(bootCap);
    var drainPts = [
      new THREEref.Vector3(koCx + 0.5, bootBot + 0.1, 0),
      new THREEref.Vector3(koCx + 0.5, 0.25, 0),
      new THREEref.Vector3(koCx + 1.5, 0.25, 0)
    ];
    var drain = new THREEref.Mesh(new THREEref.TubeGeometry(
      new THREEref.CatmullRomCurve3(drainPts, false, "catmullrom", 0.2), 26, 0.07, 8, false), metal(COL.steelDark));
    g.add(drain);
    var sump = new THREEref.Mesh(new THREEref.BoxGeometry(0.7, 0.5, 0.7), skidMat());
    sump.position.set(koCx + 1.7, 0.25, 0); g.add(sump);

    // INLET header — process/relief gas enters the drum top at the far end.
    var inNozX = koCx + koLen / 2 - 0.35;
    var inNoz = new THREEref.Mesh(new THREEref.CylinderGeometry(0.2, 0.2, 0.6, 12), metal(COL.steelDark));
    inNoz.position.set(inNozX, koY + koR + 0.25, 0); g.add(inNoz);
    var header = new THREEref.Mesh(new THREEref.TubeGeometry(new THREEref.CatmullRomCurve3([
      new THREEref.Vector3(-0.2, 1.5, 0),                 // arrives from the process side (P6 lands here)
      new THREEref.Vector3(inNozX, 1.5, 0),
      new THREEref.Vector3(inNozX, koY + koR + 0.55, 0)   // down into the inlet nozzle
    ], false, "catmullrom", 0.2), 44, 0.18, 12, false), metal(COL.steelDark));
    g.add(header);
    var hdrFlg = new THREEref.Mesh(new THREEref.CylinderGeometry(0.27, 0.27, 0.1, 14), metal(COL.steel));
    hdrFlg.rotation.z = Math.PI / 2; hdrFlg.position.set(-0.2, 1.5, 0); g.add(hdrFlg);

    // GAS OUTLET riser — dry gas leaves the drum top (stack end) into the stack base.
    var outNozX = koCx - koLen / 2 + 0.35;
    var outNoz = new THREEref.Mesh(new THREEref.CylinderGeometry(0.18, 0.18, 0.6, 12), metal(COL.steelDark));
    outNoz.position.set(outNozX, koY + koR + 0.25, 0); g.add(outNoz);
    var riser = new THREEref.Mesh(new THREEref.TubeGeometry(new THREEref.CatmullRomCurve3([
      new THREEref.Vector3(outNozX, koY + koR + 0.5, 0),
      new THREEref.Vector3(outNozX, 2.7, 0),
      new THREEref.Vector3(0.0, 2.4, 0)                   // into the stack
    ], false, "catmullrom", 0.25), 44, 0.16, 12, false), metal(COL.steelDark));
    g.add(riser);

    // ── flare stack + flange rings ──
    var mastG = new THREEref.CylinderGeometry(0.3, 0.42, H, 16);
    var mast = new THREEref.Mesh(mastG, metal(COL.steelDark));
    mast.position.y = H / 2; g.add(mast);
    for (i = 1; i <= 3; i++) {
      var ring = new THREEref.Mesh(new THREEref.TorusGeometry(0.35, 0.05, 6, 16), metal(COL.steel));
      ring.position.y = (H / 4) * i; ring.rotation.x = Math.PI / 2; g.add(ring);
    }
    // pilot-gas + ignition lines running up the stack to the tip pilots
    var pilotMat = metal(0xAEB8C4);
    for (i = 0; i < 2; i++) {
      var pwire = new THREEref.Mesh(new THREEref.CylinderGeometry(0.035, 0.035, H + 1.2, 6), pilotMat);
      pwire.position.set(0.5, (H + 1.2) / 2, i === 0 ? 0.18 : -0.18); g.add(pwire);
    }
    for (i = 1; i <= 3; i++) {
      var standoff = new THREEref.Mesh(new THREEref.BoxGeometry(0.25, 0.05, 0.5), metal(COL.skid));
      standoff.position.set(0.42, (H / 4) * i, 0); g.add(standoff);
    }

    // ── guy cables: collar at 0.75H -> 3 ground anchors ──
    var collarY = H * 0.75;
    var collar = new THREEref.Mesh(new THREEref.TorusGeometry(0.45, 0.05, 6, 16), metal(COL.steel));
    collar.position.y = collarY; collar.rotation.x = Math.PI / 2; g.add(collar);
    var cableMat = new THREEref.MeshStandardMaterial({ color: 0x8895A5, metalness: 0.6, roughness: 0.5 });
    for (i = 0; i < 3; i++) {
      var ca = (i / 3) * Math.PI * 2 + 0.5;
      var ax = Math.cos(ca) * 4.5, az = Math.sin(ca) * 4.5;
      var len = Math.sqrt(ax * ax + az * az + collarY * collarY);
      var cable = new THREEref.Mesh(new THREEref.CylinderGeometry(0.025, 0.025, len, 5), cableMat);
      cable.position.set(ax / 2, collarY / 2, az / 2);
      var dir = new THREEref.Vector3(ax, -collarY, az).normalize();
      cable.quaternion.setFromUnitVectors(new THREEref.Vector3(0, 1, 0), dir);
      g.add(cable);
      var anc = new THREEref.Mesh(new THREEref.BoxGeometry(0.3, 0.3, 0.3), skidMat());
      anc.position.set(ax, 0.15, az); g.add(anc);
    }

    // ── flare tip / burner head + windshield crown + pilot ──
    var tipG = new THREEref.CylinderGeometry(0.55, 0.42, 1.4, 16);
    var tip = new THREEref.Mesh(tipG, metal(COL.steel));
    tip.position.y = H + 0.7; g.add(tip);
    addEdges(g, tipG, tip, COL.accent, 0.35);
    var crown = new THREEref.Mesh(new THREEref.CylinderGeometry(0.64, 0.55, 0.45, 16, 1, true),
      new THREEref.MeshStandardMaterial({ color: COL.steelDark, metalness: 0.6, roughness: 0.5, side: THREEref.DoubleSide }));
    crown.position.y = H + 1.5; g.add(crown);
    var pilot = new THREEref.Mesh(new THREEref.SphereGeometry(0.12, 8, 6), glowMat(0xFFD27A, 0.95));
    pilot.position.set(0.46, H + 1.6, 0); g.add(pilot);

    // ── FLAME: layered additive plume that flickers + leans DOWNWIND ──
    var flameY = H + 1.7;   // burner mouth
    var yaw = new THREEref.Group(); yaw.position.y = flameY; g.add(yaw);
    var lean = new THREEref.Group(); yaw.add(lean);
    function flameMat(color) {
      return new THREEref.MeshBasicMaterial({
        color: color, transparent: true, opacity: 0.5,
        blending: THREEref.AdditiveBlending, depthWrite: false
      });
    }
    // Torch-flame silhouette: a lathe (revolved) teardrop — narrow neck, a bulge,
    // then a long taper to a point. Layered additive shells read like a real
    // flame, far better than plain cones. One geometry, scaled per layer.
    var FLAME_PROFILE = [
      new THREEref.Vector2(0.03, 0.0),
      new THREEref.Vector2(0.26, 0.45),
      new THREEref.Vector2(0.50, 1.05),
      new THREEref.Vector2(0.47, 1.75),
      new THREEref.Vector2(0.34, 2.55),
      new THREEref.Vector2(0.18, 3.25),
      new THREEref.Vector2(0.06, 3.75),
      new THREEref.Vector2(0.0, 4.05)
    ];
    var flameGeo = new THREEref.LatheGeometry(FLAME_PROFILE, 20);
    var layers = [];
    // Each layer ramps cool (low intake) -> hot (high intake); status tints are
    // applied per-frame (warn=amber, bad=sooty). See animate().
    function addLayer(sc, coolHex, hotHex, op, j) {
      var m = new THREEref.Mesh(flameGeo, flameMat(hotHex));
      m.scale.setScalar(sc); lean.add(m);
      layers.push({ mesh: m, baseOp: op, phase: j * 1.7, base: sc,
                    cool: new THREEref.Color(coolHex), hot: new THREEref.Color(hotHex) });
    }
    addLayer(1.0,  0x5A1206, 0xFF6A22, 0.30, 0);  // outer envelope: sooty red -> hot orange
    addLayer(0.74, 0xC23A0A, 0xFFA63C, 0.5, 1);   // mid:   ember -> amber
    addLayer(0.50, 0xFF8A3C, 0xFFF3C8, 0.85, 2);  // core:  orange -> near white-hot
    addLayer(0.28, 0xFFD27A, 0xFFFFFF, 0.85, 3);  // inner white-hot tip
    var pl = new THREEref.PointLight(0xFF7A2C, 1.6, 42); pl.position.y = flameY + 1.4; g.add(pl);

    _flares.push({ yaw: yaw, lean: lean, layers: layers, light: pl });
    return g;
  }

  function buildEFM() {
    var g = new THREEref.Group();
    var skid = new THREEref.Mesh(new THREEref.BoxGeometry(2.4, 0.4, 1.6), skidMat());
    skid.position.y = 0.2; g.add(skid);
    var run = new THREEref.Mesh(new THREEref.CylinderGeometry(0.3, 0.3, 2.2, 14), metal(COL.steel));
    run.rotation.z = Math.PI / 2; run.position.set(0, 0.9, 0); g.add(run);
    var cab = new THREEref.Mesh(new THREEref.BoxGeometry(0.7, 1.0, 0.5), metal(COL.steelDark));
    cab.position.set(-0.7, 1.3, 0.5); g.add(cab);
    // tilted solar panel
    var panel = new THREEref.Mesh(new THREEref.BoxGeometry(1.4, 0.06, 0.9), new THREEref.MeshStandardMaterial({
      color: 0x16335A, metalness: 0.3, roughness: 0.3, emissive: 0x0A2A4A, emissiveIntensity: 0.25
    }));
    panel.position.set(0.6, 1.9, -0.4); panel.rotation.x = -0.5; g.add(panel);
    var pole = new THREEref.Mesh(new THREEref.CylinderGeometry(0.05, 0.05, 1.6, 8), metal(COL.skid));
    pole.position.set(0.6, 1.1, -0.4); g.add(pole);
    return g;
  }

  function buildTower() {
    var g = new THREEref.Group();
    var h = 13.0, spread = 1.1, i, lvl;
    // 4 lattice legs
    var legs = [[1, 1], [1, -1], [-1, 1], [-1, -1]];
    for (i = 0; i < legs.length; i++) {
      var leg = new THREEref.Mesh(new THREEref.CylinderGeometry(0.06, 0.09, h, 6), metal(COL.steelDark));
      leg.position.set(legs[i][0] * spread * 0.5, h / 2, legs[i][1] * spread * 0.5);
      leg.rotation.z = legs[i][0] * 0.045; leg.rotation.x = -legs[i][1] * 0.045;
      g.add(leg);
    }
    // ring braces
    for (lvl = 1; lvl <= 4; lvl++) {
      var ry = (h / 5) * lvl;
      var ring = new THREEref.Mesh(new THREEref.TorusGeometry(spread * 0.5 * (1 - lvl * 0.07), 0.04, 6, 14), metal(COL.skid));
      ring.position.y = ry; ring.rotation.x = Math.PI / 2; g.add(ring);
    }
    // dish
    var dish = new THREEref.Mesh(new THREEref.CylinderGeometry(0.9, 0.9, 0.18, 20), metal(COL.steel));
    dish.position.set(0.8, h * 0.78, 0); dish.rotation.z = Math.PI / 2; g.add(dish);
    // beacon
    var beacon = new THREEref.Mesh(new THREEref.SphereGeometry(0.22, 12, 8), glowMat(COL.blink, 0.95));
    beacon.position.y = h + 0.3; g.add(beacon);
    blinkMeshes.push(beacon);
    return g;
  }

  // Line heater / scrubber — CUTAWAY indirect water-bath heater: bottom half
  // solid metal (holds the water bath), top half glass so you see inside: the
  // glowing fire-tube/burner, the process coil the gas runs through, and the
  // water level. Animated: combustion glow pulses, bubbles rise, gas flows
  // through the coil (all in animate()).
  function buildHeater() {
    var g = new THREEref.Group();
    var len = 4.2, r = 1.0, yC = r + 0.7, i;

    // split shell: bottom metal (water bath), top glass (after rotz=+90°, theta=0 -> top)
    var botG = new THREEref.CylinderGeometry(r, r, len, 28, 1, true, Math.PI / 2, Math.PI);
    var bot = new THREEref.Mesh(botG, new THREEref.MeshStandardMaterial({
      color: COL.steel, metalness: 0.55, roughness: 0.45, side: THREEref.DoubleSide }));
    bot.rotation.z = Math.PI / 2; bot.position.y = yC; g.add(bot);
    var glassMat = new THREEref.MeshStandardMaterial({
      color: 0xBFD8E6, metalness: 0.1, roughness: 0.08, transparent: true, opacity: 0.15,
      side: THREEref.DoubleSide, depthWrite: false });
    var topG = new THREEref.CylinderGeometry(r, r, len, 28, 1, true, -Math.PI / 2, Math.PI);
    var top = new THREEref.Mesh(topG, glassMat);
    top.rotation.z = Math.PI / 2; top.position.y = yC; g.add(top);
    addEdges(g, new THREEref.CylinderGeometry(r, r, len, 28), bot, COL.accent, 0.32);
    var capA = new THREEref.Mesh(new THREEref.SphereGeometry(r, 16, 10), glassMat);
    capA.position.set(-len / 2, yC, 0); g.add(capA);
    var capB = new THREEref.Mesh(new THREEref.SphereGeometry(r, 16, 10), glassMat);
    capB.position.set(len / 2, yC, 0); g.add(capB);

    // skid + burner stack + process nozzle (exterior)
    var skid = new THREEref.Mesh(new THREEref.BoxGeometry(len * 0.7, 0.6, r * 2.2), skidMat());
    skid.position.y = 0.3; g.add(skid);
    var stack = new THREEref.Mesh(new THREEref.CylinderGeometry(0.18, 0.22, 2.4, 12), metal(COL.steelDark));
    stack.position.set(-len * 0.28, yC + r + 1.0, 0); g.add(stack);
    var noz = new THREEref.Mesh(new THREEref.CylinderGeometry(0.12, 0.12, 0.9, 10), metal(COL.steelDark));
    noz.position.set(len * 0.22, yC + r + 0.4, 0); g.add(noz);   // TOP gas-outlet nozzle (to the separator)
    // proper inlet-scrubber connections (per the horizontal-vessel reference):
    // END inlet -> inlet diverter -> mist extractor -> TOP gas outlet, liquid drains
    // out the BOTTOM. Inlet enters the end head (from the wellhead), not the top.
    var inNoz = new THREEref.Mesh(new THREEref.CylinderGeometry(0.13, 0.13, 0.8, 10), metal(COL.steelDark));
    inNoz.rotation.z = Math.PI / 2; inNoz.position.set(-len / 2 - 0.3, yC, 0); g.add(inNoz);          // inlet on the end head
    var inFl = new THREEref.Mesh(new THREEref.CylinderGeometry(0.22, 0.22, 0.08, 14), metal(COL.steelDark));
    inFl.rotation.z = Math.PI / 2; inFl.position.set(-len / 2 - 0.62, yC, 0); g.add(inFl);            // inlet flange face
    var diverter = new THREEref.Mesh(new THREEref.BoxGeometry(0.08, 0.85, 1.2), metal(0xAEB8C4));
    diverter.position.set(-len * 0.36, yC + 0.15, 0); diverter.rotation.z = 0.3; g.add(diverter);     // inlet diverter plate
    var mist = new THREEref.Mesh(new THREEref.BoxGeometry(0.16, 0.8, 1.4),
      new THREEref.MeshStandardMaterial({ color: 0xC7D0DA, transparent: true, opacity: 0.5, metalness: 0.3, roughness: 0.7 }));
    mist.position.set(len * 0.22, yC + 0.55, 0); g.add(mist);                                          // mist extractor before the gas outlet
    var drain = new THREEref.Mesh(new THREEref.CylinderGeometry(0.09, 0.09, 0.5, 8), metal(COL.steelDark));
    drain.position.set(len * 0.3, yC - r - 0.2, 0); g.add(drain);                                      // bottom liquid-knockout drain
    var drainV = new THREEref.Mesh(new THREEref.TorusGeometry(0.12, 0.03, 6, 12), metal(0xCC4444));
    drainV.position.set(len * 0.3, yC - r - 0.45, 0); drainV.rotation.x = Math.PI / 2; g.add(drainV);  // drain valve

    // ── INTERNALS (visible through the glass top) ──
    var bathY = yC + 0.15;                 // water-bath level (~65% full)
    var bathBot = yC - r + 0.06;
    var bathH = bathY - bathBot;
    var bath = new THREEref.Mesh(new THREEref.BoxGeometry(len * 0.88, bathH, 1.7),
      new THREEref.MeshStandardMaterial({ color: 0x1E7FA8, transparent: true, opacity: 0.4,
        metalness: 0.1, roughness: 0.2, emissive: 0x0E4E70, emissiveIntensity: 0.12 }));
    bath.position.set(0, bathBot + bathH / 2, 0); g.add(bath);
    var level = new THREEref.Mesh(new THREEref.BoxGeometry(len * 0.88, 0.04, 1.7), glowMat(0x38D6E0, 0.55));
    level.position.set(0, bathY, 0); g.add(level);

    // fire tube + burner muzzle (immersed, glows with combustion)
    var fireMat = new THREEref.MeshStandardMaterial({ color: 0xFF7A33, emissive: 0xFF4500,
      emissiveIntensity: 0.8, metalness: 0.4, roughness: 0.5 });
    var fire = new THREEref.Mesh(new THREEref.CylinderGeometry(0.24, 0.24, len * 0.66, 14), fireMat);
    fire.rotation.z = Math.PI / 2; fire.position.set(0.1, yC - 0.45, 0.45); g.add(fire);
    var muzzle = new THREEref.Mesh(new THREEref.CylinderGeometry(0.28, 0.34, 0.5, 14), metal(COL.steelDark));
    muzzle.rotation.z = Math.PI / 2; muzzle.position.set(-len * 0.4, yC - 0.45, 0.45); g.add(muzzle);

    // process coil (the gas being heated spirals through the bath)
    var pts = [], turns = 3, n = 48, coilR = 0.52, coilLen = len * 0.62, a;
    for (i = 0; i <= n; i++) {
      var t = i / n; a = t * turns * 2 * Math.PI;
      pts.push(new THREEref.Vector3(-coilLen / 2 + t * coilLen, yC - 0.05 + Math.sin(a) * coilR * 0.5, -0.35 + Math.cos(a) * coilR));
    }
    var curve = new THREEref.CatmullRomCurve3(pts);
    var coil = new THREEref.Mesh(new THREEref.TubeGeometry(curve, 90, 0.08, 8, false), metal(COL.accent));
    g.add(coil);

    // animated material: gas packets flow through the coil; bubbles rise in the bath
    var flow = [], bubbles = [];
    for (i = 0; i < 5; i++) {
      var fp = new THREEref.Mesh(new THREEref.SphereGeometry(0.1, 8, 6), glowMat(PRODUCT.gas || 0x7DE0FF, 0.85));
      g.add(fp); flow.push({ mesh: fp, offset: i / 5 });
    }
    for (i = 0; i < 7; i++) {
      var bb = new THREEref.Mesh(new THREEref.SphereGeometry(0.06, 6, 5), glowMat(0x9FE8F0, 0.5));
      g.add(bb); bubbles.push({ mesh: bb, offset: i / 7, x: (i / 7 - 0.5) * len * 0.7, z: ((i % 3) - 1) * 0.45 });
    }
    _heater = { fire: fire, level: level, curve: curve, flow: flow, bubbles: bubbles,
                bathBot: bathBot, bathY: bathY };
    return g;
  }

  // PLC shelter — small metal control building on a skid with a door + AC unit.
  function buildShelter() {
    var g = new THREEref.Group();
    var w = 2.6, h = 2.4, d = 2.2;
    var base = new THREEref.Mesh(new THREEref.BoxGeometry(w + 0.3, 0.5, d + 0.3), skidMat());
    base.position.y = 0.25; g.add(base);
    var box = new THREEref.Mesh(new THREEref.BoxGeometry(w, h, d), metal(COL.steel));
    box.position.y = h / 2 + 0.5; g.add(box);
    addEdges(g, new THREEref.BoxGeometry(w, h, d), box, COL.accent, 0.3);
    var roof = new THREEref.Mesh(new THREEref.BoxGeometry(w + 0.2, 0.2, d + 0.2), metal(COL.steelDark));
    roof.position.y = h + 0.5 + 0.1; g.add(roof);
    var door = new THREEref.Mesh(new THREEref.BoxGeometry(0.9, 1.7, 0.06), metal(COL.steelDark));
    door.position.set(0, 1.35, d / 2 + 0.03); g.add(door);
    var ac = new THREEref.Mesh(new THREEref.BoxGeometry(0.7, 0.5, 0.4), metal(COL.skid));
    ac.position.set(w / 2 - 0.45, 1.7, -d / 2 - 0.22); g.add(ac);
    return g;
  }

  // Power system — solar array on poles + a battery cabinet on a skid.
  function buildPower() {
    var g = new THREEref.Group();
    var base = new THREEref.Mesh(new THREEref.BoxGeometry(1.7, 0.4, 1.2), skidMat());
    base.position.set(-1.4, 0.2, 0); g.add(base);
    var cabG = new THREEref.BoxGeometry(1.4, 1.6, 0.9);
    var cab = new THREEref.Mesh(cabG, metal(COL.steelDark));
    cab.position.set(-1.4, 1.2, 0); g.add(cab);
    addEdges(g, cabG, cab, COL.accent, 0.3);
    var panelMat = new THREEref.MeshStandardMaterial({
      color: 0x16335A, metalness: 0.3, roughness: 0.3, emissive: 0x0A2A4A, emissiveIntensity: 0.25
    });
    var i, px;
    for (i = 0; i < 2; i++) {
      px = 0.7 + i * 1.7;
      var panel = new THREEref.Mesh(new THREEref.BoxGeometry(1.5, 0.06, 1.0), panelMat);
      panel.position.set(px, 1.9, 0); panel.rotation.x = -0.5; g.add(panel);
      var pole = new THREEref.Mesh(new THREEref.CylinderGeometry(0.06, 0.06, 1.8, 8), metal(COL.skid));
      pole.position.set(px, 1.0, 0.12); g.add(pole);
    }
    return g;
  }

  // Solar array — a ground-mount row of tilted PV panels on a support frame.
  function buildSolar() {
    var g = new THREEref.Group();
    var panelMat = new THREEref.MeshStandardMaterial({
      color: 0x16335A, metalness: 0.3, roughness: 0.3, emissive: 0x0A2A4A, emissiveIntensity: 0.25
    });
    var rows = 4, i, px;
    for (i = 0; i < rows; i++) {
      px = (i - (rows - 1) / 2) * 1.7;
      var pg = new THREEref.BoxGeometry(1.5, 0.08, 1.7);
      var panel = new THREEref.Mesh(pg, panelMat);
      panel.position.set(px, 1.5, 0); panel.rotation.x = -0.55; g.add(panel);
      addEdges(g, pg, panel, 0x3B82F6, 0.4);
      var legF = new THREEref.Mesh(new THREEref.CylinderGeometry(0.05, 0.05, 1.0, 6), metal(COL.skid));
      legF.position.set(px, 0.5, 0.55); g.add(legF);
      var legB = new THREEref.Mesh(new THREEref.CylinderGeometry(0.05, 0.05, 1.7, 6), metal(COL.skid));
      legB.position.set(px, 0.85, -0.55); g.add(legB);
    }
    return g;
  }

  // Communications — VSAT dish + comms cabinet + whip antenna (blinking tip).
  function buildComms() {
    var g = new THREEref.Group();
    var base = new THREEref.Mesh(new THREEref.BoxGeometry(1.3, 0.3, 1.0), skidMat());
    base.position.y = 0.15; g.add(base);
    var cabG = new THREEref.BoxGeometry(1.0, 1.4, 0.7);
    var cab = new THREEref.Mesh(cabG, metal(COL.steelDark));
    cab.position.set(0, 0.9, 0); g.add(cab);
    addEdges(g, cabG, cab, COL.accent, 0.3);
    // VSAT dish (a shallow spherical cap) on a mast
    var mast = new THREEref.Mesh(new THREEref.CylinderGeometry(0.08, 0.08, 1.8, 8), metal(COL.skid));
    mast.position.set(1.2, 0.9, 0); g.add(mast);
    var dishMat = new THREEref.MeshStandardMaterial({ color: COL.steel, metalness: 0.4, roughness: 0.4, side: THREEref.DoubleSide });
    var dish = new THREEref.Mesh(new THREEref.SphereGeometry(0.9, 18, 10, 0, Math.PI * 2, 0, Math.PI * 0.33), dishMat);
    dish.position.set(1.2, 1.85, 0); dish.rotation.z = -0.7; dish.rotation.x = 0.35; g.add(dish);
    var feed = new THREEref.Mesh(new THREEref.CylinderGeometry(0.03, 0.03, 0.7, 6), metal(COL.steelDark));
    feed.position.set(1.6, 2.05, 0); feed.rotation.z = -0.9; g.add(feed);
    // whip antenna with a blinking tip
    var whip = new THREEref.Mesh(new THREEref.CylinderGeometry(0.02, 0.035, 2.4, 6), metal(COL.steelDark));
    whip.position.set(-0.45, 2.05, 0); g.add(whip);
    var tip = new THREEref.Mesh(new THREEref.SphereGeometry(0.1, 8, 6), glowMat(COL.blink, 0.9));
    tip.position.set(-0.45, 3.25, 0); g.add(tip);
    blinkMeshes.push(tip);
    return g;
  }

  // Windsock — a met instrument on a pole; the striped sock streams DOWNWIND.
  // NOT a topology asset (no health ring) — it's a real windsock, oriented from
  // the live wind every frame (see animate()). Brand teal + purple bands.
  function buildWindsock() {
    var g = new THREEref.Group();
    var pole = new THREEref.Mesh(new THREEref.CylinderGeometry(0.12, 0.16, 6.2, 12), metal(COL.steelDark));
    pole.position.y = 3.1; g.add(pole);
    var base = new THREEref.Mesh(new THREEref.BoxGeometry(0.9, 0.3, 0.9), skidMat());
    base.position.y = 0.15; g.add(base);
    // pivot at the top — rotated to the wind-toward bearing each frame
    var pivot = new THREEref.Group(); pivot.position.set(0, 5.9, 0); g.add(pivot);
    var collar = new THREEref.Mesh(new THREEref.CylinderGeometry(0.11, 0.11, 0.5, 10), metal(COL.steel));
    collar.rotation.z = Math.PI / 2; collar.position.x = 0.06; pivot.add(collar);
    // droop group — sock hangs in light wind, near-horizontal when windy, + billow
    var droop = new THREEref.Group(); pivot.add(droop);
    var bands = 5, i, x0, xc, rB, rS, col;
    for (i = 0; i < bands; i++) {
      rB = 0.5 - i * 0.072; rS = 0.5 - (i + 1) * 0.072;
      x0 = 0.25 + i * 0.66; xc = x0 + 0.33;
      col = (i % 2 === 0) ? 0x06B6D4 : 0x6366F1;
      var bg = new THREEref.CylinderGeometry(rS, rB, 0.66, 16, 1, true);
      var bm = new THREEref.Mesh(bg, new THREEref.MeshStandardMaterial({
        color: col, metalness: 0.1, roughness: 0.7, side: THREEref.DoubleSide,
        emissive: col, emissiveIntensity: 0.14
      }));
      bm.rotation.z = -Math.PI / 2; bm.position.x = xc; droop.add(bm);
    }
    var ring = new THREEref.Mesh(new THREEref.TorusGeometry(0.5, 0.05, 8, 20), metal(COL.steel));
    ring.rotation.y = Math.PI / 2; ring.position.x = 0.25; droop.add(ring);
    g.userData = { id: "WSK", type: "windsock", pivot: pivot, droop: droop };
    return g;
  }

  // TEG glycol DEHYDRATOR — tall contactor (absorber) column with trays + a
  // reboiler/regenerator skid + glycol pump. Dries sales gas to pipeline dewpoint.
  function buildDehydrator() {
    var g = new THREEref.Group();
    var skid = new THREEref.Mesh(new THREEref.BoxGeometry(3.4, 0.4, 2.0), skidMat()); skid.position.y = 0.2; g.add(skid);
    var glassMat = new THREEref.MeshStandardMaterial({ color: 0xBFD8E6, metalness: 0.1, roughness: 0.08, transparent: true, opacity: 0.16, side: THREEref.DoubleSide, depthWrite: false });
    var colG = new THREEref.CylinderGeometry(0.55, 0.55, 5.4, 18, 1, true);
    var col = new THREEref.Mesh(colG, glassMat); col.position.set(-0.9, 3.1, 0); g.add(col); addEdges(g, colG, col, COL.accent, 0.32);
    var head = new THREEref.Mesh(new THREEref.SphereGeometry(0.55, 16, 10, 0, Math.PI * 2, 0, Math.PI / 2), metal(COL.steelDark)); head.position.set(-0.9, 5.8, 0); g.add(head);
    for (var ti = 0; ti < 5; ti++) { var tray = new THREEref.Mesh(new THREEref.CylinderGeometry(0.5, 0.5, 0.05, 16), metal(0x9AA6B2)); tray.position.set(-0.9, 1.5 + ti * 0.7, 0); g.add(tray); }
    var reb = new THREEref.Mesh(new THREEref.CylinderGeometry(0.5, 0.5, 2.0, 16), metal(COL.steel)); reb.rotation.z = Math.PI / 2; reb.position.set(0.95, 0.95, 0); g.add(reb);
    var rstack = new THREEref.Mesh(new THREEref.CylinderGeometry(0.12, 0.14, 1.6, 10), metal(COL.steelDark)); rstack.position.set(0.95, 2.0, 0); g.add(rstack);
    var pump = new THREEref.Mesh(new THREEref.BoxGeometry(0.5, 0.4, 0.4), metal(COL.steel)); pump.position.set(0.95, 0.6, 0.85); g.add(pump);
    return g;
  }
  // VAPOR RECOVERY UNIT — small gas compressor skid pulling tank vapors back.
  function buildVRU() {
    var g = new THREEref.Group();
    var skid = new THREEref.Mesh(new THREEref.BoxGeometry(2.4, 0.4, 1.6), skidMat()); skid.position.y = 0.2; g.add(skid);
    var motor = new THREEref.Mesh(new THREEref.CylinderGeometry(0.4, 0.4, 1.2, 16), metal(COL.steel)); motor.rotation.z = Math.PI / 2; motor.position.set(-0.6, 0.9, 0); g.add(motor);
    var comp = new THREEref.Mesh(new THREEref.BoxGeometry(0.9, 0.8, 0.8), metal(COL.steelDark)); comp.position.set(0.6, 0.9, 0); g.add(comp); addEdges(g, new THREEref.BoxGeometry(0.9, 0.8, 0.8), comp, COL.accent, 0.25);
    var scrub = new THREEref.Mesh(new THREEref.CylinderGeometry(0.28, 0.28, 1.4, 12), metal(COL.steel)); scrub.position.set(1.0, 1.0, 0.6); g.add(scrub);
    return g;
  }
  // ENCLOSED COMBUSTOR — insulated vertical can with an internal burner (clean
  // burn of tank/relief vapors, ~98% destruction) + wind fence base.
  function buildCombustor() {
    var g = new THREEref.Group();
    var base = new THREEref.Mesh(new THREEref.BoxGeometry(2.0, 0.4, 2.0), skidMat()); base.position.y = 0.2; g.add(base);
    var canG = new THREEref.CylinderGeometry(0.7, 0.8, 4.2, 18);
    var can = new THREEref.Mesh(canG, metal(0x8A93A0)); can.position.y = 2.5; g.add(can); addEdges(g, canG, can, COL.accent, 0.25);
    var lip = new THREEref.Mesh(new THREEref.CylinderGeometry(0.75, 0.7, 0.3, 18), metal(COL.steelDark)); lip.position.y = 4.7; g.add(lip);
    var fl = new THREEref.Mesh(new THREEref.ConeGeometry(0.45, 1.2, 12), glowMat(0xFF7A33, 0.7)); fl.position.y = 4.4; g.add(fl);
    return g;
  }
  // SALTWATER DISPOSAL pump — triplex injection pump + motor + a small wellhead.
  function buildSWD() {
    var g = new THREEref.Group();
    var skid = new THREEref.Mesh(new THREEref.BoxGeometry(2.6, 0.4, 1.4), skidMat()); skid.position.y = 0.2; g.add(skid);
    var motor = new THREEref.Mesh(new THREEref.CylinderGeometry(0.35, 0.35, 1.2, 14), metal(COL.steel)); motor.rotation.z = Math.PI / 2; motor.position.set(-0.6, 0.8, 0); g.add(motor);
    var pump = new THREEref.Mesh(new THREEref.BoxGeometry(1.0, 0.6, 0.7), metal(COL.steelDark)); pump.position.set(0.5, 0.75, 0); g.add(pump);
    var plungers = new THREEref.Mesh(new THREEref.CylinderGeometry(0.12, 0.12, 1.1, 8), metal(0x9AA6B2)); plungers.rotation.z = Math.PI / 2; plungers.position.set(0.5, 0.95, 0); g.add(plungers);
    var wh = new THREEref.Mesh(new THREEref.CylinderGeometry(0.18, 0.22, 0.9, 12), metal(COL.steelDark)); wh.position.set(1.3, 0.65, 0.5); g.add(wh);
    var whw = new THREEref.Mesh(new THREEref.TorusGeometry(0.16, 0.04, 8, 14), metal(0xCC4444)); whw.position.set(1.3, 1.0, 0.5); whw.rotation.x = Math.PI / 2; g.add(whw);
    return g;
  }
  // FUEL-GAS CONDITIONING SKID — a small scrubber/KO pot drops liquids out of the
  // fuel-gas tap, a regulator drops the pressure, and conditioned gas leaves to the
  // heater / TEG reboiler / pneumatics. Inlet (from compressor discharge) on the
  // WEST end, conditioned-gas outlet on the EAST end.
  function buildFuelGas() {
    var g = new THREEref.Group();
    var skid = new THREEref.Mesh(new THREEref.BoxGeometry(2.0, 0.36, 1.1), skidMat()); skid.position.y = 0.18; g.add(skid);
    // vertical fuel-gas scrubber (small KO pot) with a glass cutaway + liquid boot
    var pot = new THREEref.Mesh(new THREEref.CylinderGeometry(0.32, 0.32, 1.5, 18), metal(COL.steel));
    pot.position.set(-0.5, 1.1, 0); g.add(pot);
    var potCap = new THREEref.Mesh(new THREEref.SphereGeometry(0.32, 14, 8, 0, Math.PI * 2, 0, Math.PI / 2), metal(COL.steelDark));
    potCap.position.set(-0.5, 1.85, 0); g.add(potCap);
    var boot = new THREEref.Mesh(new THREEref.CylinderGeometry(0.12, 0.12, 0.3, 10), metal(COL.steelDark));
    boot.position.set(-0.5, 0.5, 0); g.add(boot);          // liquid drain boot
    // regulator (spring-dome) + run to the outlet
    var reg = new THREEref.Mesh(new THREEref.SphereGeometry(0.2, 14, 10), metal(0x6B7785));
    reg.position.set(0.35, 0.95, 0); g.add(reg);
    var regCap = new THREEref.Mesh(new THREEref.CylinderGeometry(0.13, 0.16, 0.18, 12), metal(0x9AA6B2));
    regCap.position.set(0.35, 1.2, 0); g.add(regCap);
    var run = new THREEref.Mesh(new THREEref.CylinderGeometry(0.07, 0.07, 1.7, 10), metal(0x9AA6B2));
    run.rotation.z = Math.PI / 2; run.position.set(0.0, 0.78, 0); g.add(run);
    var gaugeF = new THREEref.Mesh(new THREEref.CylinderGeometry(0.1, 0.1, 0.05, 14), metal(0xBFD8E6));
    gaugeF.rotation.x = Math.PI / 2; gaugeF.position.set(0.35, 1.4, 0.16); g.add(gaugeF);  // fuel-gas pressure gauge
    return g;
  }
  // ESD / SIS PANEL — a safety cabinet SEPARATE from the control RTU (ISA-84): an
  // orange instrument enclosure with a red mushroom E-STOP and an amber beacon.
  // It trips the wellhead SSV on an upset. No process piping (logic/IO only).
  function buildESD() {
    var g = new THREEref.Group();
    var legs = [[-0.5, -0.4], [0.5, -0.4], [-0.5, 0.4], [0.5, 0.4]];
    legs.forEach(function (p) {
      var l = new THREEref.Mesh(new THREEref.CylinderGeometry(0.05, 0.05, 0.7, 6), metal(COL.steelDark));
      l.position.set(p[0], 0.35, p[1]); g.add(l);
    });
    var cab = new THREEref.Mesh(new THREEref.BoxGeometry(1.2, 1.1, 0.5),
      new THREEref.MeshStandardMaterial({ color: 0xC2620E, metalness: 0.4, roughness: 0.5 }));  // safety orange
    cab.position.set(0, 1.25, 0); g.add(cab);
    addEdges(g, new THREEref.BoxGeometry(1.2, 1.1, 0.5), cab, COL.accent, 0.4);
    // red mushroom E-STOP on the face
    var estop = new THREEref.Mesh(new THREEref.CylinderGeometry(0.14, 0.1, 0.1, 14), glowMat(0xEF4444, 0.7));
    estop.rotation.x = Math.PI / 2; estop.position.set(-0.3, 1.35, 0.27); g.add(estop);
    // amber status beacon on top
    var bcol = new THREEref.Mesh(new THREEref.CylinderGeometry(0.04, 0.04, 0.18, 6), metal(COL.steelDark));
    bcol.position.set(0.4, 1.9, 0); g.add(bcol);
    var beacon = new THREEref.Mesh(new THREEref.SphereGeometry(0.1, 12, 8), glowMat(0xFBBF24, 0.85));
    beacon.position.set(0.4, 2.05, 0); g.add(beacon);
    // 'SIS' nameplate strip
    var plate = new THREEref.Mesh(new THREEref.BoxGeometry(0.8, 0.16, 0.02), metal(0x111827));
    plate.position.set(0.15, 1.6, 0.26); g.add(plate);
    return g;
  }
  // CONDENSATE LACT UNIT — Lease Automatic Custody Transfer skid: a charge pump, a
  // positive-displacement/Coriolis meter, an air eliminator, a sampler can and a
  // valve manifold. Inlet (from the condensate tank) WEST, custody/load-out EAST.
  function buildLACT() {
    var g = new THREEref.Group();
    var skid = new THREEref.Mesh(new THREEref.BoxGeometry(2.4, 0.36, 1.2), skidMat()); skid.position.y = 0.18; g.add(skid);
    var pump = new THREEref.Mesh(new THREEref.BoxGeometry(0.7, 0.5, 0.6), metal(COL.steelDark)); pump.position.set(-0.7, 0.65, 0); g.add(pump);
    var motor = new THREEref.Mesh(new THREEref.CylinderGeometry(0.22, 0.22, 0.7, 12), metal(COL.steel)); motor.rotation.z = Math.PI / 2; motor.position.set(-1.05, 0.65, 0); g.add(motor);
    // meter body (horizontal) + electronics head
    var meter = new THREEref.Mesh(new THREEref.CylinderGeometry(0.26, 0.26, 0.7, 14), metal(0x9AA6B2)); meter.rotation.z = Math.PI / 2; meter.position.set(0.2, 0.75, 0); g.add(meter);
    var head = new THREEref.Mesh(new THREEref.BoxGeometry(0.28, 0.3, 0.28), metal(0x111827)); head.position.set(0.2, 1.15, 0); g.add(head);
    // air eliminator (vertical pot) + sampler can
    var ae = new THREEref.Mesh(new THREEref.CylinderGeometry(0.16, 0.16, 0.7, 12), metal(COL.steel)); ae.position.set(-0.2, 1.0, 0.35); g.add(ae);
    var sampler = new THREEref.Mesh(new THREEref.CylinderGeometry(0.12, 0.12, 0.5, 10), metal(0x6B7785)); sampler.position.set(0.7, 0.85, 0.3); g.add(sampler);
    // run header + take-off flange (load-out)
    var run = new THREEref.Mesh(new THREEref.CylinderGeometry(0.1, 0.1, 2.1, 12), metal(0x9AA6B2)); run.rotation.z = Math.PI / 2; run.position.set(0.0, 0.5, 0); g.add(run);
    return g;
  }
  // PRODUCED-WATER METER — a simple metered spool: a horizontal run on supports with
  // a turbine/mag meter body and an electronics head, measuring disposal volume out
  // of the SWD pump. Inlet WEST, outlet EAST (to the disposal well).
  function buildWaterMeter() {
    var g = new THREEref.Group();
    [-0.7, 0.7].forEach(function (x) {
      var sup = new THREEref.Mesh(new THREEref.BoxGeometry(0.12, 0.55, 0.3), metal(COL.steelDark));
      sup.position.set(x, 0.28, 0); g.add(sup);
    });
    var run = new THREEref.Mesh(new THREEref.CylinderGeometry(0.16, 0.16, 1.9, 14), metal(0x3B82F6)); run.rotation.z = Math.PI / 2; run.position.set(0, 0.7, 0); g.add(run);
    var body = new THREEref.Mesh(new THREEref.CylinderGeometry(0.22, 0.22, 0.5, 16), metal(0x9AA6B2)); body.rotation.z = Math.PI / 2; body.position.set(0, 0.7, 0); g.add(body);
    var head = new THREEref.Mesh(new THREEref.BoxGeometry(0.24, 0.28, 0.24), metal(0x111827)); head.position.set(0, 1.06, 0); g.add(head);
    [-0.55, 0.55].forEach(function (x) {
      var fl = new THREEref.Mesh(new THREEref.CylinderGeometry(0.2, 0.2, 0.08, 14), metal(COL.steelDark)); fl.rotation.z = Math.PI / 2; fl.position.set(x, 0.7, 0); g.add(fl);
    });
    return g;
  }
  function buildEquip(type) {
    if (type === "fuelgas")    { return buildFuelGas(); }
    if (type === "esd")        { return buildESD(); }
    if (type === "lact")       { return buildLACT(); }
    if (type === "watermeter") { return buildWaterMeter(); }
    if (type === "dehydrator") { return buildDehydrator(); }
    if (type === "vru")        { return buildVRU(); }
    if (type === "combustor")  { return buildCombustor(); }
    if (type === "swd")        { return buildSWD(); }
    if (type === "wellhead")   { return buildWellhead(); }
    if (type === "chemtote")   { return buildChemTote(); }
    if (type === "separator")  { return buildSeparator(); }
    if (type === "compressor") { return buildCompressor(); }
    if (type === "oiltank")    { return buildTank("oil", 0.7); }
    if (type === "watertank")  { return buildTank("water", 0.55); }
    if (type === "efm")        { return buildEFM(); }
    if (type === "flare")      { return buildFlare(); }
    if (type === "tower")      { return buildTower(); }
    if (type === "heater" || type === "scrubber") { return buildHeater(); }
    if (type === "shelter" || type === "rtu")     { return buildShelter(); }
    if (type === "power"   || type === "solar")   { return buildPower(); }
    if (type === "solararray")                    { return buildSolar(); }
    if (type === "comms"   || type === "vsat")    { return buildComms(); }
    return new THREEref.Group();
  }

  // ── PIPE BUILDER ────────────────────────────────────────────────────────────
  // Engineered field piping: diameter-scaled runs with flanged tie-ins (bolt
  // circles), elbow fittings at the corners, pipe supports/sleepers, an inline
  // gate valve + insulation cladding on the process headers, and the digital-twin
  // signature — glowing "data-pulse" rings that travel the pipe along its path.
  var _UP = null, _ZAXIS = null;
  function _nodeType(id) { for (var i = 0; i < EQUIP.length; i++) { if (EQUIP[i].id === id) { return EQUIP[i].type; } } return ""; }
  // Tie-in nozzle height + reach-to-edge for each vessel, so a header connects to
  // the real nozzle (wellhead WING valve, heater inlet/outlet ends, separator
  // inlet end) instead of the vessel centre.
  // Tie-in HEIGHT for a pipe at this equipment — depends on which physical nozzle
  // the product actually uses, so gas leaves the TOP and liquid the BOTTOM, etc.
  // (Matches the modeled nozzles in buildSeparator/buildCompressor/buildFlare.)
  function _nozH(t, p, isSource) {
    if (t === "separator") return p === "gas" ? 3.9 : 0.7;        // gas top outlet/inlet vs liquid bottom dump
    if (t === "compressor") return isSource ? 1.5 : 2.4;          // discharge header (out) vs suction scrubber (in)
    if (t === "heater" || t === "scrubber") return 2.75;
    if (t === "wellhead") return 3.78;                           // production take-off (choke flange) height
    if (t === "flare") return 2.0;                                // relief gas into the KO-drum inlet
    if (t === "oiltank" || t === "watertank") return 1.9;        // gravity dump enters the upper shell
    if (t === "efm") return 1.1;
    if (t === "chemtote") return 1.0;
    return 1.4;
  }
  // Tie-in REACH from the equipment center (clears the footprint to the real nozzle).
  function _nozR(t, p) {
    if (t === "separator") return 3.0;                            // outlets sit near the vessel ends (±2.94)
    if (t === "compressor") return 2.4;
    if (t === "heater" || t === "scrubber") return 1.9;
    if (t === "wellhead") return 1.78;                            // production wing/choke reaches out ±1.78
    if (t === "oiltank" || t === "watertank") return 2.95;       // clear the 2.8 m tank radius
    if (t === "flare") return 2.2;
    if (t === "efm") return 0.8;
    if (t === "chemtote") return 0.7;
    return 0.8;
  }
  // EXACT nozzle registry — local offset of the REAL modeled nozzle stub for a pipe
  // of this product/role. Equipment groups are axis-aligned at scale 1, so the world
  // tie = equipmentCenter + offset. Values match the stubs modeled in
  // buildWellhead/buildHeater/buildSeparator/buildCompressor/buildFlare/buildTank.
  function _noz(t, p, isSource) {
    if (t === "wellhead") return isSource ? { x: 1.78, y: 3.78, z: 0 } : { x: -0.82, y: 1.85, z: 0 };       // production take-off flange (choke out) · chem-injection flange in
    if (t === "heater" || t === "scrubber") return isSource ? { x: 0.95, y: 3.1, z: 0 } : { x: -2.1, y: 1.7, z: 0 }; // gas outlet TOP (via mist extractor) · inlet on the END head
    if (t === "separator") {
      if (p === "gas") return isSource ? { x: 2.94, y: 4.0, z: 0 } : { x: -2.8, y: 4.0, z: 0 };            // gas outlet E-top · inlet W-top
      if (p === "water") return { x: 2.94, y: 0.6, z: -0.5 };                                              // water outlet (bottom)
      return { x: 3.2, y: 2.0, z: 0.5 };                                                                   // condensate over the weir (E head, mid)
    }
    if (t === "compressor") return isSource ? { x: 2.6, y: 1.2, z: 0 } : { x: -2.0, y: 2.0, z: 0 };        // discharge header (E) · suction on the SEP-facing (W) side
    if (t === "flare") return { x: 2.4, y: 2.3, z: -0.9 };                                                 // relief into the KO drum on the compressor-facing (N) side
    if (t === "oiltank" || t === "watertank") return { x: 0, y: 4.3, z: 2.6 };                            // gravity dump into upper shell, facing the train
    if (t === "efm") return isSource ? { x: 0.8, y: 1.1, z: 0 } : { x: -0.8, y: 1.1, z: 0 };
    if (t === "chemtote") return { x: 1.4, y: 1.5, z: 0 };                                                 // injection-pump discharge toward the wellhead
    if (t === "dehydrator") return isSource ? { x: 0.2, y: 5.0, z: 0 } : { x: -1.5, y: 0.9, z: 0 };        // dry gas off the top · wet gas into the contactor bottom
    if (t === "vru") return isSource ? { x: 0.6, y: 1.4, z: 0 } : { x: 1.1, y: 1.0, z: 0.6 };              // discharge · suction (tank vapors)
    if (t === "combustor") return { x: -0.9, y: 0.7, z: 0 };                                               // vapor inlet at the base
    if (t === "swd") return { x: -1.0, y: 0.8, z: 0 };                                                     // pump suction (produced water)
    if (t === "fuelgas") return isSource ? { x: 1.0, y: 0.78, z: 0 } : { x: -0.95, y: 0.6, z: 0 };        // conditioned-gas outlet (E) · fuel tap inlet (W)
    if (t === "lact") return isSource ? { x: 1.05, y: 0.5, z: 0 } : { x: -1.05, y: 0.5, z: 0 };           // custody load-out (E) · tank inlet (W)
    if (t === "watermeter") return isSource ? { x: 0.55, y: 0.7, z: 0 } : { x: -0.55, y: 0.7, z: 0 };     // metered outlet (E) · SWD inlet (W)
    return { x: 0, y: 1.4, z: 0 };
  }
  function buildPipe(spec) {
    if (!_UP) { _UP = new THREEref.Vector3(0, 1, 0); _ZAXIS = new THREEref.Vector3(0, 0, 1); }
    var a = equipLocal(spec.from), b = equipLocal(spec.to);
    var nozzle = 1.4, rackH = spec.rackH, pts;
    if (spec.detailed) {
      // ENGINEERED PRODUCTION HEADER (wellhead -> line heater -> separator):
      // come off the source nozzle facing the destination, drop to a LOW run on
      // sleepers (~1.2 m), run straight across, then rise into the dest nozzle —
      // with 90° elbows at the corners. This is how a real wellsite is piped:
      // short, low, nozzle-to-nozzle, not up-and-over a tall pipe rack.
      var fT = _nodeType(spec.from), tT = _nodeType(spec.to);
      // Start the pipe ON the real source nozzle stub and land it ON the real dest
      // nozzle stub, then drop/rise to a low sleeper run with 90° elbows between.
      var sN = _noz(fT, spec.product, true), dN = _noz(tT, spec.product, false);
      var sTie = new THREEref.Vector3(a.x + sN.x, sN.y, a.z + sN.z);                // exact source nozzle
      var dTie = new THREEref.Vector3(b.x + dN.x, dN.y, b.z + dN.z);                // exact dest nozzle
      // TANK NOZZLES — tie ON the shell, on the face POINTING AT the connected
      // equipment, so the run leaves outward and never crosses under/through the
      // tank. Elevation matches the real service: liquid gravity fill enters an
      // UPPER side inlet, a liquid/equalizer outlet leaves LOW near grade, and
      // vapor leaves the ROOF (thief hatch -> VRU). r=2.8 shell + flange standoff.
      function _tankTie(center, peer, product, isOutlet) {
        var dx = peer.x - center.x, dz = peer.z - center.z, L = Math.sqrt(dx * dx + dz * dz) || 1;
        var R = 3.0, y;
        if (product === "gas") { y = 6.15; }            // vapor: roof nozzle -> VRU
        else if (isOutlet) { y = 0.85; }                // liquid / equalizer outlet: low side nozzle
        else { y = 4.2; }                               // liquid gravity fill: upper side inlet
        return new THREEref.Vector3(center.x + dx / L * R, y, center.z + dz / L * R);
      }
      var bothTanks = (fT === "oiltank" || fT === "watertank") && (tT === "oiltank" || tT === "watertank");
      if (fT === "oiltank" || fT === "watertank") { sTie = _tankTie(a, b, spec.product, true); }
      // tank-to-tank liquid line = bottom EQUALIZER (both ends low); otherwise a
      // gravity fill enters the upper side inlet.
      if (tT === "oiltank" || tT === "watertank") { dTie = _tankTie(b, a, spec.product, bothTanks && spec.product !== "gas"); }
      var runH = 1.2;
      // MANHATTAN / orthogonal route — vertical drop off the source nozzle, run on
      // X, run on Z, vertical rise into the dest nozzle. Every segment is axis-
      // aligned, so the only bends are true 90° elbows (no curved pipe — like the field).
      pts = [
        sTie,
        new THREEref.Vector3(sTie.x, runH, sTie.z),                                 // drop/rise to the sleeper run
        new THREEref.Vector3(dTie.x, runH, sTie.z),                                 // run along X
        new THREEref.Vector3(dTie.x, runH, dTie.z),                                 // run along Z
        dTie                                                                         // rise/drop into the dest nozzle
      ];
    } else {
      pts = [
        new THREEref.Vector3(a.x, nozzle, a.z),
        new THREEref.Vector3(a.x, rackH, a.z),
        new THREEref.Vector3((a.x + b.x) / 2, rackH, (a.z + b.z) / 2),
        new THREEref.Vector3(b.x, rackH, b.z),
        new THREEref.Vector3(b.x, nozzle, b.z)
      ];
    }
    var curve;
    if (spec.detailed) {
      // sharp-cornered polyline — straight runs joined by true 90° elbows, nothing rounded
      curve = new THREEref.CurvePath();
      for (var _ci = 0; _ci < pts.length - 1; _ci++) {
        if (pts[_ci].distanceTo(pts[_ci + 1]) > 1e-4) { curve.add(new THREEref.LineCurve3(pts[_ci], pts[_ci + 1])); }
      }
    } else {
      curve = new THREEref.CatmullRomCurve3(pts, false, "catmullrom", 0.35);
    }
    var dia = spec.diameter || 3;
    var radius = 0.13 + dia * 0.03;                 // 3" -> 0.22, 4" -> 0.25
    var detailed = !!spec.detailed;
    var color = PRODUCT[spec.product] || PRODUCT.gas;

    // main pipe
    var tubeG = new THREEref.TubeGeometry(curve, 72, radius, 14, false);
    var mesh = new THREEref.Mesh(tubeG, pmat(color));
    facility.add(mesh);

    // insulation cladding (aluminum jacket) on the hot heater-outlet line
    if (detailed && spec.from === "HTR") {
      var clad = new THREEref.Mesh(new THREEref.TubeGeometry(curve, 72, radius + 0.09, 14, false),
        new THREEref.MeshStandardMaterial({ color: 0xC9D2DC, metalness: 0.45, roughness: 0.55,
          transparent: true, opacity: 0.8, side: THREEref.DoubleSide }));
      facility.add(clad);
    }

    // ── fitting helpers (oriented to the pipe's local tangent) ──
    function quatTo(axis, u) {
      var tg = curve.getTangentAt(u).normalize();
      return new THREEref.Quaternion().setFromUnitVectors(axis, tg);
    }
    function flangePair(u, bolts) {
      var p = curve.getPointAt(u), tg = curve.getTangentAt(u).normalize();
      var q = new THREEref.Quaternion().setFromUnitVectors(_UP, tg);
      [-0.05, 0.05].forEach(function (off) {
        var d = new THREEref.Mesh(new THREEref.CylinderGeometry(radius + 0.13, radius + 0.13, 0.07, 18), metal(COL.steelDark));
        d.position.copy(p.clone().addScaledVector(tg, off)); d.quaternion.copy(q); facility.add(d);
      });
      if (bolts) {
        var ref = Math.abs(tg.y) < 0.9 ? _UP : new THREEref.Vector3(1, 0, 0);
        var e1 = new THREEref.Vector3().crossVectors(tg, ref).normalize();
        var e2 = new THREEref.Vector3().crossVectors(tg, e1).normalize();
        for (var bi = 0; bi < 6; bi++) {
          var ang = bi / 6 * Math.PI * 2, rb = radius + 0.10;
          var bp = p.clone().addScaledVector(e1, Math.cos(ang) * rb).addScaledVector(e2, Math.sin(ang) * rb);
          var bolt = new THREEref.Mesh(new THREEref.CylinderGeometry(0.022, 0.022, 0.17, 6), metal(0x9AA6B2));
          bolt.position.copy(bp); bolt.quaternion.copy(q); facility.add(bolt);
        }
      }
    }
    function elbow(u) {
      var p = curve.getPointAt(u);
      var s = new THREEref.Mesh(new THREEref.SphereGeometry(radius + 0.09, 16, 12), metal(COL.steel));
      s.position.copy(p); facility.add(s);
    }
    function support(u) {
      var p = curve.getPointAt(u), legH = Math.max(0.3, p.y - radius - 0.1);
      var leg = new THREEref.Mesh(new THREEref.BoxGeometry(0.14, legH, 0.14), metal(COL.steelDark));
      leg.position.set(p.x, legH / 2, p.z); facility.add(leg);
      var base = new THREEref.Mesh(new THREEref.BoxGeometry(0.32, 0.08, 0.32), skidMat());
      base.position.set(p.x, 0.04, p.z); facility.add(base);
      var saddle = new THREEref.Mesh(new THREEref.CylinderGeometry(radius + 0.05, radius + 0.05, 0.2, 12, 1, true, 0, Math.PI), metal(COL.steel));
      saddle.rotation.z = Math.PI / 2; saddle.position.set(p.x, p.y - radius - 0.02, p.z); facility.add(saddle);
    }
    function gateValve(u) {
      var p = curve.getPointAt(u), q = quatTo(_UP, u);
      var body = new THREEref.Mesh(new THREEref.CylinderGeometry(radius + 0.16, radius + 0.16, 0.5, 16), metal(0x6B7785));
      body.position.copy(p); body.quaternion.copy(q); facility.add(body);
      var bonnet = new THREEref.Mesh(new THREEref.CylinderGeometry(0.1, 0.14, 0.55, 12), metal(COL.steelDark));
      bonnet.position.copy(p.clone().add(new THREEref.Vector3(0, radius + 0.45, 0))); facility.add(bonnet);
      var hw = new THREEref.Mesh(new THREEref.TorusGeometry(0.27, 0.05, 8, 18), metal(0xCC4444));
      hw.position.copy(p.clone().add(new THREEref.Vector3(0, radius + 0.78, 0))); hw.rotation.x = Math.PI / 2; facility.add(hw);
    }
    // inline field device: BPR (back-pressure regulator) = wide diaphragm dome
    // actuator; flare_valve (relief) = tall spring-bonnet with topworks.
    function inlineDevice(u, kind) {
      var p = curve.getPointAt(u), q = quatTo(_UP, u);
      var body = new THREEref.Mesh(new THREEref.CylinderGeometry(radius + 0.18, radius + 0.18, 0.55, 16), metal(0x6B7785));
      body.position.copy(p); body.quaternion.copy(q); facility.add(body);
      var stem = new THREEref.Mesh(new THREEref.CylinderGeometry(0.07, 0.07, 0.45, 10), metal(COL.steelDark));
      stem.position.copy(p.clone().add(new THREEref.Vector3(0, radius + 0.4, 0))); facility.add(stem);
      if (kind === "bpr") {
        // diaphragm dome (the BPR signature) + pilot tube
        var dome = new THREEref.Mesh(new THREEref.CylinderGeometry(0.42, 0.42, 0.22, 18), metal(COL.accent));
        dome.position.copy(p.clone().add(new THREEref.Vector3(0, radius + 0.74, 0))); facility.add(dome);
        var domeTop = new THREEref.Mesh(new THREEref.SphereGeometry(0.42, 16, 8, 0, Math.PI * 2, 0, Math.PI / 2), metal(0x9AA6B2));
        domeTop.position.copy(p.clone().add(new THREEref.Vector3(0, radius + 0.85, 0))); facility.add(domeTop);
        var pilot = new THREEref.Mesh(new THREEref.CylinderGeometry(0.03, 0.03, 0.7, 6), metal(COL.steelDark));
        pilot.position.copy(p.clone().add(new THREEref.Vector3(0.3, radius + 0.5, 0))); pilot.rotation.z = Math.PI / 2.4; facility.add(pilot);
      } else {
        // relief/flare valve: tall spring bonnet + cap (set above BPR pressure)
        var bonnet = new THREEref.Mesh(new THREEref.CylinderGeometry(0.16, 0.2, 0.7, 12), metal(PRODUCT.gas));
        bonnet.position.copy(p.clone().add(new THREEref.Vector3(0, radius + 0.78, 0))); facility.add(bonnet);
        var cap = new THREEref.Mesh(new THREEref.CylinderGeometry(0.1, 0.1, 0.18, 10), metal(COL.steelDark));
        cap.position.copy(p.clone().add(new THREEref.Vector3(0, radius + 1.22, 0))); facility.add(cap);
      }
    }

    // flanged tie-ins at both vessel connections
    flangePair(0.0, detailed);
    flangePair(1.0, detailed);
    if (detailed) {
      // elbow fittings at the true 90° corners of the orthogonal route
      for (var _ei = 1; _ei < pts.length - 1; _ei++) {
        var _es = new THREEref.Mesh(new THREEref.SphereGeometry(radius + 0.09, 14, 10), metal(COL.steel));
        _es.position.copy(pts[_ei]); facility.add(_es);
      }
      // sleeper supports spaced along the run (~every 3.5 m) so long lines don't sag
      var _runLen = curve.getLength();
      var _nSup = Math.max(2, Math.min(9, Math.round(_runLen / 3.5)));
      for (var _si = 1; _si <= _nSup; _si++) { support(0.15 + (_si / (_nSup + 1)) * 0.7); }
      gateValve(0.5);                    // isolation valve on every line
      // BPR sits near the separator gas outlet (run start); flare valve near the
      // relief take-off — both just downstream of the source nozzle.
      if (spec.inline === "bpr") { inlineDevice(0.3, "bpr"); }
      else if (spec.inline === "flare_valve") { inlineDevice(0.3, "flare_valve"); }
    } else {
      support(0.5);
    }

    // flow packets — slugs riding the line
    var packets = [], k, np = 3, pr = Math.max(0.18, radius * 1.15);
    for (k = 0; k < np; k++) {
      var pk = new THREEref.Mesh(new THREEref.SphereGeometry(pr, 10, 8), glowMat(0xFFFFFF, 0.9));
      pk.material.color.setHex(color); facility.add(pk);
      packets.push({ mesh: pk, offset: k / np });
    }
    // digital-twin "data-pulse" rings — glowing bands sweeping the pipe path
    var pulses = [];
    if (detailed) {
      for (k = 0; k < 2; k++) {
        var ring = new THREEref.Mesh(new THREEref.TorusGeometry(radius + 0.11, 0.045, 8, 22), glowMat(COL.accent, 0.9));
        facility.add(ring); pulses.push({ mesh: ring, offset: k / 2 });
      }
    }
    return { id: spec.id, mesh: mesh, curve: curve, packets: packets, pulses: pulses,
             detailed: detailed, product: spec.product, baseSpeed: spec.speed, speed: spec.speed };
  }

  // ── FACILITY ASSEMBLY ───────────────────────────────────────────────────────
  // ── COMMS / OT-NETWORK OVERLAY (the industrial-network layer) ───────────────
  // Thin medium-colored cabling modeled on a midstream monitoring architecture:
  // the RTU/PLC shelter is the field comms hub — Ethernet to comms, Fiber to the
  // radio backhaul, Serial/Modbus to the metered instruments, I/O to power/solar.
  // Run low (cable-tray height) so it reads UNDER the process piping.
  // Legend: Fiber=orange, Ethernet=blue, Serial=red, I/O=purple.
  function buildCommsNet() {
    var MED = { fiber: 0xF28C28, ethernet: 0x1D5FE0, serial: 0xE03B3B, io: 0xA06CD4 };
    var links = [
      ["RTU", "COM", "ethernet"], ["COM", "TWR", "fiber"],
      ["RTU", "PWR", "io"], ["RTU", "SOL", "io"],
      ["RTU", "SEP", "serial"], ["RTU", "CMP", "serial"], ["RTU", "EFM", "serial"]
    ];
    links.forEach(function (lk, li) {
      var a = equipLocal(lk[0]), b = equipLocal(lk[1]), col = MED[lk[2]] || MED.ethernet;
      var trayH = 0.22 + (li % 4) * 0.06;   // stacked tray levels so parallel runs don't overlap
      // SCHEMATIC / cable-tray route: riser up, run on X, run on Z, riser down —
      // 90° bends only (no diagonal), matching the orthogonal process piping.
      var pts = [
        new THREEref.Vector3(a.x, 0.14, a.z), new THREEref.Vector3(a.x, trayH, a.z),
        new THREEref.Vector3(b.x, trayH, a.z), new THREEref.Vector3(b.x, trayH, b.z),
        new THREEref.Vector3(b.x, 0.14, b.z)
      ];
      var crv = new THREEref.CurvePath();
      for (var ci = 0; ci < pts.length - 1; ci++) { if (pts[ci].distanceTo(pts[ci + 1]) > 1e-4) { crv.add(new THREEref.LineCurve3(pts[ci], pts[ci + 1])); } }
      var mat = new THREEref.MeshStandardMaterial({ color: col, emissive: col, emissiveIntensity: 0.4,
        metalness: 0.2, roughness: 0.6, transparent: true, opacity: 0.85 });
      facility.add(new THREEref.Mesh(new THREEref.TubeGeometry(crv, 64, 0.045, 8, false), mat));
    });
  }
  // ── FIELD INSTRUMENTATION (detectors + IP camera, from the monitoring ref) ──
  // Pad safety/security devices: gas detector, pressure transmitter, and a
  // pan-tilt IP camera on a pole — each wired back to the RTU on an I/O link.
  function buildFieldInstruments() {
    var rtu = equipLocal("RTU"), io = 0xA06CD4, _ioN = 0;
    function ioLink(x, z) {
      var trayH = 0.20 + (_ioN++ % 4) * 0.06;   // stacked tray levels
      // schematic / cable-tray route back to the RTU — 90° bends only
      var pts = [
        new THREEref.Vector3(x, 0.12, z), new THREEref.Vector3(x, trayH, z),
        new THREEref.Vector3(rtu.x, trayH, z), new THREEref.Vector3(rtu.x, trayH, rtu.z),
        new THREEref.Vector3(rtu.x, 0.14, rtu.z)
      ];
      var crv = new THREEref.CurvePath();
      for (var ci = 0; ci < pts.length - 1; ci++) { if (pts[ci].distanceTo(pts[ci + 1]) > 1e-4) { crv.add(new THREEref.LineCurve3(pts[ci], pts[ci + 1])); } }
      facility.add(new THREEref.Mesh(new THREEref.TubeGeometry(crv, 48, 0.04, 6, false),
        new THREEref.MeshStandardMaterial({ color: io, emissive: io, emissiveIntensity: 0.4, transparent: true, opacity: 0.8 })));
    }
    // gas detector (SE of the compressor)
    var cmp = equipLocal("CMP"), gx = cmp.x + 2.0, gz = cmp.z + 3.0;
    var gpole = new THREEref.Mesh(new THREEref.CylinderGeometry(0.06, 0.07, 1.9, 8), metal(COL.steelDark));
    gpole.position.set(gx, 0.95, gz); facility.add(gpole);
    var ghead = new THREEref.Mesh(new THREEref.CylinderGeometry(0.22, 0.22, 0.42, 14), metal(0xE0B020));
    ghead.position.set(gx, 2.05, gz); facility.add(ghead);
    var gcone = new THREEref.Mesh(new THREEref.ConeGeometry(0.22, 0.26, 14), metal(COL.steel));
    gcone.position.set(gx, 2.38, gz); facility.add(gcone);
    ioLink(gx, gz);
    // pressure transmitter (S of the separator)
    var sep = equipLocal("SEP"), px = sep.x + 1.0, pz = sep.z + 2.6;
    var pstand = new THREEref.Mesh(new THREEref.CylinderGeometry(0.05, 0.06, 1.3, 6), metal(COL.steelDark));
    pstand.position.set(px, 0.65, pz); facility.add(pstand);
    var pbody = new THREEref.Mesh(new THREEref.BoxGeometry(0.42, 0.42, 0.28), metal(COL.steel));
    pbody.position.set(px, 1.35, pz); facility.add(pbody);
    var pgauge = new THREEref.Mesh(new THREEref.CylinderGeometry(0.19, 0.19, 0.09, 16), metal(0xBFD8E6));
    pgauge.rotation.x = Math.PI / 2; pgauge.position.set(px, 1.35, pz + 0.18); facility.add(pgauge);
    ioLink(px, pz);
    // pan-tilt IP camera on a tall pole at the SW corner, overlooking the whole pad
    var wh = equipLocal("WH"), cx = wh.x - 1.5, cz = wh.z + 5.0;
    var cpole = new THREEref.Mesh(new THREEref.CylinderGeometry(0.1, 0.13, 5.8, 12), metal(COL.steelDark));
    cpole.position.set(cx, 2.9, cz); facility.add(cpole);
    var carm = new THREEref.Mesh(new THREEref.BoxGeometry(0.9, 0.11, 0.11), metal(COL.steelDark));
    carm.position.set(cx + 0.45, 5.7, cz); facility.add(carm);
    var cbody = new THREEref.Mesh(new THREEref.BoxGeometry(0.7, 0.38, 0.38), metal(0x2A2F3A));
    cbody.position.set(cx + 0.95, 5.62, cz); cbody.rotation.y = -0.7; facility.add(cbody);
    var cshield = new THREEref.Mesh(new THREEref.BoxGeometry(0.78, 0.07, 0.46), metal(0x3A4150));
    cshield.position.set(cx + 0.95, 5.86, cz); cshield.rotation.y = -0.7; facility.add(cshield);
    var clens = new THREEref.Mesh(new THREEref.CylinderGeometry(0.13, 0.13, 0.2, 14), metal(0x0C0F14));
    clens.rotation.z = Math.PI / 2; clens.rotation.y = -0.7; clens.position.set(cx + 1.28, 5.58, cz - 0.18); facility.add(clens);
    var cled = new THREEref.Mesh(new THREEref.SphereGeometry(0.05, 8, 6), glowMat(0xFF3B3B, 0.9));   // recording LED
    cled.position.set(cx + 1.2, 5.78, cz - 0.12); facility.add(cled);
    ioLink(cx, cz);
    // H2S DETECTOR (sour-service personnel safety) near the wellhead/separator
    var wh2 = equipLocal("WH"), hx = wh2.x + 1.2, hz = wh2.z + 2.2;
    var hpole = new THREEref.Mesh(new THREEref.CylinderGeometry(0.06, 0.07, 1.7, 8), metal(COL.steelDark));
    hpole.position.set(hx, 0.85, hz); facility.add(hpole);
    var hhead = new THREEref.Mesh(new THREEref.CylinderGeometry(0.18, 0.18, 0.34, 14), metal(0xEF4444));
    hhead.position.set(hx, 1.85, hz); facility.add(hhead);
    var hbeac = new THREEref.Mesh(new THREEref.SphereGeometry(0.07, 8, 6), glowMat(0xFF3B3B, 0.9));
    hbeac.position.set(hx, 2.08, hz); facility.add(hbeac);
    ioLink(hx, hz);
  }
  function buildFacility() {
    facility = new THREEref.Group();

    // lighting
    var hemi = new THREEref.HemisphereLight(0xBCD0FF, 0x1A2230, 0.95); facility.add(hemi);
    var dir = new THREEref.DirectionalLight(0xFFFFFF, 0.85); dir.position.set(28, 55, 18); facility.add(dir);
    var amb = new THREEref.PointLight(COL.accent, 0.55, 140); amb.position.set(0, 32, 0); facility.add(amb);

    // equipment
    var i, e, m, p;
    for (i = 0; i < EQUIP.length; i++) {
      e = EQUIP[i];
      m = buildEquip(e.type);
      p = toLocal(e.lng, e.lat);
      m.position.set(p.x, 0, p.z);
      m.userData = { id: e.id, name: e.name, type: e.type };
      facility.add(m);
      equipMeshes[e.id] = m;
    }

    // Windsock — a real met instrument on the field (no health ring). Placed
    // directly (not via the topology) and oriented to live wind in animate().
    try {
      var wsk = buildWindsock();
      var wp = toLocal(WINDSOCK_LL[0], WINDSOCK_LL[1]);
      wsk.position.set(wp.x, 0, wp.z);
      facility.add(wsk);
      _windsock = wsk.userData;
    } catch (eWsk) { _windsock = null; }

    // pipes (added straight to facility inside buildPipe)
    var j;
    for (j = 0; j < PIPES.length; j++) {
      segments.push(buildPipe(PIPES[j]));
    }
    buildCommsNet();          // OT-network overlay (Phase 4 of the pipeline-architecture roadmap)
    buildFieldInstruments();  // pad detectors + IP camera from the monitoring reference
    // SECONDARY-CONTAINMENT BERM around the tank battery (spill control + NSPS/SPCC)
    (function () {
      var ot1 = equipLocal("OT1"), pwt = equipLocal("PWT");
      var bcx = (ot1.x + pwt.x) / 2, bcz = (ot1.z + pwt.z) / 2;
      var halfW = Math.abs(pwt.x - ot1.x) / 2 + 4.0, halfD = 4.2, bh = 0.9, tB = 0.5;
      var bmat = new THREEref.MeshStandardMaterial({ color: 0x6B5B4A, metalness: 0.04, roughness: 0.96 });
      [[bcx, bcz - halfD, 2 * halfW, tB], [bcx, bcz + halfD, 2 * halfW, tB],
       [bcx - halfW, bcz, tB, 2 * halfD], [bcx + halfW, bcz, tB, 2 * halfD]].forEach(function (w) {
        var m = new THREEref.Mesh(new THREEref.BoxGeometry(w[2], bh, w[3]), bmat);
        m.position.set(w[0], bh / 2, w[1]); facility.add(m);
      });
    })();

    scene.add(facility);
  }

  // ── MAPLIBRE CUSTOM LAYER ────────────────────────────────────────────────────
  function computeTransform() {
    var merc = maplibregl.MercatorCoordinate.fromLngLat(ORIGIN, 0);
    transform = {
      x: merc.x, y: merc.y, z: merc.z,
      scale: merc.meterInMercatorCoordinateUnits()
    };
  }

  function animate(map) {
    var t = ((window.performance && performance.now) ? performance.now() : 0) - _clock0;
    var ts = t * 0.001;
    var i, s, k, pk, u, pos;
    // flow packets — size + tube glow scale with live flow so it reads on camera
    for (i = 0; i < segments.length; i++) {
      s = segments[i];
      var fl = (typeof s.flow === "number") ? s.flow : 0.5;
      if (s.mesh && s.mesh.material) {
        s.mesh.material.emissiveIntensity = 0.16 + fl * 0.55 + Math.sin(ts * 4 + i) * 0.12 * fl;
      }
      var sc = 0.55 + fl * 1.1;
      for (k = 0; k < s.packets.length; k++) {
        pk = s.packets[k];
        u = (ts * s.speed + pk.offset) % 1;
        if (u < 0) { u += 1; }
        pos = s.curve.getPointAt(u);
        pk.mesh.position.set(pos.x, pos.y, pos.z);
        pk.mesh.scale.set(sc, sc, sc);
      }
      // digital-twin data-pulse rings — sweep the pipe path, oriented to its tangent
      if (s.pulses && _ZAXIS) {
        for (k = 0; k < s.pulses.length; k++) {
          var pu = s.pulses[k], uu = ((ts * (s.speed * 2.4) + pu.offset) % 1 + 1) % 1;
          var pp = s.curve.getPointAt(uu), tg = s.curve.getTangentAt(uu).normalize();
          pu.mesh.position.set(pp.x, pp.y, pp.z);
          pu.mesh.quaternion.setFromUnitVectors(_ZAXIS, tg);
          pu.mesh.material.opacity = (0.2 + 0.65 * Math.sin(uu * Math.PI)) * (0.4 + 0.6 * fl);
        }
      }
    }
    // flare flicker
    for (i = 0; i < flameMeshes.length; i++) {
      var f = 0.85 + Math.sin(ts * 11 + i) * 0.12 + Math.sin(ts * 23) * 0.05;
      flameMeshes[i].scale.set(1, f, 1);
      flameMeshes[i].material.opacity = 0.7 + Math.sin(ts * 9 + i) * 0.18;
    }
    // tower beacon blink
    for (i = 0; i < blinkMeshes.length; i++) {
      blinkMeshes[i].material.opacity = (Math.sin(ts * 3) > 0.4) ? 0.95 : 0.12;
    }
    // flare — flame COLOR + SIZE reflect the live INTAKE (gas flow into the stack,
    // segment P6) + its status; the plume flickers + leans DOWNWIND with the wind.
    if (_flares.length && !_FLAME_WARN) {
      _FLAME_WARN = new THREEref.Color(0xFBBF24); _FLAME_SOOT = new THREEref.Color(0x6B2A12);
    }
    var _intake = null;
    for (k = 0; k < segments.length; k++) {
      if (segments[k].id === "P6" || segments[k].to === "FLR") { _intake = segments[k]; break; }
    }
    var intakeFlow = (_intake && typeof _intake.flow === "number") ? _intake.flow : 0.7;
    var intakeStatus = (_intake && _intake.status) ? _intake.status : "good";
    var hot = Math.max(0, Math.min(1, intakeFlow));   // 0 (no intake) .. 1 (full)
    for (i = 0; i < _flares.length; i++) {
      var fr = _flares[i];
      var fw = (window.AevusWindsock && window.AevusWindsock.wind) ? window.AevusWindsock.wind() : null;
      var ftoward = (fw && typeof fw.towardDeg === "number") ? fw.towardDeg : 135;
      var fmph = (fw && typeof fw.mph === "number") ? fw.mph : 8;
      fr.yaw.rotation.y = Math.PI - ftoward * Math.PI / 180;
      fr.lean.rotation.x = Math.min(0.9, fmph * 0.04) + Math.sin(ts * 2.4) * 0.05;
      // intake flow scales the whole plume (small/dim when starved, tall/bright when full)
      fr.lean.scale.setScalar(0.42 + hot * 0.95);
      var dim = (intakeStatus === "bad") ? 0.6 : 1;
      for (k = 0; k < fr.layers.length; k++) {
        var L = fr.layers[k];
        // temperature colour by intake: cool (low flow) -> hot (high flow)
        L.mesh.material.color.copy(L.cool).lerp(L.hot, hot);
        if (intakeStatus === "warn") { L.mesh.material.color.lerp(_FLAME_WARN, 0.45); }
        else if (intakeStatus === "bad") { L.mesh.material.color.lerp(_FLAME_SOOT, 0.55); }
        // flicker: pulse height, wobble width, sway organically — like a torch
        var puls = 1 + Math.sin(ts * (8 + k * 2) + L.phase) * 0.16 + Math.sin(ts * 23 + k) * 0.05;
        var wob = 1 + Math.sin(ts * (11 + k) + L.phase) * 0.07;
        L.mesh.scale.set(L.base * wob, L.base * puls, L.base * wob);
        L.mesh.rotation.z = Math.sin(ts * (3 + k) + L.phase) * 0.06;
        L.mesh.rotation.x = Math.cos(ts * (2.6 + k)) * 0.045;
        L.mesh.material.opacity = L.baseOp * (0.78 + Math.sin(ts * (6 + k) + L.phase) * 0.2) * (0.35 + hot * 0.65) * dim;
      }
      if (fr.light) { fr.light.intensity = (0.4 + hot * 1.5) + Math.sin(ts * 8) * 0.35; }
    }
    // separator cutaway — gas flows along the top to the outlet; droplets fall
    // off the inlet diverter into the pool; the liquid level gently shimmers.
    if (_separator) {
      var S = _separator;
      for (k = 0; k < S.gas.length; k++) {
        var gp = S.gas[k], u = ((ts * 0.16 + gp.offset) % 1 + 1) % 1;
        gp.mesh.position.set(S.x0 + u * (S.x1 - S.x0), S.gasY + Math.sin(ts * 3 + k) * 0.12, Math.sin(ts * 1.3 + k) * 0.4);
        gp.mesh.material.opacity = 0.18 + 0.3 * Math.sin(u * Math.PI);
      }
      for (k = 0; k < S.drops.length; k++) {
        var dp = S.drops[k], v = ((ts * 0.6 + dp.offset) % 1 + 1) % 1;
        dp.mesh.position.set(S.dropX + Math.sin(k) * 0.2, S.dropTop - v * (S.dropTop - S.poolY), Math.cos(k) * 0.3);
        dp.mesh.material.opacity = v < 0.9 ? 0.85 : 0;
      }
      if (S.level) { S.level.position.y = S.poolY + Math.sin(ts * 1.5) * 0.025; }
    }
    // line heater cutaway — fire-tube glow pulses (combustion), bubbles rise in
    // the water bath, gas packets flow through the process coil.
    if (_heater) {
      var H = _heater;
      if (H.fire) { H.fire.material.emissiveIntensity = 0.55 + 0.35 * (0.5 + 0.5 * Math.sin(ts * 9)) + 0.1 * Math.sin(ts * 23); }
      for (k = 0; k < H.bubbles.length; k++) {
        var bb = H.bubbles[k], w = ((ts * 0.4 + bb.offset) % 1 + 1) % 1;
        bb.mesh.position.set(bb.x + Math.sin(ts * 2 + k) * 0.06, H.bathBot + 0.1 + w * (H.bathY - H.bathBot - 0.15), bb.z);
        bb.mesh.material.opacity = w < 0.88 ? 0.5 : 0;
      }
      if (H.curve && H.flow) {
        for (k = 0; k < H.flow.length; k++) {
          var hp = H.flow[k], hu = ((ts * 0.1 + hp.offset) % 1 + 1) % 1;
          var pt = H.curve.getPointAt(hu);
          hp.mesh.position.set(pt.x, pt.y, pt.z);
        }
      }
      if (H.level) { H.level.position.y = H.bathY + Math.sin(ts * 1.7) * 0.02; }
    }
    // wellhead cutaway — oil/gas rises up the production bore; some turns out the
    // wing valve to the flowline.
    if (_wellhead) {
      var W = _wellhead;
      for (k = 0; k < W.riser.length; k++) {
        var rp = W.riser[k], ru = ((ts * 0.22 + rp.offset) % 1 + 1) % 1;
        rp.mesh.position.set(Math.sin(ts * 2 + k) * 0.03, W.y0 + ru * (W.y1 - W.y0), Math.cos(ts * 2 + k) * 0.03);
        rp.mesh.material.opacity = 0.5 + 0.4 * Math.sin(ru * Math.PI);
      }
      for (k = 0; k < W.wingFlow.length; k++) {
        var wp = W.wingFlow[k], wu = ((ts * 0.5 + wp.offset) % 1 + 1) % 1;
        wp.mesh.position.set(wu * W.wingX, W.wingY, 0);
        wp.mesh.material.opacity = wu < 0.92 ? 0.9 : 0;
      }
    }
    // storage tanks — level shimmer, gauge bead tracks the level, fill drips in
    for (i = 0; i < _tanks.length; i++) {
      var T = _tanks[i], wob = Math.sin(ts * 1.3 + i) * 0.03;
      if (T.level) { T.level.position.y = T.fillTop + wob; }
      if (T.bead) { T.bead.position.y = T.fillTop + wob; }
      for (k = 0; k < T.drops.length; k++) {
        var td = T.drops[k], tv = ((ts * 0.45 + td.offset) % 1 + 1) % 1;
        td.mesh.position.set(T.dropX + Math.sin(k) * 0.2, T.dropTop - tv * (T.dropTop - T.fillTop), Math.cos(k) * 0.2);
        td.mesh.material.opacity = tv < 0.9 ? 0.85 : 0;
      }
    }
    // chemical tote — level shimmer + metered injection droplets up the line
    if (_chemtote) {
      var C = _chemtote;
      if (C.level) { C.level.position.y = C.fillTop + Math.sin(ts * 1.6) * 0.015; }
      for (k = 0; k < C.drops.length; k++) {
        var cd = C.drops[k], cu = ((ts * 0.55 + cd.offset) % 1 + 1) % 1;
        var cp = C.curve.getPointAt(cu);
        cd.mesh.position.set(cp.x, cp.y, cp.z);
      }
    }
    // compressor — piston reciprocates inside the glass cylinder
    if (_compressor) {
      var P = _compressor, ph = (Math.sin(ts * 6) + 1) / 2;       // 0..1 stroke
      var px = P.x0 + ph * (P.x1 - P.x0);
      if (P.piston) { P.piston.position.x = px; }
      if (P.rod) { P.rod.position.x = P.rodX + ph * 0.3; }
    }
    // flare KO drum — knockout liquid level shimmer + settling droplets
    if (_koDrum) {
      var K = _koDrum;
      if (K.level) { K.level.position.y = K.poolY + Math.sin(ts * 1.5) * 0.02; }
      for (k = 0; k < K.drops.length; k++) {
        var kd = K.drops[k], kv = ((ts * 0.5 + kd.offset) % 1 + 1) % 1;
        kd.mesh.position.set(K.cx + (k / K.drops.length - 0.5) * K.len * 0.7, K.dropTop - kv * (K.dropTop - K.poolY), (k % 2 ? 0.2 : -0.2));
        kd.mesh.material.opacity = kv < 0.9 ? 0.85 : 0;
      }
    }
    // windsock — stream DOWNWIND in the real geographic direction (local frame:
    // x=east, z=south => rotation.y = PI/2 - toward), with flutter + wind-driven droop
    if (_windsock && _windsock.pivot) {
      var wd = (window.AevusWindsock && window.AevusWindsock.wind) ? window.AevusWindsock.wind() : null;
      var towardDeg = (wd && typeof wd.towardDeg === "number") ? wd.towardDeg : 135;
      var mph = (wd && typeof wd.mph === "number") ? wd.mph : 8;
      var towardRad = towardDeg * Math.PI / 180;
      _windsock.pivot.rotation.y = (Math.PI / 2 - towardRad) + Math.sin(ts * 1.6) * 0.12;
      if (_windsock.droop) {
        var ext = Math.max(0, Math.min(1, mph / 18));   // 0 calm .. 1 fully extended
        _windsock.droop.rotation.z = -(1 - ext) * 0.95 + Math.sin(ts * 3.2) * 0.08 * (0.4 + ext);
        _windsock.droop.rotation.y = Math.sin(ts * 2.3) * 0.06;
      }
    }
  }

  function makeLayer(map) {
    return {
      id: LAYER_ID,
      type: "custom",
      renderingMode: "3d",
      onAdd: function (m, gl) {
        THREEref = window.THREE;
        camera = new THREEref.Camera();
        scene = new THREEref.Scene();
        buildFacility();
        renderer = new THREEref.WebGLRenderer({ canvas: m.getCanvas(), context: gl, antialias: true });
        renderer.autoClear = false;
        computeTransform();
        startStatusPoll();
        startFlowPoll();
      },
      render: function (gl, matrix) {
        if (!renderer) { return; }
        var rotationX = new THREEref.Matrix4().makeRotationAxis(new THREEref.Vector3(1, 0, 0), Math.PI / 2);
        var l = new THREEref.Matrix4()
          .makeTranslation(transform.x, transform.y, transform.z)
          .scale(new THREEref.Vector3(transform.scale, -transform.scale, transform.scale))
          .multiply(rotationX);
        var m = new THREEref.Matrix4().fromArray(matrix);
        camera.projectionMatrix = m.multiply(l);
        animate(map);
        renderer.resetState();
        renderer.render(scene, camera);
        if (!_painted) { onFirstPaint(); }  // first frame on screen => drop the loader
        map.triggerRepaint();
      }
    };
  }

  // ── LIVE FLOW POLL (B1: drive pipe flow from the twin /flow endpoint) ────────
  // Each segment's normalized flow (0..1) + direction + status drives packet
  // speed, emissive intensity, and a bad-status red glow. This is the heartbeat
  // layer: the pipes now reflect live plant state, not hardcoded constants.
  var _flowTimer = null;
  var _sim = {};  // segId -> true while a what-if override holds (poll must not clobber it)
  function startFlowPoll() {
    if (_flowTimer) { return; }
    pollFlow();
    _flowTimer = setInterval(pollFlow, 4000);
  }
  function pollFlow() {
    try {
      fetch("/api/v1/twin/facility/" + TWIN_FACILITY + "/flow", { credentials: "same-origin" })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (d) { if (d && d.segments) { applyFlow(d.segments); } })
        .catch(function () {});
    } catch (e) {}
  }
  function applyFlow(list) {
    var byId = {}, i, j, s, seg, flow, dir;
    for (i = 0; i < segments.length; i++) { byId[segments[i].id] = segments[i]; }
    for (i = 0; i < list.length; i++) {
      seg = list[i];
      s = byId[seg.id];
      if (!s) { continue; }
      if (_sim[seg.id]) { continue; }  // a what-if override holds this segment
      flow = Math.max(0, Math.min(1, seg.flow || 0));
      dir = (seg.dir < 0) ? -1 : 1;
      s.flow = flow;
      s.status = seg.status || "good";   // exposed for the flare flame (intake-driven)
      s.speed = flow * 0.22 * dir;  // flow drives packet speed + direction
      if (s.mesh && s.mesh.material) {
        s.mesh.material.emissiveIntensity = 0.18 + flow * 0.55;
        // bad status -> turn the pipe fully red (base colour + glow) so failures
        // read unmistakably on the twin; otherwise hold the product colour.
        if (seg.status === "bad") {
          s.mesh.material.color.setHex(COL.bad); s.mesh.material.emissive.setHex(COL.bad);
        } else {
          s.mesh.material.color.setHex(PRODUCT[s.product] || COL.steel);
          s.mesh.material.emissive.setHex(PRODUCT[s.product] || COL.steel);
        }
      }
      for (j = 0; j < s.packets.length; j++) {
        s.packets[j].mesh.visible = flow > 0.02;
      }
    }
  }

  // ── LIVE STATUS POLL (Phase-1: tint equipment by asset status) ───────────────
  var _statusTimer = null;
  function startStatusPoll() {
    if (_statusTimer) { return; }
    pollStatus();
    _statusTimer = setInterval(pollStatus, 15000);
  }
  function pollStatus() {
    try {
      fetch("/api/v1/assets", { credentials: "same-origin" })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (data) { if (data) { applyStatus(data); } })
        .catch(function () {});
    } catch (e) {}
  }
  function applyStatus(data) {
    // best-effort name match; tint emissive of matched equipment
    var list = Array.isArray(data) ? data : (data && data.assets ? data.assets : []);
    var i, j, a, name, key, mesh, col;
    // update the equipment callouts (health badge) by bound asset_id
    var byId = {};
    for (i = 0; i < list.length; i++) { if (list[i] && list[i].id) { byId[list[i].id] = list[i]; } }
    updateCallouts(byId);
    for (i = 0; i < list.length; i++) {
      a = list[i];
      name = (a && (a.name || a.id) || "").toString().toLowerCase();
      key = null;
      if (name.indexOf("compress") >= 0) { key = "CMP"; }
      else if (name.indexOf("separat") >= 0) { key = "SEP"; }
      else if (name.indexOf("flare") >= 0) { key = "FLR"; }
      else if (name.indexOf("water") >= 0) { key = "PWT"; }
      else if (name.indexOf("tank") >= 0) { key = "OT1"; }
      else if (name.indexOf("well") >= 0) { key = "WH"; }
      else if (name.indexOf("efm") >= 0 || name.indexOf("meter") >= 0) { key = "EFM"; }
      else if (name.indexOf("rad") >= 0 || name.indexOf("tower") >= 0) { key = "TWR"; }
      if (!key || !equipMeshes[key]) { continue; }
      col = (a.status === "bad" || a.status === "critical") ? COL.bad
          : (a.status === "warn" || a.status === "warning") ? COL.warn : COL.good;
      mesh = equipMeshes[key];
      mesh.traverse(function (o) {
        if (o.isMesh && o.material && o.material.emissive && o.material.metalness !== undefined) {
          o.material.emissive.setHex(col);
          o.material.emissiveIntensity = 0.18;
        }
      });
    }
  }

  // ── HIDE THE OLD BOXY PAD ────────────────────────────────────────────────────
  var BOXY = [
    "well-3d-pads", "well-3d-extrusion", "well-3d-glow", "well-3d-alarm-ring",
    "tank-liquid-fill", "tank-liquid-surface", "tank-rim-glow", "tank-level-text",
    "well-3d-detail", "well-3d-detail-glow"
  ];
  function hideBoxy(map) {
    try { if (typeof window._toggle3dBuildings === "function") { window._toggle3dBuildings(false); } } catch (e) {}
    var i;
    for (i = 0; i < BOXY.length; i++) {
      try { if (map.getLayer(BOXY[i])) { map.setLayoutProperty(BOXY[i], "visibility", "none"); } } catch (e2) {}
    }
  }

  // ── MOUNT / ATTACH ───────────────────────────────────────────────────────────
  function onMapPage() {
    if ((location.hash || "").toLowerCase().indexOf("map") >= 0) { return true; }
    var sec = document.querySelector('section[data-page="map"]');
    return !!(sec && sec.offsetParent !== null);
  }

  // ── Twin load lifecycle ──────────────────────────────────────────────────
  // The "Building digital twin" placeholder is driven by the FIRST actual
  // render() of the scene — an event, NOT a setTimeout — so it is correct on any
  // device/network (fast desktop or cold-cache phone). The only timer is a
  // SAFETY NET for the failure path (topology 500 / WebGL blocked) so we never
  // leave an infinite spinner. State: building -> ready, or building -> degraded.
  var _painted = false;
  var _loaderTimeout = null;
  var _loaderAt = 0;            // ms timestamp the loader appeared (for min-duration)
  function _twinLoaderEl() { return document.getElementById("kd-twin-loader"); }
  function showTwinLoader(map) {
    try {
      var c = map.getContainer(); if (!c || _twinLoaderEl()) { return; }
      if (!document.getElementById("kd-twin-loader-css")) {
        var st = document.createElement("style");
        st.id = "kd-twin-loader-css";
        st.textContent =
          "#kd-twin-loader{position:absolute;inset:0;z-index:12;display:flex;flex-direction:column;" +
          "align-items:center;justify-content:center;gap:14px;background:rgba(11,16,32,0.92);" +
          "transition:opacity .45s ease;font-family:Manrope,-apple-system,sans-serif;pointer-events:none;}" +
          "#kd-twin-loader.kd-hide{opacity:0;}" +
          "#kd-twin-loader .kd-ring{width:34px;height:34px;border-radius:50%;" +
          "border:2.5px solid rgba(6,182,212,0.22);border-top-color:#06B6D4;animation:kdspin .8s linear infinite;}" +
          "#kd-twin-loader .kd-msg{font-size:12px;letter-spacing:1.6px;text-transform:uppercase;" +
          "color:#9FB3C8;font-weight:600;}@keyframes kdspin{to{transform:rotate(360deg);}}";
        document.head.appendChild(st);
      }
      var el = document.createElement("div");
      el.id = "kd-twin-loader";
      el.innerHTML = '<div class="kd-ring"></div><div class="kd-msg">Building digital twin…</div>';
      c.appendChild(el);
      if (!_loaderAt) { _loaderAt = Date.now(); }
    } catch (e) {}
  }
  function hideTwinLoader() {
    if (_loaderTimeout) { clearTimeout(_loaderTimeout); _loaderTimeout = null; }
    var el = _twinLoaderEl(); if (!el) { return; }
    el.classList.add("kd-hide");
    setTimeout(function () { try { if (el.parentNode) { el.parentNode.removeChild(el); } } catch (e) {} }, 500);
  }
  function onFirstPaint() {
    if (_painted) { return; }
    _painted = true;
    try { document.body.classList.add("kd-twin-painted"); } catch (e) {}  // reveals .kd-co callouts
    try { window.dispatchEvent(new CustomEvent("aevus:twin-ready")); } catch (e) {}
    // Reveal only once the layout has STOPPED moving. The base map resizes as the
    // side panels settle (at load + ~3s), panning the framing left then down; the
    // snap-back corrects it but a frame leaks through. Keep the loader up until
    // there's been no camera/resize change for 900ms (hard cap 5s), so the
    // operator sees ONE stable reveal instead of the settle shifts.
    var map = _attachedMap;
    if (!map) { hideTwinLoader(); return; }
    var settled = false, hideT = null;
    var cap = setTimeout(forceReveal, 6000);
    function forceReveal() { settled = false; doReveal(); }
    function onCh() { if (hideT) { clearTimeout(hideT); } hideT = setTimeout(reveal, 900); }
    function reveal() {
      if (settled) { return; }
      // Stay up at least 3.8s so the loader spans the ~3s settle shift, then
      // require 900ms of quiet on top — whichever is later.
      var elapsed = Date.now() - (_loaderAt || Date.now());
      if (elapsed < 3800) { if (hideT) { clearTimeout(hideT); } hideT = setTimeout(reveal, 3800 - elapsed); return; }
      doReveal();
    }
    function doReveal() {
      if (settled) { return; }
      settled = true;
      if (hideT) { clearTimeout(hideT); }
      if (cap) { clearTimeout(cap); }
      try { map.off("move", onCh); map.off("resize", onCh); } catch (e) {}
      hideTwinLoader();
    }
    try { map.on("move", onCh); map.on("resize", onCh); } catch (e) {}
    onCh();  // start the quiet-period countdown
  }

  function attach(map) {
    if (!window.THREE) { return; }     // THREE not loaded yet
    _attachedMap = map;
    _painted = false;
    showTwinLoader(map);               // cleared by the first render() (below)
    if (_loaderTimeout) { clearTimeout(_loaderTimeout); }
    _loaderTimeout = setTimeout(function () {
      // Safety net only — never the happy path. If the twin hasn't painted in
      // 9s the build/topology/WebGL failed; drop the overlay so the operator
      // still gets the map instead of a frozen spinner.
      if (!_painted) { console.warn("[killdeer3d] twin not painted in 9s — removing loader (degraded)"); hideTwinLoader(); }
    }, 9000);
    // reset per-mount state (new map instance => rebuild scene in onAdd)
    scene = null; renderer = null; facility = null;
    segments = []; equipMeshes = {}; flameMeshes = []; blinkMeshes = []; _windsock = null; _flares = []; _separator = null; _heater = null; _wellhead = null; _tanks = []; _chemtote = null; _compressor = null; _koDrum = null; _callouts = {};
    try {
      if (map.getLayer(LAYER_ID)) { map.removeLayer(LAYER_ID); }
    } catch (e) {}
    hideBoxy(map);
    try {
      map.addLayer(makeLayer(map));
      console.log("[killdeer3d] facility layer attached");
      frameFacility(map);
      injectSimUI(map);
      injectAskUI(map);
      injectLayoutFixes(map);
    } catch (e3) {
      console.warn("[killdeer3d] addLayer failed", e3);
      _attachedMap = null;
    }
  }

  // Auto-frame the equipment cluster when the map page is entered. The native
  // map runs its own "fit all assets" camera shortly after load, which can
  // override us — so we re-assert at staggered delays: an initial animated
  // flyTo, then snap-backs ONLY if the camera got dragged away from the pad
  // (i.e. the native fit won). If the user has panned to the facility we leave
  // them alone.
  // The native map periodically re-fits its camera to ALL demo assets (zoom ~14,
  // regional), which fights us not just on load but on every refit. So we enforce
  // the facility frame INDEFINITELY — snapping back whenever the camera gets pulled
  // far from the pad — until the operator manually moves the map. Programmatic moves
  // (ours + the native fit) have no originalEvent; only real gestures set userMoved,
  // so we seize the camera from the native fit without ever fighting the operator.
  function frameFacility(map) {
    if (_frameIv) { clearInterval(_frameIv); _frameIv = null; }
    if (_frameMove) { try { map.off("move", _frameMove); } catch (e) {} _frameMove = null; }
    if (_frameResize) { try { map.off("resize", _frameResize); } catch (e) {} _frameResize = null; }
    var done = false, snapping = false;

    // Neutralize the base map's automatic camera moves while the twin owns the
    // frame. The base map calls fitBounds/flyTo to "fit all demo assets" once
    // they finish loading (~5s after load), which yanks the camera to the
    // regional view; the snap-back then returns it — that round-trip is the
    // post-load jump/flicker. While framed on the Map page these become no-ops;
    // off the Map page, or after the operator takes over (a gesture sets
    // __twinFramed=false via cleanup), they pass through unchanged. Our own snap
    // uses jumpTo (not patched), so framing still works.
    if (!map.__camPatched) {
      map.__camPatched = true;
      ["flyTo", "fitBounds", "easeTo"].forEach(function (fn) {
        var orig = map[fn];
        map[fn] = function () {
          if (map.__twinFramed && onMapPage()) { return map; }
          return orig.apply(map, arguments);
        };
      });
    }
    map.__twinFramed = true;

    function framedNow() {
      try {
        var c = map.getCenter();
        return Math.abs(c.lng - FRAME.center[0]) < 0.0015 &&
               Math.abs(c.lat - FRAME.center[1]) < 0.0015 &&
               Math.abs(map.getZoom() - (FRAME.zoom || 20.1)) < 0.35 &&
               Math.abs(map.getPitch() - (FRAME.pitch || 55)) < 6;
      } catch (e) { return false; }
    }
    function snap() {
      if (snapping) { return; }
      snapping = true;
      try {
        map.stop();  // cancel any native flyTo
        // Lift the facility into vertical center. Without bottom padding the
        // jumpTo centers the *geographic* point at screen-middle, but the 55°
        // pitch projects the facility geometry mostly BELOW that point — so it
        // renders low with empty sky on top and the flare/EFM clipped at the
        // bottom (the "shifted down" report, 2026-06-04). Bottom padding moves
        // the projected center up; ~38% of viewport height centers it cleanly.
        // Responsive so it holds across window sizes / Wall mode. framedNow()
        // checks center/zoom/pitch only, so padding doesn't disturb the lock.
        var padBottom = framePad();
        map.jumpTo({
          center: FRAME.center, zoom: FRAME.zoom, pitch: FRAME.pitch, bearing: FRAME.bearing,
          padding: { top: 0, right: 0, bottom: padBottom, left: 0 }
        });
      } catch (e) {}
      snapping = false;
    }
    function cleanup() {
      if (_frameIv) { clearInterval(_frameIv); _frameIv = null; }
      if (_frameMove) { try { map.off("move", _frameMove); } catch (e) {} _frameMove = null; }
      try { map.off("dragstart", onUser); map.off("zoomstart", onUser); map.off("rotatestart", onUser); } catch (e) {}
      if (_frameResize) { try { map.off("resize", _frameResize); } catch (e) {} _frameResize = null; }
      try { map.__twinFramed = false; } catch (e) {}  // operator took over => let native camera moves through
    }
    function onUser(e) {
      // Honor a gesture as "operator took over" ONLY while already framed, so the
      // load-phase / native-fit churn can't kill the lock before it engages.
      if (!e || !e.originalEvent || done) { return; }
      if (!framedNow()) { return; }
      done = true;
      cleanup();
    }
    function onMove() {
      // Snap back THIS frame whenever the native "fit all assets" camera pulls us
      // off the pad — so there is no visible zoom-out/zoom-in flicker on load.
      if (done || snapping) { return; }
      if (!onMapPage()) { return; }
      if (!framedNow()) { snap(); }
    }
    try { map.on("dragstart", onUser); map.on("zoomstart", onUser); map.on("rotatestart", onUser); } catch (e0) {}
    _frameMove = onMove;
    try { map.on("move", onMove); } catch (e1) {}
    // Re-snap immediately on map resize. The framing padding is px-based, so a
    // resize (panels settling at load + ~3s in -> map.resize()) shifts the framed
    // position until the next snap. Catch it on the resize event, not 600ms later.
    _frameResize = function () { if (!done && onMapPage()) { snap(); } };
    try { map.on("resize", _frameResize); } catch (e2) {}
    snap();  // instant initial frame — jumpTo, never an animated flyTo
    // Backup poll in case 'move' isn't firing while the map sits idle.
    _frameIv = setInterval(function () {
      if (done || !onMapPage()) { return; }
      if (!framedNow()) { snap(); }
    }, 600);
  }

  function tick() {
    if (!onMapPage()) { return; }
    if (!_topoReady) { return; }  // wait for topology (or its fallback) before building
    var map = window._aevusMapInstance || null;
    if (!map) { return; }
    if (map === _attachedMap) {
      // keep boxy hidden in case award overlay re-shows them on remount
      hideBoxy(map);
      return;
    }
    if (typeof map.isStyleLoaded === "function" && !map.isStyleLoaded()) { return; }
    attach(map);
  }

  loadTopology();  // fetch the facility graph (B1) before the first attach

  // Cover the base map ASAP so the operator never sees the raw regional basemap
  // flash before the twin builds. Poll fast for the map instance the moment the
  // Map page is active, and drop the "Building twin" overlay over it — well
  // before attach() would. Stops once shown, the twin paints, or it gives up.
  (function earlyLoader() {
    var tries = 0;
    var iv = setInterval(function () {
      tries++;
      if (_painted || tries > 60) { clearInterval(iv); return; }
      var m = window._aevusMapInstance;
      if (!onMapPage() || !m || !m.getCanvas) { return; }
      clearInterval(iv);
      try {
        showTwinLoader(m);
        // Pre-frame the camera to the FINAL twin frame right now — before the
        // 3D geometry builds — and block the base map's regional auto-fit from
        // this instant. Without this the camera churns 15 -> 16 (native fit,
        // ~1s) -> 20/55 (twin snap, ~2.4s): the two shifts (camera log). Jumping
        // straight to the frame here, behind the loader, means ONE silent move
        // and zero visible shifts; the geometry just fills in already-framed.
        if (!m.__camPatched) {
          m.__camPatched = true;
          ["flyTo", "fitBounds", "easeTo"].forEach(function (fn) {
            var orig = m[fn];
            m[fn] = function () { if (m.__twinFramed && onMapPage()) { return m; } return orig.apply(m, arguments); };
          });
        }
        m.__twinFramed = true;
        var pad = framePad();
        m.jumpTo({ center: FRAME.center, zoom: FRAME.zoom, pitch: FRAME.pitch, bearing: FRAME.bearing,
                   padding: { top: 0, right: 0, bottom: pad, left: 0 } });
      } catch (e) {}
    }, 80);
  })();

  setInterval(tick, 1000);
  window.addEventListener("hashchange", function () { setTimeout(tick, 300); });

  // ── PUBLIC API ────────────────────────────────────────────────────────────────
  // ── WHAT-IF SIMULATION (L4: inject a fault, watch the twin react) ────────────
  // Display-only — IL-9000: this overrides the TWIN's visualization, never a real
  // device. It shows how a failure propagates so operators can rehearse response.
  function _applySeg(segId, flow, status) {
    var i, j, s;
    for (i = 0; i < segments.length; i++) {
      s = segments[i];
      if (s.id !== segId) { continue; }
      s.flow = flow;
      s.speed = flow * 0.22;
      if (s.mesh && s.mesh.material) {
        s.mesh.material.emissiveIntensity = 0.16 + flow * 0.55;
        var hex = status === "bad" ? COL.bad : (PRODUCT[s.product] || COL.steel);
        s.mesh.material.color.setHex(hex); s.mesh.material.emissive.setHex(hex);
      }
      for (j = 0; j < s.packets.length; j++) { s.packets[j].mesh.visible = flow > 0.02; }
      return;
    }
  }
  function _tintEquip(id, hex, intensity) {
    var m = equipMeshes[id];
    if (!m) { return; }
    m.traverse(function (o) {
      if (o.isMesh && o.material && o.material.emissive && o.material.metalness !== undefined) {
        o.material.emissive.setHex(hex); o.material.emissiveIntensity = intensity;
      }
    });
  }
  var SCENARIOS = {
    "compressor-trip": { segs: ["P3", "P6", "P7"], equip: ["CMP"], label: "Compressor Trip" }
  };
  function simulateScenario(name) {
    var sc = SCENARIOS[name];
    if (!sc) { return false; }
    var i;
    for (i = 0; i < sc.segs.length; i++) { _sim[sc.segs[i]] = true; _applySeg(sc.segs[i], 0, "bad"); }
    for (i = 0; i < sc.equip.length; i++) { _tintEquip(sc.equip[i], COL.bad, 0.4); }
    console.log("[killdeer3d] what-if: " + (sc.label || name) + " injected");
    return true;
  }
  function clearSim() {
    _sim = {};
    pollStatus(); pollFlow();  // restore equipment + pipes from live data
    console.log("[killdeer3d] what-if cleared — back to live");
  }

  // Small brand-compliant control (text only — no emoji per IL UI rule).
  function injectSimUI(map) {
    try {
      var c = map.getContainer && map.getContainer();
      if (!c || c.querySelector("#kd-sim-ui")) { return; }
      var box = document.createElement("div");
      box.id = "kd-sim-ui";
      box.style.cssText = "position:absolute;bottom:156px;left:50%;transform:translateX(-50%);z-index:6;" +
        "display:flex;gap:8px;font-family:Manrope,-apple-system,sans-serif;";
      var btn = "padding:7px 14px;border-radius:8px;font-size:12px;font-weight:600;cursor:pointer;";
      box.innerHTML =
        '<button id="kd-sim-trip" style="' + btn + 'background:rgba(239,68,68,0.16);border:1px solid #EF4444;color:#FCA5A5;">Simulate: Compressor Trip</button>' +
        '<button id="kd-sim-reset" style="' + btn + 'background:rgba(6,182,212,0.16);border:1px solid #06B6D4;color:#67E8F9;">Reset to Live</button>';
      c.appendChild(box);
      box.querySelector("#kd-sim-trip").addEventListener("click", function () { simulateScenario("compressor-trip"); });
      box.querySelector("#kd-sim-reset").addEventListener("click", function () { clearSim(); });
    } catch (e) {}
  }

  // "Ask the twin" — natural-language Q&A grounded in the live twin state,
  // answered by the platform's AI layer (/api/v1/ai/twin-ask). Read-only.
  function injectAskUI(map) {
    try {
      var c = map.getContainer && map.getContainer();
      if (!c || c.querySelector("#kd-ask-ui")) { return; }
      var box = document.createElement("div");
      box.id = "kd-ask-ui";
      box.style.cssText = "position:absolute;bottom:100px;left:50%;transform:translateX(-50%);z-index:6;" +
        "width:560px;max-width:82%;font-family:Manrope,-apple-system,sans-serif;";
      box.innerHTML =
        '<div id="kd-ask-answer" style="display:none;background:rgba(11,17,32,0.93);border:1px solid rgba(6,182,212,0.4);' +
        'border-radius:10px;padding:12px 14px;margin-bottom:8px;color:#E2E8F0;font-size:13px;line-height:1.5;' +
        'max-height:210px;overflow:auto;backdrop-filter:blur(6px);white-space:pre-wrap;"></div>' +
        '<div style="display:flex;gap:8px;">' +
        '<input id="kd-ask-input" autocomplete="off" placeholder="Ask the twin…  e.g. is gas reaching the flare?" ' +
        'style="flex:1;background:rgba(11,17,32,0.92);border:1px solid rgba(6,182,212,0.45);border-radius:8px;' +
        'padding:9px 12px;color:#E2E8F0;font-size:13px;font-family:inherit;outline:none;" />' +
        '<button id="kd-ask-send" style="background:#06B6D4;border:none;border-radius:8px;padding:9px 18px;' +
        'color:#04121A;font-size:13px;font-weight:700;cursor:pointer;">Ask</button>' +
        '</div>';
      c.appendChild(box);
      var input = box.querySelector("#kd-ask-input");
      var ans = box.querySelector("#kd-ask-answer");
      var send = box.querySelector("#kd-ask-send");
      function ask() {
        var q = (input.value || "").trim();
        if (!q) { return; }
        ans.style.display = "block"; ans.textContent = "Thinking…"; send.disabled = true;
        fetch("/api/v1/ai/twin-ask", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "same-origin",
          body: JSON.stringify({ question: q, facility_id: TWIN_FACILITY })
        }).then(function (r) {
          if (r.ok) { return r.json(); }
          return r.json().then(function (e) { throw new Error((e && e.detail) || ("HTTP " + r.status)); });
        }).then(function (d) {
          ans.textContent = (d && d.reply) || "(no answer)";
          send.disabled = false;
        }).catch(function (e) {
          ans.textContent = "Couldn't reach the twin assistant: " + e.message;
          send.disabled = false;
        });
      }
      send.addEventListener("click", ask);
      input.addEventListener("keydown", function (e) { if (e.key === "Enter") { ask(); } });
      // keep map gestures from stealing the input's focus/clicks
      ["mousedown", "dblclick", "wheel"].forEach(function (ev) {
        box.addEventListener(ev, function (e) { e.stopPropagation(); });
      });
    } catch (e) {}
  }

  // ── LAYOUT FIXES + EQUIPMENT CALLOUTS ────────────────────────────────────────
  // (1) Hide the native, scattered demo-fleet asset markers + regional geofence
  //     (they render far NW of the pad and read as broken).
  // (2) Place clean, labeled callouts AT the twin equipment, health-tinted.
  // (3) Nudge the native Weather widget up + move the Measure control under Layers.
  function injectLayoutFixes(map) {
    try {
      if (!document.getElementById("kd-layout-css")) {
        var st = document.createElement("style");
        st.id = "kd-layout-css";
        st.textContent =
          ".map-asset-marker{display:none !important;}" +
          ".kd-co{display:flex;align-items:center;gap:7px;font-family:Manrope,-apple-system,sans-serif;" +
          "white-space:nowrap;pointer-events:none;transform:translateY(-6px);}" +
          // colored score ring — conic-gradient donut, fill % = health score, status-colored
          ".kd-co-ring{position:relative;width:30px;height:30px;border-radius:50%;flex:0 0 auto;" +
          "display:flex;align-items:center;justify-content:center;" +
          "background:conic-gradient(#10D478 0,rgba(255,255,255,0.14) 0);" +
          "box-shadow:0 0 0 1.5px rgba(255,255,255,0.20),0 2px 7px rgba(0,0,0,0.55);}" +
          ".kd-co-ring::before{content:'';position:absolute;inset:3.5px;border-radius:50%;" +
          "background:#0B1020;box-shadow:inset 0 0 5px rgba(0,0,0,0.7);}" +
          ".kd-co-num{position:relative;z-index:1;font-family:'JetBrains Mono',ui-monospace,monospace;" +
          "font-size:11px;font-weight:800;color:#fff;line-height:1;letter-spacing:-0.5px;}" +
          // label stack — name on top, ID · STATUS sub-line (status-colored), on a soft chip
          ".kd-co-label{display:flex;flex-direction:column;gap:1px;line-height:1.12;" +
          "background:rgba(8,12,24,0.58);padding:2px 8px;border-radius:7px;" +
          "border:1px solid rgba(255,255,255,0.08);}" +
          ".kd-co-name{font-size:10.5px;font-weight:700;color:#F1F5F9;letter-spacing:0.1px;" +
          "text-shadow:0 1px 2px rgba(0,0,0,0.85);}" +
          ".kd-co-sub{font-size:8px;font-weight:800;letter-spacing:0.6px;text-transform:uppercase;color:#94A3B8;}";
        document.head.appendChild(st);
      }
    } catch (e) {}
    hideRegionalGeofence(map);
    addEquipmentCallouts(map);
    // native widgets render a touch late + can re-render; re-apply a few times.
    repositionNative(map);
    setTimeout(function () { repositionNative(map); }, 800);
    setTimeout(function () { repositionNative(map); }, 2500);
  }

  function hideRegionalGeofence(map) {
    try {
      var layers = map.getStyle().layers || [];
      layers.forEach(function (l) {
        if (/geofence|zone|perimeter|control|sl3|tracker|dispatch/i.test(l.id)) {
          try { map.setLayoutProperty(l.id, "visibility", "none"); } catch (e) {}
        }
      });
    } catch (e2) {}
  }

  function addEquipmentCallouts(map) {
    if (typeof maplibregl === "undefined") { return; }
    var i, e, el, ring, num, label, name, sub;
    for (i = 0; i < EQUIP.length; i++) {
      e = EQUIP[i];
      if (_callouts[e.id]) { continue; }
      el = document.createElement("div");
      el.className = "kd-co";

      // colored score ring (conic donut) with the health number in the center
      ring = document.createElement("div");
      ring.className = "kd-co-ring";
      num = document.createElement("div");
      num.className = "kd-co-num";
      num.textContent = "–";
      ring.appendChild(num);

      // label stack: asset name + "ID · STATUS" sub-line
      label = document.createElement("div");
      label.className = "kd-co-label";
      name = document.createElement("div");
      name.className = "kd-co-name";
      name.textContent = e.name;
      sub = document.createElement("div");
      sub.className = "kd-co-sub";
      sub.textContent = e.id + " · —";
      label.appendChild(name); label.appendChild(sub);

      el.appendChild(ring); el.appendChild(label);
      try {
        // Tall/built-up units (flare stack, radio tower, the gas-lift compressor
        // skid) rise UP the screen, so anchor the label+ring UNDERNEATH the base
        // (centered, hanging below) instead of to the side — otherwise the callout
        // collides with the unit.
        var tall = (e.type === "flare" || e.type === "tower" || e.type === "compressor" || e.type === "shelter" || e.type === "power" || e.type === "dehydrator" || e.type === "combustor");
        // Storage tanks are tall verticals — float the label+ring ABOVE the tank
        // top (anchor the callout's bottom edge ~132px above the base point).
        var tank = (e.type === "oiltank" || e.type === "watertank");
        var opts = tank
          ? { element: el, anchor: "bottom", offset: [0, -132] }
          : tall
            ? { element: el, anchor: "top", offset: [0, 16] }
            : { element: el, anchor: "left", offset: [12, 0] };
        if (tall || tank) { el.style.flexDirection = "column"; el.style.alignItems = "center"; el.style.gap = "3px"; el.style.transform = "none"; }
        var mk = new maplibregl.Marker(opts).setLngLat([e.lng, e.lat]).addTo(map);
        _callouts[e.id] = { marker: mk, ring: ring, num: num, sub: sub, name: name, node: e };
      } catch (ex) {}
    }
  }
  function COL_HEX(n) { return "#" + ("000000" + n.toString(16)).slice(-6); }

  function repositionNative(map) {
    try {
      var c = map.getContainer();
      if (!c) { return; }
      // The map-overlay layout — the weather-widget position AND the Measure
      // button location — is now controlled entirely by CSS in Aevus_Console.html
      // (.map-weather-legend raised off the bottom; .map-measure-btn moved under
      // the Layers box). The old DOM-walk here grabbed wrong elements: the weather
      // pass shoved the whole map down (2026-06-04) and the Measure pass never
      // matched (button text wasn't exactly "Measure"). Both removed.
      void c;
    } catch (e) {}
  }

  var _STATUS_WORD = { good: "Healthy", warn: "Warning", bad: "Critical" };
  function updateCallouts(byId) {
    var id, co, a, hex, score, word;
    for (id in _callouts) {
      if (!_callouts.hasOwnProperty(id)) { continue; }
      co = _callouts[id];
      a = (co.node.asset_id && byId[co.node.asset_id]) || null;
      if (a) {
        hex = (a.status === "bad") ? COL.bad : (a.status === "warn") ? COL.warn : COL.good;
        score = (typeof a.health === "number") ? a.health : null;
        word = _STATUS_WORD[a.status] || (a.status || "").toString();
      } else {
        hex = COL.accent; score = null; word = "—";  // unbound equipment — neutral, no fake score
      }
      try {
        var hexS = COL_HEX(hex);
        // ring: fill arc proportional to the score, in the status color; track = faint white
        var pct = (score === null) ? 0 : Math.max(0, Math.min(100, score));
        co.ring.style.background = (score === null)
          ? "conic-gradient(rgba(255,255,255,0.16) 0 100%)"
          : "conic-gradient(" + hexS + " 0 " + pct + "%,rgba(255,255,255,0.14) " + pct + "% 100%)";
        co.num.textContent = (score === null) ? "–" : String(Math.round(score));
        co.num.style.color = (score === null) ? "#94A3B8" : "#fff";
        // sub-line: "ID · STATUS" with the status word in the status color
        co.sub.innerHTML = co.node.id + " · <span style=\"color:" + hexS + "\">" + word + "</span>";
      } catch (e) {}
    }
  }

  window.AevusKilldeer3D = {
    simulate: function (name) { return simulateScenario(name || "compressor-trip"); },
    clearSim: function () { clearSim(); },
    setFlow: function (segId, opts) {
      var i, s;
      opts = opts || {};
      for (i = 0; i < segments.length; i++) {
        s = segments[i];
        if (s.id === segId) {
          if (typeof opts.rate === "number") {
            // map a 0..1 normalized rate to a flow speed; keep direction sign
            s.speed = Math.max(0, opts.rate) * (s.baseSpeed > 0 ? 1 : 1) * 0.2;
          }
          if (opts.state === "stopped") { s.speed = 0; }
          return true;
        }
      }
      return false;
    },
    remount: function () { _attachedMap = null; tick(); },
    frame: function () { if (_attachedMap) { frameFacility(_attachedMap); } },
    debug: function () {
      return { attached: !!_attachedMap, segments: segments.length,
               equip: Object.keys(equipMeshes).length, hasRenderer: !!renderer };
    }
  };
  // live segment registry (getter — `segments` is reassigned on each attach)
  try { Object.defineProperty(window.AevusKilldeer3D, "_segments", { get: function () { return segments; } }); } catch (e) {}

  console.log("[killdeer3d] module loaded — awaiting map");
})();

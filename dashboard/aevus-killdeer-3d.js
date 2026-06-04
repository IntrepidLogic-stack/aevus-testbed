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
  var FRAME = { center: [-95.86769, 29.33956], zoom: 20.1, pitch: 55, bearing: -20 };

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
    { id: "WH",  lng: -95.86790, lat: 29.33982, type: "wellhead",  name: "Wellhead — BlueJay #1" },
    { id: "CHE", lng: -95.86800, lat: 29.33978, type: "chemtote",  name: "Chemical Injection" },
    { id: "SEP", lng: -95.86790, lat: 29.33965, type: "separator", name: "2-Phase Separator" },
    { id: "CMP", lng: -95.86815, lat: 29.33968, type: "compressor",name: "Gas-Lift Compressor" },
    { id: "OT1", lng: -95.86755, lat: 29.33967, type: "oiltank",   name: "Stock Tank #1" },
    { id: "OT2", lng: -95.86755, lat: 29.33960, type: "oiltank",   name: "Stock Tank #2" },
    { id: "PWT", lng: -95.86742, lat: 29.33965, type: "watertank", name: "Produced Water Tank" },
    { id: "EFM", lng: -95.86735, lat: 29.33948, type: "efm",       name: "EFM / Custody Meter" },
    { id: "FLR", lng: -95.86790, lat: 29.33932, type: "flare",     name: "Flare Stack" },
    { id: "TWR", lng: -95.86735, lat: 29.33992, type: "tower",     name: "Radio Tower" }
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
  function loadTopology() {
    var finish = function () { _topoReady = true; };
    var safety = setTimeout(finish, 5000);  // never block forever on a hung fetch
    try {
      fetch("/api/v1/twin/facility/" + TWIN_FACILITY + "/topology", { credentials: "same-origin" })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (t) {
          if (t && t.nodes && t.edges) {
            if (Array.isArray(t.origin) && t.origin.length === 2) { ORIGIN = t.origin; }
            if (t.frame && t.frame.center) {
              FRAME = { center: t.frame.center, zoom: t.frame.zoom, pitch: t.frame.pitch, bearing: t.frame.bearing };
            }
            EQUIP = t.nodes.map(function (n) {
              return { id: n.id, lng: n.lnglat[0], lat: n.lnglat[1], type: n.type, name: n.name, asset_id: n.asset_id };
            });
            PIPES = t.edges.map(function (e) {
              return { id: e.id, from: e.from, to: e.to, product: e.product,
                       rackH: e.rack_h_m || 2.2, speed: _BASE_SPEED[e.product] || 0.1 };
            });
            console.log("[killdeer3d] topology from API:", EQUIP.length, "nodes,", PIPES.length, "edges");
          } else {
            console.warn("[killdeer3d] topology API empty — using fallback geometry");
          }
          clearTimeout(safety); finish();
        })
        .catch(function () { console.warn("[killdeer3d] topology fetch failed — using fallback"); clearTimeout(safety); finish(); });
    } catch (e) { clearTimeout(safety); finish(); }
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
  var transform = null;
  var _attachedMap = null;
  var _frameIv = null;          // single persistent auto-frame enforcement loop
  var _frameMove = null;        // per-frame 'move' snap handler (kills load flicker)
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
  function buildWellhead() {
    var g = new THREEref.Group();
    var spoolG = new THREEref.CylinderGeometry(0.45, 0.5, 1.4, 16);
    var spool = new THREEref.Mesh(spoolG, metal(COL.steelDark)); spool.position.y = 0.7; g.add(spool);
    var tree = new THREEref.Mesh(new THREEref.BoxGeometry(0.5, 1.8, 0.5), metal(COL.steel));
    tree.position.y = 1.9; g.add(tree);
    var wheel = new THREEref.Mesh(new THREEref.TorusGeometry(0.42, 0.07, 8, 18), metal(0xC44));
    wheel.position.set(0.45, 1.6, 0); wheel.rotation.y = Math.PI / 2; g.add(wheel);
    var cap = new THREEref.Mesh(new THREEref.SphereGeometry(0.28, 12, 8), metal(COL.steel));
    cap.position.y = 2.85; g.add(cap);
    return g;
  }

  function buildChemTote() {
    var g = new THREEref.Group();
    var tank = new THREEref.Mesh(new THREEref.BoxGeometry(1.2, 1.2, 1.2), glowMat(PRODUCT.chemical, 0.55));
    tank.position.y = 0.9; g.add(tank);
    addEdges(g, new THREEref.BoxGeometry(1.25, 1.25, 1.25), tank, 0xCBD5E1, 0.6);
    var base = new THREEref.Mesh(new THREEref.BoxGeometry(1.35, 0.3, 1.35), skidMat());
    base.position.y = 0.15; g.add(base);
    return g;
  }

  function buildSeparator() {
    var g = new THREEref.Group();
    var len = 7.0, r = 1.4;
    var bodyG = new THREEref.CylinderGeometry(r, r, len, 24);
    var body = new THREEref.Mesh(bodyG, metal(COL.steel));
    body.rotation.z = Math.PI / 2; body.position.y = r + 0.9; g.add(body);
    addEdges(g, bodyG, body, COL.accent, 0.35);
    // domed end caps
    var capA = new THREEref.Mesh(new THREEref.SphereGeometry(r, 16, 12), metal(COL.steel));
    capA.position.set(-len / 2, r + 0.9, 0); g.add(capA);
    var capB = new THREEref.Mesh(new THREEref.SphereGeometry(r, 16, 12), metal(COL.steel));
    capB.position.set(len / 2, r + 0.9, 0); g.add(capB);
    // saddle supports
    var sx, k, dx = [-len * 0.3, len * 0.3];
    for (k = 0; k < dx.length; k++) {
      sx = dx[k];
      var sad = new THREEref.Mesh(new THREEref.BoxGeometry(0.6, 0.9, r * 2.0), skidMat());
      sad.position.set(sx, 0.45, 0); g.add(sad);
    }
    // relief nozzle on top
    var noz = new THREEref.Mesh(new THREEref.CylinderGeometry(0.16, 0.16, 1.2, 10), metal(COL.steelDark));
    noz.position.set(len * 0.25, r + 0.9 + r + 0.5, 0); g.add(noz);
    return g;
  }

  function buildCompressor() {
    var g = new THREEref.Group();
    var skid = new THREEref.Mesh(new THREEref.BoxGeometry(5.2, 0.5, 3.0), skidMat());
    skid.position.y = 0.25; g.add(skid);
    var engine = new THREEref.Mesh(new THREEref.BoxGeometry(3.0, 1.7, 1.7), metal(COL.steel));
    engine.position.set(-0.6, 1.35, 0); g.add(engine);
    addEdges(g, new THREEref.BoxGeometry(3.0, 1.7, 1.7), engine, COL.accent, 0.3);
    var cyl = new THREEref.Mesh(new THREEref.CylinderGeometry(0.9, 0.9, 2.2, 18), metal(COL.steelDark));
    cyl.rotation.z = Math.PI / 2; cyl.position.set(1.7, 1.1, 0); g.add(cyl);
    var stack = new THREEref.Mesh(new THREEref.CylinderGeometry(0.22, 0.26, 3.2, 12), metal(COL.steelDark));
    stack.position.set(-1.6, 2.9, -0.6); g.add(stack);
    return g;
  }

  function buildTank(productKey, level) {
    var g = new THREEref.Group();
    var r = 2.8, h = 6.0;
    var shellG = new THREEref.CylinderGeometry(r, r, h, 28, 1, true);
    var shell = new THREEref.Mesh(shellG, new THREEref.MeshStandardMaterial({
      color: COL.steel, metalness: 0.5, roughness: 0.5, side: THREEref.DoubleSide
    }));
    shell.position.y = h / 2; g.add(shell);
    addEdges(g, new THREEref.CylinderGeometry(r, r, h, 28), shell, COL.accent, 0.28);
    // flat roof
    var roof = new THREEref.Mesh(new THREEref.CylinderGeometry(r, r, 0.3, 28), metal(COL.steelDark));
    roof.position.y = h + 0.15; g.add(roof);
    // thief hatch
    var hatch = new THREEref.Mesh(new THREEref.CylinderGeometry(0.4, 0.4, 0.4, 12), metal(COL.steelDark));
    hatch.position.set(r * 0.4, h + 0.4, 0); g.add(hatch);
    // liquid level fill (product-tinted, translucent)
    var lvl = Math.max(0.05, Math.min(0.95, level || 0.6));
    var fillG = new THREEref.CylinderGeometry(r * 0.96, r * 0.96, h * lvl, 28);
    var fill = new THREEref.Mesh(fillG, glowMat(PRODUCT[productKey], 0.35));
    fill.position.y = (h * lvl) / 2; g.add(fill);
    return g;
  }

  function buildFlare() {
    var g = new THREEref.Group();
    var h = 12.0;
    var mast = new THREEref.Mesh(new THREEref.CylinderGeometry(0.32, 0.45, h, 14), metal(COL.steelDark));
    mast.position.y = h / 2; g.add(mast);
    // guy-wire suggestion: 3 thin struts
    var a, i;
    for (i = 0; i < 3; i++) {
      a = (i / 3) * Math.PI * 2;
      var strut = new THREEref.Mesh(new THREEref.CylinderGeometry(0.04, 0.04, h * 0.7, 6), metal(COL.skid));
      strut.position.set(Math.cos(a) * 1.6, h * 0.42, Math.sin(a) * 1.6);
      strut.rotation.z = Math.cos(a) * 0.28; strut.rotation.x = -Math.sin(a) * 0.28;
      g.add(strut);
    }
    var flame = new THREEref.Mesh(new THREEref.ConeGeometry(0.95, 2.6, 14), glowMat(COL.flame, 0.85));
    flame.position.y = h + 1.3; g.add(flame);
    flameMeshes.push(flame);
    var pl = new THREEref.PointLight(0xFF7A2C, 1.3, 34); pl.position.set(0, h + 1.3, 0); g.add(pl);
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

  function buildEquip(type) {
    if (type === "wellhead")   { return buildWellhead(); }
    if (type === "chemtote")   { return buildChemTote(); }
    if (type === "separator")  { return buildSeparator(); }
    if (type === "compressor") { return buildCompressor(); }
    if (type === "oiltank")    { return buildTank("oil", 0.7); }
    if (type === "watertank")  { return buildTank("water", 0.55); }
    if (type === "efm")        { return buildEFM(); }
    if (type === "flare")      { return buildFlare(); }
    if (type === "tower")      { return buildTower(); }
    return new THREEref.Group();
  }

  // ── PIPE BUILDER ────────────────────────────────────────────────────────────
  function buildPipe(spec) {
    var a = equipLocal(spec.from), b = equipLocal(spec.to);
    var nozzle = 1.4;
    var pts = [
      new THREEref.Vector3(a.x, nozzle, a.z),
      new THREEref.Vector3(a.x, spec.rackH, a.z),
      new THREEref.Vector3((a.x + b.x) / 2, spec.rackH, (a.z + b.z) / 2),
      new THREEref.Vector3(b.x, spec.rackH, b.z),
      new THREEref.Vector3(b.x, nozzle, b.z)
    ];
    var curve = new THREEref.CatmullRomCurve3(pts, false, "catmullrom", 0.4);
    var tubeG = new THREEref.TubeGeometry(curve, 48, 0.22, 10, false);
    var color = PRODUCT[spec.product];
    var mesh = new THREEref.Mesh(tubeG, pmat(color));
    facility.add(mesh);

    // flow packets — small bright spheres travelling the curve
    var packets = [], k, np = 3;
    for (k = 0; k < np; k++) {
      var pk = new THREEref.Mesh(new THREEref.SphereGeometry(0.34, 10, 8), glowMat(0xFFFFFF, 0.9));
      pk.material.color.setHex(color);
      facility.add(pk);
      packets.push({ mesh: pk, offset: k / np });
    }
    return { id: spec.id, mesh: mesh, curve: curve, packets: packets,
             product: spec.product, baseSpeed: spec.speed, speed: spec.speed };
  }

  // ── FACILITY ASSEMBLY ───────────────────────────────────────────────────────
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

    // pipes (added straight to facility inside buildPipe)
    var j;
    for (j = 0; j < PIPES.length; j++) {
      segments.push(buildPipe(PIPES[j]));
    }

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

  function attach(map) {
    if (!window.THREE) { return; }     // THREE not loaded yet
    _attachedMap = map;
    // reset per-mount state (new map instance => rebuild scene in onAdd)
    scene = null; renderer = null; facility = null;
    segments = []; equipMeshes = {}; flameMeshes = []; blinkMeshes = []; _callouts = {};
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
    var done = false, snapping = false;

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
        map.jumpTo({ center: FRAME.center, zoom: FRAME.zoom, pitch: FRAME.pitch, bearing: FRAME.bearing });
      } catch (e) {}
      snapping = false;
    }
    function cleanup() {
      if (_frameIv) { clearInterval(_frameIv); _frameIv = null; }
      if (_frameMove) { try { map.off("move", _frameMove); } catch (e) {} _frameMove = null; }
      try { map.off("dragstart", onUser); map.off("zoomstart", onUser); map.off("rotatestart", onUser); } catch (e) {}
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
      box.style.cssText = "position:absolute;bottom:140px;left:50%;transform:translateX(-50%);z-index:6;" +
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
      box.style.cssText = "position:absolute;bottom:84px;left:50%;transform:translateX(-50%);z-index:6;" +
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
          ".kd-co{display:flex;align-items:center;gap:5px;font-family:Manrope,-apple-system,sans-serif;" +
          "white-space:nowrap;pointer-events:none;transform:translateY(-6px);}" +
          ".kd-co-dot{width:16px;height:16px;border-radius:50%;display:flex;align-items:center;justify-content:center;" +
          "font-size:8px;font-weight:800;color:#04121A;box-shadow:0 0 8px rgba(0,0,0,0.6);border:1.5px solid rgba(255,255,255,0.85);}" +
          ".kd-co-name{font-size:10px;font-weight:600;color:#E2E8F0;text-shadow:0 1px 3px #000,0 0 4px #000;letter-spacing:0.2px;}";
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
    var i, e, el, dot, name;
    for (i = 0; i < EQUIP.length; i++) {
      e = EQUIP[i];
      if (_callouts[e.id]) { continue; }
      el = document.createElement("div");
      el.className = "kd-co";
      dot = document.createElement("div");
      dot.className = "kd-co-dot";
      dot.style.background = COL_HEX(COL.good);
      name = document.createElement("div");
      name.className = "kd-co-name";
      name.textContent = e.name;
      el.appendChild(dot); el.appendChild(name);
      try {
        var mk = new maplibregl.Marker({ element: el, anchor: "left", offset: [10, 0] })
          .setLngLat([e.lng, e.lat]).addTo(map);
        _callouts[e.id] = { marker: mk, dot: dot, name: name, node: e };
      } catch (ex) {}
    }
  }
  function COL_HEX(n) { return "#" + ("000000" + n.toString(16)).slice(-6); }

  function repositionNative(map) {
    try {
      var c = map.getContainer();
      if (!c) { return; }
      var k;
      // NOTE: the old "raise the WEATHER widget" pass is intentionally REMOVED.
      // It matched a div by text "WEATHER", walked up to the first absolutely-
      // positioned ANCESTOR, and set bottom:84px on it. That ancestor was a large
      // wrapper, so the whole map content shifted hugely downward on load
      // (reported 2026-06-04). Net: leave the native weather widget where MapLibre
      // puts it rather than risk moving an unintended parent.
      // Measure control: move under the Layers box (top-left).
      var btns = c.querySelectorAll("button, div, a");
      for (k = 0; k < btns.length; k++) {
        if ((btns[k].textContent || "").trim() === "Measure") {
          var m = btns[k];
          var box = m.closest("[style*='position']") || m;
          box.style.position = "absolute";
          box.style.top = "300px"; box.style.left = "18px";
          box.style.right = "auto"; box.style.bottom = "auto"; box.style.zIndex = "5";
          break;
        }
      }
    } catch (e) {}
  }

  function updateCallouts(byId) {
    var id, co, a, hex, txt;
    for (id in _callouts) {
      if (!_callouts.hasOwnProperty(id)) { continue; }
      co = _callouts[id];
      a = (co.node.asset_id && byId[co.node.asset_id]) || null;
      if (a) {
        hex = (a.status === "bad") ? COL.bad : (a.status === "warn") ? COL.warn : COL.good;
        txt = (typeof a.health === "number") ? String(a.health) : "";
      } else {
        hex = COL.accent; txt = "";  // unbound equipment — neutral accent, no fake number
      }
      try { co.dot.style.background = COL_HEX(hex); co.dot.textContent = txt; } catch (e) {}
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

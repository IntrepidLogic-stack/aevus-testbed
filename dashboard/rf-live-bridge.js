/**
 * Aevus RF Live Bridge — non-invasive live-data overlay for the locked
 * production Aevus_Console.html design.
 *
 * INTENT
 * ──────
 * The deployed dashboard at https://aevus.intrepidlogic.io/dashboard/Aevus_Console.html
 * is frozen for an awards submission. We cannot edit its HTML or CSS.
 *
 * But the page was built with stable IDs on every data field (rf-r1-rssi,
 * rf-r1-qual, rf-r1-txpwr, etc.). This script subscribes to AWS IoT Core
 * MQTT-over-WSS via the aevus-dashboard-iot Cognito Identity Pool and
 * swaps the textContent of those IDs as live telemetry arrives. It
 * NEVER changes any element's class, style, structure, or attributes —
 * only the inner text. The awards-submission visual is preserved
 * exactly.
 *
 * DELIVERY
 * ────────
 * Loaded via a bookmarklet (the page itself is not modified). The
 * bookmarklet injects:
 *   <script src="https://aevus-telemetry-archive-676433090238.s3.amazonaws.com/dashboard-overlays/rf-live-bridge.js">
 * which fetches this file, which then loads aws-sdk + mqtt.js from CDN
 * and starts the bridge.
 *
 * REVERSAL
 * ────────
 * Close the browser tab. No state survives. The next page load is the
 * untouched demo. Re-click the bookmark to re-enter live mode.
 */
(function () {
  'use strict';

  // Guard against double-load
  if (window.__AEVUS_LIVE_BRIDGE__) {
    console.log('[Aevus Live] Already running — no-op');
    return;
  }
  window.__AEVUS_LIVE_BRIDGE__ = true;

  const CONFIG = {
    awsRegion: 'us-east-1',
    awsIotEndpoint: 'a23tc2oxyb9d91-ats.iot.us-east-1.amazonaws.com',
    identityPoolId: 'us-east-1:05934a30-b27c-4261-96db-e85ea7483ac2',
    siteId: 'needville',
    clientId: 'aevus-live-overlay-' + Math.random().toString(16).slice(2, 8),
  };

  // ── Field map: MQTT envelope.payload.metric → DOM id (per asset) ─────
  // Only updates textContent. Format preserved per existing display style.
  const FIELDS = {
    'RAD-01': {
      rssi:          { id: 'rf-r1-rssi',  fmt: v => `${v.toFixed(1)}` },
      snr:           { id: 'rf-r1-snr',   fmt: v => `${v.toFixed(0)}` },  // if exists
      link_quality:  { id: 'rf-r1-qual',  fmt: v => `${Math.round(v)}%` },
      tx_power:      { id: 'rf-r1-txpwr', fmt: v => `${v.toFixed(3)}` },
      temperature:   { id: 'rf-r1-temp',  fmt: v => `${v.toFixed(3)}°C` },
      voltage:       { id: 'rf-r1-volts', fmt: v => `${v.toFixed(1)}V` },
    },
    'RAD-02': {
      rssi:          { id: 'rf-r2-rssi',  fmt: v => `${v.toFixed(1)}` },
      snr:           { id: 'rf-r2-snr',   fmt: v => `${v.toFixed(0)}` },
      link_quality:  { id: 'rf-r2-qual',  fmt: v => `${Math.round(v)}%` },
      tx_power:      { id: 'rf-r2-txpwr', fmt: v => `${v.toFixed(3)}` },
      temperature:   { id: 'rf-r2-temp',  fmt: v => `${v.toFixed(3)}°C` },
      voltage:       { id: 'rf-r2-volts', fmt: v => `${v.toFixed(1)}V` },
    },
  };

  // Aggregated counters (sum across both radios)
  const AGGREGATES = {
    rx_packets: { id: 'rf-total-pkts', vals: { 'RAD-01': 0, 'RAD-02': 0 } },
    error_packets: { id: 'rf-total-err', vals: { 'RAD-01': 0, 'RAD-02': 0 } },
  };

  // ── Indicator: tiny floating badge so you know the overlay is on ─────
  function injectBadge() {
    const b = document.createElement('div');
    b.id = '__aevus_live_badge__';
    b.textContent = 'LIVE';
    b.style.cssText = [
      'position:fixed','top:6px','right:6px','z-index:99999',
      'background:#10D478','color:#0B1020','padding:2px 8px',
      'font:600 10px/1 system-ui,-apple-system,monospace',
      'border-radius:3px','letter-spacing:0.5px','pointer-events:none',
      'box-shadow:0 0 8px rgba(16,212,120,0.6)',
    ].join(';');
    document.body.appendChild(b);
    // Pulse when a message arrives
    window.__aevusPulse__ = () => {
      b.style.boxShadow = '0 0 16px rgba(16,212,120,1)';
      setTimeout(() => { b.style.boxShadow = '0 0 8px rgba(16,212,120,0.6)'; }, 150);
    };
  }

  function setText(id, value) {
    const el = document.getElementById(id);
    if (!el) return;
    el.textContent = value;
  }

  function applyTelemetry(envelope) {
    const asset = envelope.asset_id;
    const metric = envelope.payload?.metric;
    const value = envelope.payload?.value;
    if (asset == null || metric == null || value == null) return;
    if (typeof value !== 'number') return;

    if (FIELDS[asset]?.[metric]) {
      const spec = FIELDS[asset][metric];
      setText(spec.id, spec.fmt(value));
    }
    if (AGGREGATES[metric]) {
      AGGREGATES[metric].vals[asset] = value;
      const sum = Object.values(AGGREGATES[metric].vals).reduce((a, b) => a + b, 0);
      // Format counters with K/M suffix to match awards-page style
      const formatted = sum >= 1_000_000 ? (sum/1_000_000).toFixed(1) + 'M'
                      : sum >= 1_000 ? Math.round(sum/1000) + 'K'
                      : String(sum);
      setText(AGGREGATES[metric].id, formatted);
    }
    if (window.__aevusPulse__) window.__aevusPulse__();
  }

  // ── Cognito + SigV4 presign (same logic as cognito-iot-init.js) ──────
  function presignIotWssUrl(creds) {
    const region = CONFIG.awsRegion;
    const endpoint = CONFIG.awsIotEndpoint;
    const time = new Date();
    const dateStamp = time.toISOString().slice(0, 10).replace(/-/g, '');
    const amzdate = time.toISOString().replace(/[:-]|\.\d{3}/g, '');
    const service = 'iotdevicegateway';
    const algorithm = 'AWS4-HMAC-SHA256';
    const credentialScope = `${dateStamp}/${region}/${service}/aws4_request`;
    const canonicalQs =
      'X-Amz-Algorithm=' + algorithm +
      '&X-Amz-Credential=' + encodeURIComponent(creds.accessKeyId + '/' + credentialScope) +
      '&X-Amz-Date=' + amzdate +
      '&X-Amz-SignedHeaders=host';
    const payloadHash = AWS.util.crypto.sha256('', 'hex');
    const canonicalRequest = `GET\n/mqtt\n${canonicalQs}\nhost:${endpoint}\n\nhost\n${payloadHash}`;
    const stringToSign = `${algorithm}\n${amzdate}\n${credentialScope}\n${AWS.util.crypto.sha256(canonicalRequest, 'hex')}`;
    const kDate    = AWS.util.crypto.hmac('AWS4' + creds.secretAccessKey, dateStamp, 'buffer');
    const kRegion  = AWS.util.crypto.hmac(kDate, region, 'buffer');
    const kService = AWS.util.crypto.hmac(kRegion, service, 'buffer');
    const kSigning = AWS.util.crypto.hmac(kService, 'aws4_request', 'buffer');
    const signature = AWS.util.crypto.hmac(kSigning, stringToSign, 'hex');
    let url = `wss://${endpoint}/mqtt?${canonicalQs}&X-Amz-Signature=${signature}`;
    if (creds.sessionToken) url += '&X-Amz-Security-Token=' + encodeURIComponent(creds.sessionToken);
    return url;
  }

  function loadScript(src) {
    return new Promise((resolve, reject) => {
      const s = document.createElement('script');
      s.src = src;
      s.onload = resolve;
      s.onerror = () => reject(new Error('load failed: ' + src));
      document.head.appendChild(s);
    });
  }

  async function boot() {
    console.log('[Aevus Live] Booting RF live bridge...');
    try {
      await Promise.all([
        typeof AWS === 'undefined' ? loadScript('https://sdk.amazonaws.com/js/aws-sdk-2.1503.0.min.js') : Promise.resolve(),
        typeof mqtt === 'undefined' ? loadScript('https://unpkg.com/mqtt/dist/mqtt.min.js') : Promise.resolve(),
      ]);
    } catch (e) {
      console.error('[Aevus Live] Library load failed:', e);
      return;
    }

    AWS.config.region = CONFIG.awsRegion;
    AWS.config.credentials = new AWS.CognitoIdentityCredentials({ IdentityPoolId: CONFIG.identityPoolId });

    AWS.config.credentials.get(err => {
      if (err) {
        console.error('[Aevus Live] Cognito creds failed:', err);
        return;
      }
      const c = AWS.config.credentials;
      const url = presignIotWssUrl({
        accessKeyId: c.accessKeyId,
        secretAccessKey: c.secretAccessKey,
        sessionToken: c.sessionToken,
      });
      console.log('[Aevus Live] Cognito identity ready:', c.identityId);
      const client = mqtt.connect(url, {
        clientId: CONFIG.clientId,
        reconnectPeriod: 5000,
        keepalive: 60,
        clean: true,
        protocolVersion: 5,
      });
      client.on('connect', () => {
        console.log('[Aevus Live] MQTT connected, subscribing aevus/' + CONFIG.siteId + '/#');
        client.subscribe(`aevus/${CONFIG.siteId}/#`, { qos: 1 });
        injectBadge();
      });
      client.on('error', err => console.warn('[Aevus Live] MQTT error:', err.message || err));
      client.on('message', (topic, payload) => {
        let env;
        try { env = JSON.parse(payload.toString('utf-8')); }
        catch (e) { return; }
        const parts = topic.split('/');
        const cls = parts[3];  // alert/alerts | telemetry | events | state | rca
        if (cls === 'telemetry') applyTelemetry(env);
        // Future: alerts/rca handlers can update rf-link-status, rf-quality-fill, etc.
      });
    });
  }

  boot();
})();

# Aevus Dashboard — MQTT integration

The existing `Aevus_Console.html` polls the FastAPI REST API and subscribes to a FastAPI WebSocket via `api-client.js`. That path stays — it's the local-only / no-cloud fallback.

This MQTT layer is the **cloud-native real-time channel**. Same dashboard, new data path: the browser subscribes directly to `aevus/<site>/#` on a broker (local Mosquitto in dev, AWS IoT Core in production) and renders messages as they arrive.

The two paths are non-conflicting — they can both run, and whichever message arrives first updates the UI.

---

## 1. Files

```
dashboard/
├── Aevus_Console.html      # existing — UNCHANGED
├── api-client.js           # existing — UNCHANGED (REST + FastAPI WebSocket)
├── topology.html           # existing — UNCHANGED
├── mqtt-client.js          # NEW — MQTT-over-WS subscriber, dispatches by topic class
├── rca-panel.js            # NEW — slide-up RCA narrative panel (uses mqtt-client.js)
└── README.md               # this file
```

The new files are **sidecars** — they don't modify the existing HTML, just add functionality. Activation is a one-line `<script>` tag (see §4).

---

## 2. Topic → handler map

```
aevus/<site>/<asset>/alerts/<severity>    → window.AEVUS_MQTT.on('alert', fn)
aevus/<site>/<asset>/rca/<alert_id>       → window.AEVUS_MQTT.on('rca', fn)   ← rca-panel.js
aevus/<site>/<asset>/state/<key>          → window.AEVUS_MQTT.on('state', fn)
aevus/<site>/<asset>/events/<class>       → window.AEVUS_MQTT.on('event', fn)
aevus/<site>/<asset>/telemetry/<metric>   → window.AEVUS_MQTT.on('telemetry', fn)
```

Every message also fires the `'raw'` handler, useful for debug widgets and a future operator-facing audit panel.

---

## 3. Two transport modes

### 3a. Local (dev — Mosquitto on the Pi)

Mosquitto's WebSocket listener defaults to port 9001. Add to `/etc/mosquitto/mosquitto.conf`:

```conf
listener 1883
listener 9001
protocol websockets
allow_anonymous true   # dev only — never in production
```

Restart: `sudo systemctl restart mosquitto`. From the dashboard host:

```html
<script>
  window.AEVUS_MQTT_CONFIG = {
    transport: 'local',
    brokerUrl: 'ws://aevus-edge.local:9001/mqtt',
    siteId: 'lab',
  };
</script>
<script src="https://unpkg.com/mqtt/dist/mqtt.min.js"></script>
<script src="mqtt-client.js"></script>
<script src="rca-panel.js"></script>
```

### 3b. Cloud (AWS IoT Core MQTT-over-WSS)

AWS IoT Core MQTT-over-WebSocket requires a SigV4-signed URL. The flow:

1. **Provision a Cognito Identity Pool** with an unauthenticated role that has `iot:Connect` + `iot:Subscribe` on `aevus/<site>/#` only. Add this to `infra/terraform/aws-cognito.tf` (TODO — next round).

2. **At page load**, the dashboard fetches a Cognito identity, then uses the AWS SDK for JavaScript v3 to construct a presigned MQTT URL:

   ```js
   import { fromCognitoIdentityPool } from '@aws-sdk/credential-providers';
   import { SignatureV4 } from '@aws-sdk/signature-v4';
   import { Sha256 } from '@aws-crypto/sha256-js';

   const credentials = fromCognitoIdentityPool({
     identityPoolId: 'us-east-2:....',
     clientConfig: { region: 'us-east-2' },
   });

   const signer = new SignatureV4({
     credentials, service: 'iotdevicegateway',
     region: 'us-east-2', sha256: Sha256,
   });

   const signedRequest = await signer.presign({
     method: 'GET',
     hostname: 'YOUR-IOT-ENDPOINT-ats.iot.us-east-2.amazonaws.com',
     path: '/mqtt',
     protocol: 'wss:',
   });

   window.AEVUS_MQTT_CONFIG = {
     transport: 'cloud',
     brokerUrl: `wss://${signedRequest.hostname}${signedRequest.path}?${
       new URLSearchParams(signedRequest.query).toString()
     }`,
     siteId: 'lab',
   };
   ```

3. Include `mqtt-client.js` + `rca-panel.js` after the config block above.

The Cognito Identity Pool + IAM policies are queued for the next Terraform round (the cloud-side data flow is fully provisioned through SiteWise + Bedrock now; this is the *operator UI* side of cloud-side ingest).

---

## 4. Wiring the existing console without touching it

Add **at the bottom of `Aevus_Console.html`**, right before the closing `</body>`:

```html
<!-- ── Phase 7: MQTT real-time + RCA panel ───────────────────── -->
<script>
  window.AEVUS_MQTT_CONFIG = {
    transport: 'local',  // 'cloud' once Cognito is wired
    brokerUrl: 'ws://aevus-edge.local:9001/mqtt',
    siteId: 'lab',
    clientId: 'aevus-console-' + Math.random().toString(16).slice(2, 8),
  };
</script>
<script src="https://unpkg.com/mqtt/dist/mqtt.min.js"></script>
<script src="mqtt-client.js"></script>
<script src="rca-panel.js"></script>
```

That's it. The existing alert list / asset map continues to work via `api-client.js`; the new MQTT path layers on top.

Once you're comfortable, you can also subscribe your own widgets:

```js
window.AEVUS_MQTT.on('telemetry', (envelope) => {
  // envelope = { schema_version, ts, site_id, asset_id, type, source,
  //              payload: { metric, value, unit } }
  updateMyChart(envelope.asset_id, envelope.payload.metric, envelope.payload.value);
});

window.AEVUS_MQTT.on('event', (envelope) => {
  if (envelope.payload.event_class === 'dnp3' && envelope.payload.payload?.latency_ms < 500) {
    // The patent demo path — light up the dashboard when sub-500ms alarms fire.
    flashStatusIndicator(envelope.asset_id);
  }
});
```

---

## 5. Vendoring mqtt.js

`mqtt-client.js` loads `mqtt.js` from `unpkg.com` by default. **Before any federal pursuit or production deploy**, vendor it locally:

```bash
curl -o dashboard/vendor/mqtt.min.js https://unpkg.com/mqtt/dist/mqtt.min.js
```

Then change the `<script src="...">` line to point at `vendor/mqtt.min.js`. This eliminates a third-party CDN dependency in the data path and satisfies typical FedRAMP / supply-chain controls.

---

## 6. Manual smoke test

After wiring, open the console in your browser. The DevTools console should show:

```
[Aevus MQTT] Connecting (local): ws://aevus-edge.local:9001/mqtt
[Aevus MQTT] Connected, subscribing to aevus/lab/#
[Aevus MQTT] Subscribed: [{topic: "aevus/lab/#", qos: 1}]
```

Trigger a known event (toggle the MikroTik link, or run the publisher smoke test from §5b of the Pi README) and watch the console log raw envelopes. To force-render the RCA panel without a real alarm:

```js
window.AEVUS_RCA.render({
  alert_id: 'ALT-SMOKE01',
  asset_id: 'RTU-01',
  latency_ms_alert_to_rca: 2143,
  rca: {
    probable_cause: 'Discharge pressure exceeded critical threshold due to downstream valve closure.',
    evidence: [
      'discharge_pressure rose from 1180 to 1442 PSI in 2 minutes',
      'high_pressure_alarm asserted at 14:32:05Z via DNP3 (latency 143ms)',
      'asset health dropped from 92 to 45'
    ],
    severity: 'critical',
    recommended_action: 'Dispatch field technician to inspect downstream valve V-103 before any restart.',
    confidence: 0.85,
    supporting_assets: ['RTU-01']
  }
});
```

Should slide up the panel with the latency badge reading `2.1s alert→RCA` and confidence at 85% (green).

---

## 7. Brand compliance

Per `~/.claude/CLAUDE.md` and `AEVUS_filesv2/BRAND_SYSTEM_v2.md`:

- ✅ Inline SVG icons only (no emoji, no icon libraries)
- ✅ Manrope for display, JetBrains Mono for numeric
- ✅ Aevus color tokens (`--accent: #06B6D4`, `--status-good: #10D478`, etc.)
- ✅ Mobile-first responsive (panel max-width clamps to viewport)
- ✅ WCAG 2.1 AA contrast — dark surface, high-contrast text
- ✅ Confidence bar uses the platform's status semantics (good ≥ 0.8, warn ≥ 0.6, bad below)

---

## 8. What's next

- **Cognito Identity Pool Terraform** for the cloud-mode signed URL.
- **DNP3 latency widget** — a small ticker showing the rolling median + p95 alert-to-rca + condition-to-alert latencies. Same data we already publish; just a UX surface for the patent demo.
- **L4E anomaly overlay** — when L4E inference scores arrive on `aevus/+/+/events/anomaly`, render a per-asset anomaly heatmap. Lower priority — waits on the L4E training data bootstrap.

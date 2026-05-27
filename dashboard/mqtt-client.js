/**
 * Aevus Dashboard — MQTT-over-WebSocket client
 *
 * Subscribes the browser dashboard directly to the same MQTT topics
 * the edge publisher writes. This is the cloud-native data path —
 * the existing api-client.js (REST + FastAPI WebSocket) stays as
 * the fallback / local-only path.
 *
 * Two transports, selected by config:
 *   • local — ws://<host>:9001  (Mosquitto WebSocket listener)
 *   • cloud — wss://<endpoint>/mqtt  (AWS IoT Core, SigV4-signed URL)
 *
 * Library:
 *   mqtt.js (Eclipse Paho-compatible) — loaded via CDN by default.
 *   For federal / SDVOSB deployments, vendor it locally before
 *   shipping (see dashboard/README.md §5).
 *
 * Topics consumed (per docs/AWS_LANDING_ZONE.md §4):
 *   aevus/+/+/alerts/+       → handleAlert(envelope)
 *   aevus/+/+/rca/+          → handleRcaNarrative(envelope)
 *   aevus/+/+/state/+        → handleState(envelope)
 *   aevus/+/+/events/+       → handleEvent(envelope)
 *   aevus/+/+/telemetry/+    → handleTelemetry(envelope)
 *
 * Each handler is set via window.AEVUS_MQTT.on('alert', fn) — keeps
 * the binding loose so rca-panel.js and the existing api-client.js
 * can plug in without depending on each other.
 *
 * Usage:
 *   <script>
 *     window.AEVUS_MQTT_CONFIG = {
 *       transport: 'local',   // or 'cloud'
 *       brokerUrl: 'ws://localhost:9001/mqtt',
 *       siteId: 'lab',
 *       clientId: 'aevus-dashboard-' + Math.random().toString(16).slice(2, 8),
 *     };
 *   </script>
 *   <script src="https://unpkg.com/mqtt/dist/mqtt.min.js"></script>
 *   <script src="mqtt-client.js"></script>
 */

(function () {
  'use strict';

  // ── Config ───────────────────────────────────────────────────────────
  const DEFAULT_CONFIG = {
    transport: 'local',
    brokerUrl: 'ws://localhost:9001/mqtt',
    siteId: 'lab',
    clientId: 'aevus-dashboard-' + Math.random().toString(16).slice(2, 8),
    // For cloud transport (AWS IoT Core), set:
    //   awsRegion, awsIotEndpoint, awsAccessKey, awsSecretKey, awsSessionToken
    // These typically come from a Cognito Identity Pool unauth role —
    // the dashboard fetches temporary credentials at load time.
    reconnectPeriod: 5000,
    keepalive: 60,
  };
  const config = Object.assign({}, DEFAULT_CONFIG, window.AEVUS_MQTT_CONFIG || {});

  // ── Handler registry ────────────────────────────────────────────────
  // Each topic class maps to a list of callbacks. Multiple subscribers
  // (rca-panel.js, api-client.js, custom widgets) can listen for the
  // same class without stepping on each other.
  const handlers = {
    alert: [],
    rca: [],
    state: [],
    event: [],
    telemetry: [],
    raw: [],          // every message, post-decode (for debug widgets)
    connected: [],    // session open
    disconnected: [], // session lost
  };

  function on(topicClass, fn) {
    if (!handlers[topicClass]) handlers[topicClass] = [];
    handlers[topicClass].push(fn);
  }

  function fire(topicClass, ...args) {
    (handlers[topicClass] || []).forEach((fn) => {
      try {
        fn(...args);
      } catch (e) {
        console.warn(`[Aevus MQTT] ${topicClass} handler error:`, e);
      }
    });
  }

  // ── Topic classification ────────────────────────────────────────────
  // aevus/{site}/{asset}/{class}/{key} — class is the topic level we
  // dispatch on.
  function classifyTopic(topic) {
    const parts = topic.split('/');
    if (parts.length < 4) return null;
    if (parts[0] !== 'aevus') return null;
    return {
      site: parts[1],
      asset: parts[2],
      class: parts[3],
      key: parts.slice(4).join('/') || null,
    };
  }

  // ── Connection management ───────────────────────────────────────────
  let client = null;

  function connect() {
    if (typeof mqtt === 'undefined') {
      console.error(
        '[Aevus MQTT] mqtt.js library not loaded. Include it before mqtt-client.js:'
        + '\n  <script src="https://unpkg.com/mqtt/dist/mqtt.min.js"></script>'
      );
      return;
    }

    if (config.transport === 'cloud') {
      connectCloud();
    } else {
      connectLocal();
    }
  }

  function connectLocal() {
    console.log(`[Aevus MQTT] Connecting (local): ${config.brokerUrl}`);
    client = mqtt.connect(config.brokerUrl, {
      clientId: config.clientId,
      reconnectPeriod: config.reconnectPeriod,
      keepalive: config.keepalive,
      clean: true,
    });
    wireClient();
  }

  function connectCloud() {
    // AWS IoT Core MQTT-over-WSS uses a SigV4-signed URL. The page's
    // cognito-iot-init.js script presigns it and writes it onto
    // window.AEVUS_IOT_SIGNED_URL (and window.AEVUS_MQTT_CONFIG.brokerUrl).
    // We always pull the LIVE value here, not the cached `config` copy,
    // because the signed URL is only present after the async Cognito
    // credentials fetch resolves.
    const liveCfg = window.AEVUS_MQTT_CONFIG || {};
    const brokerUrl = window.AEVUS_IOT_SIGNED_URL || liveCfg.brokerUrl || config.brokerUrl;
    if (!brokerUrl || !brokerUrl.startsWith('wss://')) {
      console.error('[Aevus MQTT] Cloud transport requested but no signed wss:// URL found. Got:', brokerUrl);
      return;
    }
    console.log('[Aevus MQTT] Connecting (cloud):', brokerUrl.slice(0, 80) + '...');
    client = mqtt.connect(brokerUrl, {
      clientId: config.clientId,
      reconnectPeriod: config.reconnectPeriod,
      keepalive: config.keepalive,
      clean: true,
      protocolVersion: 5,
    });
    wireClient();
  }

  function wireClient() {
    client.on('connect', () => {
      console.log('[Aevus MQTT] Connected, subscribing to', `aevus/${config.siteId}/#`);
      client.subscribe(`aevus/${config.siteId}/#`, { qos: 1 }, (err, granted) => {
        if (err) {
          console.error('[Aevus MQTT] Subscribe failed:', err);
        } else {
          console.log('[Aevus MQTT] Subscribed:', granted);
        }
      });
      fire('connected');
    });

    client.on('reconnect', () => {
      console.log('[Aevus MQTT] Reconnecting...');
    });

    client.on('close', () => {
      console.log('[Aevus MQTT] Connection closed');
      fire('disconnected');
    });

    client.on('error', (err) => {
      console.warn('[Aevus MQTT] Error:', err.message || err);
    });

    client.on('message', (topic, payload) => {
      const parsed = classifyTopic(topic);
      if (!parsed) return;

      let envelope;
      try {
        envelope = JSON.parse(payload.toString('utf-8'));
      } catch (e) {
        console.warn('[Aevus MQTT] Bad JSON on', topic, e);
        return;
      }

      // Stamp the classification onto the envelope for handler convenience.
      envelope._topic = topic;
      envelope._topicParts = parsed;

      fire('raw', envelope);

      // Pi publishes singular topic classes (alert/event/telemetry/state);
      // older docs/tests referenced plurals — accept both.
      switch (parsed.class) {
        case 'alert':
        case 'alerts':
          fire('alert', envelope);
          break;
        case 'rca':
          fire('rca', envelope);
          break;
        case 'state':
          fire('state', envelope);
          break;
        case 'event':
        case 'events':
          fire('event', envelope);
          break;
        case 'telemetry':
          fire('telemetry', envelope);
          break;
        default:
          // Unknown class — emit on raw only.
          break;
      }
    });
  }

  function disconnect() {
    if (client) {
      client.end(true);
      client = null;
    }
  }

  // ── Public API ──────────────────────────────────────────────────────
  window.AEVUS_MQTT = {
    on,
    connect,
    disconnect,
    get connected() {
      return !!client && client.connected;
    },
    get config() {
      return { ...config };
    },
    // Exposed for unit-testing the classifier in isolation.
    _classifyTopic: classifyTopic,
  };

  // ── Auto-connect on DOM ready unless the page disables it ──────────
  // For cloud transport, wait for cognito-iot-init.js to presign the
  // wss URL and fire `aevus:mqtt-ready`. For local transport, connect
  // immediately on DOM-ready.
  function autoConnect() {
    if (config.transport === 'cloud') {
      // If the signed URL is already on the config (cognito init beat us
      // to it), connect now; otherwise wait for the ready event.
      if (window.AEVUS_IOT_SIGNED_URL || config.brokerUrl?.startsWith('wss://')) {
        connect();
      } else {
        console.log('[Aevus MQTT] Waiting for aevus:mqtt-ready (Cognito presign)...');
        window.addEventListener('aevus:mqtt-ready', function () {
          connect();
        }, { once: true });
      }
    } else {
      connect();
    }
  }

  if (window.AEVUS_MQTT_AUTO_CONNECT !== false) {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', autoConnect);
    } else {
      autoConnect();
    }
  }
})();

/**
 * Aevus Dashboard — Cognito + AWS IoT Core MQTT-over-WSS bootstrap.
 *
 * Runs BEFORE mqtt-client.js. Fetches anonymous temporary AWS credentials
 * from a Cognito Identity Pool (unauth role), SigV4-presigns a wss:// URL
 * for the AWS IoT Core data endpoint, writes it into
 * window.AEVUS_MQTT_CONFIG.brokerUrl, then dispatches a custom event
 * `aevus:mqtt-ready` that mqtt-client.js listens for (or just call
 * window.AEVUS_MQTT.connect() yourself).
 *
 * Hard requirements (page must load these first):
 *   <script src="https://sdk.amazonaws.com/js/aws-sdk-2.1503.0.min.js"></script>
 *   window.AEVUS_MQTT_CONFIG = {
 *     transport: 'cloud',
 *     awsRegion: 'us-east-1',
 *     awsIotEndpoint: 'a23tc2oxyb9d91-ats.iot.us-east-1.amazonaws.com',
 *     identityPoolId: 'us-east-1:05934a30-b27c-4261-96db-e85ea7483ac2',
 *     siteId: 'needville',
 *     clientId: 'aevus-dashboard-' + Math.random().toString(16).slice(2, 8),
 *   };
 *
 * Refreshes credentials every 50 min (Cognito anon TTL = 1 hour).
 * On expiry, re-presigns the URL and reconnects mqtt-client.
 *
 * Safe to call repeatedly — bootstrap is idempotent.
 */
(function () {
  'use strict';

  const cfg = window.AEVUS_MQTT_CONFIG;
  if (!cfg || cfg.transport !== 'cloud') {
    return;  // local transport — nothing to do
  }
  if (typeof AWS === 'undefined') {
    console.error('[Aevus Cognito] aws-sdk not loaded — include aws-sdk-2.x before this script.');
    return;
  }
  if (!cfg.identityPoolId || !cfg.awsIotEndpoint || !cfg.awsRegion) {
    console.error('[Aevus Cognito] Missing identityPoolId / awsIotEndpoint / awsRegion in AEVUS_MQTT_CONFIG.');
    return;
  }

  AWS.config.region = cfg.awsRegion;
  AWS.config.credentials = new AWS.CognitoIdentityCredentials({
    IdentityPoolId: cfg.identityPoolId,
  });

  // SigV4 presign — see AWS docs "Connecting devices to AWS IoT using MQTT over WSS"
  function presignIotWssUrl(creds) {
    const region = cfg.awsRegion;
    const endpoint = cfg.awsIotEndpoint;
    const time = new Date();
    const dateStamp = time.toISOString().slice(0, 10).replace(/-/g, '');
    const amzdate = time.toISOString().replace(/[:-]|\.\d{3}/g, '');
    const service = 'iotdevicegateway';
    const algorithm = 'AWS4-HMAC-SHA256';
    const method = 'GET';
    const canonicalUri = '/mqtt';
    const credentialScope = `${dateStamp}/${region}/${service}/aws4_request`;
    const canonicalQs =
      'X-Amz-Algorithm=' + algorithm +
      '&X-Amz-Credential=' + encodeURIComponent(creds.accessKeyId + '/' + credentialScope) +
      '&X-Amz-Date=' + amzdate +
      '&X-Amz-SignedHeaders=host';
    const canonicalHeaders = 'host:' + endpoint + '\n';
    const payloadHash = AWS.util.crypto.sha256('', 'hex');
    const canonicalRequest =
      method + '\n' + canonicalUri + '\n' + canonicalQs + '\n' +
      canonicalHeaders + '\n' + 'host' + '\n' + payloadHash;
    const stringToSign =
      algorithm + '\n' + amzdate + '\n' + credentialScope + '\n' +
      AWS.util.crypto.sha256(canonicalRequest, 'hex');
    // Derive signing key
    const kDate = AWS.util.crypto.hmac('AWS4' + creds.secretAccessKey, dateStamp, 'buffer');
    const kRegion = AWS.util.crypto.hmac(kDate, region, 'buffer');
    const kService = AWS.util.crypto.hmac(kRegion, service, 'buffer');
    const kSigning = AWS.util.crypto.hmac(kService, 'aws4_request', 'buffer');
    const signature = AWS.util.crypto.hmac(kSigning, stringToSign, 'hex');
    let url =
      'wss://' + endpoint + canonicalUri + '?' + canonicalQs + '&X-Amz-Signature=' + signature;
    if (creds.sessionToken) {
      url += '&X-Amz-Security-Token=' + encodeURIComponent(creds.sessionToken);
    }
    return url;
  }

  function bootstrap() {
    AWS.config.credentials.get(function (err) {
      if (err) {
        console.error('[Aevus Cognito] Identity Pool fetch failed:', err);
        return;
      }
      const c = AWS.config.credentials;
      const signedUrl = presignIotWssUrl({
        accessKeyId: c.accessKeyId,
        secretAccessKey: c.secretAccessKey,
        sessionToken: c.sessionToken,
      });
      cfg.brokerUrl = signedUrl;
      window.AEVUS_IOT_SIGNED_URL = signedUrl;
      console.log('[Aevus Cognito] Identity ready, IoT WSS URL presigned. Identity:', c.identityId);
      // Fire ready event — mqtt-client.js listens for this and owns
      // the actual connect() call. Do NOT call connect() here too;
      // duplicate connects with the same clientId cause AWS IoT Core
      // to boot whichever session connected first, producing a
      // reconnect storm visible as Connection closed → Reconnecting
      // loops in the console.
      window.dispatchEvent(new CustomEvent('aevus:mqtt-ready', { detail: { brokerUrl: signedUrl } }));
    });
  }

  // Refresh every 50 minutes — anon Cognito creds last 1 hour.
  bootstrap();
  setInterval(function () {
    AWS.config.credentials.refresh(function (err) {
      if (err) {
        console.warn('[Aevus Cognito] Refresh failed:', err);
        return;
      }
      bootstrap();
    });
  }, 50 * 60 * 1000);
})();

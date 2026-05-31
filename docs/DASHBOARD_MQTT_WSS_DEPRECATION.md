# Dashboard MQTT-over-WSS Transport — Rip (Task #156)

**Status:** Not in production. No tracked code to remove. Decision: **rip**
the idea, document for the record, don't revive.

## Background (Task #65)

Task #65 was marked completed with the note *"Dashboard MQTT-over-WSS
cloud transport wired (not deployed)."* The intent was to let the browser
subscribe directly to `aevus/+/+/alerts/critical` (and other topics) on
AWS IoT Core via:

- A Cognito Identity Pool (Task #34) issuing unauth IAM creds to the browser
- The browser using those creds to SigV4-sign a `wss://` connection to
  IoT Core's MQTT broker
- Paho-MQTT-JS or aws-iot-device-sdk-js handling the protocol

## Reality check

A search of tracked dashboard files on 2026-05-30 shows:
- Zero `paho`, `aws-iot`, `mqtt-wss` references in `dashboard/api-client.js`
- One `wss://` in `dashboard/topology.html:901` — but that's a plain
  WebSocket back to the FastAPI service, not IoT Core
- No Cognito Identity Pool SigV4 signing code in any tracked .js
- No `aws-iot-device-sdk-js` import or bundle

The wiring described in #65 either never landed on main, was reverted at
some point, or only ever existed as a design doc.

## Why rip instead of revive

The dashboard already gets real-time updates via the path that won
operationally:

| Path | Status | Used by |
|---|---|---|
| Pi → MQTT → IoT Core → DynamoDB latest-state → EC2 read overlay → dashboard polls REST | **LIVE** (Task #148, PR #59) | All pages |
| Pi → MQTT → IoT Core → WSS → browser subscribe | (this doc, ripped) | Nobody |

The DynamoDB-overlay path is operationally simpler:
- No browser-side AWS SDK or Cognito wiring
- No SigV4 every-message overhead
- One auth model (the existing `aevus_session` cookie / X-API-Key) instead
  of two (cookie for REST + Cognito for WSS)
- Server-side filtering / aggregation already in `/api/v1/assets` overlay

The freshness penalty of REST-polling vs MQTT-subscribe at our cadence is
~5–10s. For an operator dashboard on a single-Pi lab, that's fine. If
fleet scales and freshness becomes critical, the path forward is
server-pushed WebSocket from the FastAPI service (already partially built —
see `src/api/ws.py`), not browser-direct IoT Core.

## When to reconsider

Trip-wires that would justify reopening:
1. Operator complaint that 5–10s freshness on critical alarms is too slow
2. Fleet > 5 sites where the DynamoDB overlay starts costing real money
   on read units
3. A page that needs sub-second updates (real-time RF spectrum view)

Until then: dashboard uses REST + the existing FastAPI WebSocket
(`/api/v1/ws`). IoT Core stays a server-side concern.

## What to do with Cognito Identity Pool (Task #34)

The Cognito Identity Pool TF is in `infra/terraform/` somewhere — it was
provisioned for this transport. It now serves no purpose. Mark for cleanup
in Task #157 (the broader IaC capture / cleanup sweep).

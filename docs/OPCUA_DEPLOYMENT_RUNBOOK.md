# OPC UA Ingestion — Deployment & Cybersecurity Runbook v1

**Status:** Code complete on `feat/opcua-client-collector`; **NOT deployed** anywhere.
`OPCUA_ENABLED=false` by default. This runbook is the safe path to enable it.
**Owner:** Woody · **Created:** 2026-06-10

---

## 0. Golden rules (read before anything)

1. **Read-only. IL-9000 applies.** The OPC UA client has no write path, by design.
   Never add one.
2. **Edge-side only.** The OPC UA client runs on the **Pi / edge collector** on the OT
   LAN — **never on EC2**. AWS must not route to OT. (Same rule as Modbus: on EC2 the
   collector stays disabled.)
3. **Flag default OFF.** `OPCUA_ENABLED=false`. Enable only via a controlled sequence
   (§6), never as a blind push-to-main.
4. **`Security=None` is for public simulation servers ONLY.** Any real server uses
   `Basic256Sha256 + SignAndEncrypt` with a client certificate.
5. **Trade-secret boundary unchanged.** Only normalized vitals + coarse status leave
   the server. Raw tags stay server-side; no pearl_score internals exposed.

## 1. Where it runs — architecture

```
Customer / lab OT enclave                          Aevus
┌─────────────────────────────┐        ┌──────────────────────────────┐
│  SCADA host (OPC UA server)  │        │  Pi / edge collector         │
│  Ignition / KEPServer / ...  │◀──TLS──│  OPCUAClientCollector (RO)   │
│  opc.tcp://...:4840          │ Sign&  │  OPCUA_ENABLED=1             │
└─────────────────────────────┘ Encrypt└──────────────┬───────────────┘
        (OT VLAN, firewalled)                          │ normalized vitals only
                                                       ▼
                                              EC2 API / dashboard (cloud)
```

- The **OPC UA client lives on the Pi**, inside (or DMZ-adjacent to) the OT network.
- **EC2 never connects to a customer OPC UA server.** It only receives already-normalized
  data through the existing edge→cloud path.
- On EC2, `OPCUA_ENABLED` stays **false** permanently (it cannot reach OT and must not try).

## 2. Pre-deploy checklist

- [ ] PR reviewed and merged to `main` (code only; flag still false).
- [ ] Target = the **Pi/edge** host, not EC2.
- [ ] Customer/lab OPC UA endpoint reachable from the Pi **only** (firewall verified).
- [ ] Tag-map YAML authored for the site (browse the server to get real NodeIds).
- [ ] Client certificate provisioned and **trusted by the server** (§3).
- [ ] Network segmentation in place (§4).
- [ ] Enablement will follow §6 (control box first), never a direct prod flip.

## 3. Certificate provisioning (cybersecurity-critical)

The client authenticates with an X.509 certificate. On first use the code can
auto-generate a compliant self-signed cert (`auto_generate: true`), but for a real site:

1. **Generate / install the client cert + key** on the Pi:
   - Default paths: `certs/aevus_opcua_client_cert.der`, `certs/aevus_opcua_client_key.pem`
     (relative to the service working dir). Override in the tag-map `security:` block.
   - The cert SubjectAltName carries the **ApplicationUri** (required by OPC UA) plus DNS
     hostnames. Generated automatically by `ensure_client_cert`.
2. **Protect the private key.** It is a secret:
   - File mode `0600`, owned by the service user. **Never commit it** (`certs/` is
     gitignored). Prefer AWS Secrets Manager / SSM Parameter Store (SecureString) +
     deploy-time fetch over a key sitting on disk long-term.
3. **Server-side trust (the step people forget).** The OPC UA **server must trust our
   client cert** — push `aevus_opcua_client_cert.der` into the server's *trusted client
   certificates* directory (Ignition/KEPServer/etc. each have a trust UI). Until that
   happens the server rejects the session.
4. **(Recommended) Pin the server cert.** Set `security.server_cert` to the server's
   public cert so the client validates the server end too (mutual trust, not just
   encryption).
5. **Rotation.** Treat the client cert like any credential — track expiry (10y default,
   but rotate on policy), re-trust on the server when rotated.

## 4. Network & segmentation

- Put the OPC UA client on a **segmented OT/DMZ VLAN** (cf. the VLAN-20 OT plan).
- **Firewall:** allow only Pi → SCADA host on the OPC UA port (`:4840` typical). No
  inbound to the Pi from OT. No path from EC2 to the OPC UA server.
- Prefer **outbound-only** from the Pi where the topology allows.
- Confirm the SCADA server is **not** itself internet-exposed (it never should be — cf.
  the 14k misconfigured OPC UA servers on Shodan). We connect from inside, not over the
  internet.

## 5. Configuration

Environment (on the Pi service, e.g. `.env` / systemd `Environment=`):

```
OPCUA_ENABLED=1
OPCUA_CONFIG_PATH=/opt/aevus/config/opcua/<site>.yaml
```

Tag-map (`<site>.yaml`) — see `config/opcua/example_secure.yaml`. Key points:
- `security:` block with `policy: Basic256Sha256`, `mode: SignAndEncrypt`, cert/key paths.
- `security: null` is **forbidden** for a real site (sim-only).
- Map each NodeId to an Aevus metric key the normalizer knows (suction_pressure,
  discharge_pressure, vibration, motor_current, interstage_temp, oil_pressure, ...) so
  good/warn/bad status tagging is automatic.

## 6. Controlled enablement sequence (never flip prod blindly)

1. **Control box / laptop** — point the tag-map at a sim (Prosys) or a self-hosted
   `mcr.microsoft.com/iotedge/opc-plc` container. Verify polling + vitals + status.
2. **Staging / a non-prod Pi** — connect to the real server with full security; confirm
   the server trusts the client cert and data flows read-only.
3. **Prod edge (Pi)** — enable the flag on the Pi only, with certs provisioned and
   network locked down. **Never set `OPCUA_ENABLED=1` on EC2.**

## 7. Verification / smoke test (after enabling on the Pi)

```bash
# the overlay asset appears, read-only, protocol=opcua
curl -s <pi-or-api>/api/v1/assets | jq '.[] | select(.protocol=="opcua") | {id,status,health}'
# its vitals carry status tags
curl -s <pi-or-api>/api/v1/assets/<ASSET_ID> | jq '.vitals[] | {label,value,status}'
# the seed/fleet is intact (no asset count regression)
curl -s <pi-or-api>/api/v1/assets | jq 'length'
```

Expected: exactly one new `opcua` asset; existing assets unchanged; no errors in logs
(`opcua_connected`, `poll_success`).

## 8. Rollback (instant)

- Set `OPCUA_ENABLED=0` (or unset) and restart the service. The overlay returns `[]`
  immediately; the background poller does not start. `/assets` reverts to prior state.
- No data migration, no seed change — the overlay is in-memory only, so rollback is
  a flag flip. (This is the same proven pattern as reference/process assets.)

## 9. Monitoring & ops

- Watch logs for `opcua_connected`, `poll_success`, `poll_failed`, `opcua_config_load_failed`.
- A dropped server is handled automatically (reconnect with exponential backoff); the
  overlay reads `bad` while unreachable, so a stale link is visible, not silent.
- Alert if the opcua asset goes `bad`/missing for > N minutes (link/cert/server issue).

## 10. What is explicitly OUT of scope

- **No OPC UA writes** — ever (IL-9000). This is a read-only sidecar.
- **No EC2-side OPC UA** — the client is edge-only.
- **No `Security=None` against real servers.**
- **No public-internet OPC UA scraping** — only the customer's own server, from inside.

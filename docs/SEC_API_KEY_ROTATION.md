# SEC — API key rotation required (2026-07-22)

**Status: CLIENT FIXED · SERVER ROTATION PENDING — treat the old key as compromised.**

## What happened
CI gitleaks on PR 150 flagged a 43-char `X-API-Key` value hardcoded in
`dashboard/api-client.js` (and `award-client.js`) line 1. The key predates the
restyle work. Because those bundles are served to every browser that loads the
dashboard, the key has been publicly retrievable by anyone who viewed source —
and per `src/api/auth.py` it grants **full authenticated API access** (the same
`settings.api_key` check programmatic clients use), not the read-only demo gate.

## What was done (client side, PR 150)
- Key literal removed from both bundles. The header object degrades to `{}`;
  auth now flows through the existing paths only:
  1. session cookie (`aevus_session`) for logged-in users
  2. Cognito Bearer token
  3. demo gate (Referer `demo=true`, GET + `/ai/` only)
  `window.AEVUS_API_KEY` remains as an optional server-injected value for
  authenticated kiosk/WS deployments; it defaults to empty and nothing bakes it.
- `.gitleaksignore` added for the historical fingerprints (the value is public
  history regardless; rotation is what kills it). New secrets still fail CI.

## What the backend lane must do (cannot be done from the dashboard session)
1. **Generate a new API key** and update wherever `API_KEY` is provisioned for
   the deployment (AWS Secrets Manager per `src/secrets_loader.py`, plus any
   local `.env` on the box / edge collector).
2. **Restart the service** so the middleware picks up the new value.
3. **Verify the old key 401s**: `curl -H "X-API-Key: <old>" https://aevus.intrepidlogic.io/api/v1/assets` → 401.
4. **Audit consumers**: anything that legitimately used the old key
   (edge collector? scripts? Wall displays?) needs the new key via env/secret —
   never a client bundle.
5. Optional hardening follow-ups: rate-limit the demo `/ai/` POSTs
   (ARCHITECTURE_REVIEW H3), and consider per-client scoped keys if
   programmatic consumers grow.

## Explicitly not done
- No git-history rewrite: the value is already public via the served bundle,
  so rotation — not history surgery — is the effective remediation. A rewrite
  would disrupt both active lanes for no security gain.

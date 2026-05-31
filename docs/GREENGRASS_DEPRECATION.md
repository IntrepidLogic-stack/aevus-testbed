# Greengrass — Deprecated, Not Used (Task #155)

**Status:** The Aevus edge runs as a plain systemd unit (`aevus.service`),
NOT as AWS IoT Greengrass v2 components. Any references to Greengrass in
docs or task history are historical artifacts.

## What was built (#16–#19, #25, #39)

Six tasks in 2026 scaffolded Greengrass v2:
- Nucleus install for the Pi
- Component recipes for trap-receiver / icmp-probe / dnp3-receiver
- Artifact packaging script
- SIGTERM handling + README
- L4E bootstrap scripts (which would have run as components)

The build artifacts still live under `deploy/greengrass/artifacts/`
(gitignored — they're local-build only). No recipes, no nucleus
install scripts, and no component code are tracked in git.

## Why we shipped systemd instead

When it came time to actually deploy in 2026-05, the trade-offs played
out like this:

| Concern | Greengrass | systemd |
|---|---|---|
| Operational complexity | High (nucleus + component lifecycle + deployment groups) | Low (one .service file) |
| Update path | AWS-managed deployments | `git pull && systemctl restart aevus` |
| Logging | CloudWatch via Greengrass logger | `journalctl -u aevus` |
| Failure isolation | Per-component restart | Whole-process restart (acceptable for a single-Pi edge) |
| Cost at lab scale | Free tier covers 50 components | $0 |
| Skill required to debug | AWS IoT-specific | Universal Linux |

The lab fleet today is **one Pi**. Greengrass's per-component isolation
buys nothing at fleet size 1. systemd is more debuggable for the same
reason Linux sysadmins already know it. When the fleet exceeds ~5 edges
or the components diverge in update cadence, revisit.

## Current path (production)

- **Service:** `/etc/systemd/system/aevus.service` (in `deploy/aevus.service`)
- **Process:** `uvicorn src.main:app --host 0.0.0.0 --port 8000`
- **Updates:** `cd ~/aevus-testbed && sudo -u admin git pull origin main && sudo systemctl restart aevus`
- **Logs:** `journalctl -u aevus`
- **MQTT cert:** Standard X.509 in `/etc/aevus/certs/`, no Greengrass cert flow

## What this means for new contributors

If you see Greengrass-shaped scaffolding in:
- `deploy/greengrass/artifacts/` — it's local build output, ignore
- Old task history (#16–#19, #25, #39) — historical record only
- Code comments mentioning "Greengrass component" — stale, please update

If you want the per-component isolation Greengrass offers, the path
forward is **not** to revive the old recipes — it's to evaluate against
the current MQTT + systemd architecture and pick the right tool then.

## When to revisit

Trip-wires that would justify reopening this decision:
1. Fleet size > 5 edges (per-edge deployment groups become useful)
2. A second component on the Pi needs an independent update cadence
   from the main `aevus.service`
3. AWS introduces a free-tier-friendly Greengrass managed deployment
   that doesn't require the full nucleus

Until one of those fires, the systemd path is canonical.

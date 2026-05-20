"""
MQTT topic generation for Aevus events.

Canonical topic hierarchy (defined in docs/AWS_LANDING_ZONE.md §4):

    aevus/{site_id}/{asset_id}/telemetry/{metric}    raw values (5s/30s cadence)
    aevus/{site_id}/{asset_id}/state/{key}           discrete state transitions
    aevus/{site_id}/{asset_id}/events/{class}        SNMP traps, DNP3 events, syslog
    aevus/{site_id}/{asset_id}/alerts/{severity}     alarm engine output
    aevus/{site_id}/{asset_id}/ops/heartbeat         collector liveness (1s)
    aevus/{site_id}/system/audit                     site-wide audit feed

Why a separate module: the topic hierarchy is part of our AWS-side
contract. IoT Core rules, SiteWise asset properties, and IAM policies
all key off these patterns. Centralizing the generation keeps the
publisher, the dashboard subscriber, and the Terraform rules in sync.

Topic-level IAM (production):
  Each Greengrass core only has IAM publish permission under its own
  {site_id}/ prefix. A misbehaving (or compromised) edge can't poison
  topics belonging to other sites. Enforced via the IoT Core policy
  in infra/terraform/aws-iot-core.tf.
"""

from __future__ import annotations

import re
from typing import Final


# MQTT topic levels must not contain '/', '+', or '#'. Asset IDs and
# metric names occasionally come from external sources (asset registry
# imports, vendor MIBs), so we sanitize defensively.
_INVALID_TOPIC_CHARS: Final[re.Pattern] = re.compile(r"[/+#\s]")
_ROOT_PREFIX: Final[str] = "aevus"


def _sanitize(segment: str) -> str:
    """Replace MQTT-reserved characters with underscores.

    MQTT v3.1.1 reserves `/`, `+`, `#` for topic structure / wildcards.
    Whitespace is allowed by the spec but breaks most operator tooling.
    """
    if not segment:
        return "_"
    return _INVALID_TOPIC_CHARS.sub("_", segment)


def telemetry(site_id: str, asset_id: str, metric: str) -> str:
    """Topic for a raw telemetry reading.

    Example: aevus/lab/RTU-01/telemetry/suction_pressure
    """
    return (
        f"{_ROOT_PREFIX}/{_sanitize(site_id)}/{_sanitize(asset_id)}"
        f"/telemetry/{_sanitize(metric)}"
    )


def state(site_id: str, asset_id: str, key: str) -> str:
    """Topic for a discrete state transition (reachability, oob, etc).

    Example: aevus/lab/RTU-01/state/reachability
    """
    return (
        f"{_ROOT_PREFIX}/{_sanitize(site_id)}/{_sanitize(asset_id)}"
        f"/state/{_sanitize(key)}"
    )


def event(site_id: str, asset_id: str, event_class: str) -> str:
    """Topic for an event-class signal (snmp-trap, dnp3, syslog, drift).

    Example: aevus/lab/RTU-01/events/dnp3
             aevus/lab/SW-01/events/snmp-trap
    """
    return (
        f"{_ROOT_PREFIX}/{_sanitize(site_id)}/{_sanitize(asset_id)}"
        f"/events/{_sanitize(event_class)}"
    )


def alert(site_id: str, asset_id: str, severity: str) -> str:
    """Topic for an alarm engine emission.

    Example: aevus/lab/RTU-01/alerts/critical
             aevus/lab/RTU-01/alerts/warning
    """
    return (
        f"{_ROOT_PREFIX}/{_sanitize(site_id)}/{_sanitize(asset_id)}"
        f"/alerts/{_sanitize(severity)}"
    )


def heartbeat(site_id: str, asset_id: str) -> str:
    """Topic for collector liveness pings (1s cadence).

    Example: aevus/lab/RTU-01/ops/heartbeat
    """
    return (
        f"{_ROOT_PREFIX}/{_sanitize(site_id)}/{_sanitize(asset_id)}"
        f"/ops/heartbeat"
    )


def audit(site_id: str) -> str:
    """Topic for site-wide audit events (delivered to S3 Object Lock).

    Example: aevus/lab/system/audit
    """
    return f"{_ROOT_PREFIX}/{_sanitize(site_id)}/system/audit"


# ──────────────────────────────────────────────────────────────────────────
# Subscription patterns (for the dashboard / cloud consumers)
# ──────────────────────────────────────────────────────────────────────────
def subscription_all_for_site(site_id: str) -> str:
    """MQTT wildcard subscription: everything for one site.

    Example: aevus/lab/#
    """
    return f"{_ROOT_PREFIX}/{_sanitize(site_id)}/#"


def subscription_alerts_for_site(site_id: str) -> str:
    """MQTT wildcard subscription: all alerts for one site.

    Example: aevus/lab/+/alerts/+
    """
    return f"{_ROOT_PREFIX}/{_sanitize(site_id)}/+/alerts/+"


def subscription_all_critical_alerts() -> str:
    """Fleet-wide critical alarms subscription.

    Example: aevus/+/+/alerts/critical
    """
    return f"{_ROOT_PREFIX}/+/+/alerts/critical"

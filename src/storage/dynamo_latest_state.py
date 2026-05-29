"""
Aevus — DynamoDB latest-state reader (Phase 2 of edge→cloud convergence).

Reads the per-asset/metric latest values that the IoT rules
(aevus_latest_state_to_ddb + aevus_state_to_ddb) write into the
aevus-latest-state table, and reconstructs them into what the read-API needs:

  - telemetry items (metric = "rssi", "voltage", ...) →
        RawTelemetry → normalize_batch → list[VitalSign]
  - state items     (metric = "state:<key>")          →
        dict overlay: firmware / health / status / last_seen / uptime_24h

Design: docs/PHASE2_read_api_convergence_design.md. Registry (SQLite) stays the
source of asset METADATA; DynamoDB is the source of current VALUES/STATE.

Safety:
  - boto3 is lazy-imported, so environments without it / without AWS creds are
    unaffected unless read_source actually selects Dynamo.
  - Every failure degrades to empty results + a logged warning — never a 500
    and never blanks an asset's registry data (enrich is overlay-only).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

import structlog

from src.engine.normalizer import normalize_batch
from src.models.telemetry import RawTelemetry, VitalSign

logger = structlog.get_logger()


@dataclass
class AssetLatest:
    """Current values for one asset, split by kind."""

    vitals: list[VitalSign] = field(default_factory=list)
    state: dict[str, str] = field(default_factory=dict)  # firmware/health/status/last_seen/uptime_24h


class DynamoLatestStateReader:
    """Reads aevus-latest-state and reconstructs vitals + state per asset."""

    def __init__(self, table_name: str, region: str) -> None:
        self.table_name = table_name
        self.region = region
        self._table = None  # lazy boto3 resource
        self.log = logger.bind(component="dynamo_latest_state")

    def _tbl(self):
        if self._table is None:
            import boto3

            self._table = boto3.resource("dynamodb", region_name=self.region).Table(
                self.table_name
            )
        return self._table

    def fetch(self, asset_id: str) -> AssetLatest:
        """Query every item for one asset; split into normalized vitals + state."""
        try:
            from boto3.dynamodb.conditions import Key

            resp = self._tbl().query(KeyConditionExpression=Key("asset_id").eq(asset_id))
            items = resp.get("Items", [])
        except Exception as e:  # noqa: BLE001 — never raise into the request path
            self.log.warning("dynamo_query_failed", asset_id=asset_id, error=str(e))
            return AssetLatest()

        return self._items_to_latest(asset_id, items)

    def _items_to_latest(self, asset_id: str, items: list[dict]) -> AssetLatest:
        """Pure transform — separated so tests can exercise it without boto3."""
        readings: list[RawTelemetry] = []
        state: dict[str, str] = {}
        now = datetime.now(UTC)

        for it in items:
            metric = str(it.get("metric", ""))
            if not metric:
                continue
            if metric.startswith("state:"):
                state[metric[len("state:") :]] = str(it.get("value", ""))
                continue
            # Telemetry: DynamoDB stores numbers as Decimal → float for the model.
            try:
                value = float(it.get("value"))
            except (TypeError, ValueError):
                continue
            readings.append(
                RawTelemetry(
                    asset_id=asset_id,
                    metric=metric,
                    value=value,
                    unit=str(it.get("unit", "")),
                    timestamp=now,
                    source=str(it.get("source", "")),
                )
            )

        vitals = normalize_batch(readings) if readings else []
        return AssetLatest(vitals=vitals, state=state)

    def enrich(self, asset) -> None:
        """Overlay an Asset (from the registry) with live vitals + state from
        DynamoDB, IN PLACE. Overlay-only: if Dynamo has nothing for the asset,
        the registry asset is left untouched (so a Dynamo gap never blanks it)."""
        latest = self.fetch(asset.id)
        if latest.vitals:
            asset.vitals = latest.vitals
        st = latest.state
        if st.get("firmware"):
            asset.firmware = st["firmware"]
        if st.get("status"):
            asset.status = st["status"]
        if st.get("health") not in (None, ""):
            try:
                asset.health = int(float(st["health"]))
            except (TypeError, ValueError):
                pass


# Lazy module-level singleton so the API doesn't rebuild the boto3 client each call.
_reader: DynamoLatestStateReader | None = None


def get_reader() -> DynamoLatestStateReader:
    global _reader
    if _reader is None:
        from src.config import settings

        _reader = DynamoLatestStateReader(
            table_name=settings.dynamo_latest_state_table,
            region=settings.aws_region,
        )
    return _reader

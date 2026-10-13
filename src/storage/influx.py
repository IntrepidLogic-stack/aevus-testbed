"""
Aevus Testbed --- InfluxDB Storage Layer
Writes raw telemetry to InfluxDB 2.x and queries time-series data.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS

from src.config import settings

if TYPE_CHECKING:
    from src.models.telemetry import RawTelemetry

logger = structlog.get_logger()

# Identifier alphabet permitted inside Flux string literals (M5 injection guard):
# letters, digits, underscore, dot, colon, hyphen — covers every real asset_id
# ("RAD-01", "CMP-KILLDEER") and metric ("battery_voltage", "cpu_load_1min")
# while making quote/backslash/newline injection impossible.
_FLUX_IDENT_RE = re.compile(r"[A-Za-z0-9_.:\-]{1,128}")

_UTC = UTC


def _parse_iso_dt(s):
    """Parse an ISO-8601 string to an aware UTC datetime, or None."""
    try:
        z = str(s).strip()
        if z.endswith("Z"):
            z = z[:-1] + "+00:00"
        d = datetime.fromisoformat(z)
        return d if d.tzinfo else d.replace(tzinfo=_UTC)
    except Exception:
        return None


def _epoch_s(s):
    """ISO-8601 -> integer Unix seconds (Flux range accepts int seconds), or None."""
    d = _parse_iso_dt(s)
    return int(d.timestamp()) if d is not None else None


class InfluxStorage:
    """InfluxDB 2.x client for telemetry read/write."""

    def __init__(self) -> None:
        self._client = InfluxDBClient(
            url=settings.influx_url,
            token=settings.influx_token,
            org=settings.influx_org,
        )
        self._write_api = self._client.write_api(write_options=SYNCHRONOUS)
        self._query_api = self._client.query_api()
        self._bucket = settings.influx_bucket
        self._org = settings.influx_org
        self.log = logger.bind(component="influx")

    def write_readings(self, readings: list[RawTelemetry]) -> int:
        """Write a batch of raw telemetry readings to InfluxDB.

        Returns the number of points written.
        """
        if not readings:
            return 0

        points = []
        for r in readings:
            p = (
                Point("telemetry")
                .tag("asset_id", r.asset_id)
                .tag("metric", r.metric)
                .tag("source", r.source)
                .tag("unit", r.unit)
                .field("value", r.value)
                .time(r.timestamp, WritePrecision.S)
            )
            if r.oid:
                p = p.tag("oid", r.oid)
            if r.modbus_register:
                p = p.tag("modbus_register", str(r.modbus_register))
            points.append(p)

        try:
            self._write_api.write(bucket=self._bucket, org=self._org, record=points)
            self.log.debug("influx_write", count=len(points))
            return len(points)
        except Exception as e:
            self.log.error("influx_write_failed", error=str(e))
            return 0

    @staticmethod
    def _safe_ident(value: str, what: str) -> str | None:
        """Validate an identifier before it is interpolated into a Flux query.

        asset_id / metric values are plain identifiers ("RAD-01", "rssi",
        "battery_voltage"), but query inputs can originate from API parameters —
        unvalidated f-string interpolation was a Flux-injection vector
        (ARCHITECTURE_REVIEW M5). Anything outside the strict identifier alphabet
        (no quotes, backslashes, or newlines possible) is rejected; the caller
        returns [] exactly as it does for any other query failure.
        """
        if isinstance(value, str) and _FLUX_IDENT_RE.fullmatch(value):
            return value
        logger.warning("influx_ident_rejected", field=what, value=repr(value)[:80])
        return None

    def query_latest(self, asset_id: str) -> list[dict]:
        """Get the latest reading for each metric of an asset."""
        if self._safe_ident(asset_id, "asset_id") is None:
            return []
        query = f'''
        from(bucket: "{self._bucket}")
          |> range(start: -1h)
          |> filter(fn: (r) => r["asset_id"] == "{asset_id}")
          |> last()
        '''
        try:
            tables = self._query_api.query(query, org=self._org)
            results = []
            for table in tables:
                for record in table.records:
                    results.append(
                        {
                            "metric": record.values.get("metric", ""),
                            "value": record.get_value(),
                            "unit": record.values.get("unit", ""),
                            "time": record.get_time().isoformat(),
                        }
                    )
            return results
        except Exception as e:
            self.log.error("influx_query_failed", error=str(e))
            return []

    def query_trend(self, asset_id: str, metric: str, hours: int = 24) -> list[dict]:
        """Get time-series trend for a specific metric."""
        if self._safe_ident(asset_id, "asset_id") is None or self._safe_ident(metric, "metric") is None:
            return []
        try:
            hours = max(1, min(int(hours), 8760))  # clamp to 1h..1y; rejects non-numeric
        except (TypeError, ValueError):
            return []
        query = f'''
        from(bucket: "{self._bucket}")
          |> range(start: -{hours}h)
          |> filter(fn: (r) => r["asset_id"] == "{asset_id}")
          |> filter(fn: (r) => r["metric"] == "{metric}")
          |> aggregateWindow(every: 5m, fn: mean, createEmpty: false)
        '''
        try:
            tables = self._query_api.query(query, org=self._org)
            results = []
            for table in tables:
                for record in table.records:
                    results.append(
                        {
                            "time": record.get_time().isoformat(),
                            "value": record.get_value(),
                        }
                    )
            return results
        except Exception as e:
            self.log.error("influx_trend_query_failed", error=str(e))
            return []

    # ------------------------------------------------------------------ #
    # Phase 4 retained-history queries (Comms console Trends / rollup /   #
    # incidents / SLA). Read-only. OR-chained equality filters only — a   #
    # Flux contains() over asset_id times out on this bucket, so callers  #
    # pass explicit id/metric lists we expand into `r[x] == "a" or ...`.  #
    # Absolute window bounds are passed to range() as integer Unix        #
    # seconds (never interpolated strings) so there is no injection seam. #
    # ------------------------------------------------------------------ #

    @staticmethod
    def span_ms(from_iso: str, to_iso: str) -> int | None:
        """Span of [from, to] in milliseconds, or None if unparseable / non-positive."""
        a = _parse_iso_dt(from_iso)
        b = _parse_iso_dt(to_iso)
        if a is None or b is None:
            return None
        ms = int((b - a).total_seconds() * 1000)
        return ms if ms > 0 else None

    def retained_since(self) -> str | None:
        """Earliest retained telemetry date (YYYY-MM-DD), or None if the bucket is empty."""
        query = f'''
        from(bucket: "{self._bucket}")
          |> range(start: -90d)
          |> group()
          |> min(column: "_time")
          |> limit(n: 1)
        '''
        try:
            tables = self._query_api.query(query, org=self._org)
            for table in tables:
                for record in table.records:
                    t = record.get_time()
                    if t is not None:
                        return t.astimezone(_UTC).strftime("%Y-%m-%d")
            return None
        except Exception as e:
            self.log.error("influx_retained_since_failed", error=str(e))
            return None

    def _agg_every(self, step: int) -> int:
        try:
            return max(30, min(int(step), 86400))
        except (TypeError, ValueError):
            return 3600

    def query_rssi_matrix(self, from_iso: str, to_iso: str, step: int) -> list[dict]:
        """RSSI for every RF asset over [from,to], bucketed to `step` seconds.

        Returns a flat list [{"asset_id": str, "t": epoch_ms, "v": rssi_dbm}].
        No asset filter (every asset reporting RSSI is included), so no
        contains()/OR expansion is needed — just metric == "rssi".
        """
        start_s = _epoch_s(from_iso)
        stop_s = _epoch_s(to_iso)
        if start_s is None or stop_s is None or stop_s <= start_s:
            return []
        every = self._agg_every(step)
        query = f'''
        from(bucket: "{self._bucket}")
          |> range(start: {start_s}, stop: {stop_s})
          |> filter(fn: (r) => r["metric"] == "rssi")
          |> aggregateWindow(every: {every}s, fn: mean, createEmpty: false)
        '''
        try:
            tables = self._query_api.query(query, org=self._org)
            out: list[dict] = []
            for table in tables:
                for record in table.records:
                    v = record.get_value()
                    aid = record.values.get("asset_id")
                    t = record.get_time()
                    if v is None or aid is None or t is None:
                        continue
                    out.append({"asset_id": aid, "t": int(t.timestamp() * 1000), "v": v})
            return out
        except Exception as e:
            self.log.error("influx_rssi_matrix_failed", error=str(e))
            return []

    def query_links(
        self,
        asset_ids: list[str],
        metrics: list[str],
        from_iso: str,
        to_iso: str,
        step: int,
    ) -> dict:
        """Per-link per-metric bucketed series for the named assets + metrics.

        Returns {asset_id: {metric: [{"t": epoch_ms, "v": num}]}}. asset_id and
        metric lists are expanded into OR-chained equality predicates (contains()
        times out on this bucket); every element is identifier-validated first.
        """
        start_s = _epoch_s(from_iso)
        stop_s = _epoch_s(to_iso)
        if start_s is None or stop_s is None or stop_s <= start_s:
            return {}
        safe_aids = [a for a in (asset_ids or []) if self._safe_ident(a, "asset_id")]
        safe_mets = [m for m in (metrics or []) if self._safe_ident(m, "metric")]
        if not safe_aids or not safe_mets:
            return {}
        every = self._agg_every(step)
        aid_pred = " or ".join(f'r["asset_id"] == "{a}"' for a in safe_aids)
        met_pred = " or ".join(f'r["metric"] == "{m}"' for m in safe_mets)
        query = f'''
        from(bucket: "{self._bucket}")
          |> range(start: {start_s}, stop: {stop_s})
          |> filter(fn: (r) => {aid_pred})
          |> filter(fn: (r) => {met_pred})
          |> aggregateWindow(every: {every}s, fn: mean, createEmpty: false)
        '''
        try:
            tables = self._query_api.query(query, org=self._org)
            out: dict = {}
            for table in tables:
                for record in table.records:
                    v = record.get_value()
                    aid = record.values.get("asset_id")
                    metric = record.values.get("metric")
                    t = record.get_time()
                    if v is None or aid is None or metric is None or t is None:
                        continue
                    out.setdefault(aid, {}).setdefault(metric, []).append({"t": int(t.timestamp() * 1000), "v": v})
            return out
        except Exception as e:
            self.log.error("influx_links_query_failed", error=str(e))
            return {}

    def close(self) -> None:
        """Close the InfluxDB client."""
        self._client.close()

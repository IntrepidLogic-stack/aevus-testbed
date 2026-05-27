"""
Aevus Testbed --- InfluxDB Storage Layer
Writes raw telemetry to InfluxDB 2.x and queries time-series data.
"""

from __future__ import annotations

import structlog
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS

from src.config import settings
from src.models.telemetry import RawTelemetry

logger = structlog.get_logger()


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

    def query_latest(self, asset_id: str) -> list[dict]:
        """Get the latest reading for each metric of an asset."""
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

    def close(self) -> None:
        """Close the InfluxDB client."""
        self._client.close()

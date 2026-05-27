#!/usr/bin/env python3
"""Export historical telemetry for AWS Lookout for Equipment (L4E) training.

L4E expects training data as one CSV per "component" (in our model, one
component per asset), with columns:
    Timestamp,<metric_1>,<metric_2>,...,<metric_N>

All timestamps in UTC, ISO-8601 format. Each component file must cover
the same time range; missing values are allowed but L4E warns about
gaps > 1% of the window.

Source of truth:
    • Production: InfluxDB bucket `aevus_telemetry`
    • Lab (no Influx yet): SQLite vitals_json from the assets table

Output:
    s3://<l4e-training-bucket>/datasets/<dataset-name>/<component>.csv

Bootstrap workflow (per docs/AWS_LANDING_ZONE.md §11 + L4E docs):
    1. terraform apply with var.l4e_enabled = true (creates the bucket).
    2. Wait ≥ 14 days of operational telemetry on the platform.
    3. Run this script to export the window to S3.
    4. Run bootstrap_l4e_model.py to create the dataset + model +
       inference scheduler.

Usage:
    python scripts/export_l4e_training_data.py \\
        --source influx \\
        --influx-url http://aevus-edge:8086 \\
        --influx-token "$INFLUX_TOKEN" \\
        --influx-org intrepid-logic \\
        --influx-bucket aevus_telemetry \\
        --bucket aevus-l4e-training-prod-XXX-us-east-2 \\
        --dataset-name aevus-lab-v1 \\
        --window-days 21 \\
        --components RTU-01,RAD-01,RAD-02 \\
        --dry-run

Components default to all assets with at least one analog metric in
the source. Use --components to restrict.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sqlite3
import sys
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

# Metrics worth training L4E on. Booleans + counters excluded — L4E
# anomaly detection is designed for continuous-process signals where
# a sub-anomaly drift is meaningful. Booleans should be modeled as
# events in the alert engine instead.
DEFAULT_METRICS = [
    # Radio (JR900)
    "rssi",
    "snr",
    "tx_power",
    "temperature",
    "voltage",
    # RTU (SCADAPack 470)
    "suction_pressure",
    "discharge_pressure",
    "flow_rate",
    "gas_temperature",
    "ambient_temperature",
    "battery_voltage",
    "solar_voltage",
    "vibration",
    # Network
    "cpu_load",
    "memory_usage",
]


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--source",
        choices=["influx", "sqlite"],
        default="influx",
        help="Where to pull historical telemetry from.",
    )
    # Influx options
    p.add_argument("--influx-url")
    p.add_argument("--influx-token")
    p.add_argument("--influx-org", default="intrepid-logic")
    p.add_argument("--influx-bucket", default="aevus_telemetry")
    # SQLite (lab fallback) options
    p.add_argument("--sqlite-path", default="./data/aevus.db")
    # S3 destination
    p.add_argument(
        "--bucket",
        required=True,
        help="S3 training bucket (from `terraform output l4e_training_bucket`).",
    )
    p.add_argument(
        "--dataset-name",
        default="aevus-lab-v1",
        help="Dataset name — becomes the S3 prefix and the L4E dataset id.",
    )
    # Window + components
    p.add_argument(
        "--window-days", type=int, default=21, help="Days of history to export. L4E minimum is 14."
    )
    p.add_argument(
        "--components",
        help="Comma-separated asset_ids. Defaults to all assets that have any DEFAULT_METRICS data in the window.",
    )
    p.add_argument(
        "--metrics",
        help="Comma-separated metrics to include. Defaults to the SCADA-friendly subset.",
    )
    p.add_argument(
        "--interval",
        default="60s",
        help="Resample interval. L4E accepts 1s-3600s; 60s is a sensible default for the lab.",
    )
    # Safety / rehearsal
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be exported + write CSV bodies to stdout; never upload.",
    )
    return p.parse_args()


# ──────────────────────────────────────────────────────────────────────────
# Source — pull telemetry rows
# ──────────────────────────────────────────────────────────────────────────
def fetch_from_influx(
    args: argparse.Namespace, metrics: list[str], start: datetime, stop: datetime
) -> dict[str, dict[datetime, dict[str, float]]]:
    """Returns {asset_id: {ts: {metric: value, ...}}}."""
    try:
        from influxdb_client import InfluxDBClient
    except ImportError:
        sys.exit("influxdb-client not installed. pip install influxdb-client")

    if not args.influx_url or not args.influx_token:
        sys.exit("--influx-url and --influx-token required for --source influx")

    flux = f'''
    from(bucket: "{args.influx_bucket}")
      |> range(start: {start.isoformat()}, stop: {stop.isoformat()})
      |> filter(fn: (r) => contains(value: r._field, set: {json.dumps(metrics)}))
      |> aggregateWindow(every: {args.interval}, fn: mean, createEmpty: false)
      |> keep(columns: ["_time", "_value", "_field", "asset_id"])
    '''

    out: dict[str, dict[datetime, dict[str, float]]] = defaultdict(lambda: defaultdict(dict))
    with InfluxDBClient(
        url=args.influx_url, token=args.influx_token, org=args.influx_org
    ) as client:
        tables = client.query_api().query(flux)
        for table in tables:
            for record in table.records:
                aid = record.values.get("asset_id")
                if not aid:
                    continue
                ts = record.get_time()
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=UTC)
                out[aid][ts][record.get_field()] = record.get_value()
    return out


def fetch_from_sqlite(
    args: argparse.Namespace, metrics: list[str], start: datetime, stop: datetime
) -> dict[str, dict[datetime, dict[str, float]]]:
    """Lab fallback: pulls the latest vitals_json from each asset row.

    NOTE: SQLite stores only the *latest* snapshot in vitals_json, not
    historical readings. This path produces a single-point dataset
    useful for schema validation but NOT for actual model training.
    Production must use the Influx path.
    """
    if not Path(args.sqlite_path).exists():
        sys.exit(f"SQLite DB not found: {args.sqlite_path}")

    out: dict[str, dict[datetime, dict[str, float]]] = defaultdict(lambda: defaultdict(dict))
    now = datetime.now(UTC).replace(microsecond=0)
    conn = sqlite3.connect(args.sqlite_path)
    conn.row_factory = sqlite3.Row
    try:
        for row in conn.execute("SELECT id, vitals_json FROM assets"):
            asset_id = row["id"]
            try:
                vitals = json.loads(row["vitals_json"] or "[]")
            except json.JSONDecodeError:
                continue
            for v in vitals:
                # VitalSign objects use UPPER labels — we want lowercase metric ids.
                metric_id = v.get("label", "").lower().replace(" ", "_")
                if metric_id not in metrics:
                    continue
                raw_value = v.get("raw_value")
                if raw_value is None:
                    continue
                out[asset_id][now][metric_id] = float(raw_value)
        print(
            "WARNING: SQLite source produces single-point datasets. "
            "Use the Influx path for real L4E training.",
            file=sys.stderr,
        )
    finally:
        conn.close()
    return out


# ──────────────────────────────────────────────────────────────────────────
# Format → CSV
# ──────────────────────────────────────────────────────────────────────────
def to_csv(rows_by_ts: dict[datetime, dict[str, float]], metrics: list[str]) -> str:
    """Build the per-component CSV that L4E expects."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Timestamp"] + metrics)
    for ts in sorted(rows_by_ts.keys()):
        row = rows_by_ts[ts]
        writer.writerow([ts.isoformat()] + [row.get(m, "") for m in metrics])
    return buf.getvalue()


# ──────────────────────────────────────────────────────────────────────────
# Upload
# ──────────────────────────────────────────────────────────────────────────
def upload(args: argparse.Namespace, component: str, csv_body: str) -> str:
    try:
        import boto3
    except ImportError:
        sys.exit("boto3 not installed. pip install boto3")
    key = f"datasets/{args.dataset_name}/{component}.csv"
    s3 = boto3.client("s3")
    s3.put_object(
        Bucket=args.bucket,
        Key=key,
        Body=csv_body.encode("utf-8"),
        ContentType="text/csv",
    )
    return f"s3://{args.bucket}/{key}"


# ──────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────
def main() -> int:
    args = _parse_args()
    metrics = [m.strip() for m in (args.metrics or ",".join(DEFAULT_METRICS)).split(",")]
    stop = datetime.now(UTC).replace(microsecond=0)
    start = stop - timedelta(days=args.window_days)

    print(f"==> Source:    {args.source}")
    print(f"==> Window:    {start.isoformat()} → {stop.isoformat()} ({args.window_days}d)")
    print(f"==> Bucket:    s3://{args.bucket}/datasets/{args.dataset_name}/")
    print(f"==> Metrics:   {', '.join(metrics)}")

    if args.source == "influx":
        data = fetch_from_influx(args, metrics, start, stop)
    else:
        data = fetch_from_sqlite(args, metrics, start, stop)

    if args.components:
        wanted = {c.strip() for c in args.components.split(",")}
        data = {k: v for k, v in data.items() if k in wanted}
    print(f"==> Components: {sorted(data.keys()) or '(none — empty source)'}")

    if not data:
        print("ERROR: no telemetry rows match the filter.", file=sys.stderr)
        return 1

    for component_id, rows_by_ts in sorted(data.items()):
        csv_body = to_csv(rows_by_ts, metrics)
        line_count = csv_body.count("\n") - 1  # minus header
        if args.dry_run:
            print(
                f"\n--- DRY RUN: would upload datasets/{args.dataset_name}/{component_id}.csv ---"
            )
            print(f"  rows: {line_count}")
            preview = "\n".join(csv_body.splitlines()[:3])
            print(f"  preview:\n{preview}")
        else:
            uri = upload(args, component_id, csv_body)
            print(f"  ↑ {uri}  ({line_count} rows)")

    print("\n==> Next: run scripts/bootstrap_l4e_model.py against this dataset")
    return 0


if __name__ == "__main__":
    sys.exit(main())

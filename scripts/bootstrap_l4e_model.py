#!/usr/bin/env python3
"""Bootstrap an AWS Lookout for Equipment dataset, model, and scheduler.

L4E lifecycle (per AWS docs):
    1. CreateDataset             — define the schema (one component per
                                   asset, each with N analog metrics).
    2. StartDataIngestionJob     — point at the training-data S3 prefix
                                   uploaded by export_l4e_training_data.py.
    3. CreateModel               — kick off model training. Takes 1-4h
                                   for typical lab dataset sizes; we
                                   poll for completion.
    4. CreateInferenceScheduler  — wire up continuous inference reading
                                   from a "live" S3 prefix and writing
                                   anomaly scores back to an output
                                   prefix on a fixed cadence.

This script handles 1-3 by default. Pass --skip-model to stop after
ingestion if you only want to validate the schema. Pass --start-scheduler
to also do step 4 once the model is ACTIVE.

Pre-conditions:
    • aws-l4e.tf applied with var.l4e_enabled = true.
    • Training data uploaded via export_l4e_training_data.py.
    • Region matches Terraform region (default us-east-2).

Usage:
    python scripts/bootstrap_l4e_model.py \\
        --dataset-name aevus-lab-v1 \\
        --training-bucket aevus-l4e-training-prod-XXX-us-east-2 \\
        --inference-bucket aevus-l4e-inference-prod-XXX-us-east-2 \\
        --role-arn $(terraform -chdir=infra/terraform output -raw l4e_service_role_arn) \\
        --components RTU-01,RAD-01,RAD-02 \\
        --start-scheduler \\
        --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dataset-name", required=True,
                   help="Dataset identifier — must match the S3 prefix from the exporter.")
    p.add_argument("--training-bucket", required=True,
                   help="S3 bucket holding the training CSVs.")
    p.add_argument("--inference-bucket", required=True,
                   help="S3 bucket where inference scores will land.")
    p.add_argument("--role-arn", required=True,
                   help="L4E service role ARN (Terraform output).")
    p.add_argument("--region", default="us-east-2")
    p.add_argument("--components", required=True,
                   help="Comma-separated asset_ids matching the per-component CSVs.")
    p.add_argument("--metrics",
                   help="Comma-separated metric column names. Required if the schema can't be auto-derived from the CSV header.")
    p.add_argument("--sampling-rate", default="PT1M",
                   help="ISO-8601 duration for data sampling rate (PT1M = 1 minute).")
    p.add_argument("--training-fraction", type=float, default=0.7,
                   help="Fraction of the dataset used for training vs. evaluation. Default 0.7.")
    p.add_argument("--evaluation-window-days", type=int, default=2,
                   help="Trailing days reserved for evaluation. Default 2.")
    p.add_argument("--scheduler-frequency", default="PT5M",
                   help="How often the inference scheduler runs (PT5M = every 5 minutes).")
    p.add_argument("--skip-model", action="store_true",
                   help="Stop after ingestion. Useful for schema-only rehearsal.")
    p.add_argument("--start-scheduler", action="store_true",
                   help="Create + start the inference scheduler after the model is ACTIVE.")
    p.add_argument("--dry-run", action="store_true",
                   help="Print every API call we'd make and exit. No AWS calls.")
    p.add_argument("--wait-timeout-min", type=int, default=240,
                   help="How long to wait for model training (minutes). Default 4h.")
    return p.parse_args()


def _client(region: str):
    try:
        import boto3
    except ImportError:
        sys.exit("boto3 not installed. pip install boto3")
    return boto3.client("lookoutequipment", region_name=region)


def _schema(components: list[str], metrics: list[str]) -> dict[str, Any]:
    """L4E's dataset schema — one Component per asset, each with the
    same set of metrics."""
    return {
        "Components": [
            {
                "ComponentName": c,
                "Columns": (
                    [{"Name": "Timestamp", "Type": "DATETIME"}]
                    + [{"Name": m, "Type": "DOUBLE"} for m in metrics]
                ),
            }
            for c in components
        ]
    }


def _step(args, label: str, payload: Any) -> None:
    print(f"\n→ {label}")
    print(json.dumps(payload, indent=2, default=str))


def create_dataset(client, args, components, metrics) -> None:
    schema = _schema(components, metrics)
    _step(args, "CreateDataset", {
        "DatasetName": args.dataset_name,
        "DatasetSchema": {"InlineDataSchema": json.dumps(schema)},
        "ServerSideKmsKeyId": "alias/aws/lookoutequipment",
    })
    if args.dry_run:
        return
    try:
        client.create_dataset(
            DatasetName=args.dataset_name,
            DatasetSchema={"InlineDataSchema": json.dumps(schema)},
        )
    except client.exceptions.ConflictException:
        print("   (dataset already exists, continuing)")


def start_ingestion(client, args) -> str:
    s3_uri = f"s3://{args.training_bucket}/datasets/{args.dataset_name}/"
    payload = {
        "DatasetName": args.dataset_name,
        "IngestionInputConfiguration": {
            "S3InputConfiguration": {
                "Bucket": args.training_bucket,
                "Prefix": f"datasets/{args.dataset_name}/",
            }
        },
        "RoleArn": args.role_arn,
    }
    _step(args, f"StartDataIngestionJob (source: {s3_uri})", payload)
    if args.dry_run:
        return "dry-run-job-id"

    resp = client.start_data_ingestion_job(**payload)
    job_id = resp["JobId"]
    print(f"   job_id = {job_id}")

    print("   waiting for ingestion to finish...")
    while True:
        d = client.describe_data_ingestion_job(JobId=job_id)
        status = d["Status"]
        print(f"   status = {status}")
        if status == "SUCCESS":
            return job_id
        if status == "FAILED":
            sys.exit(f"   FAILED: {d.get('FailedReason', '')}")
        time.sleep(20)


def create_model(client, args) -> str:
    payload = {
        "ModelName": f"{args.dataset_name}-model",
        "DatasetName": args.dataset_name,
        "RoleArn": args.role_arn,
        "DataPreProcessingConfiguration": {
            "TargetSamplingRate": args.sampling_rate,
        },
        # Training window: everything except the trailing evaluation window.
        # Times are passed as ISO timestamps at the time of the call;
        # we let L4E auto-detect the window from the ingested data
        # rather than hardcoding (more robust).
    }
    _step(args, "CreateModel", payload)
    if args.dry_run:
        return "dry-run-model-name"

    client.create_model(**payload)
    name = payload["ModelName"]

    print(f"   waiting for model training (up to {args.wait_timeout_min} min)...")
    deadline = time.time() + args.wait_timeout_min * 60
    while time.time() < deadline:
        d = client.describe_model(ModelName=name)
        status = d.get("Status", "UNKNOWN")
        print(f"   status = {status}")
        if status == "SUCCESS":
            metrics = d.get("ModelMetrics", "{}")
            print(f"   model_metrics = {metrics}")
            return name
        if status == "FAILED":
            sys.exit(f"   FAILED: {d.get('FailedReason', '')}")
        time.sleep(60)
    sys.exit("   TIMEOUT — model still training. Re-run with a higher --wait-timeout-min.")


def create_scheduler(client, args, model_name: str) -> None:
    """Wire an inference scheduler reading from the 'live' inference
    input prefix and writing scores back to the inference output prefix.

    Convention:
        s3://<training-bucket>/inference-input/<dataset>/<component>.csv
        s3://<inference-bucket>/inference-output/<dataset>/...
    """
    payload = {
        "ModelName": model_name,
        "InferenceSchedulerName": f"{args.dataset_name}-scheduler",
        "DataDelayOffsetInMinutes": 5,
        "DataInputConfiguration": {
            "S3InputConfiguration": {
                "Bucket": args.training_bucket,
                "Prefix": f"inference-input/{args.dataset_name}/",
            },
        },
        "DataOutputConfiguration": {
            "S3OutputConfiguration": {
                "Bucket": args.inference_bucket,
                "Prefix": f"inference-output/{args.dataset_name}/",
            },
        },
        "DataUploadFrequency": args.scheduler_frequency,
        "RoleArn": args.role_arn,
    }
    _step(args, "CreateInferenceScheduler", payload)
    if args.dry_run:
        return
    client.create_inference_scheduler(**payload)
    client.start_inference_scheduler(InferenceSchedulerName=payload["InferenceSchedulerName"])
    print(f"   scheduler started: {payload['InferenceSchedulerName']}")


def main() -> int:
    args = _parse_args()
    components = [c.strip() for c in args.components.split(",")]

    # Metrics default — must match the exporter's DEFAULT_METRICS so the
    # schema lines up with the CSVs.
    metrics = [m.strip() for m in (args.metrics or "rssi,snr,temperature,voltage,suction_pressure,discharge_pressure,flow_rate,battery_voltage,vibration").split(",")]

    print(f"==> Region:       {args.region}")
    print(f"==> Dataset:      {args.dataset_name}")
    print(f"==> Components:   {components}")
    print(f"==> Metrics:      {metrics}")
    print(f"==> Dry-run:      {args.dry_run}")

    if args.dry_run:
        client = None
    else:
        client = _client(args.region)

    if client:
        create_dataset(client, args, components, metrics)
    else:
        create_dataset(None, args, components, metrics)

    start_ingestion(client, args)

    if args.skip_model:
        print("\n==> --skip-model set, stopping after ingestion.")
        return 0

    model_name = create_model(client, args)

    if args.start_scheduler:
        create_scheduler(client, args, model_name)
    else:
        print("\n==> Model trained. Re-run with --start-scheduler to start continuous inference.")

    return 0


if __name__ == "__main__":
    sys.exit(main())

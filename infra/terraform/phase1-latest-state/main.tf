# ---------------------------------------------------------------------------
# Aevus convergence — Phase 1: latest-state store
# (see docs/ARCHITECTURE_edge_to_cloud_convergence_v1.md §5)
#
# Goal: give the cloud a per-asset "last known value" store fed directly by the
# edge's existing MQTT → IoT Core telemetry stream, so the dashboard can read
# current state from a stream-backed store instead of polling OT or copying
# SQLite via the bridge.
#
# This module is STANDALONE and additive. The existing IoT Core landing zone
# (thing aevus-edge-needville; rules aevus_archive_all / _critical_to_sns /
# _critical_to_rca) is NOT managed here — we only add a new DynamoDB table, a
# new topic rule, and the IAM role that rule needs. Nothing existing is touched.
#
# Cost: DynamoDB on-demand + a topic rule ≈ pennies/month at lab volume.
# Apply: terraform init && terraform plan -out tf.plan && terraform apply tf.plan
# ---------------------------------------------------------------------------

terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

locals {
  common_tags = {
    Service     = "Aevus"
    Environment = "production"
    Project     = "Aevus-Telemetry-Convergence"
    Phase       = "1-latest-state"
    ManagedBy   = "Terraform"
  }
}

# ---------- DynamoDB: per-asset/per-metric latest value ----------
# One item per (asset_id, metric). Every telemetry message upserts its item, so
# a read of PK=asset_id returns that asset's full current vital set in one query
# — O(1) for the dashboard, no fan-out polling.
resource "aws_dynamodb_table" "latest_state" {
  name         = var.table_name
  billing_mode = "PAY_PER_REQUEST" # on-demand — cheapest at low/spiky volume
  hash_key     = "asset_id"
  range_key    = "metric"

  attribute {
    name = "asset_id"
    type = "S"
  }
  attribute {
    name = "metric"
    type = "S"
  }

  # Optional TTL: lets stale points self-expire if an asset goes dark for a long
  # time. Disabled by default (latest-state should persist); enable via var.
  ttl {
    attribute_name = "expires_at"
    enabled        = var.enable_ttl
  }

  point_in_time_recovery {
    enabled = true
  }

  tags = merge(local.common_tags, { Name = var.table_name })
}

# ---------- IAM role the IoT topic rule assumes to write DynamoDB ----------
data "aws_iam_policy_document" "iot_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["iot.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "iot_to_ddb" {
  name               = "aevus-iot-latest-state-ddb"
  assume_role_policy = data.aws_iam_policy_document.iot_assume.json
  tags               = local.common_tags
}

data "aws_iam_policy_document" "ddb_put" {
  statement {
    sid       = "WriteLatestState"
    actions   = ["dynamodb:PutItem"]
    resources = [aws_dynamodb_table.latest_state.arn]
  }
}

resource "aws_iam_role_policy" "iot_to_ddb" {
  name   = "aevus-iot-latest-state-ddb"
  role   = aws_iam_role.iot_to_ddb.id
  policy = data.aws_iam_policy_document.ddb_put.json
}

# ---------- IoT topic rule: telemetry stream → latest-state table ----------
# Topic contract (src/integrations/topic_map.py):
#   aevus/{site}/{asset}/telemetry/{metric}
# Envelope: top-level {site_id, source, asset_id, type, payload:{metric,value,unit}}
#
# dynamoDBv2 splits each SELECT column into its own item attribute. asset_id +
# metric form the composite key; value/unit/source/site/updated_ms are columns.
# topic(n) is used for key fields (most reliable) — n is 1-indexed.
resource "aws_iot_topic_rule" "latest_state" {
  name        = "aevus_latest_state_to_ddb"
  enabled     = true
  sql         = <<-SQL
    SELECT
      topic(3)         AS asset_id,
      topic(5)         AS metric,
      topic(2)         AS site,
      payload.value    AS value,
      payload.unit     AS unit,
      source           AS source,
      timestamp()      AS updated_ms
    FROM 'aevus/+/+/telemetry/+'
  SQL
  sql_version = "2016-03-23"

  dynamodbv2 {
    role_arn = aws_iam_role.iot_to_ddb.arn
    put_item {
      table_name = aws_dynamodb_table.latest_state.name
    }
  }

  # Surface rule errors instead of silently dropping (CloudWatch Logs).
  error_action {
    cloudwatch_logs {
      log_group_name = aws_cloudwatch_log_group.rule_errors.name
      role_arn       = aws_iam_role.iot_to_ddb.arn
    }
  }

  tags = merge(local.common_tags, { Name = "aevus_latest_state_to_ddb" })
}

# ---------- Phase 1.5: state stream → latest-state table ----------
# The edge also publishes derived/metadata STATE (firmware, health, status,
# last_seen, uptime_24h) to aevus/{site}/{asset}/state/{key}. We land these in
# the SAME table, namespacing the sort key as "state:<key>" so state and
# telemetry coexist under one asset_id partition. A single Query(asset_id) then
# returns everything the read-API needs (Phase 2). Reuses the role + table.
resource "aws_iot_topic_rule" "state" {
  name        = "aevus_state_to_ddb"
  enabled     = true
  sql         = <<-SQL
    SELECT
      topic(3)                   AS asset_id,
      concat('state:', topic(5)) AS metric,
      topic(2)                   AS site,
      payload.state              AS value,
      source                     AS source,
      timestamp()                AS updated_ms
    FROM 'aevus/+/+/state/+'
  SQL
  sql_version = "2016-03-23"

  dynamodbv2 {
    role_arn = aws_iam_role.iot_to_ddb.arn
    put_item {
      table_name = aws_dynamodb_table.latest_state.name
    }
  }

  error_action {
    cloudwatch_logs {
      log_group_name = aws_cloudwatch_log_group.rule_errors.name
      role_arn       = aws_iam_role.iot_to_ddb.arn
    }
  }

  tags = merge(local.common_tags, { Name = "aevus_state_to_ddb" })
}

resource "aws_cloudwatch_log_group" "rule_errors" {
  name              = "/aws/iot/aevus-latest-state-errors"
  retention_in_days = 14
  tags              = local.common_tags
}

# Allow the rule's role to write its error logs.
data "aws_iam_policy_document" "rule_error_logs" {
  statement {
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
      "logs:DescribeLogStreams",
    ]
    resources = ["${aws_cloudwatch_log_group.rule_errors.arn}:*"]
  }
}

resource "aws_iam_role_policy" "rule_error_logs" {
  name   = "aevus-iot-latest-state-errlogs"
  role   = aws_iam_role.iot_to_ddb.id
  policy = data.aws_iam_policy_document.rule_error_logs.json
}

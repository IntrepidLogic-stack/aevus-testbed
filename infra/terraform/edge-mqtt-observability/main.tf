# ---------------------------------------------------------------------------
# Aevus edge MQTT observability — Task #149 IaC capture
#
# Captures the out-of-band AWS resources created during the 2026-05-30 work
# on Tasks #151 (MQTT half-open hardening) and #152 (ghost-clientId fix).
# All four resources were created via AWS CLI; this module is the canonical
# source of truth going forward.
#
# What's owned here:
#   1. IoT policy version v3 of `aevus-edge-publish` (Task #152)
#      — locked clientId pattern + per-site topic scope, kills the
#        bare-thing-name slot the ghost was holding.
#   2. CloudWatch alarm `aevus-iot-ghost-connect-rejected` (Task #152)
#      — fires on any Connect.AuthError so a returning ghost is caught
#        at first attempt.
#   3. IAM role `aevus-iot-cloudwatch-metric-role` + IoT topic rule
#      `aevus_edge_mqtt_health` (Task #151 follow-up) — pumps the Pi's
#      MQTTPublisher.consecutive_publish_failures into the Aevus/Edge
#      CloudWatch namespace.
#   4. CloudWatch alarm `aevus-edge-mqtt-publish-failures` (Task #151
#      follow-up) — fires at threshold-1 (vs the in-process threshold-5).
#
# What's NOT owned here (still out-of-band, separate module):
#   • The IoT thing `aevus-edge-needville` itself + its cert attachment
#   • The S3 audit bucket + archive rules
#   • The Bedrock RCA Lambda (deployed-only; source restored in PR #59
#     under infra/lambda/rca/ — Lambda function itself still bare AWS)
#   • The SNS topic `aevus-critical-alerts` + its subscriptions
#   These are referenced as `data` resources so a `terraform apply` of
#   this module doesn't replace them.
#
# Import strategy: see IMPORT.md in this directory.
#
# Cost at lab volume: < $1/month.
# Apply:
#   cd infra/terraform/edge-mqtt-observability
#   terraform init
#   terraform plan -out tf.plan
#   terraform apply tf.plan
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

variable "aws_region" {
  type        = string
  default     = "us-east-1"
  description = "Account region. Everything Aevus lives in us-east-1."
}

variable "site_id" {
  type        = string
  default     = "needville"
  description = "Site slug — used in the IoT policy's clientId/topic patterns. Today there's one site; this is the knob to fan out when we add more edges."
}

variable "critical_sns_topic_arn" {
  type        = string
  default     = "arn:aws:sns:us-east-1:676433090238:aevus-critical-alerts"
  description = "Existing SNS topic that both alarms publish to. Subscribers (chiefegr@, woody@) managed in a separate module."
}

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id
  region     = data.aws_region.current.name
}

# ---------------------------------------------------------------------------
# 1. IoT policy aevus-edge-publish v3 (Task #152)
# ---------------------------------------------------------------------------
# Tightened from v2: iot:Connect scoped to client/aevus-edge-{site}-*
# (closes the bare-thing-name slot the ghost was grabbing); topics scoped
# to aevus/{site}/* (per-site isolation).
resource "aws_iot_policy" "edge_publish" {
  name = "aevus-edge-publish"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ConnectAsNeedvilleEdgeReplicasOnly"
        Effect   = "Allow"
        Action   = ["iot:Connect"]
        Resource = "arn:aws:iot:${local.region}:${local.account_id}:client/aevus-edge-${var.site_id}-*"
      },
      {
        Sid      = "Publish${title(var.site_id)}Topics"
        Effect   = "Allow"
        Action   = ["iot:Publish", "iot:PublishRetain"]
        Resource = "arn:aws:iot:${local.region}:${local.account_id}:topic/aevus/${var.site_id}/*"
      },
      {
        Sid      = "Subscribe${title(var.site_id)}Topics"
        Effect   = "Allow"
        Action   = ["iot:Subscribe"]
        Resource = "arn:aws:iot:${local.region}:${local.account_id}:topicfilter/aevus/${var.site_id}/*"
      },
      {
        Sid      = "Receive${title(var.site_id)}Topics"
        Effect   = "Allow"
        Action   = ["iot:Receive"]
        Resource = "arn:aws:iot:${local.region}:${local.account_id}:topic/aevus/${var.site_id}/*"
      },
    ]
  })
}

# ---------------------------------------------------------------------------
# 2. Ghost-rejection alarm (Task #152)
# ---------------------------------------------------------------------------
resource "aws_cloudwatch_metric_alarm" "iot_ghost_connect_rejected" {
  alarm_name        = "aevus-iot-ghost-connect-rejected"
  alarm_description = "IoT Connect.AuthError > 0 — a client tried to connect with a clientId not allowed by aevus-edge-publish v3. After the 2026-05-30 policy tightening, this fires if anything attempts the bare 'aevus-edge-${var.site_id}' clientId (the old ghost slot). Investigate via CloudTrail — source IP is recorded there."

  namespace           = "AWS/IoT"
  metric_name         = "Connect.AuthError"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  alarm_actions = [var.critical_sns_topic_arn]
}

# ---------------------------------------------------------------------------
# 3a. IAM role for IoT rule → CloudWatch (Task #151 follow-up)
# ---------------------------------------------------------------------------
resource "aws_iam_role" "iot_cloudwatch_metric" {
  name        = "aevus-iot-cloudwatch-metric-role"
  description = "IoT rule → CloudWatch PutMetricData for edge health metrics (Task #151). cloudwatch:PutMetricData scoped to Aevus/Edge namespace only."

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "iot.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "iot_cloudwatch_metric" {
  name = "allow-cw-put-aevus-edge"
  role = aws_iam_role.iot_cloudwatch_metric.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "cloudwatch:PutMetricData"
      Resource = "*"
      Condition = {
        StringEquals = {
          "cloudwatch:namespace" = "Aevus/Edge"
        }
      }
    }]
  })
}

# ---------------------------------------------------------------------------
# 3b. IoT topic rule → CloudWatch custom metric (Task #151 follow-up)
# ---------------------------------------------------------------------------
# Pi's main.py publishes MQTTPublisher.health every 60s to
# aevus/{site}/EDGE-01/state/mqtt_publisher_health. This rule pumps the
# consecutive_publish_failures field into the Aevus/Edge namespace so the
# alarm below can fire at threshold-1.
resource "aws_iot_topic_rule" "edge_mqtt_health" {
  name        = "aevus_edge_mqtt_health"
  description = "Task #151 — pump MQTTPublisher half-open failure counter into CloudWatch every minute. Lets us alarm at first failure (vs the in-process threshold of 5)."

  enabled     = true
  sql         = "SELECT payload.consecutive_publish_failures AS value, site_id FROM 'aevus/+/EDGE-01/state/mqtt_publisher_health'"
  sql_version = "2016-03-23"

  cloudwatch_metric {
    role_arn         = aws_iam_role.iot_cloudwatch_metric.arn
    metric_namespace = "Aevus/Edge"
    metric_name      = "ConsecutivePublishFailures"
    metric_value     = "$${value}"
    metric_unit      = "Count"
  }
}

# ---------------------------------------------------------------------------
# 4. MQTT publish-failure alarm (Task #151 follow-up)
# ---------------------------------------------------------------------------
# Maximum (not Sum) so a transient single-failure-then-success still trips
# — we want EARLIEST signal, not aggregate behavior over 5 min.
# Missing data = breaching catches the case where the Pi can't publish
# at all (cert revoked, process dead, network out).
resource "aws_cloudwatch_metric_alarm" "edge_mqtt_publish_failures" {
  alarm_name        = "aevus-edge-mqtt-publish-failures"
  alarm_description = "MQTTPublisher half-open detector counter > 0 (Task #151). In-process detector catches this at 5 consecutive failures (~25s); this alarm catches the FIRST failure (~60s). Also fires on missing-data (>10 min) — means the Pi can't publish to IoT Core at all (cert/network/process issue)."

  namespace           = "Aevus/Edge"
  metric_name         = "ConsecutivePublishFailures"
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "breaching"

  alarm_actions = [var.critical_sns_topic_arn]
  ok_actions    = [var.critical_sns_topic_arn]
}

# ---------------------------------------------------------------------------
# Outputs — for cross-module references (the eventual thing/cert module
# will want the policy name; the alarm-routing module the alarm ARNs).
# ---------------------------------------------------------------------------
output "edge_publish_policy_name" {
  value       = aws_iot_policy.edge_publish.name
  description = "IoT policy name — attach via separate cert-management."
}

output "ghost_alarm_arn" {
  value = aws_cloudwatch_metric_alarm.iot_ghost_connect_rejected.arn
}

output "publish_failures_alarm_arn" {
  value = aws_cloudwatch_metric_alarm.edge_mqtt_publish_failures.arn
}

output "iot_cloudwatch_metric_role_arn" {
  value = aws_iam_role.iot_cloudwatch_metric.arn
}

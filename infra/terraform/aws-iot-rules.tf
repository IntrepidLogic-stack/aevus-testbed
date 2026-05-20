# ============================================================
# IoT Core rules — route incoming MQTT messages to AWS services.
#
# Topic → Destination:
#
#   aevus/+/+/telemetry/+         → SiteWise property update (data)
#   aevus/+/+/state/+             → SiteWise property update (state)
#   aevus/+/+/events/+            → S3 audit (Object Lock immutable)
#   aevus/+/+/alerts/critical     → Lambda (alarm router) + S3 audit
#   aevus/+/+/alerts/+            → DynamoDB alert log
#   aevus/+/system/audit          → S3 audit (Object Lock immutable)
#
# All rules use error actions → CloudWatch Logs so we can debug
# routing failures without dropping data.
# ============================================================

# ── Shared role used by IoT Core to invoke other AWS services ───────────
resource "aws_iam_role" "iot_rule_actions" {
  name = "aevus-iot-rule-actions"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = { Service = "iot.amazonaws.com" }
      Action = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "iot_rule_actions" {
  name = "aevus-iot-rule-actions"
  role = aws_iam_role.iot_rule_actions.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "iotsitewise:BatchPutAssetPropertyValue",
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "s3:PutObject",
        ]
        Resource = "${aws_s3_bucket.audit.arn}/*"
      },
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents",
        ]
        Resource = "arn:aws:logs:*:*:*"
      },
      {
        Effect   = "Allow"
        Action   = ["kms:Encrypt", "kms:GenerateDataKey"]
        Resource = aws_kms_key.aevus.arn
      },
    ]
  })
}

resource "aws_cloudwatch_log_group" "iot_rule_errors" {
  name              = "/aevus/iot/rule-errors"
  retention_in_days = 30
  kms_key_id        = aws_kms_key.aevus.arn
}

# ── Rule: events → S3 audit (Object Lock) ──────────────────────────────
# Captures every SNMP trap, DNP3 event, and syslog message into the
# immutable audit bucket. This is the IEC 62443 evidence chain.
resource "aws_iot_topic_rule" "events_to_audit" {
  name        = "aevus_events_to_audit"
  description = "Aevus — route events/* MQTT topics into S3 audit bucket with Object Lock"
  sql         = "SELECT * FROM 'aevus/+/+/events/+'"
  sql_version = "2016-03-23"
  enabled     = true

  s3 {
    bucket_name = aws_s3_bucket.audit.id
    # Year/month/day partitioning so Athena queries are cheap.
    key      = "events/$${topic(2)}/$${topic(3)}/$${parse_time('yyyy/MM/dd', timestamp())}/$${parse_time('HH-mm-ss-SSS', timestamp())}-$${newuuid()}.json"
    role_arn = aws_iam_role.iot_rule_actions.arn
  }

  error_action {
    cloudwatch_logs {
      log_group_name = aws_cloudwatch_log_group.iot_rule_errors.name
      role_arn       = aws_iam_role.iot_rule_actions.arn
    }
  }
}

# ── Rule: alerts → S3 audit ─────────────────────────────────────────────
resource "aws_iot_topic_rule" "alerts_to_audit" {
  name        = "aevus_alerts_to_audit"
  description = "Aevus — capture every alarm into the immutable audit log"
  sql         = "SELECT * FROM 'aevus/+/+/alerts/+'"
  sql_version = "2016-03-23"
  enabled     = true

  s3 {
    bucket_name = aws_s3_bucket.audit.id
    key         = "alerts/$${topic(2)}/$${topic(3)}/$${topic(5)}/$${parse_time('yyyy/MM/dd', timestamp())}/$${parse_time('HH-mm-ss-SSS', timestamp())}-$${newuuid()}.json"
    role_arn    = aws_iam_role.iot_rule_actions.arn
  }

  error_action {
    cloudwatch_logs {
      log_group_name = aws_cloudwatch_log_group.iot_rule_errors.name
      role_arn       = aws_iam_role.iot_rule_actions.arn
    }
  }
}

# ── Rule: site-wide audit feed → S3 ─────────────────────────────────────
resource "aws_iot_topic_rule" "system_audit_to_s3" {
  name        = "aevus_system_audit"
  description = "Aevus — site-wide audit feed (CloudTrail-equivalent for the edge)"
  sql         = "SELECT * FROM 'aevus/+/system/audit'"
  sql_version = "2016-03-23"
  enabled     = true

  s3 {
    bucket_name = aws_s3_bucket.audit.id
    key         = "system/$${topic(2)}/$${parse_time('yyyy/MM/dd', timestamp())}/$${parse_time('HH-mm-ss-SSS', timestamp())}-$${newuuid()}.json"
    role_arn    = aws_iam_role.iot_rule_actions.arn
  }

  error_action {
    cloudwatch_logs {
      log_group_name = aws_cloudwatch_log_group.iot_rule_errors.name
      role_arn       = aws_iam_role.iot_rule_actions.arn
    }
  }
}

# ── Note: SiteWise ingest rule (telemetry → asset property) ─────────────
# The SiteWise rule action requires explicit propertyAlias mapping
# per asset, which is created when the seed_assets script registers
# devices against the cabinet model. Wiring up a wildcard SiteWise
# rule here would create dangling references when devices haven't
# been provisioned yet.
#
# Once the asset registry is data-driven (Lambda watches an
# DynamoDB table of devices and creates SiteWise assets + IoT rules
# per device), this section will land. Tracked separately.

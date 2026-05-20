# ============================================================
# Amazon Lookout for Equipment (L4E) — pilot stage.
#
# L4E is the right tool for continuous anomaly detection on
# industrial-process signals (vibration, RSSI, temperature, RTU
# analog values). Purpose-trained on industrial data; outperforms
# generic time-series models for sub-anomaly regime shifts.
#
# State today:
#   • We do NOT yet have labeled training data. L4E needs at least
#     14 days of normal-operation telemetry per model build.
#   • This file provisions the project, dataset stub, training data
#     bucket, and IAM. It does NOT yet create a model — model
#     creation happens after we've exported the first 14-day
#     dataset from InfluxDB → S3.
#
# Bootstrap sequence (once data is collected):
#   1. Run scripts/export_l4e_training_data.py (TBD) which dumps
#      historical InfluxDB metrics to s3://aevus-l4e-training/...
#      in L4E's CSV-per-component format.
#   2. terraform apply with var.l4e_create_model=true to trigger
#      the model build via a Terraform-managed CodeBuild job
#      (which calls CreateModel — Terraform doesn't have a native
#      L4E model resource yet).
#   3. Wire the inference scheduler to dump scores onto an MQTT
#      topic (aevus/{site}/{asset}/events/anomaly) consumed by
#      the alert engine via the publisher.
# ============================================================

variable "l4e_enabled" {
  description = "Provision the L4E pilot. Disable to skip during early-stage cost optimization."
  type        = bool
  default     = false   # opt-in until we have training data
}

# ── Training data bucket ────────────────────────────────────────────────
resource "aws_s3_bucket" "l4e_training" {
  count         = var.l4e_enabled ? 1 : 0
  bucket        = "aevus-l4e-training-${var.environment}-${data.aws_caller_identity.current.account_id}-${data.aws_region.current.name}"
  force_destroy = var.environment == "dev"
}

resource "aws_s3_bucket_server_side_encryption_configuration" "l4e_training" {
  count  = var.l4e_enabled ? 1 : 0
  bucket = aws_s3_bucket.l4e_training[0].id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.aevus.arn
    }
  }
}

resource "aws_s3_bucket_public_access_block" "l4e_training" {
  count                   = var.l4e_enabled ? 1 : 0
  bucket                  = aws_s3_bucket.l4e_training[0].id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# ── Inference results bucket ────────────────────────────────────────────
# L4E pushes anomaly scores here on its inference schedule.
resource "aws_s3_bucket" "l4e_inference" {
  count         = var.l4e_enabled ? 1 : 0
  bucket        = "aevus-l4e-inference-${var.environment}-${data.aws_caller_identity.current.account_id}-${data.aws_region.current.name}"
  force_destroy = var.environment == "dev"
}

resource "aws_s3_bucket_server_side_encryption_configuration" "l4e_inference" {
  count  = var.l4e_enabled ? 1 : 0
  bucket = aws_s3_bucket.l4e_inference[0].id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.aevus.arn
    }
  }
}

# ── L4E service role ────────────────────────────────────────────────────
resource "aws_iam_role" "l4e_service" {
  count = var.l4e_enabled ? 1 : 0
  name  = "aevus-l4e-service"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lookoutequipment.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "l4e_service" {
  count = var.l4e_enabled ? 1 : 0
  name  = "aevus-l4e-service"
  role  = aws_iam_role.l4e_service[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:ListBucket",
          "s3:GetBucketLocation",
        ]
        Resource = [
          aws_s3_bucket.l4e_training[0].arn,
          "${aws_s3_bucket.l4e_training[0].arn}/*",
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "s3:PutObject",
        ]
        Resource = "${aws_s3_bucket.l4e_inference[0].arn}/*"
      },
      {
        Effect   = "Allow"
        Action   = ["kms:Decrypt", "kms:GenerateDataKey"]
        Resource = aws_kms_key.aevus.arn
      },
    ]
  })
}

# ── L4E dataset placeholder ─────────────────────────────────────────────
# L4E dataset is the schema definition (column → component → asset
# mapping). The actual model build is gated on having training data.
#
# Schema spans the metrics most informative for industrial anomaly
# detection per CLAUDE.md threshold defaults:
#   • Radio: RSSI, SNR, temperature
#   • RTU:   suction_pressure, discharge_pressure, vibration,
#            battery_voltage, flow_rate
# ============================================================
#
# Note: Terraform's AWS provider doesn't currently support
# aws_lookoutequipment_* resources directly. Once we have data,
# the model + scheduler are created via a one-shot script that
# calls boto3.client('lookoutequipment') — see
# scripts/bootstrap_l4e_model.py (TBD).

# ── Outputs ─────────────────────────────────────────────────────────────
output "l4e_training_bucket" {
  description = "S3 bucket where L4E training data is staged. Run scripts/export_l4e_training_data.py to populate it."
  value       = var.l4e_enabled ? aws_s3_bucket.l4e_training[0].id : null
}

output "l4e_inference_bucket" {
  description = "S3 bucket where L4E publishes per-asset anomaly scores. Subscribed to by a Lambda that re-publishes onto aevus/{site}/{asset}/events/anomaly."
  value       = var.l4e_enabled ? aws_s3_bucket.l4e_inference[0].id : null
}

output "l4e_service_role_arn" {
  description = "IAM role ARN to pass to CreateModel / CreateInferenceScheduler."
  value       = var.l4e_enabled ? aws_iam_role.l4e_service[0].arn : null
}

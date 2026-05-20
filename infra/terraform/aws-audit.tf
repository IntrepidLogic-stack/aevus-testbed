# ============================================================
# Audit, artifact storage, and KMS — fleet-wide resources
#
#   • S3 audit bucket    — Object Lock for compliance evidence
#   • S3 artifacts bucket — Greengrass component artifacts
#   • KMS key            — encrypts both buckets
#   • CloudTrail trail   — control-plane API audit log
# ============================================================

# ── KMS key for buckets + log encryption ────────────────────────────────
resource "aws_kms_key" "aevus" {
  description             = "Aevus — encryption at rest for audit, artifacts, CloudTrail"
  deletion_window_in_days = 30
  enable_key_rotation     = true
}

resource "aws_kms_alias" "aevus" {
  name          = "alias/aevus-${var.environment}"
  target_key_id = aws_kms_key.aevus.key_id
}

# ── Audit bucket — Object Lock, immutable for the retention window ──────
resource "aws_s3_bucket" "audit" {
  # Bucket names are globally unique. Including account ID + region
  # avoids the "name already taken" failure mode on first apply.
  bucket        = "aevus-audit-${var.environment}-${data.aws_caller_identity.current.account_id}-${data.aws_region.current.name}"
  force_destroy = false

  # MUST be set at create time for Object Lock to work.
  object_lock_enabled = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "audit" {
  bucket = aws_s3_bucket.audit.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.aevus.arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_versioning" "audit" {
  bucket = aws_s3_bucket.audit.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_object_lock_configuration" "audit" {
  bucket = aws_s3_bucket.audit.id

  rule {
    default_retention {
      mode = "COMPLIANCE"   # not even root can shorten this window
      days = var.audit_retention_days
    }
  }
}

resource "aws_s3_bucket_public_access_block" "audit" {
  bucket                  = aws_s3_bucket.audit.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# ── Artifacts bucket — Greengrass component zip artifacts ───────────────
resource "aws_s3_bucket" "artifacts" {
  bucket        = "aevus-edge-artifacts-${var.environment}-${data.aws_caller_identity.current.account_id}-${data.aws_region.current.name}"
  force_destroy = false
}

resource "aws_s3_bucket_versioning" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.aevus.arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "artifacts" {
  bucket                  = aws_s3_bucket.artifacts.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# ── CloudTrail — control-plane audit log ────────────────────────────────
resource "aws_s3_bucket" "cloudtrail" {
  bucket        = "aevus-cloudtrail-${var.environment}-${data.aws_caller_identity.current.account_id}-${data.aws_region.current.name}"
  force_destroy = false
}

resource "aws_s3_bucket_server_side_encryption_configuration" "cloudtrail" {
  bucket = aws_s3_bucket.cloudtrail.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.aevus.arn
    }
  }
}

resource "aws_s3_bucket_public_access_block" "cloudtrail" {
  bucket                  = aws_s3_bucket.cloudtrail.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

data "aws_iam_policy_document" "cloudtrail_bucket" {
  statement {
    sid     = "AWSCloudTrailAclCheck"
    effect  = "Allow"
    actions = ["s3:GetBucketAcl"]
    principals {
      type        = "Service"
      identifiers = ["cloudtrail.amazonaws.com"]
    }
    resources = [aws_s3_bucket.cloudtrail.arn]
  }

  statement {
    sid     = "AWSCloudTrailWrite"
    effect  = "Allow"
    actions = ["s3:PutObject"]
    principals {
      type        = "Service"
      identifiers = ["cloudtrail.amazonaws.com"]
    }
    resources = ["${aws_s3_bucket.cloudtrail.arn}/AWSLogs/${data.aws_caller_identity.current.account_id}/*"]

    condition {
      test     = "StringEquals"
      variable = "s3:x-amz-acl"
      values   = ["bucket-owner-full-control"]
    }
  }
}

resource "aws_s3_bucket_policy" "cloudtrail" {
  bucket = aws_s3_bucket.cloudtrail.id
  policy = data.aws_iam_policy_document.cloudtrail_bucket.json
}

resource "aws_cloudtrail" "aevus" {
  name                          = "aevus-${var.environment}"
  s3_bucket_name                = aws_s3_bucket.cloudtrail.id
  include_global_service_events = true
  is_multi_region_trail         = true
  enable_log_file_validation    = true

  depends_on = [aws_s3_bucket_policy.cloudtrail]
}

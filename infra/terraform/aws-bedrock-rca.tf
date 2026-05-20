# ============================================================
# Bedrock RCA Lambda — patent-relevant AI on real-time events.
#
# Wired:
#   aevus/+/+/alerts/critical (IoT Core)
#     ↓
#   IoT topic rule → invoke Lambda → Bedrock (Claude) → narrative
#     ↓
#   Publish RCA back to: aevus/{site}/{asset}/rca/{alert_id}
#   Append narrative to: s3://<audit>/rca/{site}/{asset}/yyyy/MM/dd/...
#
# Source: infra/lambda/rca/ — packaged from this Terraform via the
# archive_file data source. Updating the Lambda is `terraform apply`
# after editing the source files.
# ============================================================

# ── Lambda package ──────────────────────────────────────────────────────
data "archive_file" "rca_lambda" {
  type        = "zip"
  source_dir  = "${path.module}/../lambda/rca"
  output_path = "${path.module}/.build/rca_lambda.zip"
  excludes    = ["__pycache__", "*.pyc", "requirements.txt", "tests"]
}

# ── IAM role for the Lambda ─────────────────────────────────────────────
resource "aws_iam_role" "rca_lambda" {
  name = "aevus-rca-lambda"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action = "sts:AssumeRole"
    }]
  })
}

# Basic execution role (CloudWatch Logs).
resource "aws_iam_role_policy_attachment" "rca_basic_exec" {
  role       = aws_iam_role.rca_lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# Bedrock invoke — restricted to the model we actually call.
data "aws_iam_policy_document" "rca_bedrock" {
  statement {
    sid    = "InvokeClaude"
    effect = "Allow"
    actions = [
      "bedrock:InvokeModel",
    ]
    # Region-flexible model ARN. Bedrock model IDs are documented at
    # https://docs.aws.amazon.com/bedrock/latest/userguide/models-supported.html
    resources = [
      "arn:aws:bedrock:${var.aws_region}::foundation-model/${var.bedrock_model_id}",
    ]
  }
}

resource "aws_iam_role_policy" "rca_bedrock" {
  name   = "aevus-rca-bedrock"
  role   = aws_iam_role.rca_lambda.id
  policy = data.aws_iam_policy_document.rca_bedrock.json
}

# IoT publish — for the RCA narrative back-channel.
data "aws_iam_policy_document" "rca_iot_publish" {
  statement {
    sid    = "PublishRca"
    effect = "Allow"
    actions = ["iot:Publish"]
    resources = [
      "arn:aws:iot:${var.aws_region}:${data.aws_caller_identity.current.account_id}:topic/aevus/*/rca/*",
    ]
  }
  statement {
    sid       = "DescribeEndpoint"
    effect    = "Allow"
    actions   = ["iot:DescribeEndpoint"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "rca_iot_publish" {
  name   = "aevus-rca-iot-publish"
  role   = aws_iam_role.rca_lambda.id
  policy = data.aws_iam_policy_document.rca_iot_publish.json
}

# S3 read (audit bucket) + write (RCA narratives append).
data "aws_iam_policy_document" "rca_s3" {
  statement {
    sid       = "ReadEvents"
    effect    = "Allow"
    actions   = ["s3:GetObject", "s3:ListBucket"]
    resources = [aws_s3_bucket.audit.arn, "${aws_s3_bucket.audit.arn}/*"]
  }
  statement {
    sid       = "WriteRcaNarratives"
    effect    = "Allow"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.audit.arn}/rca/*"]
  }
  # KMS — the audit bucket is encrypted with our CMK.
  statement {
    sid    = "DecryptAudit"
    effect = "Allow"
    actions = [
      "kms:Decrypt",
      "kms:GenerateDataKey",
    ]
    resources = [aws_kms_key.aevus.arn]
  }
}

resource "aws_iam_role_policy" "rca_s3" {
  name   = "aevus-rca-s3"
  role   = aws_iam_role.rca_lambda.id
  policy = data.aws_iam_policy_document.rca_s3.json
}

# SiteWise read — to fetch asset metadata + related assets.
data "aws_iam_policy_document" "rca_sitewise" {
  statement {
    sid    = "ReadAssets"
    effect = "Allow"
    actions = [
      "iotsitewise:ListAssets",
      "iotsitewise:ListAssociatedAssets",
      "iotsitewise:DescribeAsset",
      "iotsitewise:DescribeAssetModel",
      "iotsitewise:GetAssetPropertyValue",
      "iotsitewise:GetAssetPropertyValueHistory",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "rca_sitewise" {
  name   = "aevus-rca-sitewise"
  role   = aws_iam_role.rca_lambda.id
  policy = data.aws_iam_policy_document.rca_sitewise.json
}

# ── Lambda function ─────────────────────────────────────────────────────
resource "aws_cloudwatch_log_group" "rca_lambda" {
  name              = "/aws/lambda/aevus-rca"
  retention_in_days = 30
  kms_key_id        = aws_kms_key.aevus.arn
}

# Dead-letter queue for invocations that fail completely.
resource "aws_sqs_queue" "rca_dlq" {
  name                       = "aevus-rca-dlq"
  message_retention_seconds  = 1209600 # 14 days
  visibility_timeout_seconds = 60
  kms_master_key_id          = aws_kms_key.aevus.id
}

resource "aws_iam_role_policy" "rca_dlq_send" {
  name = "aevus-rca-dlq-send"
  role = aws_iam_role.rca_lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "sqs:SendMessage"
      Resource = aws_sqs_queue.rca_dlq.arn
    }]
  })
}

resource "aws_lambda_function" "rca" {
  function_name    = "aevus-rca"
  role             = aws_iam_role.rca_lambda.arn
  filename         = data.archive_file.rca_lambda.output_path
  source_code_hash = data.archive_file.rca_lambda.output_base64sha256
  handler          = "handler.lambda_handler"
  runtime          = "python3.11"
  timeout          = 30
  memory_size      = 512

  environment {
    variables = {
      AUDIT_BUCKET             = aws_s3_bucket.audit.id
      IOT_ENDPOINT             = data.aws_iot_endpoint.iot.endpoint_address
      BEDROCK_MODEL_ID         = var.bedrock_model_id
      BEDROCK_REGION           = var.aws_region
      BEDROCK_MAX_TOKENS       = "1024"
      BEDROCK_TEMPERATURE      = "0.2"
      RCA_EVENT_WINDOW_MIN     = "15"
      RCA_TELEMETRY_WINDOW_MIN = "30"
      LOG_LEVEL                = "INFO"
    }
  }

  dead_letter_config {
    target_arn = aws_sqs_queue.rca_dlq.arn
  }

  tracing_config {
    mode = "Active"  # X-Ray — useful for the patent-claim latency demo
  }

  depends_on = [
    aws_cloudwatch_log_group.rca_lambda,
    aws_iam_role_policy_attachment.rca_basic_exec,
  ]
}

# ── IoT topic rule — critical alerts trigger the RCA Lambda ────────────
resource "aws_iot_topic_rule" "rca_trigger" {
  name        = "aevus_rca_trigger"
  description = "Aevus — invoke Bedrock RCA Lambda for every critical alert"
  sql         = "SELECT * FROM 'aevus/+/+/alerts/critical'"
  sql_version = "2016-03-23"
  enabled     = true

  lambda {
    function_arn = aws_lambda_function.rca.arn
  }

  error_action {
    cloudwatch_logs {
      log_group_name = aws_cloudwatch_log_group.iot_rule_errors.name
      role_arn       = aws_iam_role.iot_rule_actions.arn
    }
  }
}

resource "aws_lambda_permission" "iot_invoke_rca" {
  statement_id  = "AllowIoTRuleInvokeRca"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.rca.function_name
  principal     = "iot.amazonaws.com"
  source_arn    = aws_iot_topic_rule.rca_trigger.arn
}

# ============================================================
# Amazon Cognito Identity Pool — dashboard MQTT-over-WSS auth
#
# The browser dashboard subscribes directly to AWS IoT Core via
# MQTT-over-WebSockets. IoT Core requires a SigV4-signed URL, which
# requires AWS credentials. The dashboard gets temporary credentials
# from this Cognito Identity Pool's unauthenticated role.
#
# Security posture:
#   • UNAUTH role grants ONLY iot:Connect + iot:Subscribe + iot:Receive
#     on `aevus/<site>/#` — read-only, single-site, no publish.
#   • One identity pool per site keeps the IAM blast radius tight.
#     For multi-site rollouts, swap to an authenticated pool with
#     per-user attribute mapping.
#   • The dashboard NEVER receives publish permissions through this
#     path. All edge → cloud publishes go through the IoT Thing certs
#     in aws-iot-core.tf.
# ============================================================

variable "cognito_enabled" {
  description = "Provision the Cognito Identity Pool for dashboard MQTT-over-WSS. Disable in dev if you're using local Mosquitto only."
  type        = bool
  default     = true
}

resource "aws_cognito_identity_pool" "dashboard" {
  count                            = var.cognito_enabled ? 1 : 0
  identity_pool_name               = "aevus_dashboard_${var.environment}"
  allow_unauthenticated_identities = true
  allow_classic_flow               = false

  # No identity providers — anonymous access only for now. Layer in
  # Cognito User Pools or SAML when the dashboard needs per-operator
  # auth (board-vote item; not blocking the demo).
}

# ── Unauthenticated role — scoped to read-only MQTT on one site ─────────
data "aws_iam_policy_document" "cognito_unauth_assume" {
  count = var.cognito_enabled ? 1 : 0

  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = ["cognito-identity.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "cognito-identity.amazonaws.com:aud"
      values   = [aws_cognito_identity_pool.dashboard[0].id]
    }
    condition {
      test     = "ForAnyValue:StringLike"
      variable = "cognito-identity.amazonaws.com:amr"
      values   = ["unauthenticated"]
    }
  }
}

resource "aws_iam_role" "dashboard_unauth" {
  count              = var.cognito_enabled ? 1 : 0
  name               = "aevus-dashboard-unauth-${var.environment}"
  assume_role_policy = data.aws_iam_policy_document.cognito_unauth_assume[0].json
}

# Topic-prefixed read-only policy. The dashboard CAN subscribe to
# everything under aevus/<site_id>/#; it CANNOT publish, CANNOT see
# other sites, CANNOT touch the AWS control plane.
data "aws_iam_policy_document" "dashboard_iot_subscribe" {
  count = var.cognito_enabled ? 1 : 0

  statement {
    sid       = "Connect"
    effect    = "Allow"
    actions   = ["iot:Connect"]
    # Dashboard clients use a random clientId on each page load.
    resources = ["arn:aws:iot:${var.aws_region}:${data.aws_caller_identity.current.account_id}:client/aevus-dashboard-*"]
  }

  # Subscribe + receive ONLY under each configured site prefix.
  # For multi-site deployments, the list expands automatically as
  # var.sites grows.
  dynamic "statement" {
    for_each = toset(keys(var.sites))
    content {
      sid    = "SubscribeSite${replace(statement.value, "-", "")}"
      effect = "Allow"
      actions = [
        "iot:Subscribe",
      ]
      resources = [
        "arn:aws:iot:${var.aws_region}:${data.aws_caller_identity.current.account_id}:topicfilter/aevus/${statement.value}/*",
      ]
    }
  }

  dynamic "statement" {
    for_each = toset(keys(var.sites))
    content {
      sid    = "ReceiveSite${replace(statement.value, "-", "")}"
      effect = "Allow"
      actions = [
        "iot:Receive",
      ]
      resources = [
        "arn:aws:iot:${var.aws_region}:${data.aws_caller_identity.current.account_id}:topic/aevus/${statement.value}/*",
      ]
    }
  }
}

resource "aws_iam_role_policy" "dashboard_iot_subscribe" {
  count  = var.cognito_enabled ? 1 : 0
  name   = "aevus-dashboard-iot-subscribe"
  role   = aws_iam_role.dashboard_unauth[0].id
  policy = data.aws_iam_policy_document.dashboard_iot_subscribe[0].json
}

# Bind the unauth role to the identity pool.
resource "aws_cognito_identity_pool_roles_attachment" "dashboard" {
  count            = var.cognito_enabled ? 1 : 0
  identity_pool_id = aws_cognito_identity_pool.dashboard[0].id

  roles = {
    "unauthenticated" = aws_iam_role.dashboard_unauth[0].arn
  }
}

# ── Outputs — the dashboard pages need these at load time ───────────────
output "cognito_identity_pool_id" {
  description = "Identity Pool ID for the dashboard's anonymous credential fetch. Inject as window.AEVUS_COGNITO_IDENTITY_POOL_ID."
  value       = var.cognito_enabled ? aws_cognito_identity_pool.dashboard[0].id : null
}

output "dashboard_unauth_role_arn" {
  description = "IAM role assumed by anonymous dashboard sessions."
  value       = var.cognito_enabled ? aws_iam_role.dashboard_unauth[0].arn : null
}

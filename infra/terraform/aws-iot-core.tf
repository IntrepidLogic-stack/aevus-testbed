# ============================================================
# AWS IoT Core landing zone
#
# Per edge device, this provisions:
#   • IoT Thing (the cloud-side representation of the Pi)
#   • Greengrass Core Device association
#   • X.509 cert + key (downloaded to local for first-time install)
#   • IoT Policy — topic-prefixed least-privilege (a device can only
#     publish under aevus/<its-site>/<its-asset>/...)
#   • Thing group membership (for fleet-wide deployments)
#
# The Greengrass token-exchange role + audit S3 bucket are shared
# fleet-wide (defined in aws-audit.tf).
# ============================================================

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

# ── Thing Group — deployment target ─────────────────────────────────────
resource "aws_iot_thing_group" "edge_devices" {
  name = var.thing_group_name

  thing_group_properties {
    thing_group_description = "Aevus edge collectors (Greengrass cores)"
    attribute_payload {
      attributes = {
        product = "aevus"
        role    = "edge-collector"
      }
    }
  }
}

# ── Per-device Thing + cert + policy ────────────────────────────────────
resource "aws_iot_thing" "edge" {
  for_each = var.edge_devices
  name     = each.key

  attributes = {
    site_id     = each.value.site_id
    description = each.value.description
  }
}

resource "aws_iot_thing_group_membership" "edge_in_group" {
  for_each         = var.edge_devices
  thing_name       = aws_iot_thing.edge[each.key].name
  thing_group_name = aws_iot_thing_group.edge_devices.name
}

# X.509 keypair generated locally for first-time install. In production
# we'd use IoT Core fleet provisioning (the device gets its cert via a
# claim cert + provisioning template). Local cert generation is fine
# for the lab + first pilot.
resource "tls_private_key" "edge" {
  for_each  = var.edge_devices
  algorithm = "RSA"
  rsa_bits  = 2048
}

resource "tls_cert_request" "edge" {
  for_each        = var.edge_devices
  private_key_pem = tls_private_key.edge[each.key].private_key_pem

  subject {
    common_name  = each.key
    organization = "Intrepid Logic LLC"
  }
}

resource "aws_iot_certificate" "edge" {
  for_each          = var.edge_devices
  csr               = tls_cert_request.edge[each.key].cert_request_pem
  active            = true
}

resource "aws_iot_thing_principal_attachment" "edge" {
  for_each  = var.edge_devices
  thing     = aws_iot_thing.edge[each.key].name
  principal = aws_iot_certificate.edge[each.key].arn
}

# ── Per-device IoT policy — topic-prefixed least-privilege ──────────────
# A misbehaving device can ONLY publish under its own site_id prefix.
# This is the IAM model that makes the topic hierarchy safe in
# production. Without this, any compromised device could poison
# topics belonging to other sites.
data "aws_iam_policy_document" "edge_device_policy" {
  for_each = var.edge_devices

  # Connect to the broker as this client_id only.
  statement {
    sid       = "Connect"
    effect    = "Allow"
    actions   = ["iot:Connect"]
    resources = ["arn:aws:iot:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:client/${each.key}"]
  }

  # Publish only under this device's site prefix.
  statement {
    sid    = "Publish"
    effect = "Allow"
    actions = [
      "iot:Publish",
      "iot:Receive",
    ]
    resources = [
      "arn:aws:iot:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:topic/aevus/${each.value.site_id}/*",
    ]
  }

  # Subscribe only under this device's site prefix (for inbound
  # commands once we add a control path — currently unused).
  statement {
    sid       = "Subscribe"
    effect    = "Allow"
    actions   = ["iot:Subscribe"]
    resources = ["arn:aws:iot:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:topicfilter/aevus/${each.value.site_id}/*"]
  }

  # Greengrass token-exchange.
  statement {
    sid       = "AssumeRoleWithCert"
    effect    = "Allow"
    actions   = ["iot:AssumeRoleWithCertificate"]
    resources = [aws_iot_role_alias.greengrass_token_exchange.arn]
  }
}

resource "aws_iot_policy" "edge" {
  for_each = var.edge_devices
  name     = "aevus-edge-${each.key}"
  policy   = data.aws_iam_policy_document.edge_device_policy[each.key].json
}

resource "aws_iot_policy_attachment" "edge" {
  for_each = var.edge_devices
  policy   = aws_iot_policy.edge[each.key].name
  target   = aws_iot_certificate.edge[each.key].arn
}

# ── Greengrass token exchange role + alias ─────────────────────────────
# Allows the Pi's cert to assume a role that grants the components on
# the device permission to talk to AWS services (S3 artifact downloads,
# CloudWatch Logs, etc).
resource "aws_iam_role" "greengrass_token_exchange" {
  name = "AevusGreengrassV2TokenExchangeRole"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Service = "credentials.iot.amazonaws.com"
      }
      Action = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "greengrass_token_exchange" {
  name = "AevusGreengrassV2TokenExchangePolicy"
  role = aws_iam_role.greengrass_token_exchange.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents",
          "logs:DescribeLogStreams",
        ]
        Resource = "arn:aws:logs:*:*:*"
      },
      {
        Effect = "Allow"
        Action = [
          "s3:GetBucketLocation",
          "s3:GetObject",
        ]
        # Component artifacts bucket (defined in aws-audit.tf as
        # aws_s3_bucket.artifacts). Greengrass components fetch their
        # signed zip artifacts from here.
        Resource = [
          aws_s3_bucket.artifacts.arn,
          "${aws_s3_bucket.artifacts.arn}/*",
        ]
      },
    ]
  })
}

resource "aws_iot_role_alias" "greengrass_token_exchange" {
  alias    = "AevusGreengrassV2TokenExchangeRoleAlias"
  role_arn = aws_iam_role.greengrass_token_exchange.arn
}

# ── Local artifact: write the device cert + key to disk ─────────────────
# Used only on first apply. In production we'd push these into AWS
# Secrets Manager and have the Pi pull them via the AWS CLI, but for
# the lab we want them on disk so the Greengrass installer can
# consume them directly.
resource "local_sensitive_file" "device_cert" {
  for_each = var.edge_devices
  filename = "${path.module}/.secrets/${each.key}.cert.pem"
  content  = aws_iot_certificate.edge[each.key].certificate_pem
  file_permission = "0600"
}

resource "local_sensitive_file" "device_key" {
  for_each = var.edge_devices
  filename = "${path.module}/.secrets/${each.key}.key.pem"
  content  = tls_private_key.edge[each.key].private_key_pem
  file_permission = "0600"
}

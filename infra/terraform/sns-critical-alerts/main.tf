# ---------------------------------------------------------------------------
# Aevus critical alerts — SNS topic + subscribers
# Task #157 IaC capture of the alert delivery path.
#
# Captures the SNS topic + 2 email subscriptions that both the
# edge-mqtt-observability module (PR #61) and AWS-side alarms publish
# to. Already exists in AWS (created 2026-05-21 per Task #67); this
# module imports + becomes the canonical source.
#
# What this owns:
#   • SNS topic aevus-critical-alerts
#   • Subscription chiefegr@intrepidlogic.io
#   • Subscription woody@intrepidlogic.io
#
# What this does NOT own (still out-of-band, deferred):
#   • IoT thing aevus-edge-needville + cert + cert→thing attachment
#     (device-identity flow; needs careful import to not break the Pi's
#     active session — schedule a maintenance window for that one)
#   • S3 bucket aevus-telemetry-archive-676433090238 + lifecycle rules
#     (has live production data; tf import needs explicit verification
#     of object lock / lifecycle / versioning before adopting)
#   • 6 IoT topic rules: aevus_latest_state_to_ddb, aevus_state_to_ddb,
#     aevus_critical_to_sns, aevus_critical_to_rca, aevus_archive_all
#     (aevus_edge_mqtt_health is already in edge-mqtt-observability)
#   • Bedrock RCA Lambda function aevus-rca (source restored in PR #59
#     under infra/lambda/rca/, but aws_lambda_function resource itself
#     still bare AWS — needs the deploy zip + IAM role wired)
#
# Cost: $0 (SNS standard topic + 2 subs).
# Apply:
#   cd infra/terraform/sns-critical-alerts
#   terraform init
#   # IMPORT BLOCK — see IMPORT.md
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
  type    = string
  default = "us-east-1"
}

variable "subscriber_emails" {
  type        = list(string)
  default     = ["chiefegr@intrepidlogic.io", "woody@intrepidlogic.io"]
  description = "Email subscribers. Add Lynn first (chiefegr@), then Woody. Per global memory note 2026-05-26: lynn@intrepidlogic.io does NOT route to Lynn — use chiefegr@."
}

resource "aws_sns_topic" "critical_alerts" {
  name = "aevus-critical-alerts"

  # Display name is what subscribers see in the email's From field.
  # "Aevus Notifications" is what's currently live; keep it stable.
  display_name = "Aevus Notifications"
}

resource "aws_sns_topic_subscription" "emails" {
  for_each = toset(var.subscriber_emails)

  topic_arn = aws_sns_topic.critical_alerts.arn
  protocol  = "email"
  endpoint  = each.value

  # Email subscriptions require manual confirmation via the link in the
  # confirmation email. If terraform import succeeds, the subscription
  # is already confirmed (PendingConfirmation subs don't show up in the
  # list_subscriptions output the same way).
}

output "topic_arn" {
  value       = aws_sns_topic.critical_alerts.arn
  description = "ARN to wire into CloudWatch alarms + IoT rule SNS actions."
}

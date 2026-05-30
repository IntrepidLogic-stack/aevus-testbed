# Import existing resources — first apply

All four resources in this module were created via AWS CLI on 2026-05-30. To
take ownership without recreating them, import them into state before the
first `terraform apply`.

```bash
cd infra/terraform/edge-mqtt-observability
terraform init

# 1. IoT policy (only the latest version v3 is the default; the policy
#    name itself is what we import)
terraform import aws_iot_policy.edge_publish aevus-edge-publish

# 2. Ghost-detection CloudWatch alarm
terraform import aws_cloudwatch_metric_alarm.iot_ghost_connect_rejected \
  aevus-iot-ghost-connect-rejected

# 3a. IAM role + 3b. inline policy
terraform import aws_iam_role.iot_cloudwatch_metric \
  aevus-iot-cloudwatch-metric-role
terraform import aws_iam_role_policy.iot_cloudwatch_metric \
  aevus-iot-cloudwatch-metric-role:allow-cw-put-aevus-edge

# 3c. IoT topic rule
terraform import aws_iot_topic_rule.edge_mqtt_health \
  aevus_edge_mqtt_health

# 3d. CloudWatch log group for rule's errorAction
terraform import aws_cloudwatch_log_group.rule_errors \
  /aws/iot/aevus_edge_mqtt_health_errors

# 3e. Second inline policy on the IoT role (allow-error-logs)
terraform import aws_iam_role_policy.iot_error_logs \
  aevus-iot-cloudwatch-metric-role:allow-error-logs

# 4. Publish-failures CloudWatch alarm
terraform import aws_cloudwatch_metric_alarm.edge_mqtt_publish_failures \
  aevus-edge-mqtt-publish-failures

# Verify everything imported; expect NO changes on the plan
terraform plan
```

If `terraform plan` shows changes after import, that's drift between this
module's source and what's live. Most common cause: AWS adds default tags
or audit fields that aren't worth modeling. Use `lifecycle.ignore_changes`
on those specific attributes rather than rewriting the module to match.

## Backend

This module uses local state by default (intentional — three of the four
resources are observability primitives that we'd rather lose state on than
risk corrupting). When the rest of the Aevus AWS stack moves to a shared S3
backend, migrate this module too.

## Adding a second site

Today there's one variable: `site_id = "needville"`. To onboard a second
edge (e.g. `katy`), copy this entire module to a sibling directory with
`site_id = "katy"`. Don't try to make it a for_each over sites — the IoT
policy name is account-global and we want one cert+policy per site for
blast-radius isolation.

output "iot_endpoint" {
  description = "AWS IoT Core MQTT endpoint — set this as MQTT_BROKER_HOST in the edge's .env"
  value       = data.aws_iot_endpoint.iot.endpoint_address
}

output "iot_endpoint_port" {
  description = "MQTT-over-TLS port for IoT Core"
  value       = 8883
}

output "amazon_root_ca_url" {
  description = "Download the Amazon Root CA cert for the edge: curl -o AmazonRootCA1.pem https://www.amazontrust.com/repository/AmazonRootCA1.pem"
  value       = "https://www.amazontrust.com/repository/AmazonRootCA1.pem"
}

output "edge_certs_path" {
  description = "Local filesystem path where the per-device certs + keys were written. Push these to the corresponding Pi via scp + set MQTT_CLIENT_CERT_PATH / MQTT_CLIENT_KEY_PATH in .env."
  value       = "${path.module}/.secrets/"
}

output "audit_bucket" {
  description = "S3 audit bucket — all events and alarms land here under Object Lock"
  value       = aws_s3_bucket.audit.id
}

output "artifacts_bucket" {
  description = "S3 artifacts bucket — Greengrass component zips go here"
  value       = aws_s3_bucket.artifacts.id
}

output "kms_key_arn" {
  description = "Aevus KMS key — encrypts buckets and CloudTrail"
  value       = aws_kms_key.aevus.arn
}

output "thing_group_arn" {
  description = "IoT Thing Group for Greengrass deployments"
  value       = aws_iot_thing_group.edge_devices.arn
}

output "sitewise_cabinet_assets" {
  description = "SiteWise Cabinet asset IDs per site"
  value = var.sitewise_enabled ? {
    for site_id, _ in var.sites :
    site_id => aws_iotsitewise_asset.cabinet[site_id].id
  } : {}
}

# Helper to fetch the regional IoT endpoint.
data "aws_iot_endpoint" "iot" {
  endpoint_type = "iot:Data-ATS"
}

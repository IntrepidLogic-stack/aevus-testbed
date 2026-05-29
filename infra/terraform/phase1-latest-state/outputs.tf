output "table_name" {
  description = "DynamoDB latest-state table name."
  value       = aws_dynamodb_table.latest_state.name
}

output "table_arn" {
  value = aws_dynamodb_table.latest_state.arn
}

output "topic_rule_name" {
  value = aws_iot_topic_rule.latest_state.name
}

output "verify_hint" {
  description = "How to confirm data is landing after apply."
  value       = "aws dynamodb scan --table-name ${aws_dynamodb_table.latest_state.name} --max-items 5 --region ${var.aws_region}"
}

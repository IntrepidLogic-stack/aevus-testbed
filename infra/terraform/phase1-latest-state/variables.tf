variable "aws_region" {
  description = "AWS region — must match the live IoT Core landing zone."
  type        = string
  default     = "us-east-1"
}

variable "table_name" {
  description = "DynamoDB latest-state table name."
  type        = string
  default     = "aevus-latest-state"
}

variable "enable_ttl" {
  description = "Enable DynamoDB TTL on expires_at (lets long-dark points self-expire). Off by default — latest-state should persist."
  type        = bool
  default     = false
}

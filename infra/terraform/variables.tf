# ── Core ────────────────────────────────────────────────────────────────
variable "aws_region" {
  description = "Primary AWS region. us-east-2 (Ohio) recommended for Texas latency; us-west-2 (Oregon) recommended for Bedrock model availability."
  type        = string
  default     = "us-east-2"
}

variable "environment" {
  description = "Deployment environment: dev | staging | prod"
  type        = string
  default     = "dev"

  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "environment must be dev, staging, or prod."
  }
}

# ── Sites + edge devices ────────────────────────────────────────────────
variable "sites" {
  description = "Map of site_id → human-readable description. The site_id appears in MQTT topic prefixes (aevus/<site_id>/...) and is the IAM blast radius for each edge device."
  type        = map(string)
  default = {
    lab = "Intrepid Logic Lab Cabinet"
  }
}

variable "edge_devices" {
  description = "Edge devices to register as Greengrass Core Devices + IoT Things. Each entry binds the device to a single site for IAM."
  type = map(object({
    site_id     = string
    description = string
  }))
  default = {
    "aevus-edge-lab-01" = {
      site_id     = "lab"
      description = "Raspberry Pi edge collector — lab cabinet"
    }
  }
}

variable "thing_group_name" {
  description = "IoT Thing Group that all edge devices join — deployment target."
  type        = string
  default     = "AevusEdgeDevices"
}

# ── SiteWise asset hierarchy ────────────────────────────────────────────
variable "sitewise_enabled" {
  description = "Provision the SiteWise asset model + assets. Disable in dev if SiteWise cost matters more than fidelity."
  type        = bool
  default     = true
}

# ── Bedrock RCA ─────────────────────────────────────────────────────────
variable "bedrock_model_id" {
  description = "Bedrock foundation model for the RCA Lambda. Claude Sonnet by default — switch to Haiku for lower latency / cost, Opus for deeper reasoning. Verify model availability in your region before changing."
  type        = string
  default     = "anthropic.claude-sonnet-4-20250514-v1:0"
}

# ── Audit / compliance ──────────────────────────────────────────────────
variable "audit_retention_days" {
  description = "S3 Object Lock retention for the audit bucket. 2555 days (~7 years) matches typical NIST / IEC 62443 retention expectations."
  type        = number
  default     = 2555
}

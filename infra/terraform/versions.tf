# ============================================================
# Aevus AWS landing zone — Terraform configuration
# Aligns with the IL deployment playbook (memory).
# ============================================================

terraform {
  required_version = ">= 1.7"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.70"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.0"
    }
    local = {
      source  = "hashicorp/local"
      version = "~> 2.5"
    }
  }

  # Remote state — uncomment when the team-shared S3 backend exists.
  # backend "s3" {
  #   bucket         = "il-terraform-state"
  #   key            = "aevus/aws-landing-zone/terraform.tfstate"
  #   region         = "us-east-2"
  #   dynamodb_table = "il-terraform-locks"
  #   encrypt        = true
  # }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      product     = "aevus"
      env         = var.environment
      cost-center = "aevus"
      managed-by  = "terraform"
      repo        = "aevus-testbed"
    }
  }
}

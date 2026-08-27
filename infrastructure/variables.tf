variable "project_name" {
  description = "Short name used for AWS resource naming and tagging."
  type        = string
  default     = "production-data-platform"

  validation {
    condition     = can(regex("^[a-z0-9-]{3,32}$", var.project_name))
    error_message = "project_name must contain 3 to 32 lowercase letters, numbers, or hyphens."
  }
}

variable "environment" {
  description = "Deployment environment name."
  type        = string
  default     = "dev"

  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "environment must be dev, staging, or prod."
  }
}

variable "aws_region" {
  description = "AWS region for the data platform."
  type        = string
  default     = "us-east-1"
}

variable "vpc_cidr" {
  description = "CIDR block for the isolated data-platform VPC."
  type        = string
  default     = "10.42.0.0/16"

  validation {
    condition     = can(cidrnetmask(var.vpc_cidr))
    error_message = "vpc_cidr must be a valid IPv4 CIDR block."
  }
}

variable "private_subnet_cidrs" {
  description = "Two private subnet CIDRs in separate availability zones."
  type        = list(string)
  default     = ["10.42.10.0/24", "10.42.20.0/24"]

  validation {
    condition = length(var.private_subnet_cidrs) == 2 && alltrue([
      for cidr in var.private_subnet_cidrs : can(cidrnetmask(cidr))
    ])
    error_message = "private_subnet_cidrs must contain exactly two valid CIDR blocks."
  }
}

variable "database_client_security_group_ids" {
  description = "Security groups allowed to connect to PostgreSQL. Empty keeps the database isolated."
  type        = set(string)
  default     = []
}

variable "database_instance_class" {
  description = "RDS instance class. The default is intentionally small for development."
  type        = string
  default     = "db.t4g.micro"
}

variable "database_multi_az" {
  description = "Whether RDS should maintain a synchronous standby in another AZ."
  type        = bool
  default     = false
}

variable "protect_database" {
  description = "Enable RDS deletion protection and require a final snapshot."
  type        = bool
  default     = true
}

variable "force_destroy_buckets" {
  description = "Allow Terraform to delete non-empty data buckets. Keep false outside ephemeral tests."
  type        = bool
  default     = false
}

variable "object_retention_days" {
  description = "Days before current S3 objects expire."
  type        = number
  default     = 365

  validation {
    condition     = var.object_retention_days >= 90
    error_message = "object_retention_days must be at least 90."
  }
}

variable "enable_interface_endpoints" {
  description = "Create private KMS, Secrets Manager, and CloudWatch Logs endpoints for workers."
  type        = bool
  default     = false
}

variable "alarm_topic_arn" {
  description = "Optional SNS topic ARN for CloudWatch alarm notifications."
  type        = string
  default     = null
  nullable    = true
}

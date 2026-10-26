variable "region" {
  type    = string
  default = "ap-southeast-2"
}
variable "name" {
  type    = string
  default = "stocklane-prod"
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,25}$", var.name))
    error_message = "Use 3-26 lowercase letters, digits and hyphens."
  }
}
variable "github_repository" {
  type        = string
  description = "owner/repository for the protected aws-release GitHub environment"
  validation {
    condition     = can(regex("^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", var.github_repository))
    error_message = "Use owner/repository."
  }
}
variable "github_oidc_provider_arn" {
  type        = string
  default     = ""
  description = "Reuse an existing account-wide GitHub OIDC provider when present."
}
variable "administrator_arn" {
  type        = string
  description = "Existing IAM operator role/user given EKS access. Never use the root user."
}
variable "operator_cidrs" {
  type        = list(string)
  description = "Public CIDRs allowed to reach the EKS management endpoint; use your current IP/32."
  validation {
    condition     = length(var.operator_cidrs) > 0 && alltrue([for x in var.operator_cidrs : can(cidrhost(x, 0)) && !contains(["0.0.0.0/0", "::/0"], x)])
    error_message = "Specify restricted operator CIDRs, never the entire internet."
  }
}
variable "api_domain" {
  type        = string
  description = "Owned hostname such as api.stocklane.example.com."
}
variable "route53_zone_id" {
  type        = string
  description = "Hosted zone for API certificate validation and the ALB alias."
}
variable "eks_version" {
  type    = string
  default = "1.35"
}
variable "node_instance_type" {
  type    = string
  default = "m6i.large"
}
variable "database_instance_class" {
  type    = string
  default = "db.t4g.small"
}
variable "database_multi_az" {
  type    = bool
  default = true
}
variable "database_storage_type" {
  type    = string
  default = "gp3"
  validation {
    condition     = contains(["gp2", "gp3"], var.database_storage_type)
    error_message = "Use gp2 or gp3 storage."
  }
}
variable "database_max_allocated_storage" {
  type        = number
  default     = 40
  description = "Storage autoscaling limit in GiB; zero disables autoscaling for the 20 GiB demo database."
  validation {
    condition     = var.database_max_allocated_storage == 0 || (var.database_max_allocated_storage >= 20 && floor(var.database_max_allocated_storage) == var.database_max_allocated_storage)
    error_message = "Use zero to disable autoscaling, or a whole number of GiB of at least 20."
  }
}
variable "database_backup_retention_days" {
  type        = number
  default     = null
  description = "Automated backup retention: defaults to one day for dev/test/UAT and 14 for production. Account plan restrictions still apply."
  validation {
    condition     = var.database_backup_retention_days == null ? true : (var.database_backup_retention_days >= 1 && var.database_backup_retention_days <= 35 && floor(var.database_backup_retention_days) == var.database_backup_retention_days)
    error_message = "Use a whole number of days from 1 to 35; automated backups must stay enabled."
  }
}
variable "deletion_protection" {
  type    = bool
  default = true
}
variable "bedrock_model_arn" {
  type        = string
  default     = ""
  description = "Regional vision-capable model ARN. Empty disables model invocation permissions."
}
variable "monthly_budget_usd" {
  type    = number
  default = 25
}
variable "budget_email" {
  type        = string
  description = "Owner email for budget notifications."
}
variable "environment" {
  type    = string
  default = "production"
  validation {
    condition     = contains(["dev", "test", "uat", "production"], var.environment)
    error_message = "Use dev, test, uat or production to match the Kustomize overlays."
  }
}
variable "availability_zone_count" {
  type    = number
  default = 3
  validation {
    condition     = contains([2, 3], var.availability_zone_count)
    error_message = "Use two or three availability zones."
  }
}
variable "nat_per_az" {
  type    = bool
  default = true
}
variable "node_min_size" {
  type    = number
  default = 3
}
variable "node_desired_size" {
  type    = number
  default = 3
}
variable "node_max_size" {
  type    = number
  default = 6
}
variable "cache_node_type" {
  type    = string
  default = "cache.t4g.small"
}
variable "cache_node_count" {
  type    = number
  default = 2
  validation {
    condition     = var.cache_node_count >= 2 && var.cache_node_count <= 3
    error_message = "Use a primary plus at least one replica, across at most three zones."
  }
}
variable "application_replicas" {
  type    = number
  default = 3
}

variable "service_ipv4_cidr" {
  description = "EKS Service CIDR. Immutable after cluster creation; keep the existing cluster value."
  type        = string
  default     = "172.20.0.0/16"
  validation {
    condition     = can(cidrnetmask(var.service_ipv4_cidr))
    error_message = "service_ipv4_cidr must be a valid IPv4 CIDR."
  }
}

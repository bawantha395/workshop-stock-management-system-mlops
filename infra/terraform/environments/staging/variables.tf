# Inputs come from two places:
#   terraform.tfvars          sizes and protection for this environment (committed)
#   pipeline.auto.tfvars.json account-specific values from the TFVARS_JSON
#                             GitHub secret, plus identity values the pipeline
#                             fills in (written at run time, never committed)

# ---------- Identity of this environment ----------
variable "region" {
  type    = string
  default = "ap-southeast-2"
}

variable "name" {
  type        = string
  description = "Resource name prefix: stocklane-<environment>."
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,25}$", var.name))
    error_message = "Use 3-26 lowercase letters, digits and hyphens."
  }
}

variable "environment" {
  type = string
  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "Use dev, staging or prod."
  }
}

# ---------- Access ----------
variable "administrator_arn" {
  type        = string
  description = "IAM operator role or user given EKS cluster-admin. Never the root user."
}

variable "operator_cidrs" {
  type        = list(string)
  description = "Public CIDRs allowed to reach the EKS API, for example your IP/32."
}

variable "admin_allowed_cidrs" {
  type        = list(string)
  default     = []
  description = "Public IPv4 ranges allowed to open the Argo CD and Grafana dashboards."
}

# ---------- Domains ----------
variable "route53_zone_id" {
  type        = string
  description = "Existing public hosted zone (kept between deploys)."
}

variable "api_domain" {
  type = string
}

variable "web_domain" {
  type    = string
  default = ""
}

variable "argocd_domain" {
  type    = string
  default = ""
}

variable "grafana_domain" {
  type    = string
  default = ""
}

# ---------- Size and protection (set per environment in terraform.tfvars) ----------
variable "deletion_protection" {
  type        = bool
  description = "true for prod. false lets dev/staging be destroyed in one run: no final DB snapshot, buckets and images emptied, secrets deleted immediately."
}

variable "availability_zone_count" {
  type = number
  validation {
    condition     = contains([2, 3], var.availability_zone_count)
    error_message = "Use two or three availability zones."
  }
}

variable "nat_per_az" {
  type = bool
}

variable "eks_version" {
  type    = string
  default = "1.35"
}

variable "service_ipv4_cidr" {
  type    = string
  default = "172.20.0.0/16"
}

variable "node_instance_type" {
  type = string
}

variable "node_min_size" {
  type = number
}

variable "node_desired_size" {
  type = number
}

variable "node_max_size" {
  type = number
}

variable "application_replicas" {
  type = number
}

variable "database_instance_class" {
  type = string
}

variable "database_multi_az" {
  type = bool
}

variable "database_storage_type" {
  type = string
}

variable "database_max_allocated_storage" {
  type = number
}

variable "database_backup_retention_days" {
  type = number
}

variable "cache_node_type" {
  type = string
}

variable "cache_node_count" {
  type = number
}

# ---------- Alerts and cost ----------
variable "budget_email" {
  type        = string
  description = "Receives alarms, root-cause reports and budget warnings."
}

variable "monthly_budget_usd" {
  type    = number
  default = 25
}

variable "alarm_rca_cooldown_hours" {
  type    = number
  default = 6
}

variable "alarm_rca_daily_cap" {
  type    = number
  default = 10
}

variable "application_error_threshold" {
  type    = number
  default = 20
}

# ---------- AI ----------
variable "bedrock_model_id" {
  type    = string
  default = ""
}

variable "bedrock_model_arn" {
  type    = string
  default = ""
}

variable "bedrock_region" {
  type    = string
  default = ""
}

variable "bedrock_daily_request_limit" {
  type    = number
  default = 50
  validation {
    condition     = var.bedrock_daily_request_limit >= 1 && var.bedrock_daily_request_limit <= 1000 && floor(var.bedrock_daily_request_limit) == var.bedrock_daily_request_limit
    error_message = "Set a whole number between 1 and 1000."
  }
}

# ---------- GitHub delivery (filled in by the pipeline) ----------
variable "github_repository" {
  type        = string
  description = "owner/repository allowed to deploy this environment."
  validation {
    condition     = can(regex("^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", var.github_repository))
    error_message = "Use owner/repository."
  }
}

variable "github_auth_mode" {
  type    = string
  default = "oidc"
  validation {
    condition     = contains(["oidc", "access-key"], var.github_auth_mode)
    error_message = "github_auth_mode must be oidc or access-key."
  }
  validation {
    condition     = var.github_auth_mode != "access-key" || var.github_ci_user_arn != null
    error_message = "Access-key mode requires the bootstrap-owned CI user ARN."
  }
}

variable "github_ci_user_arn" {
  type    = string
  default = null
  validation {
    condition     = var.github_ci_user_arn == null || can(regex("^arn:aws:iam::[0-9]{12}:user/[A-Za-z0-9+=,.@_/-]+$", var.github_ci_user_arn))
    error_message = "github_ci_user_arn must be an IAM user ARN."
  }
}

variable "github_oidc_provider_arn" {
  type        = string
  default     = ""
  description = "Reuse an existing account-wide GitHub OIDC provider when present."
}

variable "github_owner_id" {
  type    = string
  default = null
  validation {
    condition     = var.github_owner_id == null || can(regex("^[1-9][0-9]*$", var.github_owner_id))
    error_message = "github_owner_id must be the numeric GitHub owner ID."
  }
}

variable "github_repository_id" {
  type    = string
  default = null
  validation {
    condition     = var.github_repository_id == null || can(regex("^[1-9][0-9]*$", var.github_repository_id))
    error_message = "github_repository_id must be the numeric GitHub repository ID."
  }
}

variable "github_oidc_subject_style" {
  type    = string
  default = "immutable"
  validation {
    condition     = contains(["immutable", "legacy"], var.github_oidc_subject_style)
    error_message = "Use immutable for new GitHub repositories, or legacy only when the repository uses legacy subjects."
  }
  validation {
    condition     = var.github_oidc_subject_style == "legacy" || (var.github_owner_id != null && var.github_repository_id != null)
    error_message = "Immutable subjects require github_owner_id and github_repository_id. The pipeline supplies both automatically."
  }
}

variable "workload_permissions_boundary_arn" {
  type        = string
  default     = null
  description = "Maximum permissions for every role this stack creates (from the bootstrap stack)."
}

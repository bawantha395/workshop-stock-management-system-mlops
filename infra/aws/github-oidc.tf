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
variable "workload_permissions_boundary_arn" {
  type        = string
  default     = null
  description = "Pipeline-owned maximum permissions boundary for all workload roles."
}
# GitHub's immutable repository subjects include owner and repository IDs.
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
locals {
  github_oidc_repository  = var.github_oidc_subject_style == "legacy" ? var.github_repository : "${split("/", var.github_repository)[0]}@${coalesce(var.github_owner_id, "MISSING")}/${split("/", var.github_repository)[1]}@${coalesce(var.github_repository_id, "MISSING")}"
  github_release_subject  = "repo:${local.github_oidc_repository}:environment:aws-release"
  github_training_subject = "repo:${local.github_oidc_repository}:environment:aws-training"
  github_platform_subject = "repo:${local.github_oidc_repository}:environment:aws-platform"
}


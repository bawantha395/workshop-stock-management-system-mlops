variable "name" {
  type = string
}

variable "environment" {
  type = string
}

variable "region" {
  type = string
}

variable "account_id" {
  type = string
}

variable "partition" {
  type = string
}

variable "permissions_boundary_arn" {
  type    = string
  default = null
}

variable "force_destroy" {
  type        = bool
  description = "Allow the automation bucket to be deleted while it has objects (dev/staging)."
}

# ---------- GitHub identity ----------
variable "github_repository" {
  type = string
}

variable "github_auth_mode" {
  type = string
}

variable "github_ci_user_arn" {
  type    = string
  default = null
}

variable "github_oidc_provider_arn" {
  type    = string
  default = ""
}

variable "github_oidc_subject_style" {
  type = string
}

variable "github_owner_id" {
  type    = string
  default = null
}

variable "github_repository_id" {
  type    = string
  default = null
}

# ---------- Resources the roles may use ----------
variable "kms_key_arn" {
  type = string
}

variable "ecr_repository_arns" {
  type = list(string)
}

variable "web_bucket_arn" {
  type = string
}

variable "models_bucket_arn" {
  type = string
}

variable "cloudfront_distribution_arn" {
  type = string
}

variable "vision_model_group" {
  type = object({ name = string, arn = string })
}

variable "training_role_arn" {
  type = string
}

# ---------- Platform bootstrap runner ----------
variable "vpc_id" {
  type = string
}

variable "private_subnet_ids" {
  type = list(string)
}

variable "private_subnet_arns" {
  type = list(string)
}

variable "cluster_name" {
  type = string
}

variable "cluster_arn" {
  type = string
}

variable "cluster_security_group_id" {
  type = string
}

variable "route53_zone_id" {
  type = string
}

variable "alias_domains" {
  type        = list(string)
  description = "Hostnames the bootstrap may point at the ingress load balancer (A records only)."
}

variable "platform_buildspec" {
  type        = string
  description = "Contents of deploy/codebuild/platform-bootstrap.yml."
}

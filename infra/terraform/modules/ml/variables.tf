variable "name" {
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

variable "models_bucket_arn" {
  type = string
}

variable "training_repository_arn" {
  type        = string
  description = "ECR repository of the ml-training image."
}

variable "kms_key_arn" {
  type = string
}

variable "bedrock_model_id" {
  type        = string
  default     = ""
  description = "Foundation model ID such as amazon.nova-lite-v1:0. Empty disables AI suggestions."
  validation {
    condition     = var.bedrock_model_id == "" || can(regex("^[a-z0-9.-]+:[0-9]+$", var.bedrock_model_id))
    error_message = "Use a foundation model ID; cross-region inference profiles are not enabled by this policy."
  }
}

variable "bedrock_model_arn" {
  type        = string
  default     = ""
  description = "Alternative to bedrock_model_id: a full model ARN."
}

variable "bedrock_region" {
  type        = string
  default     = ""
  description = "Region for Bedrock calls, for example us-east-1. Empty uses var.region."
  validation {
    condition     = var.bedrock_region == "" || can(regex("^[a-z]{2}(-gov)?-[a-z]+-[0-9]$", var.bedrock_region))
    error_message = "Use an AWS Region code such as us-east-1, or leave empty."
  }
}

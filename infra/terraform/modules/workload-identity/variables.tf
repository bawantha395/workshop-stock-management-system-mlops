variable "name" {
  type = string
}

variable "permissions_boundary_arn" {
  type    = string
  default = null
}

variable "cluster_name" {
  type = string
}

variable "workload_namespace" {
  type        = string
  description = "Kubernetes namespace of the Stocklane services, for example stocklane-dev."
}

variable "kms_key_arn" {
  type = string
}

variable "buckets" {
  type = map(object({ id = string, arn = string, regional_domain_name = string }))
}

variable "queues" {
  type = object({
    events = map(object({ name = string, arn = string, url = string }))
    dead   = map(object({ name = string, arn = string }))
  })
}

variable "database_secret_arns" {
  type = map(string)
}

variable "database_master_secret_arn" {
  type    = string
  default = null
}

variable "platform_secret_arn" {
  type = string
}

variable "grafana_secret_arn" {
  type = string
}

variable "application_log_group_arn" {
  type = string
}

variable "operations_topic_arn" {
  type = string
}

variable "alerts_kms_key_arn" {
  type = string
}

variable "bedrock_invoke_arn" {
  type        = string
  description = "Foundation model the vision service may call; empty disables AI suggestions."
}

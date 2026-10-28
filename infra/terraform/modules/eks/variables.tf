variable "name" {
  type = string
}

variable "partition" {
  type = string
}

variable "permissions_boundary_arn" {
  type    = string
  default = null
}

variable "eks_version" {
  type = string
}

variable "service_ipv4_cidr" {
  type        = string
  description = "Kubernetes Service CIDR; fixed once the cluster exists."
  validation {
    condition     = can(cidrnetmask(var.service_ipv4_cidr))
    error_message = "service_ipv4_cidr must be a valid IPv4 CIDR."
  }
}

variable "private_subnet_ids" {
  type = list(string)
}

variable "operator_cidrs" {
  type        = list(string)
  description = "Public CIDRs allowed to reach the Kubernetes API."
  validation {
    condition     = length(var.operator_cidrs) > 0 && alltrue([for x in var.operator_cidrs : can(cidrhost(x, 0)) && !contains(["0.0.0.0/0", "::/0"], x)])
    error_message = "Specify restricted operator CIDRs, never the entire internet."
  }
}

variable "administrator_arn" {
  type        = string
  description = "IAM role or user that gets cluster-admin. Never the root user."
}

variable "kms_key_arn" {
  type = string
}

variable "data_security_group_id" {
  type = string
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

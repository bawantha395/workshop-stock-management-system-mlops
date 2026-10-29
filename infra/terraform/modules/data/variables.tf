variable "name" {
  type = string
}

variable "account_id" {
  type = string
}

variable "availability_zones" {
  type = list(string)
}

variable "private_subnet_ids" {
  type = list(string)
}

variable "data_security_group_id" {
  type = string
}

variable "protect_data" {
  type        = bool
  description = "Deletion protection and final snapshots for prod; false makes dev/staging easy to destroy."
}

variable "demo_admin_credentials" {
  type        = bool
  default     = false
  description = "Use the simple password \"admin\" for Grafana (dev/staging demos only; keep false for prod)."
}

variable "database_instance_class" {
  type = string
}

variable "database_multi_az" {
  type = bool
}

variable "database_storage_type" {
  type = string
  validation {
    condition     = contains(["gp2", "gp3"], var.database_storage_type)
    error_message = "Use gp2 or gp3 storage."
  }
}

variable "database_max_allocated_storage" {
  type        = number
  description = "Storage autoscaling limit in GiB; 0 disables autoscaling."
  validation {
    condition     = var.database_max_allocated_storage == 0 || (var.database_max_allocated_storage >= 20 && floor(var.database_max_allocated_storage) == var.database_max_allocated_storage)
    error_message = "Use 0, or a whole number of GiB of at least 20."
  }
}

variable "database_backup_retention_days" {
  type = number
  validation {
    condition     = var.database_backup_retention_days >= 1 && var.database_backup_retention_days <= 35 && floor(var.database_backup_retention_days) == var.database_backup_retention_days
    error_message = "Use 1-35 days; automated backups stay enabled."
  }
}

variable "cache_node_type" {
  type = string
}

variable "cache_node_count" {
  type = number
  validation {
    condition     = var.cache_node_count >= 2 && var.cache_node_count <= 3
    error_message = "Use a primary plus at least one replica, across at most three zones."
  }
}

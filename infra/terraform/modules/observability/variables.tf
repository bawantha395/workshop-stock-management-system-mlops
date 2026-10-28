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

variable "alert_email" {
  type        = string
  description = "Receives alarm emails, root-cause reports and budget warnings."
}

variable "monthly_budget_usd" {
  type = number
}

variable "event_queue_names" {
  type        = map(string)
  description = "Queue name per key; an alarm fires when the oldest message is over 2 minutes old."
}

variable "dead_letter_queue_names" {
  type        = map(string)
  description = "Dead-letter queue name per key; an alarm fires on any message."
}

variable "key_deletion_window_days" {
  type    = number
  default = 30
}

variable "alarm_rca_cooldown_hours" {
  type        = number
  default     = 6
  description = "One root-cause report per alarm within this window; repeats are only counted."
}

variable "alarm_rca_daily_cap" {
  type        = number
  default     = 10
  description = "Maximum root-cause reports per UTC day across all alarms."
}

variable "application_error_threshold" {
  type        = number
  default     = 20
  description = "Container error lines per 5 minutes that raise the application-errors alarm."
}

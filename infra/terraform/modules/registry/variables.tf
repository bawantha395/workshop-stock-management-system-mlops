variable "name" {
  type = string
}

variable "kms_key_arn" {
  type = string
}

variable "repositories" {
  type    = list(string)
  default = ["inventory", "workshop", "vision", "forecast", "operations", "ml-training"]
}

variable "force_delete" {
  type        = bool
  description = "Allow destroy while images exist (dev/staging)."
}

variable "name" {
  type = string
}

variable "account_id" {
  type = string
}

variable "owner_email" {
  type        = string
  default     = ""
  description = "Creates this user in the OWNER group and emails an invitation. Empty creates nobody."
}

variable "app_urls" {
  type        = list(string)
  description = "HTTPS base URLs of the web app; each gets /auth/callback as a sign-in redirect."
}

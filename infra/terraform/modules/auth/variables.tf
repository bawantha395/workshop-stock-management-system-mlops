variable "name" {
  type = string
}

variable "account_id" {
  type = string
}

variable "app_urls" {
  type        = list(string)
  description = "HTTPS base URLs of the web app; each gets /auth/callback as a sign-in redirect."
}

variable "name" {
  type = string
}

variable "route53_zone_id" {
  type        = string
  description = "Existing public hosted zone that owns the domains below."
}

variable "web_bucket" {
  type = object({ id = string, arn = string, regional_domain_name = string })
}

variable "web_domain" {
  type        = string
  default     = ""
  description = "Custom hostname for the React app; empty uses the CloudFront domain."
}

variable "api_domain" {
  type        = string
  description = "Hostname of the API load balancer, for example api.stocklane.example.com."
}

variable "argocd_domain" {
  type    = string
  default = ""
}

variable "grafana_domain" {
  type    = string
  default = ""
}

variable "admin_allowed_cidrs" {
  type        = list(string)
  default     = []
  description = "Public IPv4 ranges allowed to reach the admin dashboards (/24 or narrower)."
  validation {
    condition     = alltrue([for cidr in var.admin_allowed_cidrs : can(cidrnetmask(cidr)) && try(tonumber(split("/", cidr)[1]) >= 24, false)])
    error_message = "Use valid IPv4 ranges /24 or narrower; do not expose admin dashboards to the whole Internet."
  }
}

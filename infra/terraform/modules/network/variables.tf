variable "name" {
  type        = string
  description = "Resource name prefix, for example stocklane-dev."
}

variable "region" {
  type = string
}

variable "availability_zones" {
  type        = list(string)
  description = "Two or three AZs; one public and one private subnet is created in each."
}

variable "nat_per_az" {
  type        = bool
  description = "true = one NAT gateway per AZ (highly available); false = one shared NAT (cheaper)."
}

variable "cidr_block" {
  type    = string
  default = "10.42.0.0/16"
}

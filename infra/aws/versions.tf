terraform {
  required_version = ">= 1.10, < 2.0"
  required_providers {
    aws    = { source = "hashicorp/aws", version = ">= 6.0, < 7.0" }
    random = { source = "hashicorp/random", version = ">= 3.6, < 4.0" }
  }
  backend "s3" {}
}
provider "aws" {
  region = var.region
  default_tags { tags = { Project = var.name, Environment = var.environment, ManagedBy = "Terraform" } }
}
data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}
data "aws_availability_zones" "available" { state = "available" }
provider "aws" {
  alias  = "cloudfront_acm"
  region = "us-east-1"
  default_tags { tags = { Project = var.name, Environment = var.environment, ManagedBy = "Terraform" } }
}

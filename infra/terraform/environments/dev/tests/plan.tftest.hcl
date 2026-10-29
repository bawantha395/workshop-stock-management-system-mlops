# Plans the whole environment against a mocked AWS provider: no credentials,
# no cost. Checks module wiring, for_each keys, conditions and validations.
#   terraform -chdir=infra/terraform/environments/dev test -var-file=../prod/terraform.tfvars
# The CI runs it once with each environment's terraform.tfvars.

mock_provider "aws" {
  mock_data "aws_caller_identity" { defaults = { account_id = "123456789012" } }
  mock_data "aws_partition" { defaults = { partition = "aws" } }
  mock_data "aws_availability_zones" { defaults = { names = ["ap-southeast-2a", "ap-southeast-2b", "ap-southeast-2c"] } }
  mock_resource "aws_eks_cluster" {
    defaults = {
      arn        = "arn:aws:eks:ap-southeast-2:123456789012:cluster/stocklane-dev"
      vpc_config = { cluster_security_group_id = "sg-12345678" }
    }
  }
  # Real Terraform leaves the whole validation set unknown in a mocked plan, which
  # breaks for_each on the DNS validation records; give it one known entry.
  mock_resource "aws_acm_certificate" {
    defaults = {
      arn = "arn:aws:acm:ap-southeast-2:123456789012:certificate/x"
      domain_validation_options = [{
        domain_name           = "mock.example.com"
        resource_record_name  = "_mock.example.com."
        resource_record_type  = "CNAME"
        resource_record_value = "_mock.acm-validations.aws."
      }]
    }
  }
  mock_resource "aws_iam_openid_connect_provider" { defaults = { arn = "arn:aws:iam::123456789012:oidc-provider/token.actions.githubusercontent.com" } }
  mock_resource "aws_s3_bucket" { defaults = { arn = "arn:aws:s3:::bucket" } }
  mock_resource "aws_kms_key" { defaults = { arn = "arn:aws:kms:ap-southeast-2:123456789012:key/x" } }
  mock_resource "aws_sqs_queue" { defaults = { arn = "arn:aws:sqs:ap-southeast-2:123456789012:q" } }
  mock_resource "aws_iam_role" { defaults = { arn = "arn:aws:iam::123456789012:role/x" } }
  mock_resource "aws_cloudwatch_log_group" { defaults = { arn = "arn:aws:logs:ap-southeast-2:123456789012:log-group:x" } }
  mock_resource "aws_sns_topic" { defaults = { arn = "arn:aws:sns:ap-southeast-2:123456789012:t" } }
  mock_resource "aws_ecr_repository" { defaults = { arn = "arn:aws:ecr:ap-southeast-2:123456789012:repository/x" } }
  mock_resource "aws_sagemaker_model_package_group" { defaults = { arn = "arn:aws:sagemaker:ap-southeast-2:123456789012:model-package-group/x" } }
  mock_resource "aws_cloudfront_distribution" { defaults = { arn = "arn:aws:cloudfront::123456789012:distribution/x", domain_name = "d123.cloudfront.net" } }
  mock_resource "aws_codebuild_project" { defaults = { arn = "arn:aws:codebuild:ap-southeast-2:123456789012:project/x" } }
  mock_resource "aws_subnet" { defaults = { arn = "arn:aws:ec2:ap-southeast-2:123456789012:subnet/x" } }
  mock_resource "aws_dynamodb_table" { defaults = { arn = "arn:aws:dynamodb:ap-southeast-2:123456789012:table/x" } }
  mock_resource "aws_cloudwatch_event_rule" { defaults = { arn = "arn:aws:events:ap-southeast-2:123456789012:rule/x" } }
  mock_resource "aws_cognito_user_pool" { defaults = { id = "ap-southeast-2_AbCdEf123" } }
  mock_resource "aws_launch_template" { defaults = { id = "lt-0123456789abcdef0", latest_version = 1 } }
  mock_resource "aws_lambda_function" { defaults = { arn = "arn:aws:lambda:ap-southeast-2:123456789012:function:x" } }
}
mock_provider "aws" {
  alias = "us_east_1"
  mock_resource "aws_acm_certificate" {
    defaults = {
      arn = "arn:aws:acm:us-east-1:123456789012:certificate/x"
      domain_validation_options = [{
        domain_name           = "mock.example.com"
        resource_record_name  = "_mock.example.com."
        resource_record_type  = "CNAME"
        resource_record_value = "_mock.acm-validations.aws."
      }]
    }
  }
}
mock_provider "random" {
  mock_resource "random_password" { defaults = { result = "Abcdefghijklmnopqrstuvwxyz0123456789ABCD" } }
}

variables {
  github_repository    = "example/stocklane"
  github_auth_mode     = "access-key"
  github_ci_user_arn   = "arn:aws:iam::123456789012:user/stocklane-dev-github-ci"
  github_owner_id      = "1"
  github_repository_id = "2"
  administrator_arn    = "arn:aws:iam::123456789012:role/admin"
  operator_cidrs       = ["203.0.113.10/32"]
  admin_allowed_cidrs  = ["203.0.113.10/32"]
  route53_zone_id      = "Z123"
  api_domain           = "api.example.com"
  web_domain           = "app.example.com"
  argocd_domain        = "argocd.example.com"
  grafana_domain       = "grafana.example.com"
  budget_email         = "owner@example.com"
  bedrock_model_id     = "amazon.nova-lite-v1:0"
  bedrock_region       = "us-east-1"
}

run "plan" {
  command = plan
  assert {
    condition     = output.deployment.name == var.name
    error_message = "name output"
  }
  assert {
    condition     = output.deployment.environment == var.environment
    error_message = "environment output"
  }
  assert {
    condition     = output.deployment.workload_namespace == "stocklane-${var.environment}"
    error_message = "namespace"
  }
}

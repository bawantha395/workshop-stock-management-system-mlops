# Stocklane environment. This file is identical in dev, staging and prod;
# only terraform.tfvars (sizes, protection) and the state key differ.
#
#   network ─┬─ data ─┬─ registry ── ml
#            │        ├─ edge ── auth
#            └─ eks ──┴─ workload-identity, observability, cicd

locals {
  account_id         = data.aws_caller_identity.current.account_id
  partition          = data.aws_partition.current.partition
  availability_zones = slice(data.aws_availability_zones.available.names, 0, var.availability_zone_count)
  workload_namespace = "stocklane-${var.environment}"
}

module "network" {
  source             = "../../modules/network"
  name               = var.name
  region             = var.region
  availability_zones = local.availability_zones
  nat_per_az         = var.nat_per_az
}

module "data" {
  source                         = "../../modules/data"
  name                           = var.name
  account_id                     = local.account_id
  availability_zones             = local.availability_zones
  private_subnet_ids             = module.network.private_subnet_ids
  data_security_group_id         = module.network.data_security_group_id
  protect_data                   = var.deletion_protection
  demo_admin_credentials         = var.demo_admin_credentials
  database_instance_class        = var.database_instance_class
  database_multi_az              = var.database_multi_az
  database_storage_type          = var.database_storage_type
  database_max_allocated_storage = var.database_max_allocated_storage
  database_backup_retention_days = var.database_backup_retention_days
  cache_node_type                = var.cache_node_type
  cache_node_count               = var.cache_node_count
}

module "registry" {
  source       = "../../modules/registry"
  name         = var.name
  kms_key_arn  = module.data.kms_key_arn
  force_delete = !var.deletion_protection
}

module "eks" {
  source                   = "../../modules/eks"
  name                     = var.name
  partition                = local.partition
  permissions_boundary_arn = var.workload_permissions_boundary_arn
  eks_version              = var.eks_version
  service_ipv4_cidr        = var.service_ipv4_cidr
  private_subnet_ids       = module.network.private_subnet_ids
  operator_cidrs           = var.operator_cidrs
  administrator_arn        = var.administrator_arn
  kms_key_arn              = module.data.kms_key_arn
  data_security_group_id   = module.network.data_security_group_id
  node_instance_type       = var.node_instance_type
  node_min_size            = var.node_min_size
  node_desired_size        = var.node_desired_size
  node_max_size            = var.node_max_size
}

module "ml" {
  source                   = "../../modules/ml"
  name                     = var.name
  region                   = var.region
  account_id               = local.account_id
  partition                = local.partition
  permissions_boundary_arn = var.workload_permissions_boundary_arn
  models_bucket_arn        = module.data.buckets["models"].arn
  training_repository_arn  = module.registry.repositories["ml-training"].arn
  kms_key_arn              = module.data.kms_key_arn
  bedrock_model_id         = var.bedrock_model_id
  bedrock_model_arn        = var.bedrock_model_arn
  bedrock_region           = var.bedrock_region
}

module "observability" {
  source                      = "../../modules/observability"
  name                        = var.name
  region                      = var.region
  account_id                  = local.account_id
  partition                   = local.partition
  permissions_boundary_arn    = var.workload_permissions_boundary_arn
  alert_email                 = var.budget_email
  monthly_budget_usd          = var.monthly_budget_usd
  event_queue_names           = { for k, q in module.data.queues.events : k => q.name }
  dead_letter_queue_names     = { for k, q in module.data.queues.dead : k => q.name }
  key_deletion_window_days    = var.deletion_protection ? 30 : 7
  alarm_rca_cooldown_hours    = var.alarm_rca_cooldown_hours
  alarm_rca_daily_cap         = var.alarm_rca_daily_cap
  application_error_threshold = var.application_error_threshold
}

module "workload_identity" {
  source                     = "../../modules/workload-identity"
  name                       = var.name
  permissions_boundary_arn   = var.workload_permissions_boundary_arn
  cluster_name               = module.eks.cluster_name
  workload_namespace         = local.workload_namespace
  kms_key_arn                = module.data.kms_key_arn
  buckets                    = module.data.buckets
  queues                     = module.data.queues
  database_secret_arns       = module.data.database_secret_arns
  database_master_secret_arn = module.data.database_master_secret_arn
  platform_secret_arn        = module.data.platform_secret_arn
  grafana_secret_arn         = module.data.grafana_secret_arn
  application_log_group_arn  = module.observability.application_log_group_arn
  operations_topic_arn       = module.observability.operations_topic_arn
  alerts_kms_key_arn         = module.observability.alerts_kms_key_arn
  bedrock_invoke_arn         = module.ml.bedrock_invoke_arn
}

module "edge" {
  source              = "../../modules/edge"
  providers           = { aws = aws, aws.us_east_1 = aws.us_east_1 }
  name                = var.name
  route53_zone_id     = var.route53_zone_id
  web_bucket          = module.data.buckets["web"]
  web_domain          = var.web_domain
  api_domain          = var.api_domain
  argocd_domain       = var.argocd_domain
  grafana_domain      = var.grafana_domain
  admin_allowed_cidrs = var.admin_allowed_cidrs
}

module "auth" {
  source      = "../../modules/auth"
  name        = var.name
  account_id  = local.account_id
  app_urls    = distinct(["https://${module.edge.cloudfront_domain_name}", module.edge.web_url])
  owner_email = coalesce(var.initial_owner_email, var.budget_email)
}

module "cicd" {
  source                      = "../../modules/cicd"
  name                        = var.name
  environment                 = var.environment
  region                      = var.region
  account_id                  = local.account_id
  partition                   = local.partition
  permissions_boundary_arn    = var.workload_permissions_boundary_arn
  force_destroy               = !var.deletion_protection
  github_repository           = var.github_repository
  github_auth_mode            = var.github_auth_mode
  github_ci_user_arn          = var.github_ci_user_arn
  github_oidc_provider_arn    = var.github_oidc_provider_arn
  github_oidc_subject_style   = var.github_oidc_subject_style
  github_owner_id             = var.github_owner_id
  github_repository_id        = var.github_repository_id
  kms_key_arn                 = module.data.kms_key_arn
  ecr_repository_arns         = [for r in module.registry.repositories : r.arn]
  web_bucket_arn              = module.data.buckets["web"].arn
  models_bucket_arn           = module.data.buckets["models"].arn
  cloudfront_distribution_arn = module.edge.cloudfront_distribution_arn
  vision_model_group          = module.ml.vision_model_group
  forecast_model_group        = module.ml.forecast_model_group
  training_role_arn           = module.ml.training_role_arn
  vpc_id                      = module.network.vpc_id
  private_subnet_ids          = module.network.private_subnet_ids
  private_subnet_arns         = module.network.private_subnet_arns
  cluster_name                = module.eks.cluster_name
  cluster_arn                 = module.eks.cluster_arn
  cluster_security_group_id   = module.eks.cluster_security_group_id
  route53_zone_id             = var.route53_zone_id
  alias_domains               = compact([var.api_domain, var.argocd_domain, var.grafana_domain])
  platform_buildspec          = file("${path.root}/../../../../deploy/codebuild/platform-bootstrap.yml")
}

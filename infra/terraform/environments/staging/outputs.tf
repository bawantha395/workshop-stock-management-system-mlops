# One non-secret map that the release, platform and training workflows read
# (published to the automation bucket after every apply).
output "deployment" {
  value = {
    region             = var.region
    account_id         = local.account_id
    name               = var.name
    environment        = var.environment
    workload_namespace = local.workload_namespace
    github_repository  = var.github_repository
    github_auth_mode   = var.github_auth_mode

    # network and cluster
    vpc_id               = module.network.vpc_id
    cluster_name         = module.eks.cluster_name
    service_ipv4_cidr    = module.eks.service_ipv4_cidr
    application_replicas = var.application_replicas

    # domains and edge
    route53_zone_id            = var.route53_zone_id
    api_domain                 = var.api_domain
    api_certificate_arn        = module.edge.api_certificate_arn
    web_domain                 = var.web_domain
    frontend_url               = module.edge.web_url
    cloudfront_distribution_id = module.edge.cloudfront_distribution_id
    argocd_domain              = var.argocd_domain
    grafana_domain             = var.grafana_domain
    admin_allowed_cidrs        = var.admin_allowed_cidrs
    demo_admin_credentials     = var.demo_admin_credentials
    admin_certificate_arn      = module.edge.admin_certificate_arn

    # data
    kms_key_arn         = module.data.kms_key_arn
    web_bucket          = module.data.buckets["web"].id
    media_bucket        = module.data.buckets["media"].id
    model_bucket        = module.data.buckets["models"].id
    database_host       = module.data.database_address
    master_secret_arn   = module.data.database_master_secret_arn
    database_secrets    = module.data.database_secret_arns
    platform_secret_arn = module.data.platform_secret_arn
    grafana_secret_arn  = module.data.grafana_secret_arn
    cache_host          = module.data.cache_host
    stock_queue_url     = module.data.queues.events["stock"].url
    catalogue_queue_url = module.data.queues.events["catalogue"].url

    # sign-in
    cognito_issuer        = "https://cognito-idp.${var.region}.amazonaws.com/${module.auth.user_pool_id}"
    cognito_user_pool_id  = module.auth.user_pool_id
    cognito_web_client_id = module.auth.web_client_id
    cognito_token_url     = "https://${module.auth.domain}.auth.${var.region}.amazoncognito.com/oauth2/token"

    # delivery
    ecr                        = { for k, r in module.registry.repositories : k => r.url }
    automation_bucket          = module.cicd.automation_bucket
    platform_bootstrap_project = module.cicd.platform_bootstrap_project
    github_release_role_arn    = module.cicd.github_release_role_arn
    github_training_role_arn   = module.cicd.github_training_role_arn
    github_platform_role_arn   = module.cicd.github_platform_role_arn

    # ML and AI
    training_role_arn           = module.ml.training_role_arn
    model_package_group         = module.ml.vision_model_group.name
    bedrock_model_id            = module.ml.bedrock_model_id
    bedrock_region              = module.ml.bedrock_region
    bedrock_daily_request_limit = var.bedrock_daily_request_limit

    # operations
    application_log_group = module.observability.application_log_group_name
    operations_topic_arn  = module.observability.operations_topic_arn
  }
}

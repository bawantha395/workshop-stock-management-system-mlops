output "deployment" {
  value = {
    region                     = var.region
    github_auth_mode           = var.github_auth_mode
    automation_bucket          = aws_s3_bucket.automation.id
    platform_bootstrap_project = aws_codebuild_project.platform_bootstrap.name
    github_platform_role_arn   = aws_iam_role.github_platform.arn
    name                       = var.name
    environment                = var.environment
    workload_namespace         = local.workload_namespace
    github_repository          = var.github_repository
    application_replicas       = var.application_replicas
    account_id                 = local.suffix
    cluster_name               = aws_eks_cluster.main.name
    vpc_id                     = aws_vpc.main.id
    api_domain                 = var.api_domain
    api_certificate_arn        = aws_acm_certificate_validation.api.certificate_arn
    route53_zone_id            = var.route53_zone_id
    frontend_url               = "https://${aws_cloudfront_distribution.web.domain_name}"
    cloudfront_distribution_id = aws_cloudfront_distribution.web.id
    web_bucket                 = aws_s3_bucket.private["web"].id
    media_bucket               = aws_s3_bucket.private["media"].id
    model_bucket               = aws_s3_bucket.private["models"].id
    database_host              = aws_db_instance.main.address
    master_secret_arn          = aws_db_instance.main.master_user_secret[0].secret_arn
    database_secrets           = { for k, v in aws_secretsmanager_secret.database : k => v.arn }
    platform_secret_arn        = aws_secretsmanager_secret.shared.arn
    grafana_secret_arn         = aws_secretsmanager_secret.grafana.arn
    cache_host                 = aws_elasticache_replication_group.main.primary_endpoint_address
    stock_queue_url            = aws_sqs_queue.events["stock"].url
    catalogue_queue_url        = aws_sqs_queue.events["catalogue"].url
    cognito_issuer             = "https://cognito-idp.${var.region}.amazonaws.com/${aws_cognito_user_pool.main.id}"
    cognito_user_pool_id       = aws_cognito_user_pool.main.id
    cognito_web_client_id      = aws_cognito_user_pool_client.web.id
    cognito_camera_client_id   = aws_cognito_user_pool_client.camera.id
    cognito_token_url          = "https://${aws_cognito_user_pool_domain.main.domain}.auth.${var.region}.amazoncognito.com/oauth2/token"
    ecr                        = { for k, v in aws_ecr_repository.services : k => v.repository_url }
    github_release_role_arn    = aws_iam_role.github_release.arn
    github_training_role_arn   = aws_iam_role.github_training.arn
    training_role_arn          = aws_iam_role.training.arn
    model_package_group        = aws_sagemaker_model_package_group.vision.model_package_group_name
    kms_key_arn                = aws_kms_key.main.arn
    application_log_group      = aws_cloudwatch_log_group.application.name
    operations_topic_arn       = aws_sns_topic.operations.arn
  }
}

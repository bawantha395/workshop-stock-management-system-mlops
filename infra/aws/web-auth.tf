resource "aws_cloudfront_origin_access_control" "web" {
  name                              = var.name
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}
resource "aws_cloudfront_distribution" "web" {
  enabled             = true
  default_root_object = "index.html"
  price_class         = "PriceClass_100"
  origin {
    domain_name              = aws_s3_bucket.private["web"].bucket_regional_domain_name
    origin_id                = "private-react"
    origin_access_control_id = aws_cloudfront_origin_access_control.web.id
  }
  default_cache_behavior {
    allowed_methods        = ["GET", "HEAD", "OPTIONS"]
    cached_methods         = ["GET", "HEAD"]
    target_origin_id       = "private-react"
    viewer_protocol_policy = "redirect-to-https"
    compress               = true
    cache_policy_id        = "658327ea-f89d-4fab-a63d-7e88639e58f6"
  }
  custom_error_response {
    error_code            = 403
    response_code         = 200
    response_page_path    = "/index.html"
    error_caching_min_ttl = 0
  }
  restrictions {
    geo_restriction { restriction_type = "none" }
  }
  viewer_certificate { cloudfront_default_certificate = true }
}
resource "aws_s3_bucket_policy" "web" {
  bucket = aws_s3_bucket.private["web"].id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Principal = { Service = "cloudfront.amazonaws.com" }, Action = "s3:GetObject", Resource = "${aws_s3_bucket.private["web"].arn}/*", Condition = { StringEquals = { "AWS:SourceArn" = aws_cloudfront_distribution.web.arn } } },
    { Effect = "Deny", Principal = "*", Action = "s3:*", Resource = [aws_s3_bucket.private["web"].arn, "${aws_s3_bucket.private["web"].arn}/*"], Condition = { Bool = { "aws:SecureTransport" = "false" } } }
  ] })
}
resource "aws_cognito_user_pool" "main" {
  name                     = var.name
  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]
  admin_create_user_config { allow_admin_create_user_only = true }
  password_policy {
    minimum_length    = 14
    require_lowercase = true
    require_uppercase = true
    require_numbers   = true
    require_symbols   = true
  }
  mfa_configuration = "ON"
  software_token_mfa_configuration { enabled = true }
}
resource "aws_cognito_user_pool_domain" "main" {
  domain       = "${var.name}-${local.suffix}"
  user_pool_id = aws_cognito_user_pool.main.id
}
resource "aws_cognito_user_group" "staff" {
  for_each     = toset(["OWNER", "MECHANIC"])
  user_pool_id = aws_cognito_user_pool.main.id
  name         = each.key
}
resource "aws_cognito_user_pool_client" "web" {
  name                                 = "react-pwa"
  user_pool_id                         = aws_cognito_user_pool.main.id
  generate_secret                      = false
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes                 = ["openid", "email", "profile"]
  supported_identity_providers         = ["COGNITO"]
  callback_urls                        = ["https://${aws_cloudfront_distribution.web.domain_name}/auth/callback"]
  logout_urls                          = ["https://${aws_cloudfront_distribution.web.domain_name}"]
  prevent_user_existence_errors        = "ENABLED"
  enable_token_revocation              = true
  access_token_validity                = 15
  id_token_validity                    = 15
  refresh_token_validity               = 7
  token_validity_units {
    access_token  = "minutes"
    id_token      = "minutes"
    refresh_token = "days"
  }
}
resource "aws_cognito_resource_server" "camera" {
  identifier   = "stocklane"
  name         = "Workshop capture API"
  user_pool_id = aws_cognito_user_pool.main.id
  scope {
    scope_name        = "capture"
    scope_description = "Upload capture evidence; no stock or invoice approval"
  }
}
resource "aws_cognito_user_pool_client" "camera" {
  name                                 = "enrolled-workshop-camera"
  user_pool_id                         = aws_cognito_user_pool.main.id
  generate_secret                      = true
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["client_credentials"]
  allowed_oauth_scopes                 = ["${aws_cognito_resource_server.camera.identifier}/capture"]
  access_token_validity                = 60
  token_validity_units { access_token = "minutes" }
}
resource "aws_acm_certificate" "api" {
  domain_name       = var.api_domain
  validation_method = "DNS"
  lifecycle { create_before_destroy = true }
}
resource "aws_route53_record" "certificate" {
  for_each = { for d in aws_acm_certificate.api.domain_validation_options : d.domain_name => d }
  zone_id  = var.route53_zone_id
  name     = each.value.resource_record_name
  type     = each.value.resource_record_type
  records  = [each.value.resource_record_value]
  ttl      = 60
}
resource "aws_acm_certificate_validation" "api" {
  certificate_arn         = aws_acm_certificate.api.arn
  validation_record_fqdns = [for x in aws_route53_record.certificate : x.fqdn]
}
resource "aws_iam_openid_connect_provider" "github" {
  count          = var.github_oidc_provider_arn == "" ? 1 : 0
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}
resource "aws_iam_role" "github_release" {
  permissions_boundary = var.workload_permissions_boundary_arn
  name                 = "${var.name}-github-release"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect    = "Allow", Action = "sts:AssumeRoleWithWebIdentity", Principal = { Federated = var.github_oidc_provider_arn == "" ? aws_iam_openid_connect_provider.github[0].arn : var.github_oidc_provider_arn },
    Condition = { StringEquals = { "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com", "token.actions.githubusercontent.com:sub" = local.github_release_subject } }
  }] })
}
resource "aws_iam_role_policy" "github_release" {
  name = "publish-reviewed-releases"
  role = aws_iam_role.github_release.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["ecr:GetAuthorizationToken"], Resource = "*" },
    { Effect = "Allow", Action = ["ecr:BatchCheckLayerAvailability", "ecr:InitiateLayerUpload", "ecr:UploadLayerPart", "ecr:CompleteLayerUpload", "ecr:PutImage", "ecr:DescribeImages", "ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"], Resource = [for x in aws_ecr_repository.services : x.arn] },
    { Effect = "Allow", Action = ["s3:ListBucket"], Resource = [aws_s3_bucket.private["web"].arn, aws_s3_bucket.private["models"].arn] },
    { Effect = "Allow", Action = ["s3:PutObject", "s3:DeleteObject", "s3:GetObject"], Resource = ["${aws_s3_bucket.private["web"].arn}/*", "${aws_s3_bucket.private["models"].arn}/releases/*"] },
    { Effect = "Allow", Action = ["s3:GetObject"], Resource = "${aws_s3_bucket.private["models"].arn}/training/*" },
    { Effect = "Allow", Action = ["sagemaker:DescribeModelPackage"], Resource = "arn:${data.aws_partition.current.partition}:sagemaker:${var.region}:${local.suffix}:model-package/${aws_sagemaker_model_package_group.vision.model_package_group_name}/*" },
    { Effect = "Allow", Action = ["cloudfront:CreateInvalidation"], Resource = aws_cloudfront_distribution.web.arn },
    { Effect = "Allow", Action = ["kms:GenerateDataKey", "kms:Decrypt"], Resource = aws_kms_key.main.arn }
  ] })
}

# Delivery identities and tooling for this environment:
#  - GitHub roles: release (push images, publish web/model), training
#    (SageMaker jobs + Model Registry) and platform (start the bootstrap)
#  - the automation bucket for deployment outputs and platform sources
#  - a private CodeBuild runner that installs the Kubernetes platform from
#    inside the VPC, so the cluster API never needs to be widely exposed

locals {
  github_oidc_repository = var.github_oidc_subject_style == "legacy" ? var.github_repository : format(
    "%s@%s/%s@%s", split("/", var.github_repository)[0], coalesce(var.github_owner_id, "MISSING"),
    split("/", var.github_repository)[1], coalesce(var.github_repository_id, "MISSING")
  )
  oidc_provider_arn = var.github_auth_mode != "oidc" ? "" : (
    var.github_oidc_provider_arn == "" ? aws_iam_openid_connect_provider.github[0].arn : var.github_oidc_provider_arn
  )
  # Each GitHub environment (aws-release, aws-training, aws-platform) may only
  # assume its own role. In access-key mode the restricted CI user assumes it.
  github_trust = { for role, environment in {
    release  = "aws-release"
    training = "aws-training"
    platform = "aws-platform"
    } : role => var.github_auth_mode == "access-key" ? jsonencode({ Version = "2012-10-17", Statement = [{
      Effect = "Allow", Principal = { AWS = var.github_ci_user_arn }, Action = "sts:AssumeRole"
      }] }) : jsonencode({ Version = "2012-10-17", Statement = [{
      Effect    = "Allow", Action = "sts:AssumeRoleWithWebIdentity", Principal = { Federated = local.oidc_provider_arn },
      Condition = { StringEquals = { "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com", "token.actions.githubusercontent.com:sub" = "repo:${local.github_oidc_repository}:environment:${environment}" } }
  }] }) }
  codebuild_project = "${var.name}-platform-bootstrap"
}

resource "aws_iam_openid_connect_provider" "github" {
  count          = var.github_auth_mode == "oidc" && var.github_oidc_provider_arn == "" ? 1 : 0
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

# ---------- Automation bucket ----------
resource "aws_s3_bucket" "automation" {
  bucket        = "${var.name}-automation-${var.account_id}"
  force_destroy = var.force_destroy
}

resource "aws_s3_bucket_public_access_block" "automation" {
  bucket                  = aws_s3_bucket.automation.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "automation" {
  bucket = aws_s3_bucket.automation.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "automation" {
  bucket = aws_s3_bucket.automation.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "automation" {
  bucket = aws_s3_bucket.automation.id
  rule {
    id     = "expire-bootstrap-sources"
    status = "Enabled"
    filter { prefix = "sources/" }
    expiration { days = 14 }
    noncurrent_version_expiration { noncurrent_days = 14 }
    abort_incomplete_multipart_upload { days_after_initiation = 1 }
  }
}

resource "aws_s3_bucket_policy" "automation" {
  bucket = aws_s3_bucket.automation.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Sid       = "RequireTLS", Effect = "Deny", Principal = "*", Action = "s3:*",
    Resource  = [aws_s3_bucket.automation.arn, "${aws_s3_bucket.automation.arn}/*"],
    Condition = { Bool = { "aws:SecureTransport" = "false" } }
  }] })
}

# ---------- GitHub release role ----------
resource "aws_iam_role" "github_release" {
  permissions_boundary = var.permissions_boundary_arn
  name                 = "${var.name}-github-release"
  assume_role_policy   = local.github_trust["release"]
}

resource "aws_iam_role_policy" "github_release" {
  name = "publish-reviewed-releases"
  role = aws_iam_role.github_release.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["ecr:GetAuthorizationToken"], Resource = "*" },
    { Effect = "Allow", Action = ["ecr:BatchCheckLayerAvailability", "ecr:InitiateLayerUpload", "ecr:UploadLayerPart", "ecr:CompleteLayerUpload", "ecr:PutImage", "ecr:DescribeImages", "ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"], Resource = var.ecr_repository_arns },
    { Effect = "Allow", Action = ["s3:ListBucket"], Resource = [var.web_bucket_arn, var.models_bucket_arn] },
    { Effect = "Allow", Action = ["s3:PutObject", "s3:DeleteObject", "s3:GetObject"], Resource = ["${var.web_bucket_arn}/*", "${var.models_bucket_arn}/releases/*"] },
    { Effect = "Allow", Action = ["s3:GetObject"], Resource = "${var.models_bucket_arn}/training/*" },
    { Effect = "Allow", Action = ["sagemaker:DescribeModelPackage"], Resource = "arn:${var.partition}:sagemaker:${var.region}:${var.account_id}:model-package/${var.vision_model_group.name}/*" },
    { Effect = "Allow", Action = ["cloudfront:CreateInvalidation"], Resource = var.cloudfront_distribution_arn },
    { Effect = "Allow", Action = ["kms:GenerateDataKey", "kms:Decrypt"], Resource = var.kms_key_arn }
  ] })
}

# ---------- GitHub training role ----------
resource "aws_iam_role" "github_training" {
  permissions_boundary = var.permissions_boundary_arn
  name                 = "${var.name}-github-training"
  assume_role_policy   = local.github_trust["training"]
}

resource "aws_iam_role_policy" "github_training" {
  name = "run-bounded-training-and-register"
  role = aws_iam_role.github_training.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["sagemaker:CreateTrainingJob", "sagemaker:DescribeTrainingJob", "sagemaker:StopTrainingJob"], Resource = "arn:${var.partition}:sagemaker:${var.region}:${var.account_id}:training-job/${var.name}-*" },
    { Effect = "Allow", Action = ["sagemaker:CreateProcessingJob", "sagemaker:DescribeProcessingJob", "sagemaker:StopProcessingJob"], Resource = "arn:${var.partition}:sagemaker:${var.region}:${var.account_id}:processing-job/${var.name}-*" },
    { Effect = "Allow", Action = ["sagemaker:CreateModelPackage", "sagemaker:DescribeModelPackage", "sagemaker:UpdateModelPackage"], Resource = [
      var.forecast_model_group.arn, "arn:${var.partition}:sagemaker:${var.region}:${var.account_id}:model-package/${var.forecast_model_group.name}/*",
      var.vision_model_group.arn, "arn:${var.partition}:sagemaker:${var.region}:${var.account_id}:model-package/${var.vision_model_group.name}/*"
    ] },
    { Effect = "Allow", Action = "iam:PassRole", Resource = var.training_role_arn, Condition = { StringEquals = { "iam:PassedToService" = "sagemaker.amazonaws.com" } } },
    # CreateModelPackage checks that the caller itself can read the inference image.
    { Effect = "Allow", Action = ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer", "ecr:BatchCheckLayerAvailability", "ecr:DescribeImages"], Resource = "arn:${var.partition}:ecr:${var.region}:${var.account_id}:repository/${var.name}/ml-training" },
    { Effect = "Allow", Action = ["s3:GetObject", "s3:PutObject"], Resource = "${var.models_bucket_arn}/*" },
    { Effect = "Allow", Action = ["s3:ListBucket"], Resource = var.models_bucket_arn },
    { Effect = "Allow", Action = ["kms:GenerateDataKey", "kms:Decrypt"], Resource = var.kms_key_arn }
  ] })
}

# Release and training read the Terraform outputs published for this environment.
resource "aws_iam_role_policy" "github_deployment_metadata" {
  for_each = {
    release  = aws_iam_role.github_release.id
    training = aws_iam_role.github_training.id
  }
  name = "read-reviewed-deployment-metadata"
  role = each.value
  policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect   = "Allow", Action = ["s3:GetObject", "s3:GetObjectVersion"],
    Resource = "${aws_s3_bucket.automation.arn}/outputs/${var.environment}/*"
  }] })
}

# ---------- Private platform bootstrap (CodeBuild inside the VPC) ----------
resource "aws_iam_role" "platform_bootstrap" {
  permissions_boundary = var.permissions_boundary_arn
  name                 = "${var.name}-platform-bootstrap"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect = "Allow", Principal = { Service = "codebuild.amazonaws.com" }, Action = "sts:AssumeRole",
    Condition = {
      StringEquals = { "aws:SourceAccount" = var.account_id },
      ArnEquals    = { "aws:SourceArn" = "arn:${var.partition}:codebuild:${var.region}:${var.account_id}:project/${local.codebuild_project}" }
    }
  }] })
}

resource "aws_cloudwatch_log_group" "platform_bootstrap" {
  name              = "/aws/codebuild/${local.codebuild_project}"
  retention_in_days = 7
}

resource "aws_security_group" "platform_bootstrap" {
  name_prefix = "${var.name}-bootstrap-"
  description = "Private CodeBuild runner; no inbound rules"
  vpc_id      = var.vpc_id
}

resource "aws_vpc_security_group_egress_rule" "platform_bootstrap_https" {
  security_group_id = aws_security_group.platform_bootstrap.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
}

resource "aws_vpc_security_group_ingress_rule" "platform_bootstrap_api" {
  security_group_id            = var.cluster_security_group_id
  referenced_security_group_id = aws_security_group.platform_bootstrap.id
  ip_protocol                  = "tcp"
  from_port                    = 443
  to_port                      = 443
}

resource "aws_iam_role_policy" "platform_bootstrap" {
  name = "install-reviewed-private-platform"
  role = aws_iam_role.platform_bootstrap.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["s3:GetObject", "s3:GetObjectVersion"], Resource = ["${aws_s3_bucket.automation.arn}/sources/*", "${aws_s3_bucket.automation.arn}/outputs/*"] },
    { Effect = "Allow", Action = ["s3:GetBucketLocation", "s3:ListBucket"], Resource = aws_s3_bucket.automation.arn },
    { Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = "${aws_cloudwatch_log_group.platform_bootstrap.arn}:*" },
    { Effect = "Allow", Action = ["eks:DescribeCluster"], Resource = var.cluster_arn },
    { Effect = "Allow", Action = ["ec2:CreateNetworkInterface", "ec2:DeleteNetworkInterface", "ec2:DescribeDhcpOptions", "ec2:DescribeNetworkInterfaces", "ec2:DescribeSubnets", "ec2:DescribeSecurityGroups", "ec2:DescribeVpcs"], Resource = "*" },
    { Effect = "Allow", Action = ["ec2:CreateNetworkInterfacePermission"], Resource = "arn:${var.partition}:ec2:${var.region}:${var.account_id}:network-interface/*", Condition = { StringEquals = { "ec2:AuthorizedService" = "codebuild.amazonaws.com" }, ArnEquals = { "ec2:Subnet" = var.private_subnet_arns } } },
    { Effect = "Allow", Action = ["elasticloadbalancing:DescribeLoadBalancers"], Resource = "*" },
    { Effect = "Allow", Action = ["route53:ChangeResourceRecordSets"], Resource = "arn:${var.partition}:route53:::hostedzone/${var.route53_zone_id}", Condition = { "ForAllValues:StringEquals" = {
      "route53:ChangeResourceRecordSetsNormalizedRecordNames" = var.alias_domains,
      "route53:ChangeResourceRecordSetsRecordTypes"           = ["A"],
      "route53:ChangeResourceRecordSetsActions"               = ["UPSERT"]
    } } }
  ] })
}

resource "aws_eks_access_entry" "platform_bootstrap" {
  cluster_name  = var.cluster_name
  principal_arn = aws_iam_role.platform_bootstrap.arn
  type          = "STANDARD"
}

resource "aws_eks_access_policy_association" "platform_bootstrap" {
  cluster_name  = var.cluster_name
  principal_arn = aws_eks_access_entry.platform_bootstrap.principal_arn
  policy_arn    = "arn:${var.partition}:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"
  access_scope { type = "cluster" }
}

resource "aws_codebuild_project" "platform_bootstrap" {
  name                   = local.codebuild_project
  service_role           = aws_iam_role.platform_bootstrap.arn
  build_timeout          = 45
  queued_timeout         = 15
  concurrent_build_limit = 1
  artifacts { type = "NO_ARTIFACTS" }
  environment {
    type            = "LINUX_CONTAINER"
    compute_type    = "BUILD_GENERAL1_SMALL"
    image           = "aws/codebuild/standard:7.0"
    privileged_mode = false
    environment_variable {
      name  = "EXPECTED_ACCOUNT_ID"
      value = var.account_id
    }
    environment_variable {
      name  = "EXPECTED_PROJECT"
      value = var.name
    }
    environment_variable {
      name  = "EXPECTED_REGION"
      value = var.region
    }
  }
  source {
    type      = "S3"
    location  = "${aws_s3_bucket.automation.id}/sources/not-yet-published.zip"
    buildspec = var.platform_buildspec
  }
  vpc_config {
    vpc_id             = var.vpc_id
    subnets            = var.private_subnet_ids
    security_group_ids = [aws_security_group.platform_bootstrap.id]
  }
  logs_config {
    cloudwatch_logs {
      group_name  = aws_cloudwatch_log_group.platform_bootstrap.name
      stream_name = "platform"
    }
  }
  depends_on = [aws_iam_role_policy.platform_bootstrap, aws_eks_access_policy_association.platform_bootstrap, aws_s3_bucket_policy.automation]
}

# ---------- GitHub platform role ----------
resource "aws_iam_role" "github_platform" {
  permissions_boundary = var.permissions_boundary_arn
  name                 = "${var.name}-github-platform"
  max_session_duration = 7200
  assume_role_policy   = local.github_trust["platform"]
}

resource "aws_iam_role_policy" "github_platform" {
  name = "submit-reviewed-platform-bootstrap"
  role = aws_iam_role.github_platform.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["s3:GetObject", "s3:GetObjectVersion"], Resource = "${aws_s3_bucket.automation.arn}/outputs/*" },
    { Effect = "Allow", Action = ["s3:PutObject"], Resource = "${aws_s3_bucket.automation.arn}/sources/*" },
    { Effect = "Allow", Action = ["codebuild:StartBuild", "codebuild:BatchGetBuilds", "codebuild:StopBuild"], Resource = [aws_codebuild_project.platform_bootstrap.arn, "arn:${var.partition}:codebuild:${var.region}:${var.account_id}:build/${aws_codebuild_project.platform_bootstrap.name}:*"] }
  ] })
}

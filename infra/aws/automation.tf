# The state backend is bootstrapped separately with CloudFormation.
# This bucket contains only deployment metadata and reviewed platform sources.
resource "aws_s3_bucket" "automation" {
  bucket        = "${var.name}-automation-${local.suffix}"
  force_destroy = false
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
resource "aws_iam_role" "platform_bootstrap" {
  permissions_boundary = var.workload_permissions_boundary_arn
  name                 = "${var.name}-platform-bootstrap"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect = "Allow", Principal = { Service = "codebuild.amazonaws.com" }, Action = "sts:AssumeRole",
    Condition = {
      StringEquals = { "aws:SourceAccount" = local.suffix },
      ArnEquals    = { "aws:SourceArn" = "arn:${data.aws_partition.current.partition}:codebuild:${var.region}:${local.suffix}:project/${var.name}-platform-bootstrap" }
    }
  }] })
}
resource "aws_cloudwatch_log_group" "platform_bootstrap" {
  name              = "/aws/codebuild/${var.name}-platform-bootstrap"
  retention_in_days = 7
}
resource "aws_security_group" "platform_bootstrap" {
  name_prefix = "${var.name}-bootstrap-"
  description = "Private CodeBuild runner; no inbound rules"
  vpc_id      = aws_vpc.main.id
}
resource "aws_vpc_security_group_egress_rule" "platform_bootstrap_https" {
  security_group_id = aws_security_group.platform_bootstrap.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
}
resource "aws_vpc_security_group_ingress_rule" "platform_bootstrap_api" {
  security_group_id            = aws_eks_cluster.main.vpc_config[0].cluster_security_group_id
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
    { Effect = "Allow", Action = ["eks:DescribeCluster"], Resource = aws_eks_cluster.main.arn },
    { Effect = "Allow", Action = ["ec2:CreateNetworkInterface", "ec2:DeleteNetworkInterface", "ec2:DescribeDhcpOptions", "ec2:DescribeNetworkInterfaces", "ec2:DescribeSubnets", "ec2:DescribeSecurityGroups", "ec2:DescribeVpcs"], Resource = "*" },
    { Effect = "Allow", Action = ["ec2:CreateNetworkInterfacePermission"], Resource = "arn:${data.aws_partition.current.partition}:ec2:${var.region}:${local.suffix}:network-interface/*", Condition = { StringEquals = { "ec2:AuthorizedService" = "codebuild.amazonaws.com" }, ArnEquals = { "ec2:Subnet" = [for s in aws_subnet.private : s.arn] } } },
    { Effect = "Allow", Action = ["elasticloadbalancing:DescribeLoadBalancers"], Resource = "*" },
    { Effect = "Allow", Action = ["route53:ChangeResourceRecordSets"], Resource = "arn:${data.aws_partition.current.partition}:route53:::hostedzone/${var.route53_zone_id}", Condition = { "ForAllValues:StringEquals" = { "route53:ChangeResourceRecordSetsNormalizedRecordNames" = [var.api_domain], "route53:ChangeResourceRecordSetsRecordTypes" = ["A"], "route53:ChangeResourceRecordSetsActions" = ["UPSERT"] } } }
  ] })
}
resource "aws_eks_access_entry" "platform_bootstrap" {
  cluster_name  = aws_eks_cluster.main.name
  principal_arn = aws_iam_role.platform_bootstrap.arn
  type          = "STANDARD"
}
resource "aws_eks_access_policy_association" "platform_bootstrap" {
  cluster_name  = aws_eks_cluster.main.name
  principal_arn = aws_eks_access_entry.platform_bootstrap.principal_arn
  policy_arn    = "arn:${data.aws_partition.current.partition}:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"
  access_scope { type = "cluster" }
}
resource "aws_codebuild_project" "platform_bootstrap" {
  name                   = "${var.name}-platform-bootstrap"
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
      value = local.suffix
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
    buildspec = file("${path.module}/../../deploy/codebuild/platform-bootstrap.yml")
  }
  vpc_config {
    vpc_id             = aws_vpc.main.id
    subnets            = aws_subnet.private[*].id
    security_group_ids = [aws_security_group.platform_bootstrap.id]
  }
  logs_config {
    cloudwatch_logs {
      group_name  = aws_cloudwatch_log_group.platform_bootstrap.name
      stream_name = "platform"
    }
  }
  depends_on = [aws_iam_role_policy.platform_bootstrap, aws_eks_access_policy_association.platform_bootstrap, aws_nat_gateway.main, aws_s3_bucket_policy.automation]
}
resource "aws_iam_role" "github_platform" {
  permissions_boundary = var.workload_permissions_boundary_arn
  name                 = "${var.name}-github-platform"
  max_session_duration = 7200
  assume_role_policy = var.github_auth_mode == "access-key" ? jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Principal = { AWS = var.github_ci_user_arn }, Action = "sts:AssumeRole" }] }) : jsonencode({ Version = "2012-10-17", Statement = [{
    Effect    = "Allow", Action = "sts:AssumeRoleWithWebIdentity",
    Principal = { Federated = var.github_oidc_provider_arn == "" ? aws_iam_openid_connect_provider.github[0].arn : var.github_oidc_provider_arn },
    Condition = { StringEquals = { "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com", "token.actions.githubusercontent.com:sub" = local.github_platform_subject } }
  }] })
}
resource "aws_iam_role_policy" "github_platform" {
  name = "submit-reviewed-platform-bootstrap"
  role = aws_iam_role.github_platform.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["s3:GetObject", "s3:GetObjectVersion"], Resource = "${aws_s3_bucket.automation.arn}/outputs/*" },
    { Effect = "Allow", Action = ["s3:PutObject"], Resource = "${aws_s3_bucket.automation.arn}/sources/*" },
    { Effect = "Allow", Action = ["codebuild:StartBuild", "codebuild:BatchGetBuilds", "codebuild:StopBuild"], Resource = [aws_codebuild_project.platform_bootstrap.arn, "arn:${data.aws_partition.current.partition}:codebuild:${var.region}:${local.suffix}:build/${aws_codebuild_project.platform_bootstrap.name}:*"] }
  ] })
}
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


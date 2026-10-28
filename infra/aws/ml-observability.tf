resource "aws_iam_role" "training" {
  permissions_boundary = var.workload_permissions_boundary_arn
  name                 = "${var.name}-sagemaker-training"
  assume_role_policy   = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Principal = { Service = "sagemaker.amazonaws.com" }, Action = "sts:AssumeRole" }] })
}
resource "aws_iam_role_policy" "training" {
  name = "train-from-reviewed-datasets"
  role = aws_iam_role.training.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["s3:ListBucket"], Resource = aws_s3_bucket.private["models"].arn },
    { Effect = "Allow", Action = ["s3:GetObject", "s3:PutObject"], Resource = "${aws_s3_bucket.private["models"].arn}/*" },
    { Effect = "Allow", Action = ["ecr:GetAuthorizationToken"], Resource = "*" },
    { Effect = "Allow", Action = ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer", "ecr:BatchCheckLayerAvailability"], Resource = aws_ecr_repository.services["ml-training"].arn },
    { Effect = "Allow", Action = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"], Resource = "arn:${data.aws_partition.current.partition}:logs:${var.region}:${local.suffix}:log-group:/aws/sagemaker/*" },
    { Effect = "Allow", Action = ["kms:GenerateDataKey", "kms:Decrypt", "kms:Encrypt"], Resource = aws_kms_key.main.arn }
  ] })
}
resource "aws_sagemaker_model_package_group" "vision" {
  model_package_group_name        = "${var.name}-visual-sku"
  model_package_group_description = "Versioned visual encoder and trained same-SKU similarity calibration; manual approval required"
}
resource "aws_iam_role" "github_training" {
  permissions_boundary = var.workload_permissions_boundary_arn
  name                 = "${var.name}-github-training"
  assume_role_policy = var.github_auth_mode == "access-key" ? jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Principal = { AWS = var.github_ci_user_arn }, Action = "sts:AssumeRole" }] }) : jsonencode({ Version = "2012-10-17", Statement = [{
    Effect    = "Allow", Action = "sts:AssumeRoleWithWebIdentity", Principal = { Federated = var.github_oidc_provider_arn == "" ? aws_iam_openid_connect_provider.github[0].arn : var.github_oidc_provider_arn },
    Condition = { StringEquals = { "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com", "token.actions.githubusercontent.com:sub" = local.github_training_subject } }
  }] })
}
resource "aws_iam_role_policy" "github_training" {
  name = "run-bounded-training-and-register"
  role = aws_iam_role.github_training.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["sagemaker:CreateTrainingJob", "sagemaker:DescribeTrainingJob", "sagemaker:StopTrainingJob"], Resource = "arn:${data.aws_partition.current.partition}:sagemaker:${var.region}:${local.suffix}:training-job/${var.name}-*" },
    { Effect = "Allow", Action = ["sagemaker:CreateProcessingJob", "sagemaker:DescribeProcessingJob", "sagemaker:StopProcessingJob"], Resource = "arn:${data.aws_partition.current.partition}:sagemaker:${var.region}:${local.suffix}:processing-job/${var.name}-*" },
    { Effect = "Allow", Action = ["sagemaker:CreateModelPackage", "sagemaker:DescribeModelPackage", "sagemaker:UpdateModelPackage"], Resource = [aws_sagemaker_model_package_group.forecast.arn, "arn:${data.aws_partition.current.partition}:sagemaker:${var.region}:${local.suffix}:model-package/${aws_sagemaker_model_package_group.forecast.model_package_group_name}/*", aws_sagemaker_model_package_group.vision.arn, "arn:${data.aws_partition.current.partition}:sagemaker:${var.region}:${local.suffix}:model-package/${aws_sagemaker_model_package_group.vision.model_package_group_name}/*"] },
    { Effect = "Allow", Action = "iam:PassRole", Resource = aws_iam_role.training.arn, Condition = { StringEquals = { "iam:PassedToService" = "sagemaker.amazonaws.com" } } },
    { Effect = "Allow", Action = ["s3:GetObject", "s3:PutObject"], Resource = "${aws_s3_bucket.private["models"].arn}/*" },
    { Effect = "Allow", Action = ["s3:ListBucket"], Resource = aws_s3_bucket.private["models"].arn },
    { Effect = "Allow", Action = ["kms:GenerateDataKey", "kms:Decrypt"], Resource = aws_kms_key.main.arn }
  ] })
}
resource "aws_cloudwatch_metric_alarm" "queue_age" {
  for_each            = aws_sqs_queue.events
  alarm_name          = "${var.name}-${each.key}-backlog-age"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateAgeOfOldestMessage"
  dimensions          = { QueueName = each.value.name }
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 3
  threshold           = 120
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.operations.arn]
  ok_actions          = [aws_sns_topic.operations.arn]
}
resource "aws_cloudwatch_metric_alarm" "dead_letters" {
  for_each            = aws_sqs_queue.dead
  alarm_name          = "${var.name}-${each.key}-dead-letters"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = each.value.name }
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.operations.arn]
  ok_actions          = [aws_sns_topic.operations.arn]
}
resource "aws_budgets_budget" "monthly" {
  name         = "${var.name}-monthly"
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.budget_email]
  }
}
resource "aws_kms_key" "alerts" {
  description             = "${var.name} operations notification encryption"
  enable_key_rotation     = true
  deletion_window_in_days = 30
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Sid = "AccountAdministration", Effect = "Allow", Principal = { AWS = "arn:${data.aws_partition.current.partition}:iam::${local.suffix}:root" }, Action = "kms:*", Resource = "*" },
    { Sid = "CloudWatchAlarms", Effect = "Allow", Principal = { Service = "cloudwatch.amazonaws.com" }, Action = ["kms:Decrypt", "kms:GenerateDataKey*"], Resource = "*", Condition = { StringEquals = { "aws:SourceAccount" = local.suffix }, ArnLike = { "aws:SourceArn" = "arn:${data.aws_partition.current.partition}:cloudwatch:${var.region}:${local.suffix}:alarm:${var.name}-*" } } }
  ] })
}
resource "aws_sns_topic" "operations" {
  name              = "${var.name}-operations"
  kms_master_key_id = aws_kms_key.alerts.arn
}
locals {
  # SNS topic policies accept a subset of SNS API actions. Expanding sns:*
  # includes operations outside that subset and SNS rejects the entire policy.
  sns_topic_policy_actions = [
    "sns:AddPermission", "sns:DeleteTopic", "sns:GetDataProtectionPolicy",
    "sns:GetTopicAttributes", "sns:ListSubscriptionsByTopic", "sns:ListTagsForResource",
    "sns:Publish", "sns:PutDataProtectionPolicy", "sns:RemovePermission",
    "sns:SetTopicAttributes", "sns:Subscribe"
  ]
}
resource "aws_sns_topic_policy" "operations" {
  arn = aws_sns_topic.operations.arn
  policy = jsonencode({ Version = "2012-10-17", Id = "${var.name}-operations", Statement = [
    { Sid = "Owner", Effect = "Allow", Principal = { AWS = "arn:${data.aws_partition.current.partition}:iam::${local.suffix}:root" }, Action = local.sns_topic_policy_actions, Resource = aws_sns_topic.operations.arn },
    { Sid = "CloudWatchAlarms", Effect = "Allow", Principal = { Service = "cloudwatch.amazonaws.com" }, Action = "sns:Publish", Resource = aws_sns_topic.operations.arn, Condition = { StringEquals = { "aws:SourceAccount" = local.suffix }, ArnLike = { "aws:SourceArn" = "arn:${data.aws_partition.current.partition}:cloudwatch:${var.region}:${local.suffix}:alarm:${var.name}-*" } } },
    { Sid = "TLSOnly", Effect = "Deny", Principal = "*", Action = local.sns_topic_policy_actions, Resource = aws_sns_topic.operations.arn, Condition = { Bool = { "aws:SecureTransport" = "false" } } }
  ] })
}
resource "aws_sns_topic_subscription" "owner" {
  topic_arn = aws_sns_topic.operations.arn
  protocol  = "email"
  endpoint  = var.budget_email
}
resource "aws_iam_role_policy" "alertmanager" {
  name = "publish-platform-alerts"
  role = aws_iam_role.pods["alertmanager"].id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = "sns:Publish", Resource = aws_sns_topic.operations.arn },
    { Effect = "Allow", Action = ["kms:Decrypt", "kms:GenerateDataKey*"], Resource = aws_kms_key.alerts.arn }
  ] })
}

resource "aws_sagemaker_model_package_group" "forecast" {
  model_package_group_name        = "${var.name}-stock-forecast"
  model_package_group_description = "Stock usage forecasting with temporal evaluation and weekday baseline gates"
}

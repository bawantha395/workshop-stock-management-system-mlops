# Logs, alarms, the operations email topic, the monthly budget and the
# rule-based alarm root-cause (RCA) Lambda.
#
# Alarm -> SNS email.  Alarm entering ALARM -> EventBridge -> Lambda collects
# read-only evidence (metrics, Logs Insights, CloudTrail) -> SNS email report.

# ---------- Logs ----------
resource "aws_cloudwatch_log_group" "application" {
  name              = "/stocklane/${var.name}/containers"
  retention_in_days = 7
}

# ---------- Notifications ----------
resource "aws_kms_key" "alerts" {
  description             = "${var.name} operations notification encryption"
  enable_key_rotation     = true
  deletion_window_in_days = var.key_deletion_window_days
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Sid = "AccountAdministration", Effect = "Allow", Principal = { AWS = "arn:${var.partition}:iam::${var.account_id}:root" }, Action = "kms:*", Resource = "*" },
    { Sid = "CloudWatchAlarms", Effect = "Allow", Principal = { Service = "cloudwatch.amazonaws.com" }, Action = ["kms:Decrypt", "kms:GenerateDataKey*"], Resource = "*",
    Condition = { StringEquals = { "aws:SourceAccount" = var.account_id }, ArnLike = { "aws:SourceArn" = local.alarm_arn_pattern } } }
  ] })
}

locals {
  alarm_arn_pattern = "arn:${var.partition}:cloudwatch:${var.region}:${var.account_id}:alarm:${var.name}-*"
  # SNS topic policies accept only a subset of SNS actions; "sns:*" is rejected.
  sns_topic_policy_actions = [
    "sns:AddPermission", "sns:DeleteTopic", "sns:GetDataProtectionPolicy",
    "sns:GetTopicAttributes", "sns:ListSubscriptionsByTopic", "sns:ListTagsForResource",
    "sns:Publish", "sns:PutDataProtectionPolicy", "sns:RemovePermission",
    "sns:SetTopicAttributes", "sns:Subscribe"
  ]
}

resource "aws_sns_topic" "operations" {
  name              = "${var.name}-operations"
  kms_master_key_id = aws_kms_key.alerts.arn
}

resource "aws_sns_topic_policy" "operations" {
  arn = aws_sns_topic.operations.arn
  policy = jsonencode({ Version = "2012-10-17", Id = "${var.name}-operations", Statement = [
    { Sid = "Owner", Effect = "Allow", Principal = { AWS = "arn:${var.partition}:iam::${var.account_id}:root" }, Action = local.sns_topic_policy_actions, Resource = aws_sns_topic.operations.arn },
    { Sid = "CloudWatchAlarms", Effect = "Allow", Principal = { Service = "cloudwatch.amazonaws.com" }, Action = "sns:Publish", Resource = aws_sns_topic.operations.arn,
    Condition = { StringEquals = { "aws:SourceAccount" = var.account_id }, ArnLike = { "aws:SourceArn" = local.alarm_arn_pattern } } },
    { Sid = "TLSOnly", Effect = "Deny", Principal = "*", Action = local.sns_topic_policy_actions, Resource = aws_sns_topic.operations.arn, Condition = { Bool = { "aws:SecureTransport" = "false" } } }
  ] })
}

resource "aws_sns_topic_subscription" "owner" {
  topic_arn = aws_sns_topic.operations.arn
  protocol  = "email"
  endpoint  = var.alert_email
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
    subscriber_email_addresses = [var.alert_email]
  }
}

# ---------- Alarms ----------
resource "aws_cloudwatch_metric_alarm" "queue_age" {
  for_each            = var.event_queue_names
  alarm_name          = "${var.name}-${each.key}-backlog-age"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateAgeOfOldestMessage"
  dimensions          = { QueueName = each.value }
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
  for_each            = var.dead_letter_queue_names
  alarm_name          = "${var.name}-${each.key}-dead-letters"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = each.value }
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.operations.arn]
  ok_actions          = [aws_sns_topic.operations.arn]
}

# Service failures from container logs, not only queue health.
resource "aws_cloudwatch_log_metric_filter" "application_errors" {
  name           = "${var.name}-application-errors"
  log_group_name = aws_cloudwatch_log_group.application.name
  pattern        = "?ERROR ?Exception ?FATAL"
  metric_transformation {
    name          = "ApplicationErrors"
    namespace     = "Stocklane/${var.name}"
    value         = "1"
    default_value = "0"
  }
}

resource "aws_cloudwatch_metric_alarm" "application_errors" {
  alarm_name          = "${var.name}-application-errors"
  alarm_description   = "Container error lines exceeded the threshold; a root-cause report follows by email"
  namespace           = "Stocklane/${var.name}"
  metric_name         = "ApplicationErrors"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = var.application_error_threshold
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.operations.arn]
  ok_actions          = [aws_sns_topic.operations.arn]
}

# ---------- Alarm root-cause reports ----------
# The Lambda package is committed and checked against its source by
# tests/test_alarm_rca.py; rebuild it with scripts/build_alarm_rca.py.
resource "aws_dynamodb_table" "alarm_rca" {
  name         = "${var.name}-alarm-rca"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"
  attribute {
    name = "pk"
    type = "S"
  }
  ttl {
    attribute_name = "expires"
    enabled        = true
  }
  server_side_encryption { enabled = true }
}

resource "aws_cloudwatch_log_group" "alarm_rca" {
  name              = "/aws/lambda/${var.name}-alarm-rca"
  retention_in_days = 14
}

resource "aws_iam_role" "alarm_rca" {
  permissions_boundary = var.permissions_boundary_arn
  name                 = "${var.name}-alarm-rca"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect = "Allow", Principal = { Service = "lambda.amazonaws.com" }, Action = "sts:AssumeRole"
  }] })
}

resource "aws_iam_role_policy" "alarm_rca" {
  name = "read-only-alarm-evidence"
  role = aws_iam_role.alarm_rca.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = "${aws_cloudwatch_log_group.alarm_rca.arn}:*" },
    { Effect = "Allow", Action = ["cloudwatch:DescribeAlarms", "cloudwatch:DescribeAlarmHistory", "cloudwatch:GetMetricData", "cloudtrail:LookupEvents", "logs:GetQueryResults", "logs:StopQuery"], Resource = "*" },
    { Effect = "Allow", Action = ["logs:StartQuery"], Resource = "${aws_cloudwatch_log_group.application.arn}:*" },
    { Effect = "Allow", Action = ["dynamodb:PutItem", "dynamodb:UpdateItem"], Resource = aws_dynamodb_table.alarm_rca.arn },
    { Effect = "Allow", Action = "sns:Publish", Resource = aws_sns_topic.operations.arn },
    { Effect = "Allow", Action = ["kms:Decrypt", "kms:GenerateDataKey*"], Resource = aws_kms_key.alerts.arn }
  ] })
}

resource "aws_lambda_function" "alarm_rca" {
  function_name    = "${var.name}-alarm-rca"
  role             = aws_iam_role.alarm_rca.arn
  runtime          = "python3.12"
  handler          = "alarm_rca.handler"
  filename         = "${path.module}/lambda/alarm-rca.zip"
  source_code_hash = filebase64sha256("${path.module}/lambda/alarm-rca.zip")
  timeout          = 120
  memory_size      = 256
  environment {
    variables = {
      NAME_PREFIX      = "${var.name}-"
      TABLE            = aws_dynamodb_table.alarm_rca.name
      TOPIC_ARN        = aws_sns_topic.operations.arn
      LOG_GROUP        = aws_cloudwatch_log_group.application.name
      COOLDOWN_HOURS   = tostring(var.alarm_rca_cooldown_hours)
      DAILY_CAP        = tostring(var.alarm_rca_daily_cap)
      LOOKBACK_MINUTES = "30"
    }
  }
  depends_on = [aws_cloudwatch_log_group.alarm_rca, aws_iam_role_policy.alarm_rca]
}

resource "aws_cloudwatch_event_rule" "alarm_rca" {
  name        = "${var.name}-alarm-rca"
  description = "Project alarms entering ALARM start a rule-based root-cause report"
  event_pattern = jsonencode({
    source        = ["aws.cloudwatch"]
    "detail-type" = ["CloudWatch Alarm State Change"]
    detail = {
      alarmName = [{ prefix = "${var.name}-" }]
      state     = { value = ["ALARM"] }
    }
  })
}

resource "aws_cloudwatch_event_target" "alarm_rca" {
  rule = aws_cloudwatch_event_rule.alarm_rca.name
  arn  = aws_lambda_function.alarm_rca.arn
  retry_policy {
    maximum_retry_attempts       = 2
    maximum_event_age_in_seconds = 3600
  }
}

resource "aws_lambda_permission" "alarm_rca" {
  statement_id  = "AllowProjectAlarmEvents"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.alarm_rca.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.alarm_rca.arn
}

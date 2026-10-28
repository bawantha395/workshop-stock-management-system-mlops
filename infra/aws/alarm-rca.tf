# Rule-based root-cause reports for project CloudWatch alarms.
# Alarm enters ALARM -> EventBridge -> Lambda (DynamoDB guards, read-only
# evidence from CloudWatch, Logs Insights and CloudTrail) -> SNS email.
# The deployment package is committed and checked against its source by
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
  permissions_boundary = var.workload_permissions_boundary_arn
  name                 = "${var.name}-alarm-rca"
  assume_role_policy   = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Principal = { Service = "lambda.amazonaws.com" }, Action = "sts:AssumeRole" }] })
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

# Application error rate from container logs, so the pipeline also covers
# service failures, not only SQS backlog and dead letters.
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

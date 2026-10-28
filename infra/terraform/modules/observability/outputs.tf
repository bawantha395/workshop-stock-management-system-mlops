output "application_log_group_name" {
  value = aws_cloudwatch_log_group.application.name
}

output "application_log_group_arn" {
  value = aws_cloudwatch_log_group.application.arn
}

output "operations_topic_arn" {
  value = aws_sns_topic.operations.arn
}

output "alerts_kms_key_arn" {
  value = aws_kms_key.alerts.arn
}

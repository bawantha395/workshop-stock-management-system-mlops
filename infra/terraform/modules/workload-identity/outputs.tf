output "role_arns" {
  description = "IAM role ARN per workload service account."
  value       = { for k, r in aws_iam_role.pods : k => r.arn }
}

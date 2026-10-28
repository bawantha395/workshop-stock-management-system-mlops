output "automation_bucket" {
  value = aws_s3_bucket.automation.id
}

output "platform_bootstrap_project" {
  value = aws_codebuild_project.platform_bootstrap.name
}

output "github_release_role_arn" {
  value = aws_iam_role.github_release.arn
}

output "github_training_role_arn" {
  value = aws_iam_role.github_training.arn
}

output "github_platform_role_arn" {
  value = aws_iam_role.github_platform.arn
}

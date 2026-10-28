output "repositories" {
  description = "Repository ARN and URL per image name."
  value       = { for k, r in aws_ecr_repository.services : k => { arn = r.arn, url = r.repository_url } }
}

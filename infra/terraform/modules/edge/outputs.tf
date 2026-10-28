output "web_url" {
  value = local.web_url
}

output "cloudfront_domain_name" {
  value = aws_cloudfront_distribution.web.domain_name
}

output "cloudfront_distribution_id" {
  value = aws_cloudfront_distribution.web.id
}

output "cloudfront_distribution_arn" {
  value = aws_cloudfront_distribution.web.arn
}

output "api_certificate_arn" {
  value = aws_acm_certificate_validation.api.certificate_arn
}

output "admin_certificate_arn" {
  value = length(local.admin_domains) == 0 ? "" : aws_acm_certificate_validation.admin[0].certificate_arn
}

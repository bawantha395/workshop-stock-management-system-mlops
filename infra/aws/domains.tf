locals {
  admin_domains = compact([var.argocd_domain, var.grafana_domain])
  web_url       = var.web_domain == "" ? "https://${aws_cloudfront_distribution.web.domain_name}" : "https://${var.web_domain}"
}
resource "aws_acm_certificate" "web" {
  count             = var.web_domain == "" ? 0 : 1
  provider          = aws.cloudfront_acm
  domain_name       = var.web_domain
  validation_method = "DNS"
  lifecycle { create_before_destroy = true }
}
resource "aws_route53_record" "web_certificate" {
  for_each        = var.web_domain == "" ? {} : { for d in aws_acm_certificate.web[0].domain_validation_options : d.domain_name => d }
  zone_id         = var.route53_zone_id
  name            = each.value.resource_record_name
  type            = each.value.resource_record_type
  records         = [each.value.resource_record_value]
  ttl             = 60
  allow_overwrite = true
}
resource "aws_acm_certificate_validation" "web" {
  count                   = var.web_domain == "" ? 0 : 1
  provider                = aws.cloudfront_acm
  certificate_arn         = aws_acm_certificate.web[0].arn
  validation_record_fqdns = [for r in aws_route53_record.web_certificate : r.fqdn]
}
resource "aws_route53_record" "web" {
  count   = var.web_domain == "" ? 0 : 1
  zone_id = var.route53_zone_id
  name    = var.web_domain
  type    = "A"
  alias {
    name                   = aws_cloudfront_distribution.web.domain_name
    zone_id                = aws_cloudfront_distribution.web.hosted_zone_id
    evaluate_target_health = false
  }
}
resource "aws_acm_certificate" "admin" {
  count                     = length(local.admin_domains) == 0 ? 0 : 1
  domain_name               = local.admin_domains[0]
  subject_alternative_names = slice(local.admin_domains, 1, length(local.admin_domains))
  validation_method         = "DNS"
  lifecycle {
    create_before_destroy = true
    precondition {
      condition     = length(var.admin_allowed_cidrs) > 0
      error_message = "Set admin_allowed_cidrs to your public office/home IP range before enabling dashboard domains."
    }
  }
}
resource "aws_route53_record" "admin_certificate" {
  for_each        = length(local.admin_domains) == 0 ? {} : { for d in aws_acm_certificate.admin[0].domain_validation_options : d.domain_name => d }
  zone_id         = var.route53_zone_id
  name            = each.value.resource_record_name
  type            = each.value.resource_record_type
  records         = [each.value.resource_record_value]
  ttl             = 60
  allow_overwrite = true
}
resource "aws_acm_certificate_validation" "admin" {
  count                   = length(local.admin_domains) == 0 ? 0 : 1
  certificate_arn         = aws_acm_certificate.admin[0].arn
  validation_record_fqdns = [for r in aws_route53_record.admin_certificate : r.fqdn]
}

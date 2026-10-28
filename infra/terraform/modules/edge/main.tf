# Public entry points: CloudFront for the React app (private S3 origin),
# TLS certificates for the web, API and admin hostnames, and DNS records.
# CloudFront certificates must live in us-east-1 (aws.us_east_1 provider).

locals {
  admin_domains = compact([var.argocd_domain, var.grafana_domain])
  web_url       = var.web_domain == "" ? "https://${aws_cloudfront_distribution.web.domain_name}" : "https://${var.web_domain}"
}

# ---------- React app on CloudFront ----------
resource "aws_cloudfront_origin_access_control" "web" {
  name                              = var.name
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_distribution" "web" {
  aliases             = var.web_domain == "" ? [] : [var.web_domain]
  enabled             = true
  default_root_object = "index.html"
  price_class         = "PriceClass_100"
  origin {
    domain_name              = var.web_bucket.regional_domain_name
    origin_id                = "private-react"
    origin_access_control_id = aws_cloudfront_origin_access_control.web.id
  }
  default_cache_behavior {
    allowed_methods        = ["GET", "HEAD", "OPTIONS"]
    cached_methods         = ["GET", "HEAD"]
    target_origin_id       = "private-react"
    viewer_protocol_policy = "redirect-to-https"
    compress               = true
    cache_policy_id        = "658327ea-f89d-4fab-a63d-7e88639e58f6" # Managed-CachingOptimized
  }
  # Single-page app: unknown paths return index.html.
  custom_error_response {
    error_code            = 403
    response_code         = 200
    response_page_path    = "/index.html"
    error_caching_min_ttl = 0
  }
  restrictions {
    geo_restriction { restriction_type = "none" }
  }
  viewer_certificate {
    cloudfront_default_certificate = var.web_domain == ""
    acm_certificate_arn            = var.web_domain == "" ? null : aws_acm_certificate_validation.web[0].certificate_arn
    ssl_support_method             = var.web_domain == "" ? null : "sni-only"
    minimum_protocol_version       = var.web_domain == "" ? "TLSv1" : "TLSv1.2_2021"
  }
}

resource "aws_s3_bucket_policy" "web" {
  bucket = var.web_bucket.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Principal = { Service = "cloudfront.amazonaws.com" }, Action = "s3:GetObject", Resource = "${var.web_bucket.arn}/*", Condition = { StringEquals = { "AWS:SourceArn" = aws_cloudfront_distribution.web.arn } } },
    { Effect = "Deny", Principal = "*", Action = "s3:*", Resource = [var.web_bucket.arn, "${var.web_bucket.arn}/*"], Condition = { Bool = { "aws:SecureTransport" = "false" } } }
  ] })
}

# ---------- Web certificate (us-east-1) and DNS ----------
resource "aws_acm_certificate" "web" {
  count             = var.web_domain == "" ? 0 : 1
  provider          = aws.us_east_1
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
  provider                = aws.us_east_1
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

# ---------- API certificate (used by the Kubernetes ALB ingress) ----------
resource "aws_acm_certificate" "api" {
  domain_name       = var.api_domain
  validation_method = "DNS"
  lifecycle { create_before_destroy = true }
}

resource "aws_route53_record" "api_certificate" {
  for_each        = { for d in aws_acm_certificate.api.domain_validation_options : d.domain_name => d }
  zone_id         = var.route53_zone_id
  name            = each.value.resource_record_name
  type            = each.value.resource_record_type
  records         = [each.value.resource_record_value]
  ttl             = 60
  allow_overwrite = true
}

resource "aws_acm_certificate_validation" "api" {
  certificate_arn         = aws_acm_certificate.api.arn
  validation_record_fqdns = [for r in aws_route53_record.api_certificate : r.fqdn]
}

# ---------- Admin certificate (Argo CD and Grafana) ----------
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

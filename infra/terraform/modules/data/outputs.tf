output "kms_key_arn" {
  value = aws_kms_key.main.arn
}

output "buckets" {
  description = "media, models and web buckets: id, arn and regional domain name."
  value = { for k, b in aws_s3_bucket.private : k => {
    id                   = b.id
    arn                  = b.arn
    regional_domain_name = b.bucket_regional_domain_name
  } }
}

output "queues" {
  description = "Event queues (stock, catalogue) and their dead-letter queues."
  value = {
    events = { for k, q in aws_sqs_queue.events : k => { name = q.name, arn = q.arn, url = q.url } }
    dead   = { for k, q in aws_sqs_queue.dead : k => { name = q.name, arn = q.arn } }
  }
}

output "database_address" {
  value = aws_db_instance.main.address
}

# RDS creates and rotates the admin password in Secrets Manager.
output "database_master_secret_arn" {
  value = one(aws_db_instance.main.master_user_secret[*].secret_arn)
}

output "database_secret_arns" {
  value = { for k, s in aws_secretsmanager_secret.database : k => s.arn }
}

output "platform_secret_arn" {
  value = aws_secretsmanager_secret.shared.arn
}

output "grafana_secret_arn" {
  value = aws_secretsmanager_secret.grafana.arn
}

output "cache_host" {
  value = aws_elasticache_replication_group.main.primary_endpoint_address
}

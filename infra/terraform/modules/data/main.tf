# Everything that stores application data: the encryption key, S3 buckets,
# SQS queues, PostgreSQL, Redis and the generated application secrets.
#
# protect_data = true  (prod)        deletion protection, final DB snapshot,
#                                    buckets refuse to delete while not empty
# protect_data = false (dev/staging) one-command teardown: no snapshot,
#                                    buckets emptied, secrets deleted at once

locals {
  services = toset(["inventory", "workshop", "vision"])
}

resource "aws_kms_key" "main" {
  description             = "${var.name} application encryption"
  enable_key_rotation     = true
  deletion_window_in_days = var.protect_data ? 30 : 7
}

resource "aws_kms_alias" "main" {
  name          = "alias/${var.name}"
  target_key_id = aws_kms_key.main.key_id
}

# ---------- S3 ----------
resource "aws_s3_bucket" "private" {
  for_each      = toset(["media", "models", "web"])
  bucket        = "${var.name}-${each.key}-${var.account_id}"
  force_destroy = !var.protect_data
}

resource "aws_s3_bucket_public_access_block" "private" {
  for_each                = aws_s3_bucket.private
  bucket                  = each.value.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "private" {
  for_each = aws_s3_bucket.private
  bucket   = each.value.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "private" {
  for_each = aws_s3_bucket.private
  bucket   = each.value.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = each.key == "web" ? "AES256" : "aws:kms"
      kms_master_key_id = each.key == "web" ? null : aws_kms_key.main.arn
    }
    bucket_key_enabled = each.key != "web"
  }
}

# The web bucket policy (CloudFront access + TLS) lives in the edge module.
resource "aws_s3_bucket_policy" "deny_http" {
  for_each = { for k, v in aws_s3_bucket.private : k => v if k != "web" }
  bucket   = each.value.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Sid       = "RequireTLS", Effect = "Deny", Principal = "*", Action = "s3:*",
    Resource  = [each.value.arn, "${each.value.arn}/*"],
    Condition = { Bool = { "aws:SecureTransport" = "false" } }
  }] })
}

# ---------- SQS ----------
resource "aws_sqs_queue" "dead" {
  for_each                  = toset(["stock", "catalogue"])
  name                      = "${var.name}-${each.key}-dlq"
  message_retention_seconds = 1209600
  kms_master_key_id         = aws_kms_key.main.arn
}

resource "aws_sqs_queue" "events" {
  for_each                   = aws_sqs_queue.dead
  name                       = "${var.name}-${each.key}"
  visibility_timeout_seconds = 120
  message_retention_seconds  = 345600
  kms_master_key_id          = aws_kms_key.main.arn
  redrive_policy             = jsonencode({ deadLetterTargetArn = each.value.arn, maxReceiveCount = 5 })
}

# ---------- PostgreSQL ----------
resource "aws_db_subnet_group" "main" {
  name_prefix = "${var.name}-"
  subnet_ids  = var.private_subnet_ids
}

resource "aws_db_instance" "main" {
  identifier                      = var.name
  engine                          = "postgres"
  engine_version                  = "17"
  instance_class                  = var.database_instance_class
  allocated_storage               = 20
  max_allocated_storage           = var.database_max_allocated_storage
  storage_type                    = var.database_storage_type
  db_name                         = "stocklane"
  username                        = "stocklane_admin"
  manage_master_user_password     = true
  master_user_secret_kms_key_id   = aws_kms_key.main.arn
  storage_encrypted               = true
  kms_key_id                      = aws_kms_key.main.arn
  db_subnet_group_name            = aws_db_subnet_group.main.name
  vpc_security_group_ids          = [var.data_security_group_id]
  publicly_accessible             = false
  multi_az                        = var.database_multi_az
  backup_retention_period         = var.database_backup_retention_days
  deletion_protection             = var.protect_data
  skip_final_snapshot             = !var.protect_data
  final_snapshot_identifier       = var.protect_data ? "${var.name}-final-snapshot" : null
  auto_minor_version_upgrade      = true
  enabled_cloudwatch_logs_exports = ["postgresql", "upgrade"]
}

# ---------- Generated secrets ----------
resource "random_password" "database" {
  for_each = local.services
  length   = 40
  special  = false
}

resource "random_password" "internal" {
  length  = 48
  special = false
}

resource "random_password" "capabilities" {
  for_each = toset(["INVENTORY_READ_TOKEN", "INVENTORY_CONTROL_TOKEN"])
  length   = 48
  special  = false
}

resource "random_password" "cache" {
  length  = 40
  special = false
}

resource "random_password" "grafana" {
  length  = 40
  special = false
}

resource "aws_secretsmanager_secret" "grafana" {
  name                    = "${var.name}/grafana/admin"
  kms_key_id              = aws_kms_key.main.arn
  recovery_window_in_days = var.protect_data ? 7 : 0
}

resource "aws_secretsmanager_secret_version" "grafana" {
  secret_id     = aws_secretsmanager_secret.grafana.id
  secret_string = jsonencode({ username = "admin", password = var.demo_admin_credentials ? "admin" : random_password.grafana.result })
}

resource "aws_secretsmanager_secret" "database" {
  for_each                = local.services
  name                    = "${var.name}/${each.key}/database"
  kms_key_id              = aws_kms_key.main.arn
  recovery_window_in_days = var.protect_data ? 7 : 0
}

resource "aws_secretsmanager_secret_version" "database" {
  for_each  = local.services
  secret_id = aws_secretsmanager_secret.database[each.key].id
  secret_string = jsonencode({
    username = each.key, password = random_password.database[each.key].result,
    host     = aws_db_instance.main.address, port = 5432, dbname = "stocklane"
  })
}

resource "aws_secretsmanager_secret" "shared" {
  name                    = "${var.name}/platform"
  kms_key_id              = aws_kms_key.main.arn
  recovery_window_in_days = var.protect_data ? 7 : 0
}

resource "aws_secretsmanager_secret_version" "shared" {
  secret_id = aws_secretsmanager_secret.shared.id
  secret_string = jsonencode(merge(
    { INTERNAL_TOKEN = random_password.internal.result, REDIS_PASSWORD = random_password.cache.result },
    { for k, v in random_password.capabilities : k => v.result }
  ))
}

# ---------- Redis ----------
resource "aws_elasticache_subnet_group" "main" {
  name       = var.name
  subnet_ids = var.private_subnet_ids
}

resource "aws_elasticache_replication_group" "main" {
  replication_group_id        = var.name
  description                 = "Disposable application cache, never inventory authority"
  engine                      = "redis"
  engine_version              = "7.1"
  node_type                   = var.cache_node_type
  num_cache_clusters          = var.cache_node_count
  automatic_failover_enabled  = true
  multi_az_enabled            = true
  preferred_cache_cluster_azs = slice(var.availability_zones, 0, var.cache_node_count)
  subnet_group_name           = aws_elasticache_subnet_group.main.name
  security_group_ids          = [var.data_security_group_id]
  at_rest_encryption_enabled  = true
  kms_key_id                  = aws_kms_key.main.arn
  transit_encryption_enabled  = true
  auth_token                  = random_password.cache.result
}

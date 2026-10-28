# One IAM role per Kubernetes service account, linked with EKS Pod Identity.
# Each policy grants only what that workload needs (least privilege).

locals {
  pod_trust = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect = "Allow", Principal = { Service = "pods.eks.amazonaws.com" }, Action = ["sts:AssumeRole", "sts:TagSession"]
  }] })
  service_accounts = {
    inventory          = { namespace = var.workload_namespace, account = "inventory" }
    workshop           = { namespace = var.workload_namespace, account = "workshop" }
    vision             = { namespace = var.workload_namespace, account = "vision" }
    forecast           = { namespace = var.workload_namespace, account = "forecast" }
    database-bootstrap = { namespace = var.workload_namespace, account = "database-bootstrap" }
    external-secrets   = { namespace = "external-secrets", account = "external-secrets" }
    load-balancer      = { namespace = "kube-system", account = "aws-load-balancer-controller" }
    telemetry          = { namespace = "amazon-cloudwatch", account = "fluent-bit" }
    alertmanager       = { namespace = "monitoring", account = "stocklane-alertmanager" }
  }
  media_arn  = var.buckets["media"].arn
  models_arn = var.buckets["models"].arn
}

resource "aws_iam_role" "pods" {
  permissions_boundary = var.permissions_boundary_arn
  for_each             = local.service_accounts
  name                 = "${var.name}-${each.key}"
  assume_role_policy   = local.pod_trust
}

# Associations exist before the pods start, so credentials are injected on
# first creation. Namespaces and service accounts can be created later.
resource "aws_eks_pod_identity_association" "pods" {
  for_each        = local.service_accounts
  cluster_name    = var.cluster_name
  namespace       = each.value.namespace
  service_account = each.value.account
  role_arn        = aws_iam_role.pods[each.key].arn
}

resource "aws_iam_role_policy" "inventory" {
  name = "publish-inventory-events"
  role = aws_iam_role.pods["inventory"].id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["s3:PutObject"], Resource = "${local.models_arn}/forecast/datasets/*" },
    { Effect = "Allow", Action = ["sqs:SendMessage"], Resource = [for q in var.queues.events : q.arn] },
    { Effect = "Allow", Action = ["kms:GenerateDataKey", "kms:Decrypt"], Resource = var.kms_key_arn }
  ] })
}

resource "aws_iam_role_policy" "workshop" {
  name = "consume-stock-store-invoices"
  role = aws_iam_role.pods["workshop"].id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"], Resource = var.queues.events["stock"].arn },
    { Effect = "Allow", Action = ["s3:PutObject", "s3:GetObject"], Resource = "${local.media_arn}/invoices/*" },
    { Effect = "Allow", Action = ["kms:GenerateDataKey", "kms:Decrypt"], Resource = var.kms_key_arn }
  ] })
}

resource "aws_iam_role_policy" "vision" {
  name = "catalogue-vision-storage"
  role = aws_iam_role.pods["vision"].id
  policy = jsonencode({ Version = "2012-10-17", Statement = concat([
    { Effect = "Allow", Action = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"], Resource = var.queues.events["catalogue"].arn },
    { Effect = "Allow", Action = ["s3:GetObject", "s3:PutObject"], Resource = "${local.media_arn}/images/*" },
    { Effect = "Allow", Action = ["s3:GetObject"], Resource = "${local.models_arn}/releases/*" },
    { Effect = "Allow", Action = ["kms:GenerateDataKey", "kms:Decrypt"], Resource = var.kms_key_arn }
  ], var.bedrock_invoke_arn == "" ? [] : [{ Effect = "Allow", Action = ["bedrock:InvokeModel"], Resource = var.bedrock_invoke_arn }]) })
}

resource "aws_iam_role_policy" "forecast" {
  name = "read-published-stock-forecast"
  role = aws_iam_role.pods["forecast"].id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["s3:ListBucket"], Resource = local.models_arn },
    { Effect = "Allow", Action = ["s3:GetObject"], Resource = "${local.models_arn}/forecast/current.json" },
    { Effect = "Allow", Action = ["kms:Decrypt"], Resource = var.kms_key_arn }
  ] })
}

resource "aws_iam_role_policy" "database_bootstrap" {
  name = "initialise-service-owned-schemas"
  role = aws_iam_role.pods["database-bootstrap"].id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["secretsmanager:GetSecretValue"], Resource = concat(values(var.database_secret_arns), compact([var.database_master_secret_arn])) },
    { Effect = "Allow", Action = ["kms:Decrypt"], Resource = var.kms_key_arn }
  ] })
}

resource "aws_iam_role_policy" "external_secrets" {
  name = "read-application-secrets"
  role = aws_iam_role.pods["external-secrets"].id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"], Resource = concat(values(var.database_secret_arns), [var.platform_secret_arn, var.grafana_secret_arn]) },
    { Effect = "Allow", Action = ["kms:Decrypt"], Resource = var.kms_key_arn }
  ] })
}

resource "aws_iam_role_policy" "load_balancer" {
  name   = "aws-load-balancer-controller"
  role   = aws_iam_role.pods["load-balancer"].id
  policy = file("${path.module}/policies/load-balancer-controller.json")
}

resource "aws_iam_role_policy" "telemetry" {
  name = "write-container-logs"
  role = aws_iam_role.pods["telemetry"].id
  policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect   = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents", "logs:DescribeLogStreams"],
    Resource = "${var.application_log_group_arn}:*"
  }] })
}

resource "aws_iam_role_policy" "alertmanager" {
  name = "publish-platform-alerts"
  role = aws_iam_role.pods["alertmanager"].id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = "sns:Publish", Resource = var.operations_topic_arn },
    { Effect = "Allow", Action = ["kms:Decrypt", "kms:GenerateDataKey*"], Resource = var.alerts_kms_key_arn }
  ] })
}

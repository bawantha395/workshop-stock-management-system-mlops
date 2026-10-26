data "aws_iam_policy_document" "eks_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["eks.amazonaws.com"]
    }
  }
}
resource "aws_iam_role" "eks" {
  permissions_boundary = var.workload_permissions_boundary_arn
  name                 = "${var.name}-cluster"
  assume_role_policy   = data.aws_iam_policy_document.eks_trust.json
}
resource "aws_iam_role_policy_attachment" "eks" {
  role       = aws_iam_role.eks.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/AmazonEKSClusterPolicy"
}
resource "aws_cloudwatch_log_group" "eks" {
  name              = "/aws/eks/${var.name}/cluster"
  retention_in_days = 14
}
resource "aws_eks_cluster" "main" {
  kubernetes_network_config { service_ipv4_cidr = var.service_ipv4_cidr }
  name                      = var.name
  version                   = var.eks_version
  role_arn                  = aws_iam_role.eks.arn
  enabled_cluster_log_types = ["api", "audit", "authenticator", "controllerManager", "scheduler"]
  access_config { authentication_mode = "API" }
  vpc_config {
    subnet_ids              = aws_subnet.private[*].id
    endpoint_private_access = true
    endpoint_public_access  = true
    public_access_cidrs     = var.operator_cidrs
  }
  encryption_config {
    resources = ["secrets"]
    provider { key_arn = aws_kms_key.main.arn }
  }
  depends_on = [aws_iam_role_policy_attachment.eks, aws_cloudwatch_log_group.eks]
}
resource "aws_eks_access_entry" "operator" {
  cluster_name  = aws_eks_cluster.main.name
  principal_arn = var.administrator_arn
  type          = "STANDARD"
}
resource "aws_eks_access_policy_association" "operator" {
  cluster_name  = aws_eks_cluster.main.name
  principal_arn = aws_eks_access_entry.operator.principal_arn
  policy_arn    = "arn:${data.aws_partition.current.partition}:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"
  access_scope { type = "cluster" }
}
resource "aws_iam_role" "nodes" {
  permissions_boundary = var.workload_permissions_boundary_arn
  name                 = "${var.name}-nodes"
  assume_role_policy   = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Principal = { Service = "ec2.amazonaws.com" }, Action = "sts:AssumeRole" }] })
}
resource "aws_iam_role_policy_attachment" "nodes" {
  for_each   = toset(["AmazonEKSWorkerNodePolicy", "AmazonEC2ContainerRegistryPullOnly", "AmazonEKS_CNI_Policy"])
  role       = aws_iam_role.nodes.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/${each.key}"
}
resource "aws_launch_template" "workers" {
  name_prefix = "${var.name}-workers-"
  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
  }
  block_device_mappings {
    device_name = "/dev/xvda"
    ebs {
      volume_size           = 30
      volume_type           = "gp3"
      encrypted             = true
      delete_on_termination = true
    }
  }
}
resource "aws_eks_node_group" "main" {
  cluster_name           = aws_eks_cluster.main.name
  node_group_name_prefix = "cpu-workers-"
  node_role_arn          = aws_iam_role.nodes.arn
  subnet_ids             = aws_subnet.private[*].id
  instance_types         = [var.node_instance_type]
  capacity_type          = "ON_DEMAND"
  ami_type               = "AL2023_x86_64_STANDARD"
  launch_template {
    id      = aws_launch_template.workers.id
    version = tostring(aws_launch_template.workers.latest_version)
  }
  scaling_config {
    desired_size = var.node_desired_size
    min_size     = var.node_min_size
    max_size     = var.node_max_size
  }
  update_config { max_unavailable = 1 }
  # Instance types are immutable. A unique name lets EKS create replacement
  # capacity before draining the previous group; temporary quota is required.
  lifecycle { create_before_destroy = true }
  depends_on = [aws_iam_role_policy_attachment.nodes, aws_nat_gateway.main]
}
resource "aws_eks_addon" "main" {
  for_each                    = toset(["vpc-cni", "coredns", "kube-proxy", "eks-pod-identity-agent", "aws-ebs-csi-driver"])
  cluster_name                = aws_eks_cluster.main.name
  addon_name                  = each.key
  configuration_values        = each.key == "vpc-cni" ? jsonencode({ enableNetworkPolicy = "true" }) : null
  resolve_conflicts_on_update = "PRESERVE"
  depends_on                  = [aws_eks_node_group.main, aws_eks_pod_identity_association.pods, aws_iam_role_policy_attachment.ebs]
}
locals {
  workload_namespace = var.environment == "production" ? "stocklane" : "stocklane-${var.environment}"
  pod_trust          = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Principal = { Service = "pods.eks.amazonaws.com" }, Action = ["sts:AssumeRole", "sts:TagSession"] }] })
  platform_accounts = {
    inventory          = { namespace = local.workload_namespace, account = "inventory" }
    workshop           = { namespace = local.workload_namespace, account = "workshop" }
    vision             = { namespace = local.workload_namespace, account = "vision" }
    forecast           = { namespace = local.workload_namespace, account = "forecast" }
    external-secrets   = { namespace = "external-secrets", account = "external-secrets" }
    load-balancer      = { namespace = "kube-system", account = "aws-load-balancer-controller" }
    ebs                = { namespace = "kube-system", account = "ebs-csi-controller-sa" }
    database-bootstrap = { namespace = local.workload_namespace, account = "database-bootstrap" }
    telemetry          = { namespace = "amazon-cloudwatch", account = "fluent-bit" }
    alertmanager       = { namespace = "monitoring", account = "stocklane-alertmanager" }
  }
}
resource "aws_iam_role" "pods" {
  permissions_boundary = var.workload_permissions_boundary_arn
  for_each             = local.platform_accounts
  name                 = "${var.name}-${each.key}"
  assume_role_policy   = local.pod_trust
}
resource "aws_eks_pod_identity_association" "pods" {
  for_each        = local.platform_accounts
  cluster_name    = aws_eks_cluster.main.name
  namespace       = each.value.namespace
  service_account = each.value.account
  role_arn        = aws_iam_role.pods[each.key].arn
  # Associations must precede add-on Pods so their credentials are injected on
  # first creation. Namespace/service-account objects may be created later.
  depends_on = [aws_eks_cluster.main]
}
resource "aws_iam_role_policy_attachment" "ebs" {
  role       = aws_iam_role.pods["ebs"].name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/service-role/AmazonEBSCSIDriverPolicy"
}
resource "aws_iam_role_policy" "inventory" {
  name = "publish-inventory-events"
  role = aws_iam_role.pods["inventory"].id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["s3:PutObject"], Resource = "${aws_s3_bucket.private["models"].arn}/forecast/datasets/*" },
    { Effect = "Allow", Action = ["sqs:SendMessage"], Resource = [for q in aws_sqs_queue.events : q.arn] },
    { Effect = "Allow", Action = ["kms:GenerateDataKey", "kms:Decrypt"], Resource = aws_kms_key.main.arn }
  ] })
}
resource "aws_iam_role_policy" "workshop" {
  name = "consume-stock-store-invoices"
  role = aws_iam_role.pods["workshop"].id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"], Resource = aws_sqs_queue.events["stock"].arn },
    { Effect = "Allow", Action = ["s3:PutObject", "s3:GetObject"], Resource = "${aws_s3_bucket.private["media"].arn}/invoices/*" },
    { Effect = "Allow", Action = ["kms:GenerateDataKey", "kms:Decrypt"], Resource = aws_kms_key.main.arn }
  ] })
}
resource "aws_iam_role_policy" "vision" {
  name = "catalogue-vision-storage"
  role = aws_iam_role.pods["vision"].id
  policy = jsonencode({ Version = "2012-10-17", Statement = concat([
    { Effect = "Allow", Action = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"], Resource = aws_sqs_queue.events["catalogue"].arn },
    { Effect = "Allow", Action = ["s3:GetObject", "s3:PutObject"], Resource = "${aws_s3_bucket.private["media"].arn}/images/*" },
    { Effect = "Allow", Action = ["s3:GetObject"], Resource = "${aws_s3_bucket.private["models"].arn}/releases/*" },
    { Effect = "Allow", Action = ["kms:GenerateDataKey", "kms:Decrypt"], Resource = aws_kms_key.main.arn }
  ], local.bedrock_invoke_arn == "" ? [] : [{ Effect = "Allow", Action = ["bedrock:InvokeModel"], Resource = local.bedrock_invoke_arn }]) })
}
resource "aws_iam_role_policy" "secrets" {
  name = "read-application-secrets"
  role = aws_iam_role.pods["external-secrets"].id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"], Resource = concat([for x in aws_secretsmanager_secret.database : x.arn], [aws_secretsmanager_secret.shared.arn, aws_secretsmanager_secret.grafana.arn]) },
    { Effect = "Allow", Action = ["kms:Decrypt"], Resource = aws_kms_key.main.arn }
  ] })
}
resource "aws_iam_role_policy" "database_bootstrap" {
  name = "initialise-service-owned-schemas"
  role = aws_iam_role.pods["database-bootstrap"].id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["secretsmanager:GetSecretValue"], Resource = concat([for x in aws_secretsmanager_secret.database : x.arn], [aws_db_instance.main.master_user_secret[0].secret_arn]) },
    { Effect = "Allow", Action = ["kms:Decrypt"], Resource = aws_kms_key.main.arn }
  ] })
}
resource "aws_iam_role_policy" "load_balancer" {
  name   = "aws-load-balancer-controller"
  role   = aws_iam_role.pods["load-balancer"].id
  policy = file("${path.module}/policies/load-balancer-controller.json")
}
resource "aws_cloudwatch_log_group" "application" {
  name              = "/stocklane/${var.name}/containers"
  retention_in_days = 7
}
resource "aws_iam_role_policy" "telemetry" {
  name   = "write-container-logs"
  role   = aws_iam_role.pods["telemetry"].id
  policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents", "logs:DescribeLogStreams"], Resource = "${aws_cloudwatch_log_group.application.arn}:*" }] })
}

resource "aws_iam_role_policy" "forecast" {
  name = "read-published-stock-forecast"
  role = aws_iam_role.pods["forecast"].id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["s3:ListBucket"], Resource = aws_s3_bucket.private["models"].arn },
    { Effect = "Allow", Action = ["s3:GetObject"], Resource = "${aws_s3_bucket.private["models"].arn}/forecast/current.json" },
    { Effect = "Allow", Action = ["kms:Decrypt"], Resource = aws_kms_key.main.arn }
  ] })
}

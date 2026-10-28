# EKS control plane, managed worker nodes and core add-ons. Application pod
# permissions live in the workload-identity module; only the EBS CSI driver
# identity is here because the add-on needs it at creation time.

# ---------- Control plane ----------
resource "aws_iam_role" "cluster" {
  permissions_boundary = var.permissions_boundary_arn
  name                 = "${var.name}-cluster"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect = "Allow", Principal = { Service = "eks.amazonaws.com" }, Action = "sts:AssumeRole"
  }] })
}

resource "aws_iam_role_policy_attachment" "cluster" {
  role       = aws_iam_role.cluster.name
  policy_arn = "arn:${var.partition}:iam::aws:policy/AmazonEKSClusterPolicy"
}

resource "aws_cloudwatch_log_group" "cluster" {
  name              = "/aws/eks/${var.name}/cluster"
  retention_in_days = 14
}

resource "aws_eks_cluster" "main" {
  name                      = var.name
  version                   = var.eks_version
  role_arn                  = aws_iam_role.cluster.arn
  enabled_cluster_log_types = ["api", "audit", "authenticator", "controllerManager", "scheduler"]
  access_config { authentication_mode = "API" }
  kubernetes_network_config { service_ipv4_cidr = var.service_ipv4_cidr }
  vpc_config {
    subnet_ids              = var.private_subnet_ids
    endpoint_private_access = true
    endpoint_public_access  = true
    public_access_cidrs     = var.operator_cidrs
  }
  encryption_config {
    resources = ["secrets"]
    provider { key_arn = var.kms_key_arn }
  }
  depends_on = [aws_iam_role_policy_attachment.cluster, aws_cloudwatch_log_group.cluster]
}

# The human operator gets cluster-admin through an EKS access entry.
resource "aws_eks_access_entry" "operator" {
  cluster_name  = aws_eks_cluster.main.name
  principal_arn = var.administrator_arn
  type          = "STANDARD"
}

resource "aws_eks_access_policy_association" "operator" {
  cluster_name  = aws_eks_cluster.main.name
  principal_arn = aws_eks_access_entry.operator.principal_arn
  policy_arn    = "arn:${var.partition}:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"
  access_scope { type = "cluster" }
}

# ---------- Worker nodes ----------
resource "aws_iam_role" "nodes" {
  permissions_boundary = var.permissions_boundary_arn
  name                 = "${var.name}-nodes"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect = "Allow", Principal = { Service = "ec2.amazonaws.com" }, Action = "sts:AssumeRole"
  }] })
}

resource "aws_iam_role_policy_attachment" "nodes" {
  for_each   = toset(["AmazonEKSWorkerNodePolicy", "AmazonEC2ContainerRegistryPullOnly", "AmazonEKS_CNI_Policy"])
  role       = aws_iam_role.nodes.name
  policy_arn = "arn:${var.partition}:iam::aws:policy/${each.key}"
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
  subnet_ids             = var.private_subnet_ids
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
  # Instance types are immutable: a new uniquely named group comes up before
  # the old one drains.
  lifecycle { create_before_destroy = true }
  depends_on = [aws_iam_role_policy_attachment.nodes]
}

# ---------- Core add-ons ----------
resource "aws_iam_role" "ebs_csi" {
  permissions_boundary = var.permissions_boundary_arn
  name                 = "${var.name}-ebs"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect = "Allow", Principal = { Service = "pods.eks.amazonaws.com" }, Action = ["sts:AssumeRole", "sts:TagSession"]
  }] })
}

resource "aws_iam_role_policy_attachment" "ebs_csi" {
  role       = aws_iam_role.ebs_csi.name
  policy_arn = "arn:${var.partition}:iam::aws:policy/service-role/AmazonEBSCSIDriverPolicy"
}

resource "aws_eks_pod_identity_association" "ebs_csi" {
  cluster_name    = aws_eks_cluster.main.name
  namespace       = "kube-system"
  service_account = "ebs-csi-controller-sa"
  role_arn        = aws_iam_role.ebs_csi.arn
}

resource "aws_eks_addon" "main" {
  for_each                    = toset(["vpc-cni", "coredns", "kube-proxy", "eks-pod-identity-agent", "aws-ebs-csi-driver"])
  cluster_name                = aws_eks_cluster.main.name
  addon_name                  = each.key
  configuration_values        = each.key == "vpc-cni" ? jsonencode({ enableNetworkPolicy = "true" }) : null
  resolve_conflicts_on_update = "PRESERVE"
  depends_on                  = [aws_eks_node_group.main, aws_eks_pod_identity_association.ebs_csi, aws_iam_role_policy_attachment.ebs_csi]
}

# ---------- Database and Redis access from the cluster ----------
resource "aws_vpc_security_group_ingress_rule" "postgres" {
  security_group_id            = var.data_security_group_id
  referenced_security_group_id = aws_eks_cluster.main.vpc_config[0].cluster_security_group_id
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
}

resource "aws_vpc_security_group_ingress_rule" "cache" {
  security_group_id            = var.data_security_group_id
  referenced_security_group_id = aws_eks_cluster.main.vpc_config[0].cluster_security_group_id
  ip_protocol                  = "tcp"
  from_port                    = 6379
  to_port                      = 6379
}

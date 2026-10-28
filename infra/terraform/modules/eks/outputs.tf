output "cluster_name" {
  value = aws_eks_cluster.main.name
}

output "cluster_arn" {
  value = aws_eks_cluster.main.arn
}

output "cluster_security_group_id" {
  value = aws_eks_cluster.main.vpc_config[0].cluster_security_group_id
}

output "service_ipv4_cidr" {
  value = aws_eks_cluster.main.kubernetes_network_config[0].service_ipv4_cidr
}

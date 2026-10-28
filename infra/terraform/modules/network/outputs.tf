output "vpc_id" {
  value = aws_vpc.main.id
}

output "public_subnet_ids" {
  value = aws_subnet.public[*].id
}

# Workloads placed in private subnets need a working route to the internet
# (image pulls, AWS APIs). Publishing the IDs only after the NAT routes exist
# makes every consumer wait for them without explicit depends_on.
output "private_subnet_ids" {
  value      = aws_subnet.private[*].id
  depends_on = [aws_route_table_association.private, aws_nat_gateway.main]
}

output "private_subnet_arns" {
  value      = aws_subnet.private[*].arn
  depends_on = [aws_route_table_association.private, aws_nat_gateway.main]
}

output "data_security_group_id" {
  value = aws_security_group.data.id
}

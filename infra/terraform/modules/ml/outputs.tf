output "training_role_arn" {
  value = aws_iam_role.training.arn
}

output "vision_model_group" {
  value = { name = aws_sagemaker_model_package_group.vision.model_package_group_name, arn = aws_sagemaker_model_package_group.vision.arn }
}

output "bedrock_invoke_arn" {
  value = local.bedrock_invoke_arn
}

output "bedrock_model_id" {
  value = local.bedrock_runtime_model_id
}

output "bedrock_region" {
  value = local.bedrock_region
}

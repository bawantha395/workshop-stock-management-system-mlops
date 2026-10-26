locals {
  bedrock_invoke_arn       = var.bedrock_model_arn != "" ? var.bedrock_model_arn : (var.bedrock_model_id == "" ? "" : "arn:${data.aws_partition.current.partition}:bedrock:${var.region}::foundation-model/${var.bedrock_model_id}")
  bedrock_runtime_model_id = var.bedrock_model_id != "" ? var.bedrock_model_id : var.bedrock_model_arn
}

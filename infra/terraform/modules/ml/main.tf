# SageMaker training role, the two Model Registry groups and the Bedrock model
# the vision service may call. Training runs as SageMaker Processing jobs on
# ml.t3 instances (see mlops/sagemaker_jobs.py).

locals {
  bedrock_region           = var.bedrock_region != "" ? var.bedrock_region : var.region
  bedrock_runtime_model_id = var.bedrock_model_id != "" ? var.bedrock_model_id : var.bedrock_model_arn
  bedrock_invoke_arn = var.bedrock_model_arn != "" ? var.bedrock_model_arn : (
    var.bedrock_model_id == "" ? "" : "arn:${var.partition}:bedrock:${local.bedrock_region}::foundation-model/${var.bedrock_model_id}"
  )
}

resource "aws_iam_role" "training" {
  permissions_boundary = var.permissions_boundary_arn
  name                 = "${var.name}-sagemaker-training"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect = "Allow", Principal = { Service = "sagemaker.amazonaws.com" }, Action = "sts:AssumeRole"
  }] })
}

resource "aws_iam_role_policy" "training" {
  name = "train-from-reviewed-datasets"
  role = aws_iam_role.training.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["s3:ListBucket"], Resource = var.models_bucket_arn },
    { Effect = "Allow", Action = ["s3:GetObject", "s3:PutObject"], Resource = "${var.models_bucket_arn}/*" },
    { Effect = "Allow", Action = ["ecr:GetAuthorizationToken"], Resource = "*" },
    { Effect = "Allow", Action = ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer", "ecr:BatchCheckLayerAvailability"], Resource = var.training_repository_arn },
    { Effect = "Allow", Action = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"], Resource = "arn:${var.partition}:logs:${var.region}:${var.account_id}:log-group:/aws/sagemaker/*" },
    { Effect = "Allow", Action = ["kms:GenerateDataKey", "kms:Decrypt", "kms:Encrypt"], Resource = var.kms_key_arn }
  ] })
}

resource "aws_sagemaker_model_package_group" "vision" {
  model_package_group_name        = "${var.name}-visual-sku"
  model_package_group_description = "Versioned visual encoder and trained same-SKU similarity calibration; manual approval required"
}

resource "aws_sagemaker_model_package_group" "forecast" {
  model_package_group_name        = "${var.name}-stock-forecast"
  model_package_group_description = "Stock usage forecasting with temporal evaluation and weekday baseline gates"
}

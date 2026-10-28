output "user_pool_id" {
  value = aws_cognito_user_pool.main.id
}

output "domain" {
  value = aws_cognito_user_pool_domain.main.domain
}

output "web_client_id" {
  value = aws_cognito_user_pool_client.web.id
}

output "camera_client_id" {
  value = aws_cognito_user_pool_client.camera.id
}

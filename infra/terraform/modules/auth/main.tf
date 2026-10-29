# Cognito user pool for staff sign-in (MFA required, admin-created users only)
# and a machine client for enrolled workshop cameras.

resource "aws_cognito_user_pool" "main" {
  name                     = var.name
  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]
  admin_create_user_config { allow_admin_create_user_only = true }
  password_policy {
    minimum_length    = 14
    require_lowercase = true
    require_uppercase = true
    require_numbers   = true
    require_symbols   = true
  }
  mfa_configuration = "ON"
  software_token_mfa_configuration { enabled = true }
}

resource "aws_cognito_user_pool_domain" "main" {
  domain       = "${var.name}-${var.account_id}"
  user_pool_id = aws_cognito_user_pool.main.id
}

resource "aws_cognito_user_group" "staff" {
  for_each     = toset(["OWNER", "MECHANIC"])
  user_pool_id = aws_cognito_user_pool.main.id
  name         = each.key
}

# The first owner. Cognito emails a temporary password; MFA is set up at first sign-in.
resource "aws_cognito_user" "owner" {
  count                    = var.owner_email == "" ? 0 : 1
  user_pool_id             = aws_cognito_user_pool.main.id
  username                 = var.owner_email
  desired_delivery_mediums = ["EMAIL"]
  attributes = {
    email          = var.owner_email
    email_verified = "true"
  }
}

resource "aws_cognito_user_in_group" "owner" {
  count        = var.owner_email == "" ? 0 : 1
  user_pool_id = aws_cognito_user_pool.main.id
  group_name   = aws_cognito_user_group.staff["OWNER"].name
  username     = aws_cognito_user.owner[0].username
}

resource "aws_cognito_user_pool_client" "web" {
  name                                 = "react-pwa"
  user_pool_id                         = aws_cognito_user_pool.main.id
  generate_secret                      = false
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes                 = ["openid", "email", "profile"]
  supported_identity_providers         = ["COGNITO"]
  callback_urls                        = [for url in var.app_urls : "${url}/auth/callback"]
  logout_urls                          = var.app_urls
  prevent_user_existence_errors        = "ENABLED"
  enable_token_revocation              = true
  access_token_validity                = 15
  id_token_validity                    = 15
  refresh_token_validity               = 7
  token_validity_units {
    access_token  = "minutes"
    id_token      = "minutes"
    refresh_token = "days"
  }
}

resource "aws_cognito_resource_server" "camera" {
  identifier   = "stocklane"
  name         = "Workshop capture API"
  user_pool_id = aws_cognito_user_pool.main.id
  scope {
    scope_name        = "capture"
    scope_description = "Upload capture evidence; no stock or invoice approval"
  }
}

resource "aws_cognito_user_pool_client" "camera" {
  name                                 = "enrolled-workshop-camera"
  user_pool_id                         = aws_cognito_user_pool.main.id
  generate_secret                      = true
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["client_credentials"]
  allowed_oauth_scopes                 = ["${aws_cognito_resource_server.camera.identifier}/capture"]
  access_token_validity                = 60
  token_validity_units { access_token = "minutes" }
}

# The legacy pool keeps its users; the new app gets its own public client for
# server-side USER_PASSWORD_AUTH (the legacy SPA's client stays untouched).
resource "aws_cognito_user_pool_client" "web" {
  name         = "${var.name}-web"
  user_pool_id = var.cognito_user_pool_id

  generate_secret = false
  explicit_auth_flows = [
    "ALLOW_USER_PASSWORD_AUTH",
    "ALLOW_REFRESH_TOKEN_AUTH",
  ]

  refresh_token_validity = var.cognito_refresh_token_days
  token_validity_units {
    refresh_token = "days"
  }
}

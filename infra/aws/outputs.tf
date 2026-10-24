output "invoke_url" {
  description = "Default execute-api URL (smoke test before the DNS cutover)."
  value       = aws_apigatewayv2_stage.default.invoke_url
}

output "hosted_zone_id" {
  value = data.aws_route53_zone.main.zone_id
}

output "dns_targets" {
  description = "Route53 alias targets for scripts/cutover_dns.sh."
  value = {
    for name, d in aws_apigatewayv2_domain_name.web : name => {
      target_domain_name = d.domain_name_configuration[0].target_domain_name
      hosted_zone_id     = d.domain_name_configuration[0].hosted_zone_id
    }
  }
}

output "table_name" {
  value = aws_dynamodb_table.main.name
}

output "lambda_function_name" {
  value = aws_lambda_function.web.function_name
}

output "cognito_client_id" {
  value = aws_cognito_user_pool_client.web.id
}

output "legacy_x_api_key" {
  value     = random_password.legacy_x_api_key.result
  sensitive = true
}

output "github_deploy_role_arn" {
  description = "Set as the AWS_DEPLOY_ROLE_ARN repository variable to enable the deploy job."
  value       = aws_iam_role.github_deploy.arn
}

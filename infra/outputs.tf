output "api_gateway_url" {
  value = aws_apigatewayv2_stage.default.invoke_url
}

output "ecr_repository_url" {
  value = aws_ecr_repository.app.repository_url
}

output "lambda_function_name" {
  value = aws_lambda_function.app.function_name
}

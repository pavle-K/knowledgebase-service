resource "aws_apigatewayv2_api" "app" {
  name          = var.service_name
  protocol_type = "HTTP"
}

locals {
  api_throttle_rate_limit  = var.api_throttle_rate_limit != "" ? tonumber(var.api_throttle_rate_limit) : 20
  api_throttle_burst_limit = var.api_throttle_burst_limit != "" ? tonumber(var.api_throttle_burst_limit) : 40
}

resource "aws_apigatewayv2_integration" "lambda" {
  api_id                 = aws_apigatewayv2_api.app.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.app.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "default" {
  api_id    = aws_apigatewayv2_api.app.id
  route_key = "$default"
  target    = "integrations/${aws_apigatewayv2_integration.lambda.id}"
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.app.id
  name        = "$default"
  auto_deploy = true

  # Global, not per-key - a circuit breaker against a flood, not a per-consumer
  # quota. Steady-state requests/sec and the burst bucket size above it.
  default_route_settings {
    throttling_rate_limit  = local.api_throttle_rate_limit
    throttling_burst_limit = local.api_throttle_burst_limit
  }
}

resource "aws_lambda_permission" "api_gateway" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.app.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.app.execution_arn}/*/*"
}

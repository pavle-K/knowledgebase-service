resource "github_repository_webhook" "ingestion" {
  for_each = toset(var.github_webhook_repos)

  repository = each.value

  configuration {
    url          = "${aws_apigatewayv2_stage.default.invoke_url}/webhook/github"
    content_type = "json"
    secret       = var.github_webhook_secret
    insecure_ssl = false
  }

  active = true
  events = ["push", "repository", "release"]
}

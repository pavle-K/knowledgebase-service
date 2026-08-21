resource "aws_ecr_repository" "app" {
  name                 = var.service_name
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_iam_role" "lambda_exec" {
  name = "${var.service_name}-lambda-exec"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "lambda.amazonaws.com"
      }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_basic_execution" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_lambda_function" "app" {
  function_name = var.service_name
  role          = aws_iam_role.lambda_exec.arn
  package_type  = "Image"
  # Tag-based, not digest-pinned: pinning via a data source would require the
  # image to already exist even just to run `terraform plan`, which breaks on
  # a first-ever deploy before anything's been pushed. The deploy workflow
  # guarantees the image with this tag exists before the full apply runs.
  image_uri   = "${aws_ecr_repository.app.repository_url}:${var.image_tag}"
  timeout     = 30
  memory_size = 512

  environment {
    variables = {
      DATABASE_URL_RW       = var.database_url_rw
      DATABASE_URL_RO       = var.database_url_ro
      ANTHROPIC_API_KEY     = var.anthropic_api_key
      OPENAI_API_KEY        = var.openai_api_key
      API_AUTH_KEY          = var.api_auth_key
      GITHUB_TOKEN          = var.github_token
      GITHUB_WEBHOOK_SECRET = var.github_webhook_secret
      EMBEDDING_PROVIDER    = var.embedding_provider
      LLM_MODEL             = var.llm_model
    }
  }
}

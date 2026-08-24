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
      DATABASE_URL_RW        = var.database_url_rw
      DATABASE_URL_RO        = var.database_url_ro
      DATABASE_URL_RO_PUBLIC = var.database_url_ro_public
      ANTHROPIC_API_KEY      = var.anthropic_api_key
      OPENAI_API_KEY         = var.openai_api_key
      API_AUTH_KEY           = var.api_auth_key
      API_ADMIN_KEY          = var.api_admin_key
      GITHUB_TOKEN           = var.github_token
      GITHUB_WEBHOOK_SECRET  = var.github_webhook_secret
      EMBEDDING_PROVIDER     = var.embedding_provider
      LLM_MODEL              = var.llm_model
      MAX_QUERY_LENGTH       = var.max_query_length
      WEBHOOK_QUEUE_URL      = aws_sqs_queue.webhook_events.url
      LANGFUSE_PUBLIC_KEY    = var.langfuse_public_key
      LANGFUSE_SECRET_KEY    = var.langfuse_secret_key
      LANGFUSE_BASE_URL      = var.langfuse_base_url
    }
  }
}

# Consumes src.api.webhook's enqueued events off SQS (infra/sqs.tf) - no API
# Gateway in front of it, so it isn't bound by the 30s integration timeout
# that made synchronous webhook ingestion time out and lose data.
resource "aws_lambda_function" "worker" {
  function_name = "${var.service_name}-worker"
  role          = aws_iam_role.worker_lambda_exec.arn
  package_type  = "Image"
  image_uri     = "${aws_ecr_repository.app.repository_url}:${var.image_tag}"
  timeout       = 900
  memory_size   = 512

  image_config {
    command = ["src.worker_handler.handler"]
  }

  environment {
    variables = {
      DATABASE_URL_RW     = var.database_url_rw
      GITHUB_TOKEN        = var.github_token
      ANTHROPIC_API_KEY   = var.anthropic_api_key
      OPENAI_API_KEY      = var.openai_api_key
      EMBEDDING_PROVIDER  = var.embedding_provider
      LLM_MODEL           = var.llm_model
      LANGFUSE_PUBLIC_KEY = var.langfuse_public_key
      LANGFUSE_SECRET_KEY = var.langfuse_secret_key
      LANGFUSE_BASE_URL   = var.langfuse_base_url
    }
  }
}

resource "aws_lambda_event_source_mapping" "webhook_worker" {
  event_source_arn = aws_sqs_queue.webhook_events.arn
  function_name    = aws_lambda_function.worker.arn
  batch_size       = 1
}

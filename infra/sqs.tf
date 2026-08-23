resource "aws_sqs_queue" "webhook_events_dlq" {
  name = "${var.service_name}-webhook-events-dlq"
}

resource "aws_sqs_queue" "webhook_events" {
  name = "${var.service_name}-webhook-events"

  # >= the worker Lambda's own timeout (infra/lambda.tf) so a message can't
  # become visible to a second receiver while the first is still processing it.
  visibility_timeout_seconds = 930

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.webhook_events_dlq.arn
    maxReceiveCount     = 3
  })
}

# API Lambda: enqueue only.
resource "aws_iam_role_policy" "webhook_events_send" {
  name = "${var.service_name}-webhook-events-send"
  role = aws_iam_role.lambda_exec.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "sqs:SendMessage"
      Resource = aws_sqs_queue.webhook_events.arn
    }]
  })
}

# Worker Lambda: poll and consume.
resource "aws_iam_role" "worker_lambda_exec" {
  name = "${var.service_name}-worker-lambda-exec"

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

resource "aws_iam_role_policy_attachment" "worker_lambda_basic_execution" {
  role       = aws_iam_role.worker_lambda_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "webhook_events_consume" {
  name = "${var.service_name}-webhook-events-consume"
  role = aws_iam_role.worker_lambda_exec.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "sqs:ReceiveMessage",
        "sqs:DeleteMessage",
        "sqs:GetQueueAttributes",
      ]
      Resource = aws_sqs_queue.webhook_events.arn
    }]
  })
}

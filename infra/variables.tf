variable "aws_region" {
  type    = string
  default = "eu-central-1"
}

variable "service_name" {
  type    = string
  default = "knowledgebase-service"
}

variable "image_tag" {
  description = "Docker image tag to deploy (e.g. the git SHA)."
  type        = string
}

# Repos to attach the GitHub webhook to. deploy.yml/terraform-plan.yml compute
# this dynamically (every non-fork repo on the account, via `gh repo list`) and
# pass it as -var; the default here only applies to a manual/local apply.
variable "github_webhook_repos" {
  type    = list(string)
  default = ["knowledgebase-service"]
}

variable "github_token" {
  description = "Used by the github provider (webhook management) and passed to the Lambda as GITHUB_TOKEN."
  type        = string
  sensitive   = true
}

variable "github_webhook_secret" {
  type      = string
  sensitive = true
}

variable "database_url_rw" {
  type      = string
  sensitive = true
}

variable "database_url_ro" {
  type      = string
  sensitive = true
}

variable "anthropic_api_key" {
  type      = string
  sensitive = true
}

variable "openai_api_key" {
  type      = string
  sensitive = true
}

variable "api_auth_key" {
  type      = string
  sensitive = true
}

variable "embedding_provider" {
  type    = string
  default = "openai"
}

variable "llm_model" {
  type    = string
  default = "claude-haiku-4-5-20251001"
}

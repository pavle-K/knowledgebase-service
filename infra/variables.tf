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

variable "database_url_ro_public" {
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

# Public tier: reads public projects only. api_admin_key reads everything.
variable "api_auth_key" {
  type      = string
  sensitive = true
}

variable "api_admin_key" {
  type      = string
  sensitive = true
}

# Optional: LLM usage/cost/tracing. src.query.synthesizer.get_langfuse_client()
# treats an empty value as "not configured" and no-ops - observability must
# never become a hard requirement to run this service.
variable "langfuse_public_key" {
  type      = string
  sensitive = true
  default   = ""
}

variable "langfuse_secret_key" {
  type      = string
  sensitive = true
  default   = ""
}

# Defaults to the EU Langfuse Cloud region when empty - only needed if the
# Langfuse project the keys above belong to is on the US region or self-hosted.
variable "langfuse_base_url" {
  type    = string
  default = ""
}

variable "embedding_provider" {
  type    = string
  default = "openai"
}

variable "llm_model" {
  type    = string
  default = "claude-haiku-4-5-20251001"
}

# Bounds embedding + LLM cost per /v1/query request - see src/api/schemas.py.
variable "max_query_length" {
  type    = string
  default = "2000"
}

# API Gateway throttle: global circuit breaker, not a per-key quota. Typed as
# string, not number - CI passes these as TF_VAR_* from a GitHub Actions
# variable, and an unset one becomes an empty string, which a number-typed
# variable would reject outright. api_gateway.tf falls back to the numeric
# defaults below when empty, via a local rather than the variable default.
variable "api_throttle_rate_limit" {
  type    = string
  default = "20"
}

variable "api_throttle_burst_limit" {
  type    = string
  default = "40"
}

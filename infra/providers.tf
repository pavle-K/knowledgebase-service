terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    github = {
      source  = "integrations/github"
      version = "~> 6.0"
    }
  }

  # Empty on purpose: bucket/key/region/dynamodb_table are supplied via
  # -backend-config flags at `terraform init` time (see .github/workflows),
  # because the bucket name includes the AWS account ID and backend blocks
  # can't reference variables. Bootstrapped by infra/bootstrap/.
  backend "s3" {}
}

provider "aws" {
  region = var.aws_region
}

provider "github" {
  token = var.github_token
}

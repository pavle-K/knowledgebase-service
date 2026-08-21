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

  # Local state deliberately, for now - no remote backend until everything
  # above this stage works.
}

provider "aws" {
  region = var.aws_region
}

provider "github" {
  token = var.github_token
}

terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Deliberately local state. This config creates the S3 bucket + DynamoDB
  # table that the main infra/ config uses as ITS remote backend - it can't
  # use that same backend for itself (a backend can't depend on a resource
  # from the config it backs). It manages exactly two resources that are
  # created once and essentially never change, so local state here is fine.
}

provider "aws" {
  region = var.aws_region
}

terraform {
  required_version = ">= 1.10.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # Shared with guppy-monorepo/deploy/terraform/cognito (same account, own key).
  # S3-native locking (use_lockfile) needs no DynamoDB lock table.
  backend "s3" {
    bucket       = "guppy-terraform-state"
    key          = "algodooonline/terraform.tfstate"
    region       = "ap-northeast-1"
    encrypt      = true
    use_lockfile = true
  }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project   = "algodooonline"
      ManagedBy = "terraform"
    }
  }
}

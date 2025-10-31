terraform {
  required_version = ">= 1.5.0"
  backend "s3" {
    bucket         = "agroai-tfstate-ld-usw1-1761768239"
    key            = "state/lamine-github-io.tfstate"
    region         = "us-west-1"
    dynamodb_table = "tf-locks"
    encrypt        = true
  }
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.60"
    }
  }
}

provider "aws" {
  region = var.region
}

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  backend "s3" {
    bucket = "agroai-tfstate-ld-usw1-1761768239"
    key    = "agroai-pilot/us-west-1/terraform.tfstate"
    region = "us-west-1"
    # dynamodb_table = "terraform-locks" # only if you actually have this table
    encrypt = true
  }
}

provider "aws" {
  region = "us-west-1"
}

locals {
  tags = {
    Project   = var.project
    ManagedBy = "terraform"
  }
}

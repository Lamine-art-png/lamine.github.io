terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  backend "s3" {
    # TODO: fill in:
    # bucket = "your-tf-state-bucket"
    # key    = "agroai-pilot/us-west-1/terraform.tfstate"
    # region = "us-west-1"
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

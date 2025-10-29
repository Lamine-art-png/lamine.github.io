terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws    = { source = "hashicorp/aws", version = "~> 5.0" }
    random = { source = "hashicorp/random", version = "~> 3.6" }
  }
  backend "s3" {
    bucket         = "<agroai-tfstate-ld-20251028-ncal>"  # exact name from CloudShell
    key            = "manulife-pilot/terraform.tfstate"
    region         = "us-west-1"
    dynamodb_table = "tf-locks"
    encrypt        = true
  }
}

provider "aws" { region = var.region }


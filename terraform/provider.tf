terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
    random = { source = "hashicorp/random", version = "~> 3.6" }
  }

  backend "s3" {
    bucket         = "<YOUR-US-WEST-1-BUCKET>"   # EXACT bucket you created
    key            = "manulife-pilot/terraform.tfstate"
    region         = "us-west-1"
    dynamodb_table = "tf-locks"
    encrypt        = true
  }
}

provider "aws" {
  region = var.region
}

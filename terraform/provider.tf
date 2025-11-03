provider "aws" {
  region = var.region
}

terraform {
  backend "s3" {
    bucket         = "agroai-tfstate-ld-usw1-1761768239"  # your bucket
    key            = "state/lamine-github-io.tfstate"
    region         = "us-west-1"
    dynamodb_table = "tf-locks"
    encrypt        = true
  }
}

terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws    = { source = "hashicorp/aws", version = "~> 5.0" }
    random = { source = "hashicorp/random", version = "~> 3.6" }
  }
 terraform {
  backend "s3" {
    bucket         = "<EXACT_BUCKET_NAME_IN_US-WEST-1>"   # if you created NEW_BUCKET, put it here
    key            = "manulife-pilot/terraform.tfstate"
    region         = "us-west-1"
    dynamodb_table = "tf-locks"
    encrypt        = true
  }
}
provider "aws" { region = var.region }


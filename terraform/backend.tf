terraform {
  backend "s3" {
    bucket         = "agroai-tfstate-ld-usw1-1761768239"
    key            = "manulife-pilot/terraform.tfstate"
    region         = "us-west-1"
    dynamodb_table = "agroai-tf-locks"
    encrypt        = true
  }
}

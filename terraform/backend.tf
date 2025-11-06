terraform {
  backend "s3" {
    bucket  = "agroai-tfstate-ld-usw1-1761768239" # existing bucket in us-west-1
    key     = "lamine.github.io/terraform.tfstate"
    region  = "us-west-1"
    encrypt = true
  }
}

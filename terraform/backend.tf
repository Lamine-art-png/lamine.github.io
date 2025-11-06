terraform {
  backend "s3" {
    bucket = "agroai-tfstate-ld-usw1-1761768239" # use one of your existing us-west-1 buckets
    key    = "lamine.github.io/terraform.tfstate"
    region = "us-west-1"
    encrypt = true
  }
}

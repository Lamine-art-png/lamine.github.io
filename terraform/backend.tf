terraform {
  backend "s3" {
    bucket         = "agroai-tfstate-ld-usw1-1761768239"
    key            = "lamine.github.io/terraform.tfstate"
    region         = "us-west-1"
    encrypt        = true
    # dynamodb_table = "tf-locks-agroai"  # add only if you created this table
  }
}

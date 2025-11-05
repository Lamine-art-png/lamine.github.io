terraform {
  backend "s3" {
    bucket = "YOUR_STATE_BUCKET"
    key    = "agroai-manulife/usw2/terraform.tfstate"   # <- new path
    region = "us-west-2"
  }
}

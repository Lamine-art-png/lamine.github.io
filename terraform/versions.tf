terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
  }

  # ⬇⬇ Keep these values the same as the backend you already use
  backend "s3" {
    bucket         = "agroai-tfstate-ld-usw1-1761768239"   # <-- your bucket
    key            = "manulife-pilot/terraform.tfstate"     # <-- your key
    region         = "us-west-1"
    dynamodb_table = "agroai-tf-locks"                      # <-- your lock table
    encrypt        = true
  }
}

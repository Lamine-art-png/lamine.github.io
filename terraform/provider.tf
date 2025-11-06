variable "region" {
  description = "AWS region"
  type        = string
  default     = "us-west-1"
}

provider "aws" {
  region = var.region
}

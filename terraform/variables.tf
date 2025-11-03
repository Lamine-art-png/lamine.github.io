variable "project" {
  description = "Name/prefix for tags and resources"
  type        = string
  default     = "agroai-manulife-pilot"
}

variable "aws_region" {
  type    = string
  default = "us-west-1"
}

variable "container_image" {
  type    = string
  default = "<YOUR_ECR_REPO_URL>:latest"
  # e.g. 292039821285.dkr.ecr.us-west-1.amazonaws.com/agroai-manulife-pilot-api:latest
}

variable "health_check_path" {
  type    = string
  default = "/"
}


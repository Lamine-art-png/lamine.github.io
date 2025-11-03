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
  # point to your ECR image (must exist and be public to the ECS task via the exec role)
  default = "292039821285.dkr.ecr.us-west-1.amazonaws.com/agroai-manulife-pilot-api"
  # e.g. "292039821285.dkr.ecr.us-west-1.amazonaws.com/agroai-manulife-pilot-api:latest"
}

variable "health_check_path" {
  type    = string
  default = "/"
}


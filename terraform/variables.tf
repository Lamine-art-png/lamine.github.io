variable "project" {
  description = "Name/prefix for tags and resources"
  type        = string
  default     = "agroai-manulife-pilot"
}

variable "aws_region" {
  type    = string
  default = "us-west-1"
}

# ECR repository URL WITHOUT a tag. We'll append :latest in main.tf
variable "container_image" {
  description = "ECR repo URL (no tag)"
  type        = string
  default     = "292039821285.dkr.ecr.us-west-1.amazonaws.com/agroai-manulife-pilot-api"
}

variable "health_check_path" {
  type    = string
  default = "/"
}

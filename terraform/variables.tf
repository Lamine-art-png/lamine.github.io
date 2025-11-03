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
  # Keep nginx for now; replace with your ECR URI when ready
  default = "public.ecr.aws/nginx/nginx:stable-alpine"
}

variable "health_check_path" {
  type    = string
  default = "/"
}

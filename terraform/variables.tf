variable "project" {
  description = "Name/prefix for tags and resources"
  type        = string
  default     = "agroai-manulife-pilot"
}

variable "aws_region" {
  type    = string
  default = "us-west-1"
}

# IMPORTANT: repository URL ONLY (no :tag). The workflows use :latest.
variable "container_image" {
  type    = string
  default = "292039821285.dkr.ecr.us-west-1.amazonaws.com/agroai-manulife-pilot-api"
}

# Match the app's /health endpoint
variable "health_check_path" {
  type    = string
  default = "/health"
}

variable "project" {
  description = "Name/prefix for tags and resources"
  type        = string
  default     = "agroai-manulife-pilot"
}

variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-west-1"
}

variable "health_check_path" {
  description = "Path the container must return 200 on"
  type        = string
  default     = "/health"
}

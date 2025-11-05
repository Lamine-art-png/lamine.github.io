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

# Change this to 8000/8080 if your app uses that port
variable "container_port" {
  description = "Container/app listening port"
  type        = number
  default     = 80
}

# Path used by the health check
variable "health_check_path" {
  description = "HTTP path for container health check"
  type        = string
  default     = "/"
}
